"""Complete, caller-scoped DocterCloud reads; raw fields are always retained."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import datetime, time, timedelta
import re

from .parsers import docter_sleep, docter_metrics, docter_other_metrics, index_number, timestamp, digest
from .platform import Platform, PlatformError, KINDS
from .sleep import TZ

FIELDS: dict[str, dict[str, tuple[str, str | None]]] = {
    'cholesterol': {'value': ('Cholesterol', None)}, 'uric-acid': {'value': ('UricAcid', None)},
    'urine-output': {'value': ('UrineOutput', None)}, 'drinking-water': {'value': ('WaterIntake', None)},
    'weight': {'value': ('Weight', None)}, 'step': {'value': ('Steps', 'steps')},
    'calories': {'value': ('Calories', None)}, 'rri': {'value': ('RRI', None)},
    'blood/glucose': {'bg': ('Glucose', None), 'value': ('Glucose', None)},
    'heart/vessel': {'heart': ('HeartIndex', None), 'elasticity': ('VascularIndex', None)},
    'activity': {'steps': ('ActivitySteps', 'steps'), 'mileages': ('ActivityDistance', 'km'),
                 'static_time': ('StaticTime', 'min'), 'dynamic_time': ('ActiveTime', 'min'),
                 'static_calories': ('StaticCalories', None), 'dynamic_calories': ('ActiveCalories', None)},
    'sports': {'steps': ('SportSteps', 'steps'), 'calories': ('SportCalories', None),
               'duration': ('SportDuration', 's'), 'heart_rate_max': ('SportMaxHR', 'bpm'),
               'heart_rate_avg': ('SportAvgHR', 'bpm'), 'distance': ('SportDistance', 'm')},
}


def combine_participants(research, platform):
    combined = {row['member_id']: dict(row) for row in research}
    counts = Counter(str(row.get('identifier') or '').strip().lower() for row in platform)
    for profile in platform:
        code = str(profile.get('identifier') or '').strip().lower()
        if code in combined and counts[code] == 1:
            row = combined[code]
            if row.get('platform_user_id') not in (None, profile['id']):
                row['platform_mapping_error'] = True
            else:
                row['platform_profile'] = profile
        else:
            if code in combined:
                combined[code]['platform_mapping_error'] = True
            # A missing/duplicate identifier never borrows another person's diary.
            key = 'doctercloud:' + str(profile['id'])
            combined[key] = {'member_id': key, 'platform_profile': profile, 'platform_only': True}
    return list(combined.values())


def normalize_metrics(kind, raw):
    extra: dict[str, tuple[str, str | None]]
    if kind == 'hrv':
        result = docter_metrics([raw])
        values = {**raw, **(raw.get('data') or {})}
        extra = {'compressive_ability': ('StressTolerance', None), 'adjustment_ability': ('Adaptability', None)}
    elif kind == 'heart/rate':
        return docter_metrics([raw], 'hr')
    elif kind in ('blood/pressure', 'blood/oxygen', 'body/temperature'):
        return docter_other_metrics([raw], kind)
    else:
        result = []
        values = {**raw, **(raw.get('data') or {})}
        extra = FIELDS.get(kind, {})
    emitted = set()
    for field, (metric, unit) in extra.items():
        value = index_number(values.get(field))
        if value is None or metric in emitted:
            continue
        when = timestamp(raw.get('occur_time', raw.get('start_time')), True)
        if when is None:
            continue
        emitted.add(metric)
        result.append({'external_record_id': str(raw.get('id', digest(raw))), 'metric': metric,
                       'value': value, 'unit': unit, 'measured_at': when, 'signal_type': 'unknown',
                       'device_external_id': None, 'algorithm_version': 'DocterCloud-V5-4-output',
                       'scale_definition': None, 'raw_payload': raw,
                       'quality_status': 'valid' if unit else 'unit_or_scale_unconfirmed'})
    return result


def load_platform_bundle(token, profile, start, end):
    api = Platform(token)
    lower = int(datetime.combine(start, time.min, TZ).timestamp())
    upper = int(datetime.combine(end + timedelta(days=1), time.min, TZ).timestamp())
    raw, statuses = {}, {}

    def read(kind):
        return api.fetch_range(kind, profile['id'], lower - (86400 if kind == 'sleep' else 0), upper)

    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = {pool.submit(read, kind): kind for kind in KINDS}
        for task in as_completed(tasks):
            kind = tasks[task]
            try:
                raw[kind] = task.result()
                statuses[kind] = {'state': 'success', 'count': len(raw[kind]), 'message': ''}
            except Exception as error:
                message = str(error) if isinstance(error, PlatformError) else '平台連線未完成，請重試'
                statuses[kind] = {'state': 'error', 'count': None, 'message': message}
    sessions, metrics, issues = [], [], []
    for kind, rows in raw.items():
        for row in rows:
            try:
                if kind == 'sleep':
                    record = dict(docter_sleep(row), source='doctercloud')
                    if str(start) <= record['sleep_date'] <= str(end):
                        sessions.append(record)
                else:
                    for record in normalize_metrics(kind, row):
                        day = datetime.fromisoformat(record['measured_at']).astimezone(TZ).date()
                        if start <= day <= end:
                            metrics.append(dict(record, source='doctercloud', platform_kind=kind,
                                                source_type=row.get('type', row.get('typr'))))
            except (ValueError, TypeError, KeyError, OverflowError):
                issues.append({'kind': kind, 'record_id': str(row.get('id', 'unknown'))})
    return {'raw': raw, 'statuses': statuses, 'sessions': sessions, 'metrics': metrics,
            'profile': profile, 'parse_issues': issues, 'loaded_at': datetime.now(TZ).isoformat()}


def merge_records(saved, live, metric=False):
    combined = {}
    for row in saved + live:
        when = row.get('measured_at' if metric else 'sleep_date')
        if metric and when:
            when = datetime.fromisoformat(str(when).replace('Z', '+00:00')).timestamp()
        external_id = row.get('external_record_id' if metric else 'external_session_id') or row.get('id') or digest(row)
        identity = (row.get('source'), str(external_id), row.get('metric') if metric else None, when)
        combined[identity] = row
    return list(combined.values())


def diary_member(member):
    return bool(re.fullmatch(r'ycc[0-9]{8}', member))
