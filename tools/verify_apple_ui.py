"""Responsive and motion QA with synthetic data; external requests are intercepted."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import sys
import threading
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from nsysu.cloud import diary_document

OUT = ROOT / 'test-results/apple'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        base = f'http://127.0.0.1:{self.server.server_port}/'
        config = {'supabase_url': 'https://synthetic.supabase.co', 'publishable_key': 'sb_publishable_SYNTHETIC',
                  'diary_url': base, 'dashboard_url': base + '?view=dashboard', 'timezone': 'Asia/Taipei'}
        query = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
        content = diary_document(config, query).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *_):
        pass


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/'
    errors, unexpected, checks = [], [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge')
            context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)

            def intercept(route):
                request = route.request
                if request.url.startswith(base):
                    route.continue_()
                elif request.url.endswith('/rest/v1/rpc/check_diary_invitation'):
                    route.fulfill(json=True)
                elif '/rest/v1/' in request.url:
                    if request.method != 'GET':
                        unexpected.append(request.url)
                    route.fulfill(json=[])
                else:
                    unexpected.append(request.url)
                    route.abort()

            context.route('**/*', intercept)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            for width in (320, 375, 390, 430, 768, 1365):
                page.set_viewport_size({'width': width, 'height': 900})
                page.goto(base)
                expect(page.locator('#home-page')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                checks.append(f'home {width}px no horizontal overflow')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(base)
            page.screenshot(path=str(OUT / 'mobile-home.png'), full_page=True)
            page.locator('#admin-login-button').click()
            expect(page.locator('#auth-dialog')).to_be_visible()
            assert page.locator('#auth-email').evaluate('e => parseFloat(getComputedStyle(e).fontSize) >= 16')
            page.screenshot(path=str(OUT / 'mobile-login.png'), full_page=True)
            page.get_by_role('button', name='關閉登入', exact=True).click()
            page.goto(base + '?member=ycc00000001&invite=' + 'a' * 64)
            expect(page.locator('#member-page')).to_be_visible()
            page.locator('#f-name').fill('SYNTHETIC')
            page.locator('#f-date').fill('2026-10-18')
            page.locator('#f-headphone').fill('0')
            page.locator('#next-step').click()
            expect(page.locator('[data-step="1"]')).to_be_visible()
            bed_date = page.locator('#f-bed-date').bounding_box()
            bed_time = page.locator('#f-sleep-time').bounding_box()
            assert bed_time['y'] >= bed_date['y'] + bed_date['height'], 'Mobile date/time must stack'
            for field, value in [('f-sleep-time', '2230'), ('f-lights-out', '2245'), ('f-sleep-onset', '15'),
                                 ('f-morning-wake-time', '0700'), ('f-wake-time', '0715')]:
                page.locator('#' + field).fill(value)
            expect(page.locator('#f-sleep-time')).to_have_value('22:30')
            page.screenshot(path=str(OUT / 'mobile-time.png'), full_page=True)
            page.locator('#next-step').click()
            page.locator('#f-wakeups').fill('0')
            page.locator('input[name=fallback][value="無"]').check()
            page.locator('#cg-disturbance input[value="無"]').check()
            page.locator('#scale-disturbance [data-v="0"]').click()
            page.locator('#scale-quality [data-v="4"]').click()
            for width in (320, 375, 390, 430):
                page.set_viewport_size({'width': width, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                for button in page.locator('.step-panel:not([hidden]) .scale-btn').all():
                    bounds = button.bounding_box()
                    assert bounds['width'] >= 32 and bounds['height'] >= 48
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path=str(OUT / 'mobile-rating.png'), full_page=True)
            page.locator('#next-step').click()
            expect(page.locator('#review-area')).to_contain_text('22:30')
            page.screenshot(path=str(OUT / 'mobile-review.png'), full_page=True)
            assert not unexpected, unexpected
            checks.append('mobile four-step diary, stacked times, ratings, review without writes')
            # Verify immediate feedback, smooth retarget and reduced-motion handling.
            page.get_by_role('button', name='修改夜間狀況', exact=True).click()
            button = page.locator('#scale-quality [data-v="4"]')
            button.scroll_into_view_if_needed()
            bounds = button.bounding_box()
            page.mouse.move(bounds['x'] + bounds['width']/2, bounds['y'] + bounds['height']/2)
            page.mouse.down()
            page.wait_for_function("getComputedStyle(document.querySelector('#scale-quality [data-v=\"4\"]')).transform !== 'none'")
            page.mouse.up()
            page.wait_for_function("document.querySelector('#scale-quality [data-v=\"4\"]').style.transform === ''")
            page.emulate_media(reduced_motion='reduce')
            page.mouse.down()
            assert button.evaluate('e => getComputedStyle(e).transform') == 'none'
            page.mouse.up()
            checks.append('spring press/release settles; reduced motion disables transforms')
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    (OUT / 'result.json').write_text(json.dumps({'status': 'passed', 'checks': checks,
                                               'production_writes': False, 'page_errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: responsive layouts, mobile diary, spring feedback and reduced motion; no production writes')


if __name__ == '__main__':
    main()
