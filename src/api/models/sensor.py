"""Sensor metadata models"""
from typing import Dict, List, Optional
from datetime import datetime

class SensorMetadata:
    """Represents metadata about a sensor"""
    
    def __init__(self,
                 sensor_id: str,
                 sensor_type: str,
                 metering_point: str,
                 device_id: str,
                 first_seen: Optional[int] = None,
                 last_seen: Optional[int] = None,
                 data_count: int = 0,
                 value_fields: Optional[List[str]] = None):
        """
        Initialize sensor metadata
        
        Args:
            sensor_id: Unique sensor identifier
            sensor_type: Type of sensor (e.g., 'shelly-3em-pro', 'netatmo')
            metering_point: Measurement point identifier
            device_id: Device identifier this sensor belongs to
            first_seen: First data timestamp (ms)
            last_seen: Last data timestamp (ms)
            data_count: Total number of data points received
            value_fields: List of value field names this sensor reports
        """
        self.sensor_id = sensor_id
        self.sensor_type = sensor_type
        self.metering_point = metering_point
        self.device_id = device_id
        self.first_seen = first_seen or int(datetime.now().timestamp() * 1000)
        self.last_seen = last_seen or int(datetime.now().timestamp() * 1000)
        self.data_count = data_count
        self.value_fields = value_fields or []
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage"""
        return {
            'sensor_id': self.sensor_id,
            'sensor_type': self.sensor_type,
            'metering_point': self.metering_point,
            'device_id': self.device_id,
            'first_seen': self.first_seen,
            'last_seen': self.last_seen,
            'data_count': self.data_count,
            'value_fields': self.value_fields
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SensorMetadata':
        """Create instance from dictionary"""
        return cls(
            sensor_id=data.get('sensor_id', ''),
            sensor_type=data.get('sensor_type', ''),
            metering_point=data.get('metering_point', ''),
            device_id=data.get('device_id', ''),
            first_seen=data.get('first_seen'),
            last_seen=data.get('last_seen'),
            data_count=data.get('data_count', 0),
            value_fields=data.get('value_fields', [])
        )
