# Deployment script for KWF Energiemonitor API to Google Cloud Run
# Usage: .\deploy.ps1 [PROJECT_ID]

param(
    [string]$ProjectId
)

$ErrorActionPreference = "Stop"

# Get project ID from parameter or prompt
if (-not $ProjectId) {
    $ProjectId = Read-Host "Enter your GCP Project ID"
}

Write-Host "Starting deployment to Google Cloud Run..." -ForegroundColor Green
Write-Host "Project ID: $ProjectId" -ForegroundColor Yellow

# Set the project
Write-Host "`nSetting GCP project..." -ForegroundColor Yellow
gcloud config set project $ProjectId

# Check if Secret Manager secret exists
Write-Host "`nChecking for device keys in Secret Manager..." -ForegroundColor Yellow
$secretExists = gcloud secrets describe energiemonitor-device-keys 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Secret 'energiemonitor-device-keys' not found!" -ForegroundColor Red
    Write-Host "Please create it first with:"
    Write-Host "  gcloud secrets create energiemonitor-device-keys --data-file=keys.json" -ForegroundColor Yellow
    exit 1
}

# Enable required APIs
Write-Host "`nEnabling required APIs..." -ForegroundColor Yellow
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable firestore.googleapis.com
gcloud services enable secretmanager.googleapis.com

# Build and deploy
Write-Host "`nBuilding and deploying to Cloud Run..." -ForegroundColor Yellow
gcloud run deploy energiemonitor-api `
  --source . `
  --region europe-west6 `
  --platform managed `
  --allow-unauthenticated `
  --set-env-vars GCP_PROJECT=$ProjectId `
  --memory 1Gi `
  --cpu 1 `
  --timeout 300 `
  --max-instances 10 `
  --min-instances 0

# Get the service URL
$ServiceUrl = gcloud run services describe energiemonitor-api --region europe-west6 --format 'value(status.url)'

Write-Host "`n[SUCCESS] Deployment successful!" -ForegroundColor Green
Write-Host "`nService URL: $ServiceUrl" -ForegroundColor Yellow
Write-Host "`nEndpoints:"
Write-Host "  - Health: $ServiceUrl/health" -ForegroundColor Yellow
Write-Host "  - Telemetry: $ServiceUrl/telemetry" -ForegroundColor Yellow
Write-Host "  - Export: $ServiceUrl/export" -ForegroundColor Yellow
Write-Host "`nTest with:"
Write-Host "  curl $ServiceUrl/health" -ForegroundColor Yellow
