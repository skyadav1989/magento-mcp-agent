from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    app_name: str = 'Magento MCP Gateway'
    app_version: str = '1.0.0'
    host: str = '0.0.0.0'
    port: int = 10000

    # Public MCP resource URL, e.g. https://your-service.onrender.com/mcp
    mcp_resource_url: str = 'http://localhost:8000/mcp'
    oauth_issuer_url: str = 'https://issuer.example.com'
    jwt_audience: str = ''
    jwt_jwks_url: str = ''
    jwt_algorithms: str = 'RS256'

    # Development-only fallback. Keep empty in production when JWKS is configured.
    dev_jwt_secret: str = ''

    # Tenant configuration. Example:
    # {"okaya":{"base_url":"https://shopdev.okaya.in","token":"<secret>"}}
    tenants_json: str = '{}'

    # Update protection
    require_product_update_approval: bool = True
    max_description_length: int = 5000
    approval_ttl_seconds: int = 600
    http_timeout_seconds: float = 30.0

    # CORS / transport security
    allowed_origins: str = ''
    allowed_hosts: str = ''


@lru_cache
def get_settings() -> Settings:
    return Settings()
