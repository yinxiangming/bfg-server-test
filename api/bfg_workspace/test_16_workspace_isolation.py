"""
API integration test 16: Workspace Isolation
Test that users from one workspace cannot access data from another workspace.
Pure API mode: client1=admin_client (ws1), client2=admin_client2 (ws2).
"""

import uuid
import pytest
from types import SimpleNamespace


def _results(response):
    if isinstance(response.data, list):
        return response.data
    return response.data.get('results', [])


def _collection_count(response):
    if isinstance(response.data, dict) and 'count' in response.data:
        return response.data['count']
    return len(_results(response))


def _setup_workspace_data(client, workspace, customer):
    """Create warehouse, store, category, product, address, order via API. Return SimpleNamespace dict. Use unique codes to avoid duplicate key."""
    suf = uuid.uuid4().hex[:6]
    # Address
    addr = client.post("/api/v1/addresses/", {
        "customer_id": customer.id,
        "full_name": "Test User", "phone": "1234567890",
        "address_line1": "123 St", "city": "City", "country": "US", "postal_code": "12345",
    })
    assert addr.status_code == 201, addr.data
    address_id = addr.data["id"]

    # Warehouse
    wh = client.post("/api/v1/delivery/warehouses/", {"name": f"WH-{suf}", "code": f"WH-001-{suf}"})
    assert wh.status_code == 201, wh.data
    warehouse_id = wh.data["id"]

    # Store
    store = client.post("/api/v1/shop/stores/", {
        "name": f"Store-{suf}", "code": f"ST-001-{suf}", "warehouse_ids": [warehouse_id],
    })
    assert store.status_code == 201, store.data
    store_id = store.data["id"]

    # Category and product
    cat = client.post("/api/v1/shop/categories/", {
        "name": f"Category-{suf}", "slug": f"category-{suf}", "language": "en", "is_active": True,
    })
    assert cat.status_code == 201, cat.data
    prod = client.post("/api/v1/shop/admin/products/", {
        "name": f"Product-{suf}", "slug": f"product-{suf}", "sku": f"PROD-001-{suf}", "price": "100.00",
        "category_ids": [cat.data["id"]], "language": "en", "is_active": True,
    })
    assert prod.status_code == 201, prod.data
    product_id = prod.data["id"]

    # Order
    order = client.post("/api/v1/shop/orders/", {
        "customer_id": customer.id,
        "store_id": store_id,
        "shipping_address_id": address_id,
        "billing_address_id": address_id,
        "status": "pending",
        "payment_status": "pending",
    })
    assert order.status_code == 201, order.data
    order_id = order.data["id"]

    return {
        "customer": SimpleNamespace(id=customer.id),
        "address": SimpleNamespace(id=address_id),
        "warehouse": SimpleNamespace(id=warehouse_id),
        "store": SimpleNamespace(id=store_id, name=store.data.get("name")),
        "category": SimpleNamespace(id=cat.data["id"]),
        "product": SimpleNamespace(id=product_id, name=prod.data.get("name")),
        "order": SimpleNamespace(id=order_id),
    }


