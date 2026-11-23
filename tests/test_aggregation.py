"""Tageswerte: reine Rechenlogik ohne Firestore."""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest  # noqa: E402

from aggregation.allocation import DayInfo, Entry, allocate, entry_from_doc, needed_from  # noqa: E402
from aggregation.climate import occupancy  # noqa: E402
from aggregation.daily import build_daily  # noqa: E402
from aggregation.energy import integrate  # noqa: E402
from aggregation.fires import detect_fires  # noqa: E402
from aggregation.series import day_bounds, hour_bounds, local_hhmm  # noqa: E402

DAY = date(2026, 7, 14)
H = 3600_000
MIN = 60_000


def at(day: date, hh: int, mm: int = 0) -> int:
    return day_bounds(day)[0] + hh * H + mm * MIN


def constant(start, end, step, value, field='power'):
    return [(t, {field: value}) for t in range(start, end, step)]


# --- Tagesgrenzen -------------------------------------------------------

def test_day_bounds_dst():
    s, e = day_bounds(date(2026, 3, 29))
    assert e - s == 23 * H
    s, e = day_bounds(date(2026, 10, 25))
    assert e - s == 25 * H
    assert len(hour_bounds(date(2026, 10, 25))) == 25
    assert local_hhmm(at(DAY, 19, 20)) == '19:20'


# --- Strom ---------------------------------------------------------------

def test_integrate_constant_full_day():
    s, e = day_bounds(DAY)
    series = [(t, 1000.0) for t in range(s, e, 10_000)]
    res = integrate(series, s, e, hour_bounds(DAY))
    assert res.kwh == pytest.approx(24.0)
    assert res.covered_ms == e - s
    assert res.hourly_kwh[13] == pytest.approx(1.0)


def test_integrate_gap_is_not_counted():
    s, e = day_bounds(DAY)
    series = [(t, 1000.0) for t in range(s, e, 10_000) if not (at(DAY, 10) <= t < at(DAY, 11))]
    res = integrate(series, s, e, hour_bounds(DAY))
    assert res.kwh == pytest.approx(23.0, abs=0.01)
    assert res.hourly_kwh[10] == pytest.approx(0.0, abs=0.01)


def test_build_daily_energy_and_feed_in():
    s, e = day_bounds(DAY)
    raw = {
        ('E3', 'victron'): constant(at(DAY, 10), at(DAY, 14), 10_000, 500.0),
        ('E1', 'victron'): constant(s, at(DAY, 12), 10_000, 100.0) + constant(at(DAY, 12), e, 10_000, -200.0),
        ('I2', 'shelly-3em-pro'): constant(s, e, 20_000, 0.0, 'act_power'),
    }
    doc = build_daily(DAY, raw, now_ms=e + H, metering_points=['E1', 'E3', 'I2'])
    assert doc['energy_kwh']['E3'] == pytest.approx(2.0, abs=0.01)
    assert doc['energy_kwh']['E1'] == pytest.approx(1.2, abs=0.01)
    assert doc['energy_kwh']['E2'] == pytest.approx(2.4, abs=0.01)
    assert doc['energy_sensor']['I2'] == 'shelly-3em-pro'
    assert doc['availability']['E1'] == pytest.approx(1.0)
    assert doc['partial'] is False
    assert len(doc['hourly_kwh']['E3']) == 24


def test_build_daily_hot_water_from_shelly_1pm():
    s, e = day_bounds(DAY)
    pts = (constant(s, at(DAY, 7), 10_000, 0.0, 'act_power')
           + constant(at(DAY, 7), at(DAY, 8), 10_000, 1200.0, 'act_power')
           + constant(at(DAY, 8), e, 10_000, 0.0, 'act_power'))
    doc = build_daily(DAY, {('I1', 'shelly-1pm-gen4'): pts}, now_ms=e + H, metering_points=['I1'])
    assert doc['energy_sensor']['I1'] == 'shelly-1pm-gen4'
    assert doc['energy_kwh']['I1'] == pytest.approx(1.2, abs=0.01)


