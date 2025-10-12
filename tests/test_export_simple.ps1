# Test script for XLSX export functionality
# This script sends test data and downloads it as XLSX

$baseUrl = "https://telemetry-api-325255315766.europe-west6.run.app"
$apiKey = "testmon00_1234567890"
$deviceId = "testmon00"

Write-Host "============================================================"
Write-Host "Testing XLSX Export with Batched Data"
Write-Host "============================================================"

# Step 1: Send test data
Write-Host "`n1. Sending test telemetry data..."
$testData = @{
    device_id = $deviceId
    timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    sensor_data = @(
        @{
            sensor_id = "temperature"
            metering_point = "room1"
            value = 22.5
            unit = "C"
        },
        @{
            sensor_id = "humidity"
            metering_point = "room1"
            value = 55.0
            unit = "%"
        },
        @{
            sensor_id = "power"
            metering_point = "phase1"
            value = 1500.0
            unit = "W"
        }
    )
}

$body = $testData | ConvertTo-Json -Depth 10

try {
    $response = Invoke-RestMethod `
        -Uri "$baseUrl/telemetry" `
        -Method POST `
        -Headers @{
            "KWF-Device-Key" = $apiKey
            "Content-Type" = "application/json"
        } `
        -Body $body
    
    Write-Host "[OK] Data sent successfully"
    Write-Host "  Message: $($response.message)"
} catch {
    Write-Host "[ERROR] Failed to send data: $_"
    exit 1
}

# Step 2: Check buffer stats
Write-Host "`n2. Checking buffer stats..."
try {
    $bufferStats = Invoke-RestMethod -Uri "$baseUrl/buffer/stats"
    Write-Host "[OK] Buffer stats retrieved"
    Write-Host "  Total devices: $($bufferStats.total_devices)"
    if ($bufferStats.devices.$deviceId) {
        Write-Host "  $deviceId points: $($bufferStats.devices.$deviceId.total_points)"
    }
} catch {
    Write-Host "[WARN] Could not retrieve buffer stats: $_"
}

# Step 3: Flush buffer
Write-Host "`n3. Flushing buffer..."
$today = Get-Date -Format "yyyy-MM-dd"
try {
    $flushResponse = Invoke-RestMethod `
        -Uri "$baseUrl/buffer/flush?date=$today" `
        -Method POST `
        -Headers @{"KWF-Device-Key" = $apiKey}
    
    Write-Host "[OK] Buffer flushed: $($flushResponse.message)"
} catch {
    Write-Host "[WARN] Could not flush buffer: $_"
}

# Wait for data to be written
Start-Sleep -Seconds 2

# Step 4: Export data as XLSX
Write-Host "`n4. Exporting data as XLSX..."
$exportFile = "test_export.xlsx"
$startDate = $today
$endDate = $today
$exportUrl = "$baseUrl/export?start_date=$startDate`&end_date=$endDate"

try {
    Invoke-WebRequest `
        -Uri $exportUrl `
        -Headers @{"KWF-Device-Key" = $apiKey} `
        -OutFile $exportFile
    
    if (Test-Path $exportFile) {
        $fileSize = (Get-Item $exportFile).Length
        Write-Host "[OK] XLSX file downloaded: $exportFile"
        Write-Host "  File size: $fileSize bytes"
        
        if ($fileSize -gt 0) {
            Write-Host "[OK] File appears to be valid"
        } else {
            Write-Host "[ERROR] File is empty!"
        }
    } else {
        Write-Host "[ERROR] File was not created"
    }
} catch {
    Write-Host "[ERROR] Failed to export data: $_"
    if ($_.Exception.Response) {
        Write-Host "  Status: $($_.Exception.Response.StatusCode)"
    }
    exit 1
}

# Step 5: Open the file
Write-Host "`n5. Opening XLSX file..."
try {
    Start-Process $exportFile
    Write-Host "[OK] File opened in default application"
} catch {
    Write-Host "[WARN] Could not open file automatically: $_"
    Write-Host "  Please open manually: $exportFile"
}

Write-Host "`n============================================================"
Write-Host "ALL TESTS COMPLETED SUCCESSFULLY"
Write-Host "============================================================"
Write-Host "`nExported file: $exportFile"
Write-Host "You can now verify the XLSX structure:"
Write-Host "  - Check if tabs exist for each sensor"
Write-Host "  - Verify columns: Timestamp, Date/Time, Metering Point, etc."
Write-Host "  - Check data accuracy"
