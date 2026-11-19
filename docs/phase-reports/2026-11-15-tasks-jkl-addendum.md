# Addendum — Tasks J/K/L: the two rulings and the Lua defect (2026-11-15)

Authority: MASTER BUILD PROMPT — ELARIA, BLUEPRINT V2 WIRING SPEC (2026-10-25),
plus the owner rulings of 2026-11-15. This is the ONE addendum report for this
round. Branch `arena/c2a7085d-elaria`; PR #23 stays open and unmerged.

## DONE

| item | commit | what changed | pins | suite |
| --- | --- | --- | --- | --- |
| RULING 1 — F17 unconditional | `d24564f` | an unnamed capture node is refused on EVERY machine, before the session-open earcon, with the same reason either way | 2 new/rewritten K pins (both machine shapes) | 2,121 passed, 6 skipped, 178.98 s |
| RULING 2 — `claim_reply` sole authority | `de7fcd1` | the daemon's local single-claim is deleted (delegated); early dispatch and the late gate both ask the gateway; a taken claim is answered with the fact, never a second generation | `tests/test_task_m_followup.py` (15, shared with the Lua fix) | 2,136 passed, 6 skipped, 179.30 s |
| DEFECT — Lua bind emission | `de7fcd1` | bind snippets are emitted Lua-first from one emitter; legacy only on positive <0.55 detection; the Escape cancel line is in the canonical set | 8 of the 15 in the same file | same run |
| ADDENDUM (this file) | — | the cause paragraphs the standing rule now requires | — | — |

### RULING 1 — what "unconditional" now means

- `AudioGateway.resolve_target` refuses whenever no node is configured, with
  `refusal="policy"`, **independent of whether `pw-record` exists**. The old
  device-conditional branch is gone, and the pin compares the two machine
  shapes' reasons for string equality — they cannot drift apart again.
- The refusal still lands **before the earcon**, so a refused session never
  beeps as if it had started. Both shapes are pinned end to end through the
  socket: `listening: false`, no device constructed, no `_ack` called, gateway
  back to `idle`, `_capture_source is None`.
- Consequence, stated plainly: a fresh install with no `[capture] mic_target`
  cannot capture at all until the owner names the node. That is the ruling, and
  the surfaces now say so — `config.toml.example` marks the key REQUIRED for
  capture, and doctor reports the refusal instead of a measurement.
- Doctor changes that follow from the ruling (both in the same commit):
  - the "mic level" probe is **skipped** when no node is configured, and the
    refusal is reported — probing the default source would be the same
    wrong-mic habit wearing a diagnostic costume;
  - "capture node (Mic1)" now FAILS on an empty node. It used to pass whenever
    a default-source probe returned bytes, which is exactly the habit the
    ruling kills.
- Fixture change: `tests/conftest.py` gives the test daemon a named node
  (`test-mic`), because a fixture that expects to capture now describes a
  machine whose node is named — the owner's laptop. Tests that assert the
  refusal clear both nodes explicitly.

### RULING 2 — the shadow gate is gone, not mirrored

- `_early_dispatch_reply` asks `AudioGateway.claim_reply(session_id)` and the
  local `sid in self._early_reply_tasks` membership gate is **deleted**. A
  refused dispatch journals `dictate.reply_refused_duplicate`.
- `_claim_early_reply` is now purely a task handover (pop): the permission was
  decided at dispatch, and popping is what makes the late gate reuse the same
  task rather than starting a second reply.
- The late gate's fresh-reply branch claims too. When the claim is taken it
  does not generate: it answers with the fact (`reply: None`, `suppressed`,
  "one utterance, one reply (F28) — the earlier reply for this session stands")
  and journals the refusal. The wait on a reply task is skipped when there is
  none, so no path can hang on a reply that will never exist.
- Pinned for both shapes: the LIVE shape end to end (one utterance → exactly
  one `_ask`, with the gateway ledger keyed by that session id) and the taken-
  claim shape (zero `_ask` calls, the refusal sentence in the result, the
  reason naming the rule).

### DEFECT — the installer's bind line could not run on the owner's machine

The line I issued in the previous report was legacy Hyprland syntax
(`bind = , Escape, exec, assist ptt cancel`). On the owner's Hyprland 0.57 the
legacy format no longer exists — that line would have been silently ignored.
It was in my own hands and I wrote the dead dialect; the design chat caught it,
not me.

- New `src/assistant/hypr_binds.py`: one bind set (`BINDS`), one emitter
  (`emit_binds`), one detector (`detect`). **Lua-first**: absent `hyprctl`, an
  unreadable version, or anything not positively older than 0.55 emits Lua.
  Legacy is emitted only on a positive pre-0.55 detection, because the dead
  dialect must never be the accidental default.
