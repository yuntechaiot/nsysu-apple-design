"""Recommended charts must never fabricate continuity, pairs or daily totals."""
from copy import deepcopy
from datetime import datetime

import pytest

from nsysu.observation_views import (daily_buckets, daily_range_figure, observation_figure,
                                    paired_pressure_figure, recommended_view, sleep_duration_bars)


def row(value=60, day=1, hour=7, **extra):
    return dict(metric='HR', value=value, measured_at=f'2026-10-{day:02d}T{hour:02d}:00:00+08:00',
                unit='bpm', source='SYNTHETIC', device_external_id='watch', signal_type='PPG',
                algorithm_version='v1', **extra)


def dense():
    return [row(value=60 + day + hour, day=day, hour=hour) for day in (1, 2, 4) for hour in (7, 8, 9, 10)]


def test_recommendation_distinguishes_sparse_observations_from_repeated_daily_measurements():
    assert recommended_view([row(day=1), row(day=3)], ['HR']) == '原始點位'
    assert recommended_view(dense(), ['HR']) == '每日範圍'
    fig, description = observation_figure([row(day=1), row(day=3)], ['HR'])
    assert all(trace.mode == 'markers' for trace in fig.data) and '不連線' in description


def test_daily_ranges_keep_min_median_max_counts_and_leave_unobserved_dates_empty():
    records = dense()
    original = deepcopy(records)
    fig = daily_range_figure(records, ['HR'])
    trace = fig.data[0]
    assert [value.day for value in trace.x] == [1, 2, 4]
    assert list(trace.y) == [69.5, 70.5, 72.5]
    assert list(trace.error_y.array) == [1.5] * 3 and list(trace.error_y.arrayminus) == [1.5] * 3
    assert [d[2] for d in trace.customdata] == [4] * 3
    assert records == original


def test_daily_buckets_use_taipei_days_and_do_not_merge_versions_or_devices():
    records = [dict(row(0), measured_at='2026-09-30T23:00:00Z'), row(None),
               dict(row(100), algorithm_version='v2'), dict(row(200), device_external_id='other')]
    groups = daily_buckets(records, ['HR'])
    assert len(groups) == 3
    assert all(next(iter(days)).isoformat() == '2026-10-01' for days in groups.values())
    assert len(daily_range_figure(records, ['HR']).data) == 3
    assert any(list(trace.y) == [0] for trace in daily_range_figure(records, ['HR']).data)


def test_daily_range_rejects_incompatible_units_and_does_not_total_cumulative_counters():
    with pytest.raises(ValueError, match='相同單位'):
        daily_range_figure([row(), dict(row(), unit='unknown')], ['HR'])
    counters = [dict(r, metric='Steps', unit='steps') for r in dense()]
    assert recommended_view(counters, ['Steps']) == '原始點位'


def pressure(name, value, **extra):
    return dict(row(value), metric=name, unit='mmHg', **extra)


def test_bp_connectors_only_link_unambiguous_same_measurement_pairs():
    first = pressure('SBP', 120)
    second = pressure('DBP', 80)
    fig = paired_pressure_figure([first, second])
    assert fig.data[0].name == '同次量測' and list(fig.data[0].y) == [80, 120, None]
    assert recommended_view([first, second], ['SBP', 'DBP']) == '血壓配對'
    for different in [dict(second, external_record_id='other'),
                      dict(second, measured_at='2026-10-01T08:00:00+08:00'),
                      dict(second, device_external_id='other')]:
        assert all(t.name != '同次量測' for t in paired_pressure_figure([first, different]).data)
    ambiguous = paired_pressure_figure([first, dict(first, value=130), second])
    assert all(t.name != '同次量測' for t in ambiguous.data)


def test_original_line_remains_available():
    fig, _ = observation_figure([row(), row(None, day=2), row(70, day=3)], ['HR'], '折線圖')
    assert fig.data[0].mode == 'lines+markers' and list(fig.data[0].y) == [60, None, 70]


def test_every_observed_date_is_labeled_in_range_points_and_lines():
    records = [row(day=day) for day in range(14, 20)]
    expected = [f'10/{day}' for day in range(14, 20)]
    for choice in ['每日範圍', '原始點位', '折線圖']:
        fig, _ = observation_figure(records, ['HR'], choice)
        assert fig.layout.xaxis.tickmode == 'array'
        assert list(fig.layout.xaxis.ticktext) == expected


def test_cross_year_date_labels_include_year_and_do_not_drop_missing_value_dates():
    records = [dict(row(), measured_at='2026-12-31T07:00:00+08:00'),
               dict(row(None), measured_at='2027-01-01T07:00:00+08:00')]
    fig, _ = observation_figure(records, ['HR'], '原始點位')
    assert list(fig.layout.xaxis.ticktext) == ['2026/12/31', '2027/01/01']


def session(total, hour=0, day='2026-10-01'):
    return dict(sleep_date=day, start_at=f'{day}T{hour:02d}:00:00+08:00', tst_minutes=total,
                source='SYNTHETIC', external_session_id=str(hour))


def test_sleep_bars_preserve_same_day_records_missing_and_zero_without_summing():
    records = [session(420), session(60, hour=14), session(None, day='2026-10-02'), session(0, day='2026-10-03')]
    original = deepcopy(records)
    fig = sleep_duration_bars(records)
    assert fig.data[0].type == 'bar' and list(fig.data[0].y) == [7, 1, None, 0]
    assert len(set(fig.data[0].x)) == 4
    assert len(fig.layout.xaxis.ticktext) == 4
    assert fig.layout.yaxis.rangemode == 'tozero'
    assert [a.text for a in fig.layout.annotations] == ['未提供']
    assert records == original
    assert all(isinstance(value, str) for value in fig.data[0].x)
    assert datetime.fromisoformat(records[0]['start_at']).hour == 0
