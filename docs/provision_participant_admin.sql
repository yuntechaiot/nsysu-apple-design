-- One-time setup, by the owner in the existing Sleep Log System SQL editor.
-- First create/invite the intended human in Supabase Authentication > Users.
-- Replace the email below with that verified account. Never run with a guessed identity.
-- This flag permits participant registration, not blanket access to clinical records.
begin;
do $$
declare
  researcher_email text := 'REPLACE_WITH_VERIFIED_ADMIN_EMAIL';
  researcher_id uuid;
begin
  select id into researcher_id from auth.users where lower(email)=lower(researcher_email);
  if researcher_id is null then
    raise exception 'Create the intended Supabase Auth user first and replace the email';
  end if;
  update auth.users set raw_app_meta_data=coalesce(raw_app_meta_data,'{}'::jsonb)
    || '{"participant_admin":true}'::jsonb where id=researcher_id;
end;
$$;
commit;
-- Sign out and sign in again so the JWT receives the owner-managed app_metadata.
-- Revoke later: remove only the participant_admin key and reauthenticate;
-- already-issued access tokens retain claims until refreshed/expired.
-- Existing participant_access grants are separate; revoke those explicitly if needed.