- The Escape cancel line
  (`hl.bind("Escape", hl.dsp.exec_cmd("assist ptt cancel"))`) is part of the
  canonical set, so it cannot be forgotten again.
- `ui/hyprland/elaria-binds.lua|.conf` are generated from the emitter and are
  pinned byte-for-byte against it — documentation cannot drift from what the
  installer hands the owner. Both carry the cancel bind.
- `cli.hyprland_info` delegates to `hypr_binds.detect` and returns the exact
  `emit` text for the detected syntax; doctor's bind check now requires the
  cancel bind and points at the emitted snippet for the right syntax.
- GETTING-STARTED Step 6 and `ui/README.md` are Lua-first, state 0.57, document
  Escape, and keep `.conf` only for a positively-detected older compositor.
- `tests/test_bughunt_k_doctor_drift.py`'s "present binds" fixture gained the
  cancel bind: the canonical set grew, so a deployment without it is not
  complete.
- **No owner installer run has happened**, so nothing here is a hardware claim;
  what is pinned is the emitted text and the detection rule.

### Standing rule — cause paragraphs for overruns past 2x

The previous report (`4d42c55`) does **not** contain a cause paragraph for J;
its table states the overrun and the sentence "every estimate was low", which
is a disclosure, not a cause. So the rule is applied here for J and L. K is
1.84x and under the threshold.

Measurement basis, stated so the numbers are comparable: "delivered" is
`git show --stat` insertions including the pins and the docs those tasks
required; the original estimates were for implementation plus pins.

**J — EARS, 1,224 lines vs ~330 estimated (3.7x), 20 pins vs 12 (1.7x).**
Cause: the estimate was made for the ASR path alone, and J turned out to cross
four layers — capture gating (`FrameGate` reuse), the ASR chain and its
escalation leg, the dictation service's session/provenance records, and daemon
IPC for cancel. Four specific pieces were not in the estimate at all:
(a) local-first needed a measured tier decision plus a provenance record per
leg (backend, model, latency, rtf, confidence, chars, sha16) on every
transcript; (b) the escalation leg had to be rebuilt to go through the existing
`transcribe_file` chain after the first version desynced from it — roughly 60
lines rewritten mid-task after a live-socket pin caught it; (c) J4's cancel
crossed the daemon's IPC-handler-integrity pin, which required a keyword-only
opt-out and two order-sensitive pin repairs; (d) J5's limiter was estimated as
a curve but also owes both peaks and an xrun counter to doctor forever, which is
measurement plumbing, not a curve. Eight of the twenty pins exist because every
refusal shape (quota, offline, unknown confidence, total ASR failure, pin
mismatch, tier latency) needed its own fake — refusing honestly costs a pin
each time.

**L — MOUTH, 494 lines vs ~230 estimated (2.1x), 12 pins vs 9 (1.3x).**
Cause: the estimate treated F33 as "put a settings hash in the key". The
existing VB-2 pin (a dormant local-path setting must not invalidate a Flare
render) forced the hash to be **per route**, which is both more code and a
correction that only surfaced when the full suite rejected the blanket version —
so the real work included discovering the constraint. Three further pieces were
outside the estimate: the cap needed a declared config surface
(`[tts] cache_max_files` in DEFAULTS *and* the example config) plus the
indexer's permanent exclusion, because "regenerable" has to be true structurally
and not only in prose; the labelled fallback had to be threaded through three
failure origins (backend, route, player) rather than one return site; and F21's
"consent is never voiced" needed the guard *plus* explicit `spoken: false`
declarations in both undo handlers *plus* a source-level pin, because a rule
that is only true by absence is a rule nobody can prove. The three extra pins
are the unit/wiring pair each claim needed (key, cap, label, consent).

### History integrity

A sandbox reset left the local repository at the base commit while the working
tree carried the accepted tasks. One commit was made on that stale history
(`f6fec38`) and immediately superseded with `git reset --mixed origin/…` before
anything was pushed. The pushed history is linear and contains only real work:

`7d0d3ca` (J) → `b38b1b1` (K) → `b1897ff` (L) → `4d42c55` (report) →
`d24564f` (ruling 1) → `de7fcd1` (ruling 2 + Lua) → this addendum.

### Suite wall-time trend (F36)

| stage | result | wall |
| --- | --- | --- |
| J final | 2,092 passed, 6 skipped | 184.98 s |
| K final | 2,108 passed, 6 skipped | 188.54 s |
| L final | 2,120 passed, 6 skipped | 183.67 s |
| RULING 1 | 2,121 passed, 6 skipped | 178.98 s |
| RULING 2 + Lua | 2,136 passed, 6 skipped | 179.30 s |

Recorded dependency set, local runner; `ruff check .` clean at every commit.

### Owner lines (restated — the only audio acceptance there is)

