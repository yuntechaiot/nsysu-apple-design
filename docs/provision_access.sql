-- Administrative example: run in the SAME Sleep Log System SQL editor.
-- First invite/create the intended human through Supabase Authentication UI.
-- Replace the email and subject with verified real identities. No self-enrollment.
begin;
insert into public.participant_access(user_id,member_id,can_write)
select u.id, 'ycc00000038', true from auth.users u
where lower(u.email)=lower('REPLACE_WITH_RESEARCHER_EMAIL')
on conflict(user_id,member_id) do update set can_write=excluded.can_write;
-- For an approved researcher with a documented mandate covering all subjects,
-- explicitly run this separate statement after replacing the email:
-- insert into public.participant_access(user_id,member_id,can_write)
-- select u.id,p.member_id,true from auth.users u cross join public.research_participants p
-- where lower(u.email)=lower('REPLACE_WITH_RESEARCHER_EMAIL')
-- on conflict(user_id,member_id) do update set can_write=excluded.can_write;
commit;
select count(*) as authorized_members from public.participant_access a
join auth.users u on a.user_id=u.id
where lower(u.email)=lower('REPLACE_WITH_RESEARCHER_EMAIL');
