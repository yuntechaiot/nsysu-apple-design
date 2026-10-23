"""Seven widths, Chromium + WebKit; synthetic UI, no production requests/writes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results/responsive'
WIDTHS = (320, 375, 390, 430, 768, 1024, 1440)
sys.path.insert(0, str(ROOT / 'backend'))
from nsysu.cloud import diary_document


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        base = f'http://127.0.0.1:{self.server.server_port}/'
        query = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
        content = diary_document(dict(supabase_url='https://synthetic.supabase.co', publishable_key='sb_publishable_SYNTHETIC',
                                      diary_url=base, dashboard_url=base, timezone='Asia/Taipei'), query).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass


def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Page overflow'


def settled(page):
    # Streamlit replaces widget DOM during reruns; await its actual completion signal.
    expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state', 'notRunning', timeout=30000)


def targets(page, selector):
    return page.locator(selector).evaluate_all('''elements => elements.filter(e => e.getClientRects().length && !e.disabled && (!e.closest('details:not([open])') || e.closest('summary'))).map(e => {
      const r=e.getBoundingClientRect(); return {name:e.getAttribute('aria-label')||e.textContent.trim(),width:r.width,height:r.height};
    }).filter(r=>r.width<43.9||r.height<43.9)''')


def desktop_signature(page, dashboard=False):
    return page.locator('[data-testid=stMainBlockContainer]' if dashboard else '.container').first.evaluate('''e=>{
      const r=e.getBoundingClientRect(),s=getComputedStyle(e);return {x:r.x,width:r.width,padding:s.padding,color:s.color,font:s.fontFamily};
    }''')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--engine', choices=['chromium', 'webkit'])
    parser.add_argument('--width', type=int, choices=WIDTHS)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    dashboard = f'http://127.0.0.1:{port}/'
    report = {'widths': list(WIDTHS), 'engines': {}, 'checks': [], 'unexpected_requests': [], 'page_errors': [], 'production_writes': False}
    with (OUT / 'server.log').open('w', encoding='utf-8') as log:
        child = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', 'tools/responsive_dashboard.py', '--server.address', '127.0.0.1',
                                  '--server.port', str(port), '--server.headless', 'true', '--browser.gatherUsageStats', 'false'],
                                 cwd=ROOT, stdout=log, stderr=log,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    if urlopen(dashboard + '_stcore/health', timeout=.5).status == 200:
                        break
                except OSError:
                    time.sleep(.2)
            with sync_playwright() as p:
                for engine in (['chromium'] if args.baseline else [args.engine] if args.engine else ['chromium', 'webkit']):
                    browser = getattr(p, engine).launch()
                    report['engines'][engine] = browser.version
                    for width in ([1440] if args.baseline else [args.width] if args.width else WIDTHS):
                        context = browser.new_context(viewport={'width': width, 'height': 900}, has_touch=width < 768,
                                                      is_mobile=width < 768, reduced_motion='reduce')
                        def intercept(route):
                            url = route.request.url
                            if url.startswith((base, dashboard)):
                                route.continue_()
                            elif url.endswith('/rest/v1/rpc/check_diary_invitation'):
                                route.fulfill(json=True)
                            elif url.startswith('https://synthetic.supabase.co/rest/v1/'):
                                assert route.request.method == 'GET'
                                route.fulfill(json=[])
                            else:
                                report['unexpected_requests'].append(url)
                                route.abort()
                        context.route('**/*', intercept)
                        page = context.new_page()
                        page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
                        page.goto(base)
                        expect(page.locator('#home-page')).to_be_visible()
                        no_overflow(page)
                        if not args.baseline:
                            viewport = page.locator('meta[name=viewport]').get_attribute('content')
                            assert 'viewport-fit=cover' in viewport and 'maximum-scale' not in viewport and 'user-scalable=no' not in viewport
                            assert page.locator('body').evaluate('e=>getComputedStyle(e).userSelect') != 'none'
                        if args.baseline:
                            report['home_desktop'] = desktop_signature(page)
                            page.screenshot(path=str(OUT / 'before-home-1440.png'), full_page=False)
                        else:
                            assert not targets(page, 'button,.header-nav a,.brand,.helper-row a,.task-card a'), targets(page, 'button,.header-nav a,.brand,.helper-row a,.task-card a')
                            columns = page.locator('.task-grid').evaluate("e=>getComputedStyle(e).gridTemplateColumns.split(' ').length")
                            assert columns == (1 if width < 768 else 2), columns
                            if width < 768:
                                toggle = page.get_by_role('button', name='導覽選單', exact=True)
                                toggle.click()
                                expect(page.locator('.header-nav')).to_be_visible()
                                toggle.press('Escape')
                                expect(toggle).to_have_attribute('aria-expanded', 'false')
                            else:
                                expect(page.locator('.header-nav')).to_be_visible()
                            if width == 1440 and engine == 'chromium':
                                report['home_desktop'] = desktop_signature(page)
                            page.screenshot(path=str(OUT / f'{engine}-home-{width}.png'), full_page=False)
                            page.locator('#admin-login-button').click()
                            expect(page.locator('#auth-dialog')).to_be_visible()
                            assert page.locator('#auth-email').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)>=16')
                            assert not targets(page, '#auth-dialog button')
                            page.locator('#auth-dialog').press('Escape')
                            page.goto(base + '?member=ycc00000001&invite=' + 'a'*64)
                            expect(page.locator('#member-page')).to_be_visible()
                            page.locator('#f-name').fill('SYNTHETIC')
                            page.locator('#f-date').fill('2026-10-18')
                            page.locator('#f-headphone').fill('0')
                            page.locator('#next-step').click()
                            expect(page.locator('[data-step="1"]')).to_be_visible()
                            for field, value in [('f-sleep-time','2230'),('f-lights-out','2245'),('f-sleep-onset','15'),
                                                 ('f-morning-wake-time','0700'),('f-wake-time','0715')]:
                                page.locator('#' + field).fill(value)
                            if width < 768:
                                page.set_viewport_size({'width':width,'height':520})
                                page.locator('#f-wake-time').focus()
                                page.locator('#f-wake-time').scroll_into_view_if_needed()
                                field_box = page.locator('#f-wake-time').bounding_box()
                                bar_box = page.locator('.step-actions').bounding_box()
                                assert field_box['y'] >= page.locator('.site-header').bounding_box()['height']
                                assert field_box['y'] + field_box['height'] <= bar_box['y'], 'Focused field covered by actions'
                                page.set_viewport_size({'width':width,'height':900})
                            no_overflow(page)
                            assert not targets(page, '.step-actions button')
                            page.screenshot(path=str(OUT / f'{engine}-diary-{width}.png'), full_page=False)
                            page.locator('#next-step').click()
                            expect(page.locator('[data-step="2"]')).to_be_visible()
                            assert not targets(page, '.step-panel:not([hidden]) button'), targets(page, '.step-panel:not([hidden]) button')
                            no_overflow(page)
                            page.screenshot(path=str(OUT / f'{engine}-ratings-{width}.png'), full_page=False)
                        page.goto(dashboard)
                        page.get_by_role('button', name='查看資料', exact=True).click()
                        expect(page.get_by_role('tab')).to_have_count(8, timeout=30000)
                        settled(page)
                        no_overflow(page)
                        if args.baseline:
                            report['dashboard_desktop'] = desktop_signature(page, True)
                            report['buttons_before'] = targets(page, 'button')
                            page.screenshot(path=str(OUT / 'before-dashboard-1440.png'), full_page=False)
                            (OUT / 'baseline.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                            context.close()
                            continue
                        if width < 768:
                            assert page.evaluate("matchMedia('(pointer:coarse)').matches"), 'Touch emulation lost'
                            assert not targets(page, 'button'), targets(page, 'button')
                        filters = page.get_by_text('進階篩選：來源與裝置', exact=True)
                        filters.click()
                        no_overflow(page)
                        if width == 390:
                            page.screenshot(path=str(OUT / f'{engine}-filters-{width}.png'))
                        if width < 768:
                            assert page.evaluate("matchMedia('(pointer:coarse)').matches"), 'Touch emulation lost'
                            assert not targets(page, 'button'), targets(page, 'button')
                            tags = page.get_by_test_id('stExpander').filter(has_text='進階篩選：來源與裝置').locator('[data-tag]')
                            assert tags.evaluate_all('es=>es.length>0&&es.every(e=>e.getBoundingClientRect().height>=43.9)')
                        filters.click()
                        overview = page.get_by_role('tabpanel', name='健康總覽', exact=True)
                        metrics = overview.locator('[data-testid=stMetric]')
                        expect(metrics).to_have_count(8, timeout=30000)
                        metric_rows = metrics.evaluate_all('es=>es.slice(0,4).map(e=>e.getBoundingClientRect().y)')
                        if width < 768:
                            assert all(a<b for a,b in zip(metric_rows,metric_rows[1:])), metric_rows
                        if width == 1440:
                            assert max(metric_rows)-min(metric_rows) < 2, metric_rows
                            assert page.locator('[data-testid=stCaptionContainer] p').first.evaluate('e=>getComputedStyle(e).fontSize') == '14px'
                        charts = overview.locator('[data-testid=stPlotlyChart]')
                        expect(charts).to_have_count(3, timeout=30000)
                        for chart in charts.all():
                            ticks = chart.locator('.xaxislayer-above .xtick text')
                            expect(ticks).to_have_count(14)
                            boxes = ticks.evaluate_all('es=>es.map(e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right}})')
                            assert all(a['right'] <= b['left'] + 1 for a,b in zip(boxes,boxes[1:])), boxes
                        if width == 1440 and engine == 'chromium':
                            report['dashboard_desktop'] = desktop_signature(page, True)
                        page.screenshot(path=str(OUT / f'{engine}-dashboard-{width}.png'), full_page=False)
                        page.locator('[data-testid=stMetric]').first.scroll_into_view_if_needed()
                        page.screenshot(path=str(OUT / f'{engine}-cards-{width}.png'))
                        if width < 768:
                            expect(page.locator('[data-testid=stSidebar]')).to_have_attribute('data-collapsed', 'true')
                            page.get_by_role('button', name='Expand sidebar').click()
                            expect(page.locator('[data-testid=stSidebar]')).to_have_attribute('data-collapsed', 'false')
                            no_overflow(page)
                            page.get_by_role('button', name='Collapse sidebar').click()
                            expect(page.locator('[data-testid=stSidebar]')).to_have_attribute('data-collapsed', 'true')
                        page.get_by_role('tab', name='睡眠參數', exact=True).click()
                        settled(page)
                        panel = page.get_by_role('tabpanel', name='睡眠參數', exact=True)
                        expect(panel.locator('[data-testid=stMetric]')).to_have_count(9)
                        expect(panel.get_by_text('480 分鐘', exact=True)).to_be_visible()
                        no_overflow(page)
                        if width < 768:
                            assert not targets(page, 'button'), targets(page, 'button')
                        page.screenshot(path=str(OUT / f'{engine}-parameters-{width}.png'), full_page=False)
                        panel.get_by_text('期間對照', exact=True).click()
                        expect(panel.get_by_role('button', name='下載睡眠參數 CSV', exact=True)).to_be_visible(timeout=30000)
                        settled(page)
                        table = panel.locator('[data-testid=stDataFrame]:not(details:not([open]) [data-testid=stDataFrame])')
                        expect(table).to_have_count(1)
                        scrollers = table.locator('.dvn-scroller')
                        expect(scrollers.first).to_be_visible(timeout=15000)
                        scrollers.first.scroll_into_view_if_needed()
                        try:
                            page.wait_for_function('''id=>{
                              const panel=document.getElementById(id);
                              if(!panel)return false;
                              return [...panel.querySelectorAll('[data-testid=stDataFrame]')]
                                .filter(e=>!e.closest('details:not([open])'))
                                .some(e=>[...e.querySelectorAll('.dvn-scroller')].some(s=>s.clientWidth>0&&s.scrollWidth>s.clientWidth));
                            }''', arg=panel.get_attribute('id'), timeout=15000)
                        except Exception:
                            (OUT / 'table-debug.json').write_text(json.dumps(panel.locator('[data-testid=stDataFrame]').evaluate_all('''es=>es.map(e=>({
                              visible:!e.closest('details:not([open])'),html:e.outerHTML.slice(0,3500),
                              scrolls:[...e.querySelectorAll('.dvn-scroller')].map(s=>({width:s.clientWidth,scroll:s.scrollWidth,html:s.outerHTML.slice(0,1500)}))
                            }))'''),ensure_ascii=False,indent=2),encoding='utf-8')
                            raise
                        no_overflow(page)
                        page.screenshot(path=str(OUT / f'{engine}-table-{width}.png'), full_page=False)
                        page.goto(dashboard + '?diary=1')
                        iframe = page.locator('[data-testid=stIFrame]')
                        expect(iframe).to_be_visible()
                        expect(page.frame_locator('[data-testid=stIFrame]').locator('#home-page')).to_be_visible()
                        no_overflow(page)
                        if width < 768:
                            assert iframe.bounding_box()['height'] <= 900-55+1, iframe.bounding_box()
                            frame_box = iframe.bounding_box()
                            header_box = page.get_by_test_id('stHeader').bounding_box()
                            assert frame_box['y'] >= header_box['y']+header_box['height'], 'Toolbar covers diary'
                            container = page.get_by_test_id('stMainBlockContainer').bounding_box()
                            assert container['height'] <= 901, iframe.evaluate('''e=>{
                              const rows=[];for(let p=e;p&&rows.length<5;p=p.parentElement){const s=getComputedStyle(p);rows.push({
                               testid:p.dataset.testid,height:p.getBoundingClientRect().height,minHeight:s.minHeight,gap:s.gap,padding:s.padding,style:p.getAttribute('style')});}return rows;
                            }''')
                        report['checks'].append(f'{engine} {width}: home, menu, dialog, diary, ratings, dashboard, sidebar, all dates, nine parameters, table scroll, embedded diary')
                        print(f'PASS {engine} {width}px', flush=True)
                        context.close()
                    browser.close()
            if not args.baseline:
                assert not report['unexpected_requests'], report['unexpected_requests']
                assert not report['page_errors'], report['page_errors']
                before = json.loads((ROOT / 'tests/web_platform/fixtures/responsive_desktop.json').read_text(encoding='utf-8'))
                for key in ('home_desktop', 'dashboard_desktop'):
                    if key in report:
                        assert before[key] == report[key], (key,before[key],report[key])
                report['desktop_geometry_unchanged'] = 'dashboard_desktop' in report
                report['complete_matrix'] = len(report['checks']) == len(WIDTHS)*2
                report['real_device_required'] = ['iPhone Safari safe area, keyboard, browser chrome, pinch zoom, VoiceOver',
                                                   'Android Chrome keyboard, touch feel, TalkBack and scroll chaining']
                filename = f'result-{args.engine or "all"}-{args.width or "all"}.json' if args.engine or args.width else 'result.json'
                (OUT / filename).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            child.terminate()
            child.wait(timeout=10)
            server.shutdown()
            server.server_close()
    print('BASELINE saved' if args.baseline else 'PASS focused responsive checks' if args.engine or args.width else
          'PASS: Chromium + WebKit, all seven widths; UI only, desktop geometry preserved; real devices still required')


if __name__ == '__main__':
    main()
