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

## Firestore Datenstruktur

### Batch-Speicherung (Optimiert)

Das System verwendet eine **optimierte Batch-Speicherung**, die bis zu 2.000 Datenpunkte pro Dokument gruppiert. Dies reduziert die Schreibvorgänge um über 99% und hält die Kosten innerhalb des kostenlosen Kontingents.

```
/devices/{device_id}/
  ├── telemetry/
  │   ├── {year}/
  │   │   └── {month}/
  │   │       └── {day}/
  │   │           └── {sensor_id}_{metering_point}[_batch_nr]: {
  │   │               "sensor_id": "shelly-3em-pro",
  │   │               "device_id": "emon01",
  │   │               "metering_point": "E1",
  │   │               "date": "2025-10-12",
  │   │               "start_timestamp": 1728691200000,
  │   │               "end_timestamp": 1728777599999,
  │   │               "data_points": [
  │   │                 {
  │   │                   "timestamp": 1728691200000,
  │   │                   "values": {
  │   │                     "voltage": 231.5,
  │   │                     "act_power": 15.2,
  │   │                     "current": 1.5
  │   │                   }
  │   │                 },
  │   │                 // ... bis zu 2.000 Datenpunkte
  │   │               ],
  │   │               "count": 2000,
  │   │               "created_at": "2025-10-12T10:30:00Z"
  │   │             }
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

### Vorteile der Batch-Speicherung

- **Kosteneffizienz**: >99% Reduktion der Schreibvorgänge
  - Vorher: ~259.200 Schreibvorgänge/Monat pro Gerät
  - Nachher: ~130 Schreibvorgänge/Monat pro Gerät
  - Kosten: $0.00 (innerhalb des kostenlosen Kontingents!)

- **Kalender-basierte Abfragen**: Organisiert nach Jahr/Monat/Tag
  - Ideal für XLSX-Exporte mit Datumsbereich
  - Abfragen von Mitternacht bis Mitternacht

- **Sensorisolierung**: Separate Dokumente pro Sensor + Messpunkt
  - Einfache Filterung nach Sensor-ID
  - Keine Vermischung verschiedener Sensoren

- **Dokumentgröße**: ~265 KB bei 2.000 Datenpunkten
  - Nur 26% des 1-MB-Limits
  - 74% Sicherheitsmarge

### Pufferung und Speicherung

Das System puffert eingehende Daten im Speicher und schreibt sie in Batches:

1. **Automatisches Flushing**: Bei 2.000 Datenpunkten pro Sensor+Tag
2. **Manuelles Flushing**: Via `/buffer/flush` Endpoint
3. **Puffer-Überwachung**: Via `/buffer/stats` Endpoint

**Beispiel-Dokumentpfad:**
```
/devices/emon01/telemetry/2025/10/12/shelly-3em-pro_E1
/devices/emon01/telemetry/2025/10/12/shelly-3em-pro_E2
/devices/emon01/telemetry/2025/10/12/shelly-3em-pro_E1_2  (bei >2000 Punkten)
```

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

Exportiert Telemetriedaten als XLSX-Datei zum Download.

**Service URL:**
```
https://telemetry-api-325255315766.europe-west6.run.app
```

**Headers:**
- `KWF-Device-Key`: Device API-Schlüssel (erforderlich)

**Query Parameter:**
- `start_date`: Startdatum (ISO-Format YYYY-MM-DD oder Timestamp in ms)
- `end_date`: Enddatum (ISO-Format YYYY-MM-DD oder Timestamp in ms)

**Beispiele:**

```bash
# Mit ISO-Datum
GET https://telemetry-api-325255315766.europe-west6.run.app/export?start_date=2025-10-01&end_date=2025-10-31

# Mit Timestamp (Millisekunden)
GET https://telemetry-api-325255315766.europe-west6.run.app/export?start_date=1727740800000&end_date=1730419199999

# Mit PowerShell herunterladen
$headers = @{
    "KWF-Device-Key" = "your-device-api-key"
}

Invoke-WebRequest `
    -Uri "https://telemetry-api-325255315766.europe-west6.run.app/export?start_date=2025-10-01&end_date=2025-10-31" `
    -Headers $headers `
    -OutFile "energiemonitor_export.xlsx"

# Mit curl herunterladen
curl -H "KWF-Device-Key: your-device-api-key" \
     "https://telemetry-api-325255315766.europe-west6.run.app/export?start_date=2025-10-01&end_date=2025-10-31" \
     -o energiemonitor_export.xlsx
```

**Response:**
- XLSX-Datei mit separaten Tabs für jeden Sensor
- Dateiname: `energiemonitor_{device_id}_{start_date}_{end_date}.xlsx`
- Spalten: Timestamp, Date/Time, Metering Point, Sensor ID, + alle Sensor-Werte

