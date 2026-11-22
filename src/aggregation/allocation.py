"""Pellets, Holz und Gas aus den Formulareinträgen auf Tage verteilen.

Das Formular liefert pro Eintrag Kaufmenge, Rest und Datum. Daraus kennt man
den Verbrauch zwischen zwei Einträgen (consumed_quantity des späteren
Eintrags), nicht wann er stattfand. Konzept: 05_infotexte.md, Abschnitt 2.

Abgeschlossener Zeitraum (zwei Einträge): Die Menge wird nach der ersten
Methode verteilt, die im Zeitraum ein Gewicht grösser 0 hat:
- Pellets, Holz, Heizöl: Ofensignatur (Feuer gewichtet mit Brenndauer),
  sonst Heizgradtage, sonst gleichmässig.
- Gas: bewohnte Tage, sonst gleichmässig.

Laufender Zeitraum (nach dem letzten Eintrag): Menge pro Gewicht aus dem
letzten abgeschlossenen Zeitraum mit Verbrauch, als vorläufig markiert. Gibt
es keinen, bleibt die Menge offen (None), bei Feuern bleibt die Zahl.

Ein Tag, der nur teilweise im Zeitraum liegt, zählt anteilig (Feuer nach
Startzeit). Diesel und Benzin werden nicht verteilt.
"""
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from aggregation.settings import FIRE_FUELS, HDD_BASE_C, HDD_LIMIT_C, METHODS_FIRE, METHODS_OCCUPANCY, OCCUPANCY_FUELS


@dataclass
class Entry:
    ts: int  # Zeitpunkt des Eintrags (purchase_date), ms
    energy_type: str
    metering_point: str
    consumed: float  # Verbrauch seit dem vorherigen Eintrag gleicher Art und gleichen Messpunkts
    unit: str
    entry_id: str = ''


@dataclass
class DayInfo:
    """Was die Verteilung von einem Tag braucht (aus dem Tagesdokument)."""
    day: date
    start: int
    end: int
    fires: List[Tuple[int, float]]  # (start_ts, weight)
    occupied: Optional[bool]
    t_out_mean: Optional[float]

    @classmethod
    def from_daily(cls, day: date, start: int, end: int, doc: dict) -> 'DayInfo':
        fires = [(int(f['start_ts']), float(f.get('weight') or 0)) for f in (doc.get('fire_events') or [])
                 if f.get('start_ts') is not None]
        return cls(day, start, end, fires, doc.get('occupied'), (doc.get('climate') or {}).get('t_out_mean'))


def entry_from_doc(doc_id: str, doc: dict) -> Optional[Entry]:
    """Formulareintrag aus /devices/{id}/manual/{year}/data/{uuid} (Format von energy.dart)."""
    meta = doc.get('metadata') or {}
    etype = meta.get('energy_type') or doc.get('type')
    ts = meta.get('purchase_date') or doc.get('start_timestamp') or doc.get('timestamp')
    points = doc.get('data_points') or [{}]
    values = (points[0] or {}).get('values') or {}
    if etype is None or ts is None:
        return None
    if hasattr(ts, 'timestamp'):
        ts = int(ts.timestamp() * 1000)
    try:
        consumed = float(values.get('consumed_quantity') or 0)
    except (TypeError, ValueError):
        consumed = 0.0
    return Entry(int(ts), etype, doc.get('metering_point') or 'M0', consumed, values.get('unit') or '', doc_id)


def needed_from(entries: List[Entry]) -> Optional[int]:
    """Ab wann Tageswerte nötig sind, um den laufenden Zeitraum zu schätzen:
    Beginn des letzten abgeschlossenen Zeitraums mit Verbrauch."""
    entries = sorted(entries, key=lambda e: e.ts)
    for prev, cur in reversed(list(zip(entries, entries[1:]))):
        if cur.consumed > 0:
            return prev.ts
    return entries[-1].ts if entries else None


def methods_for(energy_type: str) -> Optional[List[str]]:
    if energy_type in FIRE_FUELS:
        return METHODS_FIRE
    if energy_type in OCCUPANCY_FUELS:
        return METHODS_OCCUPANCY
    return None


def _overlap(day: DayInfo, lo: int, hi: Optional[int]) -> float:
    a = max(day.start, lo)
    b = min(day.end, hi) if hi is not None else day.end
    return max(0, b - a) / (day.end - day.start)


