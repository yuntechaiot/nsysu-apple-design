"""Presentation must not turn unrelated health measurements into one summary."""
from datetime import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from nsysu.dashboard_summary import blood_pressure_pair, latest_series, measurement_table, trend_figure
from nsysu.sleep import TZ
from nsysu.store import Store


def metric(name='HR', value=60, when='2026-10-18T07:00:00+08:00', **extra):
    return dict(metric=name, value=value, measured_at=when, source='SYNTHETIC', unit='bpm',
                signal_type='PPG', algorithm_version='test', **extra)


def test_latest_and_change_use_absolute_time_and_one_measurement_series():
    original = metric(value=50)
    current = metric(value=0, when='2026-10-18T00:00:00+00:00')
    different_unit = dict(original, unit=None, value=900)
    different_device = dict(original, device_external_id='other', value=900)
    different_version = dict(original, algorithm_version='other', value=900)
    assert latest_series([current, different_unit, different_device, different_version, original], 'HR') == [original, current]
    assert latest_series([dict(original, value=None), dict(original, value=float('nan'))], 'HR') == []


def test_blood_pressure_requires_same_measurement_and_no_ambiguous_duplicates():
    systolic = dict(metric('SBP', 120), unit='mmHg', external_record_id='first')
    diastolic = dict(systolic, metric='DBP', value=80)
    assert blood_pressure_pair([systolic, diastolic]) == {'SBP': systolic, 'DBP': diastolic}
    for wrong in [dict(diastolic, measured_at='2026-10-18T08:00:00+08:00'),
                  dict(diastolic, source='other'), dict(diastolic, unit=None),
                  dict(diastolic, external_record_id='second')]:
        assert blood_pressure_pair([systolic, wrong]) is None
    assert blood_pressure_pair([systolic, dict(systolic, value=130), diastolic]) is None


def test_readable_table_keeps_zero_unknown_units_and_taipei_time():
    rows = [dict(metric('fatigue', 0, '2026-10-17T23:00:00Z'), unit=None)]
    table = measurement_table(rows)
    assert table.iloc[0]['測量時間'] == '2026/10/18 07:00:00'
    assert table.iloc[0]['量測項目'] == '疲倦指數'
    assert table.iloc[0]['數值'] == 0 and table.iloc[0]['單位'] == '單位未確認'
    assert 'occur_time' not in table and 'id' not in table


def test_trend_keeps_separate_device_and_version_lines():
    rows = [metric(), metric(value=70, device_external_id='second'), dict(metric(), algorithm_version='other')]
    fig = trend_figure(rows, ['HR'])
    assert len(fig.data) == 3 and len({trace.name for trace in fig.data}) == 3
    assert all(not trace.connectgaps for trace in fig.data)


def test_overview_card_opens_matching_category_and_switches_to_readable_table(monkeypatch):
    monkeypatch.setattr(Store, 'request', lambda *a, **k: True)
    sample = [metric(), dict(metric('SBP', 120), unit='mmHg'), dict(metric('DBP', 80), unit='mmHg')]

    def rows(self, table, **filters):
        return [{'member_id': 'ycc00000001'}] if table == 'research_participants' else sample if table == 'physiological_metrics' else []

    monkeypatch.setattr(Store, 'rows', rows)
    dashboard = Path(__file__).resolve().parents[2] / 'frontend/source/數據監控室.py'
    app = AppTest.from_file(str(dashboard), default_timeout=30)
    app.session_state['supabase_session'] = {'access_token': 'SYNTHETIC', 'expires_at': datetime(2030, 1, 1, tzinfo=TZ).timestamp()}
    app.run()
    next(b for b in app.button if b.label == '查看資料').click().run()
    assert not app.exception and app.session_state['dashboard_tabs'] == '健康總覽'
    assert any(m.label == '血壓（收縮壓／舒張壓）' and m.value == '120 / 80 mmHg' for m in app.metric)
    next(b for b in app.button if b.label == '查看血壓').click().run()
    assert not app.exception and app.session_state['dashboard_tabs'] == '生理數據'
    assert next(s for s in app.selectbox if s.label == '生理資料類別').value == '血壓'
    next(r for r in app.radio if r.label == '顯示方式').set_value('量測表').run()
    assert not app.exception
    assert any('測量時間' in table.value.columns and len(table.value) == 2 for table in app.dataframe)
    next(b for b in app.button if b.label == '查看血氧').click().run()
    assert not app.exception and any('無可顯示的血氧量測' in item.value for item in app.info)
