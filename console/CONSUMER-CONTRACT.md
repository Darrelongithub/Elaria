# Console consumer contract — H / F29 and landed receipts

## One mouth

**F29: the daemon gateway is the sole playback owner.** The bridge omits producer reply
`audio`; the wire adapter discards it; direct-adapter rendering never reads it, including
an audio getter or existing media element. The shell contains no Audio constructor, play
call or attachElement call. The maker engine remains byte-identical, including its unused
APIs. Nothing in this change asks the daemon to speak: console.say still sends speak=false
and history_limit=1. It does not certify that daemon speech is working.

Speaking is entered only through valid positive output levels. A state:speaking frame,
reply, or audio field alone cannot enter it. Wire mode uses the wire levels; standalone
preview uses labelled synthetic typewriter/notification cadence. Zero output levels leave
speaking. Labels still say synthesised text cadence, not measured audio, text-only/no speech.
Microphone input is not reply playback. Audio manifest work remains deferred; the existing
sample/metadata pane renderer is not a production feed or a partially installed player.

Pins: `tests/test_console_audio_owner.py`, `console/audio-owner-test.js`. Synthetic tests
exercise actual DOM rendering, direct adapter element/getter rejection, wire audio URL
rejection, levels-only speaking and pending audio status. They are not ear/hardware tests.

## Receipts are data, not guessed prose

Producer contract inspected from immutable **4218ef02be7627e787a2a5fe457ae553b80381ae**
(implementation 7b374d1), without merging or editing producer files. The consumer now shows:

- Causal assistant/user message IDs returned from the actual appends. Null/invalid IDs stay
  absent; they are not replaced by a sampled history tail. Legacy producer replies without
  these fields retain explicitly noncausal tail reporting.
- Remember: fact ID, kind, source, confidence, active-row readback, until_forgotten retention,
  row_preserved_no_api restore declaration. No stored fact text is copied into attribution.
- Forget: affected count and IDs, actual inactive/still-active/unknown readback states,
  corr_id + corr_ts decision identity, zero-match honestly, and declared absence of versions
  and a durable receipts table. Deactivation is not erasure.

Only bounded validated metadata from local-intent replies is displayed. Withheld/mock/model
results cannot masquerade as fact receipts. A missing/malformed receipt reports the actual
reply's gap, not an obsolete claim that mainline lacks the seam. General operation journal
IDs, indexed structured references and organise root/write receipts are still not invented.

The display accepts at most 1,000 affected facts, shows the first eight IDs, and explicitly
counts the remainder omitted. These are daemon-reported readbacks, not independent effect
verification, permission or durable logs. Unknown receipt fields are not rendered.
`tests/test_console_producer_receipts.py` covers current/legacy/malformed/withheld/wire
cases and executes the unchanged immutable producer methods against synthetic storage.
No live mainline/backend wiring is claimed by those method tests.

## Release boundary

H is a new consumer payload. G deliberately still targets **25ef8e6**, not H. Neither H's
mouth changes nor these new receipt displays are claimed installed by G's pinned launcher.
Do not silently repin G to H. The current-branch launch checksum is in BRIDGE.md; the
owner-authorised native deployment checksum and install command are in NATIVE-DEPLOYMENT.md.

Local H gate: **2698 passed, 9 skipped**, 141.66 seconds; Ruff **0.17.2** green.
The WebKitGTK probe remains an explicit skip without system GI/runtime/display. All
protected producer files, history_limit and the maker engine are unchanged. NectarLink is
out; no additional daemon, model call, audio backend or window orchestration was added.

## Subsequent Task I placement

F34 moves the retained reply-attribution metadata into the sessions sidebar, alongside
bounded hands ACTION/OBSERVATION/DENIAL summaries and silent private consent cards.
No attribution block remains in centre chat. Task I's separately quoted eight-line daemon
call-out is the only new protected-file edit; the protected-byte statement above describes H.
See `docs/hands-headless.md` and the combined final report for the later gate results.

## Wave 1 — IF-2 and IF-4 transport (current; supersedes legacy wire cadence above)

This branch changes only L's transport. E owns draft production and the effect; K owns
rendering and the orb; Z owns the shared gate and daemon endpoints. External contracts
remain unchanged. A paired loopback WebSocket uses v1 hello, with the bridge returning
`simulate: false`. There is no browser player, capture, synthesized input or output level,
or fallback reply. `console.say` keeps `speak: false` and `history_limit: 1`. Any returned
reply `audio` is dropped. A producer `speaking` state must correspond to actual daemon
player start/end, not a chat reply. K should render authoritative spoken text when the
producer supplies it; the bridge cannot infer it from intended text.

