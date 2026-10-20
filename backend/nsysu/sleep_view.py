"""DocterCloud-style sleep summaries with explicit missing-data boundaries."""
from collections import defaultdict
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .dashboard_summary import latest_series, measured, source_label
from .sleep import TZ, duration_label, number, sleep_display_summary
from .chart_style import COLORS, style_trend, chart_tools, render_trend

STAGES = {'deep': ('深睡', '#549688'), 'light': ('淺睡', '#4db2a2'),
          'rem': ('REM 快速動眼期', '#97cacb'), 'awake': ('清醒', '#b6bec8')}


def local_time(value, full=False):
    if not value:
        return '未提供'
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(TZ).strftime('%Y/%m/%d %H:%M' if full else '%m/%d %H:%M')


def session_label(session):
    return local_time(session.get('start_at')) + ' – ' + local_time(session.get('end_at')) + ' · ' + source_label(session)


def sleep_records_table(sessions):
    rows = []
    for session in sorted(sessions, key=lambda s: (s['sleep_date'], s.get('start_at') or ''), reverse=True):
        summary = sleep_display_summary(session)
        rows.append({'睡眠日期': session['sleep_date'], '開始時間': local_time(session.get('start_at'), True),
                     '結束時間': local_time(session.get('end_at'), True), '睡眠總時數（TST）': duration_label(summary['total_minutes']),
                     '清醒時間': duration_label(summary['awake']), '淺睡': duration_label(summary['light']),
                     '深睡': duration_label(summary['deep']), 'REM': duration_label(summary['rem']),
                     '資料來源': source_label(session)})
    return pd.DataFrame(rows)


def summary_bar(summary):
    fig = go.Figure()
    for key, (label, color) in STAGES.items():
        value = summary[key]
        if value is not None:
            fig.add_trace(go.Bar(x=[value], y=['時長分布'], orientation='h', name=label,
                                marker_color=color, text=[duration_label(value)], textposition='inside',
                                hovertemplate=label + '：%{x:g} 分鐘<extra></extra>'))
    fig.update_layout(barmode='stack', height=180, paper_bgcolor='white', plot_bgcolor='white',
                      margin=dict(t=20, b=30, l=10, r=10), font=dict(color='#29475c'),
                      legend=dict(orientation='h', y=1.4), xaxis=dict(title='分鐘', rangemode='tozero'),
                      yaxis=dict(visible=False))
    return fig


def timeline_figure(session):
    """Plot supplied intervals only; null-ended records are point observations."""
    grouped = defaultdict(list)
    for stage in session.get('stages') or []:
        if stage.get('start_at'):
            grouped[stage['stage']].append(stage)
    if not grouped:
        return None, False
    fig = go.Figure()
    points_only = False
    start, end = session.get('start_at'), session.get('end_at')
    for name, rows in grouped.items():
        label, color = STAGES.get(name, ('零星睡眠' if name == 'nap' else '未分類', '#8174bb'))
        bounded = [r for r in rows if r.get('end_at') and number(r.get('duration_minutes')) is not None
                   and start and end and start <= r['start_at'] < r['end_at'] <= end
                   and r.get('quality_status', 'valid') == 'valid']
        if bounded:
            fig.add_trace(go.Bar(base=[datetime.fromisoformat(r['start_at']).astimezone(TZ).replace(tzinfo=None) for r in bounded],
                                x=[r['duration_minutes'] * 60000 for r in bounded], y=[label] * len(bounded),
                                orientation='h', marker_color=color, name=label,
                                hovertemplate=label + '<br>開始 %{base|%m/%d %H:%M}<br>時長 %{customdata:g} 分鐘<extra></extra>',
                                customdata=[r['duration_minutes'] for r in bounded]))
        unbounded = [r for r in rows if r not in bounded]
        if unbounded:
            points_only = True
            fig.add_trace(go.Scatter(x=[datetime.fromisoformat(r['start_at']).astimezone(TZ).replace(tzinfo=None) for r in unbounded],
                                    y=[label] * len(unbounded), mode='markers', name=label + '起點',
                                    marker=dict(color=color, size=10, symbol='diamond'),
                                    hovertemplate='%{x|%m/%d %H:%M}<br>' + label + '起點（結束時間未確認）<extra></extra>'))
    fig.update_layout(height=260, margin=dict(t=15, b=40, l=10, r=10), showlegend=False,
                      barmode='overlay', paper_bgcolor='white', plot_bgcolor='white',
                      xaxis=dict(type='date', title='台灣時間', tickformat='%m/%d\n%H:%M'))
    return fig, points_only


