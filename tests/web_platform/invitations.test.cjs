const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const code=fs.readFileSync(require.resolve('../../frontend/web/invitations.js'),'utf8');
function client(handler){
 let next=0;const calls=[];
 const context=vm.createContext({Map,JSON,Error,authGeneration:0,session:{user:{id:'synthetic'}},crypto:{randomUUID:()=>`request-${++next}`},config:{supabase_url:'https://project.supabase.co'},authHeaders:async()=>({apikey:'sb_publishable_SYNTHETIC'}),fetch:async(url,options)=>{calls.push(JSON.parse(options.body));return handler(url,options,calls.length);}});
 vm.runInContext(code,context);
 vm.runInContext("invitationMember='ycc00000001';invitationToken='a'.repeat(64)",context);
 return {context,calls};
}
const row={member_id:'ycc00000001',name:'SYNTHETIC'};
const ok=()=>new Response(JSON.stringify({status:'success'}),{status:200});
test('network retry keeps the same idempotency identifier',async()=>{
 const {context,calls}=client((url,options,n)=>{assert(url.endsWith('/rpc/submit_invited_diary'));if(n===1)throw Error('network interrupted');return ok();});
 await assert.rejects(context.submitInvitedDiary(row));await context.submitInvitedDiary(row);
 assert.equal(calls[0].p_request_id,calls[1].p_request_id);assert.equal(calls[1].p_invite,'a'.repeat(64));
 await context.submitInvitedDiary(row);assert.notEqual(calls[2].p_request_id,calls[1].p_request_id);
});
test('changed payload after a failed request gets a different identifier',async()=>{
 const {context,calls}=client((url,options,n)=>{if(n===1)throw Error('network interrupted');return ok();});
 await assert.rejects(context.submitInvitedDiary(row));await context.submitInvitedDiary({...row,name:'CHANGED'});
 assert.notEqual(calls[0].p_request_id,calls[1].p_request_id);
});
test('a subject code alone cannot submit and tokens cannot be used for another subject',async()=>{
 const {context,calls}=client(()=>assert.fail('must not request'));
 await assert.rejects(context.submitInvitedDiary({...row,member_id:'ycc00000002'}));
 vm.runInContext('invitationToken=null',context);await assert.rejects(context.submitInvitedDiary(row));assert.equal(calls.length,0);
});
test('server throttling and revoked links show actionable errors',async()=>{
 for(const [status,message] of [[429,/每小時最多 5 筆/],[403,/填寫連結已失效/]]){
  const {context}=client(()=>new Response('{}',{status}));await assert.rejects(context.submitInvitedDiary(row),message);
 }
});
test('concurrent fixed QR lookups share a single authenticated request',async()=>{
 const {context,calls}=client(url=>{assert(url.endsWith('/rpc/get_fixed_diary_invitation'));return new Response(JSON.stringify({member_id:row.member_id,invite:'b'.repeat(64),fixed:true,expires_at:null}));});
 const [first,second]=await Promise.all([context.loadFixedInvitation(row.member_id),context.loadFixedInvitation(row.member_id)]);
 assert.equal(first.invite,second.invite);assert.equal(calls.length,1);
});
test('an outstanding QR lookup cannot cache a secret after logout',async()=>{
 let respond,started;const ready=new Promise(resolve=>started=resolve);
 const {context}=client(()=>new Promise(resolve=>{respond=resolve;started();}));
 const pending=context.loadFixedInvitation(row.member_id);await ready;
 context.authGeneration=1;context.session=null;
 respond(new Response(JSON.stringify({member_id:row.member_id,invite:'b'.repeat(64),fixed:true})));
 await assert.rejects(pending,/登入狀態已變更/);
 assert.equal(vm.runInContext('invitationCache.size',context),0);
});
