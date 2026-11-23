"""Zugriff auf GET /export.

Die App meldet sich mit dem Firebase-Login der Person an:
    Authorization: Bearer <Firebase-ID-Token>
    ?device_id=<Monitor>
Die API prueft das Token (Projekt aus GCP_PROJECT) und erlaubt nur Monitore,
die im User-Dokument unter monitor_read stehen, gleich wie die Firestore-Rules.

Uebergang: Solange EXPORT_ALLOW_DEVICE_KEY nicht "0" ist, geht der Export auch
noch mit dem Header KWF-Device-Key (alte App-Versionen, Skripte). Nach dem
Deploy der App EXPORT_ALLOW_DEVICE_KEY=0 setzen.
"""
import logging
import os
from functools import wraps

from flask import jsonify, request

from middleware.auth import device_id_for_key

logger = logging.getLogger(__name__)
_transport = None
_db = None


def _project_id() -> str:
    return os.environ.get('GCP_PROJECT', '').strip()


def _verify_id_token(token: str) -> dict:
    """Prueft ein Firebase-ID-Token und gibt die Claims zurueck."""
    global _transport
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token
    if _transport is None:
        _transport = google_requests.Request()
    project = _project_id()
    claims = id_token.verify_firebase_token(token, _transport, audience=project)
    if claims.get('iss') != f'https://securetoken.google.com/{project}':
        raise ValueError('wrong issuer')
    if not claims.get('sub'):
        raise ValueError('missing subject')
    return claims


def _monitor_read(uid: str) -> list:
    """monitor_read aus /users/{uid}, leere Liste wenn das Dokument fehlt."""
    global _db
    if _db is None:
        from google.cloud import firestore
        _db = firestore.Client()
    doc = _db.collection('users').document(uid).get()
    if not doc.exists:
        return []
    value = (doc.to_dict() or {}).get('monitor_read') or []
    return [str(v) for v in value] if isinstance(value, list) else []


def _device_key_allowed() -> bool:
    return os.environ.get('EXPORT_ALLOW_DEVICE_KEY', '1').strip() != '0'


def require_export_access(f):
    """Ruft f(device_id=...) auf, wenn die Person den Monitor lesen darf."""
    @wraps(f)
    def decorated(*args, **kwargs):
        header = request.headers.get('Authorization', '')
        if header.startswith('Bearer '):
            if not _project_id():
                return jsonify({'error': 'Not configured'}), 503
            try:
                claims = _verify_id_token(header[len('Bearer '):].strip())
            except Exception as e:
                logger.warning(f'Export: invalid ID token: {type(e).__name__}')
                return jsonify({'error': 'Invalid authentication'}), 401
            device_id = (request.args.get('device_id') or '').strip()
            if not device_id:
                return jsonify({'error': 'Missing required parameter: device_id'}), 400
            try:
                allowed = device_id in _monitor_read(claims['sub'])
            except Exception:
                logger.exception('Export: could not read user document')
                return jsonify({'error': 'Internal server error'}), 500
            if not allowed:
                return jsonify({'error': 'Forbidden'}), 403
            return f(device_id=device_id, *args, **kwargs)

        device_key = request.headers.get('KWF-Device-Key')
        if device_key and _device_key_allowed():
            device_id = device_id_for_key(device_key)
            if device_id:
                return f(device_id=device_id, *args, **kwargs)
            return jsonify({'error': 'Invalid authentication'}), 401

        return jsonify({'error': 'Missing authentication',
                        'message': 'Authorization: Bearer <Firebase-ID-Token> is required'}), 401
    return decorated
