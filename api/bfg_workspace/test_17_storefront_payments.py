"""
API integration test 17.6: Storefront Payments API (API-only; same contract for all backends).
"""

import hashlib
import hmac
import json
import os
import subprocess
import time
import uuid
from decimal import Decimal
from pathlib import Path

import pytest


def _create_stripe_gateway(admin_client, workspace_id):
    suffix = uuid.uuid4().hex
    webhook_secret = f"whsec_e2e_{suffix}"
    response = admin_client.post('/api/v1/finance/payment-gateways/', {
        'name': f'Stripe Callback {suffix[:8]}',
        'gateway_type': 'stripe',
        'is_active': True,
        'is_test_mode': False,
        'config': {
            'secret_key': f'sk_test_e2e_{suffix}',
            'publishable_key': f'pk_test_e2e_{suffix}',
            'webhook_secret': webhook_secret,
        },
    })
    assert response.status_code == 201, response.data
    return {
        'id': response.data['id'],
        'workspace_id': workspace_id,
        'webhook_secret': webhook_secret,
    }


def _deactivate_gateway(admin_client, gateway):
    response = admin_client.patch(
        f"/api/v1/finance/payment-gateways/{gateway['id']}/",
        {'is_active': False},
    )
    assert response.status_code == 200, response.data


def _bind_gateway_transaction(payment_id, workspace_id, gateway_id, transaction_id):
    """Model the provider-issued ID without making an external Stripe API request."""
    server_dir = Path(os.environ['BFG2_E2E_SERVER_DIR']).resolve()
    server_python = Path(os.environ['BFG2_E2E_SERVER_PYTHON']).expanduser()
    helper = Path(__file__).resolve().parents[2] / 'scripts' / 'set_gateway_transaction.py'
    subprocess.run(
        [
            str(server_python),
            str(helper),
            '--server-dir',
            str(server_dir),
            '--payment-id',
            str(payment_id),
            '--workspace-id',
            str(workspace_id),
            '--gateway-id',
            str(gateway_id),
            '--transaction-id',
            transaction_id,
        ],
        check=True,
        cwd=server_dir,
        env=os.environ.copy(),
    )


def _stripe_event(workspace_id, transaction_id, amount_minor, currency):
    return {
        'id': f'evt_{uuid.uuid4().hex}',
        'object': 'event',
        'type': 'payment_intent.succeeded',
        'data': {
            'object': {
                'id': transaction_id,
                'object': 'payment_intent',
                'amount_received': amount_minor,
                'currency': currency.lower(),
                'metadata': {'workspace_id': str(workspace_id)},
            },
        },
    }