1. **Binds, Lua first.** Append the emitted Lua snippet (aliases: the same text
   is in `ui/hyprland/elaria-binds.lua`, and `assist doctor` prints the `emit`
   field for your detected syntax). Canonical set: `SUPER + grave` start,
   `SUPER + grave` release-stop (`release = true, ignore_mods = true`),
   `Escape` → `assist ptt cancel`, `SUPER + SHIFT + F12` → `assist halt`.
   **This is the corrected installer's single config touch**; the previous
   legacy line must not be used.
2. **J — one dictation.** `assist doctor` shows `capture levels: raw peak X ·
   processed peak Y · limited samples N · xruns/dropouts M · node <name>`;
   the transcript reports `backend=local` at tier `base` with a full
   transcript, or a correctly labelled escalation; Escape mid-utterance reports
   `zeroized: true` (or says why not) and the node is released.
3. **K — one PTT and one spoken reply.** `assist status` shows
   `gateway.state` moving `ptt → idle`, `playbacks` returning to zero, and a
   press during a live session refused with its arbitration reason.
4. **L — one spoken reply.** Spoken once, then again from cache
   (`cached: true`); with the network cut the same reply arrives as labelled
   text (`speech_status: text-only`) and nothing is claimed as spoken.
5. **F17 check on the laptop.** `assist doctor` now says `mic_target='…'`
   when the node is named; clear it and PTT must refuse before any earcon
   rather than falling back to the default device.

**Pending on owner hardware, unchanged:** K's audible playback, L's audible
reply, J's single dictation run, and the corrected bind install. Nothing in this
round is an audio claim.

## DEFECTS FOUND

1. **The installer bind line shipped in legacy syntax for a Lua-only
   compositor** (found by the design chat, not by me — it was my own line in
   `4d42c55`). Fixed in `de7fcd1`; the general lesson is recorded in
   `hypr_binds.py`: a format the compositor cannot read must never be the
   default, so emission is Lua unless an old compositor is positively detected.
2. **Doctor passed "capture node (Mic1)" on an empty node whenever a
   default-source probe returned bytes.** Found while implementing ruling 1;
   fixed in the same commit (the probe is now skipped and the check fails on an
   empty node). This is the diagnostic form of the same wrong-mic habit the
   ruling kills.
3. **The canonical bind set had no cancel line at all** — not in the shipped
   snippets, not in GETTING-STARTED Step 6, not in doctor's required markers.
   Task K shipped the command and the report issued a line by hand; the set
   itself was incomplete. Fixed: the emitter owns the set, the snippets are
   generated and pinned, and doctor requires it.
4. **A single stale claim could have hung the late gate.** With the write order
   "claim, then create the task", a refused claim leaves no task to await; the
   first draft of the wiring would have awaited `None`. Fixed by skipping the
   wait when there is no reply and answering with the refusal sentence; caught
   during the rewrite, before any test run.
5. **Unchanged from `4d42c55` and still open** (out of scope again): the three
   capture paths outside the gateway (hotword, `event.py`, meeting dual), the
   protected `live_client.py` stream, and F16 streaming playback remaining
   deferred and unpromised.

## NEXT GATE

1. **Owner hardware acceptance**, in this order: (a) install the corrected Lua
   binds and confirm `assist doctor` reports the binds ok with the cancel line;
   (b) one PTT + one spoken reply (K); (c) one dictation with the limiter and
   peaks line (J); (d) one spoken reply plus the offline labelled-text check
   (L).
2. **F17 negative check on the laptop** (owner line 5): clear `mic_target`,
   confirm the refusal with no earcon, restore the node. This is the rule that
   just changed; it deserves one deliberate negative run.
3. **PR #23 merge hold unchanged**: still waiting on the owner's clean-audio S1
   (`backend=gemini_batch`). Nothing from this round is merged.

## OPEN QUESTIONS

1. **Does the unconditional F17 refusal need a first-run affordance?** Today a
   fresh install refuses capture until `mic_target` is set, and the refusal
   names the fix. Should `assist doctor` (or the installer) offer to write the
   node it measures, or stay strictly read-only and let the owner paste it?
   Read-only is the current behaviour.
2. **`claim_reply`'s ledger is in-memory** (bounded to 256 ids, oldest-first).
   A daemon restart mid-utterance forgets claims; a restart also ends the
   session, so no live double-reply is possible — but if reply claims should
   survive a restart for the live client's sake, that is a small, quotable
   change (journal-backed or store-backed).
3. **Should the emitter also own a `bind` installer** (writing the lines into
   the owner's config with a marker block), or stay an emitter plus doctor
   report? Writing into a compositor config is a mutating action and needs its
   own grant; today the owner pastes what doctor prints.
4. **The three capture paths still outside the gateway** (hotword, event,
   meeting dual) and the protected live stream — unchanged, still needing a
   grant and (for meeting) a design line about per-source ownership.
