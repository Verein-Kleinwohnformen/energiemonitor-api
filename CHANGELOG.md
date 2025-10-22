# Changelog

All notable changes to the KWF Energiemonitor API project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2025-10-22

### Changed
- **BREAKING**: Export endpoint now limited to maximum 31-day period to prevent memory issues
- Increased Cloud Run memory allocation from 512Mi to 1Gi (1 GiB) for export operations
- Optimized XLSX export service to use write-only mode for better memory efficiency
- Added explicit garbage collection during XLSX generation to reduce memory footprint

### Added
- Export endpoint now validates date range and returns detailed error message if period exceeds 31 days
- Added logging to export service for better monitoring and debugging
- Memory optimization: Implemented incremental data clearing during XLSX generation
- Created CHANGELOG.md to track version history

### Fixed
- Resolved memory limit exceeded error (528 MiB) during large data exports
- Improved error messages for invalid date ranges (e.g., end_date before start_date)

## [1.0.0] - 2025-10-22

### Added
- Initial release of KWF Energiemonitor API
- Flask-based REST API for telemetry data ingestion
- Google Cloud Run deployment with Docker containerization
- Google Cloud Firestore integration for data storage
- Batch buffering system (up to 2,000 data points per document)
- UUID-based document naming for privacy and security
- Device authentication using Secret Manager
- XLSX export functionality with multi-sensor support
- Health check endpoint for Cloud Run
- Automated deployment via Cloud Build
- Per-request batching with immediate persistence (no data loss)
- Metering point-based architecture
- Support for multiple sensor types per metering point

### Features
- `/telemetry` endpoint for data ingestion (POST)
- `/export` endpoint for XLSX data export (GET)
- `/health` endpoint for service monitoring (GET)
- Automatic data batching and optimization
- Calendar-based data organization (year/month/day)
- Cost-optimized Firestore usage (within free tier for up to 80 devices)
- Memory-efficient batch processing
- Support for both ISO date and timestamp formats

### Documentation
- Comprehensive README with setup instructions
- API endpoint documentation with examples
- Firestore data structure documentation
- Cost calculation and optimization guide
- Deployment guide for GCP
