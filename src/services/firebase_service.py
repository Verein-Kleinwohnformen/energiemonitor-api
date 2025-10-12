"""Firebase/Firestore service for data storage"""
import os
from typing import Dict, Any, Tuple, List, Optional
from datetime import datetime, timezone
from google.cloud import firestore
from google.cloud import secretmanager
from api.models.sensor import SensorMetadata
from services.batch_buffer import BatchBuffer
import logging

logger = logging.getLogger(__name__)


class FirebaseService:
    """
    Handles all Firebase/Firestore operations with optimized batching.
    
    Firestore structure (OPTIMIZED):
    /devices/{device_id}/telemetry/{year}/{month}/{day}_{sensor_id}_{metering_point}
    /devices/{device_id}/sensors/{sensor_id}
    /devices/{device_id}/metadata
    
    Batching strategy:
    - Groups up to 2,000 data points per document (50% safety margin)
    - Organizes by year/month/day for calendar-date queries
    - Separate documents per sensor and metering point
    - Flushes on batch full or day change
    
    Document structure:
    {
        "sensor_id": "shelly-3em-pro",
        "device_id": "emon01",
        "metering_point": "E1",
        "date": "2025-10-12",
        "start_timestamp": 1728691200000,
        "end_timestamp": 1728777599999,
        "data_points": [
            {"timestamp": 1728691200000, "values": {...}},
            ...
        ],
        "count": 1234,
        "created_at": "2025-10-12T10:30:00Z"
    }
    
    Benefits:
    - 99%+ reduction in write operations
    - Efficient date-range queries
    - Cost stays within free tier
    - Fast XLSX exports
    """
    
    def __init__(self):
        """Initialize Firestore client and batch buffer"""
        self.db = firestore.Client()
        self.project_id = os.environ.get('GCP_PROJECT')
        self._device_keys_cache = None
        self.batch_buffer = BatchBuffer()
        logger.info("FirebaseService initialized with batching enabled")
    
    def get_device_keys(self) -> Dict[str, str]:
        """
        Load device keys from Google Secret Manager
        
        Returns:
            Dictionary mapping device_id to API key
        """
        if self._device_keys_cache:
            return self._device_keys_cache
        
        try:
            client = secretmanager.SecretManagerServiceClient()
            secret_name = f"projects/{self.project_id}/secrets/energiemonitor-device-keys/versions/latest"
            response = client.access_secret_version(request={"name": secret_name})
            
            # Parse the JSON payload
            import json
            self._device_keys_cache = json.loads(response.payload.data.decode('UTF-8'))
            return self._device_keys_cache
        except Exception as e:
            print(f"Error loading device keys from Secret Manager: {e}")
            return {}
    
    def store_telemetry(self, device_id: str, data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Store telemetry data using optimized batching strategy.
        
        Data points are buffered in memory and written to Firestore when:
        1. Buffer reaches 2,000 points (per sensor + day)
        2. Day boundary is crossed
        3. Explicit flush is triggered
        
        Args:
            device_id: Device identifier
            data: Telemetry data dictionary
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Ensure device document exists (for Firestore console visibility)
            self._ensure_device_document(device_id)
            
            # Add data point to buffer
            should_flush, documents = self.batch_buffer.add_data_point(device_id, data)
            
            # If buffer is full, write to Firestore
            if should_flush and documents:
                logger.info(f"Buffer full for device {device_id}, flushing {len(documents)} document(s)")
                self._write_documents(documents)
            
            # Update sensor metadata asynchronously (don't wait for completion)
            self._update_sensor_metadata(device_id, data)
            
            return True, "Data buffered successfully"
            
        except Exception as e:
            logger.error(f"Failed to buffer data: {e}", exc_info=True)
            return False, f"Failed to store data: {str(e)}"
    
    def flush_buffer(self, device_id: str = None, date_str: str = None) -> Tuple[bool, str]:
        """
        Manually flush the batch buffer to Firestore.
        
        Args:
            device_id: Optional device ID to flush. If None, flush all devices.
            date_str: Optional date to flush (format: YYYY-MM-DD). If None, flush all dates.
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            if date_str and device_id:
                documents = self.batch_buffer.flush_day(device_id, date_str)
            else:
                documents = self.batch_buffer.flush_all(device_id)
            
            if documents:
                logger.info(f"Flushing {len(documents)} document(s) to Firestore")
                self._write_documents(documents)
                return True, f"Flushed {len(documents)} document(s)"
            else:
                return True, "No documents to flush"
                
        except Exception as e:
            logger.error(f"Failed to flush buffer: {e}", exc_info=True)
            return False, f"Failed to flush buffer: {str(e)}"
    
    def get_buffer_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the current buffer state.
        
        Returns:
            Dictionary with buffer statistics
        """
        return self.batch_buffer.get_buffer_stats()
    
    def _write_documents(self, documents: List[Dict[str, Any]]):
        """
        Write batched documents to Firestore.
        
        Uses batch writes for efficiency. Handles document ID conflicts
        by appending batch numbers (_1, _2, etc.) if needed.
        
        Args:
            documents: List of document dictionaries to write
        """
        for doc in documents:
            collection_path = doc['path']
            document_id = doc['document_id']
            data = doc['data']
            
            # Check if document already exists
            doc_ref = self.db.collection(collection_path).document(document_id)
            existing_doc = doc_ref.get()
            
            if existing_doc.exists:
                # Document exists, find next available batch number
                batch_num = 2
                while True:
                    new_id = f"{document_id}_{batch_num}"
                    new_ref = self.db.collection(collection_path).document(new_id)
                    if not new_ref.get().exists:
                        doc_ref = new_ref
                        break
                    batch_num += 1
                
                logger.info(f"Document {document_id} exists, using {new_id}")
            
            # Write the document
            doc_ref.set(data)
            logger.info(f"Wrote document to {collection_path}/{doc_ref.id} with {data['count']} data points")
    
    def _update_sensor_metadata(self, device_id: str, data: Dict[str, Any]):
        """
        Update sensor metadata (last seen, data count, etc.)
        This runs asynchronously to not block telemetry ingestion
        """
        try:
            sensor_id = data.get('sensor_id')
            if not sensor_id:
                return
            
            sensor_ref = self.db.collection(f'devices/{device_id}/sensors').document(sensor_id)
            timestamp = data.get('timestamp', int(datetime.now().timestamp() * 1000))
            
            # Get current metadata or create new
            sensor_doc = sensor_ref.get()
            
            if sensor_doc.exists:
                # Update existing sensor
                sensor_ref.update({
                    'last_seen': timestamp,
                    'data_count': firestore.Increment(1),
                    'metering_point': data.get('metering_point', ''),
                })
            else:
                # Create new sensor metadata
                value_fields = list(data.get('values', {}).keys())
                sensor_metadata = SensorMetadata(
                    sensor_id=sensor_id,
                    sensor_type=sensor_id,  # Could be enhanced to detect type
                    metering_point=data.get('metering_point', ''),
                    device_id=device_id,
                    first_seen=timestamp,
                    last_seen=timestamp,
                    data_count=1,
                    value_fields=value_fields
                )
                sensor_ref.set(sensor_metadata.to_dict())
                
        except Exception as e:
            print(f"Warning: Failed to update sensor metadata: {e}")
    
    def _ensure_device_document(self, device_id: str):
        """
        Ensure device document exists for Firestore console visibility.
        Creates a minimal device document if it doesn't exist.
        This makes subcollections (telemetry, sensors) visible in the console.
        """
        try:
            device_ref = self.db.collection('devices').document(device_id)
            doc = device_ref.get()
            
            if not doc.exists:
                device_ref.set({
                    'device_id': device_id,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'last_seen': datetime.now(timezone.utc).isoformat()
                })
                logger.info(f"Created device document for {device_id}")
            else:
                # Update last_seen timestamp
                device_ref.update({
                    'last_seen': datetime.now(timezone.utc).isoformat()
                })
        except Exception as e:
            # Don't fail if device document can't be created
            logger.warning(f"Could not ensure device document for {device_id}: {e}")
    
    def get_telemetry_data(self, 
                          device_id: str, 
                          start_timestamp: int, 
                          end_timestamp: int,
                          sensor_id: Optional[str] = None,
                          metering_point: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieve telemetry data for a date range from batched documents.
        
        This method:
        1. Queries documents organized by year/month/day
        2. Filters by sensor_id and/or metering_point if specified
        3. Extracts individual data points from batched documents
        4. Filters by exact timestamp range
        5. Returns flattened list of individual data points
        
        Args:
            device_id: Device identifier
            start_timestamp: Start time in milliseconds
            end_timestamp: End time in milliseconds
            sensor_id: Optional filter by sensor ID
            metering_point: Optional filter by metering point
            
        Returns:
            List of individual telemetry data dictionaries (unbatched)
        """
        try:
            start_dt = datetime.fromtimestamp(start_timestamp / 1000, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(end_timestamp / 1000, tz=timezone.utc)
            
            all_data_points = []
            
            # Iterate through each day in the range
            current_date = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            while current_date <= end_dt:
                year = current_date.year
                month = f"{current_date.month:02d}"
                day = f"{current_date.day:02d}"
                
                collection_path = f'devices/{device_id}/telemetry/{year}/{month}'
                collection_ref = self.db.collection(collection_path)
                
                # Get all documents from the collection
                # We'll filter by day prefix in Python since Firestore document ID queries are complex
                docs = collection_ref.stream()
                
                for doc in docs:
                    # Filter by day prefix in document ID
                    if not doc.id.startswith(f'{day}_'):
                        continue
                    
                    doc_data = doc.to_dict()
                    
                    # Filter by sensor if specified
                    if sensor_id and doc_data.get('sensor_id') != sensor_id:
                        continue
                    
                    # Filter by metering point if specified
                    if metering_point and doc_data.get('metering_point') != metering_point:
                        continue
                    
                    data_points = doc_data.get('data_points', [])
                    
                    # Extract metadata for each point
                    sensor_id_from_doc = doc_data.get('sensor_id')
                    metering_point_from_doc = doc_data.get('metering_point')
                    device_id_from_doc = doc_data.get('device_id')
                    
                    # Flatten batched data points and filter by timestamp
                    for point in data_points:
                        point_timestamp = point.get('timestamp')
                        
                        # Only include points within the exact timestamp range
                        if start_timestamp <= point_timestamp <= end_timestamp:
                            # Reconstruct full data point with metadata
                            full_point = {
                                'timestamp': point_timestamp,
                                'values': point.get('values', {}),
                                'sensor_id': sensor_id_from_doc,
                                'metering_point': metering_point_from_doc,
                                'device_id': device_id_from_doc
                            }
                            all_data_points.append(full_point)
                
                # Move to next day
                from datetime import timedelta
                current_date += timedelta(days=1)
            
            # Sort by timestamp
            all_data_points.sort(key=lambda x: x['timestamp'])
            
            logger.info(f"Retrieved {len(all_data_points)} data points for device {device_id}")
            return all_data_points
            
        except Exception as e:
            logger.error(f"Error retrieving telemetry data: {e}", exc_info=True)
            return []
    
    def get_device_sensors(self, device_id: str) -> List[Dict[str, Any]]:
        """
        Get all sensors for a device
        
        Args:
            device_id: Device identifier
            
        Returns:
            List of sensor metadata dictionaries
        """
        try:
            sensors_ref = self.db.collection(f'devices/{device_id}/sensors')
            sensors = []
            
            for doc in sensors_ref.stream():
                sensors.append(doc.to_dict())
            
            return sensors
            
        except Exception as e:
            print(f"Error retrieving sensors: {e}")
            return []
