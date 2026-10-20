"""Presentation-only transformations; every metric/source/unit keeps its own axis."""
import math
import statistics
from collections import defaultdict

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .sleep import TZ
from datetime import datetime


def normalize(values, method):
    valid = [v for v in values if v is not None and math.isfinite(v)]
    if not valid:
        return [None] * len(values)
    center = statistics.mean(valid) if method == "Z-score" else min(valid)
    scale = statistics.pstdev(valid) if method == "Z-score" else max(valid) - min(valid)
    return [None if v is None or not math.isfinite(v) else ((v - center) / scale if scale else 0.0) for v in values]


def extrema_sample(points, limit=1200):
    """Keep first/last and each bucket's min/max plus missing-value boundaries."""
    if len(points) <= limit:
        return points
    width = max(1, math.ceil(len(points) / max(1, (limit - 2) // 4)))
    indexes = {0, len(points) - 1}
    for start in range(0, len(points), width):
        valid = [(i, points[i][1]) for i in range(start, min(start + width, len(points))) if points[i][1] is not None]
        if valid:
            indexes.add(min(valid, key=lambda p: p[1])[0])
            indexes.add(max(valid, key=lambda p: p[1])[0])
        missing = [i for i in range(start, min(start + width, len(points))) if points[i][1] is None]
        if missing:
            indexes.update((missing[0], missing[-1]))
    return [points[i] for i in sorted(indexes)]


def metric_figures(records, selected, mode="獨立圖表", method="Z-score"):
    groups = defaultdict(list)
    for record in records:
        if record["metric"] in selected:
            key = (record["metric"], record.get("source", "DocterCloud"), record.get("unit") or "單位未確認", record.get("signal_type", "unknown"), record.get("device_external_id"))
            value = record.get("value")
            groups[key].append((record["measured_at"], value if value is not None and math.isfinite(float(value)) else None))
    figures: list = []
    if not groups:
        return figures
    keys = list(groups)
    if mode == "雙 Y 軸比較" and len(keys) != 2:
        raise ValueError("雙 Y 軸請選取兩個具有相同來源、裝置與單位的指標系列")
    combined = make_subplots(specs=[[{"secondary_y": True}]]) if mode == "雙 Y 軸比較" else go.Figure()
    for index, key in enumerate(keys):
        name, source, unit, signal, device = key
        label = f"{name} ({unit}) · {source} · {device or '裝置未提供'}"
        points = sorted(groups[key], key=lambda p: p[0])
        if mode == "標準化比較":
            values = normalize([p[1] for p in points], method)
            points = [(p[0], v) for p, v in zip(points, values)]
        points = extrema_sample(points)
        # Plot naive Taipei wall time so browser timezone cannot reinterpret dates.
        x = [datetime.fromisoformat(p[0]).astimezone(TZ).replace(tzinfo=None) for p in points]
        y = [p[1] for p in points]
        origin = {"PPG": "PPG-derived PRV", "ECG": "ECG-derived HRV"}.get(signal, "訊號來源未確認")
        trace = go.Scatter(x=x, y=y, name=label, mode="lines+markers", connectgaps=False,
                           hovertemplate=f"%{{x|%m/%d %H:%M}}<br>{label}<br>{origin}<br>%{{y:.3f}}<extra></extra>")
        if mode == "獨立圖表":
            fig = go.Figure(trace)
            fig.update_yaxes(title=label, autorange=True, rangemode="normal")
            figures.append(fig)
        elif mode == "雙 Y 軸比較":
            combined.add_trace(trace, secondary_y=bool(index))
            combined.update_yaxes(title_text=label, secondary_y=bool(index), autorange=True)
        else:
            combined.add_trace(trace)
    if mode != "獨立圖表":
        if mode == "標準化比較":
            combined.update_yaxes(title=method + "（僅視覺化）")
        figures.append(combined)
    for fig in figures:
        fig.update_layout(height=330, margin=dict(t=40, b=35), hovermode="x unified",
                          xaxis=dict(title="台灣時間（Asia/Taipei）", tickformat="%m/%d %H:%M", rangeslider=dict(visible=True)))
    return figures
