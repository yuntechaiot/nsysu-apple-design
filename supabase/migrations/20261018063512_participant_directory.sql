-- Published invitations contain only pseudonymous codes, never names or health data.
-- The existing 50 invitation codes were already published by the original website.
alter table public.research_participants add column display_name text
  check (display_name is null or length(btrim(display_name)) between 1 and 80);

create table public.participant_invites (
  member_id text primary key references public.research_participants(member_id),
  created_at timestamptz not null default now()
);
alter table public.participant_invites enable row level security;
revoke all on public.participant_invites from anon, authenticated;
grant select(member_id) on public.participant_invites to anon, authenticated;
-- This public policy applies only to the explicitly published code directory.
-- It does not grant access to research_participants, sleep_logs or clinical data.
create policy published_invite_codes on public.participant_invites for select to anon, authenticated using (true);
insert into public.participant_invites(member_id)
  select member_id from public.research_participants on conflict do nothing;

-- Only project-owner-managed app_metadata may grant participant administration.
-- This role does NOT automatically grant access to existing participants' health data.
create policy participant_admin_read on public.research_participants for select to authenticated
  using (coalesce((select auth.jwt())->'app_metadata'->>'participant_admin', '') = 'true');
create policy participant_admin_create on public.research_participants for insert to authenticated
  with check ((select auth.uid()) is not null and coalesce((select auth.jwt())->'app_metadata'->>'participant_admin', '') = 'true');
create policy invite_admin_create on public.participant_invites for insert to authenticated
  with check ((select auth.uid()) is not null and coalesce((select auth.jwt())->'app_metadata'->>'participant_admin', '') = 'true');
create policy access_admin_create_own on public.participant_access for insert to authenticated
  with check (user_id = (select auth.uid()) and coalesce((select auth.jwt())->'app_metadata'->>'participant_admin', '') = 'true');
grant insert(member_id,display_name) on public.research_participants to authenticated;
grant insert(member_id) on public.participant_invites to authenticated;
grant insert(user_id,member_id,can_write) on public.participant_access to authenticated;

-- Transactional creation: duplicate IDs never overwrite an existing subject.
-- Invoker security retains RLS even if a caller bypasses the Flask API.
create function public.register_participant(p_member_id text, p_display_name text default null)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  member text := lower(btrim(p_member_id));
  label text := nullif(btrim(p_display_name), '');
begin
  if (select auth.uid()) is null or coalesce((select auth.jwt())->'app_metadata'->>'participant_admin', '') <> 'true' then
    raise exception 'Participant administrator required' using errcode = '42501';
  end if;
  if member is null or member !~ '^ycc[0-9]{8}$' or length(coalesce(label, '')) > 80 then
    raise exception 'Invalid participant code or display name' using errcode = '22023';
  end if;
  insert into public.research_participants(member_id, display_name) values(member, label);
  insert into public.participant_invites(member_id) values(member);
  insert into public.participant_access(user_id,member_id,can_write) values((select auth.uid()),member,true);
  return jsonb_build_object('member_id',member,'display_name',label);
end;
$$;
revoke all on function public.register_participant(text,text) from public, anon;
grant execute on function public.register_participant(text,text) to authenticated;
comment on table public.participant_invites is 'Public invitation codes only; names and clinical data remain private. QR access allows submission, never history access.';
