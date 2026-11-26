"""Metadaten der Messpunkte: ein Lese- und ein Schreibvorgang pro Messpunkt und Anfrage."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

from fake_firestore import FakeFirestore  # noqa: E402
from services.firebase_service import FirebaseService  # noqa: E402


def service(db):
    svc = object.__new__(FirebaseService)
    svc.db = db
    return svc


def doc(mp, sensor, start, end, fields):
    return {'metering_point': mp, 'sensor_id': sensor, 'start_timestamp': start, 'end_timestamp': end,
            'data_points': [{'timestamp': end, 'values': {f: 1.0 for f in fields}}]}


def test_one_read_and_write_per_metering_point():
    db = FakeFirestore()
    db.store['devices/d/metering_points/K0'] = {'metering_point': 'K0', 'last_seen': 50}
    docs = [doc('K0', 'netatmo', 10, 100, ['temperature_indoor']),
            doc('K0', 'sensirion_scd4x', 10, 120, ['co2_indoor']),
            doc('K0', 'sensirion_voc', 10, 90, ['voc_index']),
            doc('E1', 'victron', 5, 110, ['power'])]
    service(db)._update_metering_points('d', docs)
    assert db.reads == 2 and db.writes == 2
    assert db.store['devices/d/metering_points/K0']['last_seen'] == 120
    e1 = db.store['devices/d/metering_points/E1']
    assert (e1['first_seen'], e1['last_seen'], e1['value_fields']) == (5, 110, ['power'])


def test_last_seen_never_goes_back():
    db = FakeFirestore()
    db.store['devices/d/metering_points/E1'] = {'metering_point': 'E1', 'last_seen': 500}
    service(db)._update_metering_points('d', [doc('E1', 'victron', 5, 110, ['power'])])
    assert db.store['devices/d/metering_points/E1']['last_seen'] == 500
