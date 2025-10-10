"""Tests for telemetry endpoint"""
import pytest
from unittest.mock import patch, MagicMock

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
        instance.store_telemetry.return_value = (True, 'Success')
        yield instance

def test_telemetry_endpoint_success(client, mock_firebase):
    """Test successful telemetry data submission"""
    data = {
        'values': {
            'voltage': 231.27,
            'act_power': 14.555,
            'pf': 0.33
        },
        'sensor_id': 'shelly-3em-pro',
        'timestamp': 1760084970005,
        'metering_point': 'E1'
    }
    
    response = client.post(
        '/telemetry',
        json=data,
        headers={'KWF-Device-Key': 'test-key-123'}
    )
    
    assert response.status_code == 200
    assert response.json['message'] == 'Data stored successfully'
    assert response.json['device_id'] == 'emon01'

def test_telemetry_endpoint_missing_auth(client, mock_firebase):
    """Test telemetry endpoint without auth header"""
    data = {
        'values': {'voltage': 231.27},
        'sensor_id': 'test-sensor',
        'metering_point': 'E1'
    }
    
    response = client.post('/telemetry', json=data)
    
    assert response.status_code == 401
    assert 'error' in response.json

def test_telemetry_endpoint_invalid_key(client, mock_firebase):
    """Test telemetry endpoint with invalid key"""
    data = {
        'values': {'voltage': 231.27},
        'sensor_id': 'test-sensor',
        'metering_point': 'E1'
    }
    
    response = client.post(
        '/telemetry',
        json=data,
        headers={'KWF-Device-Key': 'invalid-key'}
    )
    
    assert response.status_code == 401
    assert 'Invalid authentication' in response.json['error']

def test_telemetry_endpoint_invalid_data(client, mock_firebase):
    """Test telemetry endpoint with invalid data structure"""
    data = {
        'sensor_id': 'test-sensor'
        # Missing required fields
    }
    
    response = client.post(
        '/telemetry',
        json=data,
        headers={'KWF-Device-Key': 'test-key-123'}
    )
    
    assert response.status_code == 400
    assert 'Invalid data format' in response.json['error']

def test_health_endpoint(client):
    """Test health check endpoint"""
    response = client.get('/health')
    
    assert response.status_code == 200
    assert response.json['status'] == 'healthy'
