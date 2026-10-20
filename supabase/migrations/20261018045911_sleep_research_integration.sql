-- Additive migration. Existing raw values are never rewritten or removed.
begin;
set local lock_timeout = '5s';
create schema if not exists vtca_private;
revoke all on schema vtca_private from public, anon, authenticated;
create table vtca_private.sleep_logs_before_v2 as select * from public.sleep_logs;
create table vtca_private.policies_before_v2 as select * from pg_policies where schemaname='public' and tablename='sleep_logs';
revoke all on all tables in schema vtca_private from public, anon, authenticated;

alter table public.sleep_logs
  alter column sleep_time_ampm drop not null,
  add column bedtime time,
  add column lights_out_time time,
  add column final_wake_time time,
  add column out_of_bed_time time,
  add column bedtime_at timestamptz,
  add column lights_out_at timestamptz,
  add column final_wake_at timestamptz,
  add column out_of_bed_at timestamptz,
  add column subjective_waso_minutes numeric check (subjective_waso_minutes between 0 and 1440),
  add column wore_watch boolean,
  add column sleep_medication boolean,
  add column drank_alcohol boolean,
  add column timezone text not null default 'Asia/Taipei' check (timezone='Asia/Taipei'),
  add column date_definition text not null default 'legacy_unconfirmed' check (date_definition in ('legacy_unconfirmed','wake_date')),
  add column time_review_status text not null default 'needs_review' check (time_review_status in ('needs_review','verified')),
  add column legacy_time_raw jsonb,
  add column updated_at timestamptz not null default now();

-- Original form used native 24-hour input plus a redundant AM/PM selector.
-- Conflicting combinations cannot be reliably interpreted as 12-hour values.
update public.sleep_logs set
  legacy_time_raw=jsonb_build_object('sleep_time',sleep_time,'sleep_time_ampm',sleep_time_ampm,'morning_wake_time',morning_wake_time,'wake_time',wake_time,'date',date),
  bedtime=case when sleep_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'
    and ((sleep_time_ampm='AM' and split_part(sleep_time,':',1)::int < 12)
      or (sleep_time_ampm='PM' and split_part(sleep_time,':',1)::int >= 12)) then sleep_time::time end,
  final_wake_time=case when morning_wake_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then morning_wake_time::time end,
  out_of_bed_time=case when wake_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' then wake_time::time end;
-- lights_out remains NULL for every legacy row. No date anchor is guessed.
create index sleep_logs_member_date_v2 on public.sleep_logs(member_id,date);
create index sleep_logs_factors_v2 on public.sleep_logs(wore_watch,sleep_medication,drank_alcohol,date);

create table public.research_participants (
  member_id text primary key check (member_id ~ '^ycc[0-9]{8}$'),
  platform_user_id bigint unique,
  created_at timestamptz not null default now()
);
insert into public.research_participants(member_id) select distinct member_id from public.sleep_logs
where member_id ~ '^ycc[0-9]{8}$';
insert into public.research_participants(member_id) select 'ycc'||lpad(n::text,8,'0') from generate_series(1,50)n on conflict do nothing;
create table public.participant_access (
  user_id uuid not null references auth.users(id) on delete cascade,
  member_id text not null references public.research_participants(member_id),
  can_write boolean not null default false,
  primary key(user_id,member_id)
);
-- Grants and platform identity mappings can only be provisioned administratively.
alter table public.research_participants enable row level security;
alter table public.participant_access enable row level security;
create policy access_own on public.participant_access for select to authenticated using(user_id=(select auth.uid()));
create policy participant_read on public.research_participants for select to authenticated using(exists(select 1 from public.participant_access a where a.member_id=research_participants.member_id));
grant select on public.participant_access, public.research_participants to authenticated;
revoke all on public.participant_access,public.research_participants from anon;