| Frame from bridge | Shape / behavior |
|---|---|
| Pending draft | `{"event":"draft.pending","draft":{"draft_id":"…","conversation_id":"…","recipient":"…","snippet":"…","state":"pending","created_at":"…"}}` |
| Resolved draft | `{"event":"draft.resolved","draft":{"draft_id":"…","state":"approved\|rejected\|expired\|sent","outcome":"…"}}` |
| State | `{"t":"state","name":"…"}`, one of `idle`, `listening`, `thinking`, `speaking`, `error`, `offline`, `pending-draft`, `phone-connected`. Unknown state throws; no fallback mapping. |
| Levels | `{"t":"levels","role":"input","level":0.35,"source":"capture.levels","measured":true,"raw_peak":0.8,"processed_peak":0.35,"limited_samples":2}`. Input only. Capture format/threshold semantics owned by A/F/Z. |
| Capture state | `{"t":"capture-state","name":"…"}` (optionally with `reason`), where name is one of `open`, `armed`, `muted`, `stalled`, `released`, `unavailable`, `verifying`. reason is at most 256 UTF-8 bytes, non-empty trimmed text. The shell reads the mic from this frame — never from a browser-side microphone flag. Silence means no signal is known yet, never "listening". Unknown names throw. |

**IF-4 rename (owner decision 2026-11-22):** the IF-4 set was originally
`idle | listening | armed | verifying | suspended | unavailable`. It was renamed at the
wire to the daemon's own states — `open`, `armed`, `muted`, `stalled`, `released`,
`unavailable` (+ `verifying`, reserved) — because those names ARE the daemon's pipeline,
not a mapping onto invented vocabulary. `open` = a session is capturing, `armed` = the
wake path is armed, `muted` = the half-duplex gate holds the mic while she speaks,
`stalled` = no frames within the budget, `released` = the pipeline is closed, `unavailable`
= capture cannot open or the speech path is dead (never a calm idle face). `verifying` is
accepted by the bridge and the shell but emitted by no producer yet — the wake lane will
use it; its reservation avoids a breaking wire change later. The shell maps `unavailable`
to a red voice lamp, not amber. |
| Draft command receipt | `{"t":"draft-command-result","draft_id":"…","status":"accepted\|refused\|unknown"}`. A receipt is not evidence of an effect. Only `draft.resolved` changes the draft's resolution. |

Only the exact event fields above are forwarded. Draft IDs and conversation/time fields
are bounded to 128 UTF-8 bytes, recipient to 512 bytes, snippet and outcome to 8192 bytes.
Only snippet/outcome may be empty. The full recipient is available for owner review.
Snippet and outcome are opaque, untrusted **text**, never markup, instructions or command
arguments. The shell upserts by `draft_id`; replays and identical events do not add cards.
Once resolved, late pending does not revive the card; `sent` can supersede `approved`.

The shell explicitly sends `{"command":"draft.approve","draft_id":"…"}` or
`{"command":"draft.reject","draft_id":"…"}` on the same authenticated socket after a
review action; the client doesn't retry decisions on disconnect. A disconnect disables
commands until a new handshake and replayed/current pending event. No daemon gate means no
approve path. A lost command response is uncertain and the bridge refuses further commands
until reconciled; it never guesses success or issues a send itself.

### HR-L-1: proposed owner IPC seam, pending Z integration and E/K review

- Extend the existing `events.subscribe` over the owner's `0600` Unix socket with
  `{console_replay:true}`. Reply with the normal IPC response containing
  `{subscribed:true,console_replay:true}` **before** sending event lines. The replay flag
  attests that the daemon can replay retained relevant draft events in forward order and
  hand off to live events without gaps, including terminal outcomes for drafts whose
  pending events can appear in replay. A legacy ack without the replay flag disables
  drafts and their commands. L does not add a second wire, durable queue, or database.
- Proposed IF-4 producer frames on that same subscriber stream:
  `{event:"console.state",state:"…"}`,
  `{event:"capture.levels",raw_peak:n,processed_peak:n,limited_samples:n}` and
  `{event:"capture.state",state:"open|armed|muted|stalled|released|unavailable|verifying"[,reason:"…"]}`. Peaks are
  finite normalized numbers in [0,1]; limited samples is a nonnegative safe integer.
  Legacy unrelated subscription frames are ignored, not passed through to the browser.
- Proposed `console.command` receives the exact IF-2 envelope at the shared consent/journal
  gate. `accepted:true` acknowledges dispatch through the gate, not a sent SMS. A normal
  IPC `ok:false` is the gate's definitive refusal. An unconfirmed dispatched outcome
  must not be presented as refused or automatically retried. SMS, draft mutation, and
  consent policy stay with their owners. Production end-to-end delivery relies on Z/E's
  retained replay and is not established by the bridge fixture alone.

### K handoff (the legacy pinned payload will not connect via this bootstrap)

K should boot wired mode with simulation off before the visualizer starts, without local
mic capture, synthetic typing/preview signals, or `/sim` in wired mode. Implement
`ElariaShell.configureTransport({simulate:false})` (return `true` only once this is enforced)
and `ElariaShell.onDraftEvent(event)` (text-only render or remove/upsert a review card).
Extend `attachSocket(url, opts)` so it calls `opts.onFrame(parsed)` before legacy routing,
consumes `false` as handled, and fails closed on throws; call `opts.onDisconnect()` on loss
and explicit close. For an explicit review action, use `opts.sendDraft(verb,draftId,send)`
with a callback bound to the current open socket, never an automatic retry. Route
`draft-command-result` as status only; close/disable pending decision UI on disconnect.
Recognize the validated IF-4 state/level frames without synthetic fallback. A reviewed K
release will need a coordinated update of the launcher `index.html` pin; L did not alter
K's maker engine, JS, HTML, CSS, or its generated artifact.
