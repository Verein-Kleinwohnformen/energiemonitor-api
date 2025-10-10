"""Tests for export endpoint"""
import pytest
from unittest.mock import patch, MagicMock
import tempfile
import os

@pytest.fixture
def client():
    """Create test client"""
    from src.main import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def mock_firebase():
    """Mock Firebase service"""
    with patch('src.services.firebase_service.FirebaseService') as mock:
        instance = mock.return_value
        instance.get_device_keys.return_value = {
            'emon01': 'test-key-123',
            'emon02': 'test-key-456'
        }
        yield instance

@pytest.fixture
def mock_export_service():
    """Mock Export service"""
    with patch('src.services.export_service.ExportService') as mock:
        instance = mock.return_value
        # Create a temporary file to return
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
        temp_file.close()
        instance.generate_xlsx.return_value = (temp_file.name, None)
        yield instance
        # Cleanup
        try:
            os.unlink(temp_file.name)
        except:
            pass

def test_export_endpoint_success(client, mock_firebase, mock_export_service):
    """Test successful data export"""
    response = client.get(
        '/export?start_date=2025-01-01&end_date=2025-01-31',
        headers={'KWF-Device-Key': 'test-key-123'}
    )
    
    assert response.status_code == 200
    assert response.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

def test_export_endpoint_missing_params(client, mock_firebase):
    """Test export endpoint without required parameters"""
    response = client.get(
        '/export',
        headers={'KWF-Device-Key': 'test-key-123'}
    )
    
    assert response.status_code == 400
    assert 'Missing required parameters' in response.json['error']

def test_export_endpoint_missing_auth(client):
    """Test export endpoint without auth"""
    response = client.get('/export?start_date=2025-01-01&end_date=2025-01-31')
    
    assert response.status_code == 401

def test_export_endpoint_invalid_date_format(client, mock_firebase):
    """Test export endpoint with invalid date format"""
    response = client.get(
        '/export?start_date=invalid&end_date=2025-01-31',
        headers={'KWF-Device-Key': 'test-key-123'}
    )
    
    assert response.status_code == 400
    assert 'Invalid date format' in response.json['error']
