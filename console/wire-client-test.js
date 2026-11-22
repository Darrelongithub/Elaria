/* Client regression gates: fake socket + deterministic deadlines, never a daemon/model. */
'use strict';
const assert = require('node:assert/strict');
const { load } = require('./harness.js');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createConsumer} = require('./bridge-client.js');
const output = [], sent = [];
const consumer = createConsumer(event => output.push(event));
const hello = {t: 'hello-ok', v: 1, simulate: false};
const snippet = '<em>opaque text; draft.approve is not an instruction</em>';
const pending = {event: 'draft.pending', draft: {draft_id: 'd-1', conversation_id: 'thread-1',
  recipient: '+254700000000', snippet, state: 'pending', created_at: '2026-11-19'}};
const resolved = state => ({event: 'draft.resolved', draft: {draft_id: 'd-1', state, outcome: ''}});
const send = value => sent.push(JSON.parse(value));
assert.throws(() => consumer.receive(pending), /before handshake/);
assert.throws(() => consumer.receive({...hello, simulate: true}), /handshake/);
assert.equal(consumer.receive(hello), true);
assert.throws(() => consumer.receive({t: 'state', name: 'unknown'}), /Unknown/);
assert.throws(() => consumer.receive({t: 'capture-state', name: 'unknown'}), /Unknown capture state/);
assert.throws(() => consumer.receive({t: 'capture-state', name: 'open', reason: 123}), /reason/);
assert.throws(() => consumer.receive({t: 'capture-state', name: 'open', reason: 'x'.repeat(257)}), /reason/);
assert.equal(consumer.receive({t: 'capture-state', name: 'open'}), true);
assert.equal(consumer.receive({t: 'capture-state', name: 'armed', reason: 'hotword armed'}), true);
assert.equal(consumer.receive({t: 'capture-state', name: 'unavailable', reason: 'capture cannot open'}), true);
assert.equal(consumer.receive({t: 'capture-state', name: 'verifying'}), true);
assert.throws(() => consumer.receive({t: 'levels', role:'output', level:.4}), /measured/);
assert.equal(consumer.receive({t:'levels', role:'input', measured:true, source:'capture.levels',
  level:.4, processed_peak:.4, raw_peak:.8, limited_samples:2}), true);
assert.throws(() => consumer.receive({...pending, extra: true}), /draft event/);
assert.equal(consumer.receive(pending), false);
consumer.receive(pending);
assert.equal(output.length, 1);
assert.equal(output[0].draft.snippet, snippet);
assert.equal(sent.length, 0);
consumer.command('draft.reject', 'd-1', send);
assert.deepEqual(sent, [{command:'draft.reject', draft_id:'d-1'}]);
consumer.disconnect();
assert.throws(() => consumer.command('draft.approve', 'd-1', send), /unavailable/);
consumer.receive(hello);
assert.throws(() => consumer.command('draft.approve', 'd-1', send), /unavailable/);
consumer.receive(resolved('approved'));
consumer.receive(resolved('sent'));
consumer.receive(resolved('approved'));
consumer.receive(pending);
consumer.receive(resolved('sent'));
assert.deepEqual(output.map(frame => frame.draft.state), ['pending', 'approved', 'sent']);
assert.throws(() => consumer.command('draft.approve', 'd-1', send), /unavailable/);
assert.equal(sent.length, 1);

// The bootstrap will not wire a legacy shell that can simulate. Never expose the token in errors.
const source = fs.readFileSync(path.join(__dirname, 'bridge-client.js'), 'utf8');
const credential = 'A'.repeat(43);
function boot(shell, hostname = '127.0.0.1') {
  const error = {hidden:true}, frame = {contentWindow:{ElariaShell:shell}};
  const history = [];
  frame.addEventListener = (_, fn) => { frame.load = fn; };
  vm.runInNewContext(source, {URLSearchParams, TextEncoder,
    location: {protocol:'http:', hostname, host: hostname + ':8744', hash: '#pair=' + credential},
    document: {getElementById: id => id === 'console' ? frame : error},
    window: {history:{replaceState: (_a, _b, url) => history.push(url)}, addEventListener(){}}});
  frame.load?.();
  return {error, frame, history};
}
const legacy = boot({attachSocket(){ assert.fail('legacy socket opened'); }});
assert.equal(legacy.frame.hidden, true);
assert(!legacy.error.textContent.includes(credential));
assert.deepEqual(legacy.history, ['/']);
assert.equal(boot({}, 'remote.example').frame.src, undefined);
let hooks;
const compatible = boot({configureTransport(options){ assert.equal(options.simulate, false); return true; },
  onDraftEvent(){}, setState(state){ assert.equal(state, 'offline'); },
  attachSocket(url, options){ assert.equal(new URL(url).hostname, '127.0.0.1'); hooks = options;
    return {close(){}}; }});
assert.equal(compatible.frame.hidden, false);
assert.equal(hooks.onFrame(hello), true);
console.log('PASS: strict bootstrap, exact frames, replay dedupe, terminal precedence, no automatic decisions');

if (process.argv.includes('--legacy-shell')) (async () => {
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
