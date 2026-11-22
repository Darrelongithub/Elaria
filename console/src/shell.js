/*
 * Elaria console shell v6 — sidebar + centre chat + orb rail + full-screen panes.
 *
 * MERGE: the uploaded shell (terminal, orb notifications, ElariaShell wire surface) with the
 * v5 sidebar (sessions + transcript/memory/audio sections, semantic colour passes, baked memory).
 * LAYOUT RULING (owner): her orb lives in a NARROW RIGHT RAIL, never the centre — the centre is
 * always the chat. Transcript opens FULL SCREEN over the chat and the orb; the sidebar stays put.
 *
 * three.js r128 and elaria-visualizer.js are INLINED into the built index.html by build.py, so this
 * file makes zero network requests and works from file:// as well as from serve.py.
 *
 * INTEGRATION POINTS (nothing below pretends a backend exists)
 *   ElariaShell.connect({ name, send(text, ctx) })   daemon wire. send resolves to a string or
 *                                                    { text, attribution }; reply audio is DROPPED.
 *                                                    F29: daemon gateway is sole playback owner.
 *   ElariaShell.disconnect()                         wire lost: lamps, offline state, notification.
 *   ElariaShell.notify({ text, speak })              proactive tap on the shoulder from the daemon.
 *   ElariaShell.say(text)                            push an unprompted reply into the log.
 *   ElariaShell.setState(name)                       idle | listening | thinking | speaking | offline.
 *   ElariaShell.drafts(frame) / .draftResolved(...)   IF-2 draft feed -> draft-review cards;
 *                                                    approve/reject POST through the gate and the
 *                                                    card only resolves on the daemon's word.
 *   ElariaShell.transcript(rows) / .memory(cards) / .audio(rows)   feed the three panes live data.
 * Without a daemon the shell answers slash commands and says plainly that nothing is on the wire.
 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const qa = (sel) => Array.prototype.slice.call(document.querySelectorAll(sel));
  const h = (tag, cls, txt) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const reduced = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const fmt = (ts) => new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  /* Orb states, each driven by an EXISTING signal (IF-4 + IF-2). "phone-connected" and
     "pending-draft" are not base states: both are DERIVED from the draft feed (a live
     phone-connected signal, and outstanding pending count), so a removed signal cannot
     leave a lying orb behind. The visualizer engine knows five states only, so the two
     phone states ride the engine's idle world (phoneSocket maps them) while the readout,
     the panel attribute and aria carry the real name. Unknown names THROW. */
  const LABEL = { idle: 'Idle', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking',
    offline: 'Offline', 'phone-connected': 'Phone connected', 'pending-draft': 'Pending draft' };
  const BASE_STATE = { 'phone-connected': 'idle', 'pending-draft': 'idle' };
  const ENGINE_SAFE = (s) => BASE_STATE[s] || s;
  const SIZES = [14, 16, 19];
  const PANES = ['transcript', 'memory', 'audio'];
  /* IF-1 owner amendment — exactly four renderable draft states. rejected / expired /
     send-error are CAUSES under failed, never top states. */
  const DRAFT_STATES = ['pending', 'approved', 'sent', 'failed'];
  const DRAFT_CAUSES = { rejected: 'rejected', expired: 'expired', 'send-error': 'send error', send_error: 'send error' };
  const DRAFT_TIME = (ts) => {
    const n = typeof ts === 'number' ? ts : (typeof ts === 'string' && ts.trim() ? Date.parse(ts) : NaN);
    return Number.isFinite(n) ? new Date(n).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
  };

  const el = {
    app: $('app'), sb: $('sb'), sList: $('sList'), bNew: $('bNew'),
    term: $('term'), log: $('log'), pad: $('logpad'), ta: $('input'), form: $('form'), jump: $('jump'),
    orb: $('orb'), stage: $('stage'), rs: $('rs'), rsrc: $('rsrc'), rm: $('rm'),
    orbnote: $('orbnote'), wants: $('wants'),
    tgSb: $('tgSb'), tgOrb: $('tgOrb'), tgFull: $('tgFull'), tbWhich: $('tbWhich'),
    full: $('full'), ftitle: $('ftitle'), fbadge: $('fbadge'), fsub: $('fsub'), fsearch: $('fsearch'),
    fdemo: $('fdemo'), fclose: $('fclose'), fbody: $('fbody'), toasts: $('toasts')
  };

  /* colour passes
     hers gets the full pass. yours gets white and nothing else except a /command,
     because a command is not a word. Verified: paintYou emits zero spans for plain prose. */
  const esc = (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const TOKENS = [
    [/\[(ON|OK|PASS|CONNECTED|ALIVE|GREEN|KEPT)\]/g, 'ok'],
    [/\[(WARN|WARNING|PENDING|DEGRADED|AMBER|STUB|STUBBED|INTERIM|SAMPLE|DEMO)\]/g, 'warn'],
    [/\[(ERR|ERROR|FAIL|FAILED|OFF|ABSENT|DEAD|RED|NOT CONNECTED|BROKEN|HALT|STOP|LOST)\]/g, 'err'],
    [/\[(sys|note|info)\]/g, 'note'],
    [/(^|\s)(\/[a-z][a-z0-9-]*)/g, 'cmd'],
    [/(~\/[^\s:,;)<]+)/g, 'path'],
    [/(\b\d[\d,\.]*\s?(?:ms|s|MiB|MB|GB|KB|B|min|days?|hours?)?\b)/g, 'num']
  ];
  function paint(s) {
    let out = esc(s);
    TOKENS.forEach((t) => {
      out = out.replace(t[0], (m, a, b) =>
        t[0].source.indexOf('(^|\\s)') === 0 ? (a || '') + '<span class="' + t[1] + '">' + b + '</span>'
                                             : '<span class="' + t[1] + '">' + m + '</span>');
    });
    return out;
  }
  const paintYou = (s) => esc(s)
    .replace(/(^|\s)(\/[a-z][a-z0-9-]*)/g, (m, a, b) => a + '<span class="cmd">' + b + '</span>')
    .replace(/\n/g, '<br>');
  const paintHer = (s) => paint(s).replace(/\n/g, '<br>');

  /* baked content (real ledger facts) */
  const MEM = [
    { t: 'who she is', v: 'Elaria. Personal assistant, one owner. Not a product, not a demo.', w: '~/BLUEPRINT (v44)' },
    { t: 'voice', v: 'Rasp and bite. Flare, online only. Offline is text — never a spoken fallback voice.', w: '~/BLUEPRINT' },
    { t: 'wake word', v: 'Her own voice saying "Elaria", speaker-verified. Zip uploads are rejected.', w: 'WP4 — paused' },
    { t: 'how you release keys', v: 'F2 first while WIN stays held, then WIN. Never together, never WIN first — Hyprland 0.57 eats the stop otherwise.', w: 'ruled 2026-10-31' },
    { t: 'privacy', v: 'Notifications carry signals, not content. No always-on hot mic as a latency fix, ever.', w: 'ruled 2026-10-31' },
    { t: 'personality', v: 'No emoji. No canned jokes. Roasting is first-class. Dry warmth underneath.', w: '~/humour.toml' },
    { t: 'humour mining', v: 'Owner-side exports only, his side only, adjudicated, never auto-saved.', w: '~/humour.toml' },
    { t: 'money', v: 'Gemini free tier. One project, one key, $0 hard. No rotation, no stacking.', w: 'ruled' },
    { t: 'hands envelope', v: 'T0 observe · T1 reversible, act and report · T2 destructive-outward, ask and wait forever · T3 forbidden wall.', w: 'BLUEPRINT-V2 §2.14' },
    { t: 'audio doctrine', v: 'Audio is never lost. Journal, never-overwrite, trash-not-delete, hash verify.', w: 'ruled' },
    { t: 'what she heard last', v: '[PENDING] needs the wire.', w: 'daemon journal' }
  ];
  const DEMO_TR = [
    { ts: '14:07:23', id: '671964', who: 'you', text: 'okay elaria, what did that cost us', peak: '0.86', verdict: 'kept' },
    { ts: '14:07:31', id: '671964', who: 'elaria', text: 'Twenty seconds of your life and about eleven megabytes of mine.', peak: '0.71', verdict: 'kept' },
    { ts: '14:02:17', id: '3b5227', who: 'you', text: '[WARN] no transcript — session hung 301 s, watchdog rescued it', peak: '0.79', verdict: 'kept' },
    { ts: '13:56:04', id: 'b7704b', who: 'you', text: 'one mississippi, two mississippi', peak: '0.81', verdict: 'kept' },
    { ts: '09:12:55', id: '064450', who: 'you', text: 'four', peak: '0.74', verdict: 'kept' }
  ];
  const DEMO_AU = [
    { name: '20261031-140723-671964.wav', size: '312,000 B', age: 'today', tier: 'hot' },
    { name: '20261031-140217-3b5227.wav', size: '9,637,440 B', age: 'today', tier: 'hot' },
    { name: '20261031-135604-b7704b.wav', size: '171,840 B', age: 'today', tier: 'hot' },
    { name: '20261025-181730-4d90bf.wav', size: '44 B', age: '6 days', tier: 'never-retry' }
  ];
  const CENSUS = 'design-record audio census (not a current manifest): 37 files = 35 session wavs + 2 artifacts · kept 80,698,682 B · steady 11.29 MiB/day · zstd -19 ratios 0.475 / 0.582 FINAL';
  const TR_COLS = 'every row will carry: time · session id · who spoke · her exact words · peak amplitude · keep verdict';
  const AU_COLS = 'every row will carry: file · size · age · tier (hot 14 d / cold / never-retry)';

  const STUBS = [
    'stub reply. the daemon is not wired to this window, so this text is the shell talking, not me.\n\nthis is a local preview, not proof of live capabilities, successful persistence or owner-hardware rendering.',
    'stub again. no daemon or model request was made for this turn. this is local preview text, not a model answer.',
    'the shell is holding your text. this standalone window is not connected to a daemon.',
    'stub. /status shows which lamp is missing and why — amber means unavailable here; red means disconnected, not proof a component does not exist.',
    'still the shell. a connected adapter supplies replies; the wire lamp does not certify model output or an action.'
  ];
  let stubI = 0;
  const statusText = () => 'lamps, honestly:\n\n' +
    '  console   [ON]              this window, running, local\n' +
    '  daemon    [' + (daemon ? 'CONNECTED' : 'NOT CONNECTED') + ']   ' + (daemon ? 'adapter attached' : 'connection not established') + '\n' +
    '  voice     [' + (micPipelineLive() ? 'CONNECTED' : captureState === 'unavailable' ? 'UNAVAILABLE' : 'NOT CONNECTED') + ']   ' + (micPipelineLive() || captureState === 'unavailable' ? captureStateText() : 'no capture signal from this window') + '\n' +
    '  wire      [' + (daemon ? 'CONNECTED' : 'ABSENT') + ']          ' + (daemon ? 'bridge up' : 'connection not established') + '\n\n' +
    'Text replies use the attached adapter. Connection is not a claim that journal, manifest, memory or speech feeds are present; each pane keeps its own status.';

  /* storage */
  const KEY = 'elaria.console.v6';
  let data;
  try { data = JSON.parse(localStorage.getItem(KEY)); } catch (e) { data = null; }
  if (!data || !Array.isArray(data.sessions)) data = null;
  if (data) data.prefs = Object.assign({ crt: false, big: 0, sb: true, orb: true }, data.prefs);
  let saveT = 0;
  const save = () => { clearTimeout(saveT); saveT = setTimeout(() => {
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (e) { /* storage blocked */ } }, 250); };
  const cur = () => data.sessions.find((s) => s.id === data.active);

  /* runtime state */
  let V = null, vizErr = '';
  let state = 'idle', busy = false, forcedOffline = false, simOn = true;
  /* The mic is read from the daemon's capture.state — never a browser-local
     microphone flag. Null until a validated frame arrives: the shell says so. */
  let captureState = null, captureReason = null;
  const MATCH_STATE = { open: 1, armed: 1, muted: 1, stalled: 1, released: 1, unavailable: 1, verifying: 1 };
  const micPipelineLive = () => captureState === 'open' || captureState === 'armed' || captureState === 'muted';
  const micListening = () => captureState === 'open' || captureState === 'armed';
  const CAPTURE_LABEL = {
    open: 'mic open — frames capturing',
    armed: 'mic armed — hotword listening',
    muted: 'mic muted — she is speaking',
    stalled: 'mic stalled — no frames within the stall budget',
    released: 'mic released',
    unavailable: 'mic unavailable — capture cannot open or the speech path is dead',
    verifying: 'mic verifying — wake lane reserving this state (not yet emitted)',
  };
  const captureStateText = () => {
    if (!captureState || !MATCH_STATE[captureState]) return '';
    return CAPTURE_LABEL[captureState] + (captureReason ? ' — ' + captureReason : '');
  };
  let daemon = null, skip = false, voiceTimer = 0, typeT = 0;
  let pinned = true, demoOn = false, wipeArmed = false, away = null;
  let openSec = null;          // which sidebar section is folded open
  let fullPane = null;         // which pane is full screen
  let liveTR = null, liveAU = null, liveMEM = null;   // real data, once the wire feeds it
  const hist = []; let hi = 0;

  /* visualizer bridge */
  function bootVisualizer() {
    if (!window.THREE) return Promise.reject(new Error('[ERR] three.js is missing from this file.'));
    if (!window.Elaria) return Promise.reject(new Error('[ERR] the visualizer engine is missing from this file.'));
    // The maker's embed snippet, verbatim: { fit: 1.8 } — his own number for a narrow side panel.
    // simulate: true is the maker's designed option for a synthetic signal; the console needs it
    // until the wire exists so she is honest ("simulated") instead of frozen. Nothing else.
    try { return Promise.resolve(window.Elaria.create(el.stage, { simulate: true, fit: 1.8 })); }
    catch (err) { return Promise.reject(new Error((err && err.message) || 'WebGL unavailable')); }
  }
  function paintState(s) {
    el.orb.dataset.state = s;
    el.rs.textContent = LABEL[s];
    el.stage.setAttribute('aria-label', 'Elaria visualizer, ' + s);
    el.rs.classList.remove('sw'); void el.rs.offsetWidth; el.rs.classList.add('sw');
    syncOrb();
  }
  /* ---- draft-feed derived states (IF-2). Neither is ever set by hand: they exist while the
     signals do. Precedence when both hold: pending-draft speaks first — it needs the owner.
     A removed signal recalculates instead of stranding the orb, and an offline orb outranks
     both (daemon-down is Ruling D). no second player, no second sender: this only paints. */
  let phoneConnected = false;   // a daemon signal said the phone link is up
  /* One derivation, no recursion: a real state (listening / thinking / speaking) is never
     overridden, so this only runs from a base or a stale phone state. fallback=true is used
     when a SIGNAL WAS REMOVED, so the orb returns to its base instead of staying derived. */
  function applyPhone(fallback) {
    if (state === 'offline') return;                       // daemon-down outranks both (Ruling D)
    const pend = pendingDrafts().length;
    if (pend > 0) return setState('pending-draft');        // needs the owner: speaks first
    if (phoneConnected) return setState('phone-connected');
    if (fallback === true || BASE_STATE[state]) setState(micListening() ? 'listening' : 'idle');
  }
  // F29: only output levels can enter speaking. A reply/state flag is not playback evidence.
  function setState(s, fromLevels = false) {
    if (!LABEL[s]) throw new Error('unknown orb state "' + s + '" — no silent default');
    if ((s === 'speaking' && !fromLevels) || s === state) return;
    state = s; if (V) V.setState(ENGINE_SAFE(s)); paintState(s);
  }
  const setLevels = (role, level) => {
    if (!['input', 'output'].includes(role) || !Number.isFinite(level) || level < 0 || level > 1) return;
    if (V) V.setLevels(role, { level });
    if (role === 'output' && !forcedOffline) {
      if (level > 0) setState('speaking', true);
      else if (state === 'speaking') { setState(busy ? 'thinking' : micListening() ? 'listening' : 'idle'); applyPhone(false); }
    }
  };
  function settle() {
    if (busy || voiceTimer) return;
    setState(forcedOffline ? 'offline' : micListening() ? 'listening' : 'idle');
    if (!forcedOffline) applyPhone(false);
  }
  function lamps() {
    const voiceUnavailable = captureState === 'unavailable';
    const voiceLit = micPipelineLive();
    const on = { console: 'ok', daemon: daemon ? 'ok' : 'wait',
      voice: voiceLit ? 'ok' : (voiceUnavailable ? 'gone' : 'wait'),
      wire: daemon ? 'ok' : 'gone' };
    const titles = {
      console: 'console — this local window is running',
      daemon: daemon ? 'daemon — adapter attached' : 'daemon — not connected',
      voice: (voiceLit || voiceUnavailable) ? ('voice — ' + captureStateText()) : 'voice — no capture signal from this window',
      wire: daemon ? 'wire — connected; not proof of model output or an action' : 'wire — not connected'
    };
    document.querySelectorAll('[data-lamp]').forEach((li) => {
      li.dataset.on = on[li.dataset.lamp]; li.title = titles[li.dataset.lamp];
    });
  }

  let lastSrc = '';
  setInterval(() => {
    if (document.hidden || !V) return;
    const l = V.getLevels();
    el.rm.style.width = (Math.min(1, l.level || 0) * 100).toFixed(1) + '%';
    let s = '', sim = false;
    if (l.role) {
      if (l.source === 'live') s = l.role === 'input' ? 'microphone' : 'audio';
      else if (l.source === 'external') s = l.role === 'input' ? 'keystrokes' : 'text cadence';
      else if (l.source === 'simulated') { s = 'simulated'; sim = true; }
    }
    if (s !== lastSrc) { el.rsrc.textContent = s; el.rsrc.classList.toggle('sim', sim); lastSrc = s; }
  }, 150);

  /* miniature orb (2D, shares the palette) */
  const STOPS = [[.23,.07,.66],[.12,.30,1],[.61,.17,1],[1,.17,.72],[1,.42,.02],[1,.70,.10],[1,.42,.02],[1,.17,.72],[.61,.17,1]];
  function pal(x) {
    x -= Math.floor(x);
    const xs = x * 9, i = Math.floor(xs), f = xs - i, k = f * f * (3 - 2 * f);
    const a = STOPS[i], b = STOPS[(i + 1) % 9];
    return a.map((v, n) => Math.round(255 * (v + (b[n] - v) * k)));
  }
  const CURVES = [
    { f: [1,2,1], p: [0,1.7,.4],   s: [.5,-.7,.4]  }, { f: [2,3,2], p: [2.1,.3,1.2], s: [-.4,.6,.5] },
    { f: [3,2,1], p: [4,2.6,.9],   s: [.6,.4,-.5]  }, { f: [1,3,3], p: [5.1,3.9,2.2], s: [-.5,-.4,.7] },
    { f: [2,1,2], p: [1.1,5.2,3.3], s: [.3,.7,-.6] }
  ];
  class Orb {
    constructor(cv, size, speaking) {
      const d = Math.min(window.devicePixelRatio || 1, 2);
      cv.width = cv.height = size * d; cv.style.width = cv.style.height = size + 'px';
      this.c = cv.getContext('2d'); this.c.scale(d, d); this.S = size; this.sp = speaking;
    }
    draw(t) {
      const { c, S } = this, N = 56;
      const amp = this.sp ? .4 + .35 * Math.abs(Math.sin(t * 7.3)) * (.6 + .4 * Math.sin(t * 3.1)) : .12 + .06 * Math.sin(t * 1.3);
      const sc = S * .33 * (1 + .35 * amp) / 1.45;
      c.globalCompositeOperation = 'source-over'; c.clearRect(0, 0, S, S);
      const g = c.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
      g.addColorStop(0, `rgba(122,77,255,${.30 + .35 * amp})`); g.addColorStop(.6, 'rgba(255,43,184,.08)'); g.addColorStop(1, 'rgba(0,0,0,0)');
      c.fillStyle = g; c.fillRect(0, 0, S, S);
      c.globalCompositeOperation = 'lighter'; c.lineCap = 'round';
      CURVES.forEach((k, ci) => {
        const P = [];
        for (let i = 0; i <= N; i++) {
          const a = i / N * 6.2832;
          const x = Math.sin(k.f[0]*a + k.p[0] + t*k.s[0]) + .45*Math.sin((k.f[0]+2)*a + k.p[1] - t*k.s[1]*1.3);
          const y = Math.sin(k.f[1]*a + k.p[1] + t*k.s[1]) + .45*Math.sin((k.f[1]+1)*a + k.p[2] + t*k.s[2]*1.1);
          P.push([S/2 + x*sc, S/2 + y*sc, Math.cos(k.f[2]*a + k.p[2] + t*k.s[2])]);
        }
        for (let seg = 0; seg < 8; seg++) {
          const i0 = seg * 7, [r, gr, b] = pal(seg / 8 * .55 + ci * .113 + t * .02);
          const al = (.35 + .4 * (P[i0+3][2] + 1) / 2) * (.7 + .6 * amp);
          c.beginPath(); c.moveTo(P[i0][0], P[i0][1]);
          for (let i = i0 + 1; i <= i0 + 7; i++) c.lineTo(P[i][0], P[i][1]);
          c.strokeStyle = `rgba(${r},${gr},${b},${al * .22})`; c.lineWidth = 3.2; c.stroke();
          c.strokeStyle = `rgba(${r},${gr},${b},${Math.min(1, al)})`; c.lineWidth = 1; c.stroke();
        }
      });
    }
  }
  const orbs = new Set(); let orbRaf = 0, orbLast = 0;
  function orbLoop(now) {
    orbRaf = 0;
    if (!orbs.size) return;
    if (now - orbLast >= 33) { orbLast = now; orbs.forEach((o) => o.draw(now / 1000)); }
    orbRaf = requestAnimationFrame(orbLoop);
  }
  const startOrbs = () => { if (reduced) orbs.forEach((o) => o.draw(0)); else if (!orbRaf) orbRaf = requestAnimationFrame(orbLoop); };

  /* notifications: the mini orb */
  function notify(o) {
    const text = o.text || '';
    const ms = o.ms || Math.min(9000, 4500 + text.length * 40);
    /* Full slots used to mean an endless loop: closeToast only STARTS the fade and removes the
       node 450 ms later, so `while (children >= 3) closeToast(first)` could never make the
       condition false and the shell froze on the fourth notification inside one tick. Dismiss
       oldest non-fading toasts; if all three are already fading, drop one outright and move on. */
    while (el.toasts.children.length >= 3) {
      const old = Array.prototype.find.call(el.toasts.children, (t) => !t._closing);
      if (old) closeToast(old);
      else { el.toasts.firstChild.remove(); break; }
    }
    const t = h('div', 'toast'); t.setAttribute('role', 'status');
    const cv = h('canvas', 'orb-cv'); cv.setAttribute('aria-hidden', 'true');
    const col = h('div', 'tcol'), nm = h('div', 'tname');
    nm.append(h('span', '', 'Elaria'));
    if (o.speak) { const b = h('span', 'bars'); b.append(h('i'), h('i'), h('i')); nm.append(b); }
    else nm.append(h('span', 'ping'));
    col.append(nm, h('div', 'tbody', text));
    const x = h('button', 'tx', '\u00d7'); x.type = 'button'; x.setAttribute('aria-label', 'Dismiss notification');
    t.append(cv, col, x); el.toasts.append(t);
    t._orb = new Orb(cv, 44, !!o.speak); orbs.add(t._orb); startOrbs();
    el.wants.hidden = false;                       // she still wants to talk after the toast fades
    let timer = setTimeout(() => closeToast(t), ms);
    t.addEventListener('mouseenter', () => clearTimeout(timer));
    t.addEventListener('mouseleave', () => { timer = setTimeout(() => closeToast(t), 2000); });
    x.addEventListener('click', () => closeToast(t));
    t.addEventListener('click', (e) => { if (e.target !== x) { closeToast(t); el.ta.focus(); } });
    if (o.log !== false) { push('ai', text); if (!busy) log('ai', text); }
    if (o.speak) pulseVoice(Math.min(ms - 600, 900 + text.length * 45));
  }
  function closeToast(t) {
    if (!t || t._closing) return;
    t._closing = true; t.classList.add('out');
    const done = () => { orbs.delete(t._orb); t.remove(); };
    if (!t._orbDone) { t._orbDone = done; t.addEventListener('animationend', done, { once: true }); setTimeout(done, 450); }
  }
  function pulseVoice(ms) {
    if (busy || forcedOffline) return;
    clearInterval(voiceTimer); // labelled synthetic levels below, never a speech request
    const end = performance.now() + ms;
    voiceTimer = setInterval(() => {
      const t = performance.now();
      if (t >= end) { clearInterval(voiceTimer); voiceTimer = 0; setLevels('output', 0); settle(); return; }
      setLevels('output', .3 + .5 * Math.abs(Math.sin(t / 110)) * Math.random());
    }, 45);
  }
  const calmWants = () => { el.wants.hidden = true; };

  /* log rendering */
  const ROLE = { me: 'you', ai: 'elaria', sys: '', note: '', warn: '', err: '' };
  function receiptRows(value) {
    return Array.isArray(value) ? value.filter(x => typeof x === 'string' && x.length <= 1000).slice(0, 24) : [];
  }
  function receiptEl(value) {
    const rows = receiptRows(value);
    if (!rows.length) return null;
    const box = h('aside', 'attribution');
    box.setAttribute('aria-label', 'Bridge attribution, separate from reply prose');
    box.append(h('b', '', 'Bridge attribution'));
    rows.forEach(row => box.append(h('p', '', row))); // textContent only, never HTML/model markup
    return box;
  }
  function msgEl(r, text, ts, attribution) {
    const m = h('article', 'msg ' + r), hd = h('header');
    if (ROLE[r]) hd.append(h('b', 'who', ROLE[r]));
    hd.append(h('time', '', fmt(ts || Date.now())));
    const body = h('div', 'body');
    body.innerHTML = r === 'me' ? paintYou(text || '') : paintHer(text || '');
    m.append(hd, body);
    return m;
  }
  const pin = () => { if (pinned) el.log.scrollTop = el.log.scrollHeight; };
  function log(r, text) { const m = msgEl(r, text); el.pad.append(m); pin(); return m; }
  function out(content) {
    const m = msgEl('sys', typeof content === 'string' ? content : '');
    if (typeof content !== 'string') m.querySelector('.body').append(content);
    el.pad.append(m); pin();
  }
  const pushTo = (s, r, t, attribution) => { if (s) { s.msgs.push({ r, t, ts: Date.now(), attribution: receiptRows(attribution) }); save(); renderSess(); } };
  function push(r, t) { pushTo(cur(), r, t); }
  function renderAttribution() {
    const home=$('session-attribution'); home.replaceChildren();
    const messages=cur().msgs.filter(m=>receiptRows(m.attribution).length).slice(-8);
    if(!messages.length) home.append(h('p','mini','No reply attribution received for this session.'));
    messages.forEach(m=>{ const box=receiptEl(m.attribution); if(box) {box.prepend(h('time','',fmt(m.ts)));home.append(box);} });
  }
  function renderLog() {
    el.pad.replaceChildren();
    cur().msgs.forEach((m) => el.pad.append(msgEl(m.r, m.t, m.ts, m.attribution)));
    pinned = true; el.log.scrollTop = el.log.scrollHeight; el.jump.hidden = true;
    $('sname').textContent = '~/sessions/' + cur().name;
  }
  el.log.addEventListener('scroll', () => {
    pinned = el.log.scrollHeight - el.log.scrollTop - el.log.clientHeight < 80;
    el.jump.hidden = pinned;
  });
  el.jump.addEventListener('click', () => { pinned = true; el.log.scrollTop = el.log.scrollHeight; });

  /* sessions */
  function newSession(name) {
    const s = { id: Date.now().toString(36) + Math.random().toString(36).slice(2, 5),
      name: name || 'session-' + (data.sessions.length + 1), created: Date.now(), msgs: [] };
    data.sessions.push(s); data.active = s.id; save(); return s;
  }
  function renderSess() {
    renderAttribution();
    el.sList.replaceChildren();
    data.sessions.forEach((s, i) => {
      const b = h('button', 'row'); b.type = 'button';
      b.append(h('span', 'ix', String(i + 1).padStart(2, '0')), h('span', 'ti', s.name),
        h('span', 'ct', s.msgs.length + ' msg'));
      b.title = 'switch to ' + s.name;
      if (s.id === data.active) b.setAttribute('aria-current', 'true');
      b.addEventListener('click', () => switchTo(i));
      el.sList.append(b);
    });
    const n = h('button', 'row new'); n.type = 'button';
    n.append(h('span', 'ix', '+'), h('span', 'ti', 'new session'), h('span', 'ct', 'alt+N'));
    n.addEventListener('click', createSession);
    el.sList.append(n);
  }
  /* Navigation is NEVER blocked by her typing. Switching sessions cuts the sentence short, stores
     it in full in the session it belongs to, and says where it went. Blocking navigation was the
     bug behind "when i go back to boot it doesnt work": her stub reply types for ~5 s, and every
     click in that window was silently refused. */
  async function switchTo(i) {
    const target = data.sessions[i];
    if (!target || target.id === data.active) return;
    const from = cur();
    const cut = busy;
    if (cut) { interrupt(); await sleep(50); }
    clearHandsAsk();
    data.active = target.id; save(); renderLog(); renderSess();
    if (cut) {
      const note = '[note] she was mid-sentence in ' + (from ? from.name : 'that session') + ' — you switched, so it stopped. the full reply is stored there, nothing was lost.';
      push('note', note); log('note', note);
    }
    el.ta.focus();
  }
  async function createSession() {
    clearHandsAsk();
    const cut = busy;
    if (cut) { interrupt(); await sleep(50); }
    const from = cur();
    newSession(); renderLog(); renderSess();
    if (cut) out('[note] she was mid-sentence in ' + (from ? from.name : 'that session') + ' — the full reply is stored there.');
    el.ta.focus();
  }

  /* sidebar sections + full-screen panes */
  function setSec(name) {
    openSec = openSec === name ? null : name;
    PANES.forEach((p) => {
      const sec = $('sec-' + p), on = p === openSec;
      sec.classList.toggle('open', on);
      sec.querySelector('.sec-h').setAttribute('aria-expanded', String(on));
      if (on) renderSec(p);
    });
  }
  function openFull(name, force) {
    if (!force && fullPane === name && el.full.classList.contains('open')) return closeFull();
    fullPane = name;
    if (openSec !== name) { openSec = name; PANES.forEach((p) => {
      const on = p === name; $('sec-' + p).classList.toggle('open', on);
      $('sec-' + p).querySelector('.sec-h').setAttribute('aria-expanded', String(on));
      if (on) renderSec(p);
    }); }
    el.full.classList.add('open');
    el.full.setAttribute('aria-label', name + ', full screen');
    el.tbWhich.textContent = name;
    el.fsearch.value = '';
    renderFull();
  }
  function closeFull() {
    if (!el.full.classList.contains('open')) { fullPane = null; return; }
    fullPane = null; el.tbWhich.textContent = 'transcript';
    el.full.classList.add('closing');
    const done = () => el.full.classList.remove('open', 'closing');
    el.full.addEventListener('animationend', done, { once: true });
    setTimeout(done, 260);                       // animationend can be missed under reduced motion
  }
  function openPane(name) {
    if (name === 'off') { closeFull(); if (openSec) setSec(openSec); return; }
    if (name === 'transcript') return openFull('transcript');
    if (openSec !== name) setSec(name);
    if (fullPane) { fullPane = name; el.tbWhich.textContent = name; renderFull(); }
  }
  const nonempty = (rows) => Array.isArray(rows) && rows.length > 0 ? rows : null;
  const paneLive = (p) => nonempty(p === 'transcript' ? liveTR : p === 'audio' ? liveAU : liveMEM);
  const badgeFor = (p) => paneLive(p) ? ['sm', 'live']
    : p === 'memory' ? ['cp', 'shell copy'] : demoOn ? ['sm', 'sample'] : ['st', 'pending'];
  function syncBadges() {
    ['transcript', 'memory', 'audio'].forEach((p) => {
      const b = $('badge-' + p), [cls, txt] = badgeFor(p);
      b.className = 'badge ' + cls; b.textContent = txt;
    });
    if (fullPane) { const [cls, txt] = badgeFor(fullPane); el.fbadge.className = 'pill ' + cls; el.fbadge.textContent = txt; }
  }

  /* ---- compact previews inside the sidebar (exactly as they were) ---- */
  function renderSec(name) {
    const b = $('body-' + name); b.replaceChildren();
    const expand = h('button', 'sbtn'); expand.type = 'button';
    expand.append(h('span', '', '\u2922'), h('span', '', 'open ' + name + ' full screen'));
    expand.addEventListener('click', () => openFull(name));
    if (name === 'transcript') {
      const rows = liveTR || (demoOn ? DEMO_TR : null);
      if (!rows) b.append(h('p', 'mini', 'No transcript feed rows received. ' + TR_COLS + '.'));
      else rows.slice(0, 4).forEach((r) => {
        const d = h('div', 'mrow');
        d.append(h('span', 'k', r.ts), h('span', 'v', r.who + ': ' + r.text));
        b.append(d);
      });
    } else if (name === 'memory') {
      const cards = liveMEM || MEM;
      b.append(h('p', 'mini', cards.length + ' cards.'));
      cards.slice(0, 4).forEach((c) => {
        const d = h('div', 'mrow');
        d.append(h('span', 'k', c.t), h('span', 'v', c.v));
        b.append(d);
      });
    } else {
      const rows = liveAU || (demoOn ? DEMO_AU : null);
      b.append(h('p', 'mini', rows ? rows.length + ' rows shown.' : 'Deferred — no production audio pane feed. No audio manifest rows received. ' + AU_COLS + '.'));
      b.append(h('p', 'mini', CENSUS));
      const note = h('p', 'mini micnote'); b.append(note);
      if (rows) rows.slice(0, 3).forEach((r) => {
        const d = h('div', 'mrow');
        d.append(h('span', 'k', r.tier), h('span', 'v', r.name + ' · ' + r.size));
        b.append(d);
      });
    }
    b.append(expand);
    syncBadges();
  }

  /* ---- the full-screen view ---- */
  function blurb(kind, node) { const p = h('p', 'blurb' + (kind === 'live' ? ' live' : '')); p.append(node); return p; }
  function table(caption, cols, rows, cellCls) {
    const t = h('table', 'grid'), cap = h('caption', '', caption);
    const th = h('thead'), tr = h('tr');
    cols.forEach((c) => tr.append(h('th', '', c)));
    th.append(tr); t.append(cap, th);
    const tb = h('tbody');
    rows.forEach((r) => {
      const row = h('tr');
      r.forEach((cell, i) => { const td = h('td', cellCls && cellCls[i] ? cellCls[i] : ''); td.textContent = String(cell); row.append(td); });
      tb.append(row);
    });
    t.append(tb);
    return t;
  }
  function renderFull() {
    const name = fullPane || 'transcript';
    const b = el.fbody; b.replaceChildren();
    el.ftitle.textContent = name;
    syncBadges();
    const q = el.fsearch.value.trim().toLowerCase();
    const filt = (node) => { if (!q) return; node.textContent.toLowerCase().includes(q) || (node.hidden = true); };

    if (name === 'transcript') {
      el.fsub.textContent = 'voice transcription — every word she heard, with the peak and the keep verdict';
      const rows = liveTR || (demoOn ? DEMO_TR : null);
      if (!rows) b.append(blurb('warn', (() => { const f = document.createDocumentFragment();
        f.append(document.createTextNode('No journal transcript feed rows received. ' + TR_COLS + '. Type '),
          h('code', '', '/demo'), document.createTextNode(' to see the exact shape those rows will take, marked [SAMPLE] so nothing can be mistaken for live data.'));
        return f; })()));
      else {
        b.append(blurb(!liveTR && demoOn ? 'warn' : 'live', (() => { const f = document.createDocumentFragment();
          f.append(h('b', '', !liveTR && demoOn ? '[SAMPLE] ' : ''),
            document.createTextNode(!liveTR && demoOn ? 'not live data. These rows are built from real ledger facts so you can judge the layout, then thrown away.' : 'rows from the daemon journal.'));
          return f; })()));
        const t = table('voice rows', ['time', 'session', 'who', 'exact words', 'peak', 'verdict'],
          rows.map((r) => [r.ts, r.id, r.who, r.text, r.peak, r.verdict]),
          ['t', 'id', 'a', 'w', 't', 'v-k']);
        b.append(t);
      }
      const s = cur();
      b.append(table('this session, typed — ' + s.name, ['time', 'who', 'words'],
        s.msgs.map((m) => [fmt(m.ts), ROLE[m.r] || m.r, m.t]), ['t', 'a', 'w']));
      b.append(h('p', 'tnote', 'This display cache is localStorage, not her memory. Submitted text goes to the daemon and may reach its configured model provider.'));
    } else if (name === 'memory') {
      el.fsub.textContent = liveMEM ? 'cards received from the attached memory feed' : 'eleven design-record cards';
      const cards = liveMEM || MEM;
      b.append(blurb(liveMEM ? 'live' : 'warn', (() => { const f = document.createDocumentFragment();
        f.append(document.createTextNode(liveMEM ? 'Cards supplied by the attached memory feed.' : 'These cards are baked into this HTML file from the design ledger. A separate memory feed is required to replace them.'));
        return f; })()));
      const n = data.sessions.reduce((a, x) => a + x.msgs.length, 0);
      const wrap = h('div', 'cards');
      cards.forEach((c) => {
        const card = h('div', 'card');
        card.append(h('h3', '', c.t), h('p', '', c.v), h('span', 'w', c.w || ''));
        wrap.append(card);
      });
      const local = h('div', 'card');
      local.append(h('h3', '', 'this browser'), h('p', '', data.sessions.length + ' session(s), ' + n + ' message(s), stored locally under ' + KEY + '.'),
        h('span', 'w', 'browser display cache; not daemon history'));
      wrap.append(local);
      b.append(wrap);
      if (q) Array.prototype.forEach.call(wrap.children, filt);
    } else {
      el.fsub.textContent = 'recordings on disk — what was kept, how big, and which tier it sits in';
      const rows = liveAU || (demoOn ? DEMO_AU : null);
      b.append(blurb(rows ? (!liveAU && demoOn ? 'warn' : 'live') : 'warn', (() => { const f = document.createDocumentFragment();
        f.append(document.createTextNode(rows ? (!liveAU && demoOn ? '[SAMPLE] Not live data — census names and sizes, invented timestamps.' : 'Rows supplied by the attached manifest feed.')
            : 'No storage manifest feed rows received. ' + AU_COLS + '.'));
        return f; })()));
      b.append(h('p', 'tnote', CENSUS));
      if (rows) b.append(table('manifest rows', ['file', 'size', 'age', 'tier'],
        rows.map((r) => [r.name, r.size, r.age, r.tier]), ['w', 't', 't', 'v-k']));
      const note = h('p', 'tnote micnote'); b.append(note);
      b.append(h('p', 'tnote', 'capture state is read from the daemon over the wire — this shell never opens a browser microphone. nothing in this window records or stores audio.'));
    }
    if (q && name !== 'memory') Array.prototype.forEach.call(b.querySelectorAll('tbody tr'), filt);
  }

  /* The mic feedback line lives in two places at once (sidebar fold-out and full-screen pane), so the
     message is written to every copy AFTER the bodies are rebuilt, never before. */
  const renderMic = () => { if (openSec === 'audio') renderSec('audio'); if (fullPane === 'audio') renderFull(); };
  const setMicNote = (t) => qa('.micnote').forEach((n) => { n.textContent = t; });
  /* capture.state arrives over the wire. Honest by construction: the orb and the mic read the
     daemon's own state, never a browser-local microphone flag. Names come validated from the
     bridge; anything else is dropped by the wire consumer before it reaches here. */
  function renderCapture() {
    renderMic();
    setMicNote(captureStateText() || 'no capture signal from this window');
    lamps(); syncOrb();
    if (!busy && !forcedOffline && state !== 'speaking') {
      setState(micListening() ? 'listening' : 'idle');
    }
  }
  function captureStateFromFrame(name, reason) {
    if (!MATCH_STATE[name]) throw new Error('unknown capture state "' + name + '" — no silent default');
    if (reason !== undefined && reason !== null && typeof reason !== 'string') throw new Error('capture state reason must be text');
    if (reason !== undefined && reason !== null && reason.length > 256) throw new Error('capture state reason too long');
    captureState = name;
    captureReason = reason || null;
    renderCapture();
  }

  /* ---- orb readout ----
     There are NO state or signal buttons anywhere in the console. Those rows in the visualizer demo
     existed to STIMULATE modes by hand; here every state is supposed to happen in real time — driven
     by the wire, the microphone, or her typing. /state and /sim stay as hidden commands for testing,
     and nothing on screen pretends otherwise. */
  function syncOrb() {
    const cap = captureStateText();
    el.orbnote.textContent = (cap ? cap + ' · text output: ' : '') +
        'synthesised text cadence, not measured audio · text-only, no speech';
  }

  /* ---- chrome toggles ---- */
  function sidebarAria() {
    const open = window.innerWidth <= 940 ? document.body.classList.contains('sb-peek') : data.prefs.sb;
    el.tgSb.setAttribute('aria-expanded', String(open));
    $('sb').inert = !open;
  }
  window.addEventListener('resize', () => {
    if (window.innerWidth > 940) document.body.classList.remove('sb-peek');
    sidebarAria();
  });
  function toggleSb(force) {
    if (window.innerWidth <= 940) {
      const open = force != null ? force : !document.body.classList.contains('sb-peek');
      document.body.classList.toggle('sb-peek', open); sidebarAria(); return;
    }
    data.prefs.sb = force != null ? force : !data.prefs.sb;
    document.body.classList.toggle('sb-off', !data.prefs.sb);
    sidebarAria();
    save();
  }
  function toggleOrb(force) {
    data.prefs.orb = force != null ? force : !data.prefs.orb;
    document.body.classList.toggle('orb-off', !data.prefs.orb);
    el.tgOrb.setAttribute('aria-expanded', String(data.prefs.orb));
    save();
  }
  $('closeSb').addEventListener('click', () => { toggleSb(false); el.ta.focus(); });
  el.tgSb.addEventListener('click', () => { toggleSb(); el.ta.focus(); });
  el.tgOrb.addEventListener('click', () => { toggleOrb(); el.ta.focus(); });
  el.tgFull.addEventListener('click', () => openFull(fullPane || 'transcript'));
  el.fclose.addEventListener('click', () => { closeFull(); el.ta.focus(); });
  el.fdemo.addEventListener('click', () => { demoOn = !demoOn; syncBadges(); if (openSec) renderSec(openSec); if (fullPane) renderFull();
    out(demoOn ? '[SAMPLE] transcript and audio now show clearly-marked sample rows.' : 'sample rows cleared.'); });
  el.fsearch.addEventListener('input', () => { if (fullPane) renderFull(); });
  document.querySelectorAll('.sec-h').forEach((b) => b.addEventListener('click', () => {
    const p = b.dataset.pane;
    if (p === 'transcript') openFull('transcript');
    else if (p === 'drafts') { setSec('drafts'); renderDrafts(); }   // its own surface; never a full-screen pane
    else { setSec(p); if (fullPane) { fullPane = p; el.tbWhich.textContent = p; renderFull(); } }
  }));
  /* phone draft review (IF-2 / IF-1)
     One card per draft, states EXACTLY pending | approved | sent | failed, and a failed card
     names its cause (rejected / expired / send-error) underneath — IF-1 owner amendment. The
     recipient renders as the FULL number, never truncated or masked: textContent, so nothing
     in a number is elided.

     Two hard rules live here:
       1. INERT. The snippet and the body are untrusted input (IF-6) — they are written with
          textContent, never parsed, never executed. Nothing typed inside a message can run.
       2. NO LOCAL VERDICT. approve/reject POST the command and await the daemon's own
          draft-resolve frame. If the transport is missing or fails, the card says so and
          STAYS PENDING. The console never becomes a sender (same doctrine as F29/no second
          player), and deny-beats-consent: there is no optimistic path. */
  const draftStore = new Map();  // draft_id -> {id, state, cause, recipient, body, snippet, created_at, outcome, busy, error}
  let draftOrder = [];           // insertion order — a Map re-set never reorders, so keep the list
  const draftView = new Map();   // draft_id -> {node, head, to, body, meta, cause, err, approve, reject}
  const DRAFT_DISPLAY = new Set(DRAFT_STATES);

  function normDraft(raw, base) {
    if (!raw || typeof raw !== 'object') return null;
    const id = String(raw.draft_id || '').trim();
    if (!id) return null;                                   // a draft without its idempotent key is dropped
    const prev = base || {};
    let state = String(raw.state || prev.state || 'pending');
    let cause = raw.cause != null ? String(raw.cause) : (prev.cause || '');
    if (state === 'rejected' || state === 'expired' || state === 'send-error' || state === 'send_error') {
      cause = DRAFT_CAUSES[state]; state = 'failed';        // causes are not top states
    }
    if (!DRAFT_DISPLAY.has(state)) state = 'failed';        // unknown states fail closed, loudly on the card
    if (typeof raw.outcome === 'string' && raw.outcome && !cause) {
      const o = raw.outcome.toLowerCase();
      if (o === 'rejected' || o === 'expired') { state = 'failed'; cause = DRAFT_CAUSES[o]; }
    }
    const pick = (k) => raw[k] != null ? String(raw[k]) : (prev[k] != null ? String(prev[k]) : '');
    return {
      id, state, cause,
      recipient: pick('recipient'), body: pick('body') || pick('snippet'),
      created_at: raw.created_at != null ? raw.created_at : (prev.created_at != null ? prev.created_at : null),
      outcome: raw.outcome != null ? String(raw.outcome) : (prev.outcome || ''),
      busy: false, error: ''
    };
  }
  function upsertDraft(raw, base) {
    const d = normDraft(raw, base);
    if (!d) return null;
    const had = draftStore.has(d.id);
    draftStore.set(d.id, d);
    if (!had) draftOrder.push(d.id);
    return d;
  }
  function pendingDrafts() {
    return draftOrder.map((id) => draftStore.get(id)).filter((d) => d && d.state === 'pending');
  }

  function draftEl(tag, cls, txt) {
    const node = h(tag, cls || '', txt == null ? '' : String(txt));   // h() sets textContent — inert
    return node;
  }
  function draftCard(d) {
    if (draftView.has(d.id)) return draftView.get(d.id);
    const node = draftEl('article', 'draft-card');
    node.dataset.draftId = d.id; node.dataset.state = d.state;
    const head = draftEl('header', 'draft-head');
    const st = draftEl('span', 'st'); const tag = draftEl('small', '', 'draft #' + d.id);
    head.append(st, tag);
    const to = draftEl('p', 'draft-to');
    const body = draftEl('p', 'draft-body');
    const meta = draftEl('p', 'draft-meta');
    const cause = draftEl('p', 'draft-cause');
    const err = draftEl('p', 'draft-err');
    const acts = draftEl('div', 'draft-actions');
    const approve = draftEl('button', 'draft-approve', 'approve'); approve.type = 'button';
    const reject = draftEl('button', 'draft-reject', 'reject'); reject.type = 'button';
    approve.dataset.draftAct = 'approve'; reject.dataset.draftAct = 'reject';
    approve.setAttribute('aria-label', 'approve draft ' + d.id);
    reject.setAttribute('aria-label', 'reject draft ' + d.id);
    approve.addEventListener('click', () => draftDecide(d.id, 'approve', approve));
    reject.addEventListener('click', () => draftDecide(d.id, 'reject', reject));
    acts.append(approve, reject);
    node.append(head, to, body, meta, cause, err, acts);
    const view = { node, st, to, body, meta, cause, err, approve, reject };
    draftView.set(d.id, view);
    return view;
  }
  function paintCard(d) {
    const v = draftCard(d);
    v.node.dataset.state = d.state;
    v.st.textContent = d.state;                                  // the four words, and only the four
    v.to.textContent = d.recipient ? 'to ' + d.recipient : 'to — (no recipient in payload)';
    v.body.textContent = d.body || '(no body in payload)';
    const when = DRAFT_TIME(d.created_at);
    v.meta.textContent = when
      ? 'created ' + when + (d.outcome ? ' · outcome ' + d.outcome : '')
      : (d.outcome ? 'outcome ' + d.outcome : '');
    v.cause.textContent = d.state === 'failed' && d.cause ? 'cause: ' + d.cause : '';
    v.cause.hidden = !v.cause.textContent;
    v.err.textContent = d.error || '';
    v.err.hidden = !v.err.textContent;
    const live = d.state === 'pending' && !d.busy;
    v.approve.disabled = !live; v.reject.disabled = !live;
    return v;
  }
  function renderDrafts() {
    const b = $('body-drafts');
    if (!b) return;
    b.replaceChildren();
    const stat = pendingDrafts();
    const live = daemon && typeof daemon.sendDraftCommand === 'function';
    if (!draftOrder.length) {
      b.append(draftEl('p', 'mini',
        'No draft feed received. Cards appear when the daemon reports a phone draft; '
        + 'approve / reject then POST draft.approve / draft.reject and only the daemon can send.'));
    } else {
      if (!stat.length) b.append(draftEl('p', 'mini', 'No pending drafts.'));
      stat.forEach((d) => b.append(paintCard(d).node));
      const resolved = draftOrder.filter((id) => draftStore.get(id).state !== 'pending').reverse();
      if (resolved.length) {
        b.append(draftEl('p', 'mini', resolved.length + ' resolved · newest first · history below the pending cards'));
        resolved.slice(0, 6).forEach((id) => b.append(paintCard(draftStore.get(id)).node));
      }
    }
    if (!live) {
      b.append(draftEl('p', 'mini', draftOrder.some((id) => draftStore.get(id).state === 'pending')
        ? '[WARN] no command transport — approve and reject fail closed; nothing is sent from this window.'
        : 'Command transport: not connected. With no daemon there is no approve path.'));
    }
    const badge = $('badge-drafts');
    if (badge) {
      badge.textContent = stat.length + ' pending';
      badge.className = 'badge ' + (stat.length ? 'warn' : 'st');
    }
    applyPhone(true);        // a removed signal recalculates; a live one upgrades
  }
  async function draftDecide(id, verb, button) {
    const d = draftStore.get(id);
    if (!d || d.state !== 'pending' || d.busy) return;
    const live = daemon && typeof daemon.sendDraftCommand === 'function';
    if (!live) { d.error = 'No command transport; nothing was sent.'; paintCard(d); return; }
    d.busy = true; d.error = ''; paintCard(d);
    try {
      const res = await daemon.sendDraftCommand({ command: 'draft.' + verb, draft_id: id });
      /* Accept ANY state word the daemon reports and let normDraft map it: 'rejected', 'expired'
         and 'send-error' are CAUSES under failed, never top states (IF-1 owner amendment). */
      const answered = res && typeof res === 'object'
        ? (res.state != null ? res : (res.draft && res.draft.state != null ? res.draft : null))
        : null;
      if (answered) upsertDraft(Object.assign({}, answered, { draft_id: id }), draftStore.get(id));
      /* and if the daemon reported nothing, the card stays pending on purpose: no local verdict. */
    } catch (e) {
      d.error = 'Daemon refused or unreachable: ' + ((e && e.message) || 'unknown') + ' Nothing was sent from this window.';
    } finally { d.busy = false; renderDrafts(); }
    if (button) button.blur();
  }
  function draftFrame(frame) {
    if (!frame || typeof frame !== 'object') return;
    let changed = 0;
    if (Array.isArray(frame.drafts)) {
      frame.drafts.forEach((raw) => { const d = upsertDraft(raw, draftStore.get(String((raw && raw.draft_id) || ''))); if (d) changed++; });
    } else if (frame.draft && typeof frame.draft === 'object') {
      const raw = frame.draft;
      if (upsertDraft(raw, draftStore.get(String(raw.draft_id || '')))) changed++;
    }
    if ('phone_connected' in frame) phoneConnected = frame.phone_connected === true;
    renderDrafts();
    return changed;
  }
  function draftResolveFrame(frame) {
    if (!frame || typeof frame !== 'object') return null;
    const raw = (frame.draft && typeof frame.draft === 'object') ? frame.draft : frame;
    if (!raw || raw.draft_id == null) return null;
    /* A resolution arriving without a state word is a SENT one (IF-2: a resolved event supersedes
       pending; the only send outcome is sent). An explicit word — including a cause — is honoured. */
    const d = upsertDraft(Object.assign({}, raw, { state: raw.state != null ? raw.state : 'sent' }), draftStore.get(String(raw.draft_id)));
    if (d) d.busy = false;
    renderDrafts();
    return d;
  }
  function draftTick() { renderDrafts(); }   // never touched by a timer; kept explicit for tests

  el.bNew.addEventListener('click', createSession);
  el.orb.addEventListener('click', calmWants);
  document.addEventListener('click', (e) => { if (!e.target.closest('.sb, .tools, #full')) calmWants(); });

  /* commands */
  const CMDS = [
    { n: 'help', u: '/help', d: 'this list', f: () => { const g = h('div', 'cmds'); CMDS.forEach((c) => g.append(h('code', '', c.u), h('span', '', c.d))); out(g); } },
    { n: 'status', u: '/status', d: 'lamps, and what each one means', f: () => out(statusText()) },
    { n: 'demo', u: '/demo', d: 'fill transcript and audio with clearly-marked sample rows', f: () => {
      demoOn = !demoOn; syncBadges(); if (openSec) renderSec(openSec);
      openFull(demoOn ? 'transcript' : (fullPane || 'transcript'), true);   // force: /demo must never close what is open
      if (demoOn) notify({ text: 'Sample notification. This is how I tap you on the shoulder.', speak: true, log: false });
      else out('sample rows cleared.'); } },
    { n: 'transcript', u: '/transcript', d: 'open the transcript full screen   (alt+1)', f: () => openFull('transcript', true) },
    { n: 'memory', u: '/memory', d: 'open her memory cards   (alt+2)', f: () => openPane('memory') },
    { n: 'audio', u: '/audio', d: 'open the audio manifest   (alt+3)', f: () => openPane('audio') },
    { n: 'drafts', u: '/drafts', d: 'phone draft review — pending, and what each draft became', f: () => {
      setSec('drafts'); renderDrafts();
      const n = pendingDrafts().length;
      out(n ? n + ' pending draft' + (n === 1 ? '' : 's') + ' in the sidebar. Approve or reject sends the command and waits for the daemon; nothing is sent from this window.'
            : 'no pending drafts. ' + (draftOrder.length ? draftOrder.length + ' resolved, listed under the feed.' : 'no draft feed received yet.')); } },
    { n: 'panel', u: '/panel NAME|off', d: 'transcript | memory | audio | off', f: (a) => {
      const s = (a || '').toLowerCase();
      if (!PANES.concat('off').includes(s)) return out('panes: transcript, memory, audio, off');
      openPane(s); } },
    { n: 'state', u: '/state NAME', d: 'her orb: idle, listening, thinking, speaking, offline', f: (a) => {
      const s = (a || '').toLowerCase();
      if (!LABEL[s]) return out('states: ' + Object.keys(LABEL).join(', '));
      if (s === 'speaking') return out('Speaking follows output levels only; synthetic cadence is not speech.');
      forcedOffline = s === 'offline'; setState(s); } },
    { n: 'notify', u: '/notify TEXT', d: 'preview the mini-orb notification', f: (a) => notify({ text: a || 'Elaria here. I look like this when I have something to say.', speak: true, log: false }) },
    { n: 'sim', u: '/sim', d: 'synthetic voice on or off, so her orb is not frozen', f: () => { simOn = !simOn; if (V) V.simulate(simOn); syncOrb();
      out('simulated voice ' + (simOn ? '[ON]' : '[OFF]') + (simOn ? ' — her orb moves with no wire attached.' : '')); } },
    { n: 'sidebar', u: '/sidebar', d: 'hide or show the left sidebar   (alt+K)', f: () => toggleSb() },
    { n: 'orb', u: '/orb', d: 'hide or show her orb rail   (alt+B)', f: () => toggleOrb() },
    { n: 'big', u: '/big', d: 'cycle font size   (alt+0 resets)', f: () => setSize((data.prefs.big + 1) % SIZES.length) },
    { n: 'new', u: '/new', d: 'new session   (alt+N)', f: createSession },
    { n: 'ls', u: '/ls', d: 'list sessions with an index', f: () => {
      const g = h('div', 'cmds');
      data.sessions.forEach((s, i) => g.append(h('code', '', (s.id === data.active ? '* ' : '  ') + String(i + 1).padStart(2, '0')),
        h('span', '', s.name + ' · ' + s.msgs.length + ' msg')));
      out(g); } },
    { n: 'use', u: '/use N', d: 'switch to session N from /ls', f: (a) => {
      const i = parseInt(a, 10) - 1;
      if (!data.sessions[i]) return out('[ERR] no session ' + (a || '?') + '. /ls shows the index.');
      switchTo(i); } },
    { n: 'export', u: '/export', d: 'download every session as json', f: () => {
      const blob = new Blob([JSON.stringify({ exported: new Date().toISOString(), sessions: data.sessions }, null, 2)], { type: 'application/json' });
      const a = h('a'); a.href = URL.createObjectURL(blob); a.download = 'elaria-sessions.json'; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000); out('exported ' + data.sessions.length + ' session(s).'); } },
    { n: 'wipe', u: '/wipe', d: 'clear local storage   [WARN] asks first', f: (a) => {
      if ((a || '').toLowerCase() === 'yes' && wipeArmed) {
        wipeArmed = false; try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ }
        boot(true); return;
      }
      wipeArmed = true; out('[WARN] this deletes every session in this browser. Type /wipe yes to confirm, anything else cancels.'); } },
    { n: 'crt', u: '/crt', d: 'scanlines on or off', f: () => { data.prefs.crt = !data.prefs.crt; applyPrefs(); save(); } },
    { n: 'clear', u: '/clear', d: 'clear the screen, keep the session', f: () => el.pad.replaceChildren() }
  ];
  function setSize(i) { data.prefs.big = i; applyPrefs(); save(); }
  function applyPrefs() {
    document.documentElement.style.setProperty('--fs', SIZES[data.prefs.big] + 'px');
    el.term.classList.toggle('crt', !!data.prefs.crt);
  }

  /* conversation */
  // SYNTHESISED TEXT CADENCE, never measured audio. F29: no client playback/attachElement.
  const levelFor = (ch) => (/[\s.,;:!?]/.test(ch) ? .06 : .38 + Math.random() * .5);
  let abortType = null;
  function typeInto(body, text) {
    return new Promise((res) => {
      let i = 0; const per = Math.max(1, Math.ceil(text.length / 260));
      const finish = () => {
        clearTimeout(typeT); typeT = 0; abortType = null;
        body.innerHTML = paintHer(text); if (!wireRequested) setLevels('output', 0); pin(); res();
      };
      abortType = finish;
      (function tick() {
        i = skip ? text.length : Math.min(text.length, i + per);
        body.textContent = text.slice(0, i);
        if (!wireRequested) setLevels('output', skip ? 0 : levelFor(text[i - 1] || ' '));
        pin();
        if (i >= text.length) return finish();
        typeT = setTimeout(tick, 24);
      })();
    });
  }
  /* Esc, a session switch and "new session" all land here. Without it the typewriter promise never
     resolves and `busy` sticks true forever — the old Esc handler cleared typeT with nothing left to
     call the resolver, which locked the shell for the rest of the session. */
  function interrupt() {
    if (!busy) return;
    skip = true;
    if (abortType) abortType();
  }
  /* F21/F34: silent, memory-only consent cards and replayable denial summaries, sidebar ONLY. */
  let handsCard = null;
  function clearHandsAsk() {
    if (!handsCard) return;
    clearInterval(handsCard.timer); handsCard.box.remove(); handsCard = null;
  }
  function hideHandsAsk() {
    if (!handsCard) return;
    handsCard.selected = false; handsCard.details.replaceChildren();
    handsCard.reveal.hidden = false;
  }
  function handsError(message) {
    clearHandsAsk(); $('hands-state').textContent = message;
  }
  function renderHands(value, elapsedBeforePaint = 0) {
    clearHandsAsk();
    if (!value || !Array.isArray(value.events)) return handsError('Hands unavailable — no backend receipt.');
    $('hands-state').textContent = (value.open ? 'Dedicated hand open' : 'Hand closed or faulted') +
      ' · instance ' + value.instance + ' · showing ' + value.events.length + ' of ' +
      (value.total_events || value.events.length) + ' journal events · ask fallback: deny · owner hardware acceptance pending';
    const events = $('hands-events'); events.replaceChildren();
    value.events.forEach(row => {
      const item = h('p', 'hands-event');
      item.textContent = '#' + row.seq + ' ' + row.phase + ' · ' + row.reason +
        (row.verification ? ' · ' + row.verification : '') + (row.action ? ' · action #' + row.action : '');
      item.append(h('small', '', ' instance ' + (row.instance || value.instance)));
      if (row.plan_hash) item.append(h('small', '', ' plan ' + row.plan_hash));
      if (row.stdout_sha256) item.append(h('small', '', ' stdout SHA256 ' + row.stdout_sha256));
      if (row.target_sha256) item.append(h('small', '', ' target SHA256 ' + row.target_sha256));
      if (row.exit_code != null) item.append(h('small', '', ' exit ' + row.exit_code));
      events.append(item);
    });
    if (!value.ask || !daemon || typeof daemon.handsControl !== 'function') return;
    const ask = {...value.ask, remaining_s:value.ask.remaining_s-elapsedBeforePaint};
    if(!(ask.remaining_s>0)) return handsError('Hands ask expired — fallback deny. Prepare again.');
    const box = h('section', 'hands-ask'), reveal = h('button', '', 'elaria needs a yes — review hands privately');
    reveal.type = 'button'; const details = h('div'), age = h('p');
    box.append(reveal, age, details); $('hands-review').append(box);
    const card = {ask, box, reveal, details, started:performance.now(), wall:Date.now(),
      session:cur().id, selected:false, spent:false, control:daemon.handsControl};
    handsCard = card;
    const elapsed = () => Math.max(performance.now()-card.started, Date.now()-card.wall, 0)/1000;
    const fresh = () => handsCard === card && !card.spent && cur().id === card.session &&
      !document.hidden && document.hasFocus() && elapsed() < ask.remaining_s;
    reveal.onclick = () => {
      if (!fresh()) return;
      reveal.hidden = true; card.selected = true; details.replaceChildren();
      details.append(h('h3', '', 'Whole-plan consent · silent · default allow once'));
      details.append(h('p', '', 'Only the daemon-started dedicated instance; never your daily terminal.'));
      const disclosure = h('pre'); disclosure.textContent = JSON.stringify(ask.plan, null, 2); details.append(disclosure);
      details.append(h('p', '', 'Plan digest ' + ask.digest + '. No means terminal refusal. Missing marker means unknown, never success.'));
      const hint = h('p'), once = h('button', '', 'Yes — allow once'), no = h('button', '', 'No — deny');
      once.type = no.type = 'button'; once.dataset.handsDecision='allow-once'; no.dataset.handsDecision='deny';
      async function answer(decision) {
        if (!fresh() || !card.selected || !details.contains(document.activeElement)) {
          hint.textContent = 'No fresh private ask is selected.'; return;
        }
        card.spent = true;
        clearHandsAsk(); $('hands-state').textContent='Decision submitted once; awaiting observation. No automatic replay.';
        try { const response = await card.control({action:'answer', review_id:ask.review_id, digest:ask.digest, decision});
          if(response.hands) renderHands(response.hands); else handsError(response.hands_error || 'Outcome unknown; inspect journal.');
        } catch(e) {handsError('Outcome unknown; no automatic replay.');}
      }
      once.onclick=()=>answer('allow-once'); no.onclick=()=>answer('deny');
      details.append(once,no);
      if(ask.allow_always === true) {
        const always=h('button','','Allow always — this exact argv and binary/inventory hashes');
        always.type='button'; always.dataset.handsDecision='allow-always'; always.onclick=()=>answer('allow-always'); details.append(always);
      }
      const entry=h('input'); entry.setAttribute('aria-label','Focused hands decision: exact yes or no');
      entry.autocomplete='off'; entry.addEventListener('keydown',event=>{
        if(event.key!=='Enter') return;
        event.preventDefault(); event.stopPropagation();
        const v=entry.value.trim().toLowerCase();
        if(v==='yes'||v==='no') answer(v==='yes'?'allow-once':'deny'); else hint.textContent='Exact yes or no only.';
      });
      details.append(entry,hint); no.focus();
    };
    card.timer=setInterval(()=>{
      if(elapsed()>=ask.remaining_s) {handsError('Hands ask expired — fallback deny. Prepare again.');return;}
      age.textContent='Ask age '+Math.floor(elapsed())+'s · expires in '+Math.max(0,Math.floor(ask.remaining_s-elapsed()))+'s';
      if(document.hidden||!document.hasFocus()) hideHandsAsk();
    },200);
  }
  window.addEventListener('blur',hideHandsAsk);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)hideHandsAsk();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')hideHandsAsk();});
  document.querySelectorAll('[data-hands-control]').forEach(button=>{
    button.onclick=async()=>{
      clearHandsAsk();
      if(!daemon||typeof daemon.handsControl!=='function') return handsError('Hands backend not connected; no action sent.');
      button.disabled=true;
      try {const response=await daemon.handsControl({action:button.dataset.handsControl});
        if(response.hands)renderHands(response.hands);else handsError(response.hands_error||'Hands unavailable.');
      } catch(e) {handsError('Hands outcome unknown; no replay.');}
      finally {button.disabled=false;}
    };
  });

  /* Undo pilot: private, memory-only, connection-bound. Never stored in sessions or notifications. */
  let undoCard = null, undoPrivate = false;
  function clearUndo(reason) {
    if (!undoCard) return;
    clearInterval(undoCard.timer); undoCard.panel.remove(); undoCard = null;
    if (reason) out('[UNDO REVIEW] ' + reason);
  }
  function undoElapsed(c) {
    return Math.max(performance.now() - c.mono, Date.now() - c.wall, 0) / 1000;
  }
  function hideUndo() {
    const c = undoCard; if (!c) return;
    c.selected = false; c.privateBox.replaceChildren(); c.privateBox.hidden = true;
    c.reveal.hidden = false;
  }
  function renderUndo(review, decide, elapsed) {
    clearUndo('Previous card invalidated by a new preparation.');
    if (!review || !review.snapshot || typeof decide !== 'function'
        || typeof review.remaining_s !== 'number' || review.remaining_s <= elapsed) return;
    const c = {review, decide, mono:performance.now(), wall:Date.now(),
      remaining:review.remaining_s-elapsed, age:review.age_s+elapsed, session:cur().id,
      selected:false, spent:false, allowed:wireRequested ? undoPrivate : true};
    const panel = h('section', 'undo-review'); panel.setAttribute('aria-label', 'Private undo review');
    const reveal = h('button', '', 'elaria needs a yes — review privately'); reveal.type = 'button';
    const privateBox = h('div'); privateBox.hidden = true;
    const clock = h('p', 'undo-age');
    panel.append(reveal, clock, privateBox); document.body.append(panel);
    Object.assign(c, {panel,reveal,privateBox,clock}); undoCard = c;
    function fresh() {
      return undoCard === c && !c.spent && c.allowed && cur().id === c.session
        && !document.hidden && document.hasFocus() && undoElapsed(c) < c.remaining;
    }
    function show() {
      if (!fresh()) return;
      c.selected = true; reveal.hidden = true; privateBox.hidden = false;
      privateBox.replaceChildren();
      privateBox.append(h('h2', '', 'Undo — one prepared operation'));
      privateBox.append(h('p', '', 'Private review selected. Yes approves only this immutable snapshot.'));
      const rows = [
        ['Operation', 'op_id', 'op', 'plan_id', 'ts', 'status'],
        ['Targets — src is original; dst is current home', 'src', 'dst'],
        ['Preconditions — rechecked by apply', 'sha256_before', 'sha256_after']
      ];
      for (const [label, ...fields] of rows) {
        privateBox.append(h('h3', '', label));
        for (const field of fields) privateBox.append(h('p', '', field + ': ' + String(review.snapshot[field])));
      }
      privateBox.append(h('p', '', 'Snapshot digest: ' + review.ask_sha256));
      privateBox.append(h('p', '', 'Prepared at: ' + review.prepared_at + ' (wall-clock label; expiry uses a conservative elapsed budget).'));
      privateBox.append(h('h3', '', 'Collateral and reversal limits'));
      privateBox.append(h('p', '', 'Audited executor semantics, not extra prepared targets: undo can retire an identical duplicate through trash, write journal/state, and remove an emptied _Conflicts/_Unsorted parent. Prepare supplies no resolved root or collateral inventory. No extra scope is requested here.'));
      privateBox.append(h('p', '', 'No promise of exact metadata restoration or atomic reversal. Drift, missing targets, expiry or restart refuse the ask. A transport result is not independent effect verification.'));
      const yes = h('button', '', 'Yes — apply this snapshot'), no = h('button', '', 'No — terminal refusal');
      yes.type = no.type = 'button'; yes.dataset.decision = 'yes'; no.dataset.decision = 'no';
      const entry = h('input'); entry.setAttribute('aria-label', 'Focused undo decision: exact yes or no');
      entry.autocomplete = 'off'; entry.spellcheck = false;
      const hint = h('p', '', 'Use these buttons or the dedicated entry, never chat.');
      const hide = h('button', '', 'Hide private review'); hide.type = 'button'; hide.onclick = hideUndo;
      async function answer(value) {
        if (!fresh() || !c.selected || !privateBox.contains(document.activeElement)) {
          hint.textContent = 'no ask is selected'; return;
        }
        if (!['yes', 'no'].includes(value)) { hint.textContent = 'Enter exact yes or no.'; return; }
        c.spent = true; yes.disabled = no.disabled = entry.disabled = true;
        // Remove all private fields before dispatch; never re-arm this card on any failure.
        clearUndo('Decision submitted once; awaiting daemon receipt.');
        try { const result = await decide({review_id:review.review_id, ask_sha256:review.ask_sha256, decision:value});
          out(result.text || '[UNDO REVIEW] answer received; no effect verification claimed.');
        } catch (error) { out('[UNDO REVIEW] ' + (error.message || 'outcome unknown; no replay')); }
      }
      yes.onclick = () => answer('yes'); no.onclick = () => answer('no');
      entry.addEventListener('keydown', event => {
        if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); answer(entry.value.trim().toLowerCase()); }
      });
      privateBox.append(yes, no, entry, hint, hide); no.focus();
    }
    reveal.onclick = show;
    function tick() {
      const elapsed = undoElapsed(c);
      if (elapsed >= c.remaining) { clearUndo('lapsed — fresh prepare required, never a Yes.'); return; }
      clock.textContent = 'Ask age: ' + Math.floor(c.age+elapsed) + 's · lapses in ' + Math.max(0, Math.floor(c.remaining-elapsed)) + 's';
      if (cur().id !== c.session) clearUndo('Selection changed; old approval is stale.');
      else if (document.hidden || !document.hasFocus() || !c.allowed) hideUndo();
    }
    c.timer = setInterval(tick, 200); tick();
  }
  window.addEventListener('blur', hideUndo);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') hideUndo(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) hideUndo(); });

  async function deliver(rep, owner) {
    const s = owner || cur();                       // bound at send time: an interrupt or a session
    // F29: deliberately DROP reply.audio without reading it (URL, element or getter).
    // The daemon gateway is the sole playback owner; the console must never double-play.
    const text = typeof rep === 'string' ? rep : String(rep.text || '');  // switch must not
    const m = msgEl('ai', ''), body = m.querySelector('.body');                                    // move her reply
    body.classList.add('typing'); el.pad.append(m); pin();                                          // into another session
    el.log.setAttribute('aria-busy', 'true');
    await typeInto(body, text);
    body.classList.remove('typing'); el.log.removeAttribute('aria-busy'); skip = false;
    pushTo(s, 'ai', text, rep && rep.attribution);
    pin();
    if (!document.hasFocus() || document.hidden) { away = text; document.title = '\u25cf Elaria'; }
  }
  function respond(text) {
    const t = text.trim().toLowerCase();
    if (/^(hi|hey|hello|yo|sup|morning|evening)\b/.test(t))
      return 'stub hello. the real one will have more bite — this window does not have my voice behind it yet.';
    if (t.includes('status') || t.includes('wire') || t.includes('daemon')) return statusText();
    if (t.includes('help') || t.includes('command') || t.includes('what can')) return cmdHelp();
    if (t.includes('transcri') || t.includes('memor') || t.includes('audio') || t.includes('wav'))
      return 'those are sections in the sidebar, under sessions. transcript opens full screen across the chat and the orb — the sidebar stays where it is. memory and audio fold open in the sidebar and each has an "open full screen" button inside.\n\nkeys: alt+1 transcript, alt+2 memory, alt+3 audio, alt+K sidebar, alt+B orb.\n\ntranscript and audio wait for their own data feeds — /demo shows the shape they will take, marked [SAMPLE]. memory already has 11 real cards baked into this file.';
    if (t.includes('orb') || t.includes('visual') || t.includes('ball'))
      return 'she is on the right in a proportional panel, yielding to chat on narrow screens. the readout names the current state and signal. the mic is read from the daemon\'s capture.state — this window never opens a browser microphone. /sim turns the synthetic voice off.';
    if (t.includes('notif') || t.includes('pop') || t.includes('tap'))
      return 'top right, a mini orb with her name and the message — that is the tap on the shoulder. an amber pip stays on the orb rail after the toast fades, so you still know she wanted you. /notify fires one now.';
    return STUBS[stubI++ % STUBS.length];
  }
  function cmdHelp() {
    const g = 'commands this shell answers itself:\n\n';
    return g + CMDS.map((c) => '  ' + c.u.padEnd(20) + c.d).join('\n') +
      '\n\nkeys: alt+1 transcript · alt+2 memory · alt+3 audio · alt+K sidebar · alt+B orb · alt+N new · alt+0 font · esc close/skip\n\nanything that is not a command is a sentence, and a sentence comes to me.';
  }
  async function send(text) {
    if (!daemon && wireRequested) return out('[WARN] daemon wire unavailable — no turn sent and no stub reply.');
    if (forcedOffline) return out('[WARN] I am marked offline. /state idle wakes me.');
    if (busy) return out('still answering the last one. Esc skips ahead.');
    clearHandsAsk();
    clearUndo('New chat input invalidated the previous review; prepare fresh.');
    const s = cur();
    pinned = true; el.pad.append(msgEl('me', text)); pushTo(s, 'me', text); pin(); calmWants();
    busy = true; setState('thinking');
    try {
      const t0 = performance.now();
      const rep = daemon ? await daemon.send(text, { session: s.name, history: s.msgs.slice(-20) }) : respond(text);
      const left = 700 - (performance.now() - t0);   // hold "thinking" long enough to read as a state change
      if (left > 0) await sleep(left);
      if (rep && (rep.hands || rep.hands_error)) {
        if(rep.hands)renderHands(rep.hands,(performance.now()-t0)/1000);else handsError(rep.hands_error);
        return;
      }
      if (rep && rep.undoReview) renderUndo(rep.undoReview, daemon && daemon.decideUndo, (performance.now()-t0)/1000);
      await deliver(rep, s);
    } catch (err) {
      if(text.toLowerCase().startsWith('hands ')) {handsError('Hands unavailable/outcome unknown; no replay.');return;}
      const message = '[BROKEN] the daemon call failed: ' + ((err && err.message) || 'unknown error');
      el.pad.append(msgEl('err', message, null, err && err.attribution));
      pushTo(s, 'err', message, err && err.attribution); pin();
    } finally { busy = false; settle(); }
  }
  async function run(v) {
    if (wipeArmed && !/^\/wipe\s+yes$/i.test(v)) wipeArmed = false;
    if (v[0] !== '/') return send(v);
    pinned = true; el.pad.append(msgEl('me', v)); push('me', v); pin();
    const [n, ...rest] = v.slice(1).split(/\s+/), c = CMDS.find((x) => x.n === n.toLowerCase());
    if (c) c.f(rest.join(' ')); else out('[ERR] no command /' + n + '. /help lists what I answer myself.');
    renderSess();
  }

  /* input */
  const autosize = () => { el.ta.style.height = 'auto'; el.ta.style.height = Math.min(el.ta.scrollHeight, 180) + 'px'; };
  let typingT = 0, tab = { base: null, i: -1 };
  el.ta.addEventListener('input', () => {
    autosize(); tab.base = null; calmWants();
    if (busy || forcedOffline || micPipelineLive()) return;
    if (el.ta.value.trim()) { setState('listening'); setLevels('input', .3 + Math.random() * .55); }
    clearTimeout(typingT); typingT = setTimeout(settle, 2200);
  });
  el.form.addEventListener('submit', (e) => {
    e.preventDefault();
    const v = el.ta.value.trim(); if (!v) return;
    el.ta.value = ''; autosize(); hist.push(v); hi = hist.length; run(v);
  });
  el.ta.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); el.form.requestSubmit(); }
    else if (e.key === 'Tab' && el.ta.value.startsWith('/') && !/\s/.test(el.ta.value)) {
      e.preventDefault();
      if (tab.base === null) { tab.base = el.ta.value.slice(1).toLowerCase(); tab.i = -1; }
      const hits = CMDS.filter((c) => c.n.startsWith(tab.base));
      if (!hits.length) return;
      tab.i = (tab.i + 1) % hits.length; el.ta.value = '/' + hits[tab.i].n + (hits.length === 1 ? ' ' : '');
    } else if (e.key === 'ArrowUp' && el.ta.selectionStart === 0 && hi > 0) { e.preventDefault(); el.ta.value = hist[--hi]; autosize(); }
    else if (e.key === 'ArrowDown' && hi < hist.length && !el.ta.value.slice(el.ta.selectionEnd).includes('\n')) {
      e.preventDefault(); hi++; el.ta.value = hist[hi] || ''; autosize();
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (el.full.classList.contains('open')) return closeFull();
      if (document.body.classList.contains('sb-peek')) { toggleSb(false); el.ta.focus(); return; }
      if (busy) interrupt();
      return;
    }
    if (!(e.altKey || e.ctrlKey)) return;
    if (e.ctrlKey && !e.altKey && !['Digit0', 'Digit1', 'Digit2', 'Digit3', 'Digit4', 'KeyK', 'KeyB'].includes(e.code)) return;
    const act = {
      KeyN: createSession, KeyK: () => toggleSb(), KeyB: () => toggleOrb(), Digit0: () => setSize(0),
      Digit1: () => openFull('transcript'), Digit2: () => openPane('memory'), Digit3: () => openPane('audio'),
      Digit4: () => { setSec('drafts'); renderDrafts(); }
    }[e.code];
    if (act) { e.preventDefault(); act(); }
  });
  window.addEventListener('focus', () => {
    document.title = 'Elaria';
    if (away) { notify({ text: away.length > 120 ? away.slice(0, 117) + '\u2026' : away, log: false }); away = null; }
  });

  /* the wire, prepared
     Nothing here opens a socket by itself. attachSocket(url) is the ONE call the mainline builder
     makes once the daemon side exists; until then it fails closed and every lamp keeps telling the
     truth. The protocol is written down in INTEGRATION.md — this is its client half.
     localhost only, no key, no traffic leaves the machine. */
  const WIRE_V = 1;
  let wireRequested = false;  // attaching a wire never silently falls back to standalone stubs
  function attachSocket(url) {
    url = url || 'ws://127.0.0.1:8744/elaria';
    const endpoint = new URL(url);
    if (!['ws:', 'wss:'].includes(endpoint.protocol)
        || !['127.0.0.1', 'localhost', '[::1]'].includes(endpoint.hostname)
        || endpoint.username || endpoint.password) throw new Error('console wire must be localhost only');
    wireRequested = true;
    let ws = null, dead = false, tries = 0, n = 0;
    const pend = new Map();
    const backoff = () => Math.min(15000, 700 * Math.pow(1.7, tries++));
    function open() {
      if (dead || typeof WebSocket === 'undefined') return;
      try { ws = new WebSocket(url); } catch (e) { retry(); return; }
      ws.onopen = () => {
        ws.send(JSON.stringify({ t: 'hello', v: WIRE_V, client: 'console', caps: ['text', 'state', 'transcript', 'audio', 'memory', 'capture.levels', 'capture.state'] }));
      };
      ws.onmessage = (ev) => { let m; try { m = JSON.parse(ev.data); } catch (e) { return; } route(m); };
      ws.onclose = () => {
        ws = null;
        pend.forEach((finish) => finish({ error: 'wire disconnected; a submitted turn may still complete. Inspect the daemon conversation before repeating it. No automatic replay.' }));
        pend.clear(); window.ElariaShell.disconnect(); retry();
      };
      ws.onerror = () => { try { if (ws) ws.close(); } catch (e) { /* already closing */ } };
    }
    function retry() { if (!dead) setTimeout(open, backoff()); }
    function route(m) {
      if (!m || !m.t) return;
      if (m.t === 'hello-ok') {
        if (m.v !== WIRE_V) { dead = true; ws.close(); window.ElariaShell.disconnect(); return; }
        tries = 0;  // reset only AFTER a real handshake, not every failed TCP reconnect
        return window.ElariaShell.connect({ name: m.name || 'daemon', send: sendOver, decideUndo, handsControl });
      }
      if (m.t === 'undo-privacy') { undoPrivate = m.allowed === true; if (undoCard) { undoCard.allowed = m.allowed === true; if (!undoCard.allowed) hideUndo(); } return; }
      if (m.t === 'reply') { const p = pend.get(m.id); pend.delete(m.id); if (p) { if (m.undo_review) undoPrivate = true; p(m); } return; }
      if (m.t === 'state') return window.ElariaShell.setState(m.name);   // unknown names THROW inside
      if (m.t === 'levels') return window.ElariaShell.levels(m.role, m.level);
      if (m.t === 'capture-state') return window.ElariaShell.captureState(m.name, m.reason);
      if (m.t === 'notify') return window.ElariaShell.notify({ text: m.text || '', speak: !!m.speak });
      if (m.t === 'transcript') return window.ElariaShell.transcript(m.rows || []);
      if (m.t === 'audio') return window.ElariaShell.audio(m.rows || []);
      if (m.t === 'memory') return window.ElariaShell.memory(m.cards || []);
      if (m.t === 'drafts') return window.ElariaShell.drafts(m);
      if (m.t === 'draft-resolve') return window.ElariaShell.draftResolved(m);
      if (m.t === 'bye') { dead = true; try { if (ws) ws.close(); } catch (e) { /* gone */ } window.ElariaShell.disconnect(); }
    }
    function sendOver(text, ctx) {
      return new Promise((res, rej) => {
        if (!ws || ws.readyState !== 1) return rej(new Error('wire not open'));
        const id = ++n;
        pend.set(id, (m) => {
          if (m.error) { const error = new Error(m.error); error.attribution = receiptRows(m.attribution); rej(error); }
          // F29: drop audio at the wire boundary as well as the adapter renderer.
          else res({ text: m.text || '', attribution: receiptRows(m.attribution), undoReview:m.undo_review, hands:m.hands, hands_error:m.hands_error });
        });
        const message = { t: 'send', id, text, session: ctx && ctx.session,
          history: ctx && ctx.history ? ctx.history.slice(-20) : [] };
        let encoded = JSON.stringify(message);
        // History is display context, not daemon authority. Trim oldest context to the wire bound.
        while (new Blob([encoded]).size > 65536 && message.history.length) {
          message.history.shift(); encoded = JSON.stringify(message);
        }
        if (new Blob([encoded]).size > 65536) {
          pend.delete(id); rej(new Error('message exceeds the 64 KiB wire bound; no turn sent')); return;
        }
        ws.send(encoded);
        setTimeout(() => { if (pend.delete(id)) rej(new Error('daemon went quiet')); }, 45000);
      });
    }
    function handsControl(control) {
      return new Promise((res,rej)=>{
        if(!ws||ws.readyState!==1)return rej(new Error('hands wire unavailable'));
        const id=++n;
        pend.set(id,m=>res(m));
        ws.send(JSON.stringify({t:'hands-control',id,...control}));
        setTimeout(()=>{if(pend.delete(id))rej(new Error('hands outcome unknown; no replay'));},45000);
      });
    }
    function decideUndo(decision) {
      return new Promise((res, rej) => {
        if (!ws || ws.readyState !== 1) return rej(new Error('disconnected; prepare a fresh ask'));
        const id = ++n;
        pend.set(id, m => m.error ? rej(new Error(m.error)) : res(m));
        ws.send(JSON.stringify({t:'undo-decision', id, ...decision}));
        setTimeout(() => { if (pend.delete(id)) rej(new Error('outcome unknown; no replay')); }, 45000);
      });
    }
    open();
    return {
      close() { dead = true; try { if (ws) ws.close(); } catch (e) { /* gone */ } window.ElariaShell.disconnect(); },
      get open() { return !!ws && ws.readyState === 1; }
    };
  }

  /* public integration surface */
  window.ElariaShell = {
    connect(adapter) {
      if (!adapter || typeof adapter.send !== 'function') throw new Error('ElariaShell.connect needs { send(text, ctx) }.');
      daemon = adapter; forcedOffline = false;
      simOn = false; if (V) V.simulate(false);
      // The wire is live; any capture state from a previous connection is stale.
      captureState = null; captureReason = null;
      syncOrb();
      lamps(); settle();
      notify({ text: 'Daemon connected' + (adapter.name ? ': ' + adapter.name : '') + '.', log: false });
      out('[OK] wire up. replies use the attached adapter; each pane keeps its own data status.');
    },
    disconnect() {
      clearHandsAsk();
      undoPrivate = false; clearUndo('Disconnected; old card invalidated.');
      if (!daemon) return;
      daemon = null; forcedOffline = true;
      captureState = null; captureReason = null;
      renderMic(); setMicNote('no capture signal from this window'); lamps(); setState('offline'); syncOrb();
      notify({ text: 'Lost the daemon wire. Marked offline until it returns.', log: false });
    },
    notify(o) { notify(o || {}); },
    attachSocket(url) { return attachSocket(url); },
    say(text) { if (!busy) { const s = cur(); busy = true; deliver(text, s).finally(() => { busy = false; settle(); }); } },
    // unknown names THROW (IF-4: no silent default). Derived phone states are refused here —
    // they exist only while their signals do, so nothing can paint one by hand.
    setState(s) {
      if (!LABEL[s]) throw new Error('unknown orb state "' + s + '" — no silent default');
      if (BASE_STATE[s]) throw new Error('"' + s + '" is derived from the draft feed, not settable');
      forcedOffline = s === 'offline'; setState(s);
    },
    /* IF-2 consumer surface. drafts(frame) is transport-driven (draft.pending/draft.resolved ride
       the wire as 'drafts' and 'draft-resolve' frames); draftResolved(frame) upserts one resolution;
       draftsForTest()/draftId() are read/act helpers for the stub-daemon harness only. */
    drafts(frame) { return draftFrame(frame); },
    draftResolved(frame) { return !!draftResolveFrame(frame); },
    get pendingDraftCount() { return pendingDrafts().length; },
    draftIds() { return draftOrder.slice(); },   // test helper: every known draft, in order
    draftState(id) { const d = draftStore.get(String(id)); return d ? d.state : null; },  // test helper
    get phoneConnected() { return phoneConnected; },
    levels(role, level) { setLevels(role, level); },
    captureState(name, reason) { captureStateFromFrame(name, reason); },
    transcript(rows) { liveTR = nonempty(rows); demoOn = false; syncBadges(); if (openSec === 'transcript') renderSec('transcript'); if (fullPane === 'transcript') renderFull(); },
    audio(rows) { liveAU = nonempty(rows); demoOn = false; syncBadges(); if (openSec === 'audio') renderSec('audio'); if (fullPane === 'audio') renderFull(); },
    memory(cards) { liveMEM = nonempty(cards); syncBadges(); if (openSec === 'memory') renderSec('memory'); if (fullPane === 'memory') renderFull(); },
    get state() { return { daemon: !!daemon, mic: captureState, state, pane: fullPane, section: openSec }; }
  };

  /* boot */
  function seed() {
    const s = newSession('boot');
    const now = Date.now();
    const B = [
      ['sys',  'elaria console shell v6 — ' + new Date().toLocaleString() + ' — type /help for commands'],
      ['sys',  'lamps   console [ON]   daemon [NOT CONNECTED]   voice [NOT CONNECTED]   wire [ABSENT]'],
      ['note', 'colour key — green her · white you · orange names and numbers · blue system · violet aside · amber not-yet · red broken · ice paths · acid commands'],
      ['note', 'layout — sessions, transcript, memory, audio and draft review in the left sidebar. her orb in a proportional panel on the right, yielding on narrow screens. the centre is the chat, always. transcript opens full screen across the chat and the orb; the sidebar stays exactly where it is.'],
      ['note', 'notification — when she wants you, a mini orb pops top right with her name and the message. /notify fires one so you can see it.'],
      ['note', 'Local shell preview — not a model answer.\n\nThe wide orb panel is proportional; narrow screens prioritise chat. /demo displays marked sample rows; /notify demonstrates the local notification surface. These do not prove daemon feed or messaging capabilities.'],
      ['me',   '/help'],
      ['sys',  cmdHelp()]
    ];
    B.forEach(([r, t], i) => s.msgs.push({ r, t, ts: now - (B.length - i) * 4000 }));
    save();
  }
  function boot(fresh) {
    if (fresh || !data) {
      data = { sessions: [], active: null, prefs: { crt: false, big: 0, sb: true, orb: true } };
      seed();
    }
    if (!data.sessions.length || !cur()) { if (!data.sessions.length) seed(); else data.active = data.sessions[0].id; }
    applyPrefs();
    document.body.classList.toggle('sb-off', !data.prefs.sb);
    document.body.classList.toggle('orb-off', !data.prefs.orb);
    sidebarAria();
    el.tgOrb.setAttribute('aria-expanded', String(data.prefs.orb));
    renderLog(); renderSess(); lamps(); paintState(state); syncBadges(); syncOrb(); renderDrafts();
    renderSec('transcript'); renderSec('memory'); renderSec('audio');
    setMicNote(captureStateText() || 'no capture signal from this window');
    el.ta.focus();
  }
  boot(false);

  bootVisualizer().then((inst) => {
    V = inst; V.simulate(simOn); V.setState(state); el.orb.classList.add('ready'); syncOrb();
  }).catch((err) => {
    vizErr = err.message;
    el.orb.classList.add('ready');
    el.stage.append(h('p', 'stage-msg', vizErr + ' The chat, sidebar and notifications still work.'));
    el.rs.textContent = 'No orb';
  });
})();
