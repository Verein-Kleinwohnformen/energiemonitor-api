"""Strom: Leistung in W zu kWh pro Tag und pro Stunde aufsummieren."""
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import List, Tuple

from aggregation.series import Series
from aggregation.settings import STEP_FACTOR, STEP_MAX_MS, STEP_MIN_MS


@dataclass
class EnergyResult:
    kwh: float = 0.0  # positive Leistung (Bezug, Verbrauch, Produktion)
    kwh_negative: float = 0.0  # negative Leistung als positive Zahl (z.B. Rückspeisung an E1)
    hourly_kwh: List[float] = field(default_factory=lambda: [0.0] * 24)
    covered_ms: int = 0
    last_ts: int = 0


def typical_step_ms(series: Series) -> int:
    """Grösste Dauer, die ein Messwert gelten darf: 3 mal der mittlere Abstand (Median)."""
    gaps = sorted(b[0] - a[0] for a, b in zip(series, series[1:]) if b[0] > a[0])
    if not gaps:
        return STEP_MIN_MS
    median = gaps[len(gaps) // 2]
    return max(STEP_MIN_MS, min(STEP_MAX_MS, STEP_FACTOR * median))


def integrate(series: Series, start: int, end: int, hours: List[Tuple[int, int]]) -> EnergyResult:
    """Leistung über die Zeit aufsummieren.

    Jeder Wert gilt bis zum nächsten Wert, höchstens aber typical_step_ms.
    Längere Lücken zählen nicht und senken die Verfügbarkeit. Werte vor dem
    Tag zählen nicht, die Dauer wird am Tagesende abgeschnitten.
    """
    res = EnergyResult()
    pts = [p for p in series if start <= p[0] < end]
    if not pts:
        return res
    cap = typical_step_ms(series)
    starts = [h[0] for h in hours]
    for i, (t, p) in enumerate(pts):
        nxt = pts[i + 1][0] if i + 1 < len(pts) else end
        dt = min(nxt - t, cap, end - t)
        if dt <= 0:
            continue
        wh = p * dt / 3600_000.0
        res.covered_ms += dt
        hour = hours[max(bisect_right(starts, t) - 1, 0)][1]
        if p >= 0:
            res.kwh += wh / 1000.0
            res.hourly_kwh[hour] += wh / 1000.0
        else:
            res.kwh_negative += -wh / 1000.0
    res.last_ts = pts[-1][0]
    return res
