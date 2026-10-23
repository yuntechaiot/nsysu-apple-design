"""Native Streamlit dashboard, preserving the supplied platform login."""
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .charts import metric_figures
from .sleep import TZ, sleep_metrics, stage_percent, duration_label, clock_label
from .store import Store
from .dashboard_summary import NAMES

LABELS = {"light": "淺睡", "deep": "深睡", "rem": "REM", "other_sleep": "其他已確認睡眠"}
BOOLS = {"全部": "all", "是": True, "否": False, "未填／不確定": None}


def filter_diaries(rows, filters):
    return [r for r in rows if all(choice == "all" or r.get(key) is choice for key, choice in filters.items())]


def objective_view(sessions, diaries, physiology=None):
    from .sleep_view import sleep_view
    sleep_view(sessions, diaries, physiology or [], _research_sleep_details)


def _research_sleep_details(selected, diary, physiology=None):
    metrics = sleep_metrics(diary, selected)
    provenance = selected.get("metric_provenance") or {}
    tst_source = "系統計算：完整睡眠分期" if provenance.get("tst_minutes") in ("complete_stage_timeline", "explicit_complete_summary") else "來源提供的原始 TST" if selected.get('tst_minutes') is not None else "尚缺可確認的完整分期或原始研究 TST；平台摘要已在主區顯示"
    waso_source = "系統計算：首次入睡至最後醒來的清醒" if provenance.get("waso_minutes") == "bounded_awake_timeline" else "來源提供的 WASO" if selected.get('waso_minutes') is not None else "尚缺足夠的分期起訖；平台清醒時間已在主區顯示"
    cols = st.columns(4)
    for col, (title, value, source) in zip(cols, [
        ("已確認睡眠時長（研究 TST）", duration_label(selected.get("tst_minutes")), tst_source),
        ("入睡所需時間（客觀 SOL）", duration_label(metrics["sol_minutes"]), "手錶入睡－日誌關燈；系統計算"),
        ("睡中清醒時間（WASO）", duration_label(selected.get("waso_minutes")), waso_source),
        ("睡眠效率（SE）", f"{metrics['se_percent']:.2f}%" if metrics["se_percent"] is not None else "暫無資料", "TST／日誌 TIB；系統計算")]):
        col.metric(title, value)
        col.caption(source)
    cols = st.columns(4)
    cols[0].metric("實際入睡", clock_label(selected.get("sleep_onset_at")))
    cols[1].metric("最後醒來", clock_label(selected.get("final_wake_at")))
    cols[2].metric("夜間醒來次數", selected.get("awakening_count") if selected.get("awakening_count") is not None else "暫無資料")
    cols[3].metric("日誌主觀 SOL", duration_label(diary.get("sleep_onset_min")))
    st.caption("所有時刻採 Asia/Taipei 24 小時制；平台 awake 另保留，不直接視為 WASO。分期比例分母為 TST；清醒不加入睡眠比例。")
    stages = []
    for stage, label in LABELS.items():
        minutes = selected.get(stage + "_minutes")
        percent = stage_percent(minutes, selected.get("tst_minutes"))
        stage_source = "暫無資料" if minutes is None else "系統計算：完整分期" if provenance.get(stage + "_minutes") == "complete_stage_timeline" else selected["source"]
        stages.append({"階段": label, "時長": duration_label(minutes), "TST 比例": f"{percent:.2f}%" if percent is not None else "暫無資料", "來源": stage_source, "minutes": minutes})
    st.dataframe(pd.DataFrame(stages).drop(columns="minutes"), hide_index=True)
    available = [s for s in stages if s["minutes"] is not None]
    if available:
        st.plotly_chart(go.Figure(go.Bar(x=[s["階段"] for s in available], y=[s["minutes"] for s in available], marker_color="#7F77DD")).update_layout(yaxis_title="分鐘", title="已提供的睡眠分期（缺值不補零）"), width="stretch", config={'responsive': True})
    # A pie implies 100%; show one only when complete and consistent with TST.
    total = selected.get("tst_minutes")
    if total and len(available) == 4 and abs(sum(s["minutes"] for s in available) - total) < 0.01:
        st.plotly_chart(go.Figure(go.Pie(labels=[s["階段"] for s in available], values=[s["minutes"] for s in available], hole=.6)).update_layout(title="睡眠分期比例（分母 TST）"), width="stretch", config={'responsive': True})
    elif total is not None:
        unclassified = total - sum(s["minutes"] for s in available)
        st.caption(f"未分類／未提供分期：{duration_label(unclassified) if unclassified >= 0 else '來源加總不一致'}；不強迫比例為 100%。")
    timeline = selected.get("stages")
    if timeline is None and st.session_state.get("supabase_session"):
        timeline = Store(st.session_state.supabase_session["access_token"]).rows("sleep_stage_records", session_id="eq." + selected["id"])
    if timeline:
        fig = go.Figure()
        for stage in timeline:
            if stage.get("start_at") and stage.get("end_at") and stage.get("duration_minutes") is not None:
                dt = datetime.fromisoformat(stage["start_at"]).astimezone(TZ).replace(tzinfo=None)
                label = {**LABELS, 'awake': '清醒', 'unknown': '未分類'}.get(stage['stage'], stage['stage'])
                fig.add_trace(go.Bar(base=[dt], x=[stage["duration_minutes"] * 60000], y=[label], orientation="h", name=label))
        fig.update_layout(title="原始睡眠分期時間軸", xaxis=dict(type="date", tickformat="%m/%d %H:%M"), showlegend=False)
        st.plotly_chart(fig, width="stretch", config={'responsive': True})
        usable = [s for s in timeline if s.get("start_at") and s.get("end_at")]
        if usable:
            choices = {f"{i+1}. {s['stage']} {clock_label(s['start_at'])}–{clock_label(s['end_at'])}": s for i, s in enumerate(usable)}
            selected_stage = choices[st.selectbox("睡眠區段生理對照", list(choices))]
            lower, upper = datetime.fromisoformat(selected_stage["start_at"]), datetime.fromisoformat(selected_stage["end_at"])
            segment = [m for m in (physiology or []) if lower <= datetime.fromisoformat(m["measured_at"]) < upper]
            st.caption(f"區段：{selected_stage['start_at']} 至 {selected_stage['end_at']}。以下使用實際落在此區段內的量測，不補值。")
            if segment:
                groups: dict = {}
                for record in segment:
                    key = (record["metric"], record.get("source"), record.get("unit"), record.get("device_external_id"))
                    groups.setdefault(key, []).append(record["value"])
                st.dataframe(pd.DataFrame([{"指標": k[0], "來源": k[1], "單位": k[2] or "未確認", "裝置": k[3] or "未提供", "區段平均": sum(values)/len(values), "實際筆數": len(values)} for k, values in groups.items()]), hide_index=True)
                for index, fig in enumerate(metric_figures(segment, ["HR", "SBP", "DBP"])):
                    st.plotly_chart(fig, key=f"sleep-segment-{index}", width="stretch", config={'responsive': True})
            else:
                st.info("此分期區段沒有可用生理資料")


