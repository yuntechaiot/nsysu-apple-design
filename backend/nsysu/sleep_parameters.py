"""Display-only parameters from 睡眠平台數據定義_20261020_yc.docx.

The document's elapsed TST, bed-based SOL and watch-awake WASO are deliberately
separate from the existing research metrics. No source records are modified.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import math
import statistics

from .dashboard_summary import series_key
from .sleep import TZ, legacy_clock, local_clock, minutes_between, number

DEFINITION_VERSION = 'sleep-parameters-word-20261020-diary-fallback-v1'
PARAMETERS = [
    ('tib_minutes', '總躺床時數', '分鐘', '日誌離床時間－日誌躺床時間'),
    ('tst_minutes', '整體入睡時間（TST）', '分鐘', '日誌最後醒來時間－手錶入睡時間（文件定義）'),
    ('sol_minutes', '睡眠潛伏期（SOL）', '分鐘', '手錶入睡時間－日誌躺床時間（文件定義）'),
    ('awakening_count', '夜間醒來次數', '次', '個案睡眠日誌填寫的夜間醒來次數'),
    ('waso_minutes', '入睡後醒來時間（WASO）', '分鐘', '依文件採手錶清醒時間，不替代既有研究 WASO'),
    ('se_percent', '睡眠效率（SE）', '%', '本頁整體入睡時間／總躺床時數 × 100%'),
    ('rise_minutes', '賴床時間', '分鐘', '日誌離床時間－日誌最後醒來時間'),
]
MEAN_LABELS = {'stress': '入睡前平均壓力指數', 'fatigue': '入睡前平均疲倦指數'}


def instant(value):
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(TZ) if parsed.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def diary_times(log):
    if log.get('date_definition') != 'wake_date':
        return {'bed': None, 'wake': None, 'out': None}, '日誌日期定義尚未確認，請先到睡眠日誌核對。'
    day = log.get('date')
    try:
        date.fromisoformat(str(day))
    except (ValueError, TypeError):
        return {'bed': None, 'wake': None, 'out': None}, '日誌醒來日期無效。'
    clocks = {'bed': log.get('bedtime'), 'wake': log.get('final_wake_time') or log.get('morning_wake_time'),
              'out': log.get('out_of_bed_time') or log.get('wake_time')}
    times = {key: instant(log.get(field)) for key, field in
             [('bed', 'bedtime_at'), ('wake', 'final_wake_at'), ('out', 'out_of_bed_at')]}
    if any(log.get(field) and times[key] is None for key, field in
           [('bed', 'bedtime_at'), ('wake', 'final_wake_at'), ('out', 'out_of_bed_at')]):
        return times, '日誌提供的日期時間無效或缺少時區，請先核對。'
    if not clocks['bed']:
        clocks['bed'] = legacy_clock(log.get('sleep_time'), log.get('sleep_time_ampm'))
    for key in times:
        if times[key] is None and legacy_clock(clocks[key]):
            times[key] = local_clock(day, legacy_clock(clocks[key]))
    # Only anchored wake-date clocks may cross midnight; absolute timestamps never shift.
    anchor = times['wake'] or times['out']
    if times['bed'] and anchor and not log.get('bedtime_at') and times['bed'] > anchor:
        times['bed'] -= timedelta(days=1)
    if times['out'] and times['wake'] and not log.get('out_of_bed_at') and times['out'] < times['wake']:
        times['out'] += timedelta(days=1)
    if times['wake'] and times['wake'].date().isoformat() != str(day):
        return times, '日誌最後醒來時間與醒來日期不一致。'
    if times['bed'] and times['out'] and minutes_between(times['bed'], times['out']) is None:
        return times, '日誌躺床與離床時間順序有誤，或超過 24 小時。'
    if times['wake'] and ((times['bed'] and times['wake'] < times['bed']) or
                          (times['out'] and times['wake'] > times['out'])):
        return times, '日誌時間須符合躺床、最後醒來、離床的先後順序。'
    return times, ''


def watch_onset(session, allow_observed=False):
    if not session:
        return None, '缺少對應日期的手錶睡眠紀錄'
    lower, upper = instant(session.get('start_at')), instant(session.get('end_at'))
    supplied = instant(session.get('sleep_onset_at'))
    if session.get('sleep_onset_at'):
        if supplied and (not lower or supplied >= lower) and (not upper or supplied <= upper):
            return supplied, '手錶來源的入睡時間'
        return None, '手錶入睡時間無效或超出來源紀錄區間'
    if not allow_observed:
        return None, '來源未提供已確認入睡時間；可在來源設定選擇首筆分期起點供觀察'
    # A supplied stage start is a real observation even when the stage end is unknown.
    # Label it as an observed start; do not infer interval length or research WASO.
    starts = [instant(s.get('start_at')) for s in (session.get('stages') or [])
              if s.get('stage') in {'light', 'deep', 'rem'}]
    starts = [value for value in starts if value and (not lower or value >= lower) and (not upper or value <= upper)]
    return (min(starts), '手錶首筆睡眠分期起點（非完整分期確認）') if starts else (None, '缺少手錶入睡時間或睡眠分期起點')


def pre_sleep_means(metrics, onset, window_minutes=60, member_id=None):
    if onset is None:
        return []
    lower = onset - timedelta(minutes=window_minutes)
    groups: dict = defaultdict(list)
    for row in metrics:
        if row.get('metric') not in MEAN_LABELS or (member_id and row.get('member_id') not in (None, member_id)):
            continue
        when = instant(row.get('measured_at'))
        value = row.get('value')
        try:
            finite = value is not None and not isinstance(value, bool) and math.isfinite(float(value))
        except (TypeError, ValueError):
            finite = False
        if when is not None and lower <= when < onset and finite:
            groups[series_key(row) + (str(row.get('scale_definition')),)].append((when, float(value)))
    result = []
    for key, rows in groups.items():
        metric, source, unit, signal, device, version, scale = key
        result.append({'metric': metric, 'mean': statistics.mean(value for _, value in rows), 'count': len(rows),
                       'source': source or '來源未提供', 'unit': unit or '單位／量尺未確認',
                       'signal_type': signal or 'unknown', 'device': device or '未提供',
                       'algorithm_version': version or '未提供', 'scale_definition': scale,
                       'first_at': min(when for when, _ in rows).isoformat(),
                       'last_at': max(when for when, _ in rows).isoformat()})
    return sorted(result, key=lambda row: (row['metric'], row['source'], row['device'], row['algorithm_version']))


def diary_onset(log, times):
    """Estimate only from supplied diary latency; never assume missing latency is zero."""
    latency = number(log.get('sleep_onset_min'))
    if latency is None or latency > 300:
        return None, '日誌缺少有效的自覺入睡所需分鐘（0～300）'
    bed, wake = times['bed'], times['wake']
    if bed is None or wake is None:
        return None, '日誌估算入睡時間需有躺床與最後醒來時間'
    attempt = instant(log.get('lights_out_at'))
    basis = '開始嘗試入睡時間'
    if log.get('lights_out_at') and attempt is None:
        return None, '日誌開始嘗試入睡日期時間無效或缺少時區'
    if attempt is None and log.get('lights_out_time'):
        clock = legacy_clock(log['lights_out_time'])
        if clock is None:
            return None, '日誌開始嘗試入睡時間無效'
        attempt = local_clock(log['date'], clock)
        if attempt > wake:
            attempt -= timedelta(days=1)
    if attempt is None:
        attempt, basis = bed, '躺床時間（未填開始嘗試入睡時間）'
    onset = attempt + timedelta(minutes=latency)
    if not bed <= attempt <= onset <= wake:
        return None, '日誌估算入睡時間不在躺床至最後醒來的區間'
    return onset, '睡眠日誌估算：' + basis + '＋自覺入睡所需分鐘'


def calculate_parameters(log=None, session=None, metrics=None, window_minutes=60, allow_observed=False):
    log, session = log or {}, session or {}
    values: dict[str, float | None] = {key: None for key, *_ in PARAMETERS}
    reasons = {key: '缺少對應資料' for key in values}
    times, diary_issue = diary_times(log) if log else ({'bed': None, 'wake': None, 'out': None}, '缺少對應日期的睡眠日誌')
    onset, onset_basis = watch_onset(session, allow_observed)
    original_onset, original_basis = onset, onset_basis
    sources = {key: '' for key in values}
    notes = [diary_issue] if log and diary_issue else []
    pairing_issue = ''
    identity_issue = bool(log and session and (
        log.get('date') != session.get('sleep_date') or
        (log.get('member_id') and session.get('member_id') and log['member_id'] != session['member_id'])))
    if log and session and log.get('date') != session.get('sleep_date'):
        pairing_issue = '日誌與手錶睡眠日期不同，未計算跨來源參數。'
    if log.get('member_id') and session.get('member_id') and log['member_id'] != session['member_id']:
        pairing_issue = '日誌與手錶受試者不同，未計算跨來源參數。'
    if onset and not diary_issue and ((times['bed'] and onset < times['bed']) or
                                     (times['wake'] and onset > times['wake']) or
                                     (times['out'] and onset > times['out'])):
        pairing_issue = '手錶入睡時間不在日誌躺床至最後醒來的區間，請核對紀錄配對。'
    if pairing_issue:
        notes.append(pairing_issue)
    fallback = False
    if log and not diary_issue and (not onset or pairing_issue):
        onset, diary_basis = diary_onset(log, times)
        if onset is not None:
            fallback, onset_basis = True, diary_basis
            notes.append('Word 公式所需的手錶入睡時間缺少或與日誌不一致；TST、SOL、SE 改採日誌估算。')
        else:
            onset_basis = (pairing_issue or original_basis) + '；日誌備案：' + diary_basis
    elif identity_issue:
        onset = None
    if not diary_issue:
        values['tib_minutes'] = minutes_between(times['bed'], times['out'])
        values['rise_minutes'] = minutes_between(times['wake'], times['out'])
    reasons['tib_minutes'] = diary_issue or '缺少日誌躺床或離床時間'
    reasons['rise_minutes'] = diary_issue or '缺少日誌最後醒來或離床時間'
    count = number(log.get('wakeup_count'))
    if count is not None and count.is_integer():
        values['awakening_count'] = int(count)
    reasons['awakening_count'] = '缺少有效的日誌夜間醒來次數'
    if (not pairing_issue or fallback) and not diary_issue and onset:
        values['tst_minutes'] = minutes_between(onset, times['wake'])
        values['sol_minutes'] = minutes_between(times['bed'], onset)
    reasons['tst_minutes'] = diary_issue or (onset_basis if not onset else pairing_issue or '缺少有效的日誌最後醒來時間')
    reasons['sol_minutes'] = diary_issue or (onset_basis if not onset else pairing_issue or '缺少有效的日誌躺床時間')
    tib, tst = values['tib_minutes'], values['tst_minutes']
    if tib is not None and tib > 0 and tst is not None and tst <= tib:
        values['se_percent'] = tst / tib * 100
    reasons['se_percent'] = '需有有效 TST 與大於零的總躺床時數，且 TST 不可超過躺床時數'
    awake = number(session.get('awake_minutes'))
    raw = session.get('raw_payload') or {}
    if awake is None and session.get('source') == 'doctercloud' and isinstance(raw, dict) and isinstance(raw.get('data'), dict):
        awake = number(raw['data'].get('awake'))
    lower, upper = instant(session.get('start_at')), instant(session.get('end_at'))
    if not identity_issue and awake is not None and (not lower or not upper or 0 <= awake <= (upper - lower).total_seconds() / 60):
        values['waso_minutes'] = awake
        sources['waso_minutes'] = 'Word 公式：手錶清醒時間'
    reasons['waso_minutes'] = '手錶未提供有效清醒時間，或清醒時間超過來源紀錄長度'
    if values['waso_minutes'] is None and log:
        subjective_awake = number(log.get('subjective_waso_minutes'))
        sleep_interval = minutes_between(onset, times['wake']) if not diary_issue else None
        if subjective_awake is not None and sleep_interval is not None and subjective_awake <= sleep_interval:
            values['waso_minutes'] = subjective_awake
            sources['waso_minutes'] = '睡眠日誌備案：自填夜間清醒總分鐘'
        else:
            reasons['waso_minutes'] += '；日誌備案需有有效夜間清醒總分鐘與入睡區間'
    for key, value in values.items():
        if value is not None:
            reasons[key] = ''
            if not sources[key]:
                sources[key] = ('睡眠日誌備案' if fallback else 'Word 公式（日誌＋手錶）') if key in {
                    'tst_minutes', 'sol_minutes', 'se_percent'} else '睡眠日誌'
    member = log.get('member_id') or session.get('member_id')
    means = pre_sleep_means(metrics or [], onset if not log or not diary_issue else None, window_minutes, member)
    return {'date': str(log.get('date') or session.get('sleep_date') or ''), 'values': values, 'reasons': reasons,
            'times': {**times, 'onset': onset, 'watch_onset': original_onset},
            'onset_basis': onset_basis, 'watch_onset_basis': original_basis, 'sources': sources, 'notes': notes,
            'diary_id': str(log.get('id') or '未選取'),
            'session_id': str(session.get('external_session_id') or session.get('id') or '未選取'),
            'watch_source': session.get('source') or '未選取', 'pre_sleep': means,
            'window_minutes': window_minutes,
            'window_start': (onset - timedelta(minutes=window_minutes)).isoformat() if onset else None,
            'window_end': onset.isoformat() if onset else None, 'definition_version': DEFINITION_VERSION}


def matching_sessions(log, sessions, allow_observed=False):
    candidates = [s for s in sessions if s.get('sleep_date') == log.get('date')]
    times, issue = diary_times(log)
    if issue:
        return []
    result, fallback_candidates = [], []
    for session in candidates:
        if log.get('member_id') and session.get('member_id') not in (None, log['member_id']):
            continue
        onset, _ = watch_onset(session, allow_observed)
        if onset and ((times['bed'] and onset < times['bed']) or (times['wake'] and onset > times['wake']) or
                      (times['out'] and onset > times['out'])):
            fallback_candidates.append(session)
            continue
        result.append(session)
    return result or fallback_candidates


def period_parameters(diaries, sessions, metrics, window_minutes=60, allow_observed=False):
    result, used = [], set()
    metrics = [row for row in metrics if row.get('metric') in MEAN_LABELS]
    matches = [matching_sessions(log, sessions, allow_observed) for log in diaries]
    appearances = Counter(id(session) for candidates in matches for session in candidates)
    for log, candidates in zip(diaries, matches):
        chosen = candidates[0] if len(candidates) == 1 and appearances[id(candidates[0])] == 1 else None
        row = calculate_parameters(log, chosen, metrics, window_minutes, allow_observed)
        if candidates and chosen is None:
            row['notes'].append('同日紀錄無法唯一配對，請至單次觀察明確選擇，不自動合併。')
        if chosen is not None:
            used.add(id(chosen))
        result.append(row)
    for session in sessions:
        if id(session) not in used:
            row = calculate_parameters(None, session, metrics, window_minutes, allow_observed)
            row['notes'].append('此手錶紀錄未唯一配對日誌，跨來源參數保持缺值。')
            result.append(row)
    return sorted(result, key=lambda row: (row['date'], row['diary_id'], row['session_id']))
