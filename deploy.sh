#!/bin/bash

# Deployment script for KWF Energiemonitor API to Google Cloud Run
# Usage: ./deploy.sh [PROJECT_ID]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get project ID from argument or prompt
if [ -z "$1" ]; then
    read -p "Enter your GCP Project ID: " PROJECT_ID
else
    PROJECT_ID=$1
fi

echo -e "${GREEN}Starting deployment to Google Cloud Run...${NC}"
echo -e "Project ID: ${YELLOW}$PROJECT_ID${NC}"

# Set the project
echo -e "\n${YELLOW}Setting GCP project...${NC}"
gcloud config set project $PROJECT_ID

# Check if Secret Manager secret exists
echo -e "\n${YELLOW}Checking for device keys in Secret Manager...${NC}"
if ! gcloud secrets describe energiemonitor-device-keys &> /dev/null; then
    echo -e "${RED}Secret 'energiemonitor-device-keys' not found!${NC}"
    echo -e "Please create it first with:"
    echo -e "  ${YELLOW}gcloud secrets create energiemonitor-device-keys --data-file=keys.json${NC}"
    exit 1
fi

# Enable required APIs
echo -e "\n${YELLOW}Enabling required APIs...${NC}"
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable firestore.googleapis.com
gcloud services enable secretmanager.googleapis.com

# Build and deploy
echo -e "\n${YELLOW}Building and deploying to Cloud Run...${NC}"
gcloud run deploy energiemonitor-api \
  --source . \
  --region europe-west6 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars GCP_PROJECT=$PROJECT_ID \
  --memory 512Mi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 10 \
  --min-instances 0

# Get the service URL
SERVICE_URL=$(gcloud run services describe energiemonitor-api --region europe-west6 --format 'value(status.url)')

echo -e "\n${GREEN}✓ Deployment successful!${NC}"
echo -e "\nService URL: ${YELLOW}$SERVICE_URL${NC}"
echo -e "\nEndpoints:"
echo -e "  - Health: ${YELLOW}$SERVICE_URL/health${NC}"
echo -e "  - Telemetry: ${YELLOW}$SERVICE_URL/telemetry${NC}"
echo -e "  - Export: ${YELLOW}$SERVICE_URL/export${NC}"
echo -e "\nTest with:"
echo -e "  ${YELLOW}curl $SERVICE_URL/health${NC}"