alter table public.sleep_logs enable row level security;
alter policy sleep_logs_public_insert on public.sleep_logs to anon with check (
 member_id ~ '^ycc[0-9]{8}$'
 and (sleep_time_ampm is null or sleep_time_ampm in ('AM','PM'))
 and headphone_min between 0 and 600 and sleep_onset_min between 0 and 300
 and wakeup_count between 0 and 20 and disturbance_scale between 0 and 5
 and sleep_quality between 1 and 5
);
-- Restrictive policies also guard against accidental future broad read policies.
create policy sleep_read_guard on public.sleep_logs as restrictive for select to authenticated using(exists(select 1 from public.participant_access a where a.member_id=sleep_logs.member_id));
create policy sleep_read on public.sleep_logs for select to authenticated using(exists(select 1 from public.participant_access a where a.member_id=sleep_logs.member_id));
create policy sleep_write on public.sleep_logs for insert to authenticated with check(exists(select 1 from public.participant_access a where a.member_id=sleep_logs.member_id and a.can_write));
create policy sleep_update on public.sleep_logs for update to authenticated using(exists(select 1 from public.participant_access a where a.member_id=sleep_logs.member_id and a.can_write)) with check(exists(select 1 from public.participant_access a where a.member_id=sleep_logs.member_id and a.can_write));
revoke select,update,delete on public.sleep_logs from anon;
grant insert on public.sleep_logs to anon;
grant select,insert,update on public.sleep_logs to authenticated;
grant usage,select on all sequences in schema public to anon,authenticated;

create function public.validate_sleep_log_v2() returns trigger language plpgsql security invoker set search_path='' as $$
begin
  if new.date_definition='wake_date' then
    if new.date !~ '^\d{4}-\d{2}-\d{2}$' or new.bedtime_at is null or new.out_of_bed_at is null or new.final_wake_at is null then
      raise exception 'New diary requires explicit Taiwan date anchors';
    end if;
    if new.bedtime_at > new.final_wake_at or new.final_wake_at > new.out_of_bed_at
      or new.out_of_bed_at-new.bedtime_at > interval '24 hours'
      or (new.lights_out_at is not null and (new.lights_out_at<new.bedtime_at or new.lights_out_at>new.final_wake_at)) then
      raise exception 'Invalid diary chronology';
    end if;
    if (new.final_wake_at at time zone 'Asia/Taipei')::date <> new.date::date then raise exception 'Diary date must be Taiwan final waking date'; end if;
    new.bedtime:=(new.bedtime_at at time zone 'Asia/Taipei')::time;
    new.lights_out_time:=(new.lights_out_at at time zone 'Asia/Taipei')::time;
    new.final_wake_time:=(new.final_wake_at at time zone 'Asia/Taipei')::time;
    new.out_of_bed_time:=(new.out_of_bed_at at time zone 'Asia/Taipei')::time;
    new.sleep_time:=to_char(new.bedtime,'HH24:MI');
    new.morning_wake_time:=to_char(new.final_wake_time,'HH24:MI');
    new.wake_time:=to_char(new.out_of_bed_time,'HH24:MI');
    new.sleep_time_ampm:=null;
    new.time_review_status:='verified';
  end if;
  new.updated_at:=now();
  return new;
end $$;
revoke all on function public.validate_sleep_log_v2() from public,anon,authenticated;
create trigger validate_sleep_log_v2 before insert or update on public.sleep_logs for each row execute function public.validate_sleep_log_v2();

