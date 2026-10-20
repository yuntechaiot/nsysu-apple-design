-- 明確拒絕瀏覽器角色直接存取私有邀請資料；日誌 RPC 的擁有者權限不受影響。
begin;
create policy deny_direct_client_access on nsysu_private.diary_invitations
 as restrictive for all to anon,authenticated using (false) with check (false);
create policy deny_direct_client_access on nsysu_private.diary_submission_receipts
 as restrictive for all to anon,authenticated using (false) with check (false);
commit;
