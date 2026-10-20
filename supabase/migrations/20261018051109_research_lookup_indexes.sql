begin;
set local lock_timeout='5s';
-- Cover composite subject/device/session foreign keys used for RLS and joins.
create index participant_access_member on public.participant_access(member_id,user_id);
create index sessions_device_member on public.sleep_sessions(device_id,member_id);
create index sessions_import_member on public.sleep_sessions(import_id,member_id);
create index sessions_diary_member on public.sleep_sessions(sleep_log_id,member_id);
create index stages_member on public.sleep_stage_records(member_id);
create index stages_session_member on public.sleep_stage_records(session_id,member_id,start_at);
create index metrics_device_member on public.physiological_metrics(device_id,member_id);
create index metrics_import_member on public.physiological_metrics(import_id,member_id);
create index metrics_session_member on public.physiological_metrics(session_id,member_id);
create index events_device_member on public.intervention_events(device_id,member_id);
create index events_session_member on public.intervention_events(session_id,member_id);
alter table vtca_private.sleep_logs_before_v2 add primary key(id);
alter table vtca_private.policies_before_v2 add primary key(schemaname,tablename,policyname);
commit;
