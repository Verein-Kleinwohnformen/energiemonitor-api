"""Tageswerte für vergangene Tage rechnen (Backfill), lokal mit dem gcloud-Login.

Ohne --apply wird nur gerechnet und eine Zusammenfassung gezeigt, nichts
geschrieben. Gegen den Emulator: FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 setzen.

    python tools/backfill_daily.py --project <projekt> --device <gerät> --from 2026-04-01 --to 2026-09-30
    python tools/backfill_daily.py --project <projekt> --device <gerät> --from 2026-04-01 --to 2026-09-30 --apply

Braucht Application Default Credentials (gcloud auth application-default login)
mit Schreibrecht auf Firestore, wenn --apply gesetzt ist.
"""
import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.aggregation_service import MAX_DAYS_PER_CALL, AggregationService, date_range  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--project', required=True)
    ap.add_argument('--device', action='append', help='Gerät, mehrfach möglich; ohne Angabe alle')
    ap.add_argument('--from', dest='first', required=True, type=date.fromisoformat)
    ap.add_argument('--to', dest='last', required=True, type=date.fromisoformat)
    ap.add_argument('--apply', action='store_true', help='wirklich schreiben')
    args = ap.parse_args()

    from google.cloud import firestore
    svc = AggregationService(firestore.Client(project=args.project))
    devices = args.device or svc.list_devices()
    days = date_range(args.first, args.last)
    print(f"{'Schreibe' if args.apply else 'Probelauf, schreibt nichts:'} {len(days)} Tage, Geräte {devices}")

    for device in devices:
        # In Blöcken rechnen; die Verteilung der Brennstoffe läuft im letzten Block über alles neu.
        for i in range(0, len(days), MAX_DAYS_PER_CALL):
            block = days[i:i + MAX_DAYS_PER_CALL]
            res = svc.run_device(device, block, full_realloc=True, dry_run=not args.apply)
            docs = res.pop('docs', None) or {}
            line = f"{device} {block[0]} bis {block[-1]}: {res.get('written')} Tage"
            if docs:
                pv = sum((d['energy_kwh'].get('E3') or 0) for d in docs.values())
                grid = sum((d['energy_kwh'].get('E1') or 0) for d in docs.values())
                occ = sum(1 for d in docs.values() if d.get('occupied'))
                fires = sum(len(d.get('fire_events') or []) for d in docs.values())
                line += f', PV {pv:.1f} kWh, Netz {grid:.1f} kWh, bewohnt {occ}, Feuer {fires}'
            else:
                line += f", neu verteilt {res.get('reallocated')}"
            print(line, flush=True)


if __name__ == '__main__':
    main()