**XLSX-Struktur:**
```
Tab "shelly-3em-pro":
| Timestamp      | Date/Time           | Metering Point | Sensor ID       | voltage | act_power | current |
|----------------|---------------------|----------------|-----------------|---------|-----------|---------|
| 1728691200000  | 2025-10-12 00:00:00 | E1             | shelly-3em-pro  | 231.5   | 15.2      | 1.5     |
| 1728691210000  | 2025-10-12 00:00:10 | E1             | shelly-3em-pro  | 232.1   | 15.8      | 1.6     |
...

Tab "power-meter":
| Timestamp      | Date/Time           | Metering Point | Sensor ID    | power   | frequency |
|----------------|---------------------|----------------|--------------|---------|-----------|
| 1728691200000  | 2025-10-12 00:00:00 | K0             | power-meter  | 2300.0  | 50.0      |
...
```

**Hinweise:**
- ✅ Daten werden aus der Batch-Speicherung extrahiert und entpackt
- ✅ Automatische Sortierung nach Timestamp
- ✅ Alle Sensoren in separaten Tabs
- ✅ Spaltenbreiten automatisch angepasst
- ⚠️ Große Datenbereiche können längere Download-Zeiten verursachen

### GET /health

Health check endpoint for Cloud Run.

**Response:**
```json
{
  "status": "healthy"
}
```

### GET /buffer/stats

Zeigt Statistiken über gepufferte Daten (keine Authentifizierung erforderlich).

**Response:**
```json
{
  "total_devices": 2,
  "devices": {
    "emon01": {
      "dates": 1,
      "sensors": {
        "shelly-3em-pro_E1": {
          "dates": {
            "2025-10-12": 1543
          },
          "total_points": 1543
        }
      },
      "total_points": 1543
    }
  }
}
```

### POST /buffer/flush

Manuelles Flushing des Puffers für ein Gerät.

**Headers:**
- `KWF-Device-Key`: Device API key

**Query Parameter (optional):**
- `date`: Spezifisches Datum zum Flushen (Format: YYYY-MM-DD)

**Beispiel:**
```
POST /buffer/flush
POST /buffer/flush?date=2025-10-12
```

**Response:**
```json
{
  "message": "Flushed 1 document(s)",
  "device_id": "emon01",
  "date": "2025-10-12"
}
```

## Verwendung / Usage

### Vollständiges Beispiel: Daten senden und exportieren

**Schritt 1: Telemetriedaten senden**

```powershell
# API-Schlüssel und URL definieren
$apiKey = "your-device-api-key"
$baseUrl = "https://telemetry-api-325255315766.europe-west6.run.app"

# Telemetriedaten senden
$headers = @{
    "KWF-Device-Key" = $apiKey
    "Content-Type" = "application/json"
}

$data = @{
    sensor_id = "shelly-3em-pro"
    metering_point = "E1"
    timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    values = @{
        voltage = 231.5
        act_power = 15.2
        current = 1.5
        power_factor = 0.95
    }
} | ConvertTo-Json

$response = Invoke-RestMethod -Uri "$baseUrl/telemetry" -Method POST -Headers $headers -Body $data
Write-Host "✓ Daten gesendet: $($response.message)"
```

**Schritt 2: Pufferstatus prüfen**

```powershell
# Pufferstatus abrufen (keine Authentifizierung erforderlich)
$bufferStats = Invoke-RestMethod -Uri "$baseUrl/buffer/stats"
Write-Host "Gepufferte Datenpunkte: $($bufferStats.devices.emon01.total_points)"
```

**Schritt 3: Daten als XLSX exportieren**

```powershell
# Daten für Oktober 2025 exportieren
$startDate = "2025-10-01"
$endDate = "2025-10-31"

$exportUrl = "$baseUrl/export?start_date=$startDate&end_date=$endDate"

# XLSX-Datei herunterladen
Invoke-WebRequest `
    -Uri $exportUrl `
    -Headers @{"KWF-Device-Key" = $apiKey} `
    -OutFile "energiemonitor_export_oktober_2025.xlsx"

Write-Host "✓ Export erfolgreich: energiemonitor_export_oktober_2025.xlsx"
```

**Schritt 4: Optional - Puffer manuell flushen**

```powershell
# Puffer für spezifisches Datum flushen
$flushUrl = "$baseUrl/buffer/flush?date=2025-10-12"

$flushResponse = Invoke-RestMethod `
    -Uri $flushUrl `
    -Method POST `
    -Headers @{"KWF-Device-Key" = $apiKey}

Write-Host "✓ Puffer geflusht: $($flushResponse.message)"
```

### Wichtige URLs