def sleep_vitals(session, physiology):
    if not session.get('start_at') or not session.get('end_at'):
        return
    lower, upper = datetime.fromisoformat(session['start_at']), datetime.fromisoformat(session['end_at'])
    rows = [r for r in physiology if lower <= measured(r) < upper]
    st.markdown('#### 睡眠時段的心率與血氧')
    for col, name, label in zip(st.columns(2), ['HR', 'SpO2'], ['心率', '血氧']):
        with col, st.container(border=True):
            st.markdown('**' + label + '**')
            group = latest_series(rows, name)
            if not group:
                st.caption('此睡眠時段沒有可用的' + label + '量測')
                continue
            values = [float(r['value']) for r in group]
            unit = group[-1].get('unit') or '單位未確認'
            cols = st.columns(3)
            for c, text, value in zip(cols, ['最低', '平均', '最高'], [min(values), sum(values) / len(values), max(values)]):
                c.metric(text, f'{value:g} {unit}')
            st.caption(source_label(group[-1]) + f' · {len(group)} 筆同來源／裝置／版本量測')


def period_trend(sessions):
    groups = defaultdict(list)
    for session in sessions:
        groups[(session.get('source'), session.get('device_external_id'), session.get('algorithm_version'))].append(session)
    fig = go.Figure()
    for index, rows in enumerate(groups.values()):
        rows.sort(key=lambda s: (s['sleep_date'], s.get('start_at') or ''))
        # Multiple sessions per day stay separate; no silent last-entry overwrite.
        fig.add_trace(go.Scatter(x=[s['sleep_date'] for s in rows],
                                y=[sleep_display_summary(s)['total_minutes'] for s in rows],
                                mode='lines+markers', name=source_label(rows[0]) + (f' · 系列 {index+1}' if len(groups) > 1 else ''),
                                connectgaps=False, line=dict(color=COLORS[index % len(COLORS)], width=2.5, shape='linear'),
                                marker=dict(size=7),
                                hovertemplate='%{x}<br>睡眠總時長 %{y:g} 分鐘<extra></extra>'))
    style_trend(fig)
    fig.update_xaxes(title_text='睡眠日期', tickformat='%m/%d', hoverformat='%Y/%m/%d')
    fig.update_yaxes(title_text='睡眠總時長（分鐘）')
    return fig


