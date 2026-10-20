"""Visual QA for recommended views, using labeled synthetic data only."""
from pathlib import Path
import os
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results/observations'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    demo = OUT / 'preview.py'
    demo.write_text('''import sys
import streamlit as st
sys.path.insert(0, ''' + repr(str(ROOT / 'backend')) + ''')
from nsysu.apple_theme import apply
from nsysu.chart_style import render_trend
from nsysu.observation_views import presentation_control, render_observations, sleep_duration_bars
st.set_page_config(page_title='觀察方式比較',layout='wide')
apply()
st.title('依資料選圖，更容易看懂')
st.caption('呈現方式比較 · 以下全部為合成資料，未連接研究資料庫')
rows=[dict(metric='HR',value=64+(day%4)+offset,measured_at=f'2026-10-{day:02d}T{hour:02d}:00:00+08:00',
source='SYNTHETIC',unit='bpm',signal_type='PPG',device_external_id='TEST',algorithm_version='test')
for day in [1,2,3,5,6,7,8] for hour,offset in [(7,-3),(10,2),(13,5),(18,-1)]]
bp=[dict(rows[i*4],metric=m,value=value+i%3,unit='mmHg',external_record_id=f'TEST-{i}')
for i in range(7) for m,value in [('SBP',120),('DBP',78)]]
sleep=[dict(sleep_date=f'2026-10-{day:02d}',tst_minutes=value,source='SYNTHETIC',external_session_id=f'TEST-{day}')
for day,value in [(1,420),(2,390),(3,450),(4,None),(5,380),(6,430),(7,400)]]
choice=presentation_control('demo')
cols=st.columns(3)
with cols[0],st.container(border=True):
 st.subheader('每天多次量測')
 render_observations(rows,['HR'],'demo-range',choice)
with cols[1],st.container(border=True):
 st.subheader('同次血壓對照')
 render_observations(bp,['SBP','DBP'],'demo-bp')
with cols[2],st.container(border=True):
 st.subheader('每晚睡眠比較')
 st.caption('每柱一筆睡眠紀錄，不合併同日多筆；未提供的時長另行註明。')
 render_trend(sleep_duration_bars(sleep),'demo-sleep')
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
                page = browser.new_page(viewport={'width': 1365, 'height': 900}, is_mobile=True, has_touch=True)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base)
                charts = page.locator('[data-testid=stPlotlyChart]')
                expect(charts).to_have_count(3, timeout=30000)
                expect(charts.first.locator('.errorbar').first).to_be_visible()
                page.screenshot(path=str(OUT / 'comparison.png'), full_page=True)
                for width in (320, 390, 768, 1365):
                    page.set_viewport_size({'width': width, 'height': 900})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(OUT / 'mobile.png'))
                point = charts.first.locator('.point').first
                point.scroll_into_view_if_needed()
                box = point.bounding_box()
                page.touchscreen.tap(box['x'] + box['width']/2, box['y'] + box['height']/2)
                expect(charts.first.locator('.hoverlayer')).to_contain_text('每日中位數')
                expect(charts.first.locator('.hoverlayer')).to_contain_text('量測 4 筆')
                page.screenshot(path=str(OUT / 'mobile-range-tooltip.png'))
                select = page.get_by_role('combobox').first
                select.click()
                page.get_by_role('option', name='原始點位', exact=True).click()
                expect(charts.first.locator('.errorbar')).to_have_count(0)
                expect(charts.first.locator('.point')).to_have_count(28)
                select.click()
                page.get_by_role('option', name='折線圖', exact=True).click()
                expect(charts.first.locator('.js-line')).to_have_count(1)
                assert charts.nth(1).locator('.js-line').count() == 7, 'Only seven same-measurement BP connectors'
                expect(page.get_by_text('未提供', exact=True)).to_be_visible()
                assert not errors, errors
                browser.close()
        finally:
            child.terminate()
            child.wait(timeout=10)
    print('PASS: recommended range, paired BP, sleep bars, mobile tooltip, raw-point/line switching and missing-duration labels')


if __name__ == '__main__':
    main()
