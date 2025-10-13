"""Metering point metadata models"""
from typing import Dict, List, Optional
from datetime import datetime

class MeteringPointMetadata:
    """
    Represents metadata about a metering point.
    
    A metering point is a physical measurement location (e.g., E1, I2, K0)
    that can be measured by one or more sensors.
    """
    
    def __init__(self,
                 metering_point: str,
                 device_id: str,
                 sensor_types: Optional[List[str]] = None,
                 first_seen: Optional[int] = None,
                 last_seen: Optional[int] = None,
                 value_fields: Optional[List[str]] = None):
        """
        Initialize metering point metadata
        
        Args:
            metering_point: Metering point identifier (E1, I2, K0, etc.)
            device_id: Device identifier this metering point belongs to
            sensor_types: List of sensor types measuring this point (e.g., ['victron', 'shelly-3em-pro'])
            first_seen: First data timestamp (ms)
            last_seen: Last data timestamp (ms)
            value_fields: List of value field names reported by sensors at this point
        """
        self.metering_point = metering_point
        self.device_id = device_id
        self.sensor_types = sensor_types or []
        self.first_seen = first_seen or int(datetime.now().timestamp() * 1000)
        self.last_seen = last_seen or int(datetime.now().timestamp() * 1000)
        self.value_fields = value_fields or []
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage"""
        return {
            'metering_point': self.metering_point,
            'device_id': self.device_id,
            'sensor_types': self.sensor_types,
            'first_seen': self.first_seen,
            'last_seen': self.last_seen,
            'value_fields': self.value_fields
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'MeteringPointMetadata':
        """Create instance from dictionary"""
        return cls(
            metering_point=data.get('metering_point', ''),
            device_id=data.get('device_id', ''),
            sensor_types=data.get('sensor_types', []),
            first_seen=data.get('first_seen'),
            last_seen=data.get('last_seen'),
            value_fields=data.get('value_fields', [])
        )
