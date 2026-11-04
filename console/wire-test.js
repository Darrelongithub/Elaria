/* Local-only DOM + real WS gate, launched by pytest against a synthetic Unix daemon.
   This proves wiring, NOT live-model answers, actual WebGL pixels or owner audio. */
'use strict';
const assert = require('node:assert/strict');
const { JSDOM, VirtualConsole, requestInterceptor } = require('jsdom');
// Same kind of 2D test double as harness.js, injected ONLY into this test DOM.
// WebGL stays unavailable; no pixel/hardware claim. Served/committed assets stay unchanged.
const canvasTestHook = requestInterceptor((request, { element }) => {
  if (new URL(request.url).pathname !== '/console' || !element?.contentWindow) return;
  element.contentWindow.HTMLCanvasElement.prototype.getContext = function(kind) {
    if (kind !== '2d') return null;
    return new Proxy({}, {get(target, key) {
      if (key in target) return target[key];
      if (key === 'createRadialGradient' || key === 'createLinearGradient') return () => ({addColorStop(){}});
      if (key === 'measureText') return () => ({width:10});
      return () => {};
    }, set(target,key,value) { target[key]=value; return true; }});
  };
  // Let the real HTTP request continue unchanged. No bytes or WS behavior replaced.
});
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, message) {
  for (let i = 0; i < 150; i++) { if (predicate()) return; await wait(50); }
  throw new Error(message);
}
(async () => {
  const vc = new VirtualConsole();
  const errors = [];
  vc.on('jsdomError', e => {
    if (!/Not implemented|Could not parse CSS/.test(e.message)) errors.push(e.message);
  });
  let dom;
  try {
    dom = await JSDOM.fromURL(process.env.ELARIA_TEST_URL, {
      resources: { interceptors: [canvasTestHook] }, runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc
    });
    const root = dom.window.document;
    const frame = root.getElementById('console');
    await until(() => frame.contentWindow.ElariaShell?.state.daemon, 'hello did not connect shell');
    const shell = frame.contentWindow.ElariaShell;
    const doc = frame.contentDocument;
    const seen = [];
    const levels = shell.levels;
    shell.levels = (role, value) => { seen.push({ role, value }); levels(role, value); };
    const composer = doc.querySelector('textarea');
    composer.value = 'hello wire';
    composer.form.dispatchEvent(new frame.contentWindow.Event('submit', { bubbles: true, cancelable: true }));
    await until(() => doc.getElementById('logpad').textContent.includes('Synthetic wire reply — not live model proof.'),
                'real WS reply did not appear in DOM');
    await until(() => seen.some(x => x.role === 'output' && x.value > 0), 'no synthesised wire output levels');
    assert(seen.every(x => x.value >= 0 && x.value <= 1));
    await until(() => doc.querySelector('.msg.ai .attribution'), 'missing reply attribution');
    assert(doc.querySelector('.attribution').textContent.includes('not a durable journal'));
    assert(doc.querySelector('.attribution').textContent.includes('live-model'));
    assert(!root.querySelector('header'));
    assert(root.getElementById('wire-error').hidden);
    assert(doc.getElementById('orbnote').textContent.includes('synthesised text cadence, not measured audio'));
    assert(doc.getElementById('orbnote').textContent.includes('text-only, no speech'));
    assert.equal(doc.querySelectorAll('.console-footer .lamps li').length, 4);
    assert(!doc.body.textContent.includes('driven by real levels'));
    assert(!root.body.textContent.includes('tabs share'));
    assert(!doc.body.textContent.includes('tabs share'));
    assert.equal(doc.getElementById('badge-transcript').textContent, 'pending');
    assert.equal(doc.getElementById('badge-audio').textContent, 'pending');
    assert(!doc.getElementById('logpad').textContent.includes('audio and memory now come from the daemon'));
    assert.throws(() => shell.attachSocket('ws://remote.example/elaria'), /localhost only/);
    assert.deepEqual(errors, []);
    console.log('PASS: real HTTP shell → WebSocket → synthetic Unix daemon → DOM reply/state/synthesised levels');
  } finally {
    if (dom) {
      dom.window.dispatchEvent(new dom.window.Event('pagehide'));
      dom.window.close();
    }
  }
})().then(() => process.exit(0), error => { console.error(error.message); process.exit(1); });
