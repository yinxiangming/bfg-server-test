"""
API integration test 17.3: Storefront Cart API

Test cart-related storefront API endpoints
Covers: anonymous cart, authenticated cart, cart operations, cart item fields
"""

import uuid
import pytest
from decimal import Decimal

from client_remote import RemoteAPIClient


@pytest.mark.api_integration
class TestStorefrontCart:
    """Test storefront cart-related API"""
    
    def test_anonymous_cart_operations(self, workspace, admin_client):
        """A signed cart token, without cookies, must preserve the guest cart."""
        suf = uuid.uuid4().hex[:6]
        # Setup: Create product (admin_client is fixture: authenticated when remote, staff when local)
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": "Books", "slug": f"books-{suf}", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = admin_client.post('/api/v1/shop/admin/products/', {
            "name": "Python Guide", "slug": f"python-guide-{suf}", "price": "29.99",
            "category_ids": [cat_id], "language": "en", "is_active": True,
            "track_inventory": False  # Disable inventory tracking for this test
        })
        prod_id = prod_res.data['id']
        
        # Test: Anonymous user can get/create cart
        token_issuer = RemoteAPIClient(
            workspace=workspace,
            token=None,
            persist_cookies=False,
        )
        cart_res = token_issuer.get('/api/v1/store/cart/current/')
        assert cart_res.status_code == 200, (
            f"Storefront cart/current failed: {cart_res.status_code} {cart_res.data}"
        )
        assert 'id' in cart_res.data
        assert 'items' in cart_res.data
        assert 'total' in cart_res.data
        assert cart_res.data.get('cart_token')

        anonymous_api_client = RemoteAPIClient(
            workspace=workspace,
            token=None,
            persist_cookies=False,
        )
        anonymous_api_client.use_cart_token(cart_res.data['cart_token'])
        
        # Test: Add item to cart
        add_res = anonymous_api_client.post('/api/v1/store/cart/add_item/', {
            "product": prod_id,
            "quantity": 2
        })
        assert add_res.status_code == 200
        assert len(add_res.data['items']) == 1
        assert Decimal(str(add_res.data['total'])) == Decimal("59.98")  # 2 * 29.99
        
        cart_id = add_res.data['id']
        item_id = add_res.data['items'][0]['item_id']
        
        # Test: Update item quantity
        update_res = anonymous_api_client.post('/api/v1/store/cart/update_item/', {
            "item_id": item_id,
            "quantity": 3
        })
        assert update_res.status_code == 200
        assert Decimal(str(update_res.data['total'])) == Decimal("89.97")  # 3 * 29.99
        
        # Test: Remove item
        remove_res = anonymous_api_client.post('/api/v1/store/cart/remove_item/', {
            "item_id": item_id
        })
        assert remove_res.status_code == 200
        assert len(remove_res.data['items']) == 0
        assert Decimal(str(remove_res.data['total'])) == Decimal("0.00")
        
        # Test: Clear cart
        # Add item again first
        anonymous_api_client.post('/api/v1/store/cart/add_item/', {
            "product": prod_id,
            "quantity": 1
        })
        clear_res = anonymous_api_client.post('/api/v1/store/cart/clear/')
        assert clear_res.status_code == 200
        assert len(clear_res.data['items']) == 0

        tampered = RemoteAPIClient(workspace=workspace, token=None, persist_cookies=False)
        tampered.use_cart_token(f"{cart_res.data['cart_token']}tampered")
        tampered_res = tampered.get('/api/v1/store/cart/current/')
        assert tampered_res.status_code == 400, tampered_res.data
        assert 'cart_token' in tampered_res.data
    
    def test_cart_merge_on_login(self, workspace, admin_client, customer_user):
        """The signed guest cart is merged once into the logged-in customer's cart."""
        suf = uuid.uuid4().hex[:6]
        existing_customer = RemoteAPIClient(
            workspace=workspace,
            token=customer_user.token,
            persist_cookies=False,
        )
        clear_res = existing_customer.post('/api/v1/store/cart/clear/')
        assert clear_res.status_code == 200, clear_res.data
        assert clear_res.data['items'] == []

        # Setup: admin creates product
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": f"Toys {suf}", "slug": f"toys-{suf}", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = admin_client.post('/api/v1/shop/admin/products/', {
            "name": f"Toy Car {suf}", "slug": f"toy-car-{suf}", "price": "15.99",
            "category_ids": [cat_id], "language": "en", "is_active": True,
            "track_inventory": False  # Disable inventory tracking for this test
        })
        prod_id = prod_res.data['id']
        
        # Step 1: Anonymous user adds to cart
        guest_client = RemoteAPIClient(workspace=workspace, token=None, persist_cookies=False)
        current_res = guest_client.get('/api/v1/store/cart/current/')
        assert current_res.status_code == 200, current_res.data
        guest_token = current_res.data.get('cart_token')
        assert guest_token
        add_res = guest_client.post('/api/v1/store/cart/add_item/', {
            "product": prod_id,
            "quantity": 2
        })
        assert add_res.status_code == 200
        assert len(add_res.data['items']) == 1
        assert add_res.data['items'][0]['quantity'] == 2
        
        # Step 2: simulate the first authenticated request carrying the guest token.
        customer_client = RemoteAPIClient(
            workspace=workspace,
            token=customer_user.token,
            persist_cookies=False,
        )
        customer_client.use_cart_token(guest_token)
        merged_res = customer_client.get('/api/v1/store/cart/current/')
        assert merged_res.status_code == 200, merged_res.data
        assert len(merged_res.data['items']) == 1
        assert merged_res.data['items'][0]['quantity'] == 2

        # Replaying the same token must be idempotent, not double the quantity.
        replay_res = customer_client.get('/api/v1/store/cart/current/')
        assert replay_res.status_code == 200, replay_res.data
        assert len(replay_res.data['items']) == 1
        assert replay_res.data['items'][0]['quantity'] == 2

    def test_guest_cart_token_is_workspace_bound(
        self,
        workspace,
        workspace2,
        admin_client,
    ):
        """A guest token minted by one workspace cannot address another workspace."""
        source = RemoteAPIClient(workspace=workspace, token=None, persist_cookies=False)
        source_res = source.get('/api/v1/store/cart/current/')
        assert source_res.status_code == 200, source_res.data
        assert source_res.data.get('cart_token')

        target = RemoteAPIClient(workspace=workspace2, token=None, persist_cookies=False)
        target.use_cart_token(source_res.data['cart_token'])
        target_res = target.get('/api/v1/store/cart/current/')
        assert target_res.status_code == 400, target_res.data
        assert 'cart_token' in target_res.data
    
    def test_cart_item_enhanced_fields(self, workspace, admin_client, anonymous_api_client):
        """Test cart item enhanced fields (image_url, variant_options)"""
        suf = uuid.uuid4().hex[:6]
        # Setup
        cat_res = admin_client.post('/api/v1/shop/categories/', {
            "name": f"Cart Category {suf}", "slug": f"cart-category-{suf}", "language": "en", "is_active": True
        })
        cat_id = cat_res.data['id']
        
        prod_res = admin_client.post('/api/v1/shop/admin/products/', {
            "name": f"Cart Product {suf}",
            "slug": f"cart-product-{suf}",
            "price": "45.00",
            "category_ids": [cat_id],
            "language": "en",
            "is_active": True,
            "track_inventory": False
        })
        prod_id = prod_res.data['id']
        
        # Create variant with options
        var_res = admin_client.post('/api/v1/shop/variants/', {
            "product": prod_id,
            "sku": f"CART-VAR-001-{suf}",
            "name": "Medium Blue",
            "price": "45.00",
            "stock_quantity": 10,
            "options": {"size": "Medium", "color": "Blue"}
        })
        var_id = var_res.data['id']
        
        # Test: Add to cart and check enhanced fields
        add_res = anonymous_api_client.post('/api/v1/store/cart/add_item/', {
            "product": prod_id,
            "variant": var_id,
            "quantity": 1
        })
        assert add_res.status_code == 200
        
        items = add_res.data['items']
        assert len(items) > 0
        item = items[0]
        assert 'image_url' in item  # May be None if no image
        assert 'variant_options' in item
        assert item['variant_options'] == {"size": "Medium", "color": "Blue"}
