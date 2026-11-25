# RPT-Z — PreWakeRing audit (2026-11-25, manager-verified)

Question: is pre-hit audio fed, and is it *used*, or buffered and dropped?

## Verdict: fed and used for detection; deliberately NOT inherited as audio

- **Fed.** `daemon._hotword_loop` passes every always-on frame to
  `WakeGuard.feed` (`src/assistant/daemon.py`, `_hotword_loop`), which
  calls `note_frame` → `self.ring.append(frame)`
  (`src/assistant/wake_guard.py`). The handoff-era claim "ring built,
  unfed" is stale.
- **Used.** The keyword model scores a trailing window sliced from
  `ring.snapshot()` (`wake_guard.py`, `feed()`), and at trigger time
  `_wake_clip = ring.snapshot()` captures the pre-hit phrase.
- **Not inherited — by pinned design.** On CONF_HIGH, `_session_head`
  is set to the *pending command window only* (`verify()`), and
  `tests/test_wake_knock_package.py` asserts `session.head == pending`
  byte-for-byte. The wake phrase itself never becomes session audio,
  and the wake clip is never ECAPA-scored (absolute rule). Prepending
  ring audio would break both the pinned test and that rule's spirit.

## What remains genuinely open

Detector latency: the spotter fires after the phrase, so a command
spoken continuously ("Elaria, what time…") can lose its first
fraction. If that ever shows up on hardware, the fix is a *bounded*
ring tail prepended to the session head **after** CONF_HIGH only
(never scored), with the knock-package test amended deliberately —
not a silent change. Not built now: no hardware evidence it bites,
and the owner cannot run voice tests at present.

## Rules honoured

Ring stays RAM-only (`PreWakeRing`, `MADV_DONTDUMP`), zeroed on every
non-attending outcome (`_settle` / `_zero_buffers`), never persisted.
