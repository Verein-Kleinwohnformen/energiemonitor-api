"""AggregationService gegen einen Firestore im Speicher, und der Endpunkt /aggregate."""
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402
from flask import Flask  # noqa: E402

from aggregation.series import TZ, day_bounds  # noqa: E402
from fake_firestore import FakeFirestore  # noqa: E402
from services.aggregation_service import AggregationService, heating_values_from  # noqa: E402

H = 3600_000
DEV = 'demo-haus'


def put_telemetry(db, mp, sensor, points):
    """Wie die API: ein Dokument pro UTC-Tag, Sensor und Messpunkt."""
    by_day = {}
    for ts, values in points:
        d = datetime.fromtimestamp(ts / 1000, timezone.utc).date()
        by_day.setdefault(d, []).append({'timestamp': ts, 'values': values})
    for d, pts in by_day.items():
        db.store[f'devices/{DEV}/telemetry/{d.year}/{d.month:02d}/{mp}-{sensor}-{d.isoformat()}'] = {
            'sensor_id': sensor, 'metering_point': mp, 'device_id': DEV, 'date': d.isoformat(), 'day': d.day,
            'start_timestamp': pts[0]['timestamp'], 'end_timestamp': pts[-1]['timestamp'], 'data_points': pts}
    db.store[f'devices/{DEV}/metering_points/{mp}'] = {'metering_point': mp}


def put_entry(db, ts, etype, mp, consumed, uid):
    d = datetime.fromtimestamp(ts / 1000, TZ)
    db.store[f'devices/{DEV}/manual/{d.year}/data/{uid}'] = {
        'sensor_id': 'app_form', 'metering_point': mp, 'start_timestamp': ts,
        'data_points': [{'timestamp': ts, 'values': {'consumed_quantity': consumed, 'unit': 'kg'}}],
        'metadata': {'purchase_date': ts, 'energy_type': etype}}


