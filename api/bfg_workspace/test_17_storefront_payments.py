"""
API integration test 17.6: Storefront Payments API (API-only; same contract for all backends).
"""

import uuid

import pytest


def _create_payable_order(admin_client, customer_client, store, price='99.00'):
    """Create a non-zero order through the customer checkout flow."""
    suffix = uuid.uuid4().hex[:8]
    category_res = admin_client.post('/api/v1/shop/categories/', {
        'name': f'Payment Category {suffix}',
        'slug': f'payment-category-{suffix}',
        'language': 'en',
        'is_active': True,
    })
    assert category_res.status_code == 201, category_res.data
    product_res = admin_client.post('/api/v1/shop/admin/products/', {
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
    cart_res = customer_client.post('/api/v1/store/cart/add_item/', {
        'product': product_res.data['id'],
        'quantity': 1,
    })
    assert cart_res.status_code == 200, cart_res.data
    address_res = customer_client.post('/api/v1/me/addresses/', {
        'full_name': 'Payment Customer',
        'phone': '1234567890',
        'address_line1': '123 Payment St',
        'city': 'City',
        'country': 'US',
        'postal_code': '12345',
    })
    assert address_res.status_code == 201, address_res.data
    checkout_res = customer_client.post(
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
        admin_client,
        customer_client,
        workspace,
        user,
        customer,
        store,
        currency,
        payment_gateway,
    ):
        """Test payment intent creation for a payable checkout order."""
        order = _create_payable_order(admin_client, customer_client, store)
        order_id = order['id']
        # Create payment intent
        intent_res = customer_client.post("/api/v1/store/payments/intent/", {
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
        admin_client,
        customer_client,
        workspace,
        user,
        customer,
        store,
        currency,
        payment_gateway,
        other_user_client,
    ):
        """Test payment processing for a payable checkout order."""
        order = _create_payable_order(admin_client, customer_client, store)
        order_id = order['id']
        invoices_res = admin_client.get(f'/api/v1/finance/invoices/?order={order_id}')
        assert invoices_res.status_code == 200, invoices_res.data
        invoices = invoices_res.data if isinstance(invoices_res.data, list) else invoices_res.data.get('results', [])
        assert invoices, 'Checkout must create an invoice for the order'
        invoice_before = invoices[0]

        intent_res = customer_client.post("/api/v1/store/payments/intent/", {
            "order_id": order_id,
            "gateway_id": payment_gateway.id,
        })
        assert intent_res.status_code == 201, intent_res.data
        payment_id = intent_res.data["payment_id"]

        process_res = customer_client.post(
            f"/api/v1/store/payments/{payment_id}/process/"
        )
        assert process_res.status_code == 200, process_res.data
        assert process_res.data["status"] == "pending"

        payment_after = customer_client.get(f"/api/v1/me/payments/{payment_id}/")
        assert payment_after.status_code == 200, payment_after.data
        assert payment_after.data["status"] == "pending"
        order_after = customer_client.get(f"/api/v1/store/orders/{order_id}/")
        assert order_after.status_code == 200, order_after.data
        assert order_after.data["payment_status"] == "pending"
        invoice_after_res = admin_client.get(f"/api/v1/finance/invoices/{invoice_before['id']}/")
        assert invoice_after_res.status_code == 200, invoice_after_res.data
        assert invoice_after_res.data["status"] == invoice_before["status"]

        fake_res = customer_client.post("/api/v1/store/payments/99999/process/")
        assert fake_res.status_code == 404
        unauthorized_res = other_user_client.post(
            f"/api/v1/store/payments/{payment_id}/process/"
        )
        assert unauthorized_res.status_code in [403, 404]

        payment_final = customer_client.get(f"/api/v1/me/payments/{payment_id}/")
        assert payment_final.status_code == 200, payment_final.data
        assert payment_final.data["status"] == "pending"
        order_final = customer_client.get(f"/api/v1/store/orders/{order_id}/")
        assert order_final.status_code == 200, order_final.data
        assert order_final.data["payment_status"] == "pending"

    def test_payment_callback_rejects_unsigned_without_side_effects(
        self,
        workspace,
        admin_client,
        customer_client,
        store,
        payment_gateway,
        anonymous_api_client,
    ):
        """An unsigned callback cannot mutate payment, order, or invoice state."""
        order = _create_payable_order(admin_client, customer_client, store)
        order_id = order['id']
        intent_res = customer_client.post('/api/v1/store/payments/intent/', {
            'order_id': order_id,
            'gateway_id': payment_gateway.id,
        })
        assert intent_res.status_code == 201, intent_res.data
        payment_id = intent_res.data['payment_id']
        invoices_res = admin_client.get(f'/api/v1/finance/invoices/?order={order_id}')
        assert invoices_res.status_code == 200, invoices_res.data
        invoices = invoices_res.data if isinstance(invoices_res.data, list) else invoices_res.data.get('results', [])
        assert invoices
        invoice_before = invoices[0]

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

        payment_after = customer_client.get(f'/api/v1/me/payments/{payment_id}/')
        assert payment_after.status_code == 200, payment_after.data
        assert payment_after.data['status'] == 'pending'
        order_after = customer_client.get(f'/api/v1/store/orders/{order_id}/')
        assert order_after.status_code == 200, order_after.data
        assert order_after.data['payment_status'] == 'pending'
        invoice_after = admin_client.get(f"/api/v1/finance/invoices/{invoice_before['id']}/")
        assert invoice_after.status_code == 200, invoice_after.data
        assert invoice_after.data['status'] == invoice_before['status']

    def test_payment_amount_tampering_is_rejected_without_creating_payment(
        self,
        admin_client,
        customer_client,
        customer,
        store,
        payment_gateway,
    ):
        """A staff payment cannot underpay a checkout order."""
        order = _create_payable_order(admin_client, customer_client, store)
        order_id = order['id']
        invoices_res = admin_client.get(f'/api/v1/finance/invoices/?order={order_id}')
        assert invoices_res.status_code == 200, invoices_res.data
        invoices = invoices_res.data if isinstance(invoices_res.data, list) else invoices_res.data.get('results', [])
        assert invoices

        before_res = admin_client.get('/api/v1/finance/payments/')
        assert before_res.status_code == 200, before_res.data
        before = before_res.data if isinstance(before_res.data, list) else before_res.data.get('results', [])
        before_ids = {item['id'] for item in before}

        tampered = admin_client.post('/api/v1/finance/payments/', {
            'order_id': order_id,
            'customer_id': customer.id,
            'gateway_id': payment_gateway.id,
            'currency_id': invoices[0]['currency'],
            'amount': '0.01',
        })
        assert tampered.status_code == 400, tampered.data
        assert 'amount' in str(tampered.data).lower()

        after_res = admin_client.get('/api/v1/finance/payments/')
        assert after_res.status_code == 200, after_res.data
        after = after_res.data if isinstance(after_res.data, list) else after_res.data.get('results', [])
        after_ids = {item['id'] for item in after}
        assert after_ids == before_ids

        order_after = customer_client.get(f'/api/v1/store/orders/{order_id}/')
        assert order_after.status_code == 200, order_after.data
        assert order_after.data['payment_status'] == 'pending'
