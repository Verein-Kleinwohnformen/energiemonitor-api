"""Entry point for the KWF energy monitor telemetry data API"""
import os
from flask import Flask
from api.routes.telemetry import telemetry_bp
from api.routes.export import export_bp

# Initialize Flask app
app = Flask(__name__)

# Register blueprints
app.register_blueprint(telemetry_bp)
app.register_blueprint(export_bp)

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Cloud Run"""
    return {'status': 'healthy'}, 200

if __name__ == '__main__':
    # Get port from environment variable (Cloud Run sets this)
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
