"""Readable, presentation-only summaries of the already authorized measurements."""
from collections import defaultdict
from datetime import datetime
from html import escape
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .charts import extrema_sample
from .chart_style import NAMES, CHART_HELP, color_for, style_trend, chart_tools, render_trend
from .sleep import TZ, duration_label, sleep_display_summary


CATEGORIES = {
    '心率': ['HR'], '血壓': ['SBP', 'DBP'], '血氧': ['SpO2'], '體溫': ['Temperature'],
    'HRV': ['SDNN', 'RMSSD', 'TP', 'VLF', 'LF', 'HF', 'LF/HF'],
    '壓力與疲倦': ['stress', 'fatigue', 'StressTolerance', 'Adaptability'],
    '活動與運動': ['Steps', 'Calories', 'ActivitySteps', 'ActivityDistance', 'StaticTime', 'ActiveTime',
                 'StaticCalories', 'ActiveCalories', 'SportSteps', 'SportCalories', 'SportDuration',
                 'SportMaxHR', 'SportAvgHR', 'SportDistance'],
    '體重': ['Weight'], '血糖': ['Glucose'], '膽固醇': ['Cholesterol'], '尿酸': ['UricAcid'],
    '排尿量': ['UrineOutput'], '飲水量': ['WaterIntake'], '心臟與血管': ['HeartIndex', 'VascularIndex'],
    'RRI': ['RRI'],
}


def measured(row):
    value = datetime.fromisoformat(row['measured_at'].replace('Z', '+00:00'))
    return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)


def series_key(row):
    return tuple(row.get(k) for k in ('metric', 'source', 'unit', 'signal_type', 'device_external_id', 'algorithm_version'))


def valid_rows(metrics, names):
    return sorted((r for r in metrics if r['metric'] in names and r.get('value') is not None
                   and math.isfinite(float(r['value']))), key=measured)


def latest_series(metrics, name):
    """Choose the latest series; never average different units, devices or versions."""
    rows = valid_rows(metrics, [name])
    return [r for r in rows if series_key(r) == series_key(rows[-1])] if rows else []


def blood_pressure_pair(metrics):
    pairs: dict = defaultdict(lambda: defaultdict(list))
    for row in valid_rows(metrics, ['SBP', 'DBP']):
        if row.get('unit') != 'mmHg':
            continue
        key = (measured(row), row.get('source'), row.get('device_external_id'), row.get('signal_type'),
               row.get('algorithm_version'), row.get('external_record_id'))
        pairs[key][row['metric']].append(row)
    complete = [{name: values[0] for name, values in v.items()} for v in pairs.values()
                if set(v) == {'SBP', 'DBP'} and all(len(values) == 1 for values in v.values())]
    return max(complete, key=lambda v: measured(v['SBP'])) if complete else None


def unit_label(unit):
    return {'ratio': '比值', 'steps': '步', 'min': '分鐘', 's': '秒'}.get(unit, unit or '單位未確認')


def source_label(row):
    source = 'DocterCloud' if str(row.get('source', '')).lower() == 'doctercloud' else row.get('source') or '來源未提供'
    return source + (' · ' + str(row['device_external_id']) if row.get('device_external_id') else '')


def value_label(row):
    value = f"{float(row['value']):,.2f}".rstrip('0').rstrip('.')
    return value + (' ' + unit_label(row['unit']) if row.get('unit') else '')


def measurement_table(metrics):
    return pd.DataFrame([{'測量時間': measured(r).strftime('%Y/%m/%d %H:%M:%S'),
                          '量測項目': NAMES.get(r['metric'], r['metric']), '數值': r['value'],
                          '單位': unit_label(r.get('unit')), '資料來源': source_label(r)}
                         for r in reversed(valid_rows(metrics, {m['metric'] for m in metrics}))])


