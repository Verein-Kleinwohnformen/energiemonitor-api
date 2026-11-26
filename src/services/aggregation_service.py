"""Tageswerte lesen, rechnen und nach /devices/{id}/daily/{YYYY-MM-DD} schreiben.

Ablauf pro Gerät:
1. Gemessene Werte der gewünschten Tage aus den Rohdaten (aggregation.daily).
2. Formulareinträge lesen und Brennstoffe verteilen (aggregation.allocation).
   Kam seit dem letzten Lauf ein Eintrag dazu, oder ist es der Nachtlauf,
   werden alle Tage seit dem letzten abgeschlossenen Zeitraum neu verteilt.
   Sonst rechnet der stündliche Lauf nur den laufenden Zeitraum mit dem
   gespeicherten Stand (/devices/{id}/aggregation/state).
3. Schreiben. Tage, die nur neu verteilt werden, bekommen nur manual_alloc
   und manual_kwh_estimated, und nur wenn sich etwas geändert hat.
"""
import logging
import time
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from aggregation.allocation import DayInfo, Entry, allocate, can_use_state, entry_from_doc, methods_for, needed_from
from aggregation.daily import RawPoints, build_daily, raw_window
from aggregation.series import day_bounds, local_date

logger = logging.getLogger(__name__)

NEEDED_MPS = {'E1', 'E2', 'E3', 'A1', 'I1', 'I2', 'I3', 'K0'}
MAX_DAYS_PER_CALL = 31
# Neu verteilt werden höchstens so viele Tage zurück.
MAX_REALLOC_DAYS = 400
# Ein Telemetrie-Dokument enthält Punkte eines UTC-Tages.
DOC_SPAN_MAX_MS = 24 * 3600_000
# So viele aufeinanderfolgende Tage teilen sich eine Abfrage der Rohdaten.
RAW_BLOCK_DAYS = 7


def slice_raw(raw: RawPoints, w0: int, w1: int) -> RawPoints:
    """Punkte in [w0, w1) aus sortierten Rohdaten."""
    out: RawPoints = {}
    for key, pts in raw.items():
        ts = [p[0] for p in pts]
        part = pts[bisect_left(ts, w0):bisect_left(ts, w1)]
        if part:
            out[key] = part
    return out


def today_local(now_ms: Optional[int] = None) -> date:
    return local_date(now_ms if now_ms is not None else int(time.time() * 1000))


