begin;
set local lock_timeout = '5s';

-- The web form also sends five derived clock/review fields from diaryTimes().
-- Accept those keys for existing open forms, but never trust their values:
-- validate_sleep_log_v2 derives them from the validated Taiwan timestamps.
create or replace function nsysu_private.submit_invited_diary(p_invite text,p_entry jsonb,p_request_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $$
declare invitation nsysu_private.diary_invitations%rowtype; previous_hash bytea;
 fingerprint bytea; at_time timestamptz; hour_count bigint; day_count bigint;
begin
 if p_request_id is null or p_invite is null or p_invite !~ '^[a-f0-9]{64}$'
 then raise exception 'Invalid or expired invitation' using errcode='PT403'; end if;
 if p_entry is null or jsonb_typeof(p_entry)<>'object' or pg_column_size(p_entry)>12000
 then raise exception 'Invalid diary payload' using errcode='PT400'; end if;
 select * into invitation from nsysu_private.diary_invitations i
 where i.member_id=p_entry->>'member_id' and i.token_hash=sha256(convert_to(p_invite,'UTF8')) for update;
 at_time:=clock_timestamp();
 if not found or invitation.revoked_at is not null or invitation.expires_at<=at_time
 then raise exception 'Invalid or expired invitation' using errcode='PT403'; end if;
 if p_entry - array['member_id','name','date','headphone_min','sleep_time','sleep_onset_min',
  'wakeup_count','fallback_sleep','disturbance','disturbance_scale','morning_wake_time','wake_time',
  'sleep_quality','bedtime_at','lights_out_at','final_wake_at','out_of_bed_at','date_definition',
  'timezone','wore_watch','sleep_medication','drank_alcohol','subjective_waso_minutes',
  'bedtime','lights_out_time','final_wake_time','out_of_bed_time','time_review_status'] <> '{}'::jsonb
  or coalesce(p_entry->>'date_definition','')<>'wake_date'
  or coalesce(p_entry->>'timezone','Asia/Taipei')<>'Asia/Taipei'
  or coalesce(length(btrim(p_entry->>'name')),0) not between 1 and 80
  or coalesce(length(p_entry->>'disturbance'),0) not between 1 and 500
  or coalesce(length(p_entry->>'fallback_sleep'),0) not between 1 and 60
  or (p_entry->>'headphone_min')::int not between 0 and 600
  or (p_entry->>'sleep_onset_min')::int not between 0 and 300
  or (p_entry->>'wakeup_count')::int not between 0 and 20
 then raise exception 'Invalid diary payload' using errcode='PT400'; end if;
 fingerprint:=sha256(convert_to(p_entry::text,'UTF8'));
 select r.payload_hash into previous_hash from nsysu_private.diary_submission_receipts r
 where r.member_id=invitation.member_id and r.request_id=p_request_id;
 if found then
  if previous_hash<>fingerprint then raise exception 'Request already used' using errcode='PT409'; end if;
  return jsonb_build_object('status','success','duplicate_request',true);
 end if;
 select count(*) filter(where r.created_at>at_time-interval '1 hour'),count(*)
 into hour_count,day_count from nsysu_private.diary_submission_receipts r
 where r.member_id=invitation.member_id and r.created_at>at_time-interval '24 hours';
 if hour_count>=5 or day_count>=10
 then raise exception 'Submission limit reached; try later' using errcode='PT429'; end if;
 insert into public.sleep_logs(member_id,name,date,headphone_min,sleep_time,sleep_onset_min,
  wakeup_count,fallback_sleep,disturbance,disturbance_scale,morning_wake_time,wake_time,sleep_quality,
  bedtime_at,lights_out_at,final_wake_at,out_of_bed_at,date_definition,timezone,
  wore_watch,sleep_medication,drank_alcohol,subjective_waso_minutes)
 values(invitation.member_id,btrim(p_entry->>'name'),p_entry->>'date',(p_entry->>'headphone_min')::int,
  p_entry->>'sleep_time',(p_entry->>'sleep_onset_min')::int,(p_entry->>'wakeup_count')::int,
  p_entry->>'fallback_sleep',p_entry->>'disturbance',(p_entry->>'disturbance_scale')::int,
  p_entry->>'morning_wake_time',p_entry->>'wake_time',(p_entry->>'sleep_quality')::int,
  (p_entry->>'bedtime_at')::timestamptz,(p_entry->>'lights_out_at')::timestamptz,
  (p_entry->>'final_wake_at')::timestamptz,(p_entry->>'out_of_bed_at')::timestamptz,'wake_date','Asia/Taipei',
  (p_entry->>'wore_watch')::boolean,(p_entry->>'sleep_medication')::boolean,
  (p_entry->>'drank_alcohol')::boolean,(p_entry->>'subjective_waso_minutes')::numeric);
 insert into nsysu_private.diary_submission_receipts(member_id,request_id,payload_hash,created_at)
 values(invitation.member_id,p_request_id,fingerprint,at_time);
 return jsonb_build_object('status','success','duplicate_request',false);
end $$;
revoke all on function nsysu_private.submit_invited_diary(text,jsonb,uuid) from public,anon,authenticated;
grant execute on function nsysu_private.submit_invited_diary(text,jsonb,uuid) to anon,authenticated;

commit;
