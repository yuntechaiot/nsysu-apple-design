"""Dashboard sleep-parameter visual QA; all inputs are synthetic, no network data."""
from pathlib import Path
import os
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results/sleep-parameters'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    demo = OUT / 'preview.py'
    demo.write_text('''import sys
import streamlit as st
from datetime import datetime, timedelta
sys.path.insert(0, ''' + repr(str(ROOT / 'backend')) + ''')
from nsysu import dashboard_flow as flow
from nsysu.sleep import TZ
today = datetime.now(TZ).date()
previous = today-timedelta(days=1)
logs = [dict(id='DIARY-TEST',member_id='ycc00000001',date=str(today),date_definition='wake_date',
 bedtime='22:30',final_wake_time='07:00',out_of_bed_time='07:15',morning_wake_time='07:00',wake_time='07:15',
 bedtime_at=f'{previous}T22:30:00+08:00',final_wake_at=f'{today}T07:00:00+08:00',
 out_of_bed_at=f'{today}T07:15:00+08:00',lights_out_at=f'{previous}T22:45:00+08:00',
 wakeup_count=2,sleep_onset_min=15)]
watches = [dict(external_session_id='WATCH-TEST',member_id='ycc00000001',source='SYNTHETIC',
 sleep_date=str(today),start_at=f'{previous}T22:45:00+08:00',end_at=f'{today}T07:00:00+08:00',
 sleep_onset_at=f'{previous}T23:00:00+08:00',final_wake_at=f'{today}T07:00:00+08:00',
 awake_minutes=30,tst_minutes=450,waso_minutes=20,light_minutes=300,deep_minutes=100,rem_minutes=50,
 algorithm_version='test',quality_status='valid',stages=[])]
metrics=[dict(metric=metric,value=value,source='SYNTHETIC',unit=None,signal_type='PPG',
 algorithm_version='test',device_external_id='WATCH-TEST',measured_at=f'{previous}T{clock}:00+08:00')
 for metric,clock,value in [('stress','22:00',-2),('stress','22:30',2),('fatigue','22:10',0),('fatigue','22:50',10)]]
class FakeStore:
 def rows(self,table,**filters):
  return {'research_participants':[dict(member_id='ycc00000001',display_name='合成資料展示')],
          'sleep_logs':logs,'sleep_sessions':watches,'physiological_metrics':metrics,'data_imports':[]}[table]
 def request(self,*a,**k):
  return True
flow.research_store = lambda: FakeStore()
st.session_state.supabase_session={'access_token':'SYNTHETIC','expires_at':2000000000}
st.session_state.platform_token='SYNTHETIC'
st.session_state.flow_platform_members=[]
st.caption('介面測試：以下全部為合成資料，未連接研究資料庫')
flow.main()
''', encoding='utf-8')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    with (OUT / 'server.log').open('w', encoding='utf-8') as log:
        child = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(demo), '--server.address', '127.0.0.1',
                                  '--server.port', str(port), '--server.headless', 'true', '--browser.gatherUsageStats', 'false'],
                                 cwd=ROOT, stdout=log, stderr=log,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    if urlopen(base + '/_stcore/health', timeout=.5).status == 200:
                        break
                except OSError:
                    time.sleep(.2)
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='msedge')
                page = browser.new_page(viewport={'width': 1365, 'height': 1000}, is_mobile=True, has_touch=True)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base)
                page.get_by_role('button', name='查看資料', exact=True).click()
                expect(page.get_by_role('tab')).to_have_count(8, timeout=30000)
                tab = page.get_by_role('tab', name='睡眠參數', exact=True)
                tab.click()
                panel = page.get_by_role('tabpanel', name='睡眠參數', exact=True)
                expect(panel.get_by_text('480 分鐘', exact=True)).to_be_visible()
                expect(panel.get_by_text('525 分鐘', exact=True)).to_be_visible()
                expect(panel.locator('[data-testid=stMetric]')).to_have_count(9)
                assert panel.locator('[data-testid=stMetricValue]').all_text_contents() == [
                    '525 分鐘', '480 分鐘', '30 分鐘', '2 次', '30 分鐘', '91.43 %', '15 分鐘', '0', '5']
                panel.scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / 'desktop.png'), full_page=True)
                for width in (320, 390, 768, 1365):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.set_viewport_size({'width': 390, 'height': 844})
                cards = panel.locator('[data-testid=stMetric]')
                first, second = cards.nth(0).bounding_box(), cards.nth(1).bounding_box()
                assert second['y'] > first['y'] + first['height'], 'Cards stack on mobile'
                cards.first.scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / 'mobile-cards.png'))
                panel.get_by_text('期間對照', exact=True).click()
                chart = panel.locator('[data-testid=stPlotlyChart]')
                expect(chart).to_have_count(1)
                expect(chart.locator('.point')).to_have_count(1)
                expect(chart.locator('.xaxislayer-above .xtick text')).to_have_count(1)
                assert chart.locator('.xaxislayer-above .xtick text').text_content()
                expect(panel.get_by_role('button', name='下載睡眠參數 CSV', exact=True)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                chart.scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / 'mobile-period.png'))
                page.set_viewport_size({'width': 1365, 'height': 1000})
                chart.scroll_into_view_if_needed()
                page.screenshot(path=str(OUT / 'desktop-period.png'))
                expect(page.locator('[data-testid=stException]')).to_have_count(0)
                assert not errors, errors
                browser.close()
        finally:
            child.terminate()
            child.wait(timeout=10)
    print('PASS: eight dashboard tabs, nine correct parameter cards, mobile stacking, date ticks, period chart and CSV; synthetic data only')


if __name__ == '__main__':
    main()
