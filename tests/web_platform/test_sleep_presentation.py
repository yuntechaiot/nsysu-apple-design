"""Platform summary parity without fabricating research TST/WASO or intervals."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from nsysu.parsers import docter_sleep
from nsysu.sleep import TZ, sleep_display_summary
from nsysu.sleep_view import sleep_records_table, timeline_figure
from nsysu.store import Store


def sample():
    start = int(datetime(2026, 10, 18, 0, tzinfo=TZ).timestamp())
    raw = {'id': 1, 'start_time': start, 'end_time': start + 510 * 60,
           'data': {'light': 335, 'deep': 76, 'REM': 70, 'awake': 29},
           'detail_obj': [{'type': 1, 'start_time': start, 'end_time': None},
                          {'type': 0, 'start_time': start + 481 * 60, 'end_time': None}]}
    return dict(docter_sleep(raw), source='doctercloud')


def test_portal_sleep_total_and_awake_are_visible_without_loosening_research_metrics():
    session = sample()
    summary = sleep_display_summary(session)
    assert summary['total_minutes'] == 481 and summary['awake'] == 29
    assert summary['total_basis'] == 'platform_core_summary'
    assert session['tst_minutes'] is None and session['waso_minutes'] is None
    assert session['sleep_onset_at'] is None and session['final_wake_at'] is None


def test_missing_summary_fields_are_not_implicitly_zero_and_impossible_total_is_not_used():
    session = sample()
    del session['raw_payload']['data']['REM']
    assert sleep_display_summary(session)['total_minutes'] is None
    assert sleep_display_summary(session)['rem'] is None
    session = sample()
    session['raw_payload']['data']['REM'] = 1000
    assert sleep_display_summary(session)['total_minutes'] is None
    session['raw_payload']['data'] = {'light': 0, 'deep': 0, 'REM': 0, 'awake': 0}
    assert sleep_display_summary(session)['total_minutes'] == 0
    assert sleep_display_summary(session)['awake'] == 0


def test_incomplete_source_intervals_only_plot_real_observations():
    session = sample()
    fig, unbounded = timeline_figure(session)
    assert unbounded and all(trace.type == 'scatter' and trace.mode == 'markers' for trace in fig.data)
    assert sum(len(trace.x) for trace in fig.data) == 2
    assert session['stages'][0]['end_at'] is None


def test_sleep_table_keeps_multiple_same_day_records_and_separates_awake_from_sleep_total():
    session = sample()
    other = deepcopy(session)
    other['external_session_id'] = '2'
    table = sleep_records_table([session, other])
    assert len(table) == 2
    assert list(table['睡眠總時數（TST）']) == ['8 小時 1 分鐘'] * 2
    assert list(table['清醒時間']) == ['29 分鐘'] * 2


def test_sleep_analysis_uses_portal_summary_and_readable_table(monkeypatch):
    monkeypatch.setattr(Store, 'request', lambda *a, **k: True)

    def rows(self, table, **filters):
        return [{'member_id': 'ycc00000001'}] if table == 'research_participants' else [sample()] if table == 'sleep_sessions' else []

    monkeypatch.setattr(Store, 'rows', rows)
    path = Path(__file__).resolve().parents[2] / 'frontend/source/數據監控室.py'
    app = AppTest.from_file(str(path), default_timeout=30)
    app.session_state['supabase_session'] = {'access_token': 'SYNTHETIC', 'expires_at': 2000000000}
    app.run()
    next(b for b in app.button if b.label == '查看資料').click().run()
    assert not app.exception
    assert any(m.label == '睡眠總時數（TST）' and m.value == '8 小時 1 分鐘' for m in app.metric)
    assert any(m.label == '清醒時間' and m.value == '29 分鐘' for m in app.metric)
    next(r for r in app.radio if r.label == '睡眠顯示方式').set_value('睡眠紀錄表').run()
    assert not app.exception
    assert any('清醒時間' in d.value.columns and '睡眠總時數（TST）' in d.value.columns for d in app.dataframe)
