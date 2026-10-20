-- 僅新增安全邀請與提交收據；不改寫或刪除既有研究紀錄。
begin;
set local lock_timeout = '5s';
create schema if not exists nsysu_private;
revoke all on schema nsysu_private from public, anon, authenticated;
grant usage on schema nsysu_private to anon, authenticated;

create table nsysu_private.diary_invitations (
 member_id text primary key references public.research_participants(member_id),
 token_hash bytea not null unique check(octet_length(token_hash)=32),
 expires_at timestamptz not null,
 issued_at timestamptz not null default now(),
 issued_by uuid not null references auth.users(id),
 revoked_at timestamptz
);
create table nsysu_private.diary_submission_receipts (
 member_id text not null references public.research_participants(member_id),
 request_id uuid not null,
 payload_hash bytea not null,
 created_at timestamptz not null default now(),
 primary key(member_id,request_id)
);
create index diary_receipts_recent on nsysu_private.diary_submission_receipts(member_id,created_at);
alter table nsysu_private.diary_invitations enable row level security;
alter table nsysu_private.diary_submission_receipts enable row level security;
revoke all on all tables in schema nsysu_private from public, anon, authenticated;

-- Definer 僅位於非公開 schema，使用固定路徑、明確授權與固定欄位；沒有通用查詢入口。
create function nsysu_private.issue_diary_invitation(p_member_id text,p_revoke boolean)
returns jsonb language plpgsql security definer set search_path='' as $$
declare token text; expires timestamptz;
begin
 if (select auth.uid()) is null or not exists(
  select 1 from public.participant_access a
  where a.user_id=(select auth.uid()) and a.member_id=p_member_id and a.can_write
 ) then raise exception 'Participant write grant required' using errcode='42501'; end if;
 if p_revoke then
  update nsysu_private.diary_invitations set revoked_at=clock_timestamp() where member_id=p_member_id;
  return jsonb_build_object('revoked',true);
 end if;
 -- 兩個加密亂數 UUID 提供 244 位元隨機性；資料庫只保存 SHA-256。
 token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');
 expires:=clock_timestamp()+interval '30 days';
 insert into nsysu_private.diary_invitations(member_id,token_hash,expires_at,issued_by)
 values(p_member_id,sha256(convert_to(token,'UTF8')),expires,(select auth.uid()))
 on conflict(member_id) do update set token_hash=excluded.token_hash,expires_at=excluded.expires_at,
 issued_by=excluded.issued_by,issued_at=clock_timestamp(),revoked_at=null;
 return jsonb_build_object('member_id',p_member_id,'invite',token,'expires_at',expires);
end $$;
revoke all on function nsysu_private.issue_diary_invitation(text,boolean) from public,anon,authenticated;
grant execute on function nsysu_private.issue_diary_invitation(text,boolean) to authenticated;
create function public.issue_diary_invitation(p_member_id text,p_revoke boolean default false)
returns jsonb language sql security invoker set search_path='' as $$
 select nsysu_private.issue_diary_invitation(p_member_id,p_revoke)
$$;
revoke all on function public.issue_diary_invitation(text,boolean) from public,anon,authenticated;
grant execute on function public.issue_diary_invitation(text,boolean) to authenticated;

create function nsysu_private.check_diary_invitation(p_member_id text,p_invite text)
returns boolean language sql stable security definer set search_path='' as $$
 select coalesce(p_invite ~ '^[a-f0-9]{64}$',false) and exists(
  select 1 from nsysu_private.diary_invitations i where i.member_id=p_member_id
  and i.token_hash=sha256(convert_to(p_invite,'UTF8'))
  and i.revoked_at is null and i.expires_at>now())
$$;
revoke all on function nsysu_private.check_diary_invitation(text,text) from public,anon,authenticated;
grant execute on function nsysu_private.check_diary_invitation(text,text) to anon,authenticated;
create function public.check_diary_invitation(p_member_id text,p_invite text)
returns boolean language sql stable security invoker set search_path='' as $$
 select nsysu_private.check_diary_invitation(p_member_id,p_invite)
$$;
revoke all on function public.check_diary_invitation(text,text) from public,anon,authenticated;
grant execute on function public.check_diary_invitation(text,text) to anon,authenticated;

create function nsysu_private.submit_invited_diary(p_invite text,p_entry jsonb,p_request_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $$
declare invitation nsysu_private.diary_invitations%rowtype; previous_hash bytea;
 fingerprint bytea; at_time timestamptz; hour_count bigint; day_count bigint;
begin
 if p_request_id is null or p_invite is null or p_invite !~ '^[a-f0-9]{64}$'
 then raise exception 'Invalid or expired invitation' using errcode='PT403'; end if;
 if p_entry is null or jsonb_typeof(p_entry)<>'object' or pg_column_size(p_entry)>12000
 then raise exception 'Invalid diary payload' using errcode='PT400'; end if;
 -- 同一受試者的發送、限流與收據在同一交易鎖內，輪替連結不會重設提交配額。
 select * into invitation from nsysu_private.diary_invitations i
 where i.member_id=p_entry->>'member_id' and i.token_hash=sha256(convert_to(p_invite,'UTF8')) for update;
 at_time:=clock_timestamp();
 if not found or invitation.revoked_at is not null or invitation.expires_at<=at_time
 then raise exception 'Invalid or expired invitation' using errcode='PT403'; end if;
 if p_entry - array['member_id','name','date','headphone_min','sleep_time','sleep_onset_min',
  'wakeup_count','fallback_sleep','disturbance','disturbance_scale','morning_wake_time','wake_time',
  'sleep_quality','bedtime_at','lights_out_at','final_wake_at','out_of_bed_at','date_definition',
  'timezone','wore_watch','sleep_medication','drank_alcohol','subjective_waso_minutes'] <> '{}'::jsonb
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
create function public.submit_invited_diary(p_invite text,p_entry jsonb,p_request_id uuid)
returns jsonb language sql security invoker set search_path='' as $$
 select nsysu_private.submit_invited_diary(p_invite,p_entry,p_request_id)
$$;
revoke all on function public.submit_invited_diary(text,jsonb,uuid) from public,anon,authenticated;
grant execute on function public.submit_invited_diary(text,jsonb,uuid) to anon,authenticated;

-- 收回可繞過邀請驗證的匿名直接 INSERT；既有研究者的 RLS 授權保持。
revoke insert on public.sleep_logs from anon;
drop policy if exists sleep_logs_public_insert on public.sleep_logs;
comment on function public.submit_invited_diary(text,jsonb,uuid) is
 'Write-only invite: scoped subject, 30-day expiry, revocation, 5/hour and 10/24h, idempotent retry; no history access.';
commit;