@pytest.fixture
def db():
    db = FakeFirestore()
    first = date(2026, 4, 20)
    s = day_bounds(first)[0] - 6 * H
    e = day_bounds(first + timedelta(days=6))[0]
    put_telemetry(db, 'E3', 'victron', [(t, {'power': 500.0 if 10 <= datetime.fromtimestamp(t / 1000, TZ).hour < 14
                                                  else 0.0}) for t in range(s, e, 10_000)])
    put_telemetry(db, 'I2', 'shelly-3em-pro', [(t, {'act_power': 0.0}) for t in range(s, e, 20_000)])
    temp = []
    for t in range(s, e, 600_000):
        d = datetime.fromtimestamp(t / 1000, TZ).date()
        evening = day_bounds(d)[0] + 20 * H
        v = 18.0
        if d in (date(2026, 4, 21), date(2026, 4, 24)) and evening <= t < evening + 4 * H:
            v = 18.0 + min(6.0, 6.0 * (t - evening) / H) - max(0, (t - evening - H) / H * 1.9)
        temp.append((t, {'temperature_indoor': v, 'temperature_outdoor': 8.0}))
    put_telemetry(db, 'K0', 'netatmo', temp)
    put_telemetry(db, 'K0', 'sensirion_scd4x', [(t, {'co2_indoor': 900.0 if (t // H) % 24 == 20 else 450.0})
                                               for t in range(s, e, 120_000)])
    db.store['config/factors'] = {'heating_values': {'pellets': {'value': 4.8, 'unit': 'kWh/kg'}}}
    put_entry(db, day_bounds(first)[0] + 9 * H, 'pellets', 'M2', 0, 'a')
    put_entry(db, day_bounds(date(2026, 4, 23))[0] + 9 * H, 'pellets', 'M2', 3.0, 'b')
    return db


def daily(db, d):
    return db.store.get(f'devices/{DEV}/daily/{d.isoformat()}')


def test_heating_values_from_config():
    assert heating_values_from({'heating_values': {'pellets': {'value': 4.8}, 'propane': 12.8, 'x': 'n/a'}}) == \
        {'pellets': 4.8, 'propane': 12.8}
    assert heating_values_from(None) == {}


def test_range_writes_daily_docs_and_allocation(db):
    svc = AggregationService(db)
    now = day_bounds(date(2026, 4, 26))[0]
    res = svc.run_device(DEV, [date(2026, 4, 20) + timedelta(days=i) for i in range(6)], now_ms=now,
                         full_realloc=True)
    assert res['written'] == 6
    d21 = daily(db, date(2026, 4, 21))
    assert d21['energy_kwh']['E3'] == pytest.approx(2.0, abs=0.01)
    assert d21['occupied'] is True
    assert len(d21['fire_events']) == 1
    assert d21['manual_alloc']['pellets']['quantity'] == pytest.approx(3.0)
    assert d21['manual_kwh_estimated']['pellets'] == pytest.approx(14.4)
    d24 = daily(db, date(2026, 4, 24))
    assert d24['manual_alloc']['pellets']['provisional'] is True
    assert d24['manual_alloc']['pellets']['quantity'] == pytest.approx(3.0)  # 3 kg pro Feuer gleicher Dauer
    assert db.store[f'devices/{DEV}/aggregation/state']['series']['M2|pellets']['entry_count'] == 2


def test_hourly_uses_state_and_new_entry_triggers_realloc(db):
    svc = AggregationService(db)
    days = [date(2026, 4, 20) + timedelta(days=i) for i in range(5)]
    svc.run_device(DEV, days, now_ms=day_bounds(date(2026, 4, 25))[0], full_realloc=True)

    today = date(2026, 4, 25)
    reads_before = db.reads
    res = svc.run_device(DEV, [today], now_ms=day_bounds(today)[0] + 12 * H)
    assert res['full_realloc'] is False
    assert db.store.get(f'devices/{DEV}/daily/2026-04-21') is not None
    fast_reads = db.reads - reads_before

    # Neuer Eintrag am 25.: Zeitraum 23. bis 25. ist jetzt abgeschlossen
    put_entry(db, day_bounds(today)[0] + 8 * H, 'pellets', 'M2', 1.5, 'c')
    res = svc.run_device(DEV, [today], now_ms=day_bounds(today)[0] + 12 * H)
    assert res['full_realloc'] is True
    assert res['reallocated'] >= 1
    d24 = daily(db, date(2026, 4, 24))
    assert d24['manual_alloc']['pellets']['provisional'] is False
    assert d24['manual_alloc']['pellets']['quantity'] == pytest.approx(1.5)
    assert d24['energy_kwh']['E3'] == pytest.approx(2.0, abs=0.01)  # gemessene Werte unverändert
    assert fast_reads < db.reads - reads_before - fast_reads


def test_backfill_in_blocks_then_realloc_from_start(db):
    svc = AggregationService(db)
    now = day_bounds(date(2026, 4, 26))[0]
    # Zwei Blöcke, der Zeitraum 20. bis 23. reicht über die Grenze
    svc.run_device(DEV, [date(2026, 4, 20), date(2026, 4, 21)], now_ms=now, full_realloc=True)
    svc.run_device(DEV, [date(2026, 4, 22) + timedelta(days=i) for i in range(4)], now_ms=now, full_realloc=True)
    res = svc.run_device(DEV, [date(2026, 4, 25)], now_ms=now, full_realloc=True, realloc_from=date(2026, 4, 20))
    assert res['full_realloc'] is True
    total = sum((daily(db, date(2026, 4, 20) + timedelta(days=i))['manual_alloc']['pellets']['quantity'] or 0)
                for i in range(3))
    assert total == pytest.approx(3.0)
    assert daily(db, date(2026, 4, 21))['manual_alloc']['pellets']['quantity'] == pytest.approx(3.0)


def test_dry_run_writes_nothing(db):
    svc = AggregationService(db)
    before = dict(db.store)
    res = svc.run_device(DEV, [date(2026, 4, 21)], now_ms=day_bounds(date(2026, 4, 26))[0], dry_run=True)
    assert db.store == before
    assert res['docs'][date(2026, 4, 21)]['energy_kwh']['E3'] == pytest.approx(2.0, abs=0.01)


def test_future_days_are_skipped(db):
    svc = AggregationService(db)
    res = svc.run_device(DEV, [date(2026, 5, 1)], now_ms=day_bounds(date(2026, 4, 26))[0])
    assert res['written'] == 0


def test_run_rejects_long_ranges(db):
    svc = AggregationService(db)
    with pytest.raises(ValueError):
        svc.run('range', [DEV], date(2026, 1, 1), date(2026, 3, 1))
    with pytest.raises(ValueError):
        svc.run('weekly', [DEV])


# --- Endpunkt ------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    from api.routes import aggregate as route
    from middleware import scheduler_auth

    calls = []

    class Svc:
        def run(self, mode, devices, first, last, days_back):
            calls.append((mode, devices, first, last, days_back))
            return [{'device': 'x', 'written': 1}]

    monkeypatch.setattr(route, '_service', Svc())
    monkeypatch.setattr(scheduler_auth, '_verify', lambda token, aud: {
        'ok-token': {'email': 'scheduler@example.iam.gserviceaccount.com', 'email_verified': True},
        'other-token': {'email': 'someone@example.com', 'email_verified': True},
    }[token])
    app = Flask(__name__)
    app.register_blueprint(route.aggregate_bp)
    c = app.test_client()
    c.calls = calls
    return c


def test_aggregate_fails_closed_without_config(client, monkeypatch):
    monkeypatch.delenv('AGGREGATE_AUDIENCE', raising=False)
    monkeypatch.delenv('AGGREGATE_INVOKERS', raising=False)
    assert client.post('/aggregate', headers={'Authorization': 'Bearer ok-token'}).status_code == 503


def test_aggregate_auth(client, monkeypatch):
    monkeypatch.setenv('AGGREGATE_AUDIENCE', 'https://api.example.test')
    monkeypatch.setenv('AGGREGATE_INVOKERS', 'scheduler@example.iam.gserviceaccount.com')
    assert client.post('/aggregate').status_code == 401
    assert client.post('/aggregate', headers={'Authorization': 'Bearer bad'}).status_code == 401
    assert client.post('/aggregate', headers={'Authorization': 'Bearer other-token'}).status_code == 403
    r = client.post('/aggregate?mode=nightly&days_back=2', headers={'Authorization': 'Bearer ok-token'})
    assert r.status_code == 200
    assert client.calls[-1] == ('nightly', None, None, None, 2)
    r = client.post('/aggregate', json={'device': 'demo-haus', 'date': '2026-07-14'},
                    headers={'Authorization': 'Bearer ok-token'})
    assert r.status_code == 200
    assert client.calls[-1] == ('range', ['demo-haus'], date(2026, 7, 14), date(2026, 7, 14), 3)
    r = client.post('/aggregate?date=14.07.2026', headers={'Authorization': 'Bearer ok-token'})
    assert r.status_code == 400
