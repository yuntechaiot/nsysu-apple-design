"""A full inventory, raw record browser, and export of caller-scoped data."""
import json
from datetime import datetime

import pandas as pd
import streamlit as st

from .platform import KINDS
from .sleep import TZ


def all_platform_view(bundle, connection_error=None):
    st.subheader('DocterCloud 全部資料')
    st.caption('直接讀取平台已授權資料；不另外備份到 Supabase。缺少紀錄、讀取失敗與尚未確認的單位會分別標示。')
    if not bundle:
        st.info(connection_error or '此受試者尚無對應的 DocterCloud 會員，或平台尚未連線。')
        return
    statuses = bundle['statuses']
    failed = [kind for kind in KINDS if statuses[kind]['state'] != 'success']
    if failed:
        st.warning('部分平台類別尚未讀取完成：' + '、'.join(KINDS[k] for k in failed) + '。其他已成功取得的資料仍可查看。')
    if bundle['parse_issues']:
        st.info(f"有 {len(bundle['parse_issues'])} 筆資料格式尚無法繪圖；原始紀錄仍完整保留在下方，沒有當成零或刪除。")
    st.dataframe(pd.DataFrame([{'資料類別': label, '狀態': '已讀取' if statuses[k]['state'] == 'success' else '未完成',
                                '原始筆數': statuses[k]['count'], '訊息': statuses[k]['message']}
                               for k, label in KINDS.items()]), hide_index=True)
    with st.expander('受試者平台資料'):
        st.json(bundle['profile'])
    kind = st.selectbox('平台資料類別', list(KINDS), format_func=lambda k: KINDS[k], key='platform_record_kind')
    status = statuses[kind]
    if status['state'] != 'success':
        st.error(status['message'])
    else:
        rows = bundle['raw'][kind]
        if not rows:
            st.info('查詢成功，這段期間沒有此類紀錄。')
        else:
            pages = (len(rows) + 199) // 200
            page = int(st.number_input('原始資料頁次', min_value=1, max_value=pages, value=1, step=1,
                                       key=f'platform_raw_page_{kind}_{len(rows)}'))
            display = []
            for raw in rows[(page - 1) * 200:page * 200]:
                row = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in raw.items()}
                for field in ('occur_time', 'start_time', 'end_time', 'emd_time'):
                    value = raw.get(field)
                    if isinstance(value, (int, float)) and 0 <= value < 10_000_000_000:
                        row[field + '（台灣時間）'] = datetime.fromtimestamp(value, TZ).strftime('%Y-%m-%d %H:%M:%S')
                display.append(row)
            st.caption(f'共 {len(rows)} 筆，第 {page}/{pages} 頁；每頁最多 200 筆。JSON 下載包含這類全部已取得的紀錄。')
            st.dataframe(pd.DataFrame(display), hide_index=True)
        st.download_button('下載此類完整原始資料', json.dumps(rows, ensure_ascii=False, indent=2),
                           file_name=kind.replace('/', '-') + '.json', mime='application/json')
    st.download_button('下載全部已取得的平台資料', json.dumps({'profile': bundle['profile'], 'records': bundle['raw'],
                        'statuses': statuses, 'loaded_at': bundle['loaded_at']}, ensure_ascii=False),
                       file_name='doctercloud-records.json', mime='application/json')
