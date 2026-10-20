"""Presentation-only transformations; every metric/source/unit keeps its own axis."""
import math
import statistics
from collections import defaultdict
from html import escape

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .sleep import TZ
from .chart_style import color_for, label_for, style_trend
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
            key = (record["metric"], record.get("source", "DocterCloud"), record.get("unit") or "單位未確認", record.get("signal_type", "unknown"), record.get("device_external_id"), record.get('algorithm_version'))
            value = record.get("value")
            groups[key].append((record["measured_at"], float(value) if value is not None and math.isfinite(float(value)) else None))
    figures: list = []
    if not groups:
        return figures
    keys = list(groups)
    if mode == "雙 Y 軸比較" and len(keys) != 2:
        raise ValueError("雙 Y 軸需要恰好兩個資料系列；請縮小來源、裝置或版本範圍。左右軸各保留原單位。")
    combined = make_subplots(specs=[[{"secondary_y": True}]]) if mode == "雙 Y 軸比較" else go.Figure()
    for index, key in enumerate(keys):
        name, source, unit, signal, device, version = key
        label = label_for(name)
        if sum(k[0] == name for k in keys) > 1:
            label += f' · 系列 {index + 1}'
        def local_time(value):
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return (parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)).replace(tzinfo=None)
        points = sorted(groups[key], key=lambda p: local_time(p[0]))
        originals = points
        values = [p[1] for p in originals]
        if mode == "標準化比較":
            values = normalize(values, method)
        # Sample indexes so same-time observations retain their own original value.
        points = extrema_sample(list(enumerate(values)))
        # Plot naive Taipei wall time so browser timezone cannot reinterpret dates.
        x = [local_time(originals[p[0]][0]) for p in points]
        y = [p[1] for p in points]
        origin = {"PPG": "PPG-derived PRV", "ECG": "ECG-derived HRV"}.get(signal, "訊號來源未確認")
        details = '<br>'.join(escape(str(v)) for v in (source or '來源未提供', device or '裝置未提供', origin, '版本 ' + str(version or '未提供')))
        trace = go.Scatter(x=x, y=y, name=label, mode="lines+markers", connectgaps=False,
                           line=dict(color=color_for(name), width=2.5, shape='linear', dash=['solid', 'dash', 'dot'][index % 3]),
                           marker=dict(size=5 if len(points) > 60 else 7),
                           customdata=[[originals[p[0]][1]] for p in points],
                           hovertemplate='<b>' + escape(label) + '</b> · %{y:,.3~f} ' +
                           (escape(method) + '<br>原始值 %{customdata[0]} ' if mode == '標準化比較' else '') +
                           escape(unit) + '<br>' + details + '<extra></extra>')
        if mode == "獨立圖表":
            fig = go.Figure(trace)
            style_trend(fig, title=label)
            fig.update_yaxes(title=unit, autorange=True, rangemode="normal")
            figures.append(fig)
        elif mode == "雙 Y 軸比較":
            combined.add_trace(trace, secondary_y=bool(index))
            combined.update_yaxes(title_text=label + ' (' + unit + ')', secondary_y=bool(index), autorange=True,
                                  color=color_for(name))
        else:
            combined.add_trace(trace)
    if mode != "獨立圖表":
        if mode == "標準化比較":
            combined.update_yaxes(title=method + "（僅視覺化）")
        figures.append(combined)
    for fig in figures:
        if mode != '獨立圖表':
            style_trend(fig)
    return figures
