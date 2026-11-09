"""Tests for reserved value keys and the data_quality map (no Firebase needed)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.data_quality import split_reserved_values, merge_data_quality  # noqa: E402


def test_split_removes_all_underscore_keys():
    clean, quality = split_reserved_values({
        'level_liter': 918,
        '_q_status': 'degraded',
        '_q_tof_status': 2,
        '_q_ok_ratio': 0.5,
        '_internal': 'x',
    })
    assert clean == {'level_liter': 918}
    assert quality == {'status': 'degraded', 'tof_status': 2, 'ok_ratio': 0.5}


def test_split_without_reserved_keys_is_unchanged():
    values = {'voltage': 231.2, 'act_power': 14.5}
    clean, quality = split_reserved_values(values)
    assert clean == values
    assert quality == {}


def test_quality_only_record_leaves_no_values():
    clean, quality = split_reserved_values({'_q_status': 'no_valid_data', '_q_tof_status': 7})
    assert clean == {}
    assert quality['status'] == 'no_valid_data'


def test_merge_new_status_sets_since():
    merged = merge_data_quality(None, {'status': 'degraded', 'tof_status': 2}, 'apollon', 1000)
    assert merged == {'status': 'degraded', 'tof_status': 2, 'sensor_id': 'apollon',
                      'updated_at': 1000, 'since': 1000}


def test_merge_same_status_keeps_since():
    existing = {'status': 'degraded', 'since': 1000, 'updated_at': 1000}
    merged = merge_data_quality(existing, {'status': 'degraded', 'ok_ratio': 0.3}, 'apollon', 5000)
    assert merged['since'] == 1000
    assert merged['updated_at'] == 5000
    assert merged['ok_ratio'] == 0.3


def test_merge_status_change_resets_since():
    existing = {'status': 'degraded', 'since': 1000, 'updated_at': 4000}
    merged = merge_data_quality(existing, {'status': 'ok'}, 'apollon', 5000)
    assert merged['since'] == 5000


def test_merge_ignores_older_record():
    existing = {'status': 'ok', 'since': 1000, 'updated_at': 9000}
    assert merge_data_quality(existing, {'status': 'degraded'}, 'apollon', 5000) is None


def test_merge_without_status_is_ignored():
    assert merge_data_quality(None, {'tof_status': 2}, 'apollon', 5000) is None