def trend_figure(metrics, names):
    groups = defaultdict(list)
    # Keep explicit missing measurements in the line, even though summaries omit them.
    for row in sorted((r for r in metrics if r['metric'] in names), key=measured):
        groups[series_key(row)].append(row)
    fig = go.Figure()
    for index, (key, rows) in enumerate(groups.items()):
        name, source, unit, signal, device, version = key
        label = NAMES.get(name, name)
        if sum(k[0] == name for k in groups) > 1:
            label += f' · 系列 {index + 1}'
        points = extrema_sample([(measured(r).replace(tzinfo=None),
                                 float(r['value']) if r.get('value') is not None and math.isfinite(float(r['value'])) else None)
                                for r in rows])
        origin = {'PPG': 'PPG-derived PRV', 'ECG': 'ECG-derived HRV'}.get(signal, '訊號來源未確認')
        details = escape(source_label(rows[0])) + '<br>' + escape(origin) + '<br>版本 ' + escape(str(version or '未提供'))
        fig.add_trace(go.Scatter(x=[p[0] for p in points], y=[p[1] for p in points], mode='lines+markers',
                                name=label, connectgaps=False,
                                line=dict(color=color_for(name), width=2.5, shape='linear', dash=['solid', 'dash', 'dot'][index % 3]),
                                marker=dict(size=5 if len(points) > 60 else 7, color=color_for(name)),
                                hovertemplate='<b>' + escape(label) + '</b> · %{y:,.3~f} ' + escape(unit_label(unit)) +
                                '<br>' + details + '<extra></extra>'))
    units = {r.get('unit') for r in metrics if r['metric'] in names}
    style_trend(fig)
    fig.update_yaxes(title=unit_label(next(iter(units))) if len(units) == 1 else '各系列原始數值', rangemode='normal')
    return fig


def open_category(category):
    st.session_state['dashboard_tabs'] = '生理數據'
    st.session_state['measurement_category'] = category


def metric_card(metrics, name, category, key):
    rows = latest_series(metrics, name)
    with st.container(border=True, key='summary-' + key):
        if rows:
            latest = rows[-1]
            delta = float(latest['value']) - float(rows[-2]['value']) if len(rows) > 1 else None
            st.metric(NAMES[name], value_label(latest), delta=f'較前次 {delta:+.2f}' if delta is not None else None, delta_color='off')
            st.caption(measured(latest).strftime('最後量測 %m/%d %H:%M') + ' · ' + source_label(latest))
            if not latest.get('unit'):
                st.caption('單位未確認')
        else:
            st.metric(NAMES[name], '—')
            st.caption('所選期間無可顯示的量測')
        st.button('查看' + category, key='open-' + key, on_click=open_category, args=(category,), width='stretch')


def overview_view(sessions, metrics, diaries, bundle=None):
    st.subheader('健康總覽')
    st.caption('以下為所選日期內的最後一次量測，並非即時監測。點卡片下方按鈕查看趨勢或量測表。')
    failed = [k for k, v in (bundle or {}).get('statuses', {}).items() if v['state'] != 'success']
    if failed:
        st.warning('部分平台資料尚未讀取完成；請到「原始資料／下載」查看連線狀態。未載入的類別不代表沒有紀錄。')
    cols = st.columns(4)
    with cols[0]:
        metric_card(metrics, 'HR', '心率', 'hr')
    with cols[1]:
        with st.container(border=True, key='summary-bp'):
            pair = blood_pressure_pair(metrics)
            st.metric('血壓（收縮壓／舒張壓）', f"{pair['SBP']['value']:g} / {pair['DBP']['value']:g} mmHg" if pair else '—')
            st.caption(measured(pair['SBP']).strftime('最後量測 %m/%d %H:%M') if pair else '所選期間無完整的同次血壓量測')
            if pair:
                st.caption(source_label(pair['SBP']))
            st.button('查看血壓', key='open-bp', on_click=open_category, args=('血壓',), width='stretch')
    with cols[2]:
        metric_card(metrics, 'SpO2', '血氧', 'oxygen')
    with cols[3]:
        metric_card(metrics, 'Temperature', '體溫', 'temperature')
    cols = st.columns(4)
    with cols[0]:
        with st.container(border=True, key='summary-sleep'):
            latest = max(sessions, key=lambda s: (s['sleep_date'], s.get('sleep_onset_at') or '')) if sessions else None
            st.metric('睡眠時長', duration_label(sleep_display_summary(latest)['total_minutes']) if latest else '—')
            st.caption('最近睡眠 ' + latest['sleep_date'] if latest else '所選期間無手錶睡眠紀錄')
            if latest:
                st.caption(source_label(latest))
            st.button('查看睡眠分析', key='open-sleep', on_click=lambda: st.session_state.update(dashboard_tabs='睡眠分析'), width='stretch')
    with cols[1]:
        metric_card(metrics, 'SDNN', 'HRV', 'sdnn')
    with cols[2]:
        metric_card(metrics, 'stress', '壓力與疲倦', 'stress')
    with cols[3]:
        metric_card(metrics, 'fatigue', '壓力與疲倦', 'fatigue')
    st.caption(f'期間內共有 {len(sessions)} 份手錶睡眠紀錄、{len(diaries)} 份睡眠日誌。壓力、疲倦及 HRV 沿用來源數值，不套用未定義的正常範圍。')
    st.subheader('常用量測趨勢')
    st.caption(CHART_HELP)
    tools = chart_tools('overview')
    for cols, pairs in [(st.columns(2), [('心率', ['HR']), ('血壓', ['SBP', 'DBP'])]),
                        (st.columns(2), [('血氧', ['SpO2']), ('體溫', ['Temperature'])])]:
        for col, (label, names) in zip(cols, pairs):
            with col, st.container(border=True):
                st.markdown('**' + label + '**')
                rows = valid_rows(metrics, names)
                if rows:
                    # Only combine equal units on one axis; uncommon mixed units stay in the category view.
                    chosen = latest_series(rows, names[0]) or latest_series(rows, names[-1])
                    rows = [r for r in metrics if r['metric'] in names and r.get('unit') == chosen[-1].get('unit')]
                    render_trend(trend_figure(rows, names), key='overview-' + names[0], tools=tools)
                else:
                    st.info('所選期間無可顯示的量測')


