"""
API integration test 17.6: Storefront Payments API (API-only; same contract for all backends).
"""

import uuid

import pytest


def _create_payable_order(client, store, price='99.00'):
    """Create a non-zero order through the customer checkout flow."""
    suffix = uuid.uuid4().hex[:8]
    category_res = client.post('/api/v1/shop/categories/', {
        'name': f'Payment Category {suffix}',
        'slug': f'payment-category-{suffix}',
        'language': 'en',
        'is_active': True,
    })
    assert category_res.status_code == 201, category_res.data
    product_res = client.post('/api/v1/shop/admin/products/', {
        'name': f'Payment Product {suffix}',
        'slug': f'payment-product-{suffix}',
        'sku': f'PAY-{suffix}'.upper(),
        'price': price,
        'category_ids': [category_res.data['id']],
        'language': 'en',
        'is_active': True,
        'track_inventory': False,
    })
    assert product_res.status_code == 201, product_res.data
    cart_res = client.post('/api/v1/store/cart/add_item/', {
        'product': product_res.data['id'],
        'quantity': 1,
    })
    assert cart_res.status_code == 200, cart_res.data
    address_res = client.post('/api/v1/me/addresses/', {
        'full_name': 'Payment Customer',
        'phone': '1234567890',
        'address_line1': '123 Payment St',
        'city': 'City',
        'country': 'US',
        'postal_code': '12345',
    })
    assert address_res.status_code == 201, address_res.data
    checkout_res = client.post(
        '/api/v1/store/cart/checkout/',
        {
            'store': store.id,
            'shipping_address': address_res.data['id'],
        },
        HTTP_X_CART_ID=str(cart_res.data['id']),
    )
    assert checkout_res.status_code == 201, checkout_res.data
    return checkout_res.data


@pytest.mark.api_integration
class TestStorefrontPayments:
    """Test storefront payment-related API."""

    def test_payment_intent_creation(
        self,
        authenticated_client,
        workspace,
        user,
        customer,
        store,
        currency,
        payment_gateway,
    ):
        """Test payment intent creation for a payable checkout order."""
        order = _create_payable_order(authenticated_client, store)
        order_id = order['id']
        # Create payment intent
        intent_res = authenticated_client.post("/api/v1/store/payments/intent/", {
            "order_id": order_id,
            "gateway_id": payment_gateway.id,
        })
        assert intent_res.status_code == 201, intent_res.data
        assert "payment_id" in intent_res.data
        assert "payment_number" in intent_res.data
        assert "amount" in intent_res.data
        assert "currency" in intent_res.data
        assert "gateway_payload" in intent_res.data
        assert intent_res.data["status"] == "pending"

    def test_payment_processing(
        self,
        authenticated_client,
        workspace,
        user,
        customer,
        store,
        currency,
        payment_gateway,
        other_user_client,
    ):
        """Test payment processing for a payable checkout order."""
        order = _create_payable_order(authenticated_client, store)
        order_id = order['id']
        invoices_res = authenticated_client.get(f'/api/v1/finance/invoices/?order={order_id}')
        assert invoices_res.status_code == 200, invoices_res.data
        invoices = invoices_res.data if isinstance(invoices_res.data, list) else invoices_res.data.get('results', [])
        assert invoices, 'Checkout must create an invoice for the order'
        # Create payment via API
        pay_res = authenticated_client.post("/api/v1/finance/payments/", {
            "order_id": order_id,
            "gateway_id": payment_gateway.id,
            "currency_id": invoices[0]['currency'],
            "amount": str(invoices[0]['total']),
            "status": "pending",
        })
        assert pay_res.status_code == 201, pay_res.data
        payment_id = pay_res.data["id"]
        process_res = authenticated_client.post(
            f"/api/v1/store/payments/{payment_id}/process/"
        )
        assert process_res.status_code in [200, 400]
        assert "detail" in process_res.data or "status" in process_res.data
        fake_res = authenticated_client.post("/api/v1/store/payments/99999/process/")
        assert fake_res.status_code == 404
        unauthorized_res = other_user_client.post(
            f"/api/v1/store/payments/{payment_id}/process/"
        )
        assert unauthorized_res.status_code in [403, 404]

    def test_payment_callback(self, workspace, payment_gateway, anonymous_api_client):
        """Test payment gateway callback (anonymous). Uses payment_gateway fixture (gateway_type=custom) and X-Workspace-Id."""
        callback_res = anonymous_api_client.post(
            "/api/v1/store/payments/callback/custom/",
            json={},
        )
        assert callback_res.status_code == 401, callback_res.data
        assert callback_res.data.get("detail") == "Invalid signature"
        fake_res = anonymous_api_client.post(
            "/api/v1/store/payments/callback/non-existent/"
        )
        assert fake_res.status_code == 404
