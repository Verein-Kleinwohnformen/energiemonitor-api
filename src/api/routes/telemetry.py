"""Telemetry data ingestion endpoint"""
import logging
from flask import Blueprint, request, jsonify
from middleware.auth import require_device_key
from services.firebase_service import FirebaseService
from utils.validators import validate_telemetry_data
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

telemetry_bp = Blueprint('telemetry', __name__)
firebase_service = FirebaseService()

@telemetry_bp.route('/telemetry', methods=['POST'])
@require_device_key
def store_telemetry(device_id):
    """
    Store telemetry data from a device
    
    Expected payload format (from NodeRED):
    {
        "values": {
            "voltage": 231.27,
            "act_power": 14.555,
            ...
        },
        "sensor_id": "shelly-3em-pro",
        "timestamp": 1760084970005,
        "metering_point": "E1"
    }
    """
    try:
        # Log incoming request
        logger.info(f"Received telemetry request from device: {device_id}")
        logger.debug(f"Request headers: {dict(request.headers)}")
        
        data = request.get_json()
        
        # Log the raw payload
        logger.info(f"Device {device_id} payload: {data}")
        
        if not data:
            logger.warning(f"Device {device_id}: No data provided in request")
            return jsonify({'error': 'No data provided'}), 400
        
        # Validate the telemetry data structure
        is_valid, error_message = validate_telemetry_data(data)
        if not is_valid:
            logger.error(f"Device {device_id}: Validation failed - {error_message}")
            logger.debug(f"Invalid data structure: {data}")
            return jsonify({'error': f'Invalid data format: {error_message}'}), 400
        
        logger.info(f"Device {device_id}: Validation passed for sensor {data.get('sensor_id')} at metering point {data.get('metering_point')}")
        
        # Add server timestamp if not present
        if 'timestamp' not in data:
            data['timestamp'] = int(datetime.now().timestamp() * 1000)
            logger.debug(f"Device {device_id}: Added server timestamp {data['timestamp']}")
        
        # Store the data in Firebase
        logger.info(f"Device {device_id}: Storing data in Firestore...")
        success, message = firebase_service.store_telemetry(device_id, data)
        
        if success:
            logger.info(f"Device {device_id}: Data stored successfully - Sensor: {data.get('sensor_id')}, Timestamp: {data.get('timestamp')}")
            return jsonify({
                'message': 'Data stored successfully',
                'device_id': device_id,
                'sensor_id': data.get('sensor_id'),
                'timestamp': data.get('timestamp')
            }), 200
        else:
            logger.error(f"Device {device_id}: Failed to store data - {message}")
            return jsonify({'error': message}), 500
            
    except Exception as e:
        logger.exception(f"Device {device_id}: Unexpected error occurred: {str(e)}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500
