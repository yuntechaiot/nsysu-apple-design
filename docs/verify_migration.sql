-- Read-only, no patient names or raw physiology in output.
select count(*) as diary_count from public.sleep_logs;
select count(*) as original_backup_count from vtca_private.sleep_logs_before_v2;
select count(*) as legacy_lights_must_remain_null from public.sleep_logs
where id in (select id from vtca_private.sleep_logs_before_v2) and lights_out_time is not null;
select count(*) as time_conflicts from public.sleep_logs where bedtime is null;
select count(*) as mapped_participants from public.research_participants where platform_user_id is not null;
select metric,count(*) as count from public.physiological_metrics group by metric order by metric;
select member_id,source,external_session_id,count(*) from public.sleep_sessions
group by member_id,source,external_session_id having count(*)>1;
select tablename,policyname,roles,cmd from pg_policies where schemaname='public';
select n.nspname,c.relname,c.relrowsecurity from pg_class c join pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and c.relkind='r';
