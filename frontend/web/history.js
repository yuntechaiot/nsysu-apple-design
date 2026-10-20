'use strict';
let historyParticipants=[], historyDirectoryRequest=0, historyLoadRequest=0;
function updateHistoryContext(){
 const row=historyParticipants.find(p=>p.member_id===currentMember);
 el('history-context').textContent=currentMember?'受試者 '+(row?participantLabel(row):currentMember)+' · 僅顯示已授權的紀錄':'從下拉選單選擇受試者，即可查看或修改過去的日誌。';
 el('history-new-diary').disabled=!currentMember||!!row?.archived_at;
}
function renderHistoryParticipants(){
 const select=el('history-member-select');select.replaceChildren();
 const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='請選擇受試者';select.appendChild(placeholder);
 historyParticipants.forEach(row=>{const option=document.createElement('option');option.value=row.member_id;option.textContent=participantLabel(row);select.appendChild(option);});
 // A history deep link may refer to an archived code absent from the public list.
 if(currentMember&&!historyParticipants.some(row=>row.member_id===currentMember)){
  const option=document.createElement('option');option.value=currentMember;option.textContent=currentMember;select.appendChild(option);
 }
 select.value=currentMember||'';updateHistoryContext();
}
function clearHistoryDirectory(){
 historyDirectoryRequest++;historyParticipants=[];renderHistoryParticipants();
 el('history-member-select').disabled=true;el('history-directory-status').textContent='';el('history-directory-retry').hidden=true;
}
async function loadHistoryParticipants(){
 const request=++historyDirectoryRequest,generation=authGeneration;
 el('history-member-select').disabled=true;el('history-directory-status').textContent='正在載入受試者清單…';el('history-directory-retry').hidden=true;
 try{
  const headers=await authHeaders();
  const response=await fetch('/api/participants'+(session?'?include_archived=1':''),{headers:headers.Authorization?{Authorization:headers.Authorization}:{}});
  const result=await response.json();if(!response.ok)throw Error(result.error||'無法載入受試者清單');
  if(request!==historyDirectoryRequest||generation!==authGeneration)return;
  historyParticipants=result.participants;renderHistoryParticipants();el('history-member-select').disabled=false;
  el('history-directory-status').textContent=`共 ${historyParticipants.length} 位受試者${session?' · 包含已移除、保留歷史的受試者':' · 登入後可查看已授權的姓名與日誌'}`;
 }catch(error){
  if(request!==historyDirectoryRequest||generation!==authGeneration)return;
  el('history-directory-status').textContent=error.message;el('history-directory-retry').hidden=false;
 }
}
function changeHistoryParticipant(){
 const mid=val('history-member-select')||null;
 if(mid&&!historyParticipants.some(row=>row.member_id===mid))return;
 if(mid!==currentMember&&dirty){
  if(!confirm('切換受試者會清除尚未送出的日誌內容，要繼續嗎？')){el('history-member-select').value=currentMember||'';return;}
  dirty=false;editingId=null;
 }
 currentMember=mid;setRoute('history',mid);updateHistoryContext();loadHistory();
}
