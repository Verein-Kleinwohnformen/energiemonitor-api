"""Klima und Belegung pro Tag."""
from typing import Dict, List, Optional, Tuple

from aggregation.series import Series, bucket_means, percentile, rnd
from aggregation.settings import (CLIMATE_BUCKET_MS, DAYTIME_HOURS, HOT_THRESHOLD_C, OCCUPANCY_BASELINE_PERCENTILE,
                                  OCCUPANCY_MIN_COVERAGE, OCCUPANCY_RULES)

SensorFields = Dict[str, Series]  # Feld -> Zeitreihe eines Sensors


def _buckets(series: Series, start: int, end: int) -> Dict[int, float]:
    return bucket_means(series, start, end, CLIMATE_BUCKET_MS)


def n_buckets(start: int, end: int) -> int:
    return max(1, (end - start + CLIMATE_BUCKET_MS - 1) // CLIMATE_BUCKET_MS)


def climate_stats(fields: SensorFields, start: int, end: int, hours: List[Tuple[int, int]],
                  expected_end: int, co2_fallback: Optional[Series] = None) -> Tuple[dict, dict, dict]:
    """Klimawerte eines Sensors (Studienquelle), Viertelstundenmittel.

    Liefert (climate, hourly_climate, availability). expected_end ist das Ende
    des Zeitraums, für den Daten erwartet werden (heute: jetzt).
    """
    t_in = _buckets(fields.get('temperature_indoor', []), start, end)
    rh_in = _buckets(fields.get('humidity_indoor', []), start, end)
    co2_series = fields.get('co2_indoor') or co2_fallback or []
    co2 = _buckets(co2_series, start, end)
    t_out = _buckets(fields.get('temperature_outdoor', []), start, end)

    climate = {
        't_in_median': rnd(percentile(list(t_in.values()), 0.5), 1),
        't_in_p05': rnd(percentile(list(t_in.values()), 0.05), 1),
        't_in_p95': rnd(percentile(list(t_in.values()), 0.95), 1),
        't_in_max': rnd(max(t_in.values()), 1) if t_in else None,
        'rh_in_median': rnd(percentile(list(rh_in.values()), 0.5), 0),
        'co2_median': rnd(percentile(list(co2.values()), 0.5), 0),
        'co2_max': rnd(max(co2.values()), 0) if co2 else None,
        't_out_mean': rnd(sum(t_out.values()) / len(t_out), 1) if t_out else None,
        't_out_min': rnd(min(t_out.values()), 1) if t_out else None,
        't_out_max': rnd(max(t_out.values()), 1) if t_out else None,
        'hours_over_28': rnd(sum(1 for v in t_in.values() if v > HOT_THRESHOLD_C) * CLIMATE_BUCKET_MS / 3600_000, 2)
        if t_in else None,
        't_in_mean_08_20': _daytime_mean(t_in, hours),
    }

    hourly = {'t_in': _hourly_median(t_in, hours, 1), 'co2': _hourly_median(co2, hours, 0)}

    expected = n_buckets(start, min(end, expected_end))
    availability = {
        'K1': rnd(min(1.0, len(t_in) / expected), 3),
        'K2': rnd(min(1.0, len(t_out) / expected), 3),
        'K3': rnd(min(1.0, len(rh_in) / expected), 3),
        'K4': rnd(min(1.0, len(co2) / expected), 3),
    }
    return climate, hourly, availability


def _hour_of(hours: List[Tuple[int, int]], ts: int) -> int:
    hour = hours[0][1]
    for h_start, h in hours:
        if h_start <= ts:
            hour = h
        else:
            break
    return hour


def _daytime_mean(buckets: Dict[int, float], hours) -> Optional[float]:
    lo, hi = DAYTIME_HOURS
    vals = [v for b, v in buckets.items() if lo <= _hour_of(hours, b) < hi]
    return rnd(sum(vals) / len(vals), 1) if vals else None


def _hourly_median(buckets: Dict[int, float], hours, digits: int) -> List[Optional[float]]:
    per_hour: Dict[int, List[float]] = {}
    for b, v in buckets.items():
        per_hour.setdefault(_hour_of(hours, b), []).append(v)
    return [rnd(percentile(per_hour.get(h, []), 0.5), digits) for h in range(24)]


def occupancy(co2: Series, start: int, end: int, expected_end: int,
              sensor: str = 'sensirion_scd4x') -> Tuple[Optional[bool], Optional[float], Optional[float]]:
    """Bewohnt aus dem CO2 eines Tages, Regel je nach Sensor (OCCUPANCY_RULES).

    Höchstwert statt Mittelwert, weil im Sommer bei offenen Fenstern der
    Mittelwert tief bleibt. Rohwerte, kein Viertelstundenmittel, wie in der
    Auswertung Langzeittest.
    - absolute: Höchstwert über dem Schwellwert
    - rise: Höchstwert minus 10. Perzentil des Tages über dem Schwellwert
      (für Sensoren, deren Nullpunkt wandert)
    Mit zu wenig Daten unbekannt (None), ausser der Schwellwert wurde schon
    überschritten. Liefert (bewohnt, Höchstwert, Anstieg).
    """
    values = [v for t, v in co2 if start <= t < end]
    if not values:
        return None, None, None
    rule, threshold = OCCUPANCY_RULES.get(sensor, OCCUPANCY_RULES['sensirion_scd4x'])
    peak = max(values)
    rise = peak - percentile(values, OCCUPANCY_BASELINE_PERCENTILE)
    if (rise if rule == 'rise' else peak) > threshold:
        return True, peak, rise
    coverage = len(_buckets(co2, start, end)) / n_buckets(start, min(end, expected_end))
    if coverage < OCCUPANCY_MIN_COVERAGE:
        return None, peak, rise
    return False, peak, rise
