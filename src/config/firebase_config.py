"""Firebase configuration"""
import os

class FirebaseConfig:
    """Firebase/GCP configuration settings"""
    
    # Get from environment variables
    PROJECT_ID = os.environ.get('GCP_PROJECT', '')
    
    # Secret Manager settings
    DEVICE_KEYS_SECRET_NAME = 'energiemonitor-device-keys'
    
    # Firestore collection names
    DEVICES_COLLECTION = 'devices'
    TELEMETRY_SUBCOLLECTION = 'telemetry'
    SENSORS_SUBCOLLECTION = 'sensors'
    METADATA_SUBCOLLECTION = 'metadata'
    
    @staticmethod
    def get_telemetry_path(device_id: str, year: int, month: str) -> str:
        """Get Firestore path for telemetry data"""
        return f'{FirebaseConfig.DEVICES_COLLECTION}/{device_id}/{FirebaseConfig.TELEMETRY_SUBCOLLECTION}/{year}/{month}'
    
    @staticmethod
    def get_sensors_path(device_id: str) -> str:
        """Get Firestore path for sensor metadata"""
        return f'{FirebaseConfig.DEVICES_COLLECTION}/{device_id}/{FirebaseConfig.SENSORS_SUBCOLLECTION}'
