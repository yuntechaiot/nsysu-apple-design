"""Dashboard tab for the user-supplied sleep parameter definitions."""
from collections import Counter, defaultdict
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .chart_style import render_trend, show_measurement_dates, style_trend
from .parsers import digest
from .sleep_parameters import (PARAMETERS, MEAN_LABELS, calculate_parameters, instant,
                               period_parameters)


def clock(value):
    when = instant(value)
    return when.strftime('%Y/%m/%d %H:%M') if when else '未提供'


def means_table(rows):
    return pd.DataFrame([{'指標': MEAN_LABELS[r['metric']], '平均值': r['mean'], '實際筆數': r['count'],
                          '單位／量尺': r['unit'], '來源': r['source'], '裝置': r['device'],
                          '訊號': r['signal_type'], '演算法版本': r['algorithm_version'],
                          '量尺定義': r['scale_definition'],
                          '首筆量測': clock(r['first_at']), '末筆量測': clock(r['last_at'])} for r in rows])


def parameter_caption(result, key, definition):
    source = result['sources'][key]
    if source == '睡眠日誌備案':
        definition = {'tst_minutes': '日誌最後醒來時間－日誌估算入睡時間',
                      'sol_minutes': '日誌估算入睡時間－日誌躺床時間',
                      'se_percent': '日誌備案 TST／總躺床時數 × 100%'}[key]
    elif source.startswith('睡眠日誌備案：'):
        definition = '日誌填寫的夜間清醒總分鐘'
    return f'{source} · {definition}'


def record_table(results):
    rows = []
    for result in results:
        row = {'睡眠日期': result['date'], '日誌紀錄': result['diary_id'], '手錶紀錄': result['session_id'],
               '手錶來源': result['watch_source']}
        row.update({label + f'（{unit}）': result['values'][key] for key, label, unit, _ in PARAMETERS})
        row.update({label + '計算來源': result['sources'][key] for key, label, *_ in PARAMETERS})
        for metric, label in MEAN_LABELS.items():
            groups = [r for r in result['pre_sleep'] if r['metric'] == metric]
            row[label] = groups[0]['mean'] if len(groups) == 1 else None
            row[label + '筆數'] = groups[0]['count'] if len(groups) == 1 else None
            row[label + '說明'] = '多個系列，請查看入睡前指數明細' if len(groups) > 1 else groups[0]['unit'] if groups else '無可計算量測'
        row.update({'入睡時間採用來源': result['onset_basis'], '採用入睡時間': clock(result['times']['onset']),
                    '手錶原始入睡起點': clock(result['times']['watch_onset']),
                    '入睡前時窗開始': clock(result['window_start']),
                    '入睡前時窗結束': clock(result['window_end']),
                    '定義版本': result['definition_version'],
                    '資料說明': '；'.join(dict.fromkeys(result['notes'] + [label + '：' + result['reasons'][key]
                                                     for key, label, *_ in PARAMETERS if result['reasons'][key]]))})
        rows.append(row)
    return pd.DataFrame(rows)


