begin;
set local lock_timeout = '5s';

-- Keep capability tokens encrypted in Vault. Browser roles can only request
-- their authorized subject's token through the narrow staff-only helper.
alter table nsysu_private.diary_invitations
 add column fixed_secret_id uuid unique references vault.secrets(id),
 add column legacy_token_hash bytea check(legacy_token_hash is null or octet_length(legacy_token_hash)=32),
 add column legacy_expires_at timestamptz;

create function nsysu_private.get_fixed_diary_invitation(p_member_id text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare prior nsysu_private.diary_invitations%rowtype; archived timestamptz;
 token text; secret_id uuid; member text:=lower(btrim(p_member_id));
begin
 if not (select nsysu_private.is_diary_staff()) or not exists(
  select 1 from public.participant_access a
  where a.user_id=(select auth.uid()) and a.member_id=member and a.can_write
 ) then raise exception 'Participant write grant required' using errcode='42501'; end if;
 select archived_at into archived from public.research_participants where member_id=member for update;
 if not found or archived is not null then
  raise exception 'Active participant required' using errcode='42501';
 end if;
 select * into prior from nsysu_private.diary_invitations where member_id=member for update;
 if prior.fixed_secret_id is null then
  token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');
  secret_id:=vault.create_secret(token,'nsysu_diary_fixed_'||member,'Fixed write-only diary QR capability');
  insert into nsysu_private.diary_invitations(member_id,token_hash,expires_at,issued_by,fixed_secret_id,legacy_token_hash,legacy_expires_at)
  values(member,sha256(convert_to(token,'UTF8')),'infinity'::timestamptz,(select auth.uid()),secret_id,
   case when prior.revoked_at is null and prior.expires_at>now() then prior.token_hash end,
   case when prior.revoked_at is null and prior.expires_at>now() then prior.expires_at end)
  on conflict(member_id) do update set token_hash=excluded.token_hash,expires_at=excluded.expires_at,
   issued_by=excluded.issued_by,issued_at=clock_timestamp(),revoked_at=null,
   fixed_secret_id=excluded.fixed_secret_id,legacy_token_hash=excluded.legacy_token_hash,legacy_expires_at=excluded.legacy_expires_at;
 else
  if prior.revoked_at is not null then raise exception 'Diary link is disabled' using errcode='42501'; end if;
  select decrypted_secret into token from vault.decrypted_secrets where id=prior.fixed_secret_id;
  if token is null or token !~ '^[a-f0-9]{64}$' or sha256(convert_to(token,'UTF8'))<>prior.token_hash then
   raise exception 'Fixed link unavailable' using errcode='PT503';
  end if;
 end if;
 return jsonb_build_object('member_id',member,'invite',token,'fixed',true,'expires_at',null);
end $$;
revoke all on function nsysu_private.get_fixed_diary_invitation(text) from public,anon,authenticated;
grant execute on function nsysu_private.get_fixed_diary_invitation(text) to authenticated;
create function public.get_fixed_diary_invitation(p_member_id text)
returns jsonb language sql security invoker set search_path='' as $$
 select nsysu_private.get_fixed_diary_invitation(p_member_id)
$$;
revoke all on function public.get_fixed_diary_invitation(text) from public,anon,authenticated;
grant execute on function public.get_fixed_diary_invitation(text) to authenticated;

-- Old open staff pages also receive the stable token instead of rotating it.
create or replace function nsysu_private.issue_diary_invitation(p_member_id text,p_revoke boolean)
returns jsonb language plpgsql security definer set search_path='' as $$
begin
 if p_revoke is null then raise exception 'Invalid invitation operation' using errcode='22023'; end if;
 if not p_revoke then return nsysu_private.get_fixed_diary_invitation(p_member_id); end if;
 if not (select nsysu_private.is_diary_staff()) or not exists(
  select 1 from public.participant_access a
  where a.user_id=(select auth.uid()) and a.member_id=p_member_id and a.can_write
 ) then raise exception 'Participant write grant required' using errcode='42501'; end if;
 perform 1 from public.research_participants where member_id=p_member_id for update;
 if not found then raise exception 'Participant not found' using errcode='22023'; end if;
 update nsysu_private.diary_invitations set revoked_at=clock_timestamp(),legacy_token_hash=null,legacy_expires_at=null where member_id=p_member_id;
 return jsonb_build_object('revoked',true);
end $$;

create or replace function nsysu_private.check_diary_invitation(p_member_id text,p_invite text)
returns boolean language sql stable security definer set search_path='' as $$
 select coalesce(p_invite ~ '^[a-f0-9]{64}$',false) and exists(
  select 1 from nsysu_private.diary_invitations i
  join public.research_participants p on p.member_id=i.member_id
  where i.member_id=p_member_id and p.archived_at is null and i.revoked_at is null
  and ((i.token_hash=sha256(convert_to(p_invite,'UTF8')) and i.expires_at>now())
   or (i.legacy_token_hash=sha256(convert_to(p_invite,'UTF8')) and i.legacy_expires_at>now())))
$$;


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
 where i.member_id=p_entry->>'member_id'
  and ((i.token_hash=sha256(convert_to(p_invite,'UTF8')) and i.expires_at>clock_timestamp())
   or (i.legacy_token_hash=sha256(convert_to(p_invite,'UTF8')) and i.legacy_expires_at>clock_timestamp())) for update;
 at_time:=clock_timestamp();
 if not found or invitation.revoked_at is not null or invitation.expires_at<=at_time
  or not exists(select 1 from public.research_participants p where p.member_id=invitation.member_id and p.archived_at is null)
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

create or replace function nsysu_private.manage_research_participant(p_member_id text,p_display_name text,p_action text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare member text:=lower(btrim(p_member_id)); label text:=nullif(btrim(p_display_name),''); result jsonb;
begin
 if not (select nsysu_private.is_diary_staff()) then
  raise exception 'Diary administrator required' using errcode='42501';
 end if;
 if member is null or member !~ '^ycc[0-9]{8}$' or p_action is null or p_action not in ('update','archive','restore') or length(coalesce(label,''))>80 then
  raise exception 'Invalid participant operation' using errcode='22023';
 end if;
 perform 1 from public.research_participants where member_id=member for update;
 if not found then raise exception 'Participant not found' using errcode='22023'; end if;
 if p_action='update' then
  update public.research_participants set display_name=label where member_id=member;
 elsif p_action='archive' then
  update public.research_participants set archived_at=coalesce(archived_at,now()) where member_id=member;
  update nsysu_private.diary_invitations set revoked_at=now(),legacy_token_hash=null,legacy_expires_at=null where member_id=member;
  delete from public.participant_invites where member_id=member;
 else
  update public.research_participants set archived_at=null where member_id=member;
  update nsysu_private.diary_invitations set revoked_at=null where member_id=member and fixed_secret_id is not null;
  insert into public.participant_invites(member_id) values(member) on conflict do nothing;
 end if;
 select jsonb_build_object('member_id',p.member_id,'display_name',p.display_name,'archived_at',p.archived_at)
 into result from public.research_participants p where p.member_id=member;
 return result;
end;
$$;

commit;
