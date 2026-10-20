"""Per-request PostgREST client. Only publishable key plus caller JWT is used."""
import requests
import re
from .config import setting

REF = "ztsyxnrnemvcladbaaem"


class StoreError(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__(f'日誌服務請求失敗 ({status})；請確認登入與服務連線')


def settings():
    url = setting("SUPABASE_URL", f"https://{REF}.supabase.co").rstrip("/")
    expected = setting("SUPABASE_EXPECTED_REF", REF)
    if url != f"https://{expected}.supabase.co":
        raise ValueError("Supabase URL 與預期專案不一致，停止連線")
    key = setting("SUPABASE_PUBLISHABLE_KEY") or setting("SUPABASE_KEY")
    if not key.startswith("sb_publishable_"):
        raise ValueError("僅接受 Publishable Key，禁止 Service Role Key")
    return url, key


class Store:
    def __init__(self, token=None):
        self.url, key = settings()
        self.headers = {"apikey": key, "Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def request(self, method, path, payload=None, params=None):
        response = requests.request(method, self.url + path, headers=self.headers, json=payload, params=params, timeout=30)
        if not response.ok:
            # Never echo tokens, credentials or raw server tracebacks into UI.
            raise StoreError(response.status_code)
        return response.json() if response.content else None

    def rows(self, table, **filters):
        rows = []
        order = "member_id.asc" if table in ("participant_access", "research_participants", "participant_invites") else "id.asc"
        for offset in range(0, 100000, 1000):
            page = self.request("GET", f"/rest/v1/{table}", params={"select": "*", "order": order, "limit": 1000, "offset": offset, **filters})
            rows.extend(page)
            if len(page) < 1000:
                return rows
        raise ValueError("查詢超過 100000 筆，請縮小時間區間")

    def import_data(self, member, source, sessions, metrics, raw):
        from .parsers import digest
        payload = {"p_member_id": member, "p_source": source, "p_sessions": sessions,
                   "p_metrics": metrics, "p_raw": raw, "p_hash": digest(raw)}
        return self.request("POST", "/rest/v1/rpc/import_research_data", payload)

    def user(self):
        return self.request("GET", "/auth/v1/user")

    def record_failure(self, member, source, raw, error):
        from .parsers import digest
        row = {"member_id": member, "source": source, "payload_hash": digest({"failed": raw, "error": error}),
               "raw_payload": raw, "status": "failed", "error_message": error[:500], "algorithm_version": "vtca-import-2.0.0"}
        headers = dict(self.headers, Prefer="resolution=merge-duplicates,return=minimal")
        response = requests.post(self.url + "/rest/v1/data_imports", headers=headers, params={"on_conflict": "member_id,source,payload_hash"}, json=row, timeout=15)
        return response.ok


def diary_email(account):
    username = str(account or '').strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9_-]{3,31}', username):
        raise ValueError('請輸入研究團隊提供的日誌帳號')
    return username.lower() + '@diary.nsysu.invalid'


def login(account, password):
    result = Store().request("POST", "/auth/v1/token?grant_type=password", {"email": diary_email(account), "password": password})
    if not result.get('user', {}).get('app_metadata', {}).get('diary_staff'):
        raise ValueError('此帳號尚未開通日誌管理權限')
    return result
