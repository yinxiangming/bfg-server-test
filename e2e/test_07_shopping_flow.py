"""
E2E Test 07: Shopping Flow
"""

import pytest
from decimal import Decimal
import uuid

@pytest.mark.e2e
class TestShoppingFlow:
    
    def test_add_to_cart(self, authenticated_client, workspace):
        """Test adding items to cart via API"""
        suffix = uuid.uuid4().hex[:6]
        # 1. Setup Product
        # Create category
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": f"General {suffix}", "slug": f"general-{suffix}", "language": "en"
        })
        cat_id = cat_res.data['id']
        
        # Create product
        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": f"T-Shirt {suffix}", "slug": f"t-shirt-{suffix}", "category_ids": [cat_id], 
            "price": "20.00", "language": "en"
        })
        prod_id = prod_res.data['id']
        
        # Create variant with stock
        var_res = authenticated_client.post('/api/v1/shop/variants/', {
            "product": prod_id, "sku": f"TSHIRT-{suffix}-L", "name": f"Large {suffix}", "price": "20.00", "stock_quantity": 10
        })
        var_id = var_res.data['id']
        
        # 2. Create Cart (or get current)
        # Usually frontend creates a cart or gets one. Let's create one.
        cart_res = authenticated_client.post('/api/v1/shop/carts/', {})
        cart_id = cart_res.data['id']
        
        # 3. Add Item
        item_payload = {
            "product": prod_id,
            "variant": var_id,
            "quantity": 2
        }
        
        # Use action endpoint instead of nested URL
        add_res = authenticated_client.post('/api/v1/shop/carts/add_item/', item_payload)
        
        assert add_res.status_code == 200
        # Verify cart total (2 * 20.00 = 40.00)
        # Response structure depends on implementation, assuming it returns updated cart
        assert Decimal(str(add_res.data['total'])) == Decimal("40.00")
        
    def test_checkout_preparation(self, authenticated_client, workspace):
        """Test checkout preparation (address, shipping, product, full checkout)"""
        suffix = uuid.uuid4().hex[:6]
        # 1. Create Address via API
        addr_res = authenticated_client.post("/api/v1/addresses/", {
            "full_name": "John Doe",
            "address_line1": f"123 St {suffix}",
            "phone": "1234567890",
            "city": "City",
            "country": "US",
            "postal_code": "12345",
        })
        assert addr_res.status_code == 201
        address_id = addr_res.data["id"]

        # 2. Create Warehouse via API
        wh_res = authenticated_client.post("/api/v1/delivery/warehouses/", {
            "name": f"Main Warehouse {suffix}",
            "code": f"WH-001-{suffix}",
            "city": "City",
            "country": "US",
            "postal_code": "12345",
        })
        assert wh_res.status_code == 201
        warehouse_id = wh_res.data["id"]

        # 3. Create Store via API
        store_res = authenticated_client.post("/api/v1/shop/stores/", {
            "name": f"Test Store {suffix}",
            "code": f"ST-001-{suffix}",
            "warehouse_ids": [warehouse_id],
        })
        assert store_res.status_code == 201
        store_id = store_res.data["id"]

        # 4. Create category and product so cart is not empty
        cat_res = authenticated_client.post('/api/v1/shop/categories/', {
            "name": f"Checkout Cat {suffix}", "slug": f"checkout-cat-{suffix}",
            "language": "en", "is_active": True
        })
        assert cat_res.status_code == 201
        cat_id = cat_res.data['id']

        prod_res = authenticated_client.post('/api/v1/shop/products/', {
            "name": f"Checkout Product {suffix}", "slug": f"checkout-product-{suffix}",
            "price": "50.00", "category_ids": [cat_id], "language": "en",
            "is_active": True, "track_inventory": False
        })
        assert prod_res.status_code == 201
        prod_id = prod_res.data['id']

        # 5. Create Cart and add item
        authenticated_client.post('/api/v1/shop/carts/', {})
        authenticated_client.post('/api/v1/shop/carts/add_item/', {
            "product": prod_id, "quantity": 1
        })

        # 6. Checkout with items in cart
        checkout_payload = {
            "store": store_id,
            "shipping_address": address_id,
            "billing_address": address_id,
        }
        
        checkout_res = authenticated_client.post('/api/v1/shop/carts/checkout/', checkout_payload)
        assert checkout_res.status_code == 201
