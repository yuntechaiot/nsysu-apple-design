"""Readable Apple-style chart presentation; research values are never smoothed."""
from html import escape
from datetime import datetime

NAMES = {
    'HR': '心率', 'SBP': '收縮壓', 'DBP': '舒張壓', 'SpO2': '血氧', 'Temperature': '體溫',
    'SDNN': '心率變異 SDNN', 'RMSSD': '心率變異 RMSSD', 'TP': '總功率 TP',
    'VLF': '極低頻 VLF', 'LF': '低頻 LF', 'HF': '高頻 HF', 'LF/HF': '低頻／高頻 LF/HF',
    'stress': '壓力指數', 'fatigue': '疲倦指數', 'StressTolerance': '抗壓能力', 'Adaptability': '調適能力',
    'Steps': '步數', 'Calories': '熱量', 'RRI': '心搏間期 RRI', 'Weight': '體重',
    'Glucose': '血糖', 'Cholesterol': '膽固醇', 'UricAcid': '尿酸', 'UrineOutput': '排尿量',
    'WaterIntake': '飲水量', 'HeartIndex': '心臟指數', 'VascularIndex': '血管彈性指數',
    'ActivitySteps': '活動步數', 'ActivityDistance': '活動距離', 'StaticTime': '靜止時間',
    'ActiveTime': '活動時間', 'StaticCalories': '靜止熱量', 'ActiveCalories': '活動熱量',
    'SportSteps': '運動步數', 'SportCalories': '運動熱量', 'SportDuration': '運動時長',
    'SportMaxHR': '運動最高心率', 'SportAvgHR': '運動平均心率', 'SportDistance': '運動距離',
}

COLORS = ['#0071e3', '#8754c8', '#008477', '#ba641c', '#b54582', '#52667e']
# A metric keeps its color when the user changes the selection/order.
COLOR_MAP = dict(zip(['HR', 'RMSSD', 'SDNN', 'TP', 'LF/HF', 'fatigue'], COLORS))
COLOR_MAP.update(SBP=COLORS[0], DBP=COLORS[1], SpO2=COLORS[2], Temperature=COLORS[3], stress=COLORS[4])


def color_for(name):
    return COLOR_MAP.get(name, COLORS[sum(name.encode('utf-8')) % len(COLORS)])


def label_for(name):
    return NAMES.get(name, name)


def style_trend(fig, title=None, height=360):
    """Keep data linear; make touch inspection easy without stealing vertical scrolling."""
    times = [datetime.fromisoformat(str(x)) for trace in fig.data for x in trace.x]
    daily = bool(times and (max(times) - min(times)).total_seconds() > 2 * 86400)
    date_format = '%Y/%m/%d' if times and min(times).year != max(times).year else '%m/%d'
    fig.update_layout(
        height=height, autosize=True, template='plotly_white',
        margin=dict(t=52 if title else 24, b=100 if len(fig.data) > 1 else 60, l=12, r=12),
        title=dict(text=escape(title) if title else None, x=0, xanchor='left', font=dict(size=17)),
        paper_bgcolor='white', plot_bgcolor='white',
        font=dict(family='-apple-system, BlinkMacSystemFont, PingFang TC, sans-serif', size=13, color='#505968'),
        hovermode='x unified', hoverdistance=40, spikedistance=-1,
        hoverlabel=dict(bgcolor='#ffffff', bordercolor='#dfe5ed', font=dict(size=13, color='#1d1d1f'), namelength=-1),
        dragmode=False, transition=dict(duration=0),
        showlegend=len(fig.data) > 1,
        legend=dict(orientation='h', x=0, xanchor='left', y=-.28, yanchor='top',
                    font=dict(size=12), bgcolor='rgba(0,0,0,0)', itemclick='toggle', itemdoubleclick='toggleothers'),
    )
    fig.update_xaxes(
        title_text='日期／時間（台灣）', title_font=dict(size=12), type='date',
        nticks=4, tickformat=date_format if daily else '%m/%d<br>%H:%M', hoverformat='%Y/%m/%d %H:%M:%S',
        showgrid=False, zeroline=False, automargin=True,
        rangeslider=dict(visible=False), showspikes=True, spikemode='across',
        spikesnap='cursor', spikecolor='#9aa9bc', spikethickness=1, spikedash='dot',
    )
    fig.update_yaxes(gridcolor='#edf0f4', zeroline=False, nticks=5, automargin=True,
                     title_font=dict(size=12), tickfont=dict(size=12), fixedrange=True)
    return fig


CHART_CONFIG = {'displayModeBar': False, 'scrollZoom': False, 'responsive': True}
CHART_HELP = '點按資料點查看時間與數值；點圖例可隱藏／顯示系列。缺值保持中斷，不補零、不平滑。'


def chart_tools(key):
    import streamlit as st
    return st.toggle('縮放工具', key=key + '-tools',
                     help='開啟後可框選放大、拖動日期範圍，並使用工具列重設或下載圖表。關閉時方便手機上下捲動。')


def render_trend(fig, key, tools=False):
    import streamlit as st
    if tools:
        fig.update_layout(dragmode='zoom', height=420)
        fig.update_xaxes(rangeslider=dict(visible=True, thickness=.1))
        fig.update_yaxes(fixedrange=False)
    st.plotly_chart(fig, key=key, width='stretch', config={**CHART_CONFIG, 'displayModeBar': tools})
