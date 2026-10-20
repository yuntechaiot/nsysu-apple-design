"""Choose a view for the observation pattern, without changing source measurements."""
from collections import Counter, defaultdict
from datetime import datetime, time
from html import escape
import statistics

import plotly.graph_objects as go

from .chart_style import color_for, label_for, render_trend, style_trend
from .dashboard_summary import measured, series_key, source_label, trend_figure, unit_label, valid_rows
from .sleep import duration_label, sleep_display_summary

PRESENTATIONS = ['建議呈現', '原始點位', '每日範圍', '折線圖']
# Cumulative counters and amounts stay as observations: do not invent daily totals.
RANGE_METRICS = {'HR', 'SpO2', 'Temperature', 'SDNN', 'RMSSD', 'TP', 'VLF', 'LF', 'HF', 'LF/HF',
                 'stress', 'fatigue', 'StressTolerance', 'Adaptability', 'RRI', 'Weight', 'Glucose',
                 'Cholesterol', 'UricAcid', 'HeartIndex', 'VascularIndex'}


def daily_buckets(metrics, names):
    groups: dict = defaultdict(lambda: defaultdict(list))
    for row in valid_rows(metrics, names):
        groups[series_key(row)][measured(row).date()].append(row)
    return groups


def recommended_view(metrics, names):
    rows = valid_rows(metrics, names)
    if set(names) == {'SBP', 'DBP'} and {r['metric'] for r in rows} == {'SBP', 'DBP'} and all(r.get('unit') == 'mmHg' for r in rows):
        return '血壓配對'
    buckets = daily_buckets(rows, names)
    # Prefer range summaries only when repeated measurements exist across several days.
    if set(names) <= RANGE_METRICS and any(
            len(days) >= 3 and sum(len(values) for values in days.values()) >= 12
            and sum(len(values) >= 2 for values in days.values()) >= 3 for days in buckets.values()):
        return '每日範圍'
    return '原始點位'


def raw_points_figure(metrics, names):
    fig = trend_figure(metrics, names)
    fig.update_traces(mode='markers', marker=dict(size=8, opacity=.78))
    fig.update_layout(hovermode='closest')
    # Closest-point inspection needs its own timestamp, unlike unified line hover.
    for trace in fig.data:
        trace.hovertemplate = '%{x|%Y/%m/%d %H:%M:%S}<br>' + trace.hovertemplate
    return fig


def daily_range_figure(metrics, names):
    groups = daily_buckets(metrics, names)
    units = {key[2] for key in groups}
    if len(units) > 1:
        raise ValueError('每日範圍須使用相同單位；請分開查看不同單位的量測。')
    fig = go.Figure()
    for index, (key, days) in enumerate(groups.items()):
        name, source, unit, signal, device, version = key
        x, middle, lower, upper, details = [], [], [], [], []
        for day, rows in sorted(days.items()):
            values = [float(r['value']) for r in rows]
            median = statistics.median(values)
            x.append(datetime.combine(day, time.min))
            middle.append(median)
            lower.append(median - min(values))
            upper.append(max(values) - median)
            details.append([min(values), max(values), len(values), escape(source_label(rows[0])),
                            escape(str(version or '未提供'))])
        color = color_for(name)
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        label = label_for(name)
        if sum(k[0] == name for k in groups) > 1:
            label += f' · 系列 {index + 1}'
        fig.add_trace(go.Scatter(
            x=x, y=middle, name=label, mode='markers', customdata=details,
            marker=dict(size=10, color=color),
            error_y=dict(type='data', symmetric=False, array=upper, arrayminus=lower,
                         thickness=5, width=6, color=f'rgba({r},{g},{b},0.35)'),
            hovertemplate='<b>' + escape(label) + '</b><br>每日中位數 %{y:,.3~f} ' + escape(unit_label(unit)) +
                          '<br>最低 %{customdata[0]:,.3~f} · 最高 %{customdata[1]:,.3~f}' +
                          '<br>量測 %{customdata[2]} 筆<br>%{customdata[3]}<br>版本 %{customdata[4]}<extra></extra>',
        ))
    style_trend(fig)
    fig.update_xaxes(title_text='量測日期（台灣）', tickformat='%m/%d', hoverformat='%Y/%m/%d')
    fig.update_yaxes(title_text=unit_label(next(iter(units))) if units else '數值')
    return fig


