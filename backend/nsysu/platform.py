"""Only endpoints evidenced by supplied V5-4 documentation and existing code."""
import requests
from .config import setting
from .parsers import digest

KINDS = {
    'sleep': '睡眠', 'hrv': 'HRV／壓力與疲倦', 'heart/rate': '心率',
    'blood/pressure': '血壓', 'blood/oxygen': '血氧', 'body/temperature': '體溫',
    'cholesterol': '膽固醇', 'uric-acid': '尿酸', 'urine-output': '排尿量',
    'drinking-water': '飲水量', 'weight': '體重', 'blood/glucose': '血糖／醣類分析',
    'heart/vessel': '心臟與血管健康指數', 'sports': '運動紀錄', 'activity': '活動紀錄',
    'step': '步數', 'calories': '卡路里', 'rri': 'RRI',
}


class PlatformError(ValueError):
    def __init__(self, message, status=None, code=None):
        super().__init__(message)
        self.status, self.code = status, code


class Platform:
    def __init__(self, token=None):
        self.base = setting("DOCTERCLOUD_BASE_URL", "https://icare.docter.pro/back-end/app").rstrip("/")
        if self.base != "https://icare.docter.pro/back-end/app":
            raise ValueError("平台 URL 必須先依官方文件審核，避免憑證傳往未知主機")
        self.token = token
        self._sports_web = False

    def call(self, method, path, params=None, data=None):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        sports = method == 'GET' and path == '/physiologic/sports'
        use_web = sports and self._sports_web
        if use_web:
            response = self._web_sports(headers, params)
        else:
            response = requests.request(method, self.base + path, headers=headers, params=params, data=data, timeout=25, allow_redirects=False)
            if sports and response.status_code == 404:
                # Current official portal config and Sports view use this exact
                # read-only route. Reuse the same scoped token, never credentials.
                use_web = True
                response = self._web_sports(headers, params)
        if not response.ok:
            raise PlatformError(f"平台回應 HTTP {response.status_code}", status=response.status_code)
        payload = response.json()
        if payload.get("success") is not True:
            code = payload.get('code')
            messages = {-1: '平台連線已到期，請重新登入日誌帳號', -2: '平台帳密不符',
                        -3: '平台未授權這類資料', -4: '平台帳號已停用', -5: '平台不接受這組查詢參數'}
            raise PlatformError(messages.get(code, '平台未回報成功'), status=response.status_code, code=code)
        if use_web:
            self._sports_web = True
        return payload.get("data")

    def _web_sports(self, headers, params):
        query = dict(params or {})
        query.setdefault('page', 1)
        return requests.request('GET', 'https://icare.docter.pro/back-end/web/physiologic/sports',
                                headers=headers, params=query, timeout=25, allow_redirects=False)

    def login(self, account, password):
        return self.call("POST", "/login/researcher", data={"account": account, "password": password})

    def _pages(self, path, params):
        rows: list[dict] = []
        seen: set[tuple] = set()
        for page in range(1, 20001):
            # Some documented array endpoints return HTTP 500 if given page/
            # per_page. Discover the response first; only follow real pagination.
            data = self.call('GET', path, params={**params, **({'page': page} if page > 1 else {})})
            if isinstance(data, list):
                if page != 1:
                    raise PlatformError('平台在分頁途中改變回傳格式，請重新查詢')
                return data
            if not isinstance(data, dict) or not isinstance(data.get('list'), list):
                raise PlatformError('平台回傳的資料不是清單或分頁格式')
            if data.get('current_page', page) != page:
                raise PlatformError('平台未正確切換分頁，未顯示不完整結果')
            batch = data['list']
            last, total = data.get('last_page'), data.get('total')
            before = len(rows)
            for row in batch:
                identity = ('id', str(row['id'])) if row.get('id') is not None else ('hash', digest(row))
                if identity not in seen:
                    seen.add(identity)
                    rows.append(row)
            finished = (isinstance(last, int) and page >= last) or (isinstance(total, int) and len(rows) >= total)
            if finished or not batch:
                if isinstance(total, int) and len(rows) < total:
                    raise PlatformError('平台分頁筆數不足，請重新查詢')
                return rows
            if len(rows) == before:
                raise PlatformError('平台重複回傳同一頁，未顯示不完整結果')
        raise PlatformError('資料超過分頁上限，請縮小日期區間')

    def members(self, keyword='ycc'):
        # Live API rejects an empty keyword despite V5-4 marking it optional.
        if not keyword.strip():
            raise ValueError('請提供受試者編號關鍵字')
        return self._pages('/user', {'keyword': keyword})

    def fetch(self, kind, member_id, start, end):
        if kind not in KINDS:
            raise ValueError("未支援的官方 API")
        if end <= start or end - start > 90 * 86400:
            raise ValueError("平台查詢區間須介於 0–90 天")
        return self._pages('/physiologic/' + kind, {'user_id': member_id, 'start_date': start, 'end_date': end})

    def fetch_range(self, kind, member_id, start, end):
        if end <= start:
            raise ValueError('結束時間必須晚於開始時間')
        rows = {}
        while start < end:
            upper = min(start + 89 * 86400, end)
            for row in self.fetch(kind, member_id, start, upper):
                identity = ('id', str(row['id'])) if row.get('id') is not None else ('hash', digest(row))
                rows[identity] = row
            start = upper
        return list(rows.values())
