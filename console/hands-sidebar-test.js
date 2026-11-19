/* F21/F34 synthetic DOM: sidebar-only denials, private asks, no spoken/client playback. */
'use strict';
const assert=require('node:assert/strict');
const {load}=require('./harness.js');
(async()=>{
 const c=await load();const w=c.window,shell=w.ElariaShell;
 let focused=true, decisions=[], plays=0, ttl=120;
 Object.defineProperty(c.doc,'hasFocus',{value:()=>focused});
 w.Audio=function(){plays++;throw new Error('no spoken asks');};
 const envelope=()=>({instance:'a'.repeat(32),open:true,prompt_always:false,events:[
   {seq:1,phase:'DENIAL',reason:'irreversible-intent-refused'}],ask:{review_id:'review-one',digest:'b'.repeat(64),remaining_s:ttl,
   allow_always:false,plan:{steps:[{argv:['/usr/bin/mkdir','--','PRIVATE-TARGET'],cwd:'PRIVATE-CWD'}]}}});
 const control=async value=>{decisions.push(value);return {hands:{...envelope(),ask:null}};};
 shell.connect({send:async()=>({hands:envelope()}),handsControl:control});
 async function prepare(){await c.type('hands mkdir demo');await c.tick(750);}
 async function reveal(){const b=c.q('.hands-ask button');b.focus();await c.click(b);}
 try{
  await prepare();
  assert(c.q('.hands-ask').closest('#sb')); assert(!c.q('#logpad .hands-ask'));
  assert(c.$('hands-events').textContent.includes('irreversible-intent-refused'));
  assert(!c.$('logpad').textContent.includes('irreversible-intent-refused'));
  assert(!c.$('sb').textContent.includes('PRIVATE-TARGET'));
  focused=false;await reveal();assert(!c.$('sb').textContent.includes('PRIVATE-TARGET'));
  focused=true;await reveal();assert(c.$('sb').textContent.includes('PRIVATE-TARGET'));
  assert(!c.q('[data-hands-decision="allow-always"]'));
  w.dispatchEvent(new w.Event('blur'));assert(!c.$('sb').textContent.includes('PRIVATE-TARGET'));
  await reveal(); const yes=c.q('[data-hands-decision="allow-once"]');yes.focus();await c.click(yes);await c.click(yes);
  assert.equal(decisions.length,1);assert.equal(decisions[0].decision,'allow-once');
  assert.equal(decisions[0].review_id,'review-one');assert(!JSON.stringify(decisions).includes('PRIVATE'));
  await prepare();await reveal();const no=c.q('[data-hands-decision="deny"]');no.focus();await c.click(no);
  assert.equal(decisions.length,2);assert.equal(decisions[1].decision,'deny');
  await prepare();await c.type('yes');await c.tick(800);assert.equal(decisions.length,2);
  for(let i=0;i<w.localStorage.length;i++)assert(!w.localStorage.getItem(w.localStorage.key(i)).includes('PRIVATE-TARGET'));
  ttl=1;await prepare();await c.tick(1200);assert(!c.q('.hands-ask'));assert(c.$('hands-state').textContent.includes('expired'));
  ttl=120;await prepare();shell.disconnect();assert(!c.q('.hands-ask'));assert.equal(plays,0);
  assert.deepEqual(c.errors,[]);
  console.log('PASS F21/F34: silent private sidebar asks; once/No/focus/expiry/disconnect; denial never chat');
 }finally{c.close();}
 const d=await load();let wire;
 try{
  const sockets=[];
  class Socket {constructor(){this.readyState=1;this.sent=[];sockets.push(this);}send(x){this.sent.push(JSON.parse(x));}
   message(x){this.onmessage({data:JSON.stringify(x)});}close(){this.readyState=3;this.onclose();}}
  d.window.WebSocket=Socket;Object.defineProperty(d.doc,'hasFocus',{value:()=>true});
  wire=d.window.ElariaShell.attachSocket();const ws=sockets[0];ws.onopen();ws.message({t:'hello-ok',v:1});
  await d.type('hands mkdir demo');let send=ws.sent.find(m=>m.t==='send');
  ws.message({t:'reply',id:send.id,hands:envelope()});await d.tick(850);
  const reveal=d.q('.hands-ask button');reveal.focus();await d.click(reveal);
  const yes=d.q('[data-hands-decision="allow-once"]');yes.focus();await d.click(yes);
  const decision=ws.sent.find(m=>m.t==='hands-control');assert(decision);
  assert.deepEqual(Object.keys(decision).sort(),['action','decision','digest','id','review_id','t']);
  assert.equal(decision.action,'answer');assert(!JSON.stringify(decision).includes('PRIVATE'));
  ws.message({t:'reply',id:decision.id,hands_error:'synthetic outcome unknown; no replay'});await d.tick(50);
  assert(d.$('hands-state').textContent.includes('outcome unknown'));assert(!d.$('logpad').textContent.includes('outcome unknown'));
  console.log('PASS: real shell emits only the dedicated bound hands-decision frame');
 }finally{if(wire)wire.close();d.close();}
})().then(()=>process.exit(0),e=>{console.error(e);process.exit(1)});