def date_range(first: date, last: date) -> List[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def heating_values_from(factors: Optional[dict]) -> Dict[str, float]:
    """Heizwerte (kWh pro Einheit des Formulars) aus /config/factors.

    Erwartet {"heating_values": {"pellets": {"value": 4.8, "unit": "kWh/kg", "source": ...}}}
    oder kurz {"heating_values": {"pellets": 4.8}}.
    """
    out = {}
    for k, v in ((factors or {}).get('heating_values') or {}).items():
        val = v.get('value') if isinstance(v, dict) else v
        try:
            out[k] = float(val)
        except (TypeError, ValueError):
            continue
    return out


class AggregationService:
    def __init__(self, db=None):
        if db is None:
            from google.cloud import firestore
            db = firestore.Client()
        self.db = db

    # --- Lesen -----------------------------------------------------------

    def list_devices(self) -> List[str]:
        # Geräte-Dokumente existieren oft nicht (nur Unterkollektionen), darum list_documents.
        return sorted(ref.id for ref in self.db.collection('devices').list_documents())

    def metering_points(self, device: str) -> List[str]:
        return [ref.id for ref in self.db.collection(f'devices/{device}/metering_points').list_documents()]

    def load_raw(self, device: str, day: date, now_ms: Optional[int] = None) -> RawPoints:
        """Rohdaten für einen Tag in Lokalzeit plus Rand (für Feuer über Mitternacht)."""
        return self.load_raw_window(device, *raw_window(day), now_ms=now_ms)

    def load_raw_window(self, device: str, w0: int, w1: int, now_ms: Optional[int] = None) -> RawPoints:
        """Rohdaten im Zeitraum [w0, w1).

        Telemetrie liegt nach UTC-Tagen in telemetry/{year}/{month}, ein
        Dokument pro Anfrage, Sensor und Messpunkt. Gelesen werden nur
        Dokumente mit end_timestamp ab w0 (Einzelfeld-Index), nicht ganze
        UTC-Tage: Für heute fällt so der Vortag bis auf den Rand weg. Ein
        Dokument reicht höchstens über einen UTC-Tag, darum endet es
        spätestens DOC_SPAN_MAX_MS nach w1. Jedes gelesene Dokument kostet
        einen Lesevorgang.
        """
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        upper = w1 + DOC_SPAN_MAX_MS
        raw: RawPoints = {}
        m = datetime.fromtimestamp(w0 / 1000, timezone.utc).date().replace(day=1)
        last = datetime.fromtimestamp(min(w1, now_ms + 3600_000) / 1000, timezone.utc).date()
        while m <= last:
            q = self.db.collection(f'devices/{device}/telemetry/{m.year}/{m.month:02d}').where(
                'end_timestamp', '>=', w0)
            if upper <= now_ms:
                q = q.where('end_timestamp', '<', upper)
            for doc in q.stream():
                f = doc.to_dict()
                mp = f.get('metering_point')
                if mp not in NEEDED_MPS or f.get('start_timestamp', w0) >= w1:
                    continue
                pts = raw.setdefault((mp, f.get('sensor_id')), [])
                for p in f.get('data_points') or []:
                    ts = p.get('timestamp')
                    if ts is not None and w0 <= ts < w1:
                        pts.append((ts, p.get('values') or {}))
            m = (m + timedelta(days=32)).replace(day=1)
        for pts in raw.values():
            pts.sort(key=lambda x: x[0])
        return raw

    def load_raw_days(self, device: str, days: List[date], now_ms: int) -> Dict[date, RawPoints]:
        """Rohdaten für mehrere Tage: aufeinanderfolgende Tage in Blöcken von
        höchstens RAW_BLOCK_DAYS mit einer Abfrage, dann pro Tag geschnitten.
        Vorher las jeder Tag für sich zwei bis drei ganze UTC-Tage."""
        out: Dict[date, RawPoints] = {}
        blocks: List[List[date]] = []
        for d in sorted(days):
            if blocks and (d - blocks[-1][-1]).days == 1 and len(blocks[-1]) < RAW_BLOCK_DAYS:
                blocks[-1].append(d)
            else:
                blocks.append([d])
        for block in blocks:
            raw = self.load_raw_window(device, raw_window(block[0])[0], raw_window(block[-1])[1], now_ms)
            for d in block:
                out[d] = slice_raw(raw, *raw_window(d))
        return out

    def load_entries(self, device: str) -> List[Entry]:
        entries = []
        for year_ref in self.db.collection(f'devices/{device}/manual').list_documents():
            for doc in year_ref.collection('data').stream():
                e = entry_from_doc(doc.id, doc.to_dict())
                if e is not None:
                    entries.append(e)
        return entries

    def load_factors(self) -> dict:
        snap = self.db.document('config/factors').get()
        return snap.to_dict() if snap.exists else {}

    def load_daily(self, device: str, days: Iterable[date]) -> Dict[date, dict]:
        refs = [self.db.document(f'devices/{device}/daily/{d.isoformat()}') for d in days]
        out: Dict[date, dict] = {}
        if not refs:
            return out
        for snap in self.db.get_all(refs):
            if snap.exists:
                out[date.fromisoformat(snap.id)] = snap.to_dict()
        return out

    def load_state(self, device: str) -> dict:
        snap = self.db.document(f'devices/{device}/aggregation/state').get()
        return (snap.to_dict() or {}).get('series', {}) if snap.exists else {}

    # --- Rechnen ---------------------------------------------------------

    def run_device(self, device: str, days: List[date], now_ms: Optional[int] = None,
                   full_realloc: bool = False, dry_run: bool = False,
                   realloc_from: Optional[date] = None) -> dict:
        """Tageswerte für days rechnen und schreiben. Liefert eine Zusammenfassung.

        realloc_from: Brennstoffe ab diesem Tag neu verteilen (Backfill), sonst
        ab dem letzten abgeschlossenen Zeitraum, höchstens MAX_REALLOC_DAYS zurück.
        """
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        days = sorted(d for d in set(days) if day_bounds(d)[0] <= now_ms)
        if not days:
            return {'device': device, 'days': [], 'written': 0}
        mps = self.metering_points(device)
        raw = self.load_raw_days(device, days, now_ms)
        docs = {d: build_daily(d, raw[d], now_ms, mps) for d in days}

        entries = self.load_entries(device)
        heating_values = heating_values_from(self.load_factors()) if entries else {}
        state = self.load_state(device)
        series: Dict[str, List[Entry]] = {}
        for e in entries:
            if methods_for(e.energy_type) is not None:
                series.setdefault(f'{e.metering_point}|{e.energy_type}', []).append(e)

        day_infos = {d: DayInfo.from_daily(d, *day_bounds(d), doc) for d, doc in docs.items()}
        stale = any(not can_use_state(ents, state.get(k), day_infos, days) for k, ents in series.items())
        output_days = list(days)
        existing: Dict[date, dict] = {}
        if series and (full_realloc or stale or realloc_from is not None):
            # Ganze Saisons: auch Saisons, in denen die Ausgabetage liegen.
            starts = [needed_from(ents, since=day_bounds(days[0])[0]) for ents in series.values()]
            first = min(local_date(s) for s in starts if s is not None)
            first = max(min(first, days[0]), days[-1] - timedelta(days=MAX_REALLOC_DAYS))
            if realloc_from is not None:
                first = min(first, realloc_from)
            span = date_range(first, days[-1])
            existing = self.load_daily(device, [d for d in span if d not in docs])
            for d in span:
                if d not in docs:
                    # Tage ohne Tagesdokument zählen mit, aber ohne Feuer, Belegung und Klima.
                    day_infos[d] = DayInfo.from_daily(d, *day_bounds(d), existing.get(d, {}))
            output_days = sorted(set(days) | set(existing))
            state_in = None
        else:
            state_in = state

        alloc, kwh, new_state = allocate(entries, day_infos, output_days, heating_values, state=state_in)

        writes = 0
        for d, doc in docs.items():
            doc['manual_alloc'] = alloc.get(d, {})
            doc['manual_kwh_estimated'] = kwh.get(d, {})
            if not dry_run:
                self.db.document(f'devices/{device}/daily/{d.isoformat()}').set(doc)
            writes += 1
        realloc = 0
        for d, old in existing.items():
            new_alloc, new_kwh = alloc.get(d, {}), kwh.get(d, {})
            if old.get('manual_alloc') == new_alloc and old.get('manual_kwh_estimated') == new_kwh:
                continue
            if not dry_run:
                self.db.document(f'devices/{device}/daily/{d.isoformat()}').update(
                    {'manual_alloc': new_alloc, 'manual_kwh_estimated': new_kwh})
            realloc += 1
        if new_state != state and not dry_run:
            self.db.document(f'devices/{device}/aggregation/state').set(
                {'series': new_state, 'updated_at': datetime.now(timezone.utc).isoformat()})

        return {'device': device, 'days': [d.isoformat() for d in days], 'written': writes,
                'reallocated': realloc, 'full_realloc': bool(state_in is None and series),
                'docs': docs if dry_run else None}

    def run(self, mode: str, devices: Optional[List[str]] = None, first: Optional[date] = None,
            last: Optional[date] = None, days_back: int = 3, dry_run: bool = False) -> List[dict]:
        """hourly: heute. nightly: die letzten days_back Tage, alles neu verteilt. range: first bis last."""
        today = today_local()
        if mode == 'hourly':
            days, full = [today], False
        elif mode == 'nightly':
            days, full = date_range(today - timedelta(days=days_back), today - timedelta(days=1)), True
        elif mode == 'range':
            if first is None or last is None or last < first:
                raise ValueError('range braucht from und to')
            days, full = date_range(first, last), True
        else:
            raise ValueError(f'unbekannter Modus: {mode}')
        if len(days) > MAX_DAYS_PER_CALL:
            raise ValueError(f'höchstens {MAX_DAYS_PER_CALL} Tage pro Aufruf')
        results = []
        for device in devices or self.list_devices():
            try:
                res = self.run_device(device, days, full_realloc=full, dry_run=dry_run)
            except Exception as e:  # ein Gerät mit Fehler hält die anderen nicht auf
                logger.error(f'Tageswerte {device}: {e}', exc_info=True)
                res = {'device': device, 'error': str(e)}
            res.pop('docs', None)
            results.append(res)
        return results