create table public.research_devices (
 id uuid primary key default gen_random_uuid(), member_id text not null references public.research_participants(member_id),
 source text not null, external_device_id text not null, metadata jsonb not null default '{}',
 unique(member_id,source,external_device_id), unique(id,member_id)
);
create table public.data_imports (
 id uuid primary key default gen_random_uuid(), member_id text not null references public.research_participants(member_id),
 source text not null, payload_hash text not null, raw_payload jsonb not null,
 algorithm_version text not null, status text not null check(status in ('success','failed')),
 error_message text, session_count integer not null default 0, metric_count integer not null default 0,
 imported_at timestamptz not null default now(), unique(member_id,source,payload_hash), unique(id,member_id)
);
create table public.sleep_sessions (
 id uuid primary key default gen_random_uuid(), member_id text not null references public.research_participants(member_id),
 source text not null, external_session_id text not null, sleep_date date not null,
 sleep_log_id bigint references public.sleep_logs(id), device_id uuid,
 device_external_id text, source_type text, start_at timestamptz not null, end_at timestamptz not null,
 sleep_onset_at timestamptz, final_wake_at timestamptz,
 tst_minutes numeric check(tst_minutes between 0 and 1440),
 light_minutes numeric check(light_minutes between 0 and 1440), deep_minutes numeric check(deep_minutes between 0 and 1440),
 rem_minutes numeric check(rem_minutes between 0 and 1440), other_sleep_minutes numeric check(other_sleep_minutes between 0 and 1440),
 awake_minutes numeric check(awake_minutes between 0 and 1440), waso_minutes numeric check(waso_minutes between 0 and 1440),
 awakening_count integer check(awakening_count>=0), raw_payload jsonb not null, units jsonb not null,
 metric_provenance jsonb not null default '{}', algorithm_version text not null, quality_status text not null,
 quality_issues jsonb not null default '[]', imported_at timestamptz not null default now(), import_id uuid,
 unique(member_id,source,external_session_id), unique(id,member_id),
 foreign key(device_id,member_id) references public.research_devices(id,member_id),
 foreign key(import_id,member_id) references public.data_imports(id,member_id),
 check(end_at>start_at and end_at-start_at<=interval '24 hours'),
 check(sleep_onset_at is null or sleep_onset_at between start_at and end_at),
 check(final_wake_at is null or final_wake_at between start_at and end_at),
 check(sleep_onset_at is null or final_wake_at is null or sleep_onset_at<=final_wake_at)
);
-- Match an explicitly linked diary to the same subject, never just the same ID.
alter table public.sleep_logs add constraint sleep_logs_id_member_v2 unique(id,member_id);
alter table public.sleep_sessions add foreign key(sleep_log_id,member_id) references public.sleep_logs(id,member_id);
create table public.sleep_stage_records (
 id uuid primary key default gen_random_uuid(), member_id text not null references public.research_participants(member_id),
 session_id uuid not null, ordinal integer not null, stage text not null check(stage in ('awake','light','deep','rem','nap','unclassified')),
 start_at timestamptz, end_at timestamptz, duration_minutes numeric check(duration_minutes>=0),
 raw_payload jsonb not null, quality_status text not null,
 foreign key(session_id,member_id) references public.sleep_sessions(id,member_id), unique(session_id,ordinal)
);
create table public.physiological_metrics (
 id uuid primary key default gen_random_uuid(), member_id text not null references public.research_participants(member_id),
 source text not null, external_record_id text not null, metric text not null,
 value double precision not null check(value<>'NaN'::float8 and value not in ('Infinity'::float8,'-Infinity'::float8)),
 unit text, measured_at timestamptz not null, signal_type text not null check(signal_type in ('PPG','ECG','unknown')),
 session_id uuid, device_id uuid, device_external_id text,
 scale_definition jsonb, algorithm_version text not null, raw_payload jsonb not null, quality_status text not null,
 import_id uuid, imported_at timestamptz not null default now(),
 unique(member_id,source,external_record_id,metric),
 foreign key(session_id,member_id) references public.sleep_sessions(id,member_id),
 foreign key(device_id,member_id) references public.research_devices(id,member_id),
 foreign key(import_id,member_id) references public.data_imports(id,member_id)
);
create table public.intervention_events (
 id uuid primary key default gen_random_uuid(), member_id text not null references public.research_participants(member_id),
 device_id uuid, session_id uuid, source text not null, external_event_id text not null,
 event_type text not null, started_at timestamptz not null, ended_at timestamptz,
 raw_payload jsonb not null, algorithm_version text not null, received_at timestamptz not null default now(),
 unique(member_id,source,external_event_id),
 foreign key(device_id,member_id) references public.research_devices(id,member_id),
 foreign key(session_id,member_id) references public.sleep_sessions(id,member_id),
 check(ended_at is null or ended_at>=started_at)
);
create index sessions_date_source on public.sleep_sessions(member_id,sleep_date,source);
create index stages_session_time on public.sleep_stage_records(session_id,start_at);
create index physiology_subject_time on public.physiological_metrics(member_id,measured_at,metric);
create index events_subject_time on public.intervention_events(member_id,started_at);
create index imports_subject_time on public.data_imports(member_id,imported_at);

