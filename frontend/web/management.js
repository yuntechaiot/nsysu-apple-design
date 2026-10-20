'use strict';
let pendingManagement=null;
function closeManagementDialog(){el('management-dialog')?.close();pendingManagement=null;}
function showManagement(action,member,id=null){
 if(!session){openAuth();return;}
 pendingManagement={action,member,id,user:session.user.id};
 el('management-status').textContent='';el('management-name-row').hidden=action!=='update';
 const titles={update:'修改受試者姓名',archive:'移除受試者',restore:'還原受試者',deleteDiary:'刪除這筆日誌'};
 el('management-title').textContent=titles[action];
 if(action==='deleteDiary'){
  const row=records.find(r=>r.id===id&&r.member_id===member);if(!row){pendingManagement=null;return;}
  el('management-description').textContent=`受試者 ${member}，日期 ${row.date}，姓名 ${row.name}。確認後將永久刪除這一筆日誌，其他紀錄不受影響。`;
 }else{
  const row=participants.find(p=>p.member_id===member);if(!row){pendingManagement=null;return;}
  el('management-name').value=row.display_name||'';
  el('management-description').textContent=action==='archive'?`將 ${member} 從使用中清單移除並停用填寫 QR。既有日誌與研究資料保留，可在「顯示已移除的受試者」還原。`:action==='restore'?`還原 ${member} 後，會恢復這位受試者的原固定 QR Code。`:`受試者編號 ${member} 保持不變。`;
 }
 el('management-confirm').textContent=action==='deleteDiary'?'確認刪除日誌':action==='archive'?'確認移除':action==='restore'?'確認還原':'儲存姓名';
 el('management-confirm').className='btn '+(['deleteDiary','archive'].includes(action)?'btn-danger':'btn-primary');
 el('management-dialog').showModal();
}
function deleteDiary(id){if(currentMember)showManagement('deleteDiary',currentMember,id);}
function manageParticipant(action){if(selectedParticipant)showManagement(action,selectedParticipant.member_id);}
async function confirmManagement(event){
 event.preventDefault();const pending=pendingManagement;if(!pending||!session||session.user.id!==pending.user){closeManagementDialog();return;}
 const button=el('management-confirm');button.disabled=true;
 try{
  if(pending.action==='deleteDiary'){
   const deleted=await sbFetch('/sleep_logs?id=eq.'+encodeURIComponent(pending.id)+'&member_id=eq.'+encodeURIComponent(pending.member),{method:'DELETE'});
   if(!deleted?.length)throw Error('沒有刪除任何日誌，請重新整理後再試。');
   closeManagementDialog();if(currentMember===pending.member)await loadHistory();showToast('這筆日誌已刪除');
  }else{
   await diaryRPC('manage_research_participant',{p_member_id:pending.member,p_display_name:val('management-name').trim()||null,p_action:pending.action});
   if(pending.action!=='update'){
    invitationCache.delete(pending.member);
    if(invitationMember===pending.member){invitationMember=null;invitationToken=null;}
   }
   closeManagementDialog();await loadParticipants();showToast(pending.action==='update'?'姓名已更新':pending.action==='archive'?'受試者已移除，歷史資料保留':'受試者已還原，固定 QR Code 已恢復');
  }
 }catch(error){el('management-status').textContent=error.message;}finally{button.disabled=false;}
}
