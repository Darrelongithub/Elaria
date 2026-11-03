/* Client regression gates: fake socket + deterministic deadlines, never a daemon/model. */
'use strict';
const assert = require('node:assert/strict');
const { load } = require('./harness.js');
(async () => {
  const c = await load();
  const w = c.window, shell = w.ElariaShell;
  const sockets = [], deadlines = [], retries = [];
  const originalTimer = w.setTimeout.bind(w);
  w.setTimeout = (callback, ms, ...args) => {
    if (ms === 45000) { deadlines.push(callback); return -1; }
    if (ms >= 700 && ms <= 15000) {
      retries.push({ callback, ms }); return -2;
    }
    return originalTimer(callback, ms, ...args);
  };
  class FakeSocket {
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(text) { this.sent.push(JSON.parse(text)); }
    open() { this.readyState = 1; this.onopen(); }
    message(message) { this.onmessage({ data: JSON.stringify(message) }); }
    close() { this.readyState = 3; this.onclose(); }
  }
  w.WebSocket = FakeSocket;
  let wire;
  try {
    assert.throws(() => shell.attachSocket('ws://remote.example/'), /localhost/);
    assert.equal(sockets.length, 0);
    wire = shell.attachSocket();
    await c.type('test before hello');
    assert(c.$('logpad').textContent.includes('no turn sent and no stub reply'));
    sockets[0].open();
    assert.equal(sockets[0].sent[0].t, 'hello');
    assert.equal(sockets[0].sent[0].v, 1);
    sockets[0].close();
    assert.equal(retries.at(-1).ms, 700);
    retries.at(-1).callback(); sockets[1].open(); sockets[1].close();
    assert.equal(retries.at(-1).ms, 1190); // TCP open must not reset handshake backoff
    for (let attempt = 2; attempt <= 10; attempt++) {
      retries.at(-1).callback();
      const failed = sockets.at(-1); failed.open(); failed.close();
      assert.equal(retries.at(-1).ms, Math.min(15000, 700 * Math.pow(1.7, attempt)));
    }
    retries.at(-1).callback();
    const socket = sockets.at(-1);
    socket.open(); socket.message({ t: 'hello-ok', v: 1, name: 'synthetic' });
    assert(shell.state.daemon);
    await c.type('synthetic request');
    const sent = socket.sent.find(x => x.t === 'send');
    assert(sent && sent.history.length <= 20);
    socket.message({ t: 'reply', id: sent.id + 1, text: 'WRONG-ID-REPLY' });
    assert(!c.$('logpad').textContent.includes('WRONG-ID-REPLY'));
    deadlines.at(-1)(); await c.tick(20);
    assert(c.$('logpad').textContent.includes('daemon went quiet'));
    socket.message({ t: 'reply', id: sent.id, text: 'ABANDONED-REPLY' });
    assert(!c.$('logpad').textContent.includes('ABANDONED-REPLY'));
    await c.type('x'.repeat(100000));
    assert(c.$('logpad').textContent.includes('64 KiB wire bound; no turn sent'));
    assert.equal(socket.sent.filter(x => x.t === 'send').length, 1);
    await c.type('explicit second turn');
    socket.close();
    await c.tick(20);
    assert(c.$('logpad').textContent.includes('a submitted turn may still complete'));
    assert.equal(retries.at(-1).ms, 700); // real hello-ok reset the backoff
    await c.type('/state idle');
    await c.type('after disconnection');
    assert(c.$('logpad').textContent.includes('no turn sent and no stub reply'));
    assert.equal(sockets.reduce((n, s) => n + s.sent.filter(x => x.t === 'send').length, 0), 2);
    wire.close();
    wire = shell.attachSocket();
    const bad = sockets.at(-1); bad.open(); bad.message({ t: 'hello-ok', v: 2 });
    assert(!shell.state.daemon);
    assert.equal(c.errors.length, 0);
    console.log('PASS: localhost gate, offline no-stub, version, same-ID, 45s abandonment, reconnect/no replay');
  } finally { if (wire) wire.close(); c.close(); }
})().then(() => process.exit(0), error => { console.error(error); process.exit(1); });
