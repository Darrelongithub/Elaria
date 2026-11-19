# Scene-3b triage — three streams — phase report

Date: 2026-10-26 · Branch: `arena/c2a7085d-elaria` · PR #23.
Gate RESTATED (unchanged, still red): a NATURAL Win+F2 hold-speak-release
cycle must produce earcon at press, session close at release, final
transcript, spoken reply, and schema lines for each. WP1 stays parked.
Evidence tags: [HW-PROVEN] (owner hardware 2026-10-26 12:07–12:26),
[TESTED-ONLY] (sandbox), [BROKEN-laptop] (until owner re-run).

## DONE

1. **STREAM A — sensors first (WP0 doctrine).**
   - `stop.requested` schema event at every stop entry, carrying
     `source=cli|bind|watchdog` and the session_id. The watchdog routes
     through the same stop entry (`source=watchdog`); a bind stop is
     marked via `assist ptt stop --stop-source bind` (new CLI flag; the
     shipped `ui/hyprland/elaria-binds.conf`/`.lua` release lines now
     pass it). The next scene reads truth from text alone:
     `stop.requested` absent = the bind never fired; present-but-failed =
     the stop arrived and failed. [TESTED-ONLY]
   - `ack.played` / `ack.failed` schema events land with the Stream-B
     fix (below): player argv + returncode + error detail per attempt.
   - **Owner bindr probe prepared** (HANDOFF §7, manual editor edit —
     never sed): the exact probe line for below hyprland.conf:213, the
     reload/cycle/cat/delete procedure, and both outcome branches —
     bindr fires → env diff (bind-exec vs terminal); bindr never fires on
     0.56.2 legacy conf → escalate with the recommendation to pull WP3
     forward for the BINDS ONLY (Lua release bind with ignore_mods is the
     structural fix) plus an interim stopgap for owner decision
     (temporary SUPER+SHIFT+F3 = `assist ptt stop --stop-source bind`;
     stopgap never final — hold-to-talk UX is the settled design).
   - **Deferred-retry audit (2026-10-26):** "retained for retry" is a
     MESSAGE ONLY. The no-final path (`transcribe.py` →
     `transcription.deferred` verdict=no_final) keeps the wav and says
     "retained for retry", but NOTHING consumes it — the offline queue
     (`enqueue_transcription`) only covers `pending_cloud_transcription`
     (low-confidence offline), never the no-final/watchdog-severed case.
     **Defect logged (HANDOFF §6.8), owning phase WP5.** Contract owed:
     the kept 12:07 wav (`audio/20261026-120742-1beaea.wav`) is the
     standing test case — it either eventually transcribes and answers,
     or is explicitly marked never-retried. No third state.
     [TESTED-ONLY audit; limbo visible in the owner's ledger.]
2. **STREAM B — ack playback (played:false with a live sink).** Trace of
   the cached-ack player invocation, end to end:
   - **Binary resolution:** `[tts] player` ("auto" → pw-play, paplay,
     aplay via PATH; a custom command; or "none"). The first available
     binary was a COMMITMENT — a player that exists but fails ended
     playback outright while the next candidate (the owner's working
     paplay) could still make sound. **Fixed: the chain tries every
     available candidate in order.**
   - **argv/env/error swallowing:** `play_audio` returned a bare False on
     three silent failure modes (no player binary; spawn error/timeout
     recorded only in `last_voice_error`; non-zero exit with stderr
     DISCARDED). **Fixed: `_play_with_detail` records argv, returncode
     and the stderr tail per attempt; every result carries
     `player`/`argv`/`error`.**
   - **Reporting:** the ack's `played` flag is False at response time by
     construction (§18: acknowledge first, play in the background) and
     the fire-and-forget result was never reported anywhere. **Fixed:
     `ack.played`/`ack.failed` schema events carry the outcome
     (ack_kind, player, argv, error) with the session id.** An ack that
     will never play now says WHY (`speak_suppressed`: "release ack —
     never spoken by design" / "class mode" / "speak_acks off") — the
     owner's pasted `played:false` was the `ptt.stop` ack, silent by
     design, and it read like a failure because nothing said so.
   - Invoked-runner tests (`tests/test_ack_playback.py`, BH-H9 lesson —
     sandbox has no audio binaries, assert the call shape): fallback
     chain order + argv shapes, spawn-error fall-through, all-fail error
     recording, no-player reason, play_ack detail carrying, daemon-level
     `ack.played`/`ack.failed` emissions, release-ack-never-plays with
     its reason, and the press earcon (session cue) reporting through
     the same chain. [TESTED-ONLY — the owner's scene paplays the ack
     wav (`speech-c3355e59132b6af3283d.wav`) to verify it end to end.]
3. **STREAM C — completion evidence: PENDING the owner's post-stop
   journal tail** (owed). When it lands and shows `transcription.landed`
   + reply + `quota.counter` 1 user-turn, the reply path is HW-PROVEN
   end-to-end via manual stop and the regression mechanism is the
   release path ALONE — then HANDOFF §5 records it, including the formal
   retraction of alias-causation for the silence week (pins remain
   correct hygiene; cause = stop path). Merge-gate wording untouched.
4. Suite: **1,866 passed, 6 skipped**; ruff clean on touched files.

## DEFECTS FOUND (logged, not fixed)

1. **Deferred-retry limbo (new, this audit):** no consumer for kept
   no-final audio — owning phase WP5. The 12:07 wav is the standing test
   case (eventually transcribes+answers, or explicitly marked
   never-retried — no third state). [TESTED-ONLY audit.]
2. The bindr release failure itself is UNDIAGNOSED between two worlds
   (bindr never fires on 0.56.2 legacy conf vs fires-but-stop-no-ops) —
   the probe splits them; neither is fixed here. The WP3 Lua release
   bind with `ignore_mods` is the structural fix either way.
3. Carried: eventSnap (WP2) · file-fallback logic (WP5) · cached-TTS
   route (WP1) · event-smoke segment timing (WP5) · bug6
   [BROKEN-laptop, main-parity] · `uv sync` on 3.14 [UNVERIFIED].

## NEXT GATE

**Scene 3b (owner, daylight, ≤30 min)** — procedure in HANDOFF §7:
1. the bindr probe (exact line, manual editor edit, never sed),
2. a clean natural cycle on the branch build (restart the daemon first),
3. `paplay` of `~/.local/share/assistant/voice-cache/speech-c3355e59132b6af3283d.wav`,
4. the journal tail 60+ s after a manual `assist ptt stop` (Stream C's
   trigger).

Gate (unchanged, still red): a NATURAL Win+F2 hold-speak-release cycle
must produce earcon at press, session close at release, final transcript,
spoken reply, and schema lines for each.

Both outcomes are decisions: a failed scene produces a log dump and a
diagnosis, never a retry loop.

## OPEN QUESTIONS

1. If the probe shows the bindr NEVER fires: pull WP3 forward for the
   binds only — owner decision. If it fires: why does
   `assist ptt stop` no-op from the bind while working from a shell
   (env diff through the same probe)?
2. The interim stopgap (SUPER+SHIFT+F3 = stop) is owner-decision-only
   and never final; hold-to-talk is the settled design.
3. Stream C's retraction wording lands with the journal tail — no
   earlier.