def category_view(metrics):
    st.subheader('生理數據')
    st.caption('像平台一樣依類別查看；每一列保留量測時間與資料來源。')
    categories = dict(CATEGORIES)
    unknown = sorted({m['metric'] for m in metrics} - {n for values in categories.values() for n in values})
    if unknown:
        categories['其他指標'] = unknown
    category = st.selectbox('生理資料類別', list(categories), key='measurement_category')
    names = categories[category]
    rows = valid_rows(metrics, names)
    if not rows:
        st.info('所選期間無可顯示的' + category + '量測。可調整日期；原始紀錄及讀取狀態可在「原始資料／下載」核對。')
        return
    available = [n for n in names if any(r['metric'] == n for r in rows)]
    selected = available if len(available) <= 2 else [st.selectbox('量測項目', available, format_func=lambda n: NAMES.get(n, n))]
    rows = [r for r in rows if r['metric'] in selected]
    for name in selected:
        group = latest_series(rows, name)
        values = [float(r['value']) for r in group]
        latest = group[-1]
        st.markdown('**' + NAMES.get(name, name) + '**')
        cols = st.columns(4)
        for col, label, value in zip(cols, ['最新量測', '期間平均', '期間最低', '期間最高'],
                                     [values[-1], sum(values) / len(values), min(values), max(values)]):
            col.metric(label, value_label(dict(latest, value=value)))
        st.caption(f"{source_label(latest)} · {unit_label(latest.get('unit'))} · 同來源／裝置／版本 {len(group)} 筆 · 最後量測 {measured(latest):%Y/%m/%d %H:%M}")
    display = st.radio('顯示方式', ['趨勢圖', '量測表'], horizontal=True, key='measurement_display')
    if display == '趨勢圖':
        st.caption(CHART_HELP)
        tools = chart_tools('category')
        # Separate units, signals, devices and versions instead of merging incompatible series.
        groups = defaultdict(list)
        for row in metrics:
            if row['metric'] not in selected:
                continue
            groups[(row.get('unit'), row.get('source'), row.get('device_external_id'), row.get('signal_type'), row.get('algorithm_version'))].append(row)
        for index, group in enumerate(groups.values()):
            st.caption(source_label(group[0]) + ' · ' + unit_label(group[0].get('unit')))
            render_trend(trend_figure(group, selected), key='category-' + str(index), tools=tools)
    else:
        frame = measurement_table(rows)
        page_size = 100
        pages = (len(frame) + page_size - 1) // page_size
        page = int(st.number_input('量測表頁次', min_value=1, max_value=pages, value=1, step=1,
                                   key=f'measurement_page_{category}_{len(frame)}'))
        st.caption(f'共 {len(frame)} 筆量測，第 {page}/{pages} 頁，每頁最多 100 筆。')
        st.dataframe(frame.iloc[(page - 1) * page_size:page * page_size], hide_index=True, width='stretch')
    export = measurement_table(rows).map(lambda value: "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value)
    st.download_button('下載此類量測 CSV', export.to_csv(index=False).encode('utf-8-sig'),
                       file_name='measurements.csv', mime='text/csv')
