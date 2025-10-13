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

### Batch-Speicherung mit UUID-Dokumenten (Optimiert & Sicher)

Das System verwendet eine **optimierte Batch-Speicherung mit UUID-Dokumenten**, die bis zu 2.000 Datenpunkte pro Dokument gruppiert. Die Verwendung von UUIDs statt strukturierter Namen verhindert, dass sensible Informationen (Sensor-IDs, Messpunkte) in Dokumentpfaden sichtbar sind.

**Wichtig:** Daten werden **sofort nach jedem API-Request persistiert** - es gibt keine dauerhafte Pufferung zwischen Requests. Dies verhindert Datenverlust bei Service-Neustarts.

```
/devices/{device_id}/
  ├── telemetry/
  │   ├── {year}/
  │   │   └── {month}/
  │   │       └── {uuid}: {
  │   │           "sensor_id": "shelly-3em-pro",
  │   │           "device_id": "emon01",
  │   │           "metering_point": "E1",
  │   │           "date": "2025-10-12",
  │   │           "day": 12,                          // Integer für effiziente Queries
  │   │           "start_timestamp": 1728691200000,
  │   │           "end_timestamp": 1728777599999,
  │   │           "data_points": [
  │   │             {
  │   │               "timestamp": 1728691200000,
  │   │               "values": {
  │   │                 "voltage": 231.5,
  │   │                 "act_power": 15.2,
  │   │                 "current": 1.5
  │   │               }
  │   │             },
  │   │             // ... bis zu 2.000 Datenpunkte
  │   │           ],
  │   │           "count": 2000,
  │   │           "created_at": "2025-10-12T10:30:00Z"
  │   │         }
  └── metering_points/
      └── {metering_point}: {
          "metering_point": "E1",
          "device_id": "emon01",
          "sensor_types": ["victron", "shelly-3em-pro"],  // Array für mehrere Sensoren pro Messpunkt
          "first_seen": 1760084970005,
          "last_seen": 1760184970005,              // Aktualisiert bei jedem Request
          "value_fields": ["voltage", "act_power", "current"]  // Union aller Sensor-Felder
        }
```

**Hinweis:** Es gibt **kein separates Device-Dokument** mehr. Die `last_seen` Information wird direkt in den Messpunkt-Dokumenten gespeichert. Dies reduziert Schreibvorgänge um 78%.

**Messpunkt-basierte Architektur**: Die Struktur orientiert sich an den **physischen Messpunkten** (E1, E2, I1, K0), nicht an einzelnen Sensoren. Ein Messpunkt kann von mehreren Sensoren gleichzeitig gemessen werden (z.B. victron UND shelly-3em-pro an E1). Die `sensor_types` werden als Array gespeichert, wobei neue Sensor-Typen automatisch hinzugefügt werden.

### Vorteile der Architektur

- **Datenschutz & Sicherheit**:
  - UUID-Dokumentnamen verbergen sensible Informationen
  - Sensor-IDs und Messpunkte nicht in Pfaden sichtbar
  - Keine Kollisionen, keine Rückschlüsse möglich

- **Datensicherheit**:
  - **Sofortige Persistierung**: Daten werden am Ende jedes API-Requests geschrieben
  - **Kein Datenverlust**: Keine dauerhafte Pufferung zwischen Requests
  - **Serverless-sicher**: Funktioniert zuverlässig in Cloud Run-Umgebung

- **Kalender-basierte Abfragen**: Organisiert nach Jahr/Monat mit `day`-Feld
  - Effiziente Queries: `WHERE day == 12` (indexiert)
  - Ideal für XLSX-Exporte mit Datumsbereich
  - Abfragen von Mitternacht bis Mitternacht

- **Sensorisolierung**: Separate Dokumente pro Sensor + Messpunkt
  - Einfache Filterung nach Sensor-ID
  - Keine Vermischung verschiedener Sensoren

- **Dokumentgröße**: ~265 KB bei 2.000 Datenpunkten
  - Nur 26% des 1-MB-Limits
  - 74% Sicherheitsmarge

- **Write-Optimierung**:
  - Kein separates Device-Dokument (eliminiert redundante Writes)
  - `last_seen` direkt in Sensor-Dokumenten gespeichert
  - Sensor-Metadaten werden gecacht und nur einmal pro Request aktualisiert
  - Batch-Speicherung gruppiert bis zu 2.000 Datenpunkte pro Dokument

### Pufferung und Speicherung (Per-Request)

Das System verwendet **Per-Request-Batching** ohne dauerhafte Pufferung:

