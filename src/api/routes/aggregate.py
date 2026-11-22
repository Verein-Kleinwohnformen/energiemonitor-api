"""Tageswerte rechnen: POST /aggregate (nur Cloud Scheduler).

Parameter (Query oder JSON):
- mode: hourly (heute), nightly (die letzten days_back Tage, Standard 3) oder range
- device: ein Gerät; ohne Angabe alle Geräte
- from, to: YYYY-MM-DD für mode=range (höchstens 31 Tage), auch date als Abkürzung für einen Tag
"""
import logging
from datetime import date

from flask import Blueprint, jsonify, request

from middleware.scheduler_auth import require_scheduler

logger = logging.getLogger(__name__)
aggregate_bp = Blueprint('aggregate', __name__)
_service = None


def get_service():
    global _service
    if _service is None:
        from services.aggregation_service import AggregationService
        _service = AggregationService()
    return _service


def _param(body: dict, name: str):
    return request.args.get(name) or body.get(name)


@aggregate_bp.route('/aggregate', methods=['POST'])
@require_scheduler
def aggregate():
    body = request.get_json(silent=True) or {}
    mode = _param(body, 'mode') or 'hourly'
    device = _param(body, 'device')
    try:
        single = _param(body, 'date')
        first = _param(body, 'from') or single
        last = _param(body, 'to') or single
        first = date.fromisoformat(first) if first else None
        last = date.fromisoformat(last) if last else None
        if single:
            mode = 'range'
        days_back = int(_param(body, 'days_back') or 3)
        if not 1 <= days_back <= 31:
            raise ValueError('days_back zwischen 1 und 31')
        results = get_service().run(mode, [device] if device else None, first, last, days_back)
    except ValueError as e:
        return jsonify({'error': 'Invalid parameters', 'message': str(e)}), 400
    failed = [r for r in results if 'error' in r]
    logger.info(f'Aggregate {mode}: {len(results)} devices, {len(failed)} failed')
    return jsonify({'mode': mode, 'results': results}), (500 if failed and len(failed) == len(results) else 200)
