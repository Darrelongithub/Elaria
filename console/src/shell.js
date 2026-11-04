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
 *                                                    { text, audio } where audio is a URL or an
 *                                                    <audio> element (CORS-enabled) for her voice.
 *   ElariaShell.disconnect()                         wire lost: lamps, offline state, notification.
 *   ElariaShell.notify({ text, speak })              proactive tap on the shoulder from the daemon.
 *   ElariaShell.say(text)                            push an unprompted reply into the log.
 *   ElariaShell.setState(name)                       idle | listening | thinking | speaking | offline.
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
  const LABEL = { idle: 'Idle', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking', offline: 'Offline' };
  const SIZES = [14, 16, 19];
  const PANES = ['transcript', 'memory', 'audio'];

  const el = {
    app: $('app'), sb: $('sb'), sList: $('sList'), bNew: $('bNew'),
    term: $('term'), log: $('log'), pad: $('logpad'), ta: $('input'), form: $('form'), jump: $('jump'),
    orb: $('orb'), stage: $('stage'), rs: $('rs'), rsrc: $('rsrc'), rm: $('rm'),
    orbnote: $('orbnote'), wants: $('wants'),
    tgSb: $('tgSb'), tgOrb: $('tgOrb'), tgFull: $('tgFull'), tbWhich: $('tbWhich'),
    full: $('full'), ftitle: $('ftitle'), fbadge: $('fbadge'), fsub: $('fsub'), fsearch: $('fsearch'),
    fdemo: $('fdemo'), fclose: $('fclose'), fbody: $('fbody'), toasts: $('toasts')
  };

  /* ------------------------------------------------------------------ colour passes
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

  /* ------------------------------------------------------------------ baked content (real ledger facts) */
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
    'stub reply. the daemon is not wired to this window, so this text is the shell talking, not me.\n\nwhat that proves: prompt, screen, colour pass, sidebar, orb and session store all work. that is the half you asked to see.',
    'stub again. note what did not happen: no network call, no api spend, no key touched. 0 requests left this browser.',
    'the shell is holding your text. this standalone window is not connected to a daemon.',
    'stub. /status shows which lamp is missing and why — amber means unavailable here; red means disconnected, not proof a component does not exist.',
    'still the shell. a connected adapter supplies replies; the wire lamp does not certify model output or an action.'
  ];
  let stubI = 0;
  const statusText = () => 'lamps, honestly:\n\n' +
    '  console   [ON]              this window, running, local\n' +
    '  daemon    [' + (daemon ? 'CONNECTED' : 'NOT CONNECTED') + ']   ' + (daemon ? 'adapter attached' : 'connection not established') + '\n' +
    '  voice     [' + (micOn || clip ? 'CONNECTED' : 'NOT CONNECTED') + ']   ' + (micOn ? 'microphone live' : clip ? 'her voice playing' : 'no audio path from this window') + '\n' +
    '  wire      [' + (daemon ? 'CONNECTED' : 'ABSENT') + ']          ' + (daemon ? 'bridge up' : 'connection not established') + '\n\n' +
    'Text replies use the attached adapter. Connection is not a claim that journal, manifest, memory or speech feeds are present; each pane keeps its own status.';

  /* ------------------------------------------------------------------ storage */
  const KEY = 'elaria.console.v6';
  let data;
  try { data = JSON.parse(localStorage.getItem(KEY)); } catch (e) { data = null; }
  if (!data || !Array.isArray(data.sessions)) data = null;
  if (data) data.prefs = Object.assign({ crt: false, big: 0, sb: true, orb: true }, data.prefs);
  let saveT = 0;
  const save = () => { clearTimeout(saveT); saveT = setTimeout(() => {
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (e) { /* storage blocked */ } }, 250); };
  const cur = () => data.sessions.find((s) => s.id === data.active);

  /* ------------------------------------------------------------------ runtime state */
  let V = null, vizErr = '';
  let state = 'idle', busy = false, forcedOffline = false, micOn = false, simOn = true;
  let daemon = null, clip = null, endClip = null, skip = false, voiceTimer = 0, typeT = 0;
  let pinned = true, demoOn = false, wipeArmed = false, away = null;
  let openSec = null;          // which sidebar section is folded open
  let fullPane = null;         // which pane is full screen
  let liveTR = null, liveAU = null, liveMEM = null;   // real data, once the wire feeds it
  const hist = []; let hi = 0;

  /* ------------------------------------------------------------------ visualizer bridge */
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
  function setState(s) { if (s === state) return; state = s; if (V) V.setState(s); paintState(s); }
  const setLevels = (role, level) => { if (V) V.setLevels(role, { level }); };
  function settle() { if (busy || voiceTimer) return; setState(forcedOffline ? 'offline' : micOn ? 'listening' : 'idle'); }
  function lamps() {
    const on = { console: 'ok', daemon: daemon ? 'ok' : 'wait', voice: (micOn || clip) ? 'ok' : 'wait', wire: daemon ? 'ok' : 'gone' };
    const titles = {
      console: 'console — this local window is running',
      daemon: daemon ? 'daemon — adapter attached' : 'daemon — not connected',
      voice: micOn ? 'microphone input live' : clip ? 'adapter audio attached' : 'voice — no audio path from this window',
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

  /* ------------------------------------------------------------------ miniature orb (2D, shares the palette) */
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

  /* ------------------------------------------------------------------ notifications: the mini orb */
  function notify(o) {
    const text = o.text || '';
    const ms = o.ms || Math.min(9000, 4500 + text.length * 40);
    while (el.toasts.children.length >= 3) closeToast(el.toasts.firstChild);
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
    t.addEventListener('animationend', done, { once: true }); setTimeout(done, 450);
  }
  function pulseVoice(ms) {
    if (busy || forcedOffline) return;
    clearInterval(voiceTimer); setState('speaking');
    const end = performance.now() + ms;
    voiceTimer = setInterval(() => {
      const t = performance.now();
      if (t >= end) { clearInterval(voiceTimer); voiceTimer = 0; settle(); return; }
      setLevels('output', .3 + .5 * Math.abs(Math.sin(t / 110)) * Math.random());
    }, 45);
  }
  const calmWants = () => { el.wants.hidden = true; };

  /* ------------------------------------------------------------------ log rendering */
  const ROLE = { me: 'you', ai: 'elaria', sys: '', note: '', warn: '', err: '' };
  function msgEl(r, text, ts) {
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
  const pushTo = (s, r, t) => { if (s) { s.msgs.push({ r, t, ts: Date.now() }); save(); renderSess(); } };
  function push(r, t) { pushTo(cur(), r, t); }
  function renderLog() {
    el.pad.replaceChildren();
    cur().msgs.forEach((m) => el.pad.append(msgEl(m.r, m.t, m.ts)));
    pinned = true; el.log.scrollTop = el.log.scrollHeight; el.jump.hidden = true;
    $('sname').textContent = '~/sessions/' + cur().name;
  }
  el.log.addEventListener('scroll', () => {
    pinned = el.log.scrollHeight - el.log.scrollTop - el.log.clientHeight < 80;
    el.jump.hidden = pinned;
  });
  el.jump.addEventListener('click', () => { pinned = true; el.log.scrollTop = el.log.scrollHeight; });

  /* ------------------------------------------------------------------ sessions */
  function newSession(name) {
    const s = { id: Date.now().toString(36) + Math.random().toString(36).slice(2, 5),
      name: name || 'session-' + (data.sessions.length + 1), created: Date.now(), msgs: [] };
    data.sessions.push(s); data.active = s.id; save(); return s;
  }
  function renderSess() {
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
    data.active = target.id; save(); renderLog(); renderSess();
    if (cut) {
      const note = '[note] she was mid-sentence in ' + (from ? from.name : 'that session') + ' — you switched, so it stopped. the full reply is stored there, nothing was lost.';
      push('note', note); log('note', note);
    }
    el.ta.focus();
  }
  async function createSession() {
    const cut = busy;
    if (cut) { interrupt(); await sleep(50); }
    const from = cur();
    newSession(); renderLog(); renderSess();
    if (cut) out('[note] she was mid-sentence in ' + (from ? from.name : 'that session') + ' — the full reply is stored there.');
    el.ta.focus();
  }

  /* ------------------------------------------------------------------ sidebar sections + full-screen panes */
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
      b.append(h('p', 'mini', rows ? rows.length + ' rows shown.' : 'No audio manifest rows received. ' + AU_COLS + '.'));
      b.append(h('p', 'mini', CENSUS));
      const mb = h('button', 'sbtn'); mb.type = 'button';
      mb.textContent = micOn ? 'stop microphone' : 'use microphone';
      mb.addEventListener('click', toggleMic); b.append(mb);
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
      const mic = h('button', 'sbtn'); mic.type = 'button'; mic.style.maxWidth = '260px';
      mic.textContent = micOn ? 'stop microphone' : 'use microphone (drives her orb)';
      mic.addEventListener('click', toggleMic); b.append(mic);
      const note = h('p', 'tnote micnote'); b.append(note);
      b.append(h('p', 'tnote', 'the microphone stays in this browser. it drives the orb only — nothing is recorded, uploaded or stored by this shell.'));
    }
    if (q && name !== 'memory') Array.prototype.forEach.call(b.querySelectorAll('tbody tr'), filt);
  }

  /* The mic feedback line lives in two places at once (sidebar fold-out and full-screen pane), so the
     message is written to every copy AFTER the bodies are rebuilt, never before. */
  const renderMic = () => { if (openSec === 'audio') renderSec('audio'); if (fullPane === 'audio') renderFull(); };
  async function toggleMic() {
    const say = (t) => qa('.micnote').forEach((n) => { n.textContent = t; });
    if (micOn) { if (V) V.releaseMicrophone(); micOn = false; lamps(); settle(); renderMic(); say(''); return; }
    if (!V) { say('[ERR] the visualizer is unavailable, so there is nothing to attach a microphone to.'); return; }
    say('asking for the microphone\u2026');
    try {
      await V.useMicrophone(); micOn = true; simOn = false; V.simulate(false); syncOrb(); lamps(); setState('listening');
      renderMic(); say('[OK] microphone live. speak \u2014 the panel on the right is reading you. nothing is recorded or stored.');
    } catch (err) {
      const n = err && err.name;
      renderMic();
      say(n === 'NotAllowedError' || n === 'SecurityError'
        ? '[ERR] blocked. browsers need https or localhost, plus your permission.'
        : n === 'NotFoundError' ? '[ERR] no microphone found.' : '[ERR] ' + ((err && err.message) || 'unknown error'));
    }
  }

  /* ---- orb readout ----
     There are NO state or signal buttons anywhere in the console. Those rows in the visualizer demo
     existed to STIMULATE modes by hand; here every state is supposed to happen in real time — driven
     by the wire, the microphone, or her typing. /state and /sim stay as hidden commands for testing,
     and nothing on screen pretends otherwise. */
  function syncOrb() {
    el.orbnote.textContent = clip ? 'adapter audio attached; playback is not guaranteed'
      : (micOn ? 'microphone input live · text output: ' : '') +
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
    else { setSec(p); if (fullPane) { fullPane = p; el.tbWhich.textContent = p; renderFull(); } }
  }));
  el.bNew.addEventListener('click', createSession);
  el.orb.addEventListener('click', calmWants);
  document.addEventListener('click', (e) => { if (!e.target.closest('.sb, .tools, #full')) calmWants(); });

  /* ------------------------------------------------------------------ commands */
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
    { n: 'panel', u: '/panel NAME|off', d: 'transcript | memory | audio | off', f: (a) => {
      const s = (a || '').toLowerCase();
      if (!PANES.concat('off').includes(s)) return out('panes: transcript, memory, audio, off');
      openPane(s); } },
    { n: 'state', u: '/state NAME', d: 'her orb: idle, listening, thinking, speaking, offline', f: (a) => {
      const s = (a || '').toLowerCase();
      if (!LABEL[s]) return out('states: ' + Object.keys(LABEL).join(', '));
      forcedOffline = s === 'offline'; setState(s); } },
    { n: 'notify', u: '/notify TEXT', d: 'preview the mini-orb notification', f: (a) => notify({ text: a || 'Elaria here. I look like this when I have something to say.', speak: true, log: false }) },
    { n: 'mic', u: '/mic', d: 'attach or release the microphone', f: () => toggleMic() },
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

  /* ------------------------------------------------------------------ conversation */
  // SYNTHESISED TEXT CADENCE, never measured audio. Audio uses attachElement instead.
  const levelFor = (ch) => (/[\s.,;:!?]/.test(ch) ? .06 : .38 + Math.random() * .5);
  let abortType = null;
  function typeInto(body, text) {
    return new Promise((res) => {
      let i = 0; const per = Math.max(1, Math.ceil(text.length / 260));
      const finish = () => {
        clearTimeout(typeT); typeT = 0; abortType = null;
        body.innerHTML = paintHer(text); pin(); res();
      };
      abortType = finish;
      (function tick() {
        i = skip ? text.length : Math.min(text.length, i + per);
        body.textContent = text.slice(0, i);
        setLevels('output', skip ? 0 : levelFor(text[i - 1] || ' '));
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
    if (clip) { try { clip.pause(); } catch (e) { /* already gone */ } }
    if (endClip) endClip();
    if (abortType) abortType();
  }
  function playClip(src) {
    const a = typeof src === 'string' ? new Audio(src) : src;
    if (V) { try { V.attachElement(a); } catch (e) { /* cross-origin audio cannot be analysed */ } }
    clip = a; lamps(); syncOrb();
    return new Promise((r) => {
      endClip = () => { endClip = null; clip = null; lamps(); syncOrb(); r(); };
      a.onended = a.onerror = endClip;
      a.play().catch(endClip);
    });
  }
  async function deliver(rep, owner) {
    const s = owner || cur();                       // bound at send time: an interrupt or a session
    const text = typeof rep === 'string' ? rep : String(rep.text || ''), audio = rep && rep.audio;  // switch must not
    const m = msgEl('ai', ''), body = m.querySelector('.body');                                    // move her reply
    body.classList.add('typing'); el.pad.append(m); pin();                                          // into another session
    el.log.setAttribute('aria-busy', 'true'); setState('speaking');
    const ended = audio ? playClip(audio) : Promise.resolve();
    await typeInto(body, text); await ended;
    body.classList.remove('typing'); el.log.removeAttribute('aria-busy'); skip = false;
    pushTo(s, 'ai', text);
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
      return 'she is on the right in a proportional panel, yielding to chat on narrow screens. the readout names the current state and signal. /mic attaches your microphone and she reacts to your voice instead. /sim turns the synthetic voice off.';
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
    const s = cur();
    pinned = true; el.pad.append(msgEl('me', text)); pushTo(s, 'me', text); pin(); calmWants();
    busy = true; setState('thinking');
    try {
      const t0 = performance.now();
      const rep = daemon ? await daemon.send(text, { session: s.name, history: s.msgs.slice(-20) }) : respond(text);
      const left = 700 - (performance.now() - t0);   // hold "thinking" long enough to read as a state change
      if (left > 0) await sleep(left);
      await deliver(rep, s);
    } catch (err) {
      out('[BROKEN] the daemon call failed: ' + ((err && err.message) || 'unknown error'));
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

  /* ------------------------------------------------------------------ input */
  const autosize = () => { el.ta.style.height = 'auto'; el.ta.style.height = Math.min(el.ta.scrollHeight, 180) + 'px'; };
  let typingT = 0, tab = { base: null, i: -1 };
  el.ta.addEventListener('input', () => {
    autosize(); tab.base = null; calmWants();
    if (busy || forcedOffline || micOn) return;
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
    if (e.ctrlKey && !e.altKey && !['Digit0', 'Digit1', 'Digit2', 'Digit3', 'KeyK', 'KeyB'].includes(e.code)) return;
    const act = {
      KeyN: createSession, KeyK: () => toggleSb(), KeyB: () => toggleOrb(), Digit0: () => setSize(0),
      Digit1: () => openFull('transcript'), Digit2: () => openPane('memory'), Digit3: () => openPane('audio')
    }[e.code];
    if (act) { e.preventDefault(); act(); }
  });
  window.addEventListener('focus', () => {
    document.title = 'Elaria';
    if (away) { notify({ text: away.length > 120 ? away.slice(0, 117) + '\u2026' : away, log: false }); away = null; }
  });

  /* ------------------------------------------------------------------ the wire, prepared
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
        ws.send(JSON.stringify({ t: 'hello', v: WIRE_V, client: 'console', caps: ['text', 'transcript', 'audio', 'memory'] }));
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
        return window.ElariaShell.connect({ name: m.name || 'daemon', send: sendOver });
      }
      if (m.t === 'reply') { const p = pend.get(m.id); pend.delete(m.id); if (p) p(m); return; }
      if (m.t === 'state') return window.ElariaShell.setState(m.name);
      if (m.t === 'levels') return window.ElariaShell.levels(m.role, m.level);
      if (m.t === 'notify') return window.ElariaShell.notify({ text: m.text || '', speak: !!m.speak });
      if (m.t === 'transcript') return window.ElariaShell.transcript(m.rows || []);
      if (m.t === 'audio') return window.ElariaShell.audio(m.rows || []);
      if (m.t === 'memory') return window.ElariaShell.memory(m.cards || []);
      if (m.t === 'bye') { dead = true; try { if (ws) ws.close(); } catch (e) { /* gone */ } window.ElariaShell.disconnect(); }
    }
    function sendOver(text, ctx) {
      return new Promise((res, rej) => {
        if (!ws || ws.readyState !== 1) return rej(new Error('wire not open'));
        const id = ++n;
        pend.set(id, (m) => m.error ? rej(new Error(m.error))
          : res(m.audio ? { text: m.text || '', audio: m.audio } : (m.text || '')));
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
    open();
    return {
      close() { dead = true; try { if (ws) ws.close(); } catch (e) { /* gone */ } window.ElariaShell.disconnect(); },
      get open() { return !!ws && ws.readyState === 1; }
    };
  }

  /* ------------------------------------------------------------------ public integration surface */
  window.ElariaShell = {
    connect(adapter) {
      if (!adapter || typeof adapter.send !== 'function') throw new Error('ElariaShell.connect needs { send(text, ctx) }.');
      daemon = adapter; forcedOffline = false;
      simOn = false; if (V) V.simulate(false); syncOrb();
      lamps(); settle();
      notify({ text: 'Daemon connected' + (adapter.name ? ': ' + adapter.name : '') + '.', log: false });
      out('[OK] wire up. replies use the attached adapter; each pane keeps its own data status.');
    },
    disconnect() {
      if (!daemon) return;
      daemon = null; forcedOffline = true; lamps(); setState('offline'); syncOrb();
      notify({ text: 'Lost the daemon wire. Marked offline until it returns.', log: false });
    },
    notify(o) { notify(o || {}); },
    attachSocket(url) { return attachSocket(url); },
    say(text) { if (!busy) { const s = cur(); busy = true; deliver(text, s).finally(() => { busy = false; settle(); }); } },
    setState(s) { if (LABEL[s]) { forcedOffline = s === 'offline'; setState(s); } },
    levels(role, level) { setLevels(role, level); },
    transcript(rows) { liveTR = nonempty(rows); demoOn = false; syncBadges(); if (openSec === 'transcript') renderSec('transcript'); if (fullPane === 'transcript') renderFull(); },
    audio(rows) { liveAU = nonempty(rows); demoOn = false; syncBadges(); if (openSec === 'audio') renderSec('audio'); if (fullPane === 'audio') renderFull(); },
    memory(cards) { liveMEM = nonempty(cards); syncBadges(); if (openSec === 'memory') renderSec('memory'); if (fullPane === 'memory') renderFull(); },
    get state() { return { daemon: !!daemon, mic: micOn, state, pane: fullPane, section: openSec }; }
  };

  /* ------------------------------------------------------------------ boot */
  function seed() {
    const s = newSession('boot');
    const now = Date.now();
    const B = [
      ['sys',  'elaria console shell v6 — ' + new Date().toLocaleString() + ' — type /help for commands'],
      ['sys',  'lamps   console [ON]   daemon [NOT CONNECTED]   voice [NOT CONNECTED]   wire [ABSENT]'],
      ['note', 'colour key — green her · white you · orange names and numbers · blue system · violet aside · amber not-yet · red broken · ice paths · acid commands'],
      ['note', 'layout — sessions, transcript, memory and audio in the left sidebar. her orb in a proportional panel on the right, yielding on narrow screens. the centre is the chat, always. transcript opens full screen across the chat and the orb; the sidebar stays exactly where it is.'],
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
    renderLog(); renderSess(); lamps(); paintState('idle'); syncBadges(); syncOrb();
    renderSec('transcript'); renderSec('memory'); renderSec('audio');
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
