"""
API integration test 08: Payment Flow
"""

import pytest
from decimal import Decimal


@pytest.mark.api_integration
class TestPaymentFlow:

    def test_create_payment(
        self,
        admin_client,
        customer_client,
        workspace,
        store,
        payment_gateway,
        customer,
        message_templates,
    ):
        """Create a payment using the checkout invoice amount and currency."""
        # Create category via API
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            'name': 'Test Category',
            'slug': 'test-category',
            'language': 'en',
            'is_active': True
        })
        assert cat_res.status_code == 201
        category_id = cat_res.data['id']
        
        # Create product via API
        prod_res = admin_client.post('/api/v1/shop/admin/products/', {
            'name': 'Test Product',
            'slug': 'test-product',
            'sku': 'TEST001',
            'price': '100.00',
            'category_ids': [category_id],
            'language': 'en',
            'is_active': True,
            'track_inventory': False,
        })
        assert prod_res.status_code == 201
        product_id = prod_res.data['id']

        clear_res = customer_client.post('/api/v1/store/cart/clear/')
        assert clear_res.status_code == 200, clear_res.data
        
        # Create address via API
        addr_res = customer_client.post('/api/v1/me/addresses/', {
            'full_name': 'John Doe',
            'phone': '1234567890',
            'address_line1': '123 Main St',
            'city': 'City',
            'state': 'CA',
            'country': 'US',
            'postal_code': '12345'
        })
        assert addr_res.status_code == 201
        address_id = addr_res.data['id']
        
        cart_res = customer_client.post('/api/v1/store/cart/add_item/', {
            'product': product_id,
            'quantity': 1,
        })
        assert cart_res.status_code == 200, cart_res.data
        order_res = customer_client.post('/api/v1/store/cart/checkout/', {
            'store': store.id,
            'shipping_address': address_id,
            'billing_address': address_id,
        })
        assert order_res.status_code == 201, order_res.data
        assert 'amounts' in order_res.data, order_res.data
        assert 'total' in order_res.data['amounts'], order_res.data
        order_id = order_res.data['id']
        order_total = Decimal(str(order_res.data['amounts']['total']))
        assert order_total > Decimal('0.00')

        invoices_res = admin_client.get(f'/api/v1/finance/invoices/?order={order_id}')
        assert invoices_res.status_code == 200, invoices_res.data
        invoices = invoices_res.data if isinstance(invoices_res.data, list) else invoices_res.data.get('results', [])
        assert invoices, 'Checkout must create an invoice'
        invoice = invoices[0]
        assert Decimal(str(invoice['total'])) == order_total
        
        # Create Payment via API (amount should match order total)
        payment_payload = {
            "order_id": order_id,
            "customer_id": customer.id,
            "gateway_id": payment_gateway.id,
            "currency_id": invoice['currency'],
            "invoice_id": invoice['id'],
            "amount": str(order_total),
            "status": "pending"
        }
        
        payment_res = admin_client.post('/api/v1/finance/payments/', payment_payload)
        
        assert payment_res.status_code == 201, payment_res.data
        assert payment_res.data['status'] == 'pending'
        assert Decimal(str(payment_res.data['amount'])) == order_total

    def test_gift_card_creation_and_redemption(self, authenticated_client, workspace, currency):
        """Test gift card creation and redemption via API (currency from fixture; seed finance/currencies if needed)."""
        create_res = authenticated_client.post('/api/v1/marketing/gift-cards/', {
            'initial_value': '100.00',
            'balance': '100.00',
            'currency': currency.id,
            'is_active': True
        })
        assert create_res.status_code == 201
        assert str(create_res.data['initial_value']) in ('100', '100.00')
        assert Decimal(str(create_res.data['balance'])) == Decimal('100.00')
        
        gift_card_id = create_res.data['id']
        
        # Redeem gift card
        redeem_res = authenticated_client.post(
            f'/api/v1/marketing/gift-cards/{gift_card_id}/redeem/',
            {'amount': '25.00'}
        )
        
        assert redeem_res.status_code == 200
        assert redeem_res.data['success'] == True
        assert str(redeem_res.data.get('redeemed_amount', '')) in ('25', '25.00')
        assert str(redeem_res.data.get('remaining_balance', '')) in ('75', '75.00')
