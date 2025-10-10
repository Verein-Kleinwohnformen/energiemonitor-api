"""Telemetry data models"""
from typing import Dict, Any, Optional

class TelemetryData:
    """Represents a telemetry data point from a sensor"""
    
    def __init__(self, 
                 values: Dict[str, Any],
                 sensor_id: str,
                 timestamp: int,
                 metering_point: str,
                 device_id: Optional[str] = None):
        """
        Initialize telemetry data
        
        Args:
            values: Dictionary of sensor readings
            sensor_id: Unique sensor identifier
            timestamp: Unix timestamp in milliseconds
            metering_point: Measurement point identifier (e.g., E1, K0)
            device_id: Device identifier (set by auth middleware)
        """
        self.values = values
        self.sensor_id = sensor_id
        self.timestamp = timestamp
        self.metering_point = metering_point
        self.device_id = device_id
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            'values': self.values,
            'sensor_id': self.sensor_id,
            'timestamp': self.timestamp,
            'metering_point': self.metering_point,
            'device_id': self.device_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TelemetryData':
        """Create instance from dictionary"""
        return cls(
            values=data.get('values', {}),
            sensor_id=data.get('sensor_id', ''),
            timestamp=data.get('timestamp', 0),
            metering_point=data.get('metering_point', ''),
            device_id=data.get('device_id')
        )
