"""Chart changes must preserve missing data, original values and series boundaries."""
from copy import deepcopy

from nsysu.charts import metric_figures
from nsysu.dashboard_summary import trend_figure
from nsysu.chart_style import color_for


def row(value, when='2026-10-18T07:00:00+08:00', **extra):
    return dict(metric='HR', value=value, measured_at=when, source='SYNTHETIC', unit='bpm',
                signal_type='PPG', device_external_id='watch', algorithm_version='v1', **extra)


def test_summary_line_retains_explicit_missing_boundaries_and_zero():
    data = [row(60), row(None, '2026-10-18T08:00:00+08:00'), row(0, '2026-10-18T09:00:00+08:00')]
    data += [row(float('nan'), '2026-10-18T10:00:00+08:00')]
    fig = trend_figure(data, ['HR'])
    assert list(fig.data[0].y) == [60, None, 0, None]
    assert fig.data[0].connectgaps is False and fig.data[0].line.shape == 'linear'


def test_normalized_tooltip_keeps_original_values_even_at_duplicate_times():
    data = [row(60), row(80), row(None, '2026-10-18T08:00:00+08:00')]
    original = deepcopy(data)
    fig = metric_figures(data, ['HR'], '標準化比較', 'Min-Max')[0]
    assert list(fig.data[0].y) == [0, 1, None]
    assert [v[0] for v in fig.data[0].customdata] == [60, 80, None]
    assert '原始值' in fig.data[0].hovertemplate and data == original


def test_chart_order_uses_absolute_time_and_separates_algorithm_versions():
    data = [row(80, '2026-10-18T00:00:00Z'), row(60)]
    fig = metric_figures(data, ['HR'])[0]
    assert list(fig.data[0].y) == [60, 80]
    other = dict(data[0], algorithm_version='v2')
    assert len(metric_figures(data + [other], ['HR'])) == 2


def test_metric_color_stays_fixed_across_selection_order_and_chart_type():
    data = [row(60), dict(row(40), metric='SDNN', unit='ms')]
    single = metric_figures(data, ['HR'])[0].data[0]
    combined = metric_figures(data[::-1], ['SDNN', 'HR'], '標準化比較')[0]
    assert single.line.color == color_for('HR')
    assert next(t for t in combined.data if t.name == '心率').line.color == single.line.color
    assert trend_figure(data, ['HR']).data[0].line.color == single.line.color


def test_dual_axes_keep_units_and_readable_names():
    data = [row(60), dict(row(40), metric='SDNN', unit='ms')]
    fig = metric_figures(data, ['HR', 'SDNN'], '雙 Y 軸比較')[0]
    assert fig.data[0].yaxis == 'y' and fig.data[1].yaxis == 'y2'
    assert 'bpm' in fig.layout.yaxis.title.text and 'ms' in fig.layout.yaxis2.title.text
    assert fig.layout.hovermode == 'x unified' and fig.layout.xaxis.nticks == 4
