"""Data-quality status per metering point.

Devices may send reserved keys with a leading underscore inside ``values``
(e.g. ``_q_status``, ``_q_tof_status``, ``_q_ok_ratio``). These keys describe
the quality of the measurement, not the measurement itself. They are removed
before the data point is stored and are kept only once, as the
``data_quality`` map on the metering point document:

    devices/{device_id}/metering_points/{mp}.data_quality = {
        "status": "ok" | "degraded" | "no_valid_data",
        "tof_status": 2,
        "ok_ratio": 0.67,
        "sensor_id": "apollon",
        "updated_at": <ms>,   # timestamp of the newest record
        "since": <ms>         # when the current status started
    }
"""
from typing import Any, Dict, Optional, Tuple

RESERVED_PREFIX = '_'
QUALITY_PREFIX = '_q_'


def split_reserved_values(values: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Split ``values`` into (measurement values, quality fields).

    All keys with a leading underscore are removed from the measurement values.
    Keys with the ``_q_`` prefix are returned without that prefix as quality fields;
    other underscore keys are dropped.
    """
    clean: Dict[str, Any] = {}
    quality: Dict[str, Any] = {}
    for key, value in values.items():
        if key.startswith(QUALITY_PREFIX):
            quality[key[len(QUALITY_PREFIX):]] = value
        elif key.startswith(RESERVED_PREFIX):
            continue
        else:
            clean[key] = value
    return clean, quality


def merge_data_quality(existing: Optional[Dict[str, Any]],
                       quality: Dict[str, Any],
                       sensor_id: str,
                       timestamp: int) -> Optional[Dict[str, Any]]:
    """Build the new ``data_quality`` map.

    Returns None if the stored status is newer than ``timestamp`` (a buffered
    old upload must not overwrite a newer status) or if no status was sent.
    ``since`` is kept while the status stays the same.
    """
    status = quality.get('status')
    if not status:
        return None

    existing = existing or {}
    if existing.get('updated_at') and existing['updated_at'] > timestamp:
        return None

    since = timestamp
    if existing.get('status') == status and existing.get('since'):
        since = existing['since']

    merged = {k: v for k, v in quality.items() if k != 'status'}
    merged.update({
        'status': status,
        'sensor_id': sensor_id,
        'updated_at': timestamp,
        'since': since,
    })
    return merged
