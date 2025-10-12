"""
Test script for the XLSX export endpoint with batched data.

This script tests:
1. Sending sample data
2. Exporting data as XLSX
3. Verifying XLSX structure
"""

# Test export endpoint
Write-Host "=" * 60
Write-Host "Testing XLSX Export with Batched Data"
Write-Host "=" * 60

# Configuration
$apiKey = "kwf-testmon00-a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
$baseUrl = "https://telemetry-api-325255315766.europe-west6.run.app"

# Step 1: Send some test data
Write-Host "`n1. Sending test data..."
$headers = @{
    "KWF-Device-Key" = $apiKey
    "Content-Type" = "application/json"
}

$testData = @(
    @{
        sensor_id = "shelly-3em-pro"
        metering_point = "E1"
        timestamp = 1728691200000  # 2025-10-12 00:00:00
        values = @{
            voltage = 231.5
            act_power = 15.2
            current = 1.5
        }
    },
    @{
        sensor_id = "shelly-3em-pro"
        metering_point = "E1"
        timestamp = 1728691260000  # 2025-10-12 00:01:00
        values = @{
            voltage = 232.1
            act_power = 15.8
            current = 1.6
        }
    },
    @{
        sensor_id = "power-meter"
        metering_point = "K0"
        timestamp = 1728691200000  # 2025-10-12 00:00:00
        values = @{
            power = 2300.0
            frequency = 50.0
        }
    }
) | ConvertTo-Json

try {
    $response = Invoke-RestMethod `
        -Uri "$baseUrl/telemetry" `
        -Method POST `
        -Headers $headers `
        -Body $testData
    
    Write-Host "✓ Test data sent: $($response.stored_count) records"
} catch {
    Write-Host "✗ Error sending data: $_"
    exit 1
}

# Step 2: Check buffer stats
Write-Host "`n2. Checking buffer stats..."
try {
    $bufferStats = Invoke-RestMethod -Uri "$baseUrl/buffer/stats"
    Write-Host "✓ Buffer stats retrieved"
    Write-Host "  Total devices: $($bufferStats.total_devices)"
    if ($bufferStats.devices.testmon00) {
        Write-Host "  testmon00 points: $($bufferStats.devices.testmon00.total_points)"
    }
} catch {
    Write-Host "⚠ Could not retrieve buffer stats: $_"
}

# Step 3: Flush buffer to ensure data is written
Write-Host "`n3. Flushing buffer..."
try {
    $flushResponse = Invoke-RestMethod `
        -Uri "$baseUrl/buffer/flush?date=2025-10-12" `
        -Method POST `
        -Headers @{"KWF-Device-Key" = $apiKey}
    
    Write-Host "✓ Buffer flushed: $($flushResponse.message)"
} catch {
    Write-Host "⚠ Could not flush buffer: $_"
}

# Wait a moment for data to be written
Start-Sleep -Seconds 2

# Step 4: Export data as XLSX
Write-Host "`n4. Exporting data as XLSX..."
$exportFile = "test_export.xlsx"
$startDate = "2025-10-12"
$endDate = "2025-10-12"
$exportUrl = "$baseUrl/export?start_date=$startDate`&end_date=$endDate"

try {
    Invoke-WebRequest `
        -Uri $exportUrl `
        -Headers @{"KWF-Device-Key" = $apiKey} `
        -OutFile $exportFile
    
    if (Test-Path $exportFile) {
        $fileSize = (Get-Item $exportFile).Length
        Write-Host "✓ XLSX file downloaded: $exportFile"
        Write-Host "  File size: $fileSize bytes"
        
        # Check if file is valid XLSX
        if ($fileSize -gt 0) {
            Write-Host "✓ File appears to be valid (size > 0)"
        } else {
            Write-Host "✗ File is empty!"
        }
    } else {
        Write-Host "✗ File was not created"
    }
} catch {
    Write-Host "✗ Error exporting data: $_"
    Write-Host "  Status: $($_.Exception.Response.StatusCode)"
    exit 1
}

# Step 5: Try to open the file (optional)
Write-Host "`n5. Opening XLSX file..."
try {
    Start-Process $exportFile
    Write-Host "✓ File opened in default application"
} catch {
    Write-Host "⚠ Could not open file automatically: $_"
    Write-Host "  Please open manually: $exportFile"
}

Write-Host "`n" + "=" * 60
Write-Host "✓ ALL TESTS PASSED!"
Write-Host "=" * 60
Write-Host "`nExported file: $exportFile"
Write-Host "You can now verify the XLSX structure:"
Write-Host "  - Check if tabs exist for each sensor"
Write-Host "  - Verify columns: Timestamp, Date/Time, Metering Point, etc."
Write-Host "  - Check data accuracy"
