"""Data export endpoint for XLSX downloads"""
from flask import Blueprint, request, jsonify, send_file
from middleware.auth import require_device_key
from services.export_service import ExportService
from datetime import datetime

export_bp = Blueprint('export', __name__)
export_service = ExportService()

@export_bp.route('/export', methods=['GET'])
@require_device_key
def export_data(device_id):
    """
    Export telemetry data as XLSX file
    
    Query parameters:
    - start_date: Start date in ISO format (YYYY-MM-DD) or timestamp (ms)
    - end_date: End date in ISO format (YYYY-MM-DD) or timestamp (ms)
    
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
                start_ts = int(datetime.fromisoformat(start_date.replace('Z', '+00:00')).timestamp() * 1000)
            else:
                start_ts = int(start_date)
                
            if 'T' in end_date or '-' in end_date:
                end_ts = int(datetime.fromisoformat(end_date.replace('Z', '+00:00')).timestamp() * 1000)
            else:
                end_ts = int(end_date)
        except ValueError as e:
            return jsonify({
                'error': f'Invalid date format: {str(e)}'
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
