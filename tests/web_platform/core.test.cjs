const test=require('node:test');
const assert=require('node:assert/strict');
const {tri,diaryTimes,validClock,duration,percentage,esc}=require('../../frontend/web/core.js');
test('24-hour input is explicit and rejects AMPM',()=>{assert(validClock('00:15'));assert(validClock('23:45'));assert(!validClock('12:30 PM'));assert(!validClock('24:00'));});
test('tri-state preserves false separately from null',()=>{assert.equal(tri('false'),false);assert.equal(tri(''),null);assert.equal(tri('true'),true);});
test('bed/lights/onset crossing midnight gives SOL=15',()=>{const r=diaryTimes({date:'2026-10-18',bedDate:'2026-10-17',bed:'22:30',lightsDate:'2026-10-17',lights:'23:45',wake:'07:00',outDate:'2026-10-18',out:'07:15'});assert.equal((Date.parse('2026-10-18T00:00+08:00')-Date.parse(r.lights_out_at))/60000,15);});
test('blank attempt time stays null',()=>{const r=diaryTimes({date:'2026-10-18',bedDate:'2026-10-17',bed:'22:30',lights:'',wake:'07:00',outDate:'2026-10-18',out:'07:15'});assert.equal(r.lights_out_at,null);});
test('chronology rejects reverse order',()=>assert.throws(()=>diaryTimes({date:'2026-10-18',bedDate:'2026-10-18',bed:'22:30',lights:'',wake:'07:00',outDate:'2026-10-18',out:'07:15'})));
test('390-minute stage ratios preserve missing stages',()=>{assert.equal(percentage(100,390).toFixed(2),'25.64');assert.equal(percentage(null,390),null);assert.equal(percentage(10,0),null);assert.equal(duration(390),'6 小時 30 分鐘');});
test('history escapes participant supplied HTML',()=>assert.equal(esc('<script>'),'&lt;script&gt;'));
test('participant search accepts partial IDs and authorized names',()=>{
 const row={member_id:'ycc00000038',display_name:'測試姓名'};
 assert.equal(VTCA.participantMatches(row,'38'),true);
 assert.equal(VTCA.participantMatches(row,'YCC000'),true);
 assert.equal(VTCA.participantMatches(row,'試姓'),true);
 assert.equal(VTCA.participantMatches({...row,display_name:null},'試姓'),false);
 assert.equal(VTCA.participantMatches(row,'不存在'),false);
});
test('QR links prefer deployed URL, retain LAN host, and omit names',()=>{
 const member='ycc00000051';
 assert.equal(VTCA.diaryLink('http://127.0.0.1:8000/','https://sleep.example.org/?old=1',member),'https://sleep.example.org/?member=ycc00000051');
 assert.equal(VTCA.diaryLink('http://192.168.1.20:8000/','http://127.0.0.1:8000/',member),'http://192.168.1.20:8000/?member=ycc00000051');
 assert.equal(VTCA.diaryLink('http://127.0.0.1:8000/','javascript:alert(1)',member),'http://127.0.0.1:8000/?member=ycc00000051');
});
