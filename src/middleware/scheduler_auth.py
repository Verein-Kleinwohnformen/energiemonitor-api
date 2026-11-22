"""Zugriff auf /aggregate nur für Cloud Scheduler (OIDC-Token eines Dienstkontos).

Umgebungsvariablen:
- AGGREGATE_AUDIENCE: erwartete Audience im Token (URL des Dienstes)
- AGGREGATE_INVOKERS: erlaubte Dienstkonten, mit Komma getrennt

Fehlt eine davon, lehnt der Endpunkt jeden Aufruf ab.
"""
import logging
import os
from functools import wraps

from flask import jsonify, request

logger = logging.getLogger(__name__)
_transport = None


def _verify(token: str, audience: str) -> dict:
    global _transport
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    if _transport is None:
        _transport = google_requests.Request()
    return id_token.verify_oauth2_token(token, _transport, audience=audience)


def require_scheduler(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        audience = os.environ.get('AGGREGATE_AUDIENCE', '').strip()
        invokers = {e.strip() for e in os.environ.get('AGGREGATE_INVOKERS', '').split(',') if e.strip()}
        if not audience or not invokers:
            return jsonify({'error': 'Not configured', 'message': 'AGGREGATE_AUDIENCE and AGGREGATE_INVOKERS are required'}), 503
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer '):
            return jsonify({'error': 'Missing authentication'}), 401
        try:
            claims = _verify(header[len('Bearer '):], audience)
        except Exception as e:
            logger.warning(f'Aggregate: invalid token: {e}')
            return jsonify({'error': 'Invalid authentication'}), 401
        if not claims.get('email_verified') or claims.get('email') not in invokers:
            return jsonify({'error': 'Forbidden'}), 403
        return f(*args, **kwargs)
    return decorated
