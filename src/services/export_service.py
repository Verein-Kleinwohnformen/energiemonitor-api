"""Export service for generating XLSX files"""
import os
import json
import shutil
import tempfile
import gc
from typing import Tuple, Optional
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.cell import WriteOnlyCell
from services.firebase_service import FirebaseService
import logging

logger = logging.getLogger(__name__)

class ExportService:
    """Handles data export to XLSX format with memory optimization"""
    
    def __init__(self):
        """Initialize export service"""
        self.firebase_service = FirebaseService()
    
    def generate_xlsx(self, 
                     device_id: str, 
                     start_timestamp: int, 
                     end_timestamp: int,
                     include_manual: bool = True,
                     manual_only: bool = False) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate XLSX file with automatic and/or manual sensor data using memory-optimized write-only mode
        
        Args:
            device_id: Device identifier
            start_timestamp: Start time in milliseconds
            end_timestamp: End time in milliseconds
            include_manual: Include manual data (default: True)
            manual_only: Export only manual data (default: False)
            
        Returns:
            Tuple of (file_path: str, error: str)
        """
        try:
            logger.info(f"Starting XLSX generation for device {device_id} (include_manual={include_manual}, manual_only={manual_only})")
            
            # Get manual data (if requested); small, kept in memory
            manual_data = [] if not include_manual else self.firebase_service.get_manual_data(
                device_id,
                start_timestamp,
                end_timestamp
            )

            # Telemetry is streamed to per-sensor spool files on disk so that only one
            # Firestore document is in memory at a time (large ranges used to OOM Cloud Run)
            spool_dir = tempfile.mkdtemp(prefix='export_')
            spool_files = {}  # sensor_id -> open file
            value_fields = {}  # sensor_id -> set of value field names
            row_counts = {}  # sensor_id -> number of rows

            try:
                if not manual_only:
                    for entry in self.firebase_service.iter_telemetry_data(
                            device_id, start_timestamp, end_timestamp):
                        sensor_id = entry.get('sensor_id') or 'unknown'
                        if sensor_id not in spool_files:
                            spool_files[sensor_id] = open(
                                os.path.join(spool_dir, f'{len(spool_files)}.jsonl'), 'w', encoding='utf-8')
                            value_fields[sensor_id] = set()
                            row_counts[sensor_id] = 0
                        values = entry.get('values', {})
                        value_fields[sensor_id].update(values.keys())
                        row_counts[sensor_id] += 1
                        spool_files[sensor_id].write(json.dumps({
                            't': entry.get('timestamp', 0),
                            'mp': entry.get('metering_point', ''),
                            'v': values
                        }) + '\n')

                for f in spool_files.values():
                    f.close()

                if not spool_files and not manual_data:
                    return None, "No data found for the specified period"

                logger.info(f"Retrieved telemetry rows per sensor: {row_counts} and {len(manual_data)} manual data points")

                # Create workbook in write-only mode for better memory efficiency
                wb = openpyxl.Workbook(write_only=True)

                # Create a tab for each sensor
                for index, sensor_id in enumerate(spool_files):
                    logger.info(f"Processing automatic sensor {sensor_id} with {row_counts[sensor_id]} entries")
                    ws = wb.create_sheet(title=self._sanitize_sheet_name(sensor_id))
                    fields = sorted(value_fields[sensor_id])

                    # Create header row with styling
                    headers = ['Timestamp', 'Date/Time', 'Metering Point', 'Sensor ID'] + fields
                    header_cells = []
                    for header_text in headers:
                        cell = WriteOnlyCell(ws, value=header_text)
                        cell.font = Font(bold=True)
                        cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
                        header_cells.append(cell)
                    ws.append(header_cells)

                    # Add data rows (sorted by timestamp); one sensor's compact rows at a time
                    with open(os.path.join(spool_dir, f'{index}.jsonl'), encoding='utf-8') as spool:
                        rows = [json.loads(line) for line in spool]
                    rows.sort(key=lambda r: r['t'])
                    for r in rows:
                        dt = datetime.fromtimestamp(r['t'] / 1000)
                        ws.append([r['t'], dt.strftime('%Y-%m-%d %H:%M:%S'), r['mp'], sensor_id]
                                  + [r['v'].get(field, '') for field in fields])

                    del rows
                    gc.collect()
                    logger.info(f"Completed automatic sensor {sensor_id}")

                # Manual data
                if manual_data:
                    ws_manual = wb.create_sheet(title="Manual")
                    self._write_manual_sheet(ws_manual, manual_data)
                    logger.info("Completed manual data sheet")

                del manual_data

                # Save to temporary file
                temp_dir = tempfile.gettempdir()
                file_path = os.path.join(temp_dir, f'energiemonitor_{device_id}_{start_timestamp}.xlsx')

                logger.info(f"Saving XLSX to {file_path}")
                wb.save(file_path)

                # Clean up
                del wb
                gc.collect()
            finally:
                for f in spool_files.values():
                    f.close()
                shutil.rmtree(spool_dir, ignore_errors=True)

            logger.info("XLSX generation complete")
            return file_path, None

        except Exception as e:
            logger.error(f"Failed to generate XLSX: {e}", exc_info=True)
            return None, f"Failed to generate XLSX: {str(e)}"
    
    def _write_combined_sheet(self, ws, telemetry_data: list, manual_data: list) -> None:
        """
        Write combined data (telemetry + manual) to Excel sheet.
        All data is sorted by timestamp for chronological view.
        
        Args:
            ws: Write-only worksheet
            telemetry_data: List of telemetry data points
            manual_data: List of manual data points
        """
        # Combine and sort by timestamp
        all_data = telemetry_data + manual_data
        all_data.sort(key=lambda x: x.get('timestamp', 0))
        
        # Headers
        headers = ['Timestamp', 'Date/Time', 'Type', 'Metering Point', 'Sensor ID', 'Data']
        header_cells = []
        for header_text in headers:
            cell = WriteOnlyCell(ws, value=header_text)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
            header_cells.append(cell)
        ws.append(header_cells)
        
        # Data rows
        for point in all_data:
            timestamp = point.get('timestamp', 0)
            dt = datetime.fromtimestamp(timestamp / 1000)
            
            # Determine if manual or automatic
            is_manual = 'metadata' in point
            data_type = 'Manual' if is_manual else 'Automatic'
            
            # Format values as string
            values = point.get('values', {})
            values_str = ', '.join([f"{k}={v}" for k, v in values.items()])
            
            row = [
                timestamp,
                dt.strftime('%Y-%m-%d %H:%M:%S'),
                data_type,
                point.get('metering_point', ''),
                point.get('sensor_id', ''),
                values_str
            ]
            
            ws.append(row)
    
    def _write_manual_sheet(self, ws, manual_data: list) -> None:
        """
        Write manual data to Excel sheet with special formatting.
        
        Columns:
        - Timestamp
        - Date
        - Time
        - Metering Point
        - Energy Type
        - Description
        - Added Quantity
        - Leftover Quantity
        - Consumed Quantity
        - Unit
        - Purchase Date
        - Estimated Usage Date
        - Provisory
        
        Args:
            ws: Write-only worksheet
            manual_data: List of manual data points
        """
        # Headers
        headers = [
            'Timestamp', 'Date', 'Time', 'Metering Point', 
            'Energy Type', 'Description',
            'Added Quantity', 'Leftover Quantity', 'Consumed Quantity', 'Unit',
            'Purchase Date', 'Estimated Usage Date', 'Provisory'
        ]
        
        header_cells = []
        for header_text in headers:
            cell = WriteOnlyCell(ws, value=header_text)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
            header_cells.append(cell)
        ws.append(header_cells)
        
        # Data rows
        for point in manual_data:
            timestamp = point.get('timestamp', 0)
            dt = datetime.fromtimestamp(timestamp / 1000)
            
            values = point.get('values', {})
            metadata = point.get('metadata', {})
            
            # Extract fields
            purchase_date_ts = metadata.get('purchase_date', timestamp)
            purchase_date = datetime.fromtimestamp(purchase_date_ts / 1000)
            
            usage_date_ts = metadata.get('estimated_usage_date', timestamp)
            usage_date = datetime.fromtimestamp(usage_date_ts / 1000)
            
            row = [
                timestamp,
                dt.strftime('%Y-%m-%d'),
                dt.strftime('%H:%M:%S'),
                point.get('metering_point', 'M0'),
                metadata.get('energy_type', 'unknown'),
                metadata.get('description', ''),
                values.get('added_quantity', 0),
                values.get('leftover_quantity', 0),
                values.get('consumed_quantity', 0),
                values.get('unit', ''),
                purchase_date.strftime('%Y-%m-%d %H:%M'),
                usage_date.strftime('%Y-%m-%d %H:%M'),
                'Ja' if metadata.get('usage_date_provisory', True) else 'Nein'
            ]
            
            ws.append(row)
    
    def _sanitize_sheet_name(self, name: str) -> str:
        """
        Sanitize sheet name to comply with Excel requirements
        Max 31 characters, no special characters
        """
        # Remove invalid characters
        invalid_chars = ['\\', '/', '*', '[', ']', ':', '?']
        for char in invalid_chars:
            name = name.replace(char, '_')
        
        # Truncate to 31 characters
        return name[:31]
