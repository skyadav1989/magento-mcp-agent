import json
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from .config import get_settings


@dataclass(frozen=True)
class TenantConfig:
    base_url: str
    token: str


class TenantRegistry:
    def __init__(self) -> None:
        raw = json.loads(get_settings().tenants_json or '{}')
        self._tenants = {
            tenant_id: TenantConfig(
                base_url=value['base_url'].rstrip('/'),
                token=value['token'],
            )
            for tenant_id, value in raw.items()
        }

    def get(self, tenant_id: str) -> TenantConfig:
        config = self._tenants.get(tenant_id)
        if not config:
            raise PermissionError('Unknown tenant')
        return config


class MagentoClient:
    def __init__(self, config: TenantConfig) -> None:
        self.config = config
        self.timeout = get_settings().http_timeout_seconds

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.timeout,
            headers={
                'Authorization': f'Bearer {self.config.token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            },
        )

    async def get_orders_by_status(self, status: str, page_size: int = 20) -> dict:
        page_size = min(max(page_size, 1), 100)
        params = {
            'searchCriteria[filter_groups][0][filters][0][field]': 'status',
            'searchCriteria[filter_groups][0][filters][0][value]': status,
            'searchCriteria[filter_groups][0][filters][0][condition_type]': 'eq',
            'searchCriteria[pageSize]': page_size,
            'searchCriteria[currentPage]': 1,
        }
        async with self._client() as client:
            response = await client.get('/rest/V1/orders', params=params)
            response.raise_for_status()
            data = response.json()
        return {
            'total_count': data.get('total_count', 0),
            'orders': [
                {
                    'entity_id': item.get('entity_id'),
                    'increment_id': item.get('increment_id'),
                    'status': item.get('status'),
                    'state': item.get('state'),
                    'grand_total': item.get('grand_total'),
                    'created_at': item.get('created_at'),
                    'customer_email': item.get('customer_email'),
                }
                for item in data.get('items', [])
            ],
        }

    async def update_product_description(self, sku: str, description: str) -> dict:
        encoded_sku = quote(sku, safe='')
        payload = {
            'product': {
                'sku': sku,
                'custom_attributes': [
                    {'attribute_code': 'description', 'value': description}
                ],
            }
        }
        async with self._client() as client:
            response = await client.put(f'/rest/V1/products/{encoded_sku}', json=payload)
            response.raise_for_status()
            data = response.json()
        return {
            'sku': data.get('sku', sku),
            'name': data.get('name'),
            'status': data.get('status'),
            'message': 'Product description updated successfully',
        }