def physiology_view(metrics):
    from .chart_style import CHART_HELP, chart_tools, render_trend
    st.subheader("HRV／生理指標")
    st.caption("ECG：ECG-derived HRV；PPG：PPG-derived PRV。DocterCloud 文件未確認訊號與功率單位，依來源顯示未確認，保留原始數值。")
    st.caption(CHART_HELP)
    tools = chart_tools('physiology')
    mode = st.radio("圖表模式", ["獨立圖表", "雙 Y 軸比較", "標準化比較"], horizontal=True)
    names = ["HR", "RMSSD", "SDNN", "TP", "VLF", "LF", "HF", "LF/HF", "stress", "fatigue", "SBP", "DBP", "SpO2", "Temperature"]
    names += sorted({m['metric'] for m in metrics} - set(names))
    selected = st.multiselect("顯示指標", names, format_func=lambda n: NAMES.get(n, n), default=[n for n in ("HR", "RMSSD", "SDNN", "LF/HF") if any(m["metric"] == n for m in metrics)])
    method = st.selectbox("標準化方法", ["Z-score", "Min-Max"]) if mode == "標準化比較" else "Z-score"
    if mode == "雙 Y 軸比較" and len(selected) != 2:
        st.info("請選擇兩個指標；左右 Y 軸各使用自己的單位。")
        return
    try:
        figures = metric_figures(metrics, selected, mode, method)
        for index, fig in enumerate(figures):
            render_trend(fig, key=f"physiology-{index}", tools=tools)
        if not figures:
            st.info("暫無資料")
    except ValueError as error:
        st.warning(str(error))


def stress_view(metrics):
    from .chart_style import chart_tools
    from .observation_views import presentation_control, render_observations
    from .dashboard_summary import series_key, valid_rows
    st.subheader("壓力與疲倦")
    st.caption("第三方平台值供研究分析；原文件未定義高低方向、正常範圍與量尺，因此不作診斷或預設 0–100。")
    for name, label in (("stress", "Stress Index 壓力指數"), ("fatigue", "Fatigue Index 疲倦指數")):
        groups: dict = {}
        for metric in valid_rows(metrics, [name]):
            if metric["metric"] == name:
                groups.setdefault((metric.get("source"), metric.get("unit"), metric.get("device_external_id"), metric.get("algorithm_version")), []).append(metric)
        if not groups:
            st.metric(label, "暫無資料")
        for (source, unit, device, version), rows in groups.items():
            rows.sort(key=lambda r: r["measured_at"])
            newest = rows[-1]
            delta = newest["value"] - rows[-2]["value"] if len(rows) > 1 else None
            st.metric(label, f"{newest['value']:g}", delta=f"較前次 {delta:+g}" if delta is not None else None, delta_color="off")
            st.caption(f"來源 {source}｜裝置 {device or '未提供'}｜量尺 {unit or '未確認'}｜量測 {newest['measured_at']}｜版本 {version}")
    presentation = presentation_control('stress')
    tools = chart_tools('stress')
    series: dict = {}
    for metric in metrics:
        if metric['metric'] in {'stress', 'fatigue'}:
            series.setdefault(series_key(metric), []).append(metric)
    for index, rows in enumerate(series.values()):
        st.markdown('**' + NAMES[rows[0]['metric']] + '**')
        render_observations(rows, [rows[0]['metric']], key=f'stress-fatigue-{index}', presentation=presentation, tools=tools)


def main():
    from .dashboard_flow import main as flow_main
    flow_main()


if __name__ == "__main__":
    main()
