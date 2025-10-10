"""Firebase/Firestore service for data storage"""
import os
from typing import Dict, Any, Tuple, List, Optional
from datetime import datetime
from google.cloud import firestore
from google.cloud import secretmanager
from api.models.sensor import SensorMetadata

class FirebaseService:
    """
    Handles all Firebase/Firestore operations
    
    Firestore structure:
    /devices/{device_id}/telemetry/{year}/{month}/{document_id}
    /devices/{device_id}/sensors/{sensor_id}
    /devices/{device_id}/metadata
    
    This structure optimizes for:
    - Write performance (document-based, minimal reads)
    - Time-based queries (organized by year/month)
    - Cost efficiency (Firestore pricing favors fewer deep queries)
    - Sensor-based organization within each document
    """
    
    def __init__(self):
        """Initialize Firestore client"""
        self.db = firestore.Client()
        self.project_id = os.environ.get('GCP_PROJECT')
        self._device_keys_cache = None
    
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
        Store telemetry data in Firestore
        
        Args:
            device_id: Device identifier
            data: Telemetry data dictionary
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            timestamp = data.get('timestamp', int(datetime.now().timestamp() * 1000))
            dt = datetime.fromtimestamp(timestamp / 1000)
            
            # Organize by year and month for efficient querying
            year = dt.year
            month = f"{dt.month:02d}"
            
            # Create document path
            collection_path = f'devices/{device_id}/telemetry/{year}/{month}'
            
            # Add server timestamp for tracking
            data['server_timestamp'] = firestore.SERVER_TIMESTAMP
            data['device_id'] = device_id
            
            # Store the data
            doc_ref = self.db.collection(collection_path).document()
            doc_ref.set(data)
            
            # Update sensor metadata asynchronously (don't wait for completion)
            self._update_sensor_metadata(device_id, data)
            
            return True, "Data stored successfully"
            
        except Exception as e:
            return False, f"Failed to store data: {str(e)}"
    
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
    
    def get_telemetry_data(self, 
                          device_id: str, 
                          start_timestamp: int, 
                          end_timestamp: int,
                          sensor_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieve telemetry data for a date range
        
        Args:
            device_id: Device identifier
            start_timestamp: Start time in milliseconds
            end_timestamp: End time in milliseconds
            sensor_id: Optional filter by sensor ID
            
        Returns:
            List of telemetry data dictionaries
        """
        try:
            start_dt = datetime.fromtimestamp(start_timestamp / 1000)
            end_dt = datetime.fromtimestamp(end_timestamp / 1000)
            
            all_data = []
            
            # Query each month in the range
            current_date = start_dt.replace(day=1)
            while current_date <= end_dt:
                year = current_date.year
                month = f"{current_date.month:02d}"
                
                collection_path = f'devices/{device_id}/telemetry/{year}/{month}'
                query = self.db.collection(collection_path)
                
                # Filter by timestamp
                query = query.where('timestamp', '>=', start_timestamp)
                query = query.where('timestamp', '<=', end_timestamp)
                
                # Filter by sensor if specified
                if sensor_id:
                    query = query.where('sensor_id', '==', sensor_id)
                
                # Order by timestamp
                query = query.order_by('timestamp')
                
                # Execute query
                docs = query.stream()
                for doc in docs:
                    all_data.append(doc.to_dict())
                
                # Move to next month
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1)
            
            return all_data
            
        except Exception as e:
            print(f"Error retrieving telemetry data: {e}")
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
