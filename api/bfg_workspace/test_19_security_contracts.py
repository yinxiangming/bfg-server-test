"""End-to-end security contracts for previously reported BFG regressions."""

import uuid
from decimal import Decimal

import pytest

from client_remote import RemoteAPIClient


def _results(response):
    if isinstance(response.data, list):
        return response.data
    return response.data.get('results', [])


def _count(response):
    if isinstance(response.data, dict) and 'count' in response.data:
        return response.data['count']
    return len(_results(response))


def _create_product(admin_client, price='100.00'):
    suffix = uuid.uuid4().hex[:8]
    category = admin_client.post('/api/v1/shop/categories/', {
        'name': f'Security Category {suffix}',
        'slug': f'security-category-{suffix}',
        'language': 'en',
        'is_active': True,
    })
    assert category.status_code == 201, category.data
    product = admin_client.post('/api/v1/shop/admin/products/', {
        'name': f'Security Product {suffix}',
        'slug': f'security-product-{suffix}',
        'sku': f'SEC-{suffix}'.upper(),
        'price': price,
        'category_ids': [category.data['id']],
        'language': 'en',
        'is_active': True,
        'track_inventory': False,
    })
    assert product.status_code == 201, product.data
    return product.data


@pytest.mark.api_integration
class TestSecurityContracts:
    def test_guest_checkout_rejects_existing_email_without_side_effects(
        self,
        workspace,
        admin_client,
        customer_client,
        store,
    ):
        """Anonymous checkout cannot bind an order to an existing account by email."""
        me_res = customer_client.get('/api/v1/me/')
        assert me_res.status_code == 200, me_res.data
        existing_email = me_res.data['email']
        product = _create_product(admin_client)

        guest = RemoteAPIClient(workspace=workspace, token=None, persist_cookies=False)
        cart_res = guest.get('/api/v1/store/cart/current/')
        assert cart_res.status_code == 200, cart_res.data
        add_res = guest.post('/api/v1/store/cart/add_item/', {
            'product': product['id'],
            'quantity': 1,
        })
        assert add_res.status_code == 200, add_res.data
        assert Decimal(str(add_res.data['total'])) == Decimal('100.00')

        customers_before = admin_client.get('/api/v1/customers/')
        orders_before = admin_client.get('/api/v1/shop/orders/')
        assert customers_before.status_code == 200, customers_before.data
        assert orders_before.status_code == 200, orders_before.data

        checkout_res = guest.post('/api/v1/store/cart/guest_checkout/', {
            'store': store.id,
            'email': existing_email,
            'full_name': 'Impersonated Customer',
            'phone': '1234567890',
            'shipping_address': {
                'full_name': 'Impersonated Customer',
                'email': existing_email,
                'phone': '1234567890',
                'address_line1': '1 Security Street',
                'city': 'Auckland',
                'country': 'NZ',
                'postal_code': '1010',
            },
        })
        assert checkout_res.status_code == 409, checkout_res.data
        assert 'sign in' in str(checkout_res.data).lower()

        customers_after = admin_client.get('/api/v1/customers/')
        orders_after = admin_client.get('/api/v1/shop/orders/')
        assert customers_after.status_code == 200, customers_after.data
        assert orders_after.status_code == 200, orders_after.data
        assert _count(customers_after) == _count(customers_before)
        assert _count(orders_after) == _count(orders_before)
        cart_after = guest.get('/api/v1/store/cart/current/')
        assert cart_after.status_code == 200, cart_after.data
        assert len(cart_after.data['items']) == 1

    def test_checkout_rejects_another_customer_address_without_order(
        self,
        admin_client,
        customer_client,
        other_user_client,
        store,
    ):
        """A same-workspace customer cannot checkout with another customer's address."""
        product = _create_product(admin_client)
        other_address = other_user_client.post('/api/v1/me/addresses/', {
            'full_name': 'Other Customer',
            'phone': '1234567890',
            'address_line1': '2 Private Street',
            'city': 'Auckland',
            'country': 'NZ',
            'postal_code': '1010',
        })
        assert other_address.status_code == 201, other_address.data
        cart_res = customer_client.post('/api/v1/shop/carts/', {})
        assert cart_res.status_code == 201, cart_res.data
        add_res = customer_client.post(
            '/api/v1/shop/carts/add_item/',
            {'product': product['id'], 'quantity': 1},
            HTTP_X_CART_ID=str(cart_res.data['id']),
        )
        assert add_res.status_code == 200, add_res.data
        before = customer_client.get('/api/v1/store/orders/')
        assert before.status_code == 200, before.data

        checkout_res = customer_client.post(
            '/api/v1/shop/carts/checkout/',
            {
                'store': store.id,
                'shipping_address': other_address.data['id'],
            },
            HTTP_X_CART_ID=str(cart_res.data['id']),
        )
        assert checkout_res.status_code == 400, checkout_res.data
        assert checkout_res.data == {
            'shipping_address': 'Address does not belong to this customer.',
        }
        after = customer_client.get('/api/v1/store/orders/')
        assert after.status_code == 200, after.data
        assert _count(after) == _count(before)

    def test_variant_must_belong_to_product_and_cart_stays_empty(
        self,
        admin_client,
        customer_client,
    ):
        """A cheap variant from another product cannot price an expensive product."""
        expensive = _create_product(admin_client, price='100.00')
        cheap = _create_product(admin_client, price='0.01')
        suffix = uuid.uuid4().hex[:8]
        cheap_variant = admin_client.post('/api/v1/shop/variants/', {
            'product': cheap['id'],
            'sku': f'CHEAP-{suffix}'.upper(),
            'name': 'Cheap Variant',
            'price': '0.01',
            'stock_quantity': 100,
        })
        assert cheap_variant.status_code == 201, cheap_variant.data
        cart = customer_client.post('/api/v1/shop/carts/', {})
        assert cart.status_code == 201, cart.data

        add_res = customer_client.post(
            '/api/v1/shop/carts/add_item/',
            {
                'product': expensive['id'],
                'variant': cheap_variant.data['id'],
                'quantity': 1,
            },
            HTTP_X_CART_ID=str(cart.data['id']),
        )
        assert add_res.status_code == 404, add_res.data
        assert add_res.data == {'detail': 'Product variant not found'}
        current = customer_client.get(
            '/api/v1/store/cart/current/',
            HTTP_X_CART_ID=str(cart.data['id']),
        )
        assert current.status_code == 200, current.data
        assert current.data['items'] == []
        assert Decimal(str(current.data['total'])) == Decimal('0.00')

    def test_me_cannot_mass_assign_login_identity(self, customer_client):
        """Profile updates cannot change the login email or username."""
        before = customer_client.get('/api/v1/me/')
        assert before.status_code == 200, before.data
        marker = uuid.uuid4().hex[:8]
        update = customer_client.patch('/api/v1/me/', {
            'email': f'attacker-{marker}@example.test',
            'username': f'attacker-{marker}',
            'first_name': f'Updated-{marker}',
        })
        assert update.status_code == 200, update.data
        after = customer_client.get('/api/v1/me/')
        assert after.status_code == 200, after.data
        assert after.data['email'] == before.data['email']
        assert after.data['username'] == before.data['username']
        assert after.data['first_name'] == f'Updated-{marker}'

    def test_payment_gateway_secrets_are_masked(self, admin_client):
        """Gateway read APIs never return employee-readable secrets."""
        suffix = uuid.uuid4().hex[:8]
        secret_key = f'sk_test_private_{suffix}'
        webhook_secret = f'whsec_private_{suffix}'
        gateway = admin_client.post('/api/v1/finance/payment-gateways/', {
            'name': f'Secret Gateway {suffix}',
            'gateway_type': 'stripe',
            'is_active': True,
            'config': {
                'secret_key': secret_key,
                'webhook_secret': webhook_secret,
                'publishable_key': f'pk_test_public_{suffix}',
            },
            'test_config': {'api_key': f'sk_test_other_{suffix}'},
        })
        assert gateway.status_code == 201, gateway.data
        gateway_id = gateway.data['id']

        detail = admin_client.get(f'/api/v1/finance/payment-gateways/{gateway_id}/')
        assert detail.status_code == 200, detail.data
        serialized = str(detail.data)
        assert secret_key not in serialized
        assert webhook_secret not in serialized
        assert detail.data['config']['secret_key'] == '********'
        assert detail.data['config']['webhook_secret'] == '********'
        assert detail.data['config']['publishable_key'] == f'pk_test_public_{suffix}'
        assert detail.data['test_config']['api_key'] == '********'

        listing = admin_client.get('/api/v1/finance/payment-gateways/')
        assert listing.status_code == 200, listing.data
        row = next(item for item in _results(listing) if item['id'] == gateway_id)
        assert secret_key not in str(row)
        assert webhook_secret not in str(row)

    @pytest.mark.parametrize(
        'path',
        [
            '/api/v1/shop/media/create_folder/',
            '/api/v1/shop/product-media/create_folder/',
        ],
    )
    @pytest.mark.parametrize('folder', ['../escape', '..', '/absolute', 'nested/folder', r'nested\folder'])
    def test_media_create_folder_rejects_traversal(self, admin_client, path, folder):
        response = admin_client.post(path, {'folder': folder})
        assert response.status_code == 400, response.data
        assert response.data == {
            'detail': 'Folder name must not contain path separators',
        }

    @pytest.mark.parametrize(
        'path',
        [
            '/api/v1/shop/media/delete_folder/',
            '/api/v1/shop/product-media/delete_folder/',
        ],
    )
    @pytest.mark.parametrize('folder', ['../escape', '..', '/absolute', 'nested/folder'])
    def test_media_delete_folder_rejects_traversal(self, admin_client, path, folder):
        response = admin_client.delete(f'{path}?folder={folder}')
        assert response.status_code == 400, response.data
        assert response.data == {
            'detail': 'Folder name must not contain path separators',
        }