| Endpoint | URL |
|----------|-----|
| **Produktion** | `https://telemetry-api-325255315766.europe-west6.run.app` |
| Health Check | `https://telemetry-api-325255315766.europe-west6.run.app/health` |
| Telemetrie POST | `https://telemetry-api-325255315766.europe-west6.run.app/telemetry` |
| Export GET | `https://telemetry-api-325255315766.europe-west6.run.app/export` |
| Pufferstatus GET | `https://telemetry-api-325255315766.europe-west6.run.app/buffer/stats` |
| Puffer Flush POST | `https://telemetry-api-325255315766.europe-west6.run.app/buffer/flush` |

### Geräte-API-Schlüssel

Die folgenden Geräte sind konfiguriert:

| Device ID | Verwendung |
|-----------|------------|
| `emon01` | Produktionsgerät 1 |
| `emon02` | Produktionsgerät 2 |
| `emon03` | Produktionsgerät 3 |
| `testmon00` | Testgerät für Entwicklung |
| `testmon01` | Testgerät für Batch-Tests |

**Hinweis:** Die tatsächlichen API-Schlüssel sind in Google Secret Manager gespeichert.

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

### Wichtige Hinweise zur Batch-Speicherung

#### Puffer-Verhalten

Das System puffert Daten **im Speicher** und schreibt sie in Batches:

1. **Automatisches Flushing**: 
   - Erfolgt bei 2.000 Datenpunkten pro Sensor+Tag
   - Verhindert zu große Dokumente

2. **Datenverlust-Risiko**:
   - ⚠️ Puffer ist im Speicher - Daten gehen bei Service-Neustart verloren
   - ✅ Durch automatisches Flushing bei 2.000 Punkten minimiert
   - 💡 **Empfehlung**: Geplantes stündliches Flushing einrichten

3. **Monitoring**:
   - Pufferstatus prüfen: `GET /buffer/stats`
   - Manuelles Flushing: `POST /buffer/flush`

#### Batch-Größe konfigurieren

In `src/services/batch_buffer.py`:
```python
class BatchBuffer:
    MAX_POINTS_PER_BATCH = 2000  # Diesen Wert ändern
```

**Empfohlener Bereich**: 1.000 - 3.000 Datenpunkte
- Unter 1.000: Zu viele Schreibvorgänge
- Über 3.000: Risiko zu großer Dokumente

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

### Firestore Batch-Speicherung

Das System verwendet eine hochoptimierte Batch-Speicherung:

- **Vorher** (einzelne Dokumente):
  - ~8.640 Schreibvorgänge pro Tag und Gerät
  - ~259.200 Schreibvorgänge pro Monat
  - Kosten: $0.47/Monat pro Gerät (nach Free Tier)

- **Nachher** (Batch-Dokumente mit 2.000 Punkten):
  - ~5 Schreibvorgänge pro Tag und Gerät
  - ~130 Schreibvorgänge pro Monat
  - **Kosten: $0.00/Monat (innerhalb Free Tier!)**
  - **Einsparung: >99% Reduktion**

- **Abfrage-Optimierung**:
  - Organisiert nach Jahr/Monat/Tag
  - Nur ~5 Dokument-Lesevorgänge pro Tag (statt 8.640)
  - Effiziente Datumsbereichsabfragen

### Cloud Run

- **Pay per request**: Auto-Scaling auf Null bei Inaktivität
- **Konfiguration**: `--min-instances=0` für maximale Kosteneinsparung
- **Cold Starts**: Akzeptabel für Telemetrie-Anwendung

### Secret Manager

- **Caching**: API-Keys werden im Speicher gecacht
- **Minimale Zugriffe**: Nur beim ersten Request nach Neustart

## Future Enhancements

### Empfohlene nächste Schritte

- [ ] **Persistenter Puffer** (Hohe Priorität)
  - Pufferzustand in Firestore oder Cloud Storage speichern
  - Wiederherstellung nach Service-Neustart
  - Verhindert Datenverlust

- [ ] **Geplantes Flushing** (Hohe Priorität)
  - Cloud Scheduler Job für periodisches Flushing (z.B. stündlich)
  - Automatisches Flushing um Mitternacht (UTC)
  - Erhöht Datensicherheit

- [ ] **Puffer-Monitoring Dashboard**
  - Visualisierung der gepufferten Daten
  - Alerts bei Anomalien
  - Überwachung pro Gerät/Sensor

- [ ] Datenaggregation (stündliche/tägliche Zusammenfassungen)
- [ ] Gerätestatus-Monitoring implementieren
- [ ] Webhook-Benachrichtigungen für Alarme
- [ ] Admin-Dashboard erstellen
- [ ] Datenaufbewahrungsrichtlinien
- [ ] Backup-Strategie implementieren

## Support

For questions or issues:
- Email: energiemonitor@kleinwohnformen.ch
- GitHub: https://github.com/Verein-Kleinwohnformen

## License

Open Source - maintained by [Verein Kleinwohnformen](https://kleinwohnformen.ch)
