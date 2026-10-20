"""Prepare actual-platform DML for administrator backfill; never includes credentials.

The private source files come from the read-only probe. Exactly matching identifier
strings establish identity; no padding, name matching or heuristic joins are used.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from nsysu.parsers import digest  # noqa: E402

folder = Path('private/platform-probe')
members = json.loads((folder/'members.json').read_text(encoding='utf-8'))
known = {f'ycc{i:08}' for i in range(1, 51)}
mapping = [{'member_id': m['identifier'], 'platform_user_id': m['id']} for m in members if m.get('identifier') in known]
assert len({m['member_id'] for m in mapping}) == len(mapping)
target = next(m for m in mapping if m['member_id'] == 'ycc00000038')
raw = json.loads((folder/'observations.json').read_text(encoding='utf-8'))
normalized = json.loads((folder/'normalized.json').read_text(encoding='utf-8'))
assert not normalized['sessions'], 'Use authenticated importer when sleep sessions are present'


def literal(value):
    return "'" + json.dumps(value, ensure_ascii=False, allow_nan=False).replace("'", "''") + "'::jsonb"


sql = f"""begin;
update public.research_participants p set platform_user_id=m.platform_user_id
from jsonb_to_recordset({literal(mapping)}) as m(member_id text,platform_user_id bigint)
where p.member_id=m.member_id and (p.platform_user_id is null or p.platform_user_id=m.platform_user_id);
with imported as (
insert into public.data_imports(member_id,source,payload_hash,raw_payload,algorithm_version,status,session_count,metric_count)
values('ycc00000038','doctercloud','{digest(raw)}',{literal(raw)},'vtca-import-2.0.0','success',0,{len(normalized['metrics'])})
on conflict(member_id,source,payload_hash) do update set imported_at=now() returning id)
insert into public.physiological_metrics(member_id,source,external_record_id,metric,value,unit,measured_at,signal_type,device_external_id,scale_definition,algorithm_version,raw_payload,quality_status,import_id)
select 'ycc00000038','doctercloud',m.external_record_id,m.metric,m.value,m.unit,m.measured_at,m.signal_type,m.device_external_id,m.scale_definition,m.algorithm_version,m.raw_payload,m.quality_status,i.id
from jsonb_to_recordset({literal(normalized['metrics'])}) as m(external_record_id text,metric text,value float8,unit text,measured_at timestamptz,signal_type text,device_external_id text,scale_definition jsonb,algorithm_version text,raw_payload jsonb,quality_status text) cross join imported i
on conflict(member_id,source,external_record_id,metric) do update set value=excluded.value,unit=excluded.unit,measured_at=excluded.measured_at,signal_type=excluded.signal_type,algorithm_version=excluded.algorithm_version,raw_payload=excluded.raw_payload,quality_status=excluded.quality_status,import_id=excluded.import_id,imported_at=now();
commit;
select json_build_object('mapped_participants',(select count(*) from public.research_participants where platform_user_id is not null),'imported_metric_count',(select count(*) from public.physiological_metrics where member_id='ycc00000038' and source='doctercloud'),'original_diary_count',(select count(*) from public.sleep_logs)) result;
"""
(folder/'verified-backfill.sql').write_text(sql,encoding='utf-8')
print(json.dumps({'verified_mapping_count':len(mapping),'actual_metric_count':len(normalized['metrics']),'prepared':True}))
