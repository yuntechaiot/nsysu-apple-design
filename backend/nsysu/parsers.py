"""Documented DocterCloud V5-4 adapter and explicit canonical CSV/JSON contract."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from datetime import datetime
from typing import Any

from .sleep import TZ, VERSION, number, stage_percent

STAGES = {0: "awake", 1: "light", 2: "deep", 3: "rem", 4: "nap"}


def index_number(value):
    """Proprietary stress/fatigue scales may be signed; only require finiteness."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def timestamp(value, epoch=False):
    if value is None or value == "":
        return None
    if epoch:
        numeric = number(value)
        if numeric is None or numeric > 10_000_000_000:
            raise ValueError("API 時間必須是 UNIX 秒；不自動猜測毫秒")
        return datetime.fromtimestamp(numeric, tz=TZ).isoformat()
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("匯入日期時間必須包含時區，例如 +08:00")
    return dt.astimezone(TZ).isoformat()


def docter_sleep(raw):
    start = timestamp(raw.get("start_time"), True)
    end = timestamp(raw.get("end_time", raw.get("emd_time")), True)
    if not start or not end or end <= start:
        raise ValueError("睡眠 Session 缺少有效起訖時間")
    summary = raw.get("data") or {}
    if not isinstance(summary, dict):
        raise ValueError("睡眠 data 必須是 JSON object")
    stages, issues = [], []
    for detail in raw.get("detail_obj") or []:
        ds, de = timestamp(detail.get("start_time"), True), timestamp(detail.get("end_time"), True)
        valid = bool(ds and de and start <= ds < de <= end)
        if not valid:
            issues.append("invalid_or_open_stage")
        stages.append({"stage": STAGES.get(detail.get("type"), "unclassified"),
                       "start_at": ds, "end_at": de,
                       "duration_minutes": (datetime.fromisoformat(de) - datetime.fromisoformat(ds)).total_seconds() / 60 if valid else None,
                       "raw_payload": detail, "quality_status": "valid" if valid else "needs_review"})
    ordered = sorted((s for s in stages if s["quality_status"] == "valid"), key=lambda s: s["start_at"])
    complete = bool(ordered and len(ordered) == len(stages) and ordered[0]["start_at"] == start
                    and ordered[-1]["end_at"] == end
                    and all(a["end_at"] == b["start_at"] for a, b in zip(ordered, ordered[1:]))
                    and all(s["stage"] != "unclassified" for s in ordered))
    if not complete:
        issues.append("incomplete_staging")
    durations = {}
    stage_provenance = {}
    for stage, key in (("light", "light"), ("deep", "deep"), ("rem", "REM"), ("nap", "napDuration")):
        direct = number(summary.get(key))
        from_stages = sum(s["duration_minutes"] for s in ordered if s["stage"] == stage)
        durations[stage] = direct if direct is not None else (from_stages if complete else None)
        stage_provenance[("other_sleep" if stage == "nap" else stage) + "_minutes"] = "platform_summary" if direct is not None else "complete_stage_timeline" if complete else "missing"
        if complete and direct is not None and abs(direct - from_stages) > 1:
            issues.append(f"{stage}_summary_mismatch")
    # Only a complete, bounded hypnogram can establish TST/WASO for this API.
    tst = sum(s["duration_minutes"] for s in ordered if s["stage"] in ("light", "deep", "rem", "nap")) if complete else None
    sleeping = [s for s in ordered if s["stage"] in ("light", "deep", "rem", "nap")]
    onset, final = (sleeping[0]["start_at"], sleeping[-1]["end_at"]) if complete and sleeping else (None, None)
    wakes = [s for s in ordered if s["stage"] == "awake" and onset and s["start_at"] >= onset and s["end_at"] <= final]
    count = sum(i == 0 or wakes[i - 1]["end_at"] != s["start_at"] for i, s in enumerate(wakes)) if complete and sleeping else None
    return {"external_session_id": str(raw["id"]) if raw.get("id") is not None else digest([start, end, raw.get("type")]),
            "sleep_date": datetime.fromisoformat(final or end).date().isoformat(), "start_at": start, "end_at": end,
            "sleep_onset_at": onset, "final_wake_at": final,
            "tst_minutes": tst, "light_minutes": durations["light"], "deep_minutes": durations["deep"],
            "rem_minutes": durations["rem"], "other_sleep_minutes": durations["nap"],
            "awake_minutes": number(summary.get("awake")),
            "waso_minutes": sum(s["duration_minutes"] for s in wakes) if complete and sleeping else None,
            "awakening_count": count, "device_external_id": None, "source_type": str(raw.get("type", "unknown")),
            "algorithm_version": VERSION, "quality_status": "needs_review" if issues else "valid",
            "quality_issues": issues + ["device_id_not_provided"], "raw_payload": raw,
            "units": {"duration": "minutes", "timestamp": "unix_seconds", "percent": "percent"},
            "stages": stages, "metric_provenance": {"tst_minutes": "complete_stage_timeline" if complete else "missing", "waso_minutes": "bounded_awake_timeline" if complete and sleeping else "missing", **stage_provenance}}


