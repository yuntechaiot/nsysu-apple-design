"""Playwright browser QA. All Supabase writes mocked; no synthetic production data."""
from pathlib import Path
import json
import os
from playwright.sync_api import sync_playwright, expect

BASE_URL = os.getenv('NSYSU_TEST_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
DASHBOARD_URL = os.getenv('NSYSU_TEST_DASHBOARD_URL', 'http://127.0.0.1:8501')
OUT = Path('test-results')
OUT.mkdir(exist_ok=True)


def main():
    rows = []
    writes = []
    participants = [{'member_id': f'ycc{i:08d}', 'display_name': None} for i in range(1, 51)]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge')
        context = browser.new_context(locale='en-US', timezone_id='America/Los_Angeles', viewport={'width': 1365, 'height': 1000})
        def route(request_route):
            request = request_route.request
            if '/auth/v1/token' in request.url:
                request_route.fulfill(json={'access_token': 'SYNTHETIC', 'refresh_token': 'test', 'expires_at': 2000000000, 'user': {'id': 'synthetic', 'app_metadata': {'diary_staff': True, 'participant_admin': True, 'diary_username': 'RESEARCH_TEST'}}})
            elif '/auth/v1/logout' in request.url:
                request_route.fulfill(status=204)
            elif '/rest/v1/sleep_logs' in request.url:
                if request.method == 'POST':
                    row = request.post_data_json
                    writes.append(row)
                    rows.append(dict(row, id=1))
                    request_route.fulfill(status=201, body='')
                elif request.method == 'PATCH':
                    row = request.post_data_json
                    writes.append(row)
                    rows[0].update(row)
                    request_route.fulfill(json=rows)
                else:
                    request_route.fulfill(json=rows)
            else:
                request_route.abort()
        context.route('https://*.supabase.co/**', route)
        def participant_route(request_route):
            request = request_route.request
            if request.method == 'POST':
                row = request.post_data_json
                if any(p['member_id'] == row['member_id'] for p in participants):
                    request_route.fulfill(status=409, json={'error': '此受試者編號已存在'})
                else:
                    participants.append(row)
                    request_route.fulfill(status=201, json={'participant': row})
            else:
                authorized = bool(request.headers.get('authorization'))
                request_route.fulfill(json={'participants': [dict(p, display_name=p['display_name'] if authorized else None) for p in participants], 'can_manage': authorized})
        context.route(BASE_URL + '/api/participants', participant_route)
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE_URL + '/')
        expect(page.locator('#home-page')).to_be_visible()
        expect(page.locator('#auth-dialog')).not_to_be_visible()
        assert page.locator('#qr-grid .qr-card').count() == 0
        page.screenshot(path=str(OUT/'flow-home.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(OUT/'flow-mobile-home.png'),full_page=True)
        page.set_viewport_size({'width':1365,'height':1000})
        page.get_by_role('button',name='開始填寫 →',exact=True).click()
        page.locator('#member-entry').click()
        expect(page.locator('#participant-options [role=option]')).to_have_count(50)
        page.locator('#member-entry').fill('wrong')
        page.locator('#entry-submit').click()
        expect(page.locator('#entry-error')).to_be_visible()
        page.locator('#member-entry').fill('00000001')
        expect(page.locator('#participant-options [role=option]')).to_have_count(1)
        page.locator('#member-entry').press('ArrowDown')
        page.locator('#member-entry').press('Enter')
        expect(page.locator('#participant-share')).to_be_visible()
        expect(page.locator('#selected-qr img')).to_be_visible()
        expect(page.locator('#participant-link')).to_have_value(BASE_URL + '/?member=ycc00000001')
        expect(page.locator('#qr-network-hint')).to_be_visible()
        page.screenshot(path=str(OUT/'participant-selected.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(OUT/'participant-mobile.png'),full_page=True)
        page.set_viewport_size({'width':1365,'height':1000})
        page.locator('#entry-submit').click()
        expect(page.locator('#member-page')).to_be_visible()
        page.locator('#next-step').click()
        expect(page.locator('#form-error')).to_contain_text('姓名')
        expect(page.locator('[data-step="0"]')).to_be_visible()
        assert page.locator('input[type=time]').count() == 0
        assert page.locator('#f-sleep-time-ampm').count() == 0
        page.locator('#f-name').fill('<img src=x onerror=alert(1)>')
        page.locator('#f-date').fill('2026-10-18')
        page.locator('#f-headphone').fill('0')
        page.locator('#f-wore-watch').select_option('false')
        page.locator('#f-sleep-medication').select_option('')
        page.locator('#f-drank-alcohol').select_option('true')
        page.locator('#next-step').click()
        page.locator('#f-bed-date').fill('2026-10-17')
        page.locator('#f-lights-date').fill('2026-10-17')
        page.locator('#f-out-date').fill('2026-10-18')
        for field, value in [('f-sleep-time','2230'),('f-lights-out','2345'),('f-sleep-onset','15'),('f-morning-wake-time','0700'),('f-wake-time','0715')]:
            page.locator('#'+field).fill(value)
        expect(page.locator('#f-sleep-time')).to_have_value('22:30')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(OUT/'flow-mobile-time.png'),full_page=True)
        page.set_viewport_size({'width':1365,'height':1000})
        page.locator('#next-step').click()
        page.locator('#f-wakeups').fill('0')
        page.locator('input[name=fallback][value="無"]').check()
        page.locator('#cg-disturbance input[value="無"]').check()
        page.locator('#scale-disturbance [data-v="0"]').click()
        page.locator('#scale-quality [data-v="4"]').click()
        page.locator('#next-step').click()
        expect(page.locator('[data-step="3"]')).to_be_visible()
        assert not writes, 'Reviewing must not submit research data'
        assert page.locator('#review-area img').count() == 0
        page.get_by_role('button',name='修改睡眠時間',exact=True).click()
        expect(page.locator('#f-sleep-time')).to_have_value('22:30')
        page.locator('#next-step').click()
        page.locator('#next-step').click()
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(OUT/'diary-24h.png'), full_page=True)
        page.locator('#submit-btn').click()
        expect(page.locator('#toast')).to_contain_text('日誌已送出')
        expect(page.locator('#success-page')).to_be_visible()
        assert writes[0]['bedtime_at'] == '2026-10-17T22:30:00+08:00'
        assert writes[0]['lights_out_at'] == '2026-10-17T23:45:00+08:00'
        assert writes[0]['wore_watch'] is False and writes[0]['sleep_medication'] is None and writes[0]['drank_alcohol'] is True
        assert 'sleep_time_ampm' not in writes[0]
        page.locator('.header-nav').get_by_role('link',name='歷史紀錄',exact=True).click()
        page.locator('#history-login-button').click()
        page.locator('#auth-email').fill('RESEARCH_TEST')
        page.locator('#auth-password').fill('SYNTHETIC')
        page.locator('#auth-submit').click()
        expect(page.locator('#history-area .rec-item')).to_have_count(1)
        assert page.locator('#history-area img').count() == 0
        page.locator('#history-area').get_by_role('button',name='編輯').click()
        expect(page.locator('#f-wore-watch')).to_have_value('false')
        expect(page.locator('#f-sleep-medication')).to_have_value('')
        page.locator('#f-sleep-medication').select_option('false')
        page.locator('#next-step').click()
        page.locator('#next-step').click()
        page.locator('#next-step').click()
        page.locator('#submit-btn').click()
        expect(page.locator('#toast')).to_contain_text('日誌已更新')
        assert writes[-1]['sleep_medication'] is False
        page.locator('.brand').click()
        page.get_by_role('button',name='開始填寫 →',exact=True).click()
        page.get_by_role('button',name='＋ 新增受試者',exact=True).first.click()
        expect(page.locator('#participant-form')).to_be_visible()
        page.locator('#new-member-id').fill('ycc00000001')
        page.locator('#new-member-name').fill('不可覆蓋')
        page.locator('#create-participant').click()
        expect(page.locator('#participant-create-status')).to_contain_text('已存在')
        page.locator('#new-member-id').fill('ycc00000051')
        page.locator('#new-member-name').fill('測試姓名')
        page.locator('#create-participant').click()
        expect(page.locator('#selected-member-label')).to_contain_text('測試姓名')
        expect(page.locator('#participant-link')).to_have_value(BASE_URL + '/?member=ycc00000051')
        page.locator('#member-entry').fill('試姓')
        expect(page.locator('#participant-options [role=option]')).to_have_count(1)
        page.locator('#participant-options [role=option]').click()
        page.locator('#member-entry').fill('找不到的姓名')
        expect(page.locator('#participant-share')).not_to_be_visible()
        expect(page.locator('#participant-options')).to_contain_text('找不到')
        assert not errors, errors
        page.locator('.header-nav').get_by_role('link',name='歷史紀錄',exact=True).click()
        page.get_by_role('button',name='登出',exact=True).click()
        expect(page.locator('#history-area')).to_contain_text('需要登入')
        page.locator('.brand').click()
        page.get_by_role('link',name='研究人員：受試者填寫連結／QR Code',exact=True).click()
        expect(page.locator('#qr-grid .qr-card')).to_have_count(51)
        assert '測試姓名' not in page.locator('#qr-grid').inner_text()
        page.locator('#search-input').fill('38')
        expect(page.locator('#qr-grid .qr-card:visible')).to_have_count(1)
        page.locator('#qr-grid .qr-card:visible').click()
        expect(page.locator('#selected-member-label')).to_have_text('ycc00000038')
        page.goto(BASE_URL + '/?member=ycc00000051')
        expect(page.locator('#member-page')).to_be_visible()
        expect(page.locator('#member-chip')).to_have_text('ycc00000051')
        page.locator('.brand').click()
        page.get_by_role('button',name='開始填寫 →',exact=True).click()
        page.get_by_role('button',name='＋ 新增受試者',exact=True).first.click()
        expect(page.locator('#participant-access-help')).to_be_visible()
        page.locator('#participant-login').click()
        expect(page.locator('#auth-dialog')).to_be_visible()
        page.locator('#auth-email').fill('RESEARCH_TEST')
        page.locator('#auth-password').fill('SYNTHETIC')
        page.locator('#auth-submit').click()
        expect(page.locator('#participant-form')).to_be_visible()
        page.locator('#participant-dialog .dialog-close').click()
        page.goto(DASHBOARD_URL)
        expect(page.get_by_role('heading',name='睡眠與生理研究',exact=True)).to_be_visible(timeout=30000)
        expect(page.get_by_role('tab')).to_have_count(0)
        expect(page.get_by_label('平台帳號',exact=True)).to_be_visible()
        expect(page.get_by_label('研究資料電子郵件',exact=True)).to_have_count(0)
        page.screenshot(path=str(OUT/'dashboard-empty.png'),full_page=True)
        context.close()
        browser.close()
    result = {'locale':'en-US','browser_timezone':'America/Los_Angeles','synthetic_writes':'mocked_only','checks': ['task-first home','mobile layout','searchable participant dropdown and keyboard selection','QR link and local-network hint','administrator creation and duplicate rejection','authorized partial name search','logout removes participant names','new participant deep link','4-step diary','review and return to edit','24h numeric input','tri-state create','history edit','XSS escaping','logout privacy','QR directory and search','purpose-specific dashboard login'],'errors':errors}
    (OUT/'browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS browser: searchable participants, QR, creation/login/duplicates, name privacy, 4-step diary, history, mobile and dashboard')


if __name__ == '__main__':
    main()
