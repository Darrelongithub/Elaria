/* Localhost bootstrap: only the public shell API; no engine access or model key. */
(() => {
  'use strict';
  const frame = document.getElementById('console');
  const error = document.getElementById('wire-error');
  let wire = null;
  const fail = (text) => { error.textContent = text; error.hidden = false; };
  // Private per-launch fragment; never embedded in public HTML or logged here.
  const token = new URLSearchParams(location.hash.slice(1)).get('pair');
  if (!token || !/^[A-Za-z0-9_-]{43}$/.test(token)) {
    fail('LOCKED — open the current private launch link from the launcher.');
    return;
  }
  function attach() {
    if (wire) wire.close();
    if (location.protocol !== 'http:' || location.hostname !== '127.0.0.1') {
      fail('REFUSED: use the launcher’s 127.0.0.1 link.');
      return;
    }
    const shell = frame.contentWindow.ElariaShell;
    if (!shell) {
      fail('Console did not load. An expired link cannot reopen it; use the current launch link.');
      return;
    }
    error.hidden = true;
    // Connection health lives in the shell lamps, not a permanent wrapper banner.
    shell.setState('offline');
    wire = shell.attachSocket('ws://' + location.host + '/elaria?token=' + encodeURIComponent(token));
  }
  frame.addEventListener('load', attach);
  frame.src = '/console?token=' + encodeURIComponent(token);
  window.addEventListener('pagehide', () => { if (wire) wire.close(); });
})();
