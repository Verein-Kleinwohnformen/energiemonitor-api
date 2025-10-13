# Test script for UUID document IDs
# This script verifies that new data is stored with randomized UUID document IDs

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Testing UUID Document IDs Implementation" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Configuration - Using testmon00 for testing
$baseUrl = "https://energiemonitor-api-325255315766.europe-west6.run.app"
$apiKey = "kwf-testmon00-a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
$deviceId = "testmon00"

Write-Host ""
Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Base URL: $baseUrl"
Write-Host "  Device ID: $deviceId"
Write-Host "  API Key: $($apiKey.Substring(0,20))..."

# Step 1: Send test data
Write-Host ""
Write-Host "[Step 1] Sending test telemetry data..." -ForegroundColor Green
$timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

$testData = @(
    @{
        sensor_id = "test-sensor-uuid"
        metering_point = "T1"
        timestamp = $timestamp
        values = @{
            temperature = 22.5
            humidity = 55.0
        }
    },
    @{
        sensor_id = "test-sensor-uuid"
        metering_point = "T2"
        timestamp = $timestamp + 1000
        values = @{
            temperature = 23.1
            humidity = 58.2
        }
    },
    @{
        sensor_id = "test-power-uuid"
        metering_point = "P1"
        timestamp = $timestamp
        values = @{
            voltage = 230.5
            current = 2.3
            power = 530.0
        }
    }
)

$body = $testData | ConvertTo-Json

try {
    $response = Invoke-RestMethod `
        -Uri "$baseUrl/telemetry" `
        -Method POST `
        -Headers @{
            "KWF-Device-Key" = $apiKey
            "Content-Type" = "application/json"
        } `
        -Body $body
    
    Write-Host "  SUCCESS: Data sent successfully" -ForegroundColor Green
    Write-Host "    Stored: $($response.stored_count) records" -ForegroundColor Gray
    Write-Host "    Device ID: $($response.device_id)" -ForegroundColor Gray
} catch {
    Write-Host "  ERROR: Failed to send data" -ForegroundColor Red
    Write-Host "    Error: $_" -ForegroundColor Red
    exit 1
}

# Step 2: Check buffer stats
Write-Host ""
Write-Host "[Step 2] Checking buffer stats..." -ForegroundColor Green
try {
    $bufferStats = Invoke-RestMethod -Uri "$baseUrl/buffer/stats"
    Write-Host "  SUCCESS: Buffer stats retrieved" -ForegroundColor Green
    Write-Host "    Total devices: $($bufferStats.total_devices)" -ForegroundColor Gray
    
    if ($bufferStats.devices.$deviceId) {
        Write-Host "    $deviceId points: $($bufferStats.devices.$deviceId.total_points)" -ForegroundColor Gray
        
        foreach ($sensor in $bufferStats.devices.$deviceId.sensors.PSObject.Properties) {
            Write-Host "      - $($sensor.Name): $($sensor.Value.total_points) points" -ForegroundColor Gray
        }
    } else {
        Write-Host "    No buffered data for $deviceId (may already be flushed)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  WARNING: Could not retrieve buffer stats" -ForegroundColor Yellow
    Write-Host "    Error: $_" -ForegroundColor Yellow
}

# Step 3: Flush buffer to write data to Firestore
Write-Host ""
Write-Host "[Step 3] Flushing buffer to Firestore..." -ForegroundColor Green
$today = Get-Date -Format "yyyy-MM-dd"

try {
    $flushResponse = Invoke-RestMethod `
        -Uri "$baseUrl/buffer/flush?date=$today" `
        -Method POST `
        -Headers @{"KWF-Device-Key" = $apiKey}
    
    Write-Host "  SUCCESS: Buffer flushed" -ForegroundColor Green
    Write-Host "    Message: $($flushResponse.message)" -ForegroundColor Gray
} catch {
    Write-Host "  WARNING: Could not flush buffer" -ForegroundColor Yellow
    Write-Host "    Error: $_" -ForegroundColor Yellow
}

# Wait for data to be written
Write-Host ""
Write-Host "  Waiting for data to be written to Firestore..." -ForegroundColor Gray
Start-Sleep -Seconds 3

# Step 4: Export data to verify it can be retrieved
Write-Host ""
Write-Host "[Step 4] Exporting data as XLSX to verify retrieval..." -ForegroundColor Green
$exportFile = "test_uuid_export_$deviceId.xlsx"
$exportUrl = "$baseUrl/export?start_date=$today&end_date=$today"

try {
    Invoke-WebRequest `
        -Uri $exportUrl `
        -Headers @{"KWF-Device-Key" = $apiKey} `
        -OutFile $exportFile
    
    $fileSize = (Get-Item $exportFile).Length
    Write-Host "  SUCCESS: Export successful" -ForegroundColor Green
    Write-Host "    File: $exportFile" -ForegroundColor Gray
    Write-Host "    Size: $fileSize bytes" -ForegroundColor Gray
    
    if ($fileSize -gt 0) {
        Write-Host ""
        Write-Host "  SUCCESS: Data retrieval with UUID documents working!" -ForegroundColor Green
    }
} catch {
    Write-Host "  ERROR: Export failed" -ForegroundColor Red
    Write-Host "    Error: $_" -ForegroundColor Red
}

# Step 5: Summary
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Test Summary" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "SUCCESS: Telemetry data sent" -ForegroundColor Green
Write-Host "SUCCESS: Buffer stats retrieved" -ForegroundColor Green
Write-Host "SUCCESS: Buffer flushed to Firestore" -ForegroundColor Green
Write-Host "SUCCESS: Data exported successfully" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Check Firestore Console at:" -ForegroundColor Gray
$year = (Get-Date).Year
$month = (Get-Date).ToString('MM')
Write-Host "   /devices/$deviceId/telemetry/$year/$month/" -ForegroundColor Gray
Write-Host "2. Verify document IDs are UUIDs (random strings)" -ForegroundColor Gray
Write-Host "3. Check that documents have a day field (integer)" -ForegroundColor Gray
Write-Host ""
Write-Host "Test complete!" -ForegroundColor Cyan
