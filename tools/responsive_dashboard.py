"""Local-only responsive fixture. No account, database or platform connection."""
from datetime import datetime, timedelta
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from nsysu import dashboard_flow as flow, cloud
from nsysu.sleep import TZ

today = datetime.now(TZ).date()
previous = today - timedelta(days=1)
logs = [dict(id='DIARY-TEST', member_id='ycc00000001', date=str(today), date_definition='wake_date',
             bedtime='22:30', final_wake_time='07:00', out_of_bed_time='07:15', morning_wake_time='07:00', wake_time='07:15',
             bedtime_at=f'{previous}T22:30:00+08:00', final_wake_at=f'{today}T07:00:00+08:00',
             out_of_bed_at=f'{today}T07:15:00+08:00', lights_out_at=f'{previous}T22:45:00+08:00',
             wakeup_count=2, sleep_onset_min=15)]
watches = [dict(external_session_id='WATCH-TEST', member_id='ycc00000001', source='SYNTHETIC',
                sleep_date=str(today), start_at=f'{previous}T22:45:00+08:00', end_at=f'{today}T07:00:00+08:00',
                sleep_onset_at=f'{previous}T23:00:00+08:00', final_wake_at=f'{today}T07:00:00+08:00',
                awake_minutes=30, tst_minutes=450, waso_minutes=20, light_minutes=300, deep_minutes=100,
                rem_minutes=50, algorithm_version='test', quality_status='valid', stages=[])]
metrics = [dict(metric=metric, value=value, source='SYNTHETIC', unit=None, signal_type='PPG',
                algorithm_version='test', device_external_id='WATCH-TEST', measured_at=f'{previous}T{clock}:00+08:00')
           for metric, clock, value in [('stress', '22:00', -2), ('stress', '22:30', 2), ('fatigue', '22:10', 0), ('fatigue', '22:50', 10)]]
metrics += [dict(metric=name, value=value + day % 3, source='SYNTHETIC', unit=unit, signal_type='PPG',
                 algorithm_version='test', measured_at=f'{today-timedelta(days=day)}T07:00:00+08:00',
                 external_record_id=f'TEST-{day}') for day in range(14)
            for name, value, unit in [('HR', 65, 'bpm'), ('SBP', 120, 'mmHg'), ('DBP', 80, 'mmHg'), ('SpO2', 98, '%')]]


class FakeStore:
    def rows(self, table, **filters):
        if table == 'physiological_metrics' and filters.get('metric'):
            return []
        return {'research_participants': [dict(member_id='ycc00000001', display_name='合成資料展示')],
                'sleep_logs': logs, 'sleep_sessions': watches, 'physiological_metrics': metrics, 'data_imports': []}[table]

    def request(self, *args, **kwargs):
        return True


if st.query_params.get('diary'):
    cloud.public_config = lambda base: dict(supabase_url='https://synthetic.supabase.co', publishable_key='sb_publishable_SYNTHETIC',
                                           diary_url=base, dashboard_url=base + '?view=dashboard', timezone='Asia/Taipei')
    cloud.main()
else:
    flow.research_store = lambda: FakeStore()
    st.session_state.supabase_session = {'access_token': 'SYNTHETIC', 'expires_at': 2000000000}
    st.session_state.platform_token = 'SYNTHETIC'
    st.session_state.flow_platform_members = []
    flow.main()
