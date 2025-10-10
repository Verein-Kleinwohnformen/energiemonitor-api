"""Data validation utilities"""
from typing import Dict, Any, Tuple

def validate_telemetry_data(data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate telemetry data structure
    
    Expected format:
    {
        "values": {...},
        "sensor_id": "string",
        "timestamp": 1760084970005,
        "metering_point": "E1"
    }
    
    Args:
        data: Data dictionary to validate
        
    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    # Check required fields
    required_fields = ['values', 'sensor_id', 'metering_point']
    
    for field in required_fields:
        if field not in data:
            return False, f"Missing required field: {field}"
    
    # Validate values is a dictionary
    if not isinstance(data['values'], dict):
        return False, "Field 'values' must be a dictionary"
    
    # Validate values is not empty
    if not data['values']:
        return False, "Field 'values' cannot be empty"
    
    # Validate sensor_id is a string
    if not isinstance(data['sensor_id'], str) or not data['sensor_id']:
        return False, "Field 'sensor_id' must be a non-empty string"
    
    # Validate metering_point is a string
    if not isinstance(data['metering_point'], str) or not data['metering_point']:
        return False, "Field 'metering_point' must be a non-empty string"
    
    # Validate timestamp if present
    if 'timestamp' in data:
        if not isinstance(data['timestamp'], (int, float)):
            return False, "Field 'timestamp' must be a number"
        
        # Check if timestamp is reasonable (between 2020 and 2050)
        min_ts = 1577836800000  # 2020-01-01
        max_ts = 2524608000000  # 2050-01-01
        if not (min_ts <= data['timestamp'] <= max_ts):
            return False, "Field 'timestamp' is out of reasonable range"
    
    return True, ""

def validate_metering_point(metering_point: str) -> Tuple[bool, str]:
    """
    Validate metering point identifier
    
    Valid metering points: E1, E2, E3, M1, M2, A1, I1, I2, K0, K1, K2, K3, K4, D1
    
    Args:
        metering_point: Metering point identifier
        
    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    valid_points = {
        'E1', 'E2', 'E3',  # Electrical
        'M1', 'M2',         # Materials (gas, wood)
        'A1',               # Deduction (monitor consumption)
        'I1', 'I2',         # Internal (hot water, heating)
        'K0', 'K1', 'K2', 'K3', 'K4',  # Comfort
        'D1'                # Water
    }
    
    if metering_point not in valid_points:
        return False, f"Invalid metering point. Must be one of: {', '.join(sorted(valid_points))}"
    
    return True, ""
