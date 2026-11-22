"""Zeitreihen-Hilfen: Tagesgrenzen in Lokalzeit, Zahlen lesen, Mittel pro Intervall."""
from bisect import bisect_right
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from aggregation.settings import TIMEZONE

TZ = ZoneInfo(TIMEZONE)

Series = List[Tuple[int, float]]  # (timestamp ms, Wert), nach Zeit sortiert


def day_bounds(day: date) -> Tuple[int, int]:
    """Beginn und Ende (exklusiv) eines Tages in Lokalzeit, in ms."""
    start = datetime(day.year, day.month, day.day, tzinfo=TZ)
    nxt = day + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=TZ)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def hour_bounds(day: date) -> List[Tuple[int, int]]:
    """Beginn jeder Stunde des Tages in ms und die Stunde auf der Uhr (0 bis 23).

    An der Zeitumstellung hat ein Tag 23 oder 25 Stunden. Die doppelte Stunde
    zählt dann auf dieselbe Uhrzeit.
    """
    start, end = day_bounds(day)
    out = []
    t = start
    while t < end:
        out.append((t, datetime.fromtimestamp(t / 1000, TZ).hour))
        t += 3600_000
    return out


def local_date(ts_ms: int) -> date:
    return datetime.fromtimestamp(ts_ms / 1000, TZ).date()


def local_hhmm(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, TZ).strftime('%H:%M')


def to_float(v) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN raus


def extract(points: Iterable[Tuple[int, dict]], field: str) -> Series:
    """Werte eines Feldes als sortierte Zeitreihe, ohne leere Werte."""
    out = []
    for ts, values in points:
        f = to_float((values or {}).get(field))
        if f is not None:
            out.append((int(ts), f))
    out.sort(key=lambda x: x[0])
    return out


def clip(series: Series, start: int, end: int) -> Series:
    return [(t, v) for t, v in series if start <= t < end]


def bucket_means(series: Series, start: int, end: int, bucket_ms: int) -> Dict[int, float]:
    """Mittelwert pro Intervall; Schlüssel = Beginn des Intervalls. Leere Intervalle fehlen."""
    sums: Dict[int, List[float]] = {}
    for t, v in series:
        if start <= t < end:
            b = start + ((t - start) // bucket_ms) * bucket_ms
            acc = sums.setdefault(b, [0.0, 0])
            acc[0] += v
            acc[1] += 1
    return {b: s / n for b, (s, n) in sums.items()}


def percentile(values: Sequence[float], q: float) -> Optional[float]:
    """Perzentil mit linearer Interpolation (wie numpy, Methode 'linear')."""
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def hour_index(bounds: List[Tuple[int, int]], ts: int) -> int:
    """Stunde auf der Uhr für einen Zeitpunkt innerhalb des Tages."""
    starts = [b[0] for b in bounds]
    i = bisect_right(starts, ts) - 1
    return bounds[max(i, 0)][1]


def rnd(v: Optional[float], digits: int) -> Optional[float]:
    return None if v is None else round(v, digits)
