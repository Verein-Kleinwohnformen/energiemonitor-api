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
    
    Accepts both single objects and arrays of objects.
    
    Single object format:
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
    
    Array format (from NodeRED batch upload):
    [
        { "values": {...}, "sensor_id": "...", "timestamp": ..., "metering_point": "..." },
        { "values": {...}, "sensor_id": "...", "timestamp": ..., "metering_point": "..." }
    ]
    """
    try:
        # Log incoming request
        logger.info(f"Received telemetry request from device: {device_id}")
        logger.debug(f"Request headers: {dict(request.headers)}")
        
        data = request.get_json()
        
        # Log the raw payload (truncated if too large)
        if isinstance(data, list):
            logger.info(f"Device {device_id}: Received batch with {len(data)} records")
        else:
            logger.info(f"Device {device_id} payload: {data}")
        
        if not data:
            logger.warning(f"Device {device_id}: No data provided in request")
            return jsonify({'error': 'No data provided'}), 400
        
        # Handle both single objects and arrays
        records = data if isinstance(data, list) else [data]
        
        stored_count = 0
        failed_count = 0
        errors = []
        
        for idx, record in enumerate(records):
            # Validate the telemetry data structure
            is_valid, error_message = validate_telemetry_data(record)
            if not is_valid:
                logger.error(f"Device {device_id}: Record {idx} validation failed - {error_message}")
                failed_count += 1
                errors.append(f"Record {idx}: {error_message}")
                continue
            
            logger.debug(f"Device {device_id}: Record {idx} validation passed for sensor {record.get('sensor_id')} at metering point {record.get('metering_point')}")
            
            # Add server timestamp if not present
            if 'timestamp' not in record:
                record['timestamp'] = int(datetime.now().timestamp() * 1000)
                logger.debug(f"Device {device_id}: Added server timestamp {record['timestamp']}")
            
            # Store the data in Firebase
            success, message = firebase_service.store_telemetry(device_id, record)
            
            if success:
                stored_count += 1
                logger.debug(f"Device {device_id}: Record {idx} stored successfully - Sensor: {record.get('sensor_id')}, Timestamp: {record.get('timestamp')}")
            else:
                logger.error(f"Device {device_id}: Record {idx} failed to store - {message}")
                failed_count += 1
                errors.append(f"Record {idx}: {message}")
        
        # Log summary
        logger.info(f"Device {device_id}: Batch complete - Stored: {stored_count}, Failed: {failed_count}")
        
        # Return appropriate response
        if stored_count > 0 and failed_count == 0:
            return jsonify({
                'message': 'All data stored successfully',
                'device_id': device_id,
                'stored_count': stored_count
            }), 200
        elif stored_count > 0 and failed_count > 0:
            return jsonify({
                'message': 'Partial success',
                'device_id': device_id,
                'stored_count': stored_count,
                'failed_count': failed_count,
                'errors': errors[:10]  # Limit to first 10 errors
            }), 207  # Multi-Status
        else:
            return jsonify({
                'error': 'Failed to store data',
                'device_id': device_id,
                'failed_count': failed_count,
                'errors': errors[:10]  # Limit to first 10 errors
            }), 400
            
    except Exception as e:
        logger.exception(f"Device {device_id}: Unexpected error occurred: {str(e)}")
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500


@telemetry_bp.route('/buffer/stats', methods=['GET'])
def get_buffer_stats():
    """
    Get current buffer statistics (no authentication required for monitoring)
    
    Returns information about:
    - Number of devices with buffered data
    - Number of data points per device/sensor/date
    - Total data points in buffer
    """
    try:
        stats = firebase_service.get_buffer_stats()
        return jsonify(stats), 200
    except Exception as e:
        logger.exception(f"Error getting buffer stats: {str(e)}")
        return jsonify({'error': f'Failed to get buffer stats: {str(e)}'}), 500


@telemetry_bp.route('/buffer/flush', methods=['POST'])
@require_device_key
def flush_buffer(device_id):
    """
    Manually flush the buffer for a specific device or date.
    
    Optional query parameters:
    - date: Flush specific date (format: YYYY-MM-DD)
    
    If no date specified, flushes all buffered data for the device.
    """
    try:
        date_str = request.args.get('date')
        
        success, message = firebase_service.flush_buffer(device_id, date_str)
        
        if success:
            logger.info(f"Device {device_id}: Manual flush triggered - {message}")
            return jsonify({
                'message': message,
                'device_id': device_id,
                'date': date_str
            }), 200
        else:
            logger.error(f"Device {device_id}: Flush failed - {message}")
            return jsonify({
                'error': message,
                'device_id': device_id
            }), 500
            
    except Exception as e:
        logger.exception(f"Device {device_id}: Error during flush: {str(e)}")
        return jsonify({'error': f'Failed to flush buffer: {str(e)}'}), 500
