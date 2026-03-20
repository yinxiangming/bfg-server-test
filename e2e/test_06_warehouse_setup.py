"""
E2E Test 06: Warehouse Setup
"""

import uuid
import pytest

@pytest.mark.e2e
class TestWarehouseSetup:
    
    def test_warehouse_configuration(self, authenticated_client, workspace):
        """Test warehouse configuration via API"""
        suffix = uuid.uuid4().hex[:6]
        # 1. Create Warehouse
        wh_code = f"DC-001-{suffix}"
        wh_payload = {
            "name": "Distribution Center",
            "code": wh_code,
            "is_active": True
        }
        
        response = authenticated_client.post('/api/v1/delivery/warehouses/', wh_payload)
        
        assert response.status_code == 201
        assert response.data['code'] == wh_code
        wh_id = response.data['id']
        
        # 2. Update Warehouse (e.g. add address or change settings)
        update_payload = {
            "name": "Main Distribution Center"
        }
        
        patch_res = authenticated_client.patch(f'/api/v1/delivery/warehouses/{wh_id}/', update_payload)
        
        assert patch_res.status_code == 200
        assert patch_res.data['name'] == "Main Distribution Center"
        
    def test_inventory_check(self, authenticated_client, workspace):
        """Test inventory endpoints (if exposed via warehouse API)"""
        suffix = uuid.uuid4().hex[:6]
        # This assumes we have an endpoint to check stock or it's part of product API
        # For now, we just verify warehouse exists and is active
        wh_payload = {"name": f"Stock WH {suffix}", "code": f"WH-STOCK-{suffix}"}
        res = authenticated_client.post('/api/v1/delivery/warehouses/', wh_payload)
        assert res.status_code == 201
        assert res.data['is_active'] is True