do $$ declare t text; begin
 foreach t in array array['research_devices','data_imports','sleep_sessions','sleep_stage_records','physiological_metrics','intervention_events'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('create policy subject_read on public.%I for select to authenticated using (exists(select 1 from public.participant_access a where a.member_id=%I.member_id))',t,t);
  execute format('create policy subject_write on public.%I for insert to authenticated with check (exists(select 1 from public.participant_access a where a.member_id=%I.member_id and a.can_write))',t,t);
  execute format('create policy subject_update on public.%I for update to authenticated using (exists(select 1 from public.participant_access a where a.member_id=%I.member_id and a.can_write)) with check (exists(select 1 from public.participant_access a where a.member_id=%I.member_id and a.can_write))',t,t,t);
  execute format('grant select,insert,update on public.%I to authenticated',t);
  execute format('revoke all on public.%I from anon',t);
 end loop;
end $$;
-- Stage replacement is transactional; each distinct original payload stays in imports.
create policy stage_replace on public.sleep_stage_records for delete to authenticated using(exists(select 1 from public.participant_access a where a.member_id=sleep_stage_records.member_id and a.can_write));
grant delete on public.sleep_stage_records to authenticated;

create function public.import_research_data(p_member_id text,p_source text,p_sessions jsonb,p_metrics jsonb,p_raw jsonb,p_hash text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare imp uuid; sess uuid; r jsonb; s jsonb; n integer; dev uuid;
begin
 if not exists(select 1 from public.participant_access where user_id=(select auth.uid()) and member_id=p_member_id and can_write) then raise exception 'Not authorized'; end if;
 if jsonb_typeof(p_sessions)<>'array' or jsonb_typeof(p_metrics)<>'array' or jsonb_array_length(p_sessions)>1000 or jsonb_array_length(p_metrics)>50000 then raise exception 'Invalid batch'; end if;
 -- Serialize imports for this subject/source, including different revisions.
 perform pg_advisory_xact_lock(hashtextextended(p_member_id||':'||p_source,0));
 insert into public.data_imports(member_id,source,payload_hash,raw_payload,algorithm_version,status,session_count,metric_count)
 values(p_member_id,p_source,p_hash,p_raw,'vtca-import-2.0.0','success',jsonb_array_length(p_sessions),jsonb_array_length(p_metrics))
 on conflict(member_id,source,payload_hash) do update set imported_at=now()
 returning id into imp;
 for r in select value from jsonb_array_elements(p_sessions) loop
  dev:=null;
  if nullif(r->>'device_external_id','') is not null then
   insert into public.research_devices(member_id,source,external_device_id) values(p_member_id,p_source,r->>'device_external_id')
   on conflict(member_id,source,external_device_id) do update set metadata=research_devices.metadata returning id into dev;
  end if;
  insert into public.sleep_sessions(member_id,source,external_session_id,sleep_date,device_id,device_external_id,source_type,start_at,end_at,sleep_onset_at,final_wake_at,tst_minutes,light_minutes,deep_minutes,rem_minutes,other_sleep_minutes,awake_minutes,waso_minutes,awakening_count,raw_payload,units,metric_provenance,algorithm_version,quality_status,quality_issues,import_id)
  values(p_member_id,p_source,r->>'external_session_id',(r->>'sleep_date')::date,dev,r->>'device_external_id',r->>'source_type',(r->>'start_at')::timestamptz,(r->>'end_at')::timestamptz,(r->>'sleep_onset_at')::timestamptz,(r->>'final_wake_at')::timestamptz,(r->>'tst_minutes')::numeric,(r->>'light_minutes')::numeric,(r->>'deep_minutes')::numeric,(r->>'rem_minutes')::numeric,(r->>'other_sleep_minutes')::numeric,(r->>'awake_minutes')::numeric,(r->>'waso_minutes')::numeric,(r->>'awakening_count')::integer,r->'raw_payload',r->'units',r->'metric_provenance',r->>'algorithm_version',r->>'quality_status',r->'quality_issues',imp)
  on conflict(member_id,source,external_session_id) do update set
   sleep_date=excluded.sleep_date,device_id=excluded.device_id,device_external_id=excluded.device_external_id,source_type=excluded.source_type,start_at=excluded.start_at,end_at=excluded.end_at,sleep_onset_at=excluded.sleep_onset_at,final_wake_at=excluded.final_wake_at,tst_minutes=excluded.tst_minutes,light_minutes=excluded.light_minutes,deep_minutes=excluded.deep_minutes,rem_minutes=excluded.rem_minutes,other_sleep_minutes=excluded.other_sleep_minutes,awake_minutes=excluded.awake_minutes,waso_minutes=excluded.waso_minutes,awakening_count=excluded.awakening_count,raw_payload=excluded.raw_payload,units=excluded.units,metric_provenance=excluded.metric_provenance,algorithm_version=excluded.algorithm_version,quality_status=excluded.quality_status,quality_issues=excluded.quality_issues,imported_at=now(),import_id=excluded.import_id returning id into sess;
  delete from public.sleep_stage_records where session_id=sess;
  n:=0;
  for s in select value from jsonb_array_elements(coalesce(r->'stages','[]')) loop
   insert into public.sleep_stage_records(member_id,session_id,ordinal,stage,start_at,end_at,duration_minutes,raw_payload,quality_status)
   values(p_member_id,sess,n,s->>'stage',(s->>'start_at')::timestamptz,(s->>'end_at')::timestamptz,(s->>'duration_minutes')::numeric,s->'raw_payload',s->>'quality_status'); n:=n+1;
  end loop;
 end loop;
 for r in select value from jsonb_array_elements(p_metrics) loop
  insert into public.physiological_metrics(member_id,source,external_record_id,metric,value,unit,measured_at,signal_type,device_external_id,scale_definition,algorithm_version,raw_payload,quality_status,import_id)
  values(p_member_id,p_source,r->>'external_record_id',r->>'metric',(r->>'value')::float8,r->>'unit',(r->>'measured_at')::timestamptz,r->>'signal_type',r->>'device_external_id',r->'scale_definition',r->>'algorithm_version',r->'raw_payload',r->>'quality_status',imp)
  on conflict(member_id,source,external_record_id,metric) do update set value=excluded.value,unit=excluded.unit,measured_at=excluded.measured_at,raw_payload=excluded.raw_payload,quality_status=excluded.quality_status,algorithm_version=excluded.algorithm_version,signal_type=excluded.signal_type,scale_definition=excluded.scale_definition,device_external_id=excluded.device_external_id,import_id=excluded.import_id,imported_at=now();
 end loop;
 return jsonb_build_object('import_id',imp,'sessions',jsonb_array_length(p_sessions),'metrics',jsonb_array_length(p_metrics));
end $$;
revoke all on function public.import_research_data(text,text,jsonb,jsonb,jsonb,text) from public,anon;
grant execute on function public.import_research_data(text,text,jsonb,jsonb,jsonb,text) to authenticated;
commit;