def csv_bytes(frame):
    safe = frame.map(lambda value: "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value)
    return safe.to_csv(index=False).encode('utf-8-sig')


def parameter_figure(results, key, label, unit):
    counts = Counter(r['date'] for r in results)
    seen: dict = defaultdict(int)
    labels, values, details = [], [], []
    for row in results:
        day = row['date']
        seen[day] += 1
        labels.append(day + (f'<br>第 {seen[day]} 筆' if counts[day] > 1 else ''))
        values.append(row['values'][key])
        details.append([escape(row['diary_id']), escape(row['session_id']), escape(row['reasons'][key])])
    fig = go.Figure(go.Bar(x=[r['date'] for r in results], y=values, customdata=details,
                          marker=dict(color='#0071e3', cornerradius=4), name=label,
                          hovertemplate='%{x}<br>' + escape(label) + ' %{y:,.2~f} ' + unit +
                          '<br>日誌 %{customdata[0]} · 手錶 %{customdata[1]}<extra></extra>'))
    style_trend(fig)
    fig.update_traces(x=labels)
    fig.update_layout(hovermode='closest', bargap=.35)
    fig.update_xaxes(type='category', title_text='睡眠日期（同日多筆分開）')
    fig.update_yaxes(title_text=unit, rangemode='tozero')
    show_measurement_dates(fig)
    for date_label, value in zip(labels, values):
        if value is None:
            fig.add_annotation(x=date_label, y=0, text='缺資料', showarrow=False, yshift=12,
                               font=dict(size=11, color='#626772'))
    return fig


def single_view(diaries, sessions, metrics, window, allow_observed):
    dates = sorted({str(r.get('date')) for r in diaries if r.get('date')} |
                   {str(r.get('sleep_date')) for r in sessions if r.get('sleep_date')}, reverse=True)
    log_dates = {str(r.get('date')) for r in diaries}
    watch_dates = {str(r.get('sleep_date')) for r in sessions}
    day = st.selectbox('睡眠參數日期', dates, key='sleep-parameters-date',
                       format_func=lambda value: value + ' · ' + ('日誌＋手錶' if value in log_dates and value in watch_dates else
                                                                  '僅日誌' if value in log_dates else '僅手錶'))
    logs = [r for r in diaries if str(r.get('date')) == day]
    watches = [r for r in sessions if str(r.get('sleep_date')) == day]
    log = logs[0] if len(logs) == 1 else None
    session = watches[0] if len(watches) == 1 else None
    if len(logs) > 1:
        index = st.selectbox('選擇對照的日誌', range(len(logs)), index=None, placeholder='同日有多筆，請明確選擇',
                             format_func=lambda i: f"日誌 {logs[i].get('id', i + 1)} · 躺床 {clock(logs[i].get('bedtime_at'))}",
                             key='sleep-parameters-diary-' + day + '-' + digest([r.get('id') for r in logs])[:12])
        log = logs[index] if index is not None else None
    if len(watches) > 1:
        index = st.selectbox('選擇對照的手錶紀錄', range(len(watches)), index=None, placeholder='同日有多筆，請明確選擇',
                             format_func=lambda i: f"{watches[i].get('source', '來源未提供')} · {watches[i].get('external_session_id', watches[i].get('id', i + 1))} · {clock(watches[i].get('start_at'))}",
                             key='sleep-parameters-watch-' + day + '-' + digest([
                                 [r.get('source'), r.get('external_session_id'), r.get('id')] for r in watches])[:12])
        session = watches[index] if index is not None else None
    if (len(logs) > 1 and log is None) or (len(watches) > 1 and session is None):
        st.info('請選擇要對照的紀錄；未選取前只顯示可獨立確認的參數，不合併多筆資料。')
    result = calculate_parameters(log, session, metrics, window, allow_observed)
    st.caption(f"日誌 {result['diary_id']} · 手錶 {result['session_id']}" + (f" · {result['watch_source']}" if session else ''))
    if not watches:
        st.info('此日沒有手錶睡眠紀錄，改以睡眠日誌備案計算；未填寫的必要欄位仍會顯示缺值原因。')
    for note in result['notes']:
        st.warning(note)
    for start in range(0, len(PARAMETERS), 3):
        for col, (key, label, unit, definition) in zip(st.columns(3), PARAMETERS[start:start + 3]):
            with col, st.container(border=True):
                value = result['values'][key]
                st.metric(label, f'{value:,.2f}'.rstrip('0').rstrip('.') + ' ' + unit if value is not None else '—',
                          help=parameter_caption(result, key, definition) if value is not None else definition)
                st.caption(result['reasons'][key] if value is None else parameter_caption(result, key, definition))
    st.markdown('#### 入睡前的壓力與疲倦')
    st.caption(f"觀察時窗：{clock(result['window_start'])} 至 {clock(result['window_end'])}，共 {window} 分鐘；包含起點、不含入睡當下。")
    st.caption('觀察時窗的入睡時間來源：' + result['onset_basis'])
    for col, (metric, label) in zip(st.columns(2), MEAN_LABELS.items()):
        groups = [row for row in result['pre_sleep'] if row['metric'] == metric]
        with col, st.container(border=True):
            value = f"{groups[0]['mean']:,.2f}".rstrip('0').rstrip('.') if len(groups) == 1 else '多個系列' if groups else '—'
            st.metric(label, value)
            st.caption(f"{groups[0]['count']} 筆 · {groups[0]['unit']} · {groups[0]['source']}" if len(groups) == 1 else
                       '不同來源、裝置、訊號或版本分開列於明細，不合併平均。' if groups else
                       '缺少入睡時間，或此時窗沒有有效量測；不補零。')
    if result['pre_sleep']:
        st.dataframe(means_table(result['pre_sleep']), hide_index=True, width='stretch')
    with st.expander('查看計算採用的時刻與來源'):
        st.dataframe(pd.DataFrame([{'時刻': label, '台灣日期時間': clock(result['times'][key])} for key, label in
                                  [('bed', '日誌躺床'), ('watch_onset', '手錶原始入睡起點'),
                                   ('onset', '本次採用入睡時間'), ('wake', '日誌最後醒來'), ('out', '日誌離床')]]),
                     hide_index=True, width='stretch')
        st.caption('入睡時間採用來源：' + result['onset_basis'])
        st.caption('手錶原始起點來源：' + result['watch_onset_basis'])


def sleep_parameters_view(sessions, diaries, metrics, context_status='success'):
    st.subheader('睡眠參數')
    # st.caption('依「睡眠平台數據定義_20261020_yc」呈現；所有時刻使用台灣時間。')
    st.info('本頁 TST＝日誌醒來－手錶入睡，SOL＝手錶入睡－日誌躺床；WASO 依文件採手錶清醒時間。既有「睡眠分析」研究指標保留原定義。')
    st.caption('優先採用 Word 公式；手錶入睡時間缺少或與日誌區間不一致時，改用日誌估算入睡時間計算 TST、SOL、SE。'
               '日誌估算＝開始嘗試入睡時間＋自覺入睡所需分鐘；未填嘗試入睡時間時以上床時間為起點。'
               '手錶清醒時間無法使用時，WASO 改採日誌夜間清醒總分鐘；必要資料缺少或時間矛盾時仍保留缺值。')
    if context_status != 'success':
        st.warning('入睡前的歷史量測尚未完整載入，平均值可能缺少查詢首日前的資料；請按上方「查看資料」重新載入。')
    if not sessions and not diaries:
        st.info('所選日期沒有睡眠日誌或手錶睡眠紀錄；可調整查詢日期後重新載入。')
        return
    with st.expander('參數定義與資料來源'):
        st.dataframe(pd.DataFrame([{'睡眠參數': label, '單位': unit, '定義／來源': definition} for _, label, unit, definition in PARAMETERS] +
                                  [{'睡眠參數': '日誌備案入睡時間', '單位': '台灣時間',
                                    '定義／來源': '開始嘗試入睡時間（未填時採躺床時間）＋自覺入睡所需分鐘；代入 TST、SOL、SE，依各項標示來源'},
                                   {'睡眠參數': 'WASO 日誌備案', '單位': '分鐘', '定義／來源': '手錶無有效清醒時間時，採日誌夜間清醒總分鐘'}] +
                                  [{'睡眠參數': label, '單位': '依來源量尺', '定義／來源': '入睡前指定時窗內實際量測的平均，預設 60 分鐘'} for label in MEAN_LABELS.values()]),
                     hide_index=True, width='stretch')
    window = st.selectbox('入睡前觀察時窗（分鐘）', [30, 60, 120], index=1, key='sleep-parameters-window')
    example_start = f'{(23 * 60 - window) // 60:02d}:{(23 * 60 - window) % 60:02d}'
    st.caption(f'備註：用於計算入睡前 {window} 分鐘的平均壓力與疲倦指數。'
               f'例如 23:00 入睡，會取 {example_start} 至 23:00 前的有效量測。'
               '此設定不影響 TST、SOL、SE 等睡眠參數；時窗內沒有有效量測時顯示缺值。')
    # with st.expander('入睡時間來源設定'):
    #     allow_observed = st.checkbox('採用首筆睡眠分期起點供觀察', value=False, key='sleep-parameters-observed',
    #                                  help='來源未提供已確認入睡時間時，可選用首筆淺睡／深睡／REM 起點。這只代表已提供的觀測起點，不推估缺少的分期。')
    #     if allow_observed:
    #         st.caption('只有缺少來源入睡時間時才使用分期起點；本頁會列出實際採用來源。')
    allow_observed = True
    mode = st.radio('參數顯示方式', ['單次觀察', '期間對照'], horizontal=True, key='sleep-parameters-mode')
    if mode == '單次觀察':
        single_view(diaries, sessions, metrics, window, allow_observed)
    else:
        st.caption('只自動配對同受試者、同日期且唯一的紀錄；入睡時間與日誌不一致時採日誌備案。多筆紀錄不自動合併。')
        results = period_parameters(diaries, sessions, metrics, window, allow_observed)
        table = record_table(results)
        st.dataframe(table, hide_index=True, width='stretch')
        parameter = st.selectbox('觀察睡眠參數', range(len(PARAMETERS)), format_func=lambda i: PARAMETERS[i][1],
                                 key='sleep-parameters-trend')
        key, label, unit, _ = PARAMETERS[parameter]
        render_trend(parameter_figure(results, key, label, unit), key='sleep-parameters-period')
        details = []
        for result in results:
            for row in means_table(result['pre_sleep']).to_dict('records'):
                details.append({'睡眠日期': result['date'], '日誌紀錄': result['diary_id'], '手錶紀錄': result['session_id'], **row})
        if details:
            with st.expander('入睡前指數的各系列明細'):
                frame = pd.DataFrame(details)
                st.dataframe(frame, hide_index=True, width='stretch')
                st.download_button('下載入睡前指數明細 CSV', csv_bytes(frame), 'pre_sleep_indices.csv', 'text/csv', key='sleep-parameters-means-download')
        st.download_button('下載睡眠參數 CSV', csv_bytes(table), 'sleep_parameters.csv', 'text/csv', key='sleep-parameters-download')
