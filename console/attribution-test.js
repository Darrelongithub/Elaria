/* Local renderer persistence/injection regression, not a daemon/model receipt proof. */
'use strict';
const assert = require('node:assert/strict');
const {load} = require('./harness.js');
(async()=>{
 const c=await load(); let restored;
 try {
  c.window.ElariaShell.say({text:'synthetic', attribution:[
   'Bridge observation: synthetic:1 (not a durable journal receipt).',
   'Daemon-reported hit text (unstructured): <img src=x onerror=alert(1)>',
   'Fact ID and kind: not supplied on this wire.'
  ]});
  await c.tick(700);
  const box=c.q('.msg.ai .attribution');
  assert(box && box.textContent.includes('not a durable journal'));
  assert(box.textContent.includes('<img') && !box.querySelector('img'));
  assert(!c.q('.msg.ai .body').textContent.includes('Bridge observation'));
  c.window.ElariaShell.connect({send:async()=>{
   throw Object.assign(new Error('synthetic refusal'), {attribution:['Execution unknown; no replay.']});
  }});
  await c.type('synthetic request'); await c.tick(700);
  assert(c.q('.msg.err .attribution').textContent.includes('Execution unknown'));
  const storage={}; for(let i=0;i<c.window.localStorage.length;i++) {
   const k=c.window.localStorage.key(i);storage[k]=c.window.localStorage.getItem(k);
  }
  restored=await load({storage});
  assert(restored.q('.attribution').textContent.includes('synthetic:1'));
  assert(restored.q('.msg.err .attribution').textContent.includes('Execution unknown'));
  assert.deepEqual(c.errors,[]); assert.deepEqual(restored.errors,[]);
  console.log('PASS: attribution separate, text-safe, persisted and restored');
 } finally {c.close(); if(restored) restored.close();}
})().then(()=>process.exit(0), e=>{console.error(e);process.exit(1)});
