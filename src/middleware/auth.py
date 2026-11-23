"""Authentication middleware for device API keys"""
from functools import wraps
import hmac
from flask import request, jsonify
from services.firebase_service import FirebaseService

firebase_service = FirebaseService()


def device_id_for_key(device_key):
    """Device-ID zum Schluessel aus dem Secret Manager, sonst None (zeitkonstanter Vergleich)."""
    found = None
    for dev_id, key in firebase_service.get_device_keys().items():
        if isinstance(key, str) and hmac.compare_digest(key.encode(), device_key.encode()):
            found = dev_id
    return found

def require_device_key(f):
    """
    Decorator to require and validate device API key
    
    Expects header: KWF-Device-Key: <api_key>
    
    On success, passes device_id to the wrapped function
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Extract the device key from the header
        device_key = request.headers.get('KWF-Device-Key')
        
        if not device_key:
            return jsonify({
                'error': 'Missing authentication',
                'message': 'KWF-Device-Key header is required'
            }), 401
        
        device_id = device_id_for_key(device_key)
        
        if not device_id:
            return jsonify({
                'error': 'Invalid authentication',
                'message': 'Invalid device key'
            }), 401
        
        # Pass device_id to the route handler
        return f(device_id=device_id, *args, **kwargs)
    
    return decorated_function
