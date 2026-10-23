"""Word definitions, cross-source pairing and caller-scoped pre-sleep windows."""
from copy import deepcopy
from datetime import date, datetime

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from nsysu import dashboard_flow
from nsysu.platform import Platform, KINDS
from nsysu.platform_data import load_platform_bundle
from nsysu.sleep import TZ, sleep_metrics
from nsysu.sleep_parameters import calculate_parameters, period_parameters, instant, pre_sleep_means
from nsysu.sleep_parameters_view import csv_bytes, parameter_figure, record_table
from nsysu.store import Store, StoreError


def night():
    log = dict(id='DIARY-TEST', member_id='ycc00000001', date='2026-10-20', date_definition='wake_date',
               bedtime='22:30', final_wake_time='07:00', out_of_bed_time='07:15', wakeup_count=2,
               bedtime_at='2026-10-19T22:30:00+08:00', final_wake_at='2026-10-20T07:00:00+08:00',
               out_of_bed_at='2026-10-20T07:15:00+08:00', lights_out_at='2026-10-19T22:45:00+08:00')
    session = dict(external_session_id='WATCH-TEST', member_id=log['member_id'], source='SYNTHETIC',
                   sleep_date=log['date'], start_at='2026-10-19T22:45:00+08:00',
                   end_at='2026-10-20T07:00:00+08:00', sleep_onset_at='2026-10-19T23:00:00+08:00',
                   awake_minutes=30, tst_minutes=450, waso_minutes=20)
    return log, session


def readings():
    return [dict(metric=metric, value=value, source='SYNTHETIC', unit=None, signal_type='PPG',
                 algorithm_version='test-v1', device_external_id='WATCH-TEST',
                 measured_at=f'2026-10-19T{clock}:00+08:00') for metric, clock, value in [
        ('stress', '21:59', 100), ('stress', '22:00', -2), ('stress', '22:30', 2),
        ('stress', '23:00', 100), ('fatigue', '22:10', 0), ('fatigue', '22:50', 10)]]


def test_all_word_formulas_differ_from_research_without_modifying_inputs():
    log, session = night()
    original = deepcopy((log, session))
    result = calculate_parameters(log, session, readings())
    assert result['values'] == dict(tib_minutes=525, tst_minutes=480, sol_minutes=30, awakening_count=2,
                                    waso_minutes=30, se_percent=pytest.approx(480 / 525 * 100), rise_minutes=15)
    assert {r['metric']: (r['mean'], r['count']) for r in result['pre_sleep']} == {'stress': (0, 2), 'fatigue': (5, 2)}
    assert result['window_start'] == '2026-10-19T22:00:00+08:00'
    assert sleep_metrics(log, session)['sol_minutes'] == 15
    assert sleep_metrics(log, session)['tst_minutes'] == 450
    assert sleep_metrics(log, session)['waso_minutes'] == 20
    assert (log, session) == original


def test_wake_date_clocks_cross_midnight_and_independent_parameters_survive_missing_onset():
    log, session = night()
    for field in ('bedtime_at', 'final_wake_at', 'out_of_bed_at'):
        log.pop(field)
    result = calculate_parameters(log, dict(session, sleep_onset_at=None))
    assert result['values']['tib_minutes'] == 525 and result['values']['rise_minutes'] == 15
    assert result['times']['bed'].day == 19
    assert result['values']['tst_minutes'] is None and result['values']['se_percent'] is None
    log.pop('final_wake_time')
    assert calculate_parameters(log)['values']['tib_minutes'] == 525


@pytest.mark.parametrize('changes', [dict(date_definition='legacy'), dict(final_wake_at='2026-10-21T07:00:00+08:00'),
                                    dict(bedtime_at='2026-10-19T22:30:00'), dict(out_of_bed_at='2026-10-19T21:00:00+08:00')])
def test_unconfirmed_or_invalid_diary_times_are_not_guessed(changes):
    log, session = night()
    result = calculate_parameters(dict(log, **changes), session)
    assert result['values']['tib_minutes'] is None and result['values']['tst_minutes'] is None
    assert result['notes']


def test_observed_stage_start_requires_opt_in_and_never_uses_session_start():
    log, session = night()
    session['sleep_onset_at'] = None
    session['stages'] = [dict(stage='awake', start_at=session['start_at']),
                         dict(stage='light', start_at='2026-10-19T23:00:00+08:00', end_at=None)]
    assert calculate_parameters(log, session)['values']['sol_minutes'] is None
    result = calculate_parameters(log, session, allow_observed=True)
    assert result['values']['sol_minutes'] == 30 and '非完整' in result['onset_basis']
    session['sleep_onset_at'] = 'invalid'
    assert calculate_parameters(log, session, allow_observed=True)['values']['sol_minutes'] is None


def test_true_zeros_missing_values_and_impossible_awake_summary():
    log, session = night()
    log.update(wakeup_count=0, bedtime_at=session['sleep_onset_at'], out_of_bed_at=log['final_wake_at'])
    result = calculate_parameters(log, dict(session, awake_minutes=0))
    assert result['values']['awakening_count'] == result['values']['waso_minutes'] == result['values']['sol_minutes'] == 0
    assert result['values']['se_percent'] == 100
    assert calculate_parameters()['values'] == dict.fromkeys(result['values'])
    assert calculate_parameters(log, dict(session, awake_minutes=9999))['values']['waso_minutes'] is None
    assert calculate_parameters(dict(log, wakeup_count=1.5), session)['values']['awakening_count'] is None


def test_mismatched_members_dates_and_onsets_do_not_produce_hybrid_values():
    log, session = night()
    for changes in [dict(member_id='OTHER'), dict(sleep_date='2026-10-21'),
                    dict(sleep_onset_at='2026-10-20T08:00:00+08:00', end_at=None)]:
        result = calculate_parameters(log, dict(session, **changes))
        assert result['values']['tst_minutes'] is None and result['values']['sol_minutes'] is None
        assert result['values']['tib_minutes'] == 525


def test_means_are_half_open_finite_and_separate_by_source_device_version_scale():
    onset = instant('2026-10-19T15:00:00Z')
    base = readings()[1]
    others = [dict(base, value=20, **changes) for changes in [dict(source='OTHER'), dict(device_external_id='OTHER'),
              dict(algorithm_version='v2'), dict(signal_type='ECG'), dict(unit='points'), dict(scale_definition='new scale')]]
    invalid = [dict(base, value=v) for v in [None, True, float('nan'), float('inf'), 'bad']]
    invalid += [dict(base, member_id='OTHER'), dict(base, measured_at='2026-10-19T22:30:00')]
    groups = pre_sleep_means(readings() + others + invalid, onset, 60, 'ycc00000001')
    assert len(groups) == 8 and sum(r['count'] for r in groups) == 10
    assert pre_sleep_means(readings(), onset, 30)[1]['mean'] == 2
    assert pre_sleep_means(readings(), None) == []


def test_period_does_not_merge_ambiguous_sessions_or_diaries():
    log, session = night()
    rows = period_parameters([log], [session, dict(session, external_session_id='SECOND')], readings())
    assert len(rows) == 3 and all(r['values']['tst_minutes'] is None for r in rows)
    rows = period_parameters([log, dict(log, id='SECOND')], [session], readings())
    assert len(rows) == 3 and all(r['values']['tst_minutes'] is None for r in rows)
    rows = period_parameters([log], [session], readings())
    assert len(rows) == 1 and rows[0]['values']['tst_minutes'] == 480
    frame = record_table(rows)
    assert frame.iloc[0]['入睡前平均壓力指數'] == 0
    assert frame.iloc[0]['睡眠日期'] == '2026-10-20'
    assert '定義版本' in frame
    safe = csv_bytes(pd.DataFrame([{'來源': '=SUM(1)'}])).decode('utf-8-sig')
    assert "'=SUM(1)" in safe


def test_period_chart_labels_every_record_date_including_missing_same_date():
    log, session = night()
    results = period_parameters([log], [session, dict(session, external_session_id='SECOND')], [])
    fig = parameter_figure(results, 'tst_minutes', 'TST', '分鐘')
    assert len(fig.layout.xaxis.tickvals) == 3
    assert all('2026-10-20' in day for day in fig.layout.xaxis.tickvals)
    assert len(fig.layout.annotations) == 3


def test_prior_context_query_uses_caller_token_member_metrics_and_bounded_window(monkeypatch):
    calls = []
    class Response:
        ok, content = True, b'[]'
        def __init__(self, data):
            self.data = data
        def json(self):
            return self.data
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response(True if url.endswith('/rpc/diary_staff_status') else [])
    monkeypatch.setattr('requests.request', request)
    monkeypatch.setattr(dashboard_flow.st, 'session_state', {})
    data = dashboard_flow.load_records(dashboard_flow.RESEARCH, {'member_id': 'ycc00000001'},
                                       date(2026, 10, 20), date(2026, 10, 20), Store('SYNTHETIC'))
    context_call = next(c for c in calls if (c[2].get('params') or {}).get('metric') == 'in.(stress,fatigue)')
    assert context_call[0] == 'GET'
    assert context_call[2]['headers']['Authorization'] == 'Bearer SYNTHETIC'
    params = context_call[2]['params']
    assert params['member_id'] == 'eq.ycc00000001'
    assert params['measured_at'] == 'gte.2026-10-18T00:00:00+08:00'
    assert params['and'] == '(measured_at.lt.2026-10-20T00:00:00+08:00)'
    assert data['pre_sleep_context_status'] == 'success'


@pytest.mark.parametrize('status', [503, 403])
def test_context_failure_is_visible_and_auth_errors_are_not_swallowed(monkeypatch, status):
    monkeypatch.setattr(dashboard_flow, 'require_research_access', lambda s: None)
    monkeypatch.setattr(dashboard_flow.st, 'session_state', {})
    def rows(self, table, **filters):
        if filters.get('metric'):
            raise StoreError(status)
        return []
    monkeypatch.setattr(Store, 'rows', rows)
    args = (dashboard_flow.RESEARCH, {'member_id': 'ycc00000001'}, date(2026, 10, 20), date(2026, 10, 20), Store('SYNTHETIC'))
    if status == 403:
        with pytest.raises(StoreError):
            dashboard_flow.load_records(*args)
    else:
        assert dashboard_flow.load_records(*args)['pre_sleep_context_status'] == 'partial'


def test_platform_context_does_not_expand_normal_metrics_or_raw_exports(monkeypatch):
    calls = []
    lower = int(datetime(2026, 10, 20, tzinfo=TZ).timestamp())
    def fetch(self, kind, member, start, end):
        calls.append((kind, start, end))
        if kind == 'hrv':
            return [dict(id=1, occur_time=lower-3600, mental_stress=-2, fatigue=0),
                    dict(id=2, occur_time=lower+3600, mental_stress=2, fatigue=10),
                    dict(id=3, occur_time='bad')]
        return []
    monkeypatch.setattr(Platform, 'fetch_range', fetch)
    data = load_platform_bundle('SYNTHETIC', {'id': 1}, date(2026, 10, 20), date(2026, 10, 20))
    assert len(calls) == len(KINDS)
    assert next(start for kind, start, _ in calls if kind == 'hrv') == lower - 2*86400
    assert {row['value'] for row in data['pre_sleep_context']} == {-2, 0}
    assert {row['value'] for row in data['metrics']} == {2, 10}
    assert [row['id'] for row in data['raw']['hrv']] == [2, 3]
    assert data['statuses']['hrv']['count'] == 2 and data['parse_issues']


def test_parameter_ui_zero_cards_period_table_and_explicit_duplicate_selection():
    script = '''
from nsysu.sleep_parameters_view import sleep_parameters_view
sleep_parameters_view(SESSIONS, DIARIES, METRICS)
'''
    log, session = night()
    app = AppTest.from_string(script.replace('SESSIONS', repr([session])).replace('DIARIES', repr([log])).replace('METRICS', repr(readings())), default_timeout=30).run()
    assert not app.exception
    assert next(m for m in app.metric if m.label == '整體入睡時間（TST）').value == '480 分鐘'
    assert next(m for m in app.metric if m.label == '入睡前平均壓力指數').value == '0'
    assert len(app.metric) == 9
    app.radio[0].set_value('期間對照').run()
    assert not app.exception
    assert any('睡眠效率（SE）（%）' in frame.value for frame in app.dataframe)
    script = script.replace('SESSIONS', repr([session, dict(session, external_session_id='SECOND')])).replace('DIARIES', repr([log])).replace('METRICS', '[]')
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    assert next(m for m in app.metric if m.label == '整體入睡時間（TST）').value == '—'
