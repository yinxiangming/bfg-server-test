"""
API integration test: Customer Management
"""

import uuid
import pytest
from decimal import Decimal

@pytest.mark.api_integration
class TestCustomerManagement:
    
    def test_customer_segment_creation(self, authenticated_client, workspace):
        """Test customer segment creation via API"""
        suffix = uuid.uuid4().hex[:6]
        seg_name = f'VIP Customers {suffix}'
        response = authenticated_client.post('/api/v1/customer-segments/', {
            'name': seg_name,
            'description': 'High value customers'
        })
        
        assert response.status_code == 201
        assert response.data['name'] == seg_name
    
    def test_customer_tag_management(self, authenticated_client, workspace):
        """Test customer tag creation and listing via API"""
        suffix = uuid.uuid4().hex[:6]
        # Create first tag
        tag1_name = f'Premium {suffix}'
        tag1_res = authenticated_client.post('/api/v1/customer-tags/', {
            'name': tag1_name
        })
        assert tag1_res.status_code == 201
        assert tag1_res.data['name'] == tag1_name
        
        # Create second tag  
        tag2_name = f'Wholesale {suffix}'
        tag2_res = authenticated_client.post('/api/v1/customer-tags/', {
            'name': tag2_name
        })
        assert tag2_res.status_code == 201
        
        # List all tags
        list_res = authenticated_client.get('/api/v1/customer-tags/')
        assert list_res.status_code == 200
        tags = list_res.data if isinstance(list_res.data, list) else list_res.data.get('results', [])
        assert len(tags) >= 2
