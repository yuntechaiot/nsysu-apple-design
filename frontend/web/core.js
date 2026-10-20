/* Shared, testable 24-hour and date helpers; no locale-dependent time input. */
(function (root) {
  const validClock = value => typeof value === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
  const tri = value => value === 'true' ? true : value === 'false' ? false : null;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function diaryEmail(account) {
    const username = String(account || '').trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9_-]{3,31}$/.test(username)) throw Error('請輸入研究團隊提供的日誌帳號');
    return username.toLowerCase() + '@diary.nsysu.invalid';
  }
  function anchored(day, clock) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !validClock(clock)) throw Error('請輸入有效日期與 HH:mm 24 小時時間');
    const value = `${day}T${clock}:00+08:00`;
    if (!Number.isFinite(Date.parse(value)) || new Date(value).toLocaleDateString('sv-SE',{timeZone:'Asia/Taipei'}) !== day) throw Error('無效日期');
    return value;
  }
  function diaryTimes(d) {
    const bed = anchored(d.bedDate,d.bed), out = anchored(d.outDate,d.out), wake = anchored(d.date,d.wake);
    const lights = d.lights ? anchored(d.lightsDate,d.lights) : null;
    if (Date.parse(bed)>Date.parse(wake) || Date.parse(wake)>Date.parse(out) || Date.parse(out)-Date.parse(bed)>86400000 || (lights && (Date.parse(lights)<Date.parse(bed)||Date.parse(lights)>Date.parse(wake)))) throw Error('請核對上床、關燈、醒來、離床的日期與先後順序（最多 24 小時）');
    return {bedtime_at:bed,lights_out_at:lights,final_wake_at:wake,out_of_bed_at:out,bedtime:d.bed,lights_out_time:d.lights||null,final_wake_time:d.wake,out_of_bed_time:d.out,date_definition:'wake_date',time_review_status:'verified',timezone:'Asia/Taipei'};
  }
  const duration = v => v == null ? '暫無資料' : `${Math.floor(v/60)} 小時 ${+(v%60).toFixed(1)} 分鐘`;
  const percentage = (v,t) => v == null || t == null || t<=0 || v>t ? null : v/t*100;
  const participantMatches = (row, query) => `${row.member_id} ${row.display_name || ''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  function diaryLink(origin, configured, member) {
    const local = host => ['localhost','127.0.0.1','[::1]'].includes(host);
    let base = new URL(origin);
    if (configured) {
      try { const candidate = new URL(configured); if (['http:','https:'].includes(candidate.protocol) && !(local(candidate.hostname) && !local(base.hostname))) base = candidate; } catch { /* Use the current page when configuration is invalid. */ }
    }
    base.search = ''; base.hash = ''; base.searchParams.set('member',member);
    return base.href;
  }
  const api = {validClock,tri,esc,diaryEmail,anchored,diaryTimes,duration,percentage,participantMatches,diaryLink};
  if (typeof module !== 'undefined') module.exports = api;
  root.VTCA = api;
})(typeof window !== 'undefined' ? window : globalThis);
