begin;
set local lock_timeout = '5s';

-- Roles are provisioned through Auth Admin; clients cannot edit app_metadata.
create function nsysu_private.is_diary_staff() returns boolean
language sql stable security definer set search_path = '' as $$
 select (select auth.uid()) is not null and exists(
  select 1 from auth.users u where u.id=(select auth.uid())
   and u.raw_app_meta_data->>'diary_staff'='true' and u.deleted_at is null
   and (u.banned_until is null or u.banned_until < now())
 );
$$;
revoke all on function nsysu_private.is_diary_staff() from public,anon;
grant execute on function nsysu_private.is_diary_staff() to authenticated;

-- This website now uses the explicitly provisioned research staff accounts.
do $$ declare t text; begin
 foreach t in array array['research_participants','participant_access','participant_invites','sleep_logs','research_devices','data_imports','sleep_sessions','sleep_stage_records','physiological_metrics','intervention_events'] loop
  execute format('create policy diary_staff_guard on public.%I as restrictive for all to authenticated using ((select nsysu_private.is_diary_staff())) with check ((select nsysu_private.is_diary_staff()))',t);
 end loop;
end $$;

alter table public.research_participants add column archived_at timestamptz;

-- All enabled staff can manage existing subjects and future website additions.
insert into public.participant_access(user_id,member_id,can_write)
 select u.id,p.member_id,true from auth.users u cross join public.research_participants p
 where u.raw_app_meta_data->>'diary_staff'='true' and u.deleted_at is null
 on conflict(user_id,member_id) do update set can_write=true;

create function nsysu_private.assign_diary_staff_access() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
 insert into public.participant_access(user_id,member_id,can_write)
  select u.id,new.member_id,true from auth.users u
  where u.raw_app_meta_data->>'diary_staff'='true' and u.deleted_at is null
  on conflict(user_id,member_id) do nothing;
 return new;
end;
$$;
revoke all on function nsysu_private.assign_diary_staff_access() from public,anon,authenticated;
create trigger assign_diary_staff_access after insert on public.research_participants
 for each row execute function nsysu_private.assign_diary_staff_access();

create or replace function public.register_participant(p_member_id text,p_display_name text default null)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare member text:=lower(btrim(p_member_id)); label text:=nullif(btrim(p_display_name),'');
begin
 if not (select nsysu_private.is_diary_staff()) or coalesce((select auth.jwt())->'app_metadata'->>'participant_admin','')<>'true' then
  raise exception 'Diary administrator required' using errcode='42501';
 end if;
 if member is null or member !~ '^ycc[0-9]{8}$' or length(coalesce(label,''))>80 then
  raise exception 'Invalid participant details' using errcode='22023';
 end if;
 insert into public.research_participants(member_id,display_name) values(member,label);
 insert into public.participant_invites(member_id) values(member);
 insert into public.participant_access(user_id,member_id,can_write) values((select auth.uid()),member,true) on conflict do nothing;
 return jsonb_build_object('member_id',member,'display_name',label,'archived_at',null);
end;
$$;

grant delete on public.sleep_logs to authenticated;
create policy sleep_delete on public.sleep_logs for delete to authenticated
 using(exists(select 1 from public.participant_access a where a.member_id=sleep_logs.member_id and a.can_write));

-- Removing a subject preserves research data and revokes guest submission links.
create function nsysu_private.manage_research_participant(p_member_id text,p_display_name text,p_action text)
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
  update nsysu_private.diary_invitations set revoked_at=now() where member_id=member;
  delete from public.participant_invites where member_id=member;
 else
  update public.research_participants set archived_at=null where member_id=member;
  insert into public.participant_invites(member_id) values(member) on conflict do nothing;
 end if;
 select jsonb_build_object('member_id',p.member_id,'display_name',p.display_name,'archived_at',p.archived_at)
 into result from public.research_participants p where p.member_id=member;
 return result;
end;
$$;
revoke all on function nsysu_private.manage_research_participant(text,text,text) from public,anon;
grant execute on function nsysu_private.manage_research_participant(text,text,text) to authenticated;
create function public.manage_research_participant(p_member_id text,p_display_name text default null,p_action text default 'update')
returns jsonb language sql security invoker set search_path = '' as $$
 select nsysu_private.manage_research_participant(p_member_id,p_display_name,p_action);
$$;
revoke all on function public.manage_research_participant(text,text,text) from public,anon;
grant execute on function public.manage_research_participant(text,text,text) to authenticated;

-- Lock subjects before invitations, matching the removal operation's lock order.
create or replace function nsysu_private.issue_diary_invitation(p_member_id text,p_revoke boolean)
returns jsonb language plpgsql security definer set search_path='' as $$
declare token text; expires timestamptz; archived timestamptz;
begin
 if not (select nsysu_private.is_diary_staff()) or not exists(
  select 1 from public.participant_access a
  where a.user_id=(select auth.uid()) and a.member_id=p_member_id and a.can_write
 ) then raise exception 'Participant write grant required' using errcode='42501'; end if;
 select archived_at into archived from public.research_participants where member_id=p_member_id for update;
 if not found then raise exception 'Participant not found' using errcode='22023'; end if;
 if p_revoke then
  update nsysu_private.diary_invitations set revoked_at=clock_timestamp() where member_id=p_member_id;
  return jsonb_build_object('revoked',true);
 end if;
 if archived is not null then raise exception 'Restore participant before issuing a new link' using errcode='42501'; end if;
 token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');
 expires:=clock_timestamp()+interval '30 days';
 insert into nsysu_private.diary_invitations(member_id,token_hash,expires_at,issued_by)
 values(p_member_id,sha256(convert_to(token,'UTF8')),expires,(select auth.uid()))
 on conflict(member_id) do update set token_hash=excluded.token_hash,expires_at=excluded.expires_at,
 issued_by=excluded.issued_by,issued_at=clock_timestamp(),revoked_at=null;
 return jsonb_build_object('member_id',p_member_id,'invite',token,'expires_at',expires);
end $$;

commit;
