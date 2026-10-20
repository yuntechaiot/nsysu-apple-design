"""Sleep definitions v2.0.0. Diary date is the final-waking local calendar date."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import math
import re
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")
VERSION = "vtca-sleep-2.0.0"


def number(value):
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def legacy_clock(value, ampm=None):
    """Never silently choose between conflicting native-time and AM/PM inputs."""
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d(?::00)?", value):
        return None
    hour, minute = map(int, value.split(":")[:2])
    if ampm:
        if ampm not in ("AM", "PM"):
            return None
        if (ampm == "AM" and hour >= 12) or (ampm == "PM" and hour < 12):
            return None
    return f"{hour:02}:{minute:02}"


def local_clock(day, clock):
    if not clock:
        return None
    return datetime.combine(date.fromisoformat(str(day)), time.fromisoformat(clock)).replace(tzinfo=TZ)


def diary_interval(log):
    """New rows carry absolute timestamps. Legacy date semantics remain unpaired."""
    if log.get("bedtime_at") and log.get("out_of_bed_at"):
        return datetime.fromisoformat(log["bedtime_at"]), datetime.fromisoformat(log["out_of_bed_at"])
    if log.get("date_definition") != "wake_date":
        return None, None
    bed = local_clock(log["date"], log.get("bedtime"))
    out = local_clock(log["date"], log.get("out_of_bed_time"))
    if bed and out and bed > out:
        bed -= timedelta(days=1)
    return bed, out


def minutes_between(start, end):
    if not start or not end:
        return None
    delta = (end - start).total_seconds() / 60
    return delta if 0 <= delta <= 1440 else None


def sleep_metrics(log, session=None):
    session = session or {}
    bed, out = diary_interval(log)
    tib = minutes_between(bed, out)
    attempt = datetime.fromisoformat(log["lights_out_at"]) if log.get("lights_out_at") else None
    onset = datetime.fromisoformat(session["sleep_onset_at"]) if session.get("sleep_onset_at") else None
    sol = minutes_between(attempt, onset)
    if sol is not None and (bed and attempt < bed or out and onset > out):
        sol = None
    tst = number(session.get("tst_minutes"))
    se = tst / tib * 100 if tst is not None and tib and tst <= tib else None
    return {"tib_minutes": tib, "sol_minutes": sol,
            "subjective_sol_minutes": log.get("sleep_onset_min"),
            "tst_minutes": tst, "waso_minutes": session.get("waso_minutes"),
            "se_percent": se, "algorithm_version": VERSION}


def stage_percent(minutes, tst):
    value, total = number(minutes), number(tst)
    return value / total * 100 if value is not None and total and value <= total else None


def sleep_display_summary(session):
    """Platform-facing summary; never substitute total awake for research WASO.

    The current official DocterCloud B20 view defines its main sleep total as
    data.light + data.deep + data.REM. Missing components stay missing here,
    rather than copying the portal's null-to-zero defaults. Strict timeline
    TST/WASO and diary-based research calculations remain unchanged.
    """
    values = {key: number(session.get(key + '_minutes')) for key in ('light', 'deep', 'rem', 'awake')}
    total = number(session.get('tst_minutes'))
    basis = 'confirmed_tst' if total is not None else 'missing'
    raw = session.get('raw_payload') or {}
    data = raw.get('data') if isinstance(raw, dict) else None
    if session.get('source') == 'doctercloud' and isinstance(data, dict):
        core = [number(data.get(key)) for key in ('light', 'deep', 'REM')]
        for key, field in (('light', 'light'), ('deep', 'deep'), ('rem', 'REM'), ('awake', 'awake')):
            values[key] = number(data.get(field))
        if all(value is not None for value in core):
            candidate = sum(value for value in core if value is not None)
            start = session.get('start_at')
            end = session.get('end_at')
            bound = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60 if start and end else None
            if bound is not None and 0 <= candidate <= bound + 1:
                total, basis = candidate, 'platform_core_summary'
    return {**values, 'total_minutes': total, 'total_basis': basis}


def duration_label(value):
    value = number(value)
    if value is None:
        return "暫無資料"
    hours, minutes = divmod(round(value, 1), 60)
    return f"{int(hours)} 小時 {minutes:g} 分鐘" if hours else f"{minutes:g} 分鐘"


def clock_label(value):
    return datetime.fromisoformat(value).astimezone(TZ).strftime("%H:%M") if value else "暫無資料"