def test_build_daily_today_is_partial():
    s, e = day_bounds(DAY)
    now = at(DAY, 12)
    raw = {('E1', 'victron'): constant(s, now, 10_000, 100.0)}
    doc = build_daily(DAY, raw, now_ms=now)
    assert doc['partial'] is True
    assert doc['availability']['E1'] == pytest.approx(1.0, abs=0.01)
    assert doc['data_until'] == now - 10_000


# --- Klima und Belegung --------------------------------------------------

def test_occupancy_sensirion_absolute():
    s, e = day_bounds(DAY)
    empty = [(t, 450.0) for t in range(s, e, 120_000)]
    assert occupancy(empty, s, e, e)[:2] == (False, 450.0)
    visit = empty + [(at(DAY, 19, m), 900.0) for m in range(0, 30, 2)]
    occ, peak, _ = occupancy(sorted(visit), s, e, e)
    assert occ is True and peak > 600
    sparse = [(at(DAY, 1), 450.0)]
    assert occupancy(sparse, s, e, e)[0] is None


def test_occupancy_netatmo_uses_rise_over_baseline():
    s, e = day_bounds(DAY)
    # leeres Haus, Nullpunkt der Netatmo hoch: absolut über 600, aber flach
    empty = [(t, 760.0 + (t // 600_000) % 3 * 10) for t in range(s, e, 600_000)]
    occ, peak, rise = occupancy(empty, s, e, e, 'netatmo')
    assert occ is False and peak > 600 and rise < 150
    # bewohnt: Abend steigt um 300 ppm über die Grundlinie
    lived = [(t, 600.0 + (300.0 if at(DAY, 19) <= t < at(DAY, 23) else 0.0)) for t in range(s, e, 600_000)]
    occ, _, rise = occupancy(lived, s, e, e, 'netatmo')
    assert occ is True and rise == pytest.approx(300.0)
    # Sensirion mit demselben Verlauf ist absolut bewohnt
    assert occupancy(empty, s, e, e, 'sensirion_scd4x')[0] is True


def test_build_daily_climate_prefers_netatmo():
    s, e = day_bounds(DAY)
    net = [(t, {'temperature_indoor': 29.0 if at(DAY, 14) <= t < at(DAY, 16) else 22.0,
                'humidity_indoor': 50, 'co2_indoor': 700, 'temperature_outdoor': 18.0})
           for t in range(s, e, 600_000)]
    voc = [(t, {'temperature_indoor': 30.0}) for t in range(s, e, 120_000)]
    scd = [(t, {'co2_indoor': 500.0}) for t in range(s, e, 120_000)]
    raw = {('K0', 'netatmo'): net, ('K0', 'sensirion_voc'): voc, ('K0', 'sensirion_scd4x'): scd}
    doc = build_daily(DAY, raw, now_ms=e + H)
    assert doc['climate_source'] == 'netatmo'
    assert doc['climate']['t_in_median'] == 22.0
    assert doc['climate']['hours_over_28'] == pytest.approx(2.0)
    assert doc['climate']['t_out_mean'] == 18.0
    assert doc['occupancy_source'] == 'sensirion_scd4x'
    assert doc['occupied'] is False
    assert doc['availability']['K1'] == 1.0
    assert len(doc['hourly_climate']['co2']) == 24


# --- Ofensignatur --------------------------------------------------------

def fire_curve(day, start_h, start_m, rise_min=60, rise_k_per_h=6.0, base=18.0, decay_k_per_h=1.5):
    """Innentemperatur alle 10 min: flach, Anstieg, dann Abkühlung."""
    t0 = at(day, start_h, start_m)
    peak = base + rise_k_per_h * rise_min / 60
    out = []
    s, e = day_bounds(day)
    for t in range(s - 3 * H, e + 12 * H, 600_000):
        if t < t0:
            v = base
        elif t < t0 + rise_min * MIN:
            v = base + rise_k_per_h * (t - t0) / H
        else:
            v = max(base - 0.5, peak - decay_k_per_h * (t - t0 - rise_min * MIN) / H)
        out.append((t, v))
    return out


def test_detect_single_fire():
    s, e = day_bounds(DAY)
    t_in = fire_curve(DAY, 19, 20)
    fires = detect_fires(t_in, None, None, s - 3 * H, e + 12 * H, s, e)
    assert len(fires) == 1
    f = fires[0]
    assert f['start'] == '19:20'
    assert f['rise_k_per_h'] == pytest.approx(6.0, abs=0.1)
    # 1 h Anstieg, 4 h Abkühlung um 6 K bei 1.5 K/h
    assert f['weight'] == pytest.approx(5.0, abs=0.2)


def test_no_fire_while_floor_heating_runs():
    s, e = day_bounds(DAY)
    t_in = fire_curve(DAY, 19, 20)
    i2 = [(t, 800.0) for t in range(s, e, 20_000)]
    assert detect_fires(t_in, i2, None, s - 3 * H, e + 12 * H, s, e) == []


def test_no_fire_with_strong_sun():
    s, e = day_bounds(DAY)
    t_in = fire_curve(DAY, 12, 0)
    e3 = [(t, 900.0) for t in range(s, e, 10_000)]
    assert detect_fires(t_in, None, e3, s - 3 * H, e + 12 * H, s, e) == []


def test_slow_rise_is_no_fire():
    s, e = day_bounds(DAY)
    t_in = fire_curve(DAY, 19, 20, rise_k_per_h=2.0)
    assert detect_fires(t_in, None, None, s - 3 * H, e + 12 * H, s, e) == []


def test_fire_belongs_to_day_of_start():
    s, e = day_bounds(DAY)
    t_in = fire_curve(DAY, 23, 50)
    assert len(detect_fires(t_in, None, None, s - 3 * H, e + 12 * H, s, e)) == 1
    nxt = DAY + timedelta(days=1)
    ns, ne = day_bounds(nxt)
    assert detect_fires(t_in, None, None, ns - 3 * H, ne + 12 * H, ns, ne) == []


# --- Verteilung der Brennstoffe -----------------------------------------

def days_info(first: date, n: int, fires=None, occupied=None, t_out=None):
    out = {}
    for i in range(n):
        d = first + timedelta(days=i)
        s, e = day_bounds(d)
        f = [(s + 19 * H, w) for w in (fires or {}).get(d, [])]
        occ = (occupied or {}).get(d, True)
        out[d] = DayInfo(d, s, e, f, occ, (t_out or {}).get(d))
    return out


def pellets(ts, consumed, mp='M2'):
    return Entry(ts, 'pellets', mp, consumed, 'kg')


def test_pellets_closed_period_by_fire_weight():
    d0 = date(2026, 4, 20)
    days = days_info(d0, 10, fires={date(2026, 4, 21): [3.0], date(2026, 4, 24): [1.0]})
    entries = [pellets(at(d0, 9), 0), pellets(at(date(2026, 4, 28), 9), 8.0)]
    alloc, kwh, _ = allocate(entries, days, days.keys(), {'pellets': 4.8})
    assert alloc[date(2026, 4, 21)]['pellets']['quantity'] == pytest.approx(6.0)
    assert alloc[date(2026, 4, 24)]['pellets']['quantity'] == pytest.approx(2.0)
    assert alloc[date(2026, 4, 22)]['pellets']['quantity'] == 0
    a = alloc[date(2026, 4, 21)]['pellets']
    assert a['method'] == 'ofensignatur' and a['provisional'] is False and a['fires'] == 1
    assert kwh[date(2026, 4, 21)]['pellets'] == pytest.approx(28.8)
    total = sum(v['pellets']['quantity'] or 0 for d, v in alloc.items() if d < date(2026, 4, 28))
    assert total == pytest.approx(8.0)


def test_pellets_running_period_uses_kg_per_fire_weight():
    d0 = date(2026, 4, 20)
    fires = {date(2026, 4, 21): [2.0], date(2026, 4, 22): [2.0], date(2026, 4, 26): [1.0]}
    days = days_info(d0, 8, fires=fires)
    entries = [pellets(at(d0, 9), 0), pellets(at(date(2026, 4, 24), 9), 6.0)]
    alloc, _, state = allocate(entries, days, days.keys())
    a = alloc[date(2026, 4, 26)]['pellets']
    assert a['provisional'] is True
    assert a['quantity'] == pytest.approx(1.5)  # 6 kg / 4 Gewicht * 1
    assert state['M2|pellets']['rates']['per_weight']['ofensignatur'] == pytest.approx(1.5)


def test_running_without_closed_period_has_only_fire_count():
    d0 = date(2026, 4, 20)
    days = days_info(d0, 3, fires={date(2026, 4, 21): [2.0]})
    alloc, kwh, _ = allocate([pellets(at(d0, 9), 0)], days, days.keys(), {'pellets': 4.8})
    a = alloc[date(2026, 4, 21)]['pellets']
    assert a['quantity'] is None and a['fires'] == 1
    assert date(2026, 4, 21) not in kwh


def test_pellets_fallback_heating_degree_days_then_uniform():
    d0 = date(2026, 11, 1)
    days = days_info(d0, 4, t_out={d0 + timedelta(days=i): t for i, t in enumerate([5.0, 15.0, 10.0, 0.0])})
    entries = [pellets(day_bounds(d0)[0], 0), pellets(day_bounds(d0 + timedelta(days=3))[0], 25.0)]
    alloc, _, _ = allocate(entries, days, days.keys())
    assert alloc[d0]['pellets']['method'] == 'heizgradtage'
    assert alloc[d0]['pellets']['quantity'] == pytest.approx(15.0)  # 15 von 25 Gradtagen
    assert alloc[d0 + timedelta(days=1)]['pellets']['quantity'] == 0
    assert alloc[d0 + timedelta(days=2)]['pellets']['quantity'] == pytest.approx(10.0)

    days = days_info(d0, 4)
    alloc, _, _ = allocate(entries, days, days.keys())
    assert alloc[d0]['pellets']['method'] == 'gleichmaessig'
    assert alloc[d0]['pellets']['quantity'] == pytest.approx(25.0 / 3, abs=0.001)


def test_propane_on_occupied_days():
    d0 = date(2026, 7, 1)
    occupied = {d0 + timedelta(days=i): i % 2 == 0 for i in range(10)}
    days = days_info(d0, 10, occupied=occupied)
    entries = [Entry(day_bounds(d0)[0], 'propane', 'M1', 0, 'kg'),
               Entry(day_bounds(d0 + timedelta(days=9))[0], 'propane', 'M1', 2.25, 'kg')]
    alloc, _, _ = allocate(entries, days, days.keys(), {'propane': 12.8})
    # bewohnt: Tage 0,2,4,6,8; Tag 8 liegt ganz im Zeitraum (Eintrag am Tag 9)
    assert alloc[d0]['propane']['method'] == 'bewohnte_tage'
    assert alloc[d0]['propane']['quantity'] == pytest.approx(0.45)
    assert alloc[d0 + timedelta(days=1)]['propane']['quantity'] == 0


def test_diesel_is_not_allocated():
    d0 = date(2026, 7, 1)
    days = days_info(d0, 3)
    entries = [Entry(at(d0, 9), 'diesel', 'M0', 0, 'Liter'), Entry(at(d0 + timedelta(days=2), 9), 'diesel', 'M0', 5, 'Liter')]
    alloc, _, state = allocate(entries, days, days.keys())
    assert alloc == {} and state == {}


def test_fast_path_matches_full_path():
    d0 = date(2026, 4, 20)
    fires = {date(2026, 4, 21): [2.0], date(2026, 4, 22): [2.0], date(2026, 4, 26): [1.0], date(2026, 4, 27): [0.5]}
    days = days_info(d0, 8, fires=fires)
    entries = [pellets(at(d0, 9), 0), pellets(at(date(2026, 4, 24), 9), 6.0)]
    today = date(2026, 4, 27)
    full, _, state = allocate(entries, days, [today])
    fast, _, _ = allocate(entries, {today: days[today]}, [today], state=state)
    assert fast == full
    # Neuer Eintrag: gespeicherter Stand gilt nicht mehr
    entries2 = entries + [pellets(at(date(2026, 4, 27), 7), 1.0)]
    again, _, _ = allocate(entries2, {today: days[today]}, [today], state=state)
    assert again[today]['pellets']['quantity'] != fast[today]['pellets']['quantity']


def test_two_metering_points_are_summed():
    d0 = date(2026, 4, 20)
    days = days_info(d0, 4, fires={date(2026, 4, 21): [1.0]})
    entries = [pellets(at(d0, 9), 0, 'M2'), pellets(at(date(2026, 4, 23), 9), 4.0, 'M2'),
               pellets(at(d0, 9), 0, 'M0'), pellets(at(date(2026, 4, 23), 9), 2.0, 'M0')]
    alloc, _, _ = allocate(entries, days, days.keys())
    a = alloc[date(2026, 4, 21)]['pellets']
    assert a['quantity'] == pytest.approx(6.0)
    assert a['by_metering_point'] == {'M0': 2.0, 'M2': 4.0}
    assert a['incomplete'] is False
    assert a['fires'] == 1


def test_needed_from_and_entry_from_doc():
    doc = {
        'sensor_id': 'app_form', 'metering_point': 'M2', 'start_timestamp': 1000,
        'data_points': [{'timestamp': 1000, 'values': {'added_quantity': 15, 'leftover_quantity': 2,
                                                       'consumed_quantity': 3.5, 'unit': 'kg'}}],
        'metadata': {'purchase_date': 1000, 'energy_type': 'pellets'},
    }
    e = entry_from_doc('x', doc)
    assert (e.ts, e.energy_type, e.metering_point, e.consumed, e.unit) == (1000, 'pellets', 'M2', 3.5, 'kg')
    entries = [pellets(1, 0), pellets(10, 5), pellets(20, 0)]
    assert needed_from(entries) == 1


def test_unknown_part_does_not_hide_known_quantity():
    d0 = date(2026, 7, 1)
    days = days_info(d0, 5)
    entries = [Entry(at(d0 - timedelta(days=100), 9), 'propane', 'M0', 0, 'kg'),  # nie nachgeführt
               Entry(at(d0, 0), 'propane', 'M1', 0, 'kg'),
               Entry(day_bounds(d0 + timedelta(days=4))[0], 'propane', 'M1', 2.0, 'kg')]
    alloc, _, _ = allocate(entries, days, days.keys())
    a = alloc[d0 + timedelta(days=1)]['propane']
    assert a['quantity'] == pytest.approx(0.5)
    assert a['incomplete'] is True and a['provisional'] is False
    assert a['by_metering_point'] == {'M0': None, 'M1': 0.5}


def test_sun_before_rise_blocks_fire():
    s, e = day_bounds(DAY)
    t_in = fire_curve(DAY, 11, 0)
    # PV gedrosselt (volle Batterie): während des Anstiegs wenig, eine Stunde vorher viel
    e3 = [(t, 900.0 if at(DAY, 9, 30) <= t < at(DAY, 10, 0) else 100.0) for t in range(s, e, 10_000)]
    assert detect_fires(t_in, None, e3, s - 3 * H, e + 12 * H, s, e) == []
    e3_dark = [(t, 0.0) for t in range(s, e, 10_000)]
    assert len(detect_fires(t_in, None, e3_dark, s - 3 * H, e + 12 * H, s, e)) == 1


def test_fire_duration_ends_when_sun_takes_over():
    s, e = day_bounds(DAY)
    t_in = fire_curve(DAY, 6, 0, decay_k_per_h=0.2)
    e3 = [(t, 800.0 if t >= at(DAY, 8) else 0.0) for t in range(s, e, 10_000)]
    f = detect_fires(t_in, None, e3, s - 3 * H, e + 12 * H, s, e)
    assert len(f) == 1 and f[0]['end'] == '08:00' and f[0]['weight'] == pytest.approx(2.0)


def test_small_ster_quantities_keep_precision():
    d0 = date(2026, 1, 1)
    days = days_info(d0, 30)
    entries = [Entry(day_bounds(d0)[0], 'woodSter', 'M2', 0, 'Ster'),
               Entry(day_bounds(d0 + timedelta(days=29))[0], 'woodSter', 'M2', 0.1, 'Ster')]
    alloc, kwh, _ = allocate(entries, days, days.keys(), {'woodSter': 1627.5})
    a = alloc[d0 + timedelta(days=3)]['woodSter']
    assert a['quantity'] == pytest.approx(0.1 / 29, rel=1e-4)
    assert kwh[d0 + timedelta(days=3)]['woodSter'] == pytest.approx(1627.5 * 0.1 / 29, abs=0.001)
