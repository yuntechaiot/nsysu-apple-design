begin;
create function public.diary_staff_status() returns boolean
language sql stable security invoker set search_path='' as $$
 select nsysu_private.is_diary_staff()
$$;
revoke all on function public.diary_staff_status() from public,anon,authenticated;
grant execute on function public.diary_staff_status() to authenticated;
commit;
