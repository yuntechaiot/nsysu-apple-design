"""Synthetic fixtures only; no platform sync or production writes."""
from datetime import datetime
import json

import pytest

from nsysu.sleep import TZ, sleep_metrics, stage_percent, duration_label
from nsysu.parsers import docter_sleep, docter_metrics, canonical_sleep, parse_sleep_file, timestamp
from nsysu.charts import normalize, metric_figures, extrema_sample
from nsysu.dashboard import filter_diaries
from nsysu.server import create_app
from nsysu.store import settings


def test_lights_not_bedtime_sol():
    diary = {"bedtime_at": "2026-10-17T22:30:00+08:00", "lights_out_at": "2026-10-17T23:45:00+08:00", "out_of_bed_at": "2026-10-18T07:15:00+08:00", "sleep_onset_min": 19}
    result = sleep_metrics(diary, {"sleep_onset_at": "2026-10-18T00:00:00+08:00", "tst_minutes": 390})
    assert result["sol_minutes"] == 15
    assert result["subjective_sol_minutes"] == 19
    assert result["tib_minutes"] == 525
    assert result["se_percent"] == pytest.approx(390 / 525 * 100)


def test_cross_midnight_twenty_minutes():
    result = sleep_metrics({"lights_out_at": "2026-10-17T23:50:00+08:00"}, {"sleep_onset_at": "2026-10-18T00:20:00+08:00"})
    assert result["sol_minutes"] == 30


def test_legacy_no_attempt_no_objective_sol():
    result = sleep_metrics({"sleep_time": "22:30", "sleep_onset_min": 15}, {"sleep_onset_at": "2026-10-18T00:00:00+08:00"})
    assert result["sol_minutes"] is None
    assert result["subjective_sol_minutes"] == 15
    assert result["tib_minutes"] is None


def test_required_percentages():
    assert round(stage_percent(200, 390), 2) == 51.28
    assert round(stage_percent(100, 390), 2) == 25.64
    assert round(stage_percent(90, 390), 2) == 23.08
    assert stage_percent(None, 390) is None
    assert stage_percent(0, 0) is None
    assert stage_percent(400, 390) is None


def test_duration_missing_and_zero():
    assert duration_label(390) == "6 小時 30 分鐘"
    assert duration_label(90) == "1 小時 30 分鐘"
    assert duration_label(None) == "暫無資料"
    assert duration_label(0) == "0 分鐘"


def epoch(hour, minute=0):
    return int(datetime(2026, 10, 18, hour, minute, tzinfo=TZ).timestamp())


def test_complete_staging_excludes_boundaries_from_waso():
    stages = [(0, epoch(0), epoch(0, 15)), (1, epoch(0, 15), epoch(1)), (0, epoch(1), epoch(1, 10)), (0, epoch(1, 10), epoch(1, 20)), (2, epoch(1, 20), epoch(2)), (0, epoch(2), epoch(2, 30))]
    parsed = docter_sleep({"id": 1, "start_time": epoch(0), "emd_time": epoch(2, 30), "detail_obj": [{"type": s, "start_time": a, "end_time": b} for s, a, b in stages]})
    assert parsed["tst_minutes"] == 85
    assert parsed["waso_minutes"] == 20
    assert parsed["awakening_count"] == 1
    assert parsed["light_minutes"] == 45
    assert parsed["rem_minutes"] == 0  # complete hypnogram establishes absence
    assert parsed["sleep_onset_at"].endswith("00:15:00+08:00")
    assert parsed["final_wake_at"].endswith("02:00:00+08:00")


def test_missing_staging_never_fills_zero_or_tst():
    parsed = docter_sleep({"start_time": epoch(0), "emd_time": epoch(7), "data": {"light": 200, "deep": 100, "REM": 90, "awake": 30}})
    assert parsed["tst_minutes"] is None
    assert parsed["waso_minutes"] is None
    assert parsed["awake_minutes"] == 30
    assert parsed["awakening_count"] is None


def test_partial_stages_not_normalized_to_hundred():
    raw = {"external_session_id": "SYNTHETIC", "start_at": "2026-10-18T00:00:00+08:00", "end_at": "2026-10-18T07:00:00+08:00", "tst_minutes": 390, "light_minutes": 200}
    result = canonical_sleep(raw)
    assert result["deep_minutes"] is None
    assert result["metric_provenance"]["light_percent"] == pytest.approx(51.28205128)
    assert result["metric_provenance"]["deep_percent"] is None


def test_unknown_stages_retained():
    parsed = docter_sleep({"start_time": epoch(0), "emd_time": epoch(7), "detail_obj": [{"type": 99, "start_time": epoch(0), "end_time": epoch(7)}]})
    assert parsed["stages"][0]["stage"] == "unclassified"
    assert parsed["tst_minutes"] is None


