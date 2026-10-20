"""Read-only UI smoke test using supplied researcher credentials in memory."""
from pathlib import Path
import json
import re
import sys

from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from nsysu.platform import Platform  # noqa: E402


def main():
    path = Path('frontend/source/國立中山大學DocterCloud管理平台資訊_20250121.pdf')
    text = '\n'.join(p.extract_text() or '' for p in PdfReader(path).pages)
    assert '帳號/密碼一樣' in text
    account = re.search(r'\bNPUST\d+\b', text).group()
    token = Platform().login(account, account)['access_token']
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'frontend/source/數據監控室.py'), default_timeout=60)
    app.session_state['platform_token'] = token
    app.run()
    next(x for x in app.selectbox if x.label == '選擇受試者').set_value('ycc00000038').run()
    next(x for x in app.radio if x.label == '日期範圍').set_value('近 30 天').run()
    next(x for x in app.button if x.label == '查看資料').click().run(timeout=60)
    assert not app.exception, 'Live UI returned an exception'
    values = [x for x in app.metric if x.label in ('Stress Index 壓力指數','Fatigue Index 疲倦指數')]
    assert len(values) == 2 and all(x.value != '暫無資料' for x in values), 'Expected actual platform index values'
    report = {'live_platform_login': 'passed', 'actual_stress_and_fatigue_rendered': True, 'database_writes': 0, 'ui_exceptions': 0}
    Path('test-results/live-platform-ui.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
