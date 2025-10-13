"""
Firestore document batching manager for telemetry data.

This module handles buffering and batching of telemetry data points
to optimize Firestore writes and reduce costs.
"""
from typing import Dict, List, Any, Tuple
from datetime import datetime, timezone
from collections import defaultdict
import threading
import logging
import uuid

logger = logging.getLogger(__name__)


class BatchBuffer:
    """
    Manages batching of telemetry data points per sensor and day.
    
    Structure: buffer[device_id][date][sensor_id][metering_point] = {data_points: [], metadata: {}}
    """
    
    # Maximum data points per document (with 50% safety margin)
    MAX_POINTS_PER_BATCH = 2000
    
    def __init__(self):
        """Initialize the batch buffer"""
        self.buffer: Dict[str, Dict[str, Dict[str, Dict[str, Dict]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
        )
        self.lock = threading.Lock()
    
    def add_data_point(self, device_id: str, data: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Add a data point to the buffer and return documents to flush if batch is full.
        
        Args:
            device_id: Device identifier
            data: Telemetry data point
            
        Returns:
            Tuple of (should_flush: bool, documents_to_flush: List[Dict])
        """
        timestamp = data.get('timestamp', int(datetime.now(timezone.utc).timestamp() * 1000))
        dt = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
        date_str = dt.strftime('%Y-%m-%d')
        
        sensor_id = data.get('sensor_id', 'unknown')
        metering_point = data.get('metering_point', 'unknown')
        
        # Create composite key for sensor+metering_point
        sensor_key = f"{sensor_id}_{metering_point}"
        
        with self.lock:
            # Initialize buffer entry if needed
            if 'data_points' not in self.buffer[device_id][date_str][sensor_id][metering_point]:
                self.buffer[device_id][date_str][sensor_id][metering_point] = {
                    'data_points': [],
                    'metadata': {
                        'sensor_id': sensor_id,
                        'device_id': device_id,
                        'metering_point': metering_point,
                        'date': date_str,
                        'start_timestamp': timestamp,
                        'end_timestamp': timestamp
                    }
                }
            
            # Add data point (only timestamp and values, no redundant fields)
            buffer_entry = self.buffer[device_id][date_str][sensor_id][metering_point]
            buffer_entry['data_points'].append({
                'timestamp': timestamp,
                'values': data.get('values', {})
            })
            
            # Update end timestamp
            buffer_entry['metadata']['end_timestamp'] = max(
                buffer_entry['metadata']['end_timestamp'],
                timestamp
            )
            
            # Check if we need to flush this batch
            if len(buffer_entry['data_points']) >= self.MAX_POINTS_PER_BATCH:
                # Extract the batch
                documents = [self._create_document(device_id, date_str, sensor_id, metering_point)]
                # Clear the buffer for this sensor+date combination
                del self.buffer[device_id][date_str][sensor_id][metering_point]
                return True, documents
            
            return False, []
    
    def flush_day(self, device_id: str, date_str: str) -> List[Dict[str, Any]]:
        """
        Flush all buffers for a specific device and date.
        
        Args:
            device_id: Device identifier
            date_str: Date string in format YYYY-MM-DD
            
        Returns:
            List of documents to write to Firestore
        """
        documents = []
        
        with self.lock:
            if device_id in self.buffer and date_str in self.buffer[device_id]:
                # Create documents for all sensors on this day
                for sensor_id in list(self.buffer[device_id][date_str].keys()):
                    for metering_point in list(self.buffer[device_id][date_str][sensor_id].keys()):
                        documents.append(self._create_document(device_id, date_str, sensor_id, metering_point))
                
                # Clear the buffer for this day
                del self.buffer[device_id][date_str]
        
        return documents
    
    def flush_all(self, device_id: str = None) -> List[Dict[str, Any]]:
        """
        Flush all buffers (optionally for a specific device).
        
        Args:
            device_id: Optional device identifier. If None, flush all devices.
            
        Returns:
            List of documents to write to Firestore
        """
        documents = []
        
        with self.lock:
            if device_id:
                # Flush specific device
                if device_id in self.buffer:
                    for date_str in list(self.buffer[device_id].keys()):
                        for sensor_id in list(self.buffer[device_id][date_str].keys()):
                            for metering_point in list(self.buffer[device_id][date_str][sensor_id].keys()):
                                documents.append(self._create_document(device_id, date_str, sensor_id, metering_point))
                    
                    del self.buffer[device_id]
            else:
                # Flush all devices
                for dev_id in list(self.buffer.keys()):
                    for date_str in list(self.buffer[dev_id].keys()):
                        for sensor_id in list(self.buffer[dev_id][date_str].keys()):
                            for metering_point in list(self.buffer[dev_id][date_str][sensor_id].keys()):
                                documents.append(self._create_document(dev_id, date_str, sensor_id, metering_point))
                
                self.buffer.clear()
        
        return documents
    
    def get_buffer_stats(self) -> Dict[str, Any]:
        """
        Get statistics about current buffer state.
        
        Returns:
            Dictionary with buffer statistics
        """
        with self.lock:
            stats = {
                'total_devices': len(self.buffer),
                'devices': {}
            }
            
            for device_id, dates in self.buffer.items():
                device_stats = {
                    'dates': len(dates),
                    'sensors': {},
                    'total_points': 0
                }
                
                for date_str, sensors in dates.items():
                    for sensor_id, metering_points in sensors.items():
                        for metering_point, buffer_entry in metering_points.items():
                            point_count = len(buffer_entry['data_points'])
                            device_stats['total_points'] += point_count
                            
                            sensor_key = f"{sensor_id}_{metering_point}"
                            if sensor_key not in device_stats['sensors']:
                                device_stats['sensors'][sensor_key] = {
                                    'dates': {},
                                    'total_points': 0
                                }
                            
                            device_stats['sensors'][sensor_key]['dates'][date_str] = point_count
                            device_stats['sensors'][sensor_key]['total_points'] += point_count
                
                stats['devices'][device_id] = device_stats
            
            return stats
    
    def _create_document(self, device_id: str, date_str: str, sensor_id: str, metering_point: str) -> Dict[str, Any]:
        """
        Create a Firestore document from the buffer.
        
        Args:
            device_id: Device identifier
            date_str: Date string
            sensor_id: Sensor identifier
            metering_point: Metering point identifier
            
        Returns:
            Document dictionary ready for Firestore
        """
        buffer_entry = self.buffer[device_id][date_str][sensor_id][metering_point]
        
        # Extract year, month, day from date string
        date_parts = date_str.split('-')
        year = date_parts[0]
        month = date_parts[1]
        day = date_parts[2]
        
        # Generate random document ID (UUID)
        document_id = str(uuid.uuid4())
        
        # Create document with all metadata stored in the document data
        doc = {
            'path': f'devices/{device_id}/telemetry/{year}/{month}',
            'document_id': document_id,
            'data': {
                **buffer_entry['metadata'],
                'day': int(day),  # Store day as a field for filtering
                'data_points': buffer_entry['data_points'],
                'count': len(buffer_entry['data_points']),
                'created_at': datetime.now(timezone.utc).isoformat()
            }
        }
        
        return doc
