from mcp.server import Server, ServerRequestContext
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, TextContent, Tool

from .approvals import ApprovalStore
from .config import get_settings
from .magento import MagentoClient, TenantRegistry
from .rbac import allowed_tools, can_use, tenant_and_role


TOOL_DEFINITIONS = {
    'get_orders_by_status': Tool(
        name='get_orders_by_status',
        description='List Magento orders for the authenticated tenant filtered by order status.',
        input_schema={
            'type': 'object',
            'properties': {
                'status': {'type': 'string', 'description': 'Magento order status, e.g. processing or complete.'},
                'page_size': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 20},
            },
            'required': ['status'],
        },
    ),
    'update_product_description': Tool(
        name='update_product_description',
        description='Update the Magento product description for one SKU. Requires approval when configured.',
        input_schema={
            'type': 'object',
            'properties': {
                'sku': {'type': 'string', 'minLength': 1, 'maxLength': 128},
                'description': {'type': 'string', 'minLength': 1, 'maxLength': 5000},
                'approval_id': {'type': 'string', 'description': 'Approved ID from the approval endpoint.'},
            },
            'required': ['sku', 'description'],
        },
    ),
}


def build_server(token_verifier: TokenVerifier, approvals: ApprovalStore) -> Server:
    tenants = TenantRegistry()
    settings = get_settings()

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        token = get_access_token()
        _, role = tenant_and_role(token)
        names = allowed_tools(role or '')
        return ListToolsResult(tools=[TOOL_DEFINITIONS[name] for name in TOOL_DEFINITIONS if name in names])

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        token = get_access_token()
        tenant_id, role = tenant_and_role(token)
        if not token or not tenant_id or not can_use(role or '', params.name):
            return CallToolResult(content=[TextContent(type='text', text='Tool not permitted')], is_error=True)

        args = params.arguments or {}
        try:
            client = MagentoClient(tenants.get(tenant_id))

            if params.name == 'get_orders_by_status':
                status = str(args.get('status', '')).strip()
                if not status or len(status) > 64:
                    raise ValueError('Invalid status')
                page_size = int(args.get('page_size', 20))
                result = await client.get_orders_by_status(status, page_size)

            elif params.name == 'update_product_description':
                sku = str(args.get('sku', '')).strip()
                description = str(args.get('description', ''))
                if not sku:
                    raise ValueError('SKU is required')
                if len(description) > settings.max_description_length:
                    raise ValueError(f'Description exceeds {settings.max_description_length} characters')

                clean_params = {'sku': sku, 'description': description}
                approval_id = args.get('approval_id')
                if settings.require_product_update_approval:
                    if not approval_id or not approvals.consume(
                        str(approval_id), tenant_id, token.subject, params.name, clean_params
                    ):
                        approval = approvals.create(tenant_id, token.subject, params.name, clean_params)
                        result = {
                            'approval_required': True,
                            'approval_id': approval.approval_id,
                            'expires_at': approval.expires_at,
                            'message': 'Human approval required. Approve this request through POST /approvals/{approval_id}/approve, then retry with approval_id.',
                        }
                        return CallToolResult(
                            content=[TextContent(type='text', text=str(result))],
                            is_error=False,
                        )
                result = await client.update_product_description(sku, description)
            else:
                raise ValueError('Unknown tool')

            return CallToolResult(content=[TextContent(type='text', text=str(result))], is_error=False)
        except Exception as exc:
            return CallToolResult(content=[TextContent(type='text', text=f'Operation failed: {exc}')], is_error=True)

    # The v2 low-level Server is used intentionally: tools/list is evaluated per
    # request, so the registry is truly dynamic for the authenticated role.
    return Server(
        'Magento MCP Gateway',
        version=settings.app_version,
        description='Secure multi-tenant MCP gateway for Magento.',
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