def sleep_view(sessions, diaries, physiology, research_details):
    st.subheader('睡眠分析')
    if not sessions:
        st.info('所選期間沒有睡眠紀錄，請調整日期或確認手錶是否已同步。')
        return
    dates = sorted({s['sleep_date'] for s in sessions}, reverse=True)
    day = st.selectbox('選擇睡眠日期', dates)
    candidates = sorted([s for s in sessions if s['sleep_date'] == day], key=lambda s: s.get('start_at') or '', reverse=True)
    index = st.selectbox('選擇睡眠紀錄', list(range(len(candidates))), format_func=lambda i: session_label(candidates[i]) + f' · 第 {i+1} 筆') if len(candidates) > 1 else 0
    selected = candidates[index]
    summary = sleep_display_summary(selected)
    st.caption(session_label(selected) + ' · 台灣時間')
    mode = st.radio('睡眠顯示方式', ['睡眠圖', '睡眠紀錄表'], horizontal=True)
    if mode == '睡眠紀錄表':
        frame = sleep_records_table(sessions)
        pages = (len(frame) + 49) // 50
        page = int(st.number_input('睡眠紀錄頁次', min_value=1, max_value=pages, value=1, step=1,
                                   key=f'sleep_table_page_{len(frame)}'))
        st.caption(f'查詢期間共 {len(frame)} 筆，第 {page}/{pages} 頁；每筆紀錄分別列出，不合併同日紀錄。')
        st.dataframe(frame.iloc[(page-1)*50:page*50], hide_index=True, width='stretch')
        export = frame.map(lambda value: "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value)
        st.download_button('下載睡眠紀錄 CSV', export.to_csv(index=False).encode('utf-8-sig'), 'sleep_records.csv', mime='text/csv')
    else:
        with st.container(border=True, key='sleep-platform-summary'):
            st.metric('睡眠總時數（TST）', duration_label(summary['total_minutes']))
            if summary['total_basis'] == 'platform_core_summary':
                st.caption('平台摘要：淺睡＋深睡＋REM，與 DocterCloud 睡眠總時數一致；清醒與零星睡眠另列。')
            elif summary['total_minutes'] is None:
                st.caption('來源未提供可確認的睡眠總時數；不把缺少的階段補成零。')
            else:
                st.caption('使用已確認的睡眠總時數；清醒不計入睡眠。')
            st.divider()
            for col, key in zip(st.columns(4), ['deep', 'light', 'rem', 'awake']):
                col.metric(STAGES[key][0] + ('時間' if key == 'awake' else ''), duration_label(summary[key]))
            other = number(selected.get('other_sleep_minutes'))
            if other is not None:
                st.caption('零星／其他已確認睡眠：' + duration_label(other))
        if any(summary[key] is not None for key in STAGES):
            st.plotly_chart(summary_bar(summary), key='sleep-duration-distribution', width='stretch')
            st.caption('各階段時長分布；清醒另列，這張圖不代表各階段的發生順序。')
        timeline, has_unbounded = timeline_figure(selected)
        if timeline is not None:
            st.markdown('#### 睡眠階段時間軸')
            st.plotly_chart(timeline, key='sleep-platform-timeline', width='stretch')
            if has_unbounded:
                st.caption('菱形是來源記錄的階段起點；來源未確認區段結束時間時，不補推區段長度或 WASO。')
        sleep_vitals(selected, physiology)
        if len(sessions) > 1:
            with st.expander('查詢期間的睡眠趨勢'):
                from .observation_views import sleep_duration_bars
                presentation = st.radio('期間呈現', ['每筆時長', '折線圖'], horizontal=True, key='sleep-period-presentation')
                st.caption('每根長條代表一筆睡眠紀錄；同日多筆分開呈現，不加總。未提供時長的紀錄會註明。' if presentation == '每筆時長'
                           else '線連接相鄰睡眠紀錄；同日多筆保留，沒有紀錄的日期不代表零小時。')
                tools = chart_tools('sleep-period')
                fig = sleep_duration_bars(sessions) if presentation == '每筆時長' else period_trend(sessions)
                render_trend(fig, key='sleep-period-trend', tools=tools)
    with st.expander('進階研究指標：WASO、SOL、睡眠效率與日誌對照'):
        st.caption('平台清醒時間是整段紀錄的 awake；WASO 僅計首次入睡至最後醒來之間的清醒，需要足夠的分期資訊確認。')
        matching = [r for r in diaries if r.get('date_definition') == 'wake_date' and r['date'] == selected['sleep_date']]
        if len(matching) > 1:
            st.warning('同日有多筆日誌，未自動配對；請在研究比較核對。')
        research_details(selected, matching[0] if len(matching) == 1 else {}, physiology)
