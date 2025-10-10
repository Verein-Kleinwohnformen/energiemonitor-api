# KWF Energiemonitor API

Cloud-based API service for the KWF Energiemonitor project. This service receives telemetry data from NodeRED-equipped energy monitor devices and stores it in Google Cloud Firestore.

## Architecture

- **Framework**: Flask (Python)
- **Deployment**: Google Cloud Run
- **Database**: Google Cloud Firestore
- **Security**: Google Secret Manager for API keys
- **Export**: XLSX generation with openpyxl

## Project Structure

```
energiemonitor-api/
├── src/
│   ├── main.py                 # Application entry point
│   ├── api/
│   │   ├── routes/
│   │   │   ├── telemetry.py    # Telemetry ingestion endpoint
│   │   │   └── export.py       # Data export endpoint
│   │   └── models/
│   │       ├── telemetry.py    # Telemetry data model
│   │       └── sensor.py       # Sensor metadata model
│   ├── services/
│   │   ├── firebase_service.py # Firestore operations
│   │   └── export_service.py   # XLSX generation
│   ├── middleware/
│   │   └── auth.py             # Device key authentication
│   ├── utils/
│   │   └── validators.py       # Data validation
│   └── config/
│       └── firebase_config.py  # Configuration
├── tests/                       # Unit tests
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Container definition
└── cloudbuild.yaml             # GCP deployment config
```

## Firestore Data Structure

```
/devices/{device_id}/
  ├── telemetry/
  │   ├── {year}/
  │   │   └── {month}/
  │   │       └── {auto_id}: {
  │   │           "timestamp": 1760084970005,
  │   │           "sensor_id": "shelly-3em-pro",
  │   │           "metering_point": "E1",
  │   │           "values": {...},
  │   │           "server_timestamp": <firestore_timestamp>
  │   │         }
  ├── sensors/
  │   └── {sensor_id}: {
  │       "sensor_id": "shelly-3em-pro",
  │       "sensor_type": "shelly-3em-pro",
  │       "metering_point": "E1",
  │       "first_seen": 1760084970005,
  │       "last_seen": 1760184970005,
  │       "data_count": 1234,
  │       "value_fields": ["voltage", "act_power", "pf"]
  │     }
```

This structure optimizes for:
- **Write performance**: Direct writes without reads
- **Time-based queries**: Organized by year/month
- **Cost efficiency**: Minimizes deep queries
- **Sensor tracking**: Automatic metadata updates

## API Endpoints

### POST /telemetry

Receives telemetry data from NodeRED devices.

**Headers:**
- `KWF-Device-Key`: Device API key

**Request Body:**
```json
{
  "values": {
    "voltage": 231.27,
    "act_power": 14.555,
    "pf": 0.33,
    "aprt_power": 44.35
  },
  "sensor_id": "shelly-3em-pro",
  "timestamp": 1760084970005,
  "metering_point": "E1"
}
```

**Response:**
```json
{
  "message": "Data stored successfully",
  "device_id": "emon01",
  "sensor_id": "shelly-3em-pro",
  "timestamp": 1760084970005
}
```

### GET /export

Export telemetry data as XLSX file.

**Headers:**
- `KWF-Device-Key`: Device API key

**Query Parameters:**
- `start_date`: Start date (ISO format or timestamp in ms)
- `end_date`: End date (ISO format or timestamp in ms)

**Example:**
```
GET /export?start_date=2025-01-01&end_date=2025-01-31
```

**Response:**
XLSX file with separate tabs for each sensor

### GET /health

Health check endpoint for Cloud Run.

**Response:**
```json
{
  "status": "healthy"
}
```

## Setup & Deployment

### Prerequisites

1. Google Cloud Project with:
   - Cloud Run API enabled
   - Firestore database created
   - Secret Manager API enabled

2. Install Google Cloud SDK:
   ```bash
   # Install gcloud CLI
   # https://cloud.google.com/sdk/docs/install
   ```

3. Authenticate:
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```

### Store Device Keys in Secret Manager

```bash
# Create the secret with your device keys
gcloud secrets create energiemonitor-device-keys \
  --data-file=keys.json \
  --replication-policy="automatic"

# Grant Cloud Run access to the secret
gcloud secrets add-iam-policy-binding energiemonitor-device-keys \
  --member="serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

**keys.json format:**
```json
{
  "emon01": "your-secure-device-key-1",
  "emon02": "your-secure-device-key-2",
  "emon03": "your-secure-device-key-3"
}
```

### Manual Deployment

```bash
# Build and deploy to Cloud Run
gcloud run deploy energiemonitor-api \
  --source . \
  --region europe-west6 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars GCP_PROJECT=YOUR_PROJECT_ID
```

### Automated Deployment with Cloud Build

```bash
# Enable Cloud Build
gcloud services enable cloudbuild.googleapis.com

# Submit build
gcloud builds submit --config cloudbuild.yaml
```

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export GCP_PROJECT=your-project-id
export GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account-key.json

# Run locally
python src/main.py
```

### Testing

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=src tests/
```

## Security

### Device Authentication

- Each device has a unique API key stored in Google Secret Manager
- Keys are validated on every request via the `KWF-Device-Key` header
- Keys are cached in memory to reduce Secret Manager calls

### Best Practices

1. **Never commit keys**: Use Secret Manager for all sensitive data
2. **Rotate keys regularly**: Update device keys periodically
3. **Use HTTPS only**: Cloud Run enforces HTTPS
4. **Monitor access**: Use Cloud Logging to track API usage

## Monitoring & Logging

All logs are automatically sent to Google Cloud Logging:

```bash
# View logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=energiemonitor-api" --limit 50

# Monitor errors
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=energiemonitor-api AND severity>=ERROR" --limit 20
```

## Cost Optimization

- **Firestore**: Pay per read/write operation
  - Organized by year/month to minimize query costs
  - Writes are cheap, optimize for write-heavy workload
  
- **Cloud Run**: Pay per request and compute time
  - Auto-scales to zero when not in use
  - Configure `--min-instances=0` for cost savings

- **Secret Manager**: Pay per access
  - Keys are cached to minimize Secret Manager calls

## Future Enhancements

- [ ] Add data aggregation (hourly/daily summaries)
- [ ] Implement device status monitoring
- [ ] Add webhook notifications for alerts
- [ ] Create admin dashboard
- [ ] Add data retention policies
- [ ] Implement data backup strategy

## Support

For questions or issues:
- Email: energiemonitor@kleinwohnformen.ch
- GitHub: https://github.com/Verein-Kleinwohnformen

## License

Open Source - maintained by [Verein Kleinwohnformen](https://kleinwohnformen.ch)
