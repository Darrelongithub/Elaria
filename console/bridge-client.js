/* Wire adapter. It never renders draft data, starts audio, or interprets text as commands. */
(() => {
  'use strict';
  const STATES = ['idle', 'listening', 'thinking', 'speaking', 'error', 'offline',
    'pending-draft', 'phone-connected'];
  const CAPTURE_STATES = ['armed', 'open', 'muted', 'stalled', 'released', 'unavailable', 'verifying'];
  const RESOLVED = ['approved', 'rejected', 'expired', 'sent'];
  const same = (left, right) => left && Object.keys(right).every(key => left[key] === right[key]);
  const keys = (value, expected) => value && typeof value === 'object'
    && Object.keys(value).length === expected.length
    && expected.every(key => Object.hasOwn(value, key));
  const text = (value, limit, empty = false) => typeof value === 'string'
    && (empty || value.trim().length > 0) && new TextEncoder().encode(value).length <= limit;

  function draftEvent(frame) {
    const pending = frame.event === 'draft.pending';
    const draft = frame.draft;
    const limits = pending
      ? {draft_id: 128, conversation_id: 128, recipient: 512, snippet: 8192, created_at: 128}
      : {draft_id: 128, outcome: 8192};
    if (!keys(frame, ['event', 'draft']) || !keys(draft, ['state', ...Object.keys(limits)])
        || !(pending ? draft.state === 'pending' : RESOLVED.includes(draft.state))
        || Object.entries(limits).some(([key, max]) => !text(draft[key], max,
          key === 'outcome' || key === 'snippet'))) throw new Error('Invalid draft event');
    return Object.freeze({...draft});
  }

  function createConsumer(consume) {
    const drafts = new Map();
    const currentPending = new Set();
    let ready = false;
    function receive(frame) {
      if (frame.t === 'hello-ok') {
        if (frame.v !== 1 || frame.simulate !== false) throw new Error('Invalid console handshake');
        ready = true;
      }
      if (frame.t === 'state' && !STATES.includes(frame.name)) throw new Error('Unknown console state');
      if (frame.t === 'capture-state' && !CAPTURE_STATES.includes(frame.name)) throw new Error('Unknown capture state');
      if (frame.t === 'capture-state' && frame.reason !== undefined && typeof frame.reason !== 'string') throw new Error('Invalid capture state reason');
      if (frame.t === 'capture-state' && frame.reason !== undefined && frame.reason.length > 256) throw new Error('Invalid capture state reason');
      if (frame.t === 'levels' && !(frame.role === 'input' && frame.measured === true
          && frame.source === 'capture.levels' && frame.level === frame.processed_peak
          && [frame.raw_peak, frame.processed_peak].every(n => typeof n === 'number' && n >= 0 && n <= 1)
          && Number.isSafeInteger(frame.limited_samples) && frame.limited_samples >= 0)) {
        throw new Error('Expected measured capture levels');
      }
      if (frame.event === 'draft.pending' || frame.event === 'draft.resolved') {
        if (!ready) throw new Error('Draft event before handshake');
        const draft = draftEvent(frame);
        const previous = drafts.get(draft.draft_id);
        if (previous && previous.state !== 'pending'
            && !(previous.state === 'approved' && draft.state === 'sent')
            && previous.state !== draft.state) return false;
        if (!previous && drafts.size >= 10000) throw new Error('Draft projection limit reached');
        if (draft.state === 'pending') currentPending.add(draft.draft_id);
        else currentPending.delete(draft.draft_id);
        if (same(previous, draft)) return false;
        drafts.set(draft.draft_id, draft);
        consume(Object.freeze({event: frame.event, draft}));
        return false; // not a legacy t-frame
      }
      return true; // validated state and measured levels are routed by the shell
    }
    function command(verb, draftId, send) {
      if (!ready || !['draft.approve', 'draft.reject'].includes(verb)
          || !currentPending.has(draftId)) throw new Error('Draft decision unavailable');
      send(JSON.stringify({command: verb, draft_id: draftId}));
    }
    return {receive, command, disconnect() { ready = false; currentPending.clear(); }};
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {createConsumer};
    return;
  }
  const frame = document.getElementById('console');
  const error = document.getElementById('wire-error');
  const fail = (text) => { frame.hidden = true; error.textContent = text; error.hidden = false; };
  if (location.protocol !== 'http:' || location.hostname !== '127.0.0.1') {
    fail('REFUSED: use the launcher’s 127.0.0.1 link.');
    return;
  }
  const token = new URLSearchParams(location.hash.slice(1)).get('pair');
  if (!token || !/^[A-Za-z0-9_-]{43}$/.test(token)) {
    fail('LOCKED — open the current private launch link from the launcher.');
    return;
  }
  window.history.replaceState(null, '', '/'); // keep the capability out of the wrapper address bar
  let wire = null;
  frame.hidden = true;
  frame.addEventListener('load', () => {
    if (wire) wire.close();
    try {
      const shell = frame.contentWindow.ElariaShell;
      // K must explicitly opt into the validated, non-simulated contract. Older payloads
      // silently ignored unknown states and could animate from synthetic sources.
      if (typeof shell?.configureTransport !== 'function' || typeof shell?.onDraftEvent !== 'function'
          || shell.configureTransport({simulate: false}) !== true) {
        fail('Console shell does not support the non-simulated wire contract.');
        return;
      }
      const consumer = createConsumer(event => shell.onDraftEvent(event));
      shell.setState('offline');
      wire = shell.attachSocket('ws://' + location.host + '/elaria?token=' + encodeURIComponent(token),
        {onFrame: consumer.receive, onDisconnect: consumer.disconnect, sendDraft: consumer.command});
      frame.hidden = false;
      error.hidden = true;
    } catch {
      fail('Console could not start the local wire.');
    }
  });
  frame.src = '/console?token=' + encodeURIComponent(token);
  window.addEventListener('pagehide', () => { if (wire) wire.close(); });
})();