def day_weight(method: str, day: DayInfo, lo: int, hi: Optional[int]) -> float:
    """Gewicht eines Tages im Zeitraum [lo, hi) für eine Methode."""
    frac = _overlap(day, lo, hi)
    if frac == 0:
        return 0.0
    if method == 'ofensignatur':
        return sum(w for t, w in day.fires if t >= lo and (hi is None or t < hi))
    if method == 'heizgradtage':
        if day.t_out_mean is None or day.t_out_mean >= HDD_LIMIT_C:
            return 0.0
        return frac * (HDD_BASE_C - day.t_out_mean)
    if method == 'bewohnte_tage':
        # TODO(prüfen): Tage mit unbekannter Belegung (None) zählen wie bewohnte.
        return 0.0 if day.occupied is False else frac
    return frac  # gleichmaessig


def fires_in(day: DayInfo, lo: int, hi: Optional[int]) -> int:
    return sum(1 for t, _ in day.fires if t >= lo and (hi is None or t < hi))


def _days_between(days: Dict[date, DayInfo], lo: int, hi: Optional[int]) -> List[DayInfo]:
    return [d for d in days.values() if d.end > lo and (hi is None or d.start < hi)]


@dataclass
class DayAlloc:
    quantity: Optional[float]
    method: str
    provisional: bool
    fires: Optional[int] = None


def allocate_series(entries: List[Entry], days: Dict[date, DayInfo],
                    output_days: Iterable[date]) -> Tuple[Dict[date, DayAlloc], Optional[dict]]:
    """Verteilung einer Reihe (gleicher Messpunkt und Energieträger).

    days muss alle Tage vom Beginn des letzten abgeschlossenen Zeitraums bis zum
    letzten Ausgabetag enthalten, sowie alle Ausgabetage. Liefert die Werte der
    Ausgabetage und die Menge pro Gewicht für den laufenden Zeitraum (rates).
    """
    entries = sorted(entries, key=lambda e: e.ts)
    if not entries:
        return {}, None
    methods = methods_for(entries[0].energy_type)
    if methods is None:
        return {}, None
    wanted = set(output_days)
    out: Dict[date, DayAlloc] = {}

    rates: Optional[dict] = None
    first_day = min((d.start for d in days.values()), default=None)
    for prev, cur in zip(entries, entries[1:]):
        lo, hi = prev.ts, cur.ts
        complete = first_day is not None and first_day <= lo
        if not complete and not any(d.end > lo and d.start < hi for d in days.values() if d.day in wanted):
            continue
        span = _days_between(days, lo, hi)
        totals = {m: sum(day_weight(m, d, lo, hi) for d in span) for m in methods}
        method = next((m for m in methods if totals[m] > 0), methods[-1])
        if cur.consumed > 0 and complete and any(totals.values()):
            rates = {'from_ts': lo, 'to_ts': hi, 'quantity': cur.consumed,
                     'per_weight': {m: cur.consumed / t for m, t in totals.items() if t > 0}}
        for d in span:
            if d.day not in wanted:
                continue
            w = day_weight(method, d, lo, hi)
            qty = cur.consumed * w / totals[method] if totals[method] > 0 else 0.0
            _add(out, d.day, qty, method, False, fires_in(d, lo, hi) if method == 'ofensignatur' else None)

    running_from = entries[-1].ts
    running_alloc(out, running_from, methods, rates, days, wanted)
    return out, {'running_from': running_from, 'rates': rates, 'entry_count': len(entries)}


def running_alloc(out: Dict[date, DayAlloc], running_from: int, methods: List[str], rates: Optional[dict],
                  days: Dict[date, DayInfo], wanted) -> None:
    """Vorläufige Werte für den laufenden Zeitraum seit dem letzten Eintrag."""
    span = _days_between(days, running_from, None)
    totals = {m: sum(day_weight(m, d, running_from, None) for d in span) for m in methods}
    method = next((m for m in methods if totals[m] > 0), methods[-1])
    per_weight = (rates or {}).get('per_weight', {}).get(method)
    for d in span:
        if d.day not in wanted:
            continue
        w = day_weight(method, d, running_from, None)
        qty = per_weight * w if per_weight is not None else None
        _add(out, d.day, qty, method, True, fires_in(d, running_from, None) if method == 'ofensignatur' else None)


def _add(out: Dict[date, DayAlloc], day: date, qty: Optional[float], method: str, provisional: bool,
         fires: Optional[int]) -> None:
    """Ein Tag mit zwei Zeiträumen (Eintrag am Tag) bekommt die Summe."""
    if day in out:
        a = out[day]
        a.quantity = None if a.quantity is None or qty is None else a.quantity + qty
        a.provisional = a.provisional or provisional
        if fires is not None:
            a.fires = (a.fires or 0) + fires
        if provisional:
            a.method = method
        return
    out[day] = DayAlloc(qty, method, provisional, fires)


