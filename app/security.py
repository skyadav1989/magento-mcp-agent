import json
import time
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from mcp.server.auth.provider import AccessToken, TokenVerifier

from .config import get_settings


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
            algorithm = header.get('alg')
            if algorithm not in [x.strip() for x in self.settings.jwt_algorithms.split(',') if x.strip()]:
                return None

            if self.settings.dev_jwt_secret and not self.settings.jwt_jwks_url:
                key = self.settings.dev_jwt_secret
            else:
                jwks = await self._load_jwks()
                jwk = next((k for k in jwks.get('keys', []) if k.get('kid') == header.get('kid')), None)
                if not jwk:
                    return None
                key = RSAAlgorithm.from_jwk(json.dumps(jwk))

            options = {'verify_aud': bool(self.settings.jwt_audience)}
            claims = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=self.settings.jwt_audience or None,
                issuer=self.settings.oauth_issuer_url or None,
                options=options,
            )

            tenant_id = claims.get('tenant_id') or claims.get('tenant')
            role = claims.get('role', 'support_agent')
            if not tenant_id:
                return None

            scopes = claims.get('scope', '')
            if isinstance(scopes, str):
                scopes = scopes.split()
            elif not isinstance(scopes, list):
                scopes = []

            # Claims are safe metadata for authorization decisions. Never put
            # Magento secrets into JWT claims or MCP responses.
            enriched = dict(claims)
            enriched['tenant_id'] = tenant_id
            enriched['role'] = role

            return AccessToken(
                token=token,
                client_id=str(claims.get('client_id', claims.get('azp', 'mcp-client'))),
                scopes=scopes,
                expires_at=claims.get('exp'),
                issuer=claims.get('iss'),
                subject=claims.get('sub'),
                resource=self.settings.mcp_resource_url,
                claims=enriched,
            )
        except Exception:
            return None
