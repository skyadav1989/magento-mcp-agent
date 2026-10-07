# Magento MCP Gateway

Secure multi-tenant MCP gateway for a Magento backend.

## What it provides

- OAuth/JWT resource-server authentication.
- Tenant isolation: JWT `tenant_id` selects the Magento credential; the client never sees that credential.
- Dynamic MCP tool registry based on JWT `role`.
- `support_agent` -> `get_orders_by_status`
- `cms_admin` / `admin` -> `get_orders_by_status`, `update_product_description`
- Human approval gate for product-description updates.
- Strict limits: one SKU per update and configurable description length.
- Streamable HTTP at `/mcp`.
- Render-ready deployment.

The current MCP Python SDK recommends Streamable HTTP for deployed servers; legacy SSE is retained by the SDK for older clients but is not used for this new project.

## Project structure

```text
app/
  config.py       # environment configuration
  security.py     # JWT/JWKS validation
  rbac.py         # role -> tool policy
  magento.py      # tenant-scoped Magento REST client
  approvals.py    # in-memory approval workflow
  mcp_server.py   # dynamic MCP tools/list + tools/call
  main.py         # FastAPI + MCP transport + approval API
requirements.txt
render.yaml
.env.example
```

## JWT claims

Your OAuth provider should issue a JWT containing at least:

```json
{
  "sub": "user-123",
  "tenant_id": "okaya",
  "role": "cms_admin",
  "scope": "mcp"
}
```

Do not put Magento REST tokens in the JWT.

## Local run

1. Copy `.env.example` to `.env`.
2. For local-only testing, use `DEV_JWT_SECRET` and `JWT_ALGORITHMS=HS256`, and set `OAUTH_ISSUER_URL` to a matching test issuer. Leave `JWT_JWKS_URL` empty.
3. Put your real Magento token only in `TENANTS_JSON` as an environment secret.
4. Run:

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

For local MCP, use `http://localhost:8000/mcp` as the resource URL and configure the allowed host/origin for localhost, or temporarily disable transport DNS protection only for local development.

## Approval flow

When `REQUIRE_PRODUCT_UPDATE_APPROVAL=true`, `update_product_description` first returns an approval request instead of modifying Magento.

A trusted human/admin UI calls:

```http
POST /approvals/{approval_id}/approve
```

Then the MCP client retries the exact same update with `approval_id`.

For production, replace the in-memory approval store with Redis/PostgreSQL so approvals survive restarts and work across multiple Render instances.

## Render

Create a Render Web Service from this repository. The included `render.yaml` configures:

```text
Build:  pip install -r requirements.txt
Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set the secret environment variables in Render. Never commit `.env` or a real Magento token.

After deployment:

```text
https://YOUR-SERVICE.onrender.com/health
https://YOUR-SERVICE.onrender.com/mcp
```

## Important production notes

- Use an external OAuth/OIDC provider and JWKS; do not use `DEV_JWT_SECRET` in production.
- Give the Magento integration token only the Magento ACL permissions required by these tools.
- Use a dedicated Magento integration token per tenant/store where possible.
- Keep approval state in Redis/PostgreSQL for multi-instance deployments.
- Put the approval endpoint behind your admin authentication before production use.
- Add audit logging with tenant, subject, tool, SKU, and result status, but never log bearer tokens or Magento credentials.
- Pin dependencies and review updates before changing the SDK version.
