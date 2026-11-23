"""GET /export: Firebase-Login mit monitor_read, Uebergang mit Device-Key"""
import os
import sys
import tempfile
import types
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

TOKENS = {'tok-anna': 'uid-anna', 'tok-ben': 'uid-ben'}
USERS = {'uid-anna': ['emon01'], 'uid-ben': ['emon02']}


@pytest.fixture
def make_client(monkeypatch):
    google = types.ModuleType('google')
    cloud = types.ModuleType('google.cloud')
    firestore = types.ModuleType('google.cloud.firestore')
    firestore.Client = MagicMock()
    firestore.ArrayUnion = lambda values: ('ArrayUnion', values)
    secretmanager = types.ModuleType('google.cloud.secretmanager')
    cloud.firestore = firestore
    cloud.secretmanager = secretmanager
    google.cloud = cloud
    for name, module in {'google': google, 'google.cloud': cloud,
                         'google.cloud.firestore': firestore,
                         'google.cloud.secretmanager': secretmanager}.items():
        monkeypatch.setitem(sys.modules, name, module)
    for name in [m for m in sys.modules
                 if m in ('api', 'services', 'middleware') or m.startswith(('api.', 'services.', 'middleware.'))]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setenv('GCP_PROJECT', 'demo-projekt')

    def build(allow_device_key='1'):
        monkeypatch.setenv('EXPORT_ALLOW_DEVICE_KEY', allow_device_key)
        from flask import Flask
        from middleware import auth, export_auth
        from api.routes import export

        keys = MagicMock()
        keys.get_device_keys.return_value = {'emon01': 'key-emon01'}
        monkeypatch.setattr(auth, 'firebase_service', keys)

        def verify(token):
            if token not in TOKENS:
                raise ValueError('bad token')
            return {'sub': TOKENS[token]}
        monkeypatch.setattr(export_auth, '_verify_id_token', verify)
        monkeypatch.setattr(export_auth, '_monitor_read', lambda uid: USERS.get(uid, []))

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
        tmp.close()
        service = MagicMock()
        service.generate_xlsx.return_value = (tmp.name, None)
        monkeypatch.setattr(export, 'export_service', service)

        app = Flask(__name__)
        app.register_blueprint(export.export_bp)
        return app.test_client(), service
    return build


QUERY = '/export?start_date=2026-11-01&end_date=2026-11-07'


def test_firebase_login_with_read_access(make_client):
    client, service = make_client()
    r = client.get(QUERY + '&device_id=emon01', headers={'Authorization': 'Bearer tok-anna'})
    assert r.status_code == 200
    assert service.generate_xlsx.call_args.kwargs['device_id'] == 'emon01'


def test_firebase_login_without_read_access(make_client):
    client, service = make_client()
    r = client.get(QUERY + '&device_id=emon01', headers={'Authorization': 'Bearer tok-ben'})
    assert r.status_code == 403
    service.generate_xlsx.assert_not_called()


def test_invalid_token(make_client):
    client, _ = make_client()
    r = client.get(QUERY + '&device_id=emon01', headers={'Authorization': 'Bearer falsch'})
    assert r.status_code == 401


def test_device_id_required_with_login(make_client):
    client, _ = make_client()
    r = client.get(QUERY, headers={'Authorization': 'Bearer tok-anna'})
    assert r.status_code == 400


def test_no_authentication(make_client):
    client, _ = make_client()
    assert client.get(QUERY + '&device_id=emon01').status_code == 401


def test_device_key_during_transition(make_client):
    client, service = make_client('1')
    r = client.get(QUERY, headers={'KWF-Device-Key': 'key-emon01'})
    assert r.status_code == 200
    assert service.generate_xlsx.call_args.kwargs['device_id'] == 'emon01'
    assert client.get(QUERY, headers={'KWF-Device-Key': 'falsch'}).status_code == 401


def test_device_key_switched_off(make_client):
    client, service = make_client('0')
    r = client.get(QUERY, headers={'KWF-Device-Key': 'key-emon01'})
    assert r.status_code == 401
    service.generate_xlsx.assert_not_called()


def test_device_id_param_ignored_with_device_key(make_client):
    """Mit Device-Key bestimmt der Schluessel das Geraet, nicht der Parameter."""
    client, service = make_client('1')
    r = client.get(QUERY + '&device_id=emon02', headers={'KWF-Device-Key': 'key-emon01'})
    assert r.status_code == 200
    assert service.generate_xlsx.call_args.kwargs['device_id'] == 'emon01'
