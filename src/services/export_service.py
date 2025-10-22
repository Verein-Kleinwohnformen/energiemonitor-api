"""Export service for generating XLSX files"""
import os
import tempfile
import gc
from typing import Tuple, Optional
from collections import defaultdict
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
                     end_timestamp: int) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate XLSX file with sensor data using memory-optimized write-only mode
        
        Args:
            device_id: Device identifier
            start_timestamp: Start time in milliseconds
            end_timestamp: End time in milliseconds
            
        Returns:
            Tuple of (file_path: str, error: str)
        """
        try:
            logger.info(f"Starting XLSX generation for device {device_id}")
            
            # Get all telemetry data for the period
            data = self.firebase_service.get_telemetry_data(
                device_id, 
                start_timestamp, 
                end_timestamp
            )
            
            if not data:
                return None, "No data found for the specified period"
            
            logger.info(f"Retrieved {len(data)} data points")
            
            # Group data by sensor_id (in memory, but necessary for separate sheets)
            sensor_data = defaultdict(list)
            for entry in data:
                sensor_id = entry.get('sensor_id', 'unknown')
                sensor_data[sensor_id].append(entry)
            
            # Clear original data list to free memory
            del data
            gc.collect()
            
            # Create workbook in write-only mode for better memory efficiency
            wb = openpyxl.Workbook(write_only=True)
            
            # Create a tab for each sensor
            for sensor_id, entries in sensor_data.items():
                logger.info(f"Processing sensor {sensor_id} with {len(entries)} entries")
                ws = wb.create_sheet(title=self._sanitize_sheet_name(sensor_id))
                
                # Get all unique value fields across all entries
                value_fields = set()
                for entry in entries:
                    value_fields.update(entry.get('values', {}).keys())
                value_fields = sorted(list(value_fields))
                
                # Create header row with styling
                headers = ['Timestamp', 'Date/Time', 'Metering Point', 'Sensor ID'] + value_fields
                header_cells = []
                for header_text in headers:
                    cell = WriteOnlyCell(ws, value=header_text)
                    cell.font = Font(bold=True)
                    cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
                    header_cells.append(cell)
                ws.append(header_cells)
                
                # Add data rows (sorted by timestamp)
                entries.sort(key=lambda x: x.get('timestamp', 0))
                for entry in entries:
                    timestamp = entry.get('timestamp', 0)
                    dt = datetime.fromtimestamp(timestamp / 1000)
                    
                    row = [
                        timestamp,
                        dt.strftime('%Y-%m-%d %H:%M:%S'),
                        entry.get('metering_point', ''),
                        entry.get('sensor_id', '')
                    ]
                    
                    # Add value fields
                    values = entry.get('values', {})
                    for field in value_fields:
                        row.append(values.get(field, ''))
                    
                    ws.append(row)
                
                # Clear entries for this sensor to free memory
                sensor_data[sensor_id] = None
                gc.collect()
                
                logger.info(f"Completed sensor {sensor_id}")
            
            # Save to temporary file
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, f'energiemonitor_{device_id}_{start_timestamp}.xlsx')
            
            logger.info(f"Saving XLSX to {file_path}")
            wb.save(file_path)
            
            # Clean up
            del wb
            del sensor_data
            gc.collect()
            
            logger.info("XLSX generation complete")
            return file_path, None
            
        except Exception as e:
            return None, f"Failed to generate XLSX: {str(e)}"
    
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