def paired_pressure_figure(metrics):
    rows = valid_rows(metrics, ['SBP', 'DBP'])
    rows = [r for r in rows if r.get('unit') == 'mmHg']
    fig = raw_points_figure(rows, ['SBP', 'DBP'])
    pairs: dict = defaultdict(lambda: defaultdict(list))
    for row in rows:
        key = (measured(row), row.get('source'), row.get('device_external_id'), row.get('signal_type'),
               row.get('algorithm_version'), row.get('external_record_id'))
        pairs[key][row['metric']].append(row)
    x, y = [], []
    for key, pair in pairs.items():
        if set(pair) != {'SBP', 'DBP'} or any(len(v) != 1 for v in pair.values()):
            continue
        when = key[0].replace(tzinfo=None)
        x.extend([when, when, None])
        y.extend([pair['DBP'][0]['value'], pair['SBP'][0]['value'], None])
    if x:
        connector = go.Scatter(x=x, y=y, mode='lines', line=dict(color='#cbd3df', width=2),
                               hoverinfo='skip', showlegend=False, name='同次量測')
        fig = go.Figure(data=[connector, *fig.data], layout=fig.layout)
    fig.update_yaxes(title_text='血壓（mmHg）')
    fig.update_layout(showlegend=True)
    return fig


def observation_figure(metrics, names, presentation='建議呈現'):
    chosen = recommended_view(metrics, names) if presentation == '建議呈現' else presentation
    if chosen == '每日範圍':
        fig = daily_range_figure(metrics, names)
        description = '每日範圍｜圓點＝中位數，直條＝最低至最高。這是量測分布，不是正常範圍。'
    elif chosen == '血壓配對':
        fig = paired_pressure_figure(metrics)
        description = '血壓配對｜藍＝收縮壓，紫＝舒張壓；細線連接同次量測，未配對資料保留單點。'
    elif chosen == '折線圖':
        fig = trend_figure(metrics, names)
        description = '折線圖｜線連接相鄰觀察值，不代表中間持續量測；明確缺值保留斷線。'
    else:
        fig = raw_points_figure(metrics, names)
        description = '原始點位｜每點一筆量測，保留實際時間；不連線推測兩次之間的變化。'
    return fig, description


def presentation_control(key):
    import streamlit as st
    return st.selectbox('圖表呈現', PRESENTATIONS, key=key + '-presentation',
                        help='依目前查詢結果選圖。每日範圍以各來源／裝置／訊號／版本分開計算，只統計已取得的量測，不代表完整全天或正常範圍。')


def render_observations(metrics, names, key, presentation='建議呈現', tools=False):
    import streamlit as st
    if not valid_rows(metrics, names):
        st.info('此資料系列沒有有效量測值；可在量測表或原始資料核對。')
        return
    fig, description = observation_figure(metrics, names, presentation)
    st.caption(description)
    if recommended_view(metrics, names) == '每日範圍' or presentation == '每日範圍':
        groups = daily_buckets(metrics, names)
        count = sum(len(rows) for days in groups.values() for rows in days.values())
        days = {day for values in groups.values() for day in values}
        st.caption(f'{count} 筆有效量測 · {len(days)} 日有紀錄 · 空白日不補值')
    render_trend(fig, key=key, tools=tools)


def sleep_duration_bars(sessions):
    rows = sorted(sessions, key=lambda s: (s['sleep_date'], s.get('start_at') or ''))
    counts = Counter(r['sleep_date'] for r in rows)
    seen: dict = defaultdict(int)
    labels, values, details = [], [], []
    for row in rows:
        day = row['sleep_date']
        seen[day] += 1
        label = day + (f'<br>第 {seen[day]} 筆' if counts[day] > 1 else '')
        minutes = sleep_display_summary(row)['total_minutes']
        labels.append(label)
        values.append(minutes / 60 if minutes is not None else None)
        details.append([duration_label(minutes), escape(source_label(row)), escape(str(row.get('external_session_id') or '未提供'))])
    # Style with true dates first, then use one categorical slot per source record.
    fig = go.Figure(go.Bar(x=[r['sleep_date'] for r in rows], y=values, name='睡眠時長',
                          marker=dict(color='#0071e3', cornerradius=5), customdata=details,
                          hovertemplate='%{x}<br><b>%{customdata[0]}</b><br>%{customdata[1]}<br>紀錄 %{customdata[2]}<extra></extra>'))
    style_trend(fig)
    fig.update_traces(x=labels)
    fig.update_layout(hovermode='closest', bargap=.35)
    ticks = labels[::max(1, (len(labels) + 3) // 4)]
    multiple_years = len({r['sleep_date'][:4] for r in rows}) > 1
    fig.update_xaxes(type='category', title_text='睡眠紀錄（同日多筆分開）', tickmode='array',
                     tickvals=ticks, ticktext=[(label if multiple_years else label[5:]).replace('-', '/') for label in ticks])
    fig.update_yaxes(title_text='睡眠時長（小時）', rangemode='tozero')
    for label, value in zip(labels, values):
        if value is None:
            fig.add_annotation(x=label, y=0, text='未提供', yshift=12, showarrow=False,
                               font=dict(size=11, color='#626772'))
    return fig
