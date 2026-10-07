import json
import logging
import time
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from mcp.server.auth.provider import AccessToken, TokenVerifier

from .config import get_settings

logger = logging.getLogger(__name__)


class JWTVerifier(TokenVerifier):
    """Validates bearer JWTs and exposes tenant/RBAC claims to MCP."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._jwks: dict[str, Any] | None = None
        self._jwks_loaded_at = 0.0

    async def _load_jwks(self) -> dict[str, Any]:
        if self._jwks and time.time() - self._jwks_loaded_at < 600:
            return self._jwks

        if not self.settings.jwt_jwks_url:
            return {}

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(self.settings.jwt_jwks_url)
            response.raise_for_status()

            self._jwks = response.json()
            self._jwks_loaded_at = time.time()

            return self._jwks

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            header = jwt.get_unverified_header(token)

            algorithm = header.get("alg")

            allowed_algorithms = [
                x.strip()
                for x in self.settings.jwt_algorithms.split(",")
                if x.strip()
            ]

            if algorithm not in allowed_algorithms:
                logger.warning(
                    "JWT rejected: algorithm=%s allowed=%s",
                    algorithm,
                    allowed_algorithms,
                )
                return None

            # Development / local HS256 authentication.
            if self.settings.dev_jwt_secret and not self.settings.jwt_jwks_url:
                key = self.settings.dev_jwt_secret

            # Production OAuth/OIDC authentication.
            else:
                jwks = await self._load_jwks()

                jwk = next(
                    (
                        k
                        for k in jwks.get("keys", [])
                        if k.get("kid") == header.get("kid")
                    ),
                    None,
                )

                if not jwk:
                    logger.warning(
                        "JWT rejected: kid=%s not found in JWKS",
                        header.get("kid"),
                    )
                    return None

                key = RSAAlgorithm.from_jwk(json.dumps(jwk))

            options = {
                "verify_aud": bool(self.settings.jwt_audience),
                "verify_iss": bool(self.settings.oauth_issuer_url),
            }

            claims = jwt.decode(
                token,
                key,
                algorithms=allowed_algorithms,
                audience=self.settings.jwt_audience or None,
                issuer=self.settings.oauth_issuer_url or None,
                options=options,
            )

            tenant_id = claims.get("tenant_id") or claims.get("tenant")

            if not tenant_id:
                logger.warning("JWT rejected: tenant_id missing")
                return None

            role = claims.get("role", "support_agent")

            scopes = claims.get("scope", "")

            if isinstance(scopes, str):
                scopes = scopes.split()
            elif not isinstance(scopes, list):
                scopes = []

            enriched = dict(claims)
            enriched["tenant_id"] = tenant_id
            enriched["role"] = role

            return AccessToken(
                token=token,
                client_id=str(
                    claims.get(
                        "client_id",
                        claims.get("azp", "mcp-client"),
                    )
                ),
                scopes=scopes,
                expires_at=claims.get("exp"),
                issuer=claims.get("iss"),
                subject=claims.get("sub"),
                resource=self.settings.mcp_resource_url,
                claims=enriched,
            )

        except jwt.ExpiredSignatureError:
            logger.warning("JWT rejected: token expired")
            return None

        except jwt.InvalidIssuerError:
            logger.warning(
                "JWT rejected: invalid issuer. expected=%s",
                self.settings.oauth_issuer_url,
            )
            return None

        except jwt.InvalidAudienceError:
            logger.warning("JWT rejected: invalid audience")
            return None

        except jwt.InvalidSignatureError:
            logger.warning("JWT rejected: invalid signature")
            return None

        except jwt.PyJWTError as exc:
            logger.warning("JWT rejected: %s", exc)
            return None

        except Exception:
            logger.exception("Unexpected JWT verification error")
            return None