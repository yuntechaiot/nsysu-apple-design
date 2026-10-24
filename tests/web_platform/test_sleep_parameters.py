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
    assert result['values'] == dict(tib_minutes=525, tst_minutes=480, sol_minutes=15, awakening_count=2,
                                    waso_minutes=30, se_percent=pytest.approx(480 / 525 * 100), rise_minutes=15,
                                    pre_attempt_bed_minutes=15)
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
    assert result['values']['sol_minutes'] == 15 and '非完整' in result['onset_basis']
    session['sleep_onset_at'] = 'invalid'
    assert calculate_parameters(log, session, allow_observed=True)['values']['sol_minutes'] is None


def test_true_zeros_missing_values_and_impossible_awake_summary():
    log, session = night()
    log.update(wakeup_count=0, bedtime_at=session['sleep_onset_at'], lights_out_at=session['sleep_onset_at'],
               out_of_bed_at=log['final_wake_at'])
    result = calculate_parameters(log, dict(session, awake_minutes=0))
    assert result['values']['awakening_count'] == result['values']['waso_minutes'] == result['values']['sol_minutes'] == 0
    assert result['values']['se_percent'] == 100
    assert calculate_parameters()['values'] == dict.fromkeys(result['values'])
    assert calculate_parameters(log)['reasons']['sol_minutes'].startswith('缺少對應日期的手錶睡眠紀錄')
    assert calculate_parameters(None, session)['reasons']['tst_minutes'] == '缺少對應日期的睡眠日誌'
    assert calculate_parameters(log, dict(session, awake_minutes=9999))['values']['waso_minutes'] is None
    assert calculate_parameters(dict(log, wakeup_count=1.5), session)['values']['awakening_count'] is None


def test_mismatched_members_dates_and_onsets_do_not_produce_hybrid_values():
    log, session = night()
    for changes in [dict(member_id='OTHER'), dict(sleep_date='2026-10-21'),
                    dict(sleep_onset_at='2026-10-20T08:00:00+08:00', end_at=None)]:
        result = calculate_parameters(log, dict(session, **changes))
        assert result['values']['tst_minutes'] is None and result['values']['sol_minutes'] is None
        assert result['values']['tib_minutes'] == 525


def diary_fallback_night():
    log, session = night()
    log.update(date='2026-10-23', bedtime_at='2026-10-23T00:30:00+08:00',
               lights_out_at='2026-10-23T00:40:00+08:00', final_wake_at='2026-10-23T08:00:00+08:00',
               out_of_bed_at='2026-10-23T11:00:00+08:00', sleep_onset_min=20, subjective_waso_minutes=10)
    session.update(sleep_date=log['date'], start_at='2026-10-22T22:30:00+08:00',
                   sleep_onset_at='2026-10-22T22:42:00+08:00', end_at='2026-10-23T08:00:00+08:00',
                   awake_minutes=86)
    return log, session


def test_diary_fallback_for_conflicting_watch_preserves_word_equations_and_originals():
    log, session = diary_fallback_night()
    before = deepcopy((log, session))
    result = calculate_parameters(log, session)
    assert result['values'] == dict(tib_minutes=630, tst_minutes=420, sol_minutes=0, awakening_count=2,
                                    waso_minutes=86, se_percent=pytest.approx(420 / 630 * 100), rise_minutes=180,
                                    pre_attempt_bed_minutes=10)
    assert result['times']['onset'] == instant('2026-10-23T01:00:00+08:00')
    assert result['times']['watch_onset'] == instant(session['sleep_onset_at'])
    assert result['sources']['tst_minutes'] == '睡眠日誌備案'
    assert result['sources']['sol_minutes'] == '修訂公式（日誌＋手錶）'
    assert result['times']['sol_onset'] == result['times']['watch_onset']
    assert result['sources']['waso_minutes'] == 'Word 公式：手錶清醒時間'
    assert '日誌估算' in result['onset_basis']
    assert (log, session) == before
    period = period_parameters([log], [session], [])
    assert len(period) == 1 and period[0]['values'] == result['values']
    exported = record_table(period).iloc[0]
    assert exported['整體入睡時間（TST）計算來源'] == '睡眠日誌備案'
    assert exported['手錶原始入睡起點'] == '2026/10/22 22:42'
    assert exported['嘗試入睡前躺床時間（分鐘）'] == 10
    assert exported['SOL 採用入睡時間'] == '2026/10/22 22:42'
    assert exported['日誌開始嘗試入睡時間'] == '2026/10/23 00:40'


def test_word_formula_has_priority_even_when_diary_latency_differs():
    log, session = night()
    result = calculate_parameters(dict(log, sleep_onset_min=120, subjective_waso_minutes=80), session)
    assert result['values']['tst_minutes'] == 480 and result['values']['sol_minutes'] == 15
    assert result['values']['waso_minutes'] == 30
    assert result['sources']['tst_minutes'] == 'Word 公式（日誌＋手錶）'


@pytest.mark.parametrize('watch_clock,expected', [('22:20', 0), ('22:40', 0), ('22:45', 0), ('23:00', 15)])
def test_revised_sol_uses_attempt_and_clamps_negative_even_before_bed(watch_clock, expected):
    log, session = night()
    result = calculate_parameters(log, dict(session, start_at='2026-10-19T22:00:00+08:00',
                                           sleep_onset_at=f'2026-10-19T{watch_clock}:00+08:00'))
    assert result['values']['sol_minutes'] == expected
    assert result['values']['pre_attempt_bed_minutes'] == 15
    assert result['sources']['sol_minutes'] == '修訂公式（日誌＋手錶）'


def test_attempt_and_sol_across_midnight_use_dates_not_clock_subtraction():
    log, session = night()
    log.update(lights_out_at='2026-10-20T00:15:00+08:00')
    result = calculate_parameters(log, dict(session, sleep_onset_at='2026-10-20T00:05:00+08:00'))
    assert result['values']['sol_minutes'] == 0
    assert result['values']['pre_attempt_bed_minutes'] == 105
    log.pop('lights_out_at')
    log['lights_out_time'] = '00:15'
    assert calculate_parameters(log, session)['values']['pre_attempt_bed_minutes'] == 105
    log['lights_out_time'] = '22:45'
    assert calculate_parameters(log, session)['values']['pre_attempt_bed_minutes'] == 15


@pytest.mark.parametrize('attempt', [None, 'invalid', '2026-10-19T22:45:00',
                                   '2026-10-19T22:00:00+08:00', '2026-10-20T08:00:00+08:00'])
def test_invalid_or_missing_attempt_is_not_replaced_with_bed_or_zero(attempt):
    log, session = night()
    result = calculate_parameters(dict(log, lights_out_at=attempt), session)
    assert result['values']['sol_minutes'] is None
    assert result['values']['pre_attempt_bed_minutes'] is None
    assert result['reasons']['sol_minutes']
    assert result['reasons']['pre_attempt_bed_minutes']
    assert result['values']['tst_minutes'] == 480
    assert result['values']['tib_minutes'] == 525


def test_missing_watch_uses_diary_sol_without_including_pre_attempt_bed_time():
    log, _ = diary_fallback_night()
    result = calculate_parameters(log)
    assert result['values']['sol_minutes'] == 20
    assert result['values']['pre_attempt_bed_minutes'] == 10
    assert result['sources']['sol_minutes'] == '睡眠日誌備案'
    assert '開始嘗試' in result['sol_onset_basis']


def test_watch_after_final_wake_uses_diary_sol_instead_of_positive_invalid_difference():
    log, session = diary_fallback_night()
    result = calculate_parameters(log, dict(session, sleep_onset_at='2026-10-23T09:00:00+08:00', end_at=None))
    assert result['values']['sol_minutes'] == 20
    assert result['sources']['sol_minutes'] == '睡眠日誌備案'


def test_new_parameter_in_period_chart_and_csv_has_same_value_and_formula():
    log, session = night()
    rows = period_parameters([log], [session], [])
    fig = parameter_figure(rows, 'pre_attempt_bed_minutes', '嘗試入睡前躺床時間', '分鐘')
    assert list(fig.data[0].y) == [15]
    exported = csv_bytes(record_table(rows)).decode('utf-8-sig')
    assert '嘗試入睡前躺床時間（分鐘）' in exported
    assert '嘗試入睡前躺床時間計算來源' in exported
    assert '修訂公式（日誌＋手錶）' in exported


def test_period_prefers_existing_compatible_watch_over_conflicting_watch():
    log, session = night()
    log['sleep_onset_min'] = 120
    conflict = dict(session, external_session_id='CONFLICT', sleep_onset_at='2026-10-19T22:00:00+08:00',
                    start_at='2026-10-19T21:00:00+08:00')
    rows = period_parameters([log], [session, conflict], [])
    diary = next(row for row in rows if row['diary_id'] == log['id'])
    assert diary['session_id'] == session['external_session_id']
    assert diary['values']['tst_minutes'] == 480
    assert diary['sources']['tst_minutes'] == 'Word 公式（日誌＋手錶）'


def test_watch_only_pre_sleep_metrics_remain_available_without_a_diary():
    _, session = night()
    result = calculate_parameters(None, session, readings())
    assert len(result['pre_sleep']) == 2
    assert result['values']['tst_minutes'] is None


def test_diary_only_fallback_uses_bed_only_when_attempt_missing_and_accepts_real_zeros():
    log, _ = diary_fallback_night()
    log.pop('lights_out_at')
    result = calculate_parameters(dict(log, sleep_onset_min=0, subjective_waso_minutes=0))
    assert result['values']['waso_minutes'] == 0
    assert result['values']['sol_minutes'] is None
    assert result['values']['pre_attempt_bed_minutes'] is None
    assert result['values']['tst_minutes'] == 450
    assert '未填' in result['onset_basis']
    log['lights_out_time'] = '00:40'
    assert calculate_parameters(log)['values']['sol_minutes'] == 20
    overnight, _ = night()
    overnight.update(lights_out_time='22:45', sleep_onset_min=15)
    overnight.pop('lights_out_at')
    assert calculate_parameters(overnight)['values']['tst_minutes'] == 480


@pytest.mark.parametrize('changes', [dict(sleep_onset_min=None), dict(sleep_onset_min=-1),
                                    dict(sleep_onset_min=True), dict(sleep_onset_min=301),
                                    dict(lights_out_at='2026-10-23T07:50:00+08:00'),
                                    dict(lights_out_at='2026-10-23T00:00:00+08:00'),
                                    dict(lights_out_at='invalid'), dict(date_definition='legacy')])
def test_invalid_diary_fallback_does_not_force_tst_but_watch_sol_is_independent(changes):
    log, session = diary_fallback_night()
    result = calculate_parameters(dict(log, **changes), session)
    assert result['values']['tst_minutes'] is None
    expected_sol = 0 if 'sleep_onset_min' in changes or changes.get('lights_out_at') == '2026-10-23T07:50:00+08:00' else None
    assert result['values']['sol_minutes'] == expected_sol
    assert result['values']['se_percent'] is None


@pytest.mark.parametrize('changes', [dict(member_id='OTHER'), dict(sleep_date='2026-10-24')])
def test_unrelated_watch_is_not_used_for_fallback_waso_or_mean_member(changes):
    log, session = diary_fallback_night()
    metric = dict(metric='stress', value=8, member_id=log['member_id'],
                  measured_at='2026-10-23T00:30:00+08:00')
    result = calculate_parameters(log, dict(session, **changes), [metric])
    assert result['values']['tst_minutes'] == 420 and result['values']['waso_minutes'] == 10
    assert result['values']['sol_minutes'] == 20
    assert result['sources']['sol_minutes'] == '睡眠日誌備案'
    assert '日誌備案' in result['sources']['waso_minutes']
    assert result['pre_sleep'][0]['mean'] == 8
    assert result['window_start'] == '2026-10-23T00:00:00+08:00'


@pytest.mark.parametrize('value', [None, -1, 421, True])
def test_invalid_or_missing_subjective_waso_is_not_assumed_zero(value):
    log, _ = diary_fallback_night()
    result = calculate_parameters(dict(log, subjective_waso_minutes=value))
    assert result['values']['waso_minutes'] is None
    assert result['values']['tst_minutes'] == 420


def test_fallback_ui_shows_actual_formula_and_both_onset_sources():
    log, session = diary_fallback_night()
    script = ('from nsysu.sleep_parameters_view import sleep_parameters_view\n'
              f'sleep_parameters_view({[session]!r}, {[log]!r}, [])')
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    assert next(m for m in app.metric if m.label == '整體入睡時間（TST）').value == '420 分鐘'
    assert next(m for m in app.metric if m.label == '睡眠潛伏期（SOL）').value == '0 分鐘'
    assert next(m for m in app.metric if m.label == '嘗試入睡前躺床時間').value == '10 分鐘'
    assert any('睡眠日誌備案 · 日誌最後醒來時間－日誌估算入睡時間' in c.value for c in app.caption)
    assert any('本次採用入睡時間' in frame.value['時刻'].values for frame in app.dataframe if '時刻' in frame.value)


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
    assert len(app.metric) == 10
    assert next(m for m in app.metric if m.label == '睡眠潛伏期（SOL）').value == '15 分鐘'
    assert next(m for m in app.metric if m.label == '嘗試入睡前躺床時間').value == '15 分鐘'
    app.radio[0].set_value('期間對照').run()
    assert not app.exception
    assert any('睡眠效率（SE）（%）' in frame.value for frame in app.dataframe)
    assert any('嘗試入睡前躺床時間（分鐘）' in frame.value for frame in app.dataframe)
    script = script.replace('SESSIONS', repr([session, dict(session, external_session_id='SECOND')])).replace('DIARIES', repr([log])).replace('METRICS', '[]')
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    assert next(m for m in app.metric if m.label == '整體入睡時間（TST）').value == '—'