@pytest.mark.parametrize("details", [
    [{"type": 1, "start_time": epoch(0), "end_time": None}],
    [{"type": 1, "start_time": epoch(0), "end_time": epoch(2)}, {"type": 2, "start_time": epoch(1), "end_time": epoch(7)}],
    [{"type": 1, "start_time": epoch(0), "end_time": epoch(2)}, {"type": 2, "start_time": epoch(3), "end_time": epoch(7)}],
])
def test_open_overlap_gap_not_complete(details):
    result = docter_sleep({"start_time": epoch(0), "emd_time": epoch(7), "detail_obj": details})
    assert result["tst_minutes"] is None
    assert result["waso_minutes"] is None


def test_time_units_and_timezone_are_explicit():
    with pytest.raises(ValueError, match="UNIX 秒"):
        timestamp(epoch(7) * 1000, True)
    with pytest.raises(ValueError, match="時區"):
        timestamp("2026-10-18T07:00:00")
    assert timestamp("2026-10-17T23:00:00Z") == "2026-10-18T07:00:00+08:00"


def test_platform_stress_fatigue_no_assumed_scale():
    raw = [{"id": 8, "occur_time": epoch(7), "fatigue": 143, "data": {"mental_stress": 0, "sdnn": 37, "lf": 10, "hf": 2}}]
    rows = docter_metrics(raw)
    by_name = {m["metric"]: m for m in rows}
    assert by_name["fatigue"]["value"] == 143
    assert by_name["stress"]["value"] == 0
    assert by_name["stress"]["unit"] is None
    assert by_name["SDNN"]["signal_type"] == "unknown"
    assert by_name["LF/HF"]["value"] == 5
    assert by_name["LF/HF"]["raw_payload"] == raw[0]


def test_index_scale_does_not_silently_discard_signed_values():
    raw = [{"id": 9, "occur_time": epoch(7), "fatigue": -3, "data": {"mental_stress": -2}}]
    result = docter_metrics(raw)
    assert {m["metric"]: m["value"] for m in result} == {"fatigue": -3, "stress": -2}


def test_json_csv_reusable_and_invalid_adapter():
    raw = {"external_session_id": "test", "start_at": "2026-10-17T23:00:00+08:00", "end_at": "2026-10-18T07:00:00+08:00", "tst_minutes": 390}
    assert parse_sleep_file(json.dumps([raw]), "json", "canonical")[0]["tst_minutes"] == 390
    csv = ','.join(raw) + '\n' + ','.join(map(str, raw.values()))
    assert parse_sleep_file(csv, "csv", "canonical")[0]["tst_minutes"] == 390
    with pytest.raises(ValueError):
        parse_sleep_file(json.dumps([raw]), "json", "invented_api")


@pytest.mark.parametrize("bad", ["-5", "nan", "Infinity"])
def test_invalid_numeric_import_rejected(bad):
    with pytest.raises(ValueError):
        canonical_sleep({"external_session_id": "t", "start_at": "2026-10-18T00:00+08:00", "end_at": "2026-10-18T07:00+08:00", "tst_minutes": bad})


def test_three_state_filter_does_not_treat_false_as_null():
    rows = [{"wore_watch": False}, {"wore_watch": None}, {"wore_watch": True}]
    assert filter_diaries(rows, {"wore_watch": False}) == [rows[0]]
    assert filter_diaries(rows, {"wore_watch": None}) == [rows[1]]


def test_normalization_is_presentation_only():
    assert normalize([10, None, 20], "Min-Max") == [0, None, 1]
    assert normalize([5, 5], "Z-score") == [0, 0]
    raw = [{"metric": name, "value": v, "unit": unit, "measured_at": "2026-10-18T07:00:00+08:00"} for name, v, unit in [("TP", 9000, "ms²"), ("LF/HF", 1.2, "ratio")]]
    original = json.dumps(raw)
    assert len(metric_figures(raw, ["TP", "LF/HF"])) == 2
    dual = metric_figures(raw, ["TP", "LF/HF"], "雙 Y 軸比較")[0]
    assert dual.data[0].yaxis == "y"
    assert dual.data[1].yaxis == "y2"
    metric_figures(raw, ["TP", "LF/HF"], "標準化比較")
    assert json.dumps(raw) == original


def test_visual_downsample_keeps_global_extrema_and_missing():
    points = [(i, float(i % 50)) for i in range(10000)]
    points[789] = (789, 999999)
    points[481] = (481, -999999)
    points[500] = (500, None)
    sampled = extrema_sample(points)
    assert points[789] in sampled and points[481] in sampled and points[500] in sampled
    assert len(sampled) <= 1200


def test_server_runtime_config_and_auth_required():
    client = create_app().test_client()
    assert client.get('/').status_code == 200
    assert client.get('/api/config').json['supabase_url'] == 'https://ztsyxnrnemvcladbaaem.supabase.co'
    assert client.get('/web/core.js').status_code == 200
    assert client.post('/api/import', json={}).status_code == 401
    assert client.post('/api/sync', json={}).status_code == 401


def test_wrong_project_or_service_key_stops(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://oftpiqotjqjjsedvrwff.supabase.co')
    with pytest.raises(ValueError):
        settings()
    monkeypatch.delenv('SUPABASE_URL')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'sb_secret_unsafe')
    with pytest.raises(ValueError):
        settings()
