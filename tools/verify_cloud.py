"""單一 Streamlit 服務的瀏覽器回歸；Supabase 僅使用記憶體假資料。"""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit, parse_qs
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results/cloud'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}/'
    env = {**os.environ, 'PUBLIC_APP_URL': base}
    with (OUT / 'server.log').open('w', encoding='utf-8') as log:
        child = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'streamlit_app.py'),
                                  '--server.address', '127.0.0.1', '--server.port', str(port),
                                  '--server.headless', 'true', '--browser.gatherUsageStats', 'false'],
                                 cwd=ROOT, env=env, stdout=log, stderr=log,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            deadline = time.monotonic() + 45
            while True:
                if child.poll() is not None:
                    raise RuntimeError('Streamlit 測試服務啟動失敗')
                try:
                    with urlopen(base + '_stcore/health', timeout=.5) as result:
                        if result.status == 200:
                            break
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError('Streamlit 測試服務啟動逾時')
                time.sleep(.2)
            run_browser(base)
        finally:
            child.terminate()
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def run_browser(base):
    records, writes, page_errors, bad_local_routes = [], [], [], []
    management_writes = []
    invitations = {'ycc00000001': 'a' * 64}
    fixed_invitations = {}
    participants = [{'member_id': f'ycc{i:08d}', 'display_name': None} for i in range(1, 51)]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge')
        context = browser.new_context(locale='en-US', timezone_id='America/Los_Angeles', viewport={'width': 1365, 'height': 1000})

        def supabase(route):
            request = route.request
            path = urlsplit(request.url).path
            authorized = request.headers.get('authorization') == 'Bearer SYNTHETIC'
            if path == '/auth/v1/token':
                credentials = request.post_data_json
                if 'grant_type=password' in request.url and (credentials.get('email') != 'research_test@diary.nsysu.invalid' or credentials.get('password') != 'SYNTHETIC'):
                    route.fulfill(status=401, json={})
                    return
                route.fulfill(json={'access_token': 'SYNTHETIC', 'refresh_token': 'test', 'expires_at': 2000000000, 'user': {'id': 'synthetic', 'app_metadata': {'diary_staff': True, 'participant_admin': True, 'diary_username': 'RESEARCH_TEST'}}})
            elif path == '/auth/v1/user':
                route.fulfill(status=200 if authorized else 401, json={'id': 'synthetic', 'app_metadata': {'participant_admin': True}} if authorized else {})
            elif path == '/auth/v1/logout':
                route.fulfill(status=204)
            elif path == '/rest/v1/participant_invites':
                route.fulfill(json=[{'member_id': row['member_id']} for row in participants if not row.get('archived_at')])
            elif path == '/rest/v1/research_participants':
                route.fulfill(json=participants if authorized else [])
            elif path == '/rest/v1/rpc/register_participant':
                if not authorized:
                    route.fulfill(status=403, json={})
                    return
                data = request.post_data_json
                if any(row['member_id'] == data['p_member_id'] for row in participants):
                    route.fulfill(status=409, json={})
                    return
                row = {'member_id': data['p_member_id'], 'display_name': data['p_display_name']}
                participants.append(row)
                route.fulfill(json=row)
            elif path == '/rest/v1/rpc/check_diary_invitation':
                data = request.post_data_json
                active = any(row['member_id'] == data['p_member_id'] and not row.get('archived_at') for row in participants)
                route.fulfill(json=active and data['p_invite'] in (invitations.get(data['p_member_id']), fixed_invitations.get(data['p_member_id'])))
            elif path == '/rest/v1/rpc/manage_research_participant':
                assert authorized
                data = request.post_data_json
                row = next(row for row in participants if row['member_id'] == data['p_member_id'])
                management_writes.append(data)
                if data['p_action'] == 'update':
                    row['display_name'] = data['p_display_name']
                else:
                    row['archived_at'] = '2026-10-19T00:00:00Z' if data['p_action'] == 'archive' else None
                    invitations.pop(row['member_id'], None)
                route.fulfill(json=row)
            elif path == '/rest/v1/rpc/get_fixed_diary_invitation':
                data = request.post_data_json
                member = data['p_member_id']
                active = any(row['member_id'] == member and not row.get('archived_at') for row in participants)
                if not authorized or not active:
                    route.fulfill(status=403, json={})
                else:
                    token = fixed_invitations.setdefault(member, ('c' if member == 'ycc00000001' else 'b') * 64)
                    route.fulfill(json={'member_id': member, 'invite': token, 'fixed': True, 'expires_at': None})
            elif path == '/rest/v1/rpc/submit_invited_diary':
                data = request.post_data_json
                row = data['p_entry']
                active = any(subject['member_id'] == row['member_id'] and not subject.get('archived_at') for subject in participants)
                if not active or data['p_invite'] not in (invitations.get(row['member_id']), fixed_invitations.get(row['member_id'])):
                    route.fulfill(status=403, json={})
                    return
                writes.append(row)
                records.append({**row, 'id': len(records)+1, 'created_at': '2026-10-18T00:00:00+08:00', 'time_review_status': 'verified'})
                route.fulfill(json={'status': 'success'})
            elif path == '/rest/v1/sleep_logs':
                if request.method == 'POST':
                    row = request.post_data_json
                    writes.append(row)
                    records.append({**row, 'id': 1})
                    route.fulfill(status=201, body='')
                elif request.method == 'PATCH':
                    assert authorized
                    row = request.post_data_json
                    writes.append(row)
                    records[0].update(row)
                    route.fulfill(json=records)
                elif request.method == 'DELETE':
                    assert authorized
                    query = parse_qs(urlsplit(request.url).query)
                    selected = [row for row in records if 'eq.' + str(row['id']) == query['id'][0] and 'eq.' + row['member_id'] == query['member_id'][0]]
                    assert len(selected) == 1
                    management_writes.append({'delete_diary': selected[0]['id']})
                    records.remove(selected[0])
                    route.fulfill(json=selected)
                else:
                    member = parse_qs(urlsplit(request.url).query).get('member_id', [None])[0]
                    route.fulfill(json=[row for row in records if member in (None, 'eq.' + row['member_id'])] if authorized else [])
            else:
                route.abort()

        context.route('https://*.supabase.co/**', supabase)
        page = context.new_page()
        page.on('pageerror', lambda error: page_errors.append(str(error)))
        page.on('request', lambda request: bad_local_routes.append(request.url) if request.url.startswith(base) and urlsplit(request.url).path.startswith(('/api/', '/web/')) else None)
        page.goto(base)
        ui = page.frame_locator('iframe').first
        expect(ui.locator('#home-page')).to_be_visible(timeout=30000)
        expect(ui.locator('#auth-dialog')).not_to_be_visible()
        def header_visible():
            chrome = page.locator('[data-testid=stHeader]').bounding_box()
            frame = page.locator('iframe').first.bounding_box()
            brand = ui.locator('.brand-symbol').bounding_box()
            header = ui.locator('.site-header').bounding_box()
            assert frame['y'] >= chrome['y'] + chrome['height'], (frame, chrome)
            assert brand['y'] >= frame['y'] and brand['y'] + brand['height'] <= header['y'] + header['height']
        header_visible()
        page.screenshot(path=str(OUT / 'home.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert ui.locator('body').evaluate('node=>node.ownerDocument.documentElement.scrollWidth<=node.ownerDocument.defaultView.innerWidth')
        header_visible()
        page.screenshot(path=str(OUT / 'mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1365, 'height': 1000})
        ui.get_by_role('link', name='查看或修改過去的日誌', exact=True).click()
        expect(ui.locator('#history-page')).to_be_visible()
        expect(ui.locator('#history-member-select option')).to_have_count(51)
        expect(ui.locator('#history-member-select')).to_have_value('')
        ui.locator('#history-member-select').select_option('ycc00000002')
        expect(ui.locator('#history-context')).to_contain_text('ycc00000002')
        expect(ui.locator('#history-login-button')).to_be_visible()
        expect(ui.locator('#history-area .rec-item')).to_have_count(0)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert ui.locator('body').evaluate('node=>node.ownerDocument.documentElement.scrollWidth<=node.ownerDocument.defaultView.innerWidth')
        page.screenshot(path=str(OUT / 'history-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1365, 'height': 1000})
        ui.locator('.brand').click()
        ui.get_by_role('button', name='開始填寫 →', exact=True).click()
        assert page.url == base, 'Embedded navigation must preserve the Streamlit host URL'
        expect(ui.locator('#auth-dialog')).to_be_visible()
        expect(ui.locator('#entry-page')).not_to_be_visible()
        page.screenshot(path=str(OUT / 'start-login.png'), full_page=True)
        ui.get_by_role('button', name='關閉登入', exact=True).click()
        expect(ui.locator('#home-page')).to_be_visible()
        ui.get_by_role('button', name='開始填寫 →', exact=True).click()
        ui.locator('#auth-email').fill('RESEARCH_TEST')
        ui.locator('#auth-password').fill('SYNTHETIC')
        ui.locator('#auth-submit').click()
        expect(ui.locator('#auth-dialog')).not_to_be_visible()
        expect(ui.locator('#entry-page')).to_be_visible()
        ui.locator('#member-entry').fill('00000001')
        expect(ui.locator('#participant-options [role=option]')).to_have_count(1)
        ui.locator('#participant-options [role=option]').click()
        expect(ui.locator('#participant-link')).to_have_value(base + '?member=ycc00000001&invite=' + 'c' * 64)
        expect(ui.locator('#selected-qr img')).to_be_visible()
        assert ui.locator('#invitation-login,#generate-invitation,#revoke-invitation').count() == 0
        ui.locator('#signout-btn').click()
        page.goto(base + '?view=start')
        expect(ui.locator('#auth-dialog')).to_be_visible()
        expect(ui.locator('#entry-page')).not_to_be_visible()
        ui.get_by_role('button', name='關閉登入', exact=True).click()
        page.goto(base + '?member=ycc00000001')
        expect(ui.locator('#auth-dialog')).to_be_visible()
        expect(ui.locator('#member-page')).not_to_be_visible()
        page.goto(base + '?member=ycc00000001&invite=' + '0' * 64)
        expect(ui.locator('#toast')).to_contain_text('到期或停用')
        expect(ui.locator('#member-page')).not_to_be_visible()
        page.goto(base + '?member=ycc00000001&invite=' + 'a' * 64)
        expect(ui.locator('#member-page')).to_be_visible()
        ui.locator('#f-name').fill('<img src=x onerror=alert(1)>')
        ui.locator('#f-date').fill('2026-10-18')
        ui.locator('#f-headphone').fill('0')
        ui.locator('#f-wore-watch').select_option('false')
        ui.locator('#f-sleep-medication').select_option('')
        ui.locator('#f-drank-alcohol').select_option('true')
        ui.locator('#next-step').click()
        for field, value in [('f-bed-date', '2026-10-17'), ('f-lights-date', '2026-10-17'), ('f-out-date', '2026-10-18'),
                             ('f-sleep-time', '2230'), ('f-lights-out', '2345'), ('f-sleep-onset', '15'),
                             ('f-morning-wake-time', '0700'), ('f-wake-time', '0715')]:
            ui.locator('#' + field).fill(value)
        expect(ui.locator('#f-sleep-time')).to_have_value('22:30')
        ui.locator('#next-step').click()
        ui.locator('#f-wakeups').fill('0')
        ui.locator('input[name=fallback][value="無"]').check()
        ui.locator('#cg-disturbance input[value="無"]').check()
        ui.locator('#scale-disturbance [data-v="0"]').click()
        ui.locator('#scale-quality [data-v="4"]').click()
        ui.locator('#next-step').click()
        expect(ui.locator('[data-step="3"]')).to_be_visible()
        assert not writes
        assert ui.locator('#review-area img').count() == 0
        ui.locator('#submit-btn').click()
        expect(ui.locator('#success-page')).to_be_visible()
        assert writes[0]['bedtime_at'] == '2026-10-17T22:30:00+08:00'
        assert writes[0]['lights_out_at'] == '2026-10-17T23:45:00+08:00'
        assert writes[0]['wore_watch'] is False and writes[0]['sleep_medication'] is None and writes[0]['drank_alcohol'] is True
        assert 'sleep_time_ampm' not in writes[0]
        ui.locator('.header-nav').get_by_role('link', name='歷史紀錄', exact=True).click()
        ui.locator('#history-login-button').click()
        ui.locator('#auth-email').fill('UNKNOWN_TEST')
        ui.locator('#auth-password').fill('SYNTHETIC')
        ui.locator('#auth-submit').click()
        expect(ui.locator('#auth-status')).to_contain_text('登入失敗')
        ui.locator('#auth-email').fill('RESEARCH_TEST')
        ui.locator('#auth-password').fill('SYNTHETIC')
        ui.locator('#auth-submit').click()
        expect(ui.locator('#history-area .rec-item')).to_have_count(1)
        expect(ui.locator('#history-member-select')).to_have_value('ycc00000001')
        ui.locator('#history-member-select').select_option('ycc00000002')
        expect(ui.locator('#history-area .rec-item')).to_have_count(0)
        expect(ui.locator('#history-context')).to_contain_text('ycc00000002')
        ui.locator('#history-member-select').select_option('ycc00000001')
        expect(ui.locator('#history-area .rec-item')).to_have_count(1)
        assert ui.locator('#history-area img').count() == 0
        ui.locator('#history-area').get_by_role('button', name='編輯').click()
        ui.locator('#f-sleep-medication').select_option('false')
        for _ in range(3):
            ui.locator('#next-step').click()
        ui.locator('#submit-btn').click()
        expect(ui.locator('#toast')).to_contain_text('日誌已更新')
        assert writes[-1]['sleep_medication'] is False
        ui.locator('.header-nav').get_by_role('link', name='歷史紀錄', exact=True).click()
        ui.locator('#history-area').get_by_role('button', name='刪除', exact=True).click()
        expect(ui.locator('#management-description')).to_contain_text('2026-10-18')
        assert ui.locator('#management-dialog img').count() == 0
        ui.locator('#management-dialog').get_by_role('button', name='取消', exact=True).click()
        assert not management_writes and len(records) == 1
        ui.locator('#history-area').get_by_role('button', name='刪除', exact=True).click()
        ui.locator('#management-confirm').click()
        expect(ui.locator('#history-area .rec-item')).to_have_count(0)
        assert management_writes == [{'delete_diary': 1}]
        ui.locator('.brand').click()
        ui.get_by_role('button', name='開始填寫 →', exact=True).click()
        ui.locator('#member-entry').fill('ycc00000001')
        ui.locator('#participant-options [role=option]').click()
        expect(ui.locator('#participant-link')).to_have_value(base + '?member=ycc00000001&invite=' + 'c' * 64)
        expect(ui.locator('#selected-qr img')).to_be_visible()
        page.goto(base + '?view=start')
        ui.locator('#member-entry').fill('ycc00000001')
        ui.locator('#participant-options [role=option]').click()
        expect(ui.locator('#participant-link')).to_have_value(base + '?member=ycc00000001&invite=' + 'c' * 64)
        expect(ui.locator('#selected-qr img')).to_be_visible()
        assert ui.locator('#invitation-login,#generate-invitation,#revoke-invitation').count() == 0
        page.screenshot(path=str(OUT / 'fixed-qr.png'), full_page=True)
        ui.get_by_role('button', name='＋ 新增受試者', exact=True).first.click()
        expect(ui.locator('#participant-form')).to_be_visible()
        ui.locator('#new-member-id').fill('ycc00000051')
        ui.locator('#new-member-name').fill('SYNTHETIC NAME')
        ui.locator('#create-participant').click()
        expect(ui.locator('#participant-link')).to_have_value(base + '?member=ycc00000051&invite=' + 'b' * 64)
        page.goto(base + '?member=ycc00000051&invite=' + 'b' * 64)
        expect(ui.locator('#member-chip')).to_have_text('ycc00000051')
        ui.locator('.brand').click()
        ui.get_by_role('button', name='開始填寫 →', exact=True).click()
        ui.locator('#member-entry').fill('ycc00000051')
        ui.locator('#participant-options [role=option]').click()
        ui.get_by_role('button', name='修改姓名', exact=True).click()
        ui.locator('#management-name').fill('SYNTHETIC <img src=x onerror=alert(1)>')
        ui.locator('#management-confirm').click()
        expect(ui.locator('#selected-member-label')).to_contain_text('SYNTHETIC <img')
        assert ui.locator('#selected-member-label img').count() == 0
        page.screenshot(path=str(OUT / 'management.png'), full_page=True)
        ui.locator('#archive-participant').click()
        ui.locator('#management-confirm').click()
        expect(ui.locator('#participant-share')).not_to_be_visible()
        assert 'ycc00000051' not in invitations
        ui.locator('.header-nav').get_by_role('link', name='歷史紀錄', exact=True).click()
        expect(ui.locator('#history-member-select option[value=ycc00000051]')).to_contain_text('已移除')
        ui.locator('#history-member-select').select_option('ycc00000051')
        expect(ui.locator('#history-context')).to_contain_text('SYNTHETIC <img')
        expect(ui.locator('#history-new-diary')).to_be_disabled()
        assert ui.locator('#history-context img').count() == 0
        expect(ui.locator('#history-area .rec-item')).to_have_count(0)
        ui.locator('.brand').click()
        ui.get_by_role('button', name='開始填寫 →', exact=True).click()
        ui.locator('#show-archived').check()
        ui.locator('#member-entry').fill('ycc00000051')
        ui.locator('#participant-options [role=option]').click()
        expect(ui.locator('#restore-participant')).to_be_visible()
        expect(ui.locator('#selected-qr')).to_contain_text('固定 QR Code 已停用')
        ui.locator('#restore-participant').click()
        ui.locator('#management-confirm').click()
        expect(ui.locator('#participant-link')).to_have_value(base + '?member=ycc00000051&invite=' + 'b' * 64)
        expect(ui.locator('#selected-qr img')).to_be_visible()
        assert participants[-1]['archived_at'] is None
        ui.locator('.brand').click()
        expect(ui.locator('#home-dashboard-link')).to_have_attribute('href', base + '?view=dashboard')
        with context.expect_page() as opened:
            ui.locator('#home-dashboard-link').click()
        dashboard = opened.value
        dashboard.on('pageerror', lambda error: page_errors.append(str(error)))
        expect(dashboard.get_by_role('heading', name='睡眠與生理研究', exact=True)).to_be_visible(timeout=30000)
        expect(dashboard.get_by_label('日誌帳號', exact=True)).to_be_visible()
        expect(dashboard.get_by_role('link', name='← 回到日誌首頁')).to_have_attribute('href', base)
        assert dashboard.url == base + '?view=dashboard'
        dashboard.screenshot(path=str(OUT / 'dashboard.png'), full_page=True)
        dashboard.close()
        page.bring_to_front()
        ui.locator('.header-nav').get_by_role('link', name='歷史紀錄', exact=True).click()
        ui.locator('#signout-btn').click()
        expect(ui.locator('#history-member-select')).not_to_contain_text('SYNTHETIC')
        expect(ui.locator('#history-login-button')).to_be_visible()
        page.screenshot(path=str(OUT / 'history-selector.png'), full_page=True)
        page.goto(base + '?view=history&member=ycc00000002')
        expect(ui.locator('#history-page')).to_be_visible()
        expect(ui.locator('#history-member-select')).to_have_value('ycc00000002')
        assert not page_errors, page_errors
        assert not bad_local_routes, bad_local_routes
        browser.close()
    result = {'status': 'passed', 'streamlit_only': True, 'production_writes': False,
              'checks': ['home', 'desktop/mobile header fully visible', 'mobile', 'participant search', 'scoped secure QR/deep link', 'plain/expired link blocked', 'fixed QR automatic display/reload stability', 'unneeded QR buttons removed', 'archive disables QR/restore retains same QR', 'four-step diary', 'review does not write',
                         '24-hour/Taiwan time', 'tri-state fields', 'history auth/edit', 'history dropdown and subject filtering', 'archived history/name privacy', 'history deep link/mobile', 'HTML escaping',
                         'caller-authorized registration', 'username login and incorrect credentials', 'single diary deletion/cancel', 'participant rename/remove/restore', 'one-URL dashboard navigation', 'dashboard login', 'return link'],
              'page_errors': page_errors, 'unexpected_flask_routes': bad_local_routes}
    (OUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: Streamlit-only diary, history, QR, administrator registration and Dashboard; all Supabase writes mocked')


if __name__ == '__main__':
    main()