def can_use_state(ents: List[Entry], st: Optional[dict], days: Dict[date, DayInfo], output_days) -> bool:
    """Der gespeicherte Stand gilt, wenn seither kein Eintrag dazukam und alle
    Ausgabetage nach dem letzten Eintrag beginnen."""
    if not st or st.get('entry_count') != len(ents):
        return False
    last = max(e.ts for e in ents)
    if st.get('running_from') != last:
        return False
    return all(d in days and days[d].start >= last for d in output_days)


def allocate(entries: List[Entry], days: Dict[date, DayInfo], output_days: Iterable[date],
             heating_values: Optional[Dict[str, float]] = None,
             state: Optional[dict] = None) -> Tuple[Dict[date, dict], Dict[date, dict], dict]:
    """Alle Reihen eines Geräts verteilen.

    Liefert pro Tag manual_alloc und manual_kwh_estimated sowie den Stand für
    die schnelle stündliche Rechnung (state). heating_values kommt aus
    /config/factors (kWh pro Einheit); ohne Faktor bleibt kWh leer.

    Mit einem gespeicherten state und ohne neuen Eintrag rechnet die Funktion
    nur den laufenden Zeitraum mit der gespeicherten Menge pro Gewicht; dann
    reichen die Ausgabetage in days.
    """
    output_days = list(output_days)
    series: Dict[Tuple[str, str], List[Entry]] = {}
    for e in entries:
        series.setdefault((e.metering_point, e.energy_type), []).append(e)

    alloc: Dict[date, dict] = {}
    new_state: dict = {}
    for (mp, etype), ents in sorted(series.items()):
        key = f'{mp}|{etype}'
        methods = methods_for(etype)
        if methods is None:
            continue
        st_old = (state or {}).get(key)
        if can_use_state(ents, st_old, days, output_days):
            per_day: Dict[date, DayAlloc] = {}
            running_alloc(per_day, st_old['running_from'], methods, st_old.get('rates'), days, set(output_days))
            st = st_old
        else:
            per_day, st = allocate_series(ents, days, output_days)
        if st is not None:
            new_state[key] = st
        unit = next((e.unit for e in ents if e.unit), '')
        for d, a in per_day.items():
            _merge(alloc.setdefault(d, {}), etype, mp, a, unit)

    kwh: Dict[date, dict] = {}
    for d, per_type in alloc.items():
        for etype, a in per_type.items():
            a.pop('_provisional', None)
            hv = (heating_values or {}).get(etype)
            if hv is not None and a['quantity'] is not None:
                kwh.setdefault(d, {})[etype] = round(a['quantity'] * hv, 3)
    return alloc, kwh, new_state


def _merge(day_alloc: dict, etype: str, mp: str, a: DayAlloc, unit: str) -> None:
    """Mehrere Messpunkte eines Energieträgers zusammenzählen.

    Ist ein Teil unbekannt (laufender Zeitraum ohne Vergleichswert), zählen die
    bekannten Teile; incomplete sagt, dass etwas fehlt. Nur wenn alles
    unbekannt ist, bleibt quantity leer.
    """
    qty = None if a.quantity is None else round(a.quantity, 3)
    cur = day_alloc.get(etype)
    if cur is None:
        cur = day_alloc[etype] = {'quantity': None, 'unit': unit, 'method': a.method, 'provisional': False,
                                  'incomplete': False, 'by_metering_point': {}}
    cur['by_metering_point'][mp] = qty
    cur.setdefault('_provisional', {})[mp] = a.provisional
    known = [m for m, v in cur['by_metering_point'].items() if v is not None]
    cur['quantity'] = round(sum(cur['by_metering_point'][m] for m in known), 3) if known else None
    cur['incomplete'] = len(known) < len(cur['by_metering_point'])
    # vorläufig, wenn ein bekannter Teil vorläufig ist (oder alles unbekannt und vorläufig)
    parts = known or list(cur['by_metering_point'])
    cur['provisional'] = any(cur['_provisional'][m] for m in parts)
    if qty is not None and qty > 0:
        cur['method'] = a.method
    if a.fires is not None:
        # Feuer gehören zum Tag, nicht zum Messpunkt: nicht doppelt zählen.
        cur['fires'] = max(cur.get('fires') or 0, a.fires)
