# Scene cards — scene-7 follow-ups (2026-10-31, for design-chat scheduling)

The work order is explicit: W3/W4/W5 are owner-scene proofs — scheduled
here as scene cards, never self-certified. W1/W2 are owner-run probes
with paste-safe outputs; their run instructions ride along. Every card
is ≤30 min daylight; both outcomes are decisions.

## SC-W3 — local ASR on Python 3.14.8 (proof of the named degradation)

**Code under proof:** W3 guard (`LocalAsrDegraded`, `local_asr.degraded`
schema line, doctor view). **Runtime:** owner laptop, Fedora 44 /
Python 3.14.8.

TERMINAL steps only (no physical action):

1. On branch code: `uv run python scripts/file_leg_probe.py --no-raw
   --wav /path/to/one/kept.wav` will exercise the remote leg; for the
   LOCAL leg run any local-ASR attempt that produced the 13:56/14:07
   journals (same command as the failing runs).
2. Grep the journal for `local_asr.degraded`.
3. Expected outcomes (both are results):
   - **transcribes** — the local leg works on 3.14.8 (the resolution
     fixed itself; note which `av` is installed).
   - **named degradation** — a plain-language `local ASR degraded: …`
     line naming `av_file=`/`av_version=`/`open_params=`, a
     `local_asr.degraded` schema line, and NO traceback. The printed
     diagnostic IS the dependency report for the fix.
4. Paste the doctor line (`assist doctor` local-ASR section) + the
   grep output back.

## SC-W4 — double-stop in BOTH release directions (Hyprland 0.57)

See `docs/dossiers/2026-10-31-hyprland-057-release-binds.md` (scene
card SC-W4 at the bottom). Direction A (F2 first) and Direction B
(WIN lifted before/with F2); expect one stop + one stop.noop per
direction after the WP3 fix; an eaten stop in Direction B confirms the
defect and cements the WP3 jump.

## SC-W5 — ready-earcon acceptance (WP1, after the cue is built)

**W5 addendum ruling (design chat, 2026-10-31):** the always-active mic
is RULED OUT as a latency measure (makes the 14:02 hot-mic class
permanent, falsifies the `capture.node_state` suspended-after-close
privacy proof, desensitizes the mic-in-use indicator, contradicts
settled hold-to-talk). WP1 scope instead: (i) READY-EARCON — a distinct
second cue fired at first audio frame (warm-up measured
1417.6/1346.5/1818.8/1607.4 ms); (ii) PRE-ROLL DISCARD — frames before
first-frame dropped by construction. Always-on listening remains
exclusively a WP4 wake-word-mode property.

Card (runs once WP1 builds the cue — EARS steps separated from
TERMINAL steps):

1. EARS ONLY: press and hold; hear the session-open cue, then the
   ready-earcon at first frame. The two cues must be distinguishable by
   ear. Speak on the blip.
2. TERMINAL: grep `capture.lifecycle` — `first_frame_latency_ms` and
   the cue's audible time must agree within 50 ms (acceptance from the
   ruling: ready-earcon audible within 50 ms of first frame).
3. EARS ONLY: confirm the first spoken words transcribe (no swallowed
   onset).

## W1 probe run (owner runtime, paste-safe)

`uv run python scripts/file_leg_probe.py` (GEMINI_API_KEY exported; the
key is never printed). Replays `20261031-145603-94129e.wav` and
`20261027-064450-77cc4e.wav` through the production file leg and one
raw SDK pass; prints wav header facts, the exact prompt, raw model text
+ char count, finish_reason, and usage_metadata. Paste the whole
output. The finish_reason reading names the stump (MAX_TOKENS →
truncation; STOP with a stump → the model heard a stump).

## W2 arms (owner runtime)

- `uv run python scripts/live_repro.py --arm A` — transcribe-live pin,
  Manual-VAD verbatim. Expect SPOKE or SILENT per the summary verdict.
- `uv run python scripts/live_repro.py --arm B` — `gemini-3.8-live`
  side-channel, the conversational docs shape. Expect `ARM B VERDICT:
  SPOKE` or `ARM B VERDICT: SILENT` (both are results; NO-RUN only if
  the door slams again).
- Paste both summaries + any MSG dumps. The ruling tree lives in the
  script docstring.
