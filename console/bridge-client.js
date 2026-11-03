/* Additive localhost consumer bootstrap. No engine access, model client or API key.
   All levels are SYNTHESISED TEXT CADENCE, not measured audio. Only public shell API. */
(() => {
  'use strict';
  const frame = document.getElementById('console');
  const label = document.getElementById('wire-status');
  let wire = null, timer = null;
  // URL fragment is printed only to the owner's terminal; it is NOT in public HTML.
  const token = new URLSearchParams(location.hash.slice(1)).get('pair');
  if (!token || !/^[A-Za-z0-9_-]{43}$/.test(token)) {
    label.textContent = 'LOCKED — open the private pairing URL printed by the launcher.';
    return;
  }
  function attach() {
    if (wire) wire.close();
    if (timer) clearInterval(timer);
    if (location.protocol !== 'http:' || location.hostname !== '127.0.0.1') {
      label.textContent = 'REFUSED: use the launcher’s 127.0.0.1 URL.';
      return;
    }
    const shell = frame.contentWindow.ElariaShell;
    if (!shell) { label.textContent = 'BROKEN: console public API did not load.'; return; }
    // Pairing token is generated locally for this bridge process; never a model API key.
    shell.setState('offline');  // no standalone stub while the live bridge is connecting
    wire = shell.attachSocket('ws://' + location.host + '/elaria?token=' + encodeURIComponent(token));
    timer = setInterval(() => {
      const state = shell.state;
      label.textContent = !state.daemon || state.state === 'offline'
        ? 'OFFLINE / NOT LIVE-READY — daemon unavailable, offline or not in live mode. No stub answers.'
        : 'TEXT WIRE CONNECTED — ' + state.state + ' · non-model outcomes are explicitly labelled';
    }, 200);
  }
  frame.addEventListener('load', attach);
  // Authenticated asset URL; public pages never disclose the shell's memory cards or token.
  frame.src = '/console?token=' + encodeURIComponent(token);
  window.addEventListener('pagehide', () => {
    if (timer) clearInterval(timer);
    if (wire) wire.close();
  });
})();