1. **Während des Requests**: Daten werden im Speicher gesammelt
2. **Am Ende des Requests**: Alle Daten werden sofort in Firestore geschrieben
3. **Nach dem Request**: Puffer wird geleert - keine Persistierung zwischen Requests

**Automatisches Splitting**: Wenn mehr als 2.000 Datenpunkte für einen Sensor+Tag eingehen, werden automatisch mehrere UUID-Dokumente erstellt.

**Beispiel-Dokumentpfade:**
```text
/devices/emon01/telemetry/2025/10/c7047a60-3fa8-48d4-aaf3-1f43d9b06aa9
/devices/emon01/telemetry/2025/10/fc2d9a4f-80bb-4c6f-b166-421403758a40
/devices/emon01/telemetry/2025/10/022677ff-7adc-4b21-8e92-9450d6ed7add
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
https://energiemonitor-api-325255315766.europe-west6.run.app
```

**Headers:**
- `KWF-Device-Key`: Device API-Schlüssel (erforderlich)

**Query Parameter:**
- `start_date`: Startdatum (ISO-Format YYYY-MM-DD oder Timestamp in ms)
- `end_date`: Enddatum (ISO-Format YYYY-MM-DD oder Timestamp in ms)

**Beispiele:**

```bash
# Mit ISO-Datum
GET https://energiemonitor-api-325255315766.europe-west6.run.app/export?start_date=2025-10-01&end_date=2025-10-31

# Mit Timestamp (Millisekunden)
GET https://energiemonitor-api-325255315766.europe-west6.run.app/export?start_date=1727740800000&end_date=1730419199999

# Mit PowerShell herunterladen
$headers = @{
    "KWF-Device-Key" = "your-device-api-key"
}

Invoke-WebRequest `
    -Uri "https://energiemonitor-api-325255315766.europe-west6.run.app/export?start_date=2025-10-01&end_date=2025-10-31" `
    -Headers $headers `
    -OutFile "energiemonitor_export.xlsx"

# Mit curl herunterladen
curl -H "KWF-Device-Key: your-device-api-key" \
     "https://energiemonitor-api-325255315766.europe-west6.run.app/export?start_date=2025-10-01&end_date=2025-10-31" \
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

## Verwendung / Usage

### Vollständiges Beispiel: Daten senden und exportieren

**Schritt 1: Telemetriedaten senden**

```powershell
# API-Schlüssel und URL definieren
$apiKey = "your-device-api-key"
$baseUrl = "https://energiemonitor-api-325255315766.europe-west6.run.app"

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

**Schritt 2: Daten als XLSX exportieren**

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

**Hinweis zu Schritt 2:**
Daten werden automatisch am Ende jedes Telemetrie-Requests gespeichert. Es ist kein manuelles Flushing mehr erforderlich. Die Daten stehen sofort für den Export zur Verfügung.

### Wichtige URLs

| Endpoint | URL |
|----------|-----|
| **Produktion** | `https://energiemonitor-api-325255315766.europe-west6.run.app` |
| Health Check | `https://energiemonitor-api-325255315766.europe-west6.run.app/health` |
| Telemetrie POST | `https://energiemonitor-api-325255315766.europe-west6.run.app/telemetry` |
| Export GET | `https://energiemonitor-api-325255315766.europe-west6.run.app/export` |

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

#### Per-Request-Batching (Neu)

Das System verwendet **Per-Request-Batching** für maximale Datensicherheit:

1. **Sofortige Persistierung**:
   - Alle Daten werden am Ende jedes `/telemetry` Requests geschrieben
   - Keine dauerhafte Pufferung zwischen Requests
   - ✅ Kein Datenverlust bei Service-Neustarts

2. **Automatisches Splitting**:
   - Dokumente werden bei 2.000 Datenpunkten pro Sensor+Tag gesplittet
   - Verhindert zu große Dokumente (1 MB Firestore-Limit)
   - Mehrere UUID-Dokumente werden automatisch erstellt

3. **Write-Optimierung**:
   - Device `last_seen` nur einmal pro Request aktualisiert
   - Sensor-Metadaten werden gecacht
   - ~80% Reduktion der Schreibvorgänge

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

## Cost Optimization & Firestore Usage

Das System verwendet hochoptimierte Batch-Speicherung ohne Device-Dokumente.

### Annahmen für Kostenberechnung

- **Geräte-Konfiguration:**
  - Daten-Upload: Stündlich (24 Requests/Tag pro Gerät)
  - Sensoren pro Gerät: 7 (Durchschnitt)
  - Datenpunkte pro Batch: ~360 (bei 10-Sekunden-Intervall = 3.600 Sekunden / 10)
  
