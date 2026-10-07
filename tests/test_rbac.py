from app.rbac import allowed_tools, can_use


def test_support_agent_only_orders():
    assert allowed_tools('support_agent') == {'get_orders_by_status'}
    assert can_use('support_agent', 'get_orders_by_status')
    assert not can_use('support_agent', 'update_product_description')


def test_cms_admin_can_update():
    assert can_use('cms_admin', 'update_product_description')
