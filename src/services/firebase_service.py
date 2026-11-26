"""Firebase/Firestore service for data storage"""
import os
from typing import Dict, Any, Tuple, List, Optional, Iterator
from datetime import datetime, timezone, timedelta
from google.cloud import firestore
from google.cloud import secretmanager
from api.models.metering_point import MeteringPointMetadata
from services.batch_buffer import BatchBuffer
from utils.data_quality import merge_data_quality
import logging

logger = logging.getLogger(__name__)


class FirebaseService:
    """
    Handles all Firebase/Firestore operations with optimized batching.
    
    Firestore structure (OPTIMIZED - No device document):
    /devices/{device_id}/telemetry/{year}/{month}/{uuid}
    /devices/{device_id}/metering_points/{metering_point}
    
    Note: No separate device document needed. Device info tracked via metering point metadata.
    
    Batching strategy (SAFE - No data loss risk):
    - Data is buffered ONLY during a single API request
    - All data is written to Firestore immediately after request processing
    - NO data is held in memory between requests
    - Groups up to 2,000 data points per document (50% safety margin)
    - Organizes by year/month/day for calendar-date queries
    - Uses randomized UUIDs for document IDs to avoid collisions
    - Separate documents per sensor and metering point
    
    Why this is safe:
    - Devices send data in large batches (1+ hours of data)
    - If a request contains >2000 points, it's split into multiple documents
    - All documents are written before the API responds
    - No risk of data loss from service restarts
    
    Document structure:
    {
        "sensor_id": "shelly-3em-pro",
        "device_id": "emon01",
        "metering_point": "E1",
        "date": "2025-10-12",
        "day": 12,
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
    - 99%+ reduction in write operations (batching within requests)
    - 78% reduction in writes by eliminating device document
    - Efficient date-range queries with indexed fields
    - Randomized document IDs prevent collisions and expose less information
    - Cost stays within free tier (even with 60+ devices)
    - Fast XLSX exports
    - NO DATA LOSS RISK (immediate writes)
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
        Store telemetry data point in temporary in-request buffer.
        Data is NOT persisted until store_telemetry_batch() is called.
        
        This is safe because:
        - Devices send data in large batches (1+ hours)
        - All data from a request is written immediately after request processing
        - No data is held between API requests
        
        Args:
            device_id: Device identifier
            data: Telemetry data dictionary
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Check if at least one valid value exists
            values = data.get('values', {})
            if not values:
                logger.debug(f"Skipping data point with no values dict for device {device_id}")
                return True, "Data point skipped (no values)"
            
            # Check if at least one value is valid (not None, not NaN, not empty string)
            has_valid_value = False
            for key, value in values.items():
                # Check if value is valid
                if value is not None and value != '' and str(value).lower() != 'nan':
                    # For numeric values, check if it's actually a valid number
                    if isinstance(value, (int, float)):
                        import math
                        if not math.isnan(value) and not math.isinf(value):
                            has_valid_value = True
                            break
                    else:
                        # Non-numeric values (strings, booleans) are valid if not empty
                        has_valid_value = True
                        break
            
            if not has_valid_value:
                logger.debug(f"Skipping data point - all values invalid for device {device_id}")
                return True, "Data point skipped (all values invalid)"
            
            # Add data point to buffer (in-memory, per-request)
            should_flush, documents = self.batch_buffer.add_data_point(device_id, data)
            
            # If a single sensor+day reaches 2,000 points within this request, write it immediately
            if should_flush and documents:
                logger.info(f"Single batch reached 2,000 points for device {device_id}, writing {len(documents)} document(s)")
                self._write_documents(documents)
                
                # Update metering point metadata for the flushed documents
                self._update_metering_points(device_id, [doc['data'] for doc in documents if 'data' in doc])
            
            return True, "Data point added to request buffer"
            
        except Exception as e:
            logger.error(f"Failed to buffer data point: {e}", exc_info=True)
            return False, f"Failed to store data: {str(e)}"
    
    def store_telemetry_batch(self, device_id: str) -> Tuple[bool, str]:
        """
        Write all buffered telemetry data for a device to Firestore.
        
        This should be called at the END of each telemetry API request to ensure
        all data from the request is persisted immediately.
        
        Also updates metering point metadata with last_seen timestamp.
        
        Args:
            device_id: Device identifier
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Flush all buffered data for this device
            documents = self.batch_buffer.flush_all(device_id)
            
            if documents:
                logger.info(f"Writing {len(documents)} document(s) to Firestore for device {device_id}")
                self._write_documents(documents)
                
                # Metering point metadata: one read and one write per metering point and request
                self._update_metering_points(device_id, [doc['data'] for doc in documents if 'data' in doc])
                
                logger.info(f"Device {device_id}: Batch write complete - Wrote {len(documents)} document(s) to Firestore")
                
                return True, f"Wrote {len(documents)} document(s) to Firestore"
            else:
                return True, "No data to write"
                
        except Exception as e:
            logger.error(f"Failed to write batch to Firestore: {e}", exc_info=True)
            return False, f"Failed to write batch: {str(e)}"
    
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
                
                # Update metering point metadata with last_seen, grouped per device
                by_device: Dict[str, List[Dict[str, Any]]] = {}
                for doc in documents:
                    if 'data' in doc and doc['data'].get('device_id'):
                        by_device.setdefault(doc['data']['device_id'], []).append(doc['data'])
                for dev_id, docs in by_device.items():
                    self._update_metering_points(dev_id, docs)
                
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
        
        Uses randomized document IDs (UUIDs) to avoid collisions.
        
        Args:
            documents: List of document dictionaries to write
        """
        for doc in documents:
            collection_path = doc['path']
            document_id = doc['document_id']
            data = doc['data']
            
            # Write the document (UUID ensures no conflicts)
            doc_ref = self.db.collection(collection_path).document(document_id)
            doc_ref.set(data)
            logger.info(f"Wrote document to {collection_path}/{doc_ref.id} with {data['count']} data points from sensor {data.get('sensor_id')} at metering point {data.get('metering_point')}")
    
    def _update_metering_point_metadata(self, device_id: str, data: Dict[str, Any]):
        """Metadaten eines Messpunkts nachführen (ein Dokument)."""
        self._update_metering_points(device_id, [data])

    def _update_metering_points(self, device_id: str, docs: List[Dict[str, Any]]):
        """
        Update metering point metadata (last_seen, sensor_types, value_fields)
        for all telemetry documents written in one request.

        Cost: one batched read (get_all) and at most one write per metering point
        and request. K0 has several sensors (netatmo, sensirion_*); before this,
        every sensor document cost its own read and write.
        """
        try:
            per_mp: Dict[str, Dict[str, Any]] = {}
            for data in docs:
                metering_point = data.get('metering_point')
                sensor_id = data.get('sensor_id')
                if not metering_point or not sensor_id:
                    continue
                # end_timestamp = last data point in the document
                timestamp = data.get('end_timestamp') or data.get('timestamp') or int(datetime.now().timestamp() * 1000)
                value_fields = set(data.get('values', {}).keys()) if 'values' in data else set()
                for point in data.get('data_points', []):
                    value_fields.update(point.get('values', {}).keys())
                agg = per_mp.setdefault(metering_point, {
                    'sensors': set(), 'value_fields': set(), 'last_seen': 0,
                    'first_seen': data.get('start_timestamp') or timestamp, 'first_sensor': sensor_id})
                agg['sensors'].add(sensor_id)
                agg['value_fields'] |= value_fields
                agg['last_seen'] = max(agg['last_seen'], timestamp)
                agg['first_seen'] = min(agg['first_seen'], data.get('start_timestamp') or timestamp)
            if not per_mp:
                return

            col = self.db.collection(f'devices/{device_id}/metering_points')
            refs = {mp: col.document(mp) for mp in per_mp}
            snaps = {snap.id: snap for snap in self.db.get_all(list(refs.values()))}

            for mp, agg in per_mp.items():
                mp_ref = refs[mp]
                snap = snaps.get(mp)
                value_fields = sorted(agg['value_fields'])
                if snap is not None and snap.exists:
                    # last_seen must never go backwards (several day documents per request)
                    existing_last_seen = (snap.to_dict() or {}).get('last_seen') or 0
                    update = {
                        'last_seen': max(agg['last_seen'], existing_last_seen),
                        'sensor_types': firestore.ArrayUnion(sorted(agg['sensors'])),
                    }
                    if value_fields:
                        # New fields (e.g. after a flow update) must appear in the app
                        update['value_fields'] = firestore.ArrayUnion(value_fields)
                    mp_ref.update(update)
                    logger.debug(f"Updated metering point metadata for {mp} with last_seen={update['last_seen']}")
                else:
                    mp_metadata = MeteringPointMetadata(
                        metering_point=mp,
                        device_id=device_id,
                        sensor_types=sorted(agg['sensors']),
                        first_seen=agg['first_seen'],
                        last_seen=agg['last_seen'],
                        value_fields=value_fields
                    )
                    mp_ref.set(mp_metadata.to_dict())
                    logger.info(f"Created metering point metadata for {mp} with sensors={sorted(agg['sensors'])}")
        except Exception as e:
            logger.warning(f"Failed to update metering point metadata: {e}")

    def update_data_quality(self, device_id: str, metering_point: str, sensor_id: str,
                            timestamp: int, quality: Dict[str, Any]) -> bool:
        """
        Store the data-quality status of a metering point (once per request, not per data point).

        Writes devices/{device_id}/metering_points/{mp}.data_quality and keeps last_seen fresh,
        so a sensor that only reports "no_valid_data" still counts as online.
        See utils/data_quality.py for the format.
        """
        try:
            mp_ref = self.db.collection(f'devices/{device_id}/metering_points').document(metering_point)
            mp_doc = mp_ref.get()
            existing = (mp_doc.to_dict() or {}) if mp_doc.exists else {}

            merged = merge_data_quality(existing.get('data_quality'), quality, sensor_id, timestamp)
            if merged is None:
                return True  # older than the stored status or no status sent

            update = {
                'metering_point': metering_point,
                'device_id': device_id,
                'data_quality': merged,
                'last_seen': max(timestamp, existing.get('last_seen') or 0),
                'sensor_types': firestore.ArrayUnion([sensor_id]),
            }
            if not mp_doc.exists:
                update['first_seen'] = timestamp
                update['value_fields'] = []
            mp_ref.set(update, merge=True)
            logger.info(f"Data quality for {device_id}/{metering_point}: {merged['status']} (since {merged['since']})")
            return True
        except Exception as e:
            logger.warning(f"Failed to update data quality: {e}")
            return False
    

    
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
            all_data_points = list(self.iter_telemetry_data(
                device_id, start_timestamp, end_timestamp, sensor_id, metering_point))

            # Sort by timestamp
            all_data_points.sort(key=lambda x: x['timestamp'])

            logger.info(f"Retrieved {len(all_data_points)} data points for device {device_id}")
            return all_data_points

        except Exception as e:
            logger.error(f"Error retrieving telemetry data: {e}", exc_info=True)
            return []

    def iter_telemetry_data(self,
                            device_id: str,
                            start_timestamp: int,
                            end_timestamp: int,
                            sensor_id: Optional[str] = None,
                            metering_point: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        """
        Stream telemetry data points for a date range, one Firestore document at a time.

        Same filtering as get_telemetry_data, but never holds more than one batched
        document in memory. Points are yielded in document order, not sorted by timestamp.
        Errors propagate to the caller.
        """
        start_dt = datetime.fromtimestamp(start_timestamp / 1000, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_timestamp / 1000, tz=timezone.utc)

        # Iterate through each day in the range
        current_date = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        while current_date <= end_dt:
            year = current_date.year
            month = f"{current_date.month:02d}"
            day = current_date.day

            collection_path = f'devices/{device_id}/telemetry/{year}/{month}'
            collection_ref = self.db.collection(collection_path)

            # Build Firestore query with filters
            query = collection_ref.where('day', '==', day)

            if sensor_id:
                query = query.where('sensor_id', '==', sensor_id)

            if metering_point:
                query = query.where('metering_point', '==', metering_point)

            for doc in query.stream():
                doc_data = doc.to_dict()

                # Extract metadata for each point
                sensor_id_from_doc = doc_data.get('sensor_id')
                metering_point_from_doc = doc_data.get('metering_point')
                device_id_from_doc = doc_data.get('device_id')

                # Flatten batched data points and filter by timestamp
                for point in doc_data.get('data_points', []):
                    point_timestamp = point.get('timestamp')

                    # Only include points within the exact timestamp range
                    if start_timestamp <= point_timestamp <= end_timestamp:
                        yield {
                            'timestamp': point_timestamp,
                            'values': point.get('values', {}),
                            'sensor_id': sensor_id_from_doc,
                            'metering_point': metering_point_from_doc,
                            'device_id': device_id_from_doc
                        }

            # Move to next day
            current_date += timedelta(days=1)
    
    def get_manual_data(self, 
                        device_id: str, 
                        start_timestamp: int, 
                        end_timestamp: int) -> List[Dict[str, Any]]:
        """
        Retrieve manual energy data for a date range.
        
        Manual data structure:
        /devices/{device_id}/manual/{year}/data/{uuid}
        
        Args:
            device_id: Device identifier
            start_timestamp: Start time in milliseconds
            end_timestamp: End time in milliseconds
            
        Returns:
            List of individual data points from manual entries
        """
        try:
            start_dt = datetime.fromtimestamp(start_timestamp / 1000, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(end_timestamp / 1000, tz=timezone.utc)
            
            all_data_points = []
            
            # Query manual data by year
            for year in range(start_dt.year, end_dt.year + 1):
                # Query the year document's data subcollection
                year_doc_path = f'devices/{device_id}/manual/{year}'
                collection_ref = self.db.collection(f'{year_doc_path}/data')
                
                # Query all documents in this year's data collection
                docs = collection_ref.stream()
                
                for doc in docs:
                    doc_data = doc.to_dict()
                    data_points = doc_data.get('data_points', [])
                    
                    # Extract metadata
                    sensor_id = doc_data.get('sensor_id', 'app_form')
                    metering_point = doc_data.get('metering_point', 'M0')
                    device_id_from_doc = doc_data.get('device_id')
                    metadata = doc_data.get('metadata', {})
                    
                    # Flatten data points and filter by timestamp
                    for point in data_points:
                        point_timestamp = point.get('timestamp')
                        
                        if start_timestamp <= point_timestamp <= end_timestamp:
                            full_point = {
                                'timestamp': point_timestamp,
                                'values': point.get('values', {}),
                                'sensor_id': sensor_id,
                                'metering_point': metering_point,
                                'device_id': device_id_from_doc,
                                'metadata': metadata  # Include description, energy_type, etc.
                            }
                            all_data_points.append(full_point)
            
            # Sort by timestamp
            all_data_points.sort(key=lambda x: x['timestamp'])
            
            logger.info(f"Retrieved {len(all_data_points)} manual data points for device {device_id}")
            return all_data_points
            
        except Exception as e:
            logger.error(f"Error retrieving manual data: {e}", exc_info=True)
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