def canonical_sleep(raw):
    """Contract fields are ours; this does not claim a third party exports them."""
    start, end = timestamp(raw.get("start_at")), timestamp(raw.get("end_at"))
    if not start or not end or end <= start or not raw.get("external_session_id"):
        raise ValueError("標準格式需要 external_session_id 與含時區起訖時間")
    result = {key: number(raw.get(key)) for key in ("tst_minutes", "light_minutes", "deep_minutes", "rem_minutes", "other_sleep_minutes", "waso_minutes", "awake_minutes", "awakening_count")}
    for key in result:
        if raw.get(key) not in (None, "") and result[key] is None:
            raise ValueError(f"{key} 必須是非負有限數字")
    if result["awakening_count"] is not None and not result["awakening_count"].is_integer():
        raise ValueError("awakening_count 必須是整數")
    result["awakening_count"] = int(result["awakening_count"]) if result["awakening_count"] is not None else None
    issues = []
    stage_values = [result[k] for k in ("light_minutes", "deep_minutes", "rem_minutes", "other_sleep_minutes")]
    if raw.get("stages_complete") is True and all(x is not None for x in stage_values) and result["tst_minutes"] is None:
        result["tst_minutes"] = sum(stage_values)
    total = result["tst_minutes"]
    if total is not None and sum(x for x in stage_values if x is not None) > total + 1:
        issues.append("stage_sum_exceeds_tst")
    onset, final = timestamp(raw.get("sleep_onset_at")), timestamp(raw.get("final_wake_at"))
    if onset and not start <= onset <= end or final and not start <= final <= end or onset and final and onset > final:
        raise ValueError("入睡／最後醒來時間超出 Session 或順序錯誤")
    for key in ("tst_minutes", "waso_minutes", "awake_minutes"):
        if result[key] is not None and result[key] > (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60:
            issues.append(f"{key}_exceeds_session")
    result.update(external_session_id=str(raw["external_session_id"]), sleep_date=datetime.fromisoformat(final or end).date().isoformat(),
                  start_at=start, end_at=end, sleep_onset_at=onset, final_wake_at=final,
                  device_external_id=raw.get("device_external_id") or None, source_type=raw.get("source_type"),
                  algorithm_version=raw.get("algorithm_version") or VERSION,
                  quality_status="needs_review" if issues else "valid", quality_issues=issues,
                  raw_payload=raw, units={"duration": "minutes", "percent": "percent", "timestamp": "ISO8601_with_offset"},
                  stages=[], metric_provenance={"tst_minutes": "source_value" if raw.get("tst_minutes") is not None else "explicit_complete_summary"})
    for stage in ("light", "deep", "rem"):
        result["metric_provenance"][f"{stage}_percent"] = stage_percent(result[f"{stage}_minutes"], total)
    return result


def parse_sleep_file(content, file_format, adapter):
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    if file_format == "csv":
        records: Any = list(csv.DictReader(io.StringIO(text)))
        if adapter != "canonical":
            raise ValueError("CSV 使用標準 Mapping；DocterCloud 匯出請使用原始 JSON")
    else:
        records = json.loads(text)
        if isinstance(records, dict):
            if records.get("success") is False:
                raise ValueError("來源回應 success=false")
            records = records.get("data", records.get("sessions"))
    if not isinstance(records, list) or not records or len(records) > 1000:
        raise ValueError("匯入應包含 1–1000 筆 Session")
    parser = {"doctercloud_v5_4": docter_sleep, "canonical": canonical_sleep}.get(adapter)
    if parser is None:
        raise ValueError("未知 Parser")
    return [parser(record) for record in records]


def docter_metrics(records, kind="hrv"):
    metrics = []
    # V5-4 does not specify power units or confirm ECG/PPG origin.
    mapping: dict[str, tuple[str, str | None]] = {"fatigue": ("fatigue", None), "mental_stress": ("stress", None),
               "sdnn": ("SDNN", None), "tp": ("TP", None), "vlf": ("VLF", None),
               "lf": ("LF", None), "hf": ("HF", None)} if kind == "hrv" else {"value": ("HR", "bpm")}
    for raw in records:
        when = timestamp(raw.get("occur_time"), True)
        if when is None:
            raise ValueError("生理指標缺少量測時間")
        data = {**raw, **(raw.get("data") or {})}
        for field, (name, unit) in mapping.items():
            value = index_number(data.get(field)) if name in ("stress", "fatigue") else number(data.get(field))
            if value is not None:
                metrics.append({"external_record_id": str(raw.get("id", digest(raw))), "metric": name,
                                "value": value, "unit": unit, "measured_at": when,
                                "signal_type": "unknown", "device_external_id": None,
                                "algorithm_version": "DocterCloud-V5-4-output",
                                "scale_definition": None, "raw_payload": raw,
                                "quality_status": "unit_or_scale_unconfirmed" if unit is None else "valid"})
        lf, hf = number(data.get("lf")), number(data.get("hf"))
        # Same-source powers cancel units; mark derived output, never overwrite raw.
        if kind == "hrv" and lf is not None and hf and number(data.get("lf_hf")) is None:
            metrics.append({"external_record_id": str(raw.get("id", digest(raw))), "metric": "LF/HF", "value": lf / hf,
                            "unit": "ratio", "measured_at": when, "signal_type": "unknown",
                            "device_external_id": None, "algorithm_version": "vtca-lf-over-hf-1",
                            "scale_definition": None, "raw_payload": raw, "quality_status": "derived_same_record"})
    return metrics


def canonical_metrics(content, file_format="json"):
    """Explicit export contract for existing B20 HRV/PRV algorithms and sources."""
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    records = list(csv.DictReader(io.StringIO(text))) if file_format == "csv" else json.loads(text)
    if not isinstance(records, list) or not 0 < len(records) <= 50000:
        raise ValueError("生理指標需為 1–50000 筆陣列")
    result = []
    for raw in records:
        required = ("external_record_id", "metric", "measured_at", "algorithm_version", "signal_type")
        if any(not raw.get(k) for k in required) or raw["signal_type"] not in ("PPG", "ECG", "unknown"):
            raise ValueError("生理指標缺少紀錄 ID、量測時間、演算法版本或訊號來源")
        value = index_number(raw.get("value")) if raw["metric"] in ("stress", "fatigue") else number(raw.get("value"))
        if value is None:
            raise ValueError("生理指標值必須為非負有限數字")
        unit = raw.get("unit") or None
        # No numerical rescaling: callers must export the algorithm's actual unit.
        result.append({"external_record_id": str(raw["external_record_id"]), "metric": raw["metric"], "value": value,
                       "measured_at": timestamp(raw["measured_at"]), "unit": unit, "signal_type": raw["signal_type"],
                       "device_external_id": raw.get("device_external_id") or None,
                       "algorithm_version": raw["algorithm_version"], "scale_definition": raw.get("scale_definition"),
                       "raw_payload": raw, "quality_status": raw.get("quality_status") or ("valid" if unit else "unit_or_scale_unconfirmed")})
    return result


def docter_other_metrics(records, kind):
    """Retain original BP, oxygen and temperature charts without inferring units."""
    configs = {"blood/pressure": {"sys": ("SBP", "mmHg"), "dia": ("DBP", "mmHg")},
               "blood/oxygen": {"value": ("SpO2", "%")}, "body/temperature": {"value": ("Temperature", "°C")}}
    result = []
    for raw in records:
        data = {**raw, **(raw.get("data") or {})}
        for field, (metric, unit) in configs[kind].items():
            value = number(data.get(field))
            if value is not None:
                result.append({"external_record_id": str(raw.get("id", digest(raw))), "metric": metric, "value": value,
                               "unit": unit, "measured_at": timestamp(raw.get("occur_time"), True),
                               "signal_type": "unknown", "device_external_id": None, "algorithm_version": "DocterCloud-V5-4-output",
                               "raw_payload": raw, "scale_definition": None, "quality_status": "valid"})
    return result