def _signed_body(event, secret):
    body = json.dumps(event, separators=(',', ':'), sort_keys=True)
    timestamp = int(time.time())
    digest = hmac.new(
        secret.encode('utf-8'),
        f'{timestamp}.{body}'.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return body, f't={timestamp},v1={digest}'


def _create_callback_payment(
    admin_client,
    customer_client,
    customer,
    store,
    workspace_id,
    gateway,
):
    order = _create_payable_order(admin_client, customer_client, store)
    invoices_res = admin_client.get(f"/api/v1/finance/invoices/?order={order['id']}")
    assert invoices_res.status_code == 200, invoices_res.data
    invoices = (
        invoices_res.data
        if isinstance(invoices_res.data, list)
        else invoices_res.data.get('results', [])
    )
    assert len(invoices) == 1, invoices
    invoice = invoices[0]
    payment_res = admin_client.post('/api/v1/finance/payments/', {
        'order_id': order['id'],
        'invoice_id': invoice['id'],
        'customer_id': customer.id,
        'gateway_id': gateway['id'],
        'currency_id': invoice['currency'],
        'amount': str(invoice['total']),
    })
    assert payment_res.status_code == 201, payment_res.data
    currency_res = admin_client.get(f"/api/v1/finance/currencies/{invoice['currency']}/")
    assert currency_res.status_code == 200, currency_res.data
    transaction_id = f"pi_e2e_{uuid.uuid4().hex}"
    _bind_gateway_transaction(
        payment_res.data['id'],
        workspace_id,
        gateway['id'],
        transaction_id,
    )
    return {
        'payment_id': payment_res.data['id'],
        'order_id': order['id'],
        'invoice_id': invoice['id'],
        'invoice_status': invoice['status'],
        'amount_minor': int(Decimal(str(invoice['total'])) * 100),
        'currency': currency_res.data['code'],
        'transaction_id': transaction_id,
    }


def _assert_callback_state(
    customer_client,
    admin_client,
    fixture,
    *,
    payment_status,
    order_status,
    invoice_status,
):
    payment = customer_client.get(f"/api/v1/me/payments/{fixture['payment_id']}/")
    order = customer_client.get(f"/api/v1/store/orders/{fixture['order_id']}/")
    invoice = admin_client.get(f"/api/v1/finance/invoices/{fixture['invoice_id']}/")
    assert payment.status_code == 200, payment.data
    assert order.status_code == 200, order.data
    assert invoice.status_code == 200, invoice.data
    assert payment.data['status'] == payment_status
    assert order.data['payment_status'] == order_status
    assert invoice.data['status'] == invoice_status


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

    def test_signed_stripe_callback_completes_payment_order_and_invoice(
        self,
        workspace,
        admin_client,
        customer_client,
        customer,
        store,
        anonymous_api_client,
    ):
        """A valid Stripe callback finalizes all linked payment state."""
        gateway = _create_stripe_gateway(admin_client, workspace.id)
        try:
            fixture = _create_callback_payment(
                admin_client,
                customer_client,
                customer,
                store,
                workspace.id,
                gateway,
            )
            event = _stripe_event(
                workspace.id,
                fixture['transaction_id'],
                fixture['amount_minor'],
                fixture['currency'],
            )
            body, signature = _signed_body(event, gateway['webhook_secret'])
            callback = anonymous_api_client.post(
                '/api/v1/store/payments/callback/stripe/',
                body,
                HTTP_STRIPE_SIGNATURE=signature,
            )
            assert callback.status_code == 200, callback.data
            assert callback.data['status'] == 'success'
            _assert_callback_state(
                customer_client,
                admin_client,
                fixture,
                payment_status='completed',
                order_status='paid',
                invoice_status='paid',
            )
        finally:
            _deactivate_gateway(admin_client, gateway)

    @pytest.mark.parametrize('mismatch', ['forged_signature', 'amount', 'currency'])
    def test_invalid_stripe_callback_has_no_side_effects(
        self,
        mismatch,
        workspace,
        admin_client,
        customer_client,
        customer,
        store,
        anonymous_api_client,
    ):
        """A forged or financially mismatched callback leaves all state pending."""
        gateway = _create_stripe_gateway(admin_client, workspace.id)
        try:
            fixture = _create_callback_payment(
                admin_client,
                customer_client,
                customer,
                store,
                workspace.id,
                gateway,
            )
            amount_minor = fixture['amount_minor'] + (1 if mismatch == 'amount' else 0)
            currency = (
                ('EUR' if fixture['currency'].upper() != 'EUR' else 'USD')
                if mismatch == 'currency'
                else fixture['currency']
            )
            event = _stripe_event(
                workspace.id,
                fixture['transaction_id'],
                amount_minor,
                currency,
            )
            signing_secret = (
                f"whsec_forged_{uuid.uuid4().hex}"
                if mismatch == 'forged_signature'
                else gateway['webhook_secret']
            )
            body, signature = _signed_body(event, signing_secret)
            callback = anonymous_api_client.post(
                '/api/v1/store/payments/callback/stripe/',
                body,
                HTTP_STRIPE_SIGNATURE=signature,
            )
            expected_status = 401 if mismatch == 'forged_signature' else 200
            assert callback.status_code == expected_status, callback.data
            _assert_callback_state(
                customer_client,
                admin_client,
                fixture,
                payment_status='pending',
                order_status='pending',
                invoice_status=fixture['invoice_status'],
            )
        finally:
            _deactivate_gateway(admin_client, gateway)

    def test_cross_tenant_stripe_callback_has_no_side_effects(
        self,
        workspace,
        workspace2,
        admin_client,
        admin_client2,
        customer_client,
        customer,
        store,
        anonymous_api_client2,
    ):
        """A valid signature for another tenant cannot settle this tenant's payment."""
        gateway = _create_stripe_gateway(admin_client, workspace.id)
        gateway2 = _create_stripe_gateway(admin_client2, workspace2.id)
        try:
            fixture = _create_callback_payment(
                admin_client,
                customer_client,
                customer,
                store,
                workspace.id,
                gateway,
            )
            event = _stripe_event(
                workspace2.id,
                fixture['transaction_id'],
                fixture['amount_minor'],
                fixture['currency'],
            )
            body, signature = _signed_body(event, gateway2['webhook_secret'])
            callback = anonymous_api_client2.post(
                '/api/v1/store/payments/callback/stripe/',
                body,
                HTTP_STRIPE_SIGNATURE=signature,
            )
            assert callback.status_code == 200, callback.data
            _assert_callback_state(
                customer_client,
                admin_client,
                fixture,
                payment_status='pending',
                order_status='pending',
                invoice_status=fixture['invoice_status'],
            )
        finally:
            _deactivate_gateway(admin_client2, gateway2)
            _deactivate_gateway(admin_client, gateway)

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
