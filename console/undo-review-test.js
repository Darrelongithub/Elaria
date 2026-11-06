/* Synthetic adapter + real DOM: focus, privacy, lifetime, no persistence or chat approval. */
'use strict';
const assert=require('node:assert/strict');
const {load}=require('./harness.js');
(async()=>{
 const c=await load();
 let focused=true, remaining=600, decisions=[], chats=[];
 Object.defineProperty(c.doc,'hasFocus',{value:()=>focused});
 function response(){return {text:'review',undoReview:{review_id:'opaque-review',ask_sha256:'a'.repeat(64),
  prepared_at:'synthetic wall clock',age_s:3,remaining_s:remaining,
  snapshot:{op_id:41,plan_id:4,op:'move',ts:'synthetic',status:'committed',
   src:'PRIVATE-ORIGINAL <img src=x onerror=alert(1)>',dst:'PRIVATE-CURRENT',
   sha256_before:'b'.repeat(64),sha256_after:'b'.repeat(64)}}};}
 const adapter={send:async text=>{chats.push(text);return response();},
   decideUndo:async value=>{decisions.push(value);return {text:'already answered'};}};
 async function prepare(){if(!c.window.ElariaShell.state.daemon)c.window.ElariaShell.connect(adapter);await c.type('undo review #41');await c.tick(1100);}
 async function reveal(){const b=c.q('.undo-review button');b.focus();await c.click(b);}
 try{
  await prepare();
  assert(c.q('.undo-review'));assert(!c.q('.undo-review').textContent.includes('PRIVATE-ORIGINAL'));
  focused=false;await reveal();assert(!c.q('.undo-review').textContent.includes('PRIVATE-ORIGINAL'));
  focused=true;await reveal();
  assert(c.q('.undo-review').textContent.includes('PRIVATE-ORIGINAL'));
  assert(!c.q('.undo-review img'));assert(c.q('.undo-age').textContent.includes('Ask age:'));
  for(let i=0;i<c.window.localStorage.length;i++) assert(!c.window.localStorage.getItem(c.window.localStorage.key(i)).includes('PRIVATE-'));
  c.window.dispatchEvent(new c.window.Event('blur'));assert(!c.q('.undo-review').textContent.includes('PRIVATE-'));
  await reveal();
  const yes=c.q('[data-decision="yes"]');yes.focus();await c.click(yes);await c.click(yes);
  assert.equal(decisions.length,1);assert.equal(decisions[0].decision,'yes');assert(!c.q('.undo-review'));
  await prepare();await reveal();
  const input=c.q('.undo-review input');input.focus();input.value=' yes please ';
  input.dispatchEvent(new c.window.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
  assert.equal(decisions.length,1);
  input.value=' NO ';input.dispatchEvent(new c.window.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
  await c.tick(40);assert.equal(decisions.length,2);assert.equal(decisions[1].decision,'no');
  assert(!c.q('.undo-review'));
  // Chat text is never a decision, even the literal word yes.
  await c.type('yes');await c.tick(1100);assert.equal(decisions.length,2);assert.equal(chats.at(-1),'yes');
  c.window.ElariaShell.disconnect();assert(!c.q('.undo-review'));
  remaining=2;await prepare();await c.tick(1300);
  assert(!c.q('.undo-review'));assert(c.$('logpad').textContent.includes('lapsed'));
  assert.equal(decisions.length,2);
  assert.deepEqual(c.errors,[]);
  console.log('PASS: private focus, safe snapshot, no storage, single Yes/No, no chat approval, expiry/disconnect');
 }finally{c.close();}
})().then(async()=>{
 const c=await load();const sockets=[];let wire;
 Object.defineProperty(c.doc,'hasFocus',{value:()=>true});
 class FakeSocket {
  constructor(){this.readyState=0;this.sent=[];sockets.push(this);}
  send(text){this.sent.push(JSON.parse(text));}
  close(){this.readyState=3;this.onclose();}
 }
 c.window.WebSocket=FakeSocket;
 try{
  wire=c.window.ElariaShell.attachSocket();const socket=sockets[0];
  socket.readyState=1;socket.onopen();
  const emit=m=>socket.onmessage({data:JSON.stringify(m)});
  emit({t:'hello-ok',v:1,name:'synthetic pilot'});
  await c.type('undo since 2h');const sent=socket.sent.find(m=>m.t==='send');
  emit({t:'reply',id:sent.id,text:'review',undo_review:{review_id:'synthetic-review',
   ask_sha256:'a'.repeat(64),prepared_at:'synthetic',age_s:0,remaining_s:600,
   snapshot:{op_id:41,plan_id:4,op:'move',ts:'synthetic',status:'committed',src:'private-original',dst:'private-current',sha256_before:null,sha256_after:null}}});
  await c.tick(1000);const reveal=c.q('.undo-review button');reveal.focus();await c.click(reveal);
  const no=c.q('[data-decision="no"]');no.focus();await c.click(no);
  const decision=socket.sent.find(m=>m.t==='undo-decision');
  assert(decision && decision.id>sent.id && decision.decision==='no');
  assert.deepEqual(Object.keys(decision).sort(),['ask_sha256','decision','id','review_id','t']);
  assert(!JSON.stringify(decision).includes('private-original'));
  emit({t:'reply',id:decision.id,text:'already answered'});await c.tick(20);
  assert(!c.q('.undo-review'));assert.deepEqual(c.errors,[]);
  console.log('PASS: real shell wire emits only the bound dedicated decision frame');
 }finally{if(wire)wire.close();c.close();}
}).then(()=>process.exit(0),e=>{console.error(e);process.exit(1)});
