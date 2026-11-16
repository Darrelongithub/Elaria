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
