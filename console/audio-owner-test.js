/* F29 synthetic DOM/wire gate, not hardware audio evidence. */
'use strict';
const assert = require('node:assert/strict');
const {load} = require('./harness.js');
(async () => {
  const c = await load();
  let plays = 0, audioReads = 0, audioCreates = 0, wire;
  const w = c.window, shell = w.ElariaShell;
  w.Audio = function() { audioCreates++; throw new Error('client playback forbidden'); };
  w.HTMLMediaElement.prototype.play = function() { plays++; return Promise.resolve(); };
  try {
    const response = {text:'A synthetic text reply.'};
    Object.defineProperty(response, 'audio', {get() { audioReads++; throw new Error('must drop audio'); }});
    shell.connect({send:async () => response});
    await c.type('adapter reply'); await c.tick(1800);
    assert(c.$('logpad').textContent.includes(response.text));
    assert.equal(audioReads, 0);
    // Even an already constructed element must not be attached, retained or played.
    const element = c.doc.createElement('audio');
    shell.say({text:'Element reply', audio:element}); await c.tick(1200);
    assert(c.$('logpad').textContent.includes('Element reply'));
    assert.equal(c.q('audio'), null);
    const sockets = [];
    class Socket {
      constructor() { sockets.push(this); this.readyState=1; this.sent=[]; }
      send(data) {this.sent.push(JSON.parse(data));}
      message(data) {this.onmessage({data:JSON.stringify(data)});}
      close() {this.readyState=3; this.onclose();}
    }
    w.WebSocket=Socket;
    wire=shell.attachSocket(); const socket=sockets[0]; socket.onopen();
    socket.message({t:'hello-ok',v:1,name:'synthetic'});
    shell.setState('idle');
    socket.message({t:'state',name:'speaking'});
    assert.equal(shell.state.state,'idle');
    await c.type('wire reply');
    const sent=socket.sent.find(m=>m.t==='send');
    socket.message({t:'reply',id:sent.id,text:'Wire text only',audio:'https://invalid.example/must-not-fetch.wav'});
    await c.tick(80);
    assert.notEqual(shell.state.state,'speaking'); // reply/typewriter is not output levels on wire
    socket.message({t:'levels',role:'output',level:.4,source:'synthesised-text-cadence'});
    assert.equal(shell.state.state,'speaking');
    socket.message({t:'levels',role:'output',level:0});
    assert.notEqual(shell.state.state,'speaking');
    await c.tick(1200);
    assert(c.$('logpad').textContent.includes('Wire text only'));
    shell.levels('output',NaN); shell.levels('output',2); shell.setState('speaking');
    assert.notEqual(shell.state.state,'speaking');
    assert.equal(plays,0); assert.equal(audioCreates,0); assert.equal(audioReads,0);
    assert.equal(c.$('badge-audio').textContent,'pending');
    assert(c.$('orbnote').textContent.includes('synthesised text cadence, not measured audio'));
    assert(!w.localStorage.getItem('elaria.console.v6').includes('must-not-fetch'));
    assert.deepEqual(c.errors,[]);
    console.log('PASS F29: reply audio dropped; no playback; speaking only from levels; pane deferred');
  } finally {if(wire) wire.close(); c.close();}
})().then(()=>process.exit(0),err=>{console.error(err);process.exit(1);});
