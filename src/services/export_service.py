"""Export service for generating XLSX files"""
import os
import tempfile
from typing import Tuple, Optional
from collections import defaultdict
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill
from services.firebase_service import FirebaseService

class ExportService:
    """Handles data export to XLSX format"""
    
    def __init__(self):
        """Initialize export service"""
        self.firebase_service = FirebaseService()
    
    def generate_xlsx(self, 
                     device_id: str, 
                     start_timestamp: int, 
                     end_timestamp: int) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate XLSX file with sensor data
        
        Args:
            device_id: Device identifier
            start_timestamp: Start time in milliseconds
            end_timestamp: End time in milliseconds
            
        Returns:
            Tuple of (file_path: str, error: str)
        """
        try:
            # Get all telemetry data for the period
            data = self.firebase_service.get_telemetry_data(
                device_id, 
                start_timestamp, 
                end_timestamp
            )
            
            if not data:
                return None, "No data found for the specified period"
            
            # Group data by sensor_id
            sensor_data = defaultdict(list)
            for entry in data:
                sensor_id = entry.get('sensor_id', 'unknown')
                sensor_data[sensor_id].append(entry)
            
            # Create workbook
            wb = openpyxl.Workbook()
            wb.remove(wb.active)  # Remove default sheet
            
            # Create a tab for each sensor
            for sensor_id, entries in sensor_data.items():
                ws = wb.create_sheet(title=self._sanitize_sheet_name(sensor_id))
                
                # Get all unique value fields across all entries
                value_fields = set()
                for entry in entries:
                    value_fields.update(entry.get('values', {}).keys())
                value_fields = sorted(list(value_fields))
                
                # Create header row
                headers = ['Timestamp', 'Date/Time', 'Metering Point', 'Sensor ID'] + value_fields
                ws.append(headers)
                
                # Style header
                header_font = Font(bold=True)
                header_fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
                for cell in ws[1]:
                    cell.font = header_font
                    cell.fill = header_fill
                
                # Add data rows
                for entry in sorted(entries, key=lambda x: x.get('timestamp', 0)):
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
                
                # Auto-adjust column widths
                for column in ws.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    ws.column_dimensions[column_letter].width = adjusted_width
            
            # Save to temporary file
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, f'energiemonitor_{device_id}_{start_timestamp}.xlsx')
            wb.save(file_path)
            
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
