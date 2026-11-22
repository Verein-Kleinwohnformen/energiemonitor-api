"""Route test for reserved "_q_*" keys, with Google Cloud libraries stubbed out"""
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture
def route(monkeypatch):
    # Stub google.cloud.firestore / secretmanager so the route can be imported offline
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
    for name in [m for m in sys.modules if m.startswith(('api.', 'services.', 'middleware.'))]:
        monkeypatch.delitem(sys.modules, name)

    from flask import Flask
    from api.routes import telemetry

    service = MagicMock()
    service.get_device_keys.return_value = {'emon01': 'key'}
    service.store_telemetry.return_value = (True, 'ok')
    service.store_telemetry_batch.return_value = (True, 'ok')
    service.update_data_quality.return_value = True
    monkeypatch.setattr(telemetry, 'firebase_service', service)

    import middleware.auth as auth
    monkeypatch.setattr(auth, 'firebase_service', service, raising=False)

    app = Flask(__name__)
    app.register_blueprint(telemetry.telemetry_bp)
    return app.test_client(), service


def post(client, body):
    return client.post('/telemetry', json=body, headers={'KWF-Device-Key': 'key'})


def test_reserved_keys_are_stripped_and_newest_quality_wins(route):
    client, service = route
    body = [
        {'sensor_id': 'apollon', 'metering_point': 'D1', 'timestamp': 1794220000000,
         'values': {'level_liter': 900, '_q_status': 'ok', '_q_tof_status': 0}},
        {'sensor_id': 'apollon', 'metering_point': 'D1', 'timestamp': 1794223600000,
         'values': {'level_liter': 918, '_q_status': 'degraded', '_q_tof_status': 2}},
    ]
    response = post(client, body)
    assert response.status_code == 200, response.json

    stored = [call.args[1]['values'] for call in service.store_telemetry.call_args_list]
    assert stored == [{'level_liter': 900}, {'level_liter': 918}]

    service.update_data_quality.assert_called_once_with(
        'emon01', 'D1', 'apollon', 1794223600000, {'status': 'degraded', 'tof_status': 2})


def test_quality_only_record_is_accepted_without_telemetry(route):
    client, service = route
    body = {'sensor_id': 'apollon', 'metering_point': 'D1', 'timestamp': 1794223600000,
            'values': {'_q_status': 'no_valid_data', '_q_tof_status': 7}}
    response = post(client, body)
    assert response.status_code == 200, response.json
    service.store_telemetry.assert_not_called()
    service.update_data_quality.assert_called_once()


def test_records_without_quality_keys_unchanged(route):
    client, service = route
    body = {'sensor_id': 'shelly-3em-pro', 'metering_point': 'E1', 'timestamp': 1794223600000,
            'values': {'voltage': 231.2}}
    response = post(client, body)
    assert response.status_code == 200, response.json
    assert service.store_telemetry.call_args.args[1]['values'] == {'voltage': 231.2}
    service.update_data_quality.assert_not_called()
