/* 專屬填寫連結：只允許新增，不提供讀取歷史的權限。 */
'use strict';
let invitationToken=null, invitationMember=null, invitationRequest=null;
const invitationCache=new Map();
const fixedInvitationLoads=new Map();
async function diaryRPC(name,payload){
 const response=await fetch(config.supabase_url+'/rest/v1/rpc/'+name,{method:'POST',headers:await authHeaders(),body:JSON.stringify(payload)});
 if(!response.ok){
  if(response.status===429)throw Error('這個填寫連結已達提交次數上限，請稍後再試；每小時最多 5 筆、24 小時最多 10 筆。');
  if(response.status===401)throw Error('登入已到期，請重新登入。');
  if(response.status===403)throw Error(['get_fixed_diary_invitation','issue_diary_invitation','manage_research_participant'].includes(name)?'這個帳號沒有此受試者的寫入授權，或受試者已移除／連結已停用。':'填寫連結已失效，請向研究團隊取得新的專屬連結。');
  throw Error('操作未完成，請核對填寫內容與連線後重試。');
 }
 return response.json();
}
function captureInvitation(params){
 const token=params.get('invite'),member=params.get('member');
 if(token&&/^[a-f0-9]{64}$/.test(token)&&/^ycc\d{8}$/.test(member||'')){invitationToken=token;invitationMember=member;}
}
async function ensureDiaryAccess(member){
 if(session)return true;
 if(invitationMember===member&&invitationToken){
  try{if(await diaryRPC('check_diary_invitation',{p_member_id:member,p_invite:invitationToken}))return true;}
  catch(error){goHome();showToast(error.message,'error');return false;}
  goHome();showToast('填寫連結已到期或停用，請向研究團隊取得新的專屬連結。','error');return false;
 }
 showMemberEntry('diary');currentMember=member;
 el('entry-error').textContent='請使用研究團隊提供的專屬 QR Code，或登入已授權的日誌帳號後填寫。';el('entry-error').hidden=false;
 postAuthAction='diary';openAuth();return false;
}
async function submitInvitedDiary(row){
 if(invitationMember!==row.member_id||!invitationToken)throw Error('請使用研究團隊提供的專屬填寫連結。');
 const content=JSON.stringify(row);
 if(!invitationRequest||invitationRequest.content!==content)invitationRequest={content,id:crypto.randomUUID()};
 const result=await diaryRPC('submit_invited_diary',{p_invite:invitationToken,p_entry:row,p_request_id:invitationRequest.id});
 if(result.status!=='success')throw Error('日誌尚未完成儲存，請重試。');
 invitationRequest=null;
}
async function loadFixedInvitation(mid){
 const generation=authGeneration;
 const pending=fixedInvitationLoads.get(mid);
 if(pending?.generation===generation)return pending.promise;
 const promise=(async()=>{
  const result=await diaryRPC('get_fixed_diary_invitation',{p_member_id:mid});
  if(!session||generation!==authGeneration)throw Error('登入狀態已變更，請重新選擇受試者。');
  if(result.fixed!==true||!/^[a-f0-9]{64}$/.test(result.invite||'')||result.member_id!==mid)throw Error('固定 QR Code 載入未完成，請重新選擇受試者。');
  invitationCache.set(mid,result);return result;
 })();
 fixedInvitationLoads.set(mid,{generation,promise});
 try{return await promise;}finally{if(fixedInvitationLoads.get(mid)?.promise===promise)fixedInvitationLoads.delete(mid);}
}