- **Firestore Free Tier:**
  - 50.000 Dokument-Lesevorgänge pro Tag
  - 20.000 Dokument-Schreibvorgänge pro Tag
  - 1 GB Speicherplatz

### Kostenberechnung: 10 Geräte

**Monatliche Operationen:**

| Operation | Pro Request | Pro Tag | Pro Monat | Free Tier | Kosten |
|-----------|-------------|---------|-----------|-----------|--------|
| **Metering Point Reads** | 0.05 | 12 | 360 | 1.5M/Monat | $0.00 |
| **Metering Point Writes** (last_seen) | 0.7 | 168 | 5,040 | 600K/Monat | $0.00 |
| **Telemetry Writes** (batched) | 0.35 | 84 | 2,520 | 600K/Monat | $0.00 |
| **Total Reads** | **0.05** | **12** | **360** | 0.02% | **$0.00** |
| **Total Writes** | **1.05** | **252** | **7,560** | 1.26% | **$0.00** |

**Speicher:**
- ~265 KB pro Batch-Dokument (2.000 Datenpunkte)
- ~2.520 Dokumente/Monat = **~650 MB**
- Free Tier: 1 GB → **$0.00**

**Gesamtkosten: $0.00/Monat** ✅

---

### Kostenberechnung: 20 Geräte

**Monatliche Operationen:**

| Operation | Pro Tag | Pro Monat | Free Tier | Kosten @ $0.06/100K |
|-----------|---------|-----------|-----------|---------------------|
| **Metering Point Reads** | 24 | 720 | 1.5M/Monat | $0.00 |
| **Metering Point Writes** | 336 | 10,080 | 600K/Monat | $0.00 |
| **Telemetry Writes** | 168 | 5,040 | 600K/Monat | $0.00 |
| **Total Reads** | **24** | **720** | 0.05% | **$0.00** |
| **Total Writes** | **504** | **15,120** | 2.52% | **$0.00** |

**Speicher:**
- ~5.040 Dokumente/Monat = **~1.3 GB**
- Free Tier: 1 GB, Überschuss: 0.3 GB
- Kosten: 0.3 GB × $0.18/GB = **$0.054/Monat**

**Gesamtkosten: ~$0.05/Monat** ✅

---

### Skalierbarkeit

| Geräte | Reads/Monat | Writes/Monat | Speicher | Monatliche Kosten |
|--------|-------------|--------------|----------|-------------------|
| 10 | 360 | 7,560 | 650 MB | **$0.00** ✅ |
| 20 | 720 | 15,120 | 1.3 GB | **$0.05** ✅ |
| 50 | 1,800 | 37,800 | 3.3 GB | **$0.41** |
| 100 | 3,600 | 75,600 | 6.6 GB | **$1.00** |

**Free Tier Kapazität:** ~80 Geräte bevor Kosten entstehen

### Cloud Run

- **Pay per request**: Auto-Scaling auf Null bei Inaktivität
- **Konfiguration**: `--min-instances=0` für maximale Kosteneinsparung
- **Cold Starts**: Akzeptabel für Telemetrie-Anwendung

### Secret Manager

- **Caching**: API-Keys werden im Speicher gecacht
- **Minimale Zugriffe**: Nur beim ersten Request nach Neustart

## Future Enhancements

### Empfohlene nächste Schritte

- [ ] **Datenaggregation** (Hohe Priorität)
  - Stündliche/tägliche Zusammenfassungen
  - Reduziert Abfragekosten für Langzeit-Analysen
  - Pre-computed Statistiken

- [ ] **Gerätestatus-Monitoring**
  - Health-Checks für Geräte
  - Alarme bei Verbindungsabbruch
  - Dashboard für Device-Status

- [ ] **Datenaufbewahrungsrichtlinien**
  - Automatisches Archivieren alter Daten
  - Cold Storage für historische Daten
  - Compliance mit DSGVO

- [ ] **Admin-Dashboard**
  - Visualisierung der Telemetriedaten
  - Device-Management
  - Export-History

- [ ] **Webhook-Benachrichtigungen**
  - Alarme bei Anomalien
  - Integration mit externen Systemen
  - Push-Notifications

- [ ] **Backup-Strategie**
  - Automatische Firestore-Backups
  - Disaster Recovery Plan
  - Export zu BigQuery für Analytics

## Support

For questions or issues:
- Email: energiemonitor@kleinwohnformen.ch
- GitHub: https://github.com/Verein-Kleinwohnformen

## License

Open Source - maintained by [Verein Kleinwohnformen](https://kleinwohnformen.ch)
