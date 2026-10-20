-- Combine directory SELECT predicates to avoid duplicate policy evaluation.
begin;
alter policy participant_read on public.research_participants using (
  coalesce((select auth.jwt())->'app_metadata'->>'participant_admin', '') = 'true'
  or exists(select 1 from public.participant_access a where a.member_id=research_participants.member_id)
);
drop policy participant_admin_read on public.research_participants;
commit;
