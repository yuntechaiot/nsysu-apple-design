"""Isolated chart QA with labeled synthetic measurements; no account or database."""
from pathlib import Path
import os
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results/charts'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    demo = OUT / 'preview.py'
    demo.write_text('''import sys
import streamlit as st
sys.path.insert(0, ''' + repr(str(ROOT / 'backend')) + ''')
from nsysu.apple_theme import apply
from nsysu.chart_style import chart_tools, render_trend
from nsysu.dashboard_summary import trend_figure
st.set_page_config(page_title='折線圖驗證',layout='wide')
apply()
st.title('看清楚，每一次變化')
st.caption('圖表呈現驗證 · 以下全部為合成資料')
rows=[dict(metric='HR',value=value,measured_at=f'2026-10-{day:02d}T07:00:00+08:00',
source='SYNTHETIC',unit='bpm',signal_type='PPG',device_external_id='TEST',algorithm_version='test')
for day,value in enumerate([66,64,69,67,None,63,65,70,68,64,66,62],1)]
with st.container(border=True):
 st.subheader('心率趨勢')
 st.caption('點按查看數值；中斷處表示沒有量測。')
 tools=chart_tools('preview')
 render_trend(trend_figure(rows,['HR']),'preview-hr',tools)
bp=[dict(r,metric=m,unit='mmHg',value=(120 if m=='SBP' else 80)+i%4) for i,r in enumerate(rows) for m in ['SBP','DBP']]
with st.container(border=True):
 st.subheader('血壓比較')
 render_trend(trend_figure(bp,['SBP','DBP']),'preview-bp')
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
                page = browser.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base)
                charts = page.locator('[data-testid=stPlotlyChart]')
                expect(charts).to_have_count(2, timeout=30000)
                expect(charts.first.locator('.main-svg').first).to_be_visible()
                for width in (320, 390, 768, 1365):
                    page.set_viewport_size({'width': width, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(OUT / 'mobile.png'))
                point = charts.first.locator('.point').first
                point.scroll_into_view_if_needed()
                box = point.bounding_box()
                page.touchscreen.tap(box['x'] + box['width']/2, box['y'] + box['height']/2)
                expect(charts.first.locator('.hoverlayer')).to_contain_text('心率')
                expect(charts.first.locator('.hoverlayer')).to_contain_text('66 bpm')
                page.screenshot(path=str(OUT / 'mobile-tooltip.png'))
                # A null at day five must create two line segments.
                assert charts.first.locator('.scatterlayer .js-line').count() == 2
                legend = charts.nth(1).locator('.infolayer > .legend .traces').first
                legend.click()
                expect(charts.nth(1).locator('.scatterlayer > .trace')).to_have_count(1)
                page.get_by_text('縮放工具', exact=True).click()
                expect(charts.first.locator('.rangeslider-container')).to_be_visible()
                expect(charts.first.locator('.modebar')).to_be_visible()
                assert not errors, errors
                browser.close()
        finally:
            child.terminate()
            child.wait(timeout=10)
    print('PASS: mobile/desktop chart layout, touch tooltip, missing-data break, legend toggle and optional zoom tools')


if __name__ == '__main__':
    main()
