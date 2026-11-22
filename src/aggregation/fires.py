"""Ofensignatur: Feuer im Pellet- oder Holzofen am Verlauf der Innentemperatur erkennen.

Ein Feuer: Die Innentemperatur steigt über mindestens 30 min um mehr als
3 K pro Stunde, gleichzeitig läuft keine elektrische Heizung (I2 im Mittel
unter 50 W) und es gibt keinen starken Sonneneintrag (E3 ab 2 h vor dem
Anstieg nie über 300 W, weil der Victron mit voller Batterie die PV drosselt).
Anstiege mit weniger als 2 h Abstand zählen als ein Feuer. Das Gewicht ist
die Dauer, in der die Innentemperatur über dem Wert vor dem Feuer lag
(Brenndauer als Näherung), höchstens 12 h. Scheint danach die Sonne (E3 über
300 W), endet die Brenndauer dort, weil die Sonne das Haus warm hält.

TODO(prüfen): Schwellen sind aus sechs Monaten Beispielhaus (April bis
September) abgeleitet. Im November erkennt die Erkennung die automatischen
Morgenstarts des Pelletofens (06:00) richtig; lange Feuer erreichen oft die
Obergrenze von 12 h. Weiter prüfen mit Daten bis Februar 2027.
"""
from typing import Dict, List, Optional

from aggregation.series import Series, bucket_means, local_hhmm
from aggregation.settings import (FIRE_BUCKET_MS, FIRE_E3_MAX_W, FIRE_I2_MAX_W, FIRE_MAX_DURATION_MS,
                                  FIRE_MERGE_MS, FIRE_RISE_K_PER_H, FIRE_SUN_LOOKBACK_MS, FIRE_WINDOW_MS)


def _window_mean(buckets: Dict[int, float], t0: int, t1: int) -> Optional[float]:
    vals = [v for b, v in buckets.items() if t0 <= b < t1]
    return sum(vals) / len(vals) if vals else None


def detect_fires(t_in: Series, i2_power: Optional[Series], e3_power: Optional[Series],
                 window_start: int, window_end: int, day_start: int, day_end: int) -> List[dict]:
    """Feuer, die am Tag [day_start, day_end) beginnen.

    t_in, i2_power und e3_power decken window_start bis window_end ab (mit Rand
    vor und nach dem Tag). Fehlt I2 oder E3 als Messpunkt (None), gilt die
    jeweilige Bedingung als erfüllt. Ein Messpunkt ohne Daten im Fenster eines
    Anstiegs schliesst ein Feuer nicht aus.
    """
    step = FIRE_BUCKET_MS
    temp = bucket_means(t_in, window_start, window_end, step)
    if len(temp) < 2:
        return []
    i2 = bucket_means(i2_power, window_start, window_end, step) if i2_power else {}
    e3 = bucket_means(e3_power, window_start, window_end, step) if e3_power else {}
    lag = FIRE_WINDOW_MS // step

    rises = []  # (start, rise_end, slope)
    for b in sorted(temp):
        b2 = b + lag * step
        if b2 not in temp:
            continue
        slope = (temp[b2] - temp[b]) / (FIRE_WINDOW_MS / 3600_000)
        if slope <= FIRE_RISE_K_PER_H:
            continue
        p_i2 = _window_mean(i2, b, b2 + step)
        if p_i2 is not None and p_i2 >= FIRE_I2_MAX_W:
            continue
        if any(v >= FIRE_E3_MAX_W for t, v in e3.items() if b - FIRE_SUN_LOOKBACK_MS <= t <= b2):
            continue
        rises.append((b, b2, slope))

    events = []  # [start, rise_end, max_slope]
    for start, rise_end, slope in rises:
        if events and start - events[-1][1] < FIRE_MERGE_MS:
            events[-1][1] = max(events[-1][1], rise_end)
            events[-1][2] = max(events[-1][2], slope)
        else:
            events.append([start, rise_end, slope])

    out = []
    for i, (start, rise_end, slope) in enumerate(events):
        # Beginn = letzter Wert vor dem Anstieg, nicht der Anfang des 30-min-Fensters
        while start + step < rise_end and start + step in temp and temp[start + step] - temp[start] < 0.1:
            start += step
        if not (day_start <= start < day_end):
            continue
        t0 = temp[start]
        limit = start + FIRE_MAX_DURATION_MS
        if i + 1 < len(events):
            limit = min(limit, events[i + 1][0])
        end = rise_end
        for b in sorted(temp):
            if b <= rise_end:
                continue
            if b >= limit:
                end = limit
                break
            end = b
            if temp[b] <= t0 or e3.get(b, 0) >= FIRE_E3_MAX_W:
                break
        end = min(end, limit)
        out.append({
            'start': local_hhmm(start),
            'end': local_hhmm(end),
            'start_ts': start,
            'end_ts': end,
            'rise_k_per_h': round(slope, 1),
            'weight': round((end - start) / 3600_000, 2),
        })
    return out
