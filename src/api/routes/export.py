"""Data export endpoint for XLSX downloads"""
from flask import Blueprint, request, jsonify, send_file
from middleware.auth import require_device_key
from services.export_service import ExportService
from datetime import datetime

export_bp = Blueprint('export', __name__)
export_service = ExportService()

# Maximum allowed export period in days
MAX_EXPORT_DAYS = 31

@export_bp.route('/export', methods=['GET'])
@require_device_key
def export_data(device_id):
    """
    Export telemetry data as XLSX file
    
    Query parameters:
    - start_date: Start date in ISO format (YYYY-MM-DD) or timestamp (ms)
    - end_date: End date in ISO format (YYYY-MM-DD) or timestamp (ms)
    
    Maximum export period: 31 days
    
    Returns:
    XLSX file with separate tabs for each sensor
    """
    try:
        # Get query parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        if not start_date or not end_date:
            return jsonify({
                'error': 'Missing required parameters: start_date and end_date'
            }), 400
        
        # Convert dates to timestamps if needed
        try:
            # Try parsing as ISO date first
            if 'T' in start_date or '-' in start_date:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                start_ts = int(start_dt.timestamp() * 1000)
            else:
                start_ts = int(start_date)
                start_dt = datetime.fromtimestamp(start_ts / 1000)
                
            if 'T' in end_date or '-' in end_date:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                # If end_date is just a date (no time component), set to end of day
                if 'T' not in end_date:
                    end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999000)
                end_ts = int(end_dt.timestamp() * 1000)
            else:
                end_ts = int(end_date)
                end_dt = datetime.fromtimestamp(end_ts / 1000)
        except ValueError as e:
            return jsonify({
                'error': f'Invalid date format: {str(e)}'
            }), 400
        
        # Validate date range (maximum 31 days)
        time_diff = end_dt - start_dt
        if time_diff.days > MAX_EXPORT_DAYS:
            return jsonify({
                'error': f'Export period exceeds maximum allowed range of {MAX_EXPORT_DAYS} days',
                'requested_days': time_diff.days,
                'max_days': MAX_EXPORT_DAYS,
                'message': f'Please limit your export to {MAX_EXPORT_DAYS} days or less'
            }), 400
        
        if time_diff.days < 0:
            return jsonify({
                'error': 'Invalid date range: end_date must be after start_date'
            }), 400
        
        # Generate the XLSX file
        file_path, error = export_service.generate_xlsx(device_id, start_ts, end_ts)
        
        if error:
            return jsonify({'error': error}), 500
        
        # Send the file
        return send_file(
            file_path,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'energiemonitor_{device_id}_{start_date}_{end_date}.xlsx'
        )
        
    except Exception as e:
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500
