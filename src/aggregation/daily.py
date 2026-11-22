"""Gemessener Teil eines Tagesdokuments /devices/{id}/daily/{YYYY-MM-DD}.

Die Verteilung der Brennstoffe (manual_alloc) rechnet allocation.py, weil
sie mehrere Tage braucht.
"""
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

from aggregation.climate import climate_stats, occupancy
from aggregation.energy import integrate
from aggregation.fires import detect_fires
from aggregation.series import Series, day_bounds, extract, hour_bounds, rnd
from aggregation.settings import (AGGREGATION_VERSION, CLIMATE_SOURCES, ELECTRIC_MPS, FIRE_LOOKAHEAD_MS,
                                  FIRE_LOOKBACK_MS, OCCUPANCY_SOURCES, POWER_SENSORS, TIMEZONE)

# Rohdaten: (Messpunkt, sensor_id) -> [(timestamp ms, values)]
RawPoints = Dict[Tuple[str, str], List[Tuple[int, dict]]]

CLIMATE_FIELDS = ['temperature_indoor', 'humidity_indoor', 'co2_indoor', 'temperature_outdoor']


def raw_window(day: date) -> Tuple[int, int]:
    """Zeitraum der Rohdaten, die build_daily für einen Tag braucht."""
    start, end = day_bounds(day)
    return start - FIRE_LOOKBACK_MS, end + FIRE_LOOKAHEAD_MS


def power_series(raw: RawPoints, mp: str) -> Tuple[Optional[str], Series]:
    """Leistung eines Messpunkts vom ersten Sensor in POWER_SENSORS mit Daten."""
    for sensor, fld in POWER_SENSORS:
        pts = raw.get((mp, sensor))
        if pts:
            s = extract(pts, fld)
            if s:
                return sensor, s
    return None, []


def _climate_fields(raw: RawPoints, sensor: str) -> Dict[str, Series]:
    pts = raw.get(('K0', sensor)) or []
    return {f: extract(pts, f) for f in CLIMATE_FIELDS}


def build_daily(day: date, raw: RawPoints, now_ms: int, metering_points: Optional[List[str]] = None) -> dict:
    """Tageswerte ohne Brennstoffverteilung.

    metering_points: Messpunkte des Geräts laut /metering_points. Fehlt I2
    oder E3 dort, gilt die Bedingung der Ofensignatur als erfüllt.
    """
    start, end = day_bounds(day)
    hours = hour_bounds(day)
    expected_end = min(end, now_ms)
    elapsed = max(1, expected_end - start)
    mps = set(metering_points) if metering_points is not None else {mp for mp, _ in raw}

    doc: dict = {
        'date': day.isoformat(),
        'timezone': TIMEZONE,
        'energy_kwh': {},
        'energy_sensor': {},
        'hourly_kwh': {},
        'availability': {},
    }
    last_ts = 0

    # Strom
    for mp in ELECTRIC_MPS:
        sensor, series = power_series(raw, mp)
        if sensor is None:
            continue
        res = integrate(series, start, end, hours)
        if res.covered_ms == 0 and not any(start <= t < end for t, _ in series):
            continue
        doc['energy_kwh'][mp] = rnd(res.kwh, 3)
        doc['energy_sensor'][mp] = sensor
        doc['hourly_kwh'][mp] = [rnd(v, 4) for v in res.hourly_kwh]
        doc['availability'][mp] = rnd(min(1.0, res.covered_ms / elapsed), 3)
        last_ts = max(last_ts, res.last_ts)
        if mp == 'E1' and res.kwh_negative > 0 and 'E2' not in mps:
            # TODO(prüfen): Victron meldet Rückspeisung an E1 als negative Leistung.
            doc['energy_kwh']['E2'] = rnd(res.kwh_negative, 3)
            doc['energy_sensor']['E2'] = f'{sensor}:E1_negativ'

    # Klima: Studienquelle Netatmo, sonst Sensirion (nicht am Lieblingsort)
    climate_source = None
    fields: Dict[str, Series] = {}
    for sensor in CLIMATE_SOURCES:
        f = _climate_fields(raw, sensor)
        if any(start <= t < end for t, _ in f['temperature_indoor']):
            climate_source, fields = sensor, f
            break
    co2_scd = _climate_fields(raw, 'sensirion_scd4x')['co2_indoor']
    if climate_source:
        climate, hourly_climate, avail = climate_stats(fields, start, end, hours, expected_end,
                                                       co2_fallback=co2_scd)
        doc['climate'] = climate
        doc['hourly_climate'] = hourly_climate
        doc['availability'].update(avail)
        for s in fields.values():
            in_day = [t for t, _ in s if start <= t < end]
            if in_day:
                last_ts = max(last_ts, max(in_day))
    doc['climate_source'] = climate_source

    # Belegung: CO2 von Sensirion SCD4x, sonst Netatmo
    doc['occupied'] = None
    doc['occupancy_source'] = None
    doc['co2_peak'] = None
    doc['co2_rise'] = None
    for sensor in OCCUPANCY_SOURCES:
        co2 = _climate_fields(raw, sensor)['co2_indoor']
        if any(start <= t < end for t, _ in co2):
            occ, peak, rise = occupancy(co2, start, end, expected_end, sensor)
            doc['occupied'], doc['occupancy_source'] = occ, sensor
            doc['co2_peak'], doc['co2_rise'] = rnd(peak, 0), rnd(rise, 0)
            break

    # Ofensignatur, mit Rand vor und nach dem Tag
    w0, w1 = raw_window(day)
    fire_source = None
    fires: List[dict] = []
    for sensor in CLIMATE_SOURCES:
        t_in = _climate_fields(raw, sensor)['temperature_indoor']
        if any(start <= t < end for t, _ in t_in):
            fire_source = sensor
            i2 = power_series(raw, 'I2')[1] if 'I2' in mps else None
            e3 = power_series(raw, 'E3')[1] if 'E3' in mps else None
            fires = detect_fires(t_in, i2, e3, w0, w1, start, end)
            break
    doc['fire_events'] = fires
    doc['fire_source'] = fire_source

    doc['partial'] = now_ms < end
    doc['data_until'] = last_ts or None
    doc['computed_at'] = datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat()
    doc['version'] = AGGREGATION_VERSION
    return doc
