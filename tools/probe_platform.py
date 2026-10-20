"""Read-only probe using credentials explicitly supplied in the project PDF.

No credential/token output. Raw research responses are kept under private/.
"""
from pathlib import Path
import json
import re
import sys
from datetime import datetime, timedelta

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from nsysu.platform import Platform  # noqa: E402
from nsysu.sleep import TZ  # noqa: E402
from nsysu.parsers import docter_sleep, docter_metrics  # noqa: E402


def main():
    path = Path('frontend/source/國立中山大學DocterCloud管理平台資訊_20250121.pdf')
    text = '\n'.join(p.extract_text() or '' for p in PdfReader(path).pages)
    if '帳號/密碼一樣' not in text:
        raise ValueError('Document does not provide an unambiguous login rule')
    account = re.search(r'\bNPUST\d+\b', text)
    if not account:
        raise ValueError('No explicitly supplied researcher account')
    platform = Platform()
    try:
        platform.token = platform.login(account.group(), account.group())['access_token']
        members = platform.members('ycc')
        output = Path('private/platform-probe')
        output.mkdir(parents=True, exist_ok=True)
        (output/'members.json').write_text(json.dumps(members, ensure_ascii=False), encoding='utf-8')
        known = {f'ycc{i:08}' for i in range(1, 51)}
        matches = [m for m in members if m.get('identifier') in known or m.get('account') in known]
        meta = {'login': 'success', 'member_count': len(members), 'member_fields': sorted({k for m in members for k in m}), 'exact_identity_matches': len(matches)}
        # A single explicitly matched participant; no database writes occur here.
        if matches:
            target = next((m for m in matches if 'ycc00000038' in (m.get('account'), m.get('identifier'))), matches[0])
            end = datetime.now(TZ)
            start = end - timedelta(days=30)
            raw = {kind: platform.fetch(kind, target['id'], int(start.timestamp()), int(end.timestamp())) for kind in ('sleep', 'hrv', 'heart/rate')}
            (output/'observations.json').write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
            normalized = {'sessions': [docter_sleep(r) for r in raw['sleep']], 'metrics': docter_metrics(raw['hrv']) + docter_metrics(raw['heart/rate'], 'hr')}
            (output/'normalized.json').write_text(json.dumps(normalized, ensure_ascii=False), encoding='utf-8')
            meta.update(counts={k: len(v) for k, v in raw.items()}, normalized_sessions=len(normalized['sessions']), normalized_metrics=len(normalized['metrics']), sleep_record_fields=sorted({k for r in raw['sleep'] for k in r}), hrv_record_fields=sorted({k for r in raw['hrv'] for k in r}))
        (output/'status.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(meta, ensure_ascii=True))
    except Exception as error:
        print(json.dumps({'login_or_probe': 'failed', 'error_type': type(error).__name__, 'message': 'Provided platform credentials or endpoint could not be verified. No database writes.'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