@pytest.mark.api_integration
class TestWorkspaceIsolation:
    """Test workspace data isolation via API."""

    @pytest.fixture
    def setup_workspace1_data(self, admin_client, workspace, customer):
        return _setup_workspace_data(admin_client, workspace, customer)

    @pytest.fixture
    def setup_workspace2_data(self, admin_client2, workspace2, customer2):
        return _setup_workspace_data(admin_client2, workspace2, customer2)

    def test_cannot_access_other_workspace_customers(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_customer = setup_workspace2_data["customer"]
        response = admin_client.get(f'/api/v1/customers/{workspace2_customer.id}/')
        assert response.status_code in [404, 403]

    def test_cannot_access_other_workspace_products(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_product = setup_workspace2_data["product"]
        response = admin_client.get(f'/api/v1/shop/admin/products/{workspace2_product.id}/')
        assert response.status_code == 404

    def test_cannot_access_other_workspace_orders(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_order = setup_workspace2_data["order"]
        response = admin_client.get(f'/api/v1/shop/orders/{workspace2_order.id}/')
        assert response.status_code == 404

    def test_cannot_access_other_workspace_addresses(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_address = setup_workspace2_data["address"]
        response = admin_client.get(f'/api/v1/addresses/{workspace2_address.id}/')
        assert response.status_code == 404

    def test_cannot_access_other_workspace_stores(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_store = setup_workspace2_data["store"]
        response = admin_client.get(f'/api/v1/shop/stores/{workspace2_store.id}/')
        assert response.status_code == 404

    def test_cannot_access_other_workspace_warehouses(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_warehouse = setup_workspace2_data["warehouse"]
        response = admin_client.get(f'/api/v1/delivery/warehouses/{workspace2_warehouse.id}/')
        assert response.status_code == 404

    def test_customer_list_only_shows_own_workspace(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        response = admin_client.get('/api/v1/customers/')
        assert response.status_code == 200
        data = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        customer_ids = [c['id'] for c in data]
        assert setup_workspace1_data['customer'].id in customer_ids
        assert setup_workspace2_data['customer'].id not in customer_ids

    def test_product_list_only_shows_own_workspace(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        response = admin_client.get('/api/v1/shop/admin/products/')
        assert response.status_code == 200
        data = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        product_ids = [p['id'] for p in data]
        assert setup_workspace1_data['product'].id in product_ids
        assert setup_workspace2_data['product'].id not in product_ids

    def test_order_list_only_shows_own_workspace(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        response = admin_client.get('/api/v1/shop/orders/')
        assert response.status_code == 200
        data = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        order_ids = [o['id'] for o in data]
        assert setup_workspace1_data['order'].id in order_ids
        assert setup_workspace2_data['order'].id not in order_ids

    def test_cannot_modify_other_workspace_product(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_product = setup_workspace2_data["product"]
        original_name = workspace2_product.name
        response = admin_client.patch(
            f'/api/v1/shop/admin/products/{workspace2_product.id}/',
            {'name': 'Hacked Product'}
        )
        assert response.status_code in [404, 403]
        # Verify via ws2 client that product was not modified
        get_res = admin_client2.get(f'/api/v1/shop/admin/products/{workspace2_product.id}/')
        assert get_res.status_code == 200
        assert get_res.data.get("name") != "Hacked Product"

    def test_cannot_delete_other_workspace_product(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_product = setup_workspace2_data["product"]
        product_id = workspace2_product.id
        response = admin_client.delete(f'/api/v1/shop/admin/products/{product_id}/')
        assert response.status_code in [404, 403]
        # Verify product still exists via ws2 client
        get_res = admin_client2.get(f'/api/v1/shop/admin/products/{product_id}/')
        assert get_res.status_code == 200

    def test_cannot_create_order_with_other_workspace_data(
        self, admin_client, admin_client2, setup_workspace1_data, setup_workspace2_data
    ):
        workspace2_customer = setup_workspace2_data["customer"]
        workspace2_store = setup_workspace2_data["store"]
        workspace2_address = setup_workspace2_data["address"]

        list_before = admin_client.get('/api/v1/shop/orders/')
        assert list_before.status_code == 200
        initial_count = _collection_count(list_before)

        response = admin_client.post('/api/v1/shop/orders/', {
            'customer_id': workspace2_customer.id,
            'store_id': workspace2_store.id,
            'shipping_address_id': workspace2_address.id,
            'billing_address_id': workspace2_address.id,
            'status': 'pending',
            'payment_status': 'pending',
        })
        assert response.status_code == 400, response.data

        list_after = admin_client.get('/api/v1/shop/orders/')
        assert list_after.status_code == 200
        final_count = _collection_count(list_after)
        assert final_count == initial_count, "No new order should be created with other workspace data"

    def test_non_admin_member_cannot_modify_or_delete_other_workspace(
        self,
        admin_client,
        admin_client2,
        workspace2,
        _session,
    ):
        """Admin rights in ws1 do not grant writes to a ws2 non-admin membership."""
        roles_res = admin_client2.get('/api/v1/staff-roles/')
        assert roles_res.status_code == 200, roles_res.data
        roles = _results(roles_res)
        non_admin = next((role for role in roles if role.get('code') != 'admin'), None)
        assert non_admin, f'No non-admin staff role available: {roles}'
        membership_res = admin_client2.post('/api/v1/staff-members/', {
            'user_id': _session['ws1']['admin_user_id'],
            'role_id': non_admin['id'],
        })
        assert membership_res.status_code in (200, 201), membership_res.data

        before = admin_client2.get(f'/api/v1/workspaces/{workspace2.id}/')
        assert before.status_code == 200, before.data
        original_name = before.data['name']

        patch_res = admin_client.patch(
            f'/api/v1/workspaces/{workspace2.id}/',
            {'name': 'E2E cross-tenant overwrite'},
        )
        assert patch_res.status_code == 403, patch_res.data
        delete_res = admin_client.delete(f'/api/v1/workspaces/{workspace2.id}/')
        assert delete_res.status_code == 403, delete_res.data

        after = admin_client2.get(f'/api/v1/workspaces/{workspace2.id}/')
        assert after.status_code == 200, after.data
        assert after.data['name'] == original_name

    def test_package_and_tracking_event_endpoints_are_tenant_scoped(
        self,
        admin_client,
        admin_client2,
        setup_workspace2_data,
    ):
        """Package and tracking-event list/detail/write operations stay in ws2."""
        ws2_order_id = setup_workspace2_data['order'].id
        suffix = uuid.uuid4().hex[:6]
        package_status = admin_client2.post('/api/v1/delivery/freight-statuses/', {
            'code': f'package-pending-{suffix}',
            'name': f'Package Pending {suffix}',
            'type': 'package',
            'state': 'PENDING',
            'is_active': True,
        })
        assert package_status.status_code == 201, package_status.data
        package = admin_client2.post('/api/v1/shop/order-packages/', {
            'order': ws2_order_id,
            'freight_status': package_status.data['id'],
            'weight': '1.00',
            'length': '10.00',
            'width': '10.00',
            'height': '10.00',
            'pieces': 1,
            'quantity': 1,
            'description': f'WS2 package {suffix}',
        })
        assert package.status_code == 201, package.data
        package_id = package.data['id']

        consignment_status = admin_client2.post('/api/v1/delivery/freight-statuses/', {
            'code': f'consignment-pending-{suffix}',
            'name': f'Consignment Pending {suffix}',
            'type': 'consignment',
            'state': 'PENDING',
            'is_active': True,
        })
        assert consignment_status.status_code == 201, consignment_status.data
        carrier = admin_client2.post('/api/v1/delivery/carriers/', {
            'name': f'WS2 Carrier {suffix}',
            'code': f'WS2-CR-{suffix}',
            'is_active': True,
        })
        assert carrier.status_code == 201, carrier.data
        service = admin_client2.post('/api/v1/delivery/freight-services/', {
            'carrier': carrier.data['id'],
            'name': f'WS2 Service {suffix}',
            'code': f'WS2-SVC-{suffix}',
            'base_price': '10.00',
            'price_per_kg': '1.00',
            'is_active': True,
        })
        assert service.status_code == 201, service.data
        sender = admin_client2.post('/api/v1/addresses/', {
            'full_name': 'WS2 Sender',
            'phone': '1234567890',
            'address_line1': '1 Sender Street',
            'city': 'Auckland',
            'country': 'NZ',
            'postal_code': '1010',
        })
        assert sender.status_code == 201, sender.data
        consignment = admin_client2.post('/api/v1/delivery/consignments/', {
            'order_ids': [ws2_order_id],
            'status_id': consignment_status.data['id'],
            'service_id': service.data['id'],
            'sender_address_id': sender.data['id'],
            'recipient_address_id': setup_workspace2_data['address'].id,
            'state': 'PENDING',
        })
        assert consignment.status_code == 201, consignment.data
        consignment_id = consignment.data.get('id')

        ws2_events_res = admin_client2.get('/api/v1/delivery/tracking-events/')
        assert ws2_events_res.status_code == 200, ws2_events_res.data
        ws2_events = _results(ws2_events_res)
        event = next(
            (
                item for item in ws2_events
                if item.get('target_type') == 'consignment'
                and item.get('target_id') == consignment_id
            ),
            None,
        )
        assert event, ws2_events
        event_id = event['id']

        ws1_packages_res = admin_client.get('/api/v1/delivery/packages/')
        assert ws1_packages_res.status_code == 200, ws1_packages_res.data
        assert package_id not in {item['id'] for item in _results(ws1_packages_res)}
        ws1_events_res = admin_client.get('/api/v1/delivery/tracking-events/')
        assert ws1_events_res.status_code == 200, ws1_events_res.data
        assert event_id not in {item['id'] for item in _results(ws1_events_res)}

        assert admin_client.get(f'/api/v1/delivery/packages/{package_id}/').status_code == 404
        assert admin_client.patch(
            f'/api/v1/delivery/packages/{package_id}/',
            {'description': 'cross-tenant overwrite'},
        ).status_code == 404
        assert admin_client.delete(f'/api/v1/delivery/packages/{package_id}/').status_code == 404
        assert admin_client.get(f'/api/v1/delivery/tracking-events/{event_id}/').status_code == 404
        assert admin_client.patch(
            f'/api/v1/delivery/tracking-events/{event_id}/',
            {'description': 'cross-tenant overwrite'},
        ).status_code == 404
        assert admin_client.delete(f'/api/v1/delivery/tracking-events/{event_id}/').status_code == 404

        package_after = admin_client2.get(f'/api/v1/delivery/packages/{package_id}/')
        assert package_after.status_code == 200, package_after.data
        assert package_after.data['description'] == f'WS2 package {suffix}'
        event_after = admin_client2.get(f'/api/v1/delivery/tracking-events/{event_id}/')
        assert event_after.status_code == 200, event_after.data
        assert event_after.data['description'] == event['description']
