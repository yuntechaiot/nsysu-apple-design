const test=require('node:test');
const assert=require('node:assert/strict');
const {diaryEmail}=require('../../frontend/web/core.js');
test('account aliases normalize without publishing a credential list',()=>{
 assert.equal(diaryEmail(' research_test '),'research_test@diary.nsysu.invalid');
 for(const value of ['', 'person@example.invalid','../admin','<script>','x'.repeat(33)])assert.throws(()=>diaryEmail(value));
});
