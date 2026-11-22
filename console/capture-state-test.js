/* capture.state — the mic read over the wire. No browser microphone ever. */
'use strict';
const assert = require('node:assert/strict');
const { load } = require('./harness.js');

(async () => {
  const c = await load();
  const shell = c.window.ElariaShell;
  const lamps = () => Object.fromEntries(c.qa('[data-lamp]').map(li => [li.dataset.lamp, li.dataset.on]));
  const voiceLamp = () => c.qa('[data-lamp]').find(li => li.dataset.lamp === 'voice');
  const micnote = () => c.qa('.micnote').map(n => n.textContent);

  let err = null;
  try { shell.captureState('listening'); } catch (e) { err = e; }
  assert(err && /unknown capture state/.test(err.message),
    'unknown capture states refuse loudly with no silent default');
  assert.throws(() => shell.captureState('armed', 42), /unknown capture state|state|reason/);
  // the shell refuses a bad reason loudly instead of rendering it
  let badReason = null;
  try { shell.captureState('armed', 42); } catch (e) { badReason = e; }
  assert(badReason, 'non-string reasons refused');
  let longReason = null;
  try { shell.captureState('armed', 'x'.repeat(300)); } catch (e) { longReason = e; }
  assert(longReason, 'overlong reasons refused');

  shell.captureState('armed', 'hotword armed');
  assert.equal(lamps().voice, 'ok');
  assert(/hotword armed/.test(voiceLamp().title), 'voice lamp title carries the reason');
  assert(micnote().length > 0 && micnote().every(t => /mic armed — hotword listening — hotword armed/.test(t)),
    'mic note reads the wire state honestly');

  shell.captureState('muted');
  assert.equal(lamps().voice, 'ok');
  assert(micnote().every(t => /mic muted — she is speaking/.test(t)));

  shell.captureState('stalled', 'stalled');
  assert.equal(lamps().voice, 'wait');
  assert(micnote().every(t => /mic stalled/.test(t)));

  /* unavailable is a broken pipeline, not a calm idle: red lamp, honest note */
  shell.captureState('unavailable', 'capture refused: node not configured');
  assert.equal(lamps().voice, 'gone', 'unavailable reads as broken, not amber');
  assert(voiceLamp().title.includes('capture refused'), 'reason rides the lamp title');
  assert(micnote().every(t => /mic unavailable — capture cannot open or the speech path is dead — capture refused: node not configured/.test(t)),
    'mic note carries the reason verbatim');
  assert.equal(shell.state.mic, 'unavailable');

  /* verifying is accepted but reserved: no producer emits it yet */
  shell.captureState('verifying');
  assert.equal(lamps().voice, 'wait', 'verifying is not a live pipeline');
  assert(micnote().every(t => /mic verifying/.test(t)));
  assert.equal(shell.state.mic, 'verifying');

  shell.captureState('released', 'hotword stopped');
  assert.equal(lamps().voice, 'wait');
  assert(micnote().every(t => /mic released — hotword stopped/.test(t)));

  /* disconnect drops the last known state honestly */
  shell.connect({ send: async () => 'synthetic', name: 'synthetic' });
  shell.captureState('open', 'session capturing');
  shell.disconnect();
  const st = shell.state;
  assert.equal(st.mic, null);
  assert.equal(st.daemon, false);
  assert(micnote().every(t => t === 'no capture signal from this window'),
    'mic note says what is actually known after disconnect');

  console.log('PASS: capture.state renders the honest pipeline state; unavailable/verifying handled');
  c.close();
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
