"""Authentication middleware for device API keys"""
from functools import wraps
from flask import request, jsonify
from services.firebase_service import FirebaseService

firebase_service = FirebaseService()

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
        
        # Load device keys from Secret Manager
        device_keys = firebase_service.get_device_keys()
        
        # Find the device_id for this key
        device_id = None
        for dev_id, key in device_keys.items():
            if key == device_key:
                device_id = dev_id
                break
        
        if not device_id:
            return jsonify({
                'error': 'Invalid authentication',
                'message': 'Invalid device key'
            }), 401
        
        # Pass device_id to the route handler
        return f(device_id=device_id, *args, **kwargs)
    
    return decorated_function
