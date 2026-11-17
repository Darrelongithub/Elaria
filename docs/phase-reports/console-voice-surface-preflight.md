# Console voice surface — preflight and owner-tooling follow-up

## Owner acceptance, recorded without rewriting earlier reports

Owner addenda 4–6 report three installed-file receipts, a cold three-file PASS/0, the correct
existing generated bind at `/home/darrel/.config/hypr/hyprland.lua:151`, and Win+Space opening
native GTK ELARIA: **“It worked.”** No config edit or reload was required. The missing wrapper
was the operational defect; the cause of the original silent invocation is still not observed.
The old checker stopped before examining the wrapper, so its zero receipts alone were not an
exhaustive historical filesystem receipt. Later installation/observation/key evidence closes
the operational issue without making that earlier check more comprehensive than it was.

The owner's F37 ruling is accepted: mainline capture fix 9e49915 and owner installation/key
conditions are satisfied. Natural-reboot recovery is residual, not a hold. No merge/rebase or
service change was performed. G/H/I, d624ddf, d893719 and their evidence remain historical.
No unprovided HTTP/storage/geometry measurements are invented here.

## Delivered in this tooling follow-up

| Ask | Result | Boundary |
|---|---|---|
| 32 | Manifest-first short owner lines; literal fallback moved into a committed script; resolved path/actual/expected printed | Trusted release identity still anchors a same-tree manifest; manual stages require checking OK before execution |
| 33 | All three target verdicts; PASS/0, NOT_INSTALLED/3, PARTIAL_INSTALL/4, invalid/unreadable STOP/2 | Current absence is not proof of historical never-installation; no repair/writes |
| 34 | Bounded read-only literal bind scanner plus optional live binds query; target/line/file hash/duplicate candidates/wrapper state | Dynamic Lua/includes cannot be exhaustively interpreted without executing config; loaded binds do not attest source-line provenance |
| 25 + voice surface | Preflight only, not implemented or accepted | Full source specification and privacy/protected-producer scope need resolution below |

Current installer SHA256:
`c0a558a7116a38ef0b0abd68ca39f6994c93253f3b15f94ce81cc276ee8185fb`.
The three installed G payload hashes and deployment target 25ef8e6 are unchanged. Neither H/I
nor a new voice surface is installed by this tooling release. The observer has its own separate
manifest; the native manifest remains exactly four files.

See `console/NATIVE-DEPLOYMENT.md` for short owner lines and verdict/observation semantics.
An already-working owner deployment does not need reinstall/reload just to accept this tooling.

## Existing orb inventory — before any new mapping

Audited current consumer source, unchanged in this follow-up:

- `console/src/shell.html:84–97`: `<aside id="orb">`, visualizer mount **`#stage`**;
  **`#rs`** state label, **`#rsrc`** signal label, **`#rm`** meter and **`#orbnote`** provenance note.
- `console/src/shell.js:145–175`: `Elaria.create(el.stage, {simulate: true, fit: 1.8})`,
  `V.setState`, `V.setLevels`; state is also written to the container dataset and aria label.
- `console/elaria-visualizer.js`: native engine states **idle, listening, thinking, speaking,
  offline**. Unknown states throw. There is **no error state**. Levels are an input/output
  amplitude API, not a sixth categorical state. No new orb needs drawing.
- Current speaking admission is output-level-driven; those levels can be synthetic text cadence.
  That is not daemon PCM playback evidence. Real playback state requires a deliberate replacement
  of that consumer contract, not relabelling the old cadence as measured audio.
- `shell.js:565–592` contains a separate local-browser microphone control; the engine exposes
  `useMicrophone`. That is NOT the daemon PTT path. It must not remain a competing capture option
  on the new live voice surface. No change/removal was made during preflight.
- Typed textarea activity can also drive synthetic input levels/state. It must not imply an open
  daemon capture session after this feature is wired.

### Required mapping, not yet shipped

| Desired indication | Existing representation | Evidence needed / gap |
|---|---|---|
| idle | native idle | daemon available AND capture closed AND no pending generation/playback; stale connection must not imply certainty |
| listening | native listening | capture-open acknowledgement + VAD state; button click/request alone is not enough |
| input level | `setLevels('input', …)` + meter/readout | sampled raw/processed peaks and limited-sample metadata from actual daemon capture; never browser microphone or generated noise |
| thinking | native thinking | generation lifecycle tied to the accepted turn/session, not arbitrary typing |
| speaking | native speaking | player lifecycle/progress, not synthesized text or a cache/synthesis result |
| error | **engine gap** | existing readout/accessible error treatment can report failure without silently inventing an engine state; mapping needs spec approval |

Keep raw and processed values separately labelled; do not clamp the diagnostic raw value into
looking healthy. A limiter contradiction is a reportable failure, not a reason to suppress the
raw evidence. A measured aggregate after a take is not a live signal during capture.

## Producer audit at immutable 9e4991583e8659703cda2df0eac9f4c59fd1c740

Only fetched/read; no merge, rebase or source copying into this branch.

1. `transcribe.py:966` sends frames to the Live transport. `live_client.py:1110–1114` sends PCM
   with `session.send_realtime_input(audio=types.Blob(...))`. Thus the existing code has a remote
   microphone-audio path. “Reuse PTT unchanged” is not itself a no-audio-egress guarantee.
2. `transcribe.py:1683` logs `capture.levels` while finalizing results, including raw/processed
   peaks, limited samples and steady/full peak readings. This is not evidence of a currently
   mounted, continuously streamed capture-level feed to the console. Live metrics/event plumbing
   is a producer task if the full spec does not identify another existing signal.
3. `_ptt_start` at `daemon.py:1879` does NOT toggle off: if capture is already running, it returns
   `already_listening` with no second cue. `assist ptt toggle` at `cli.py:2635` checks status and
   chooses start or stop. The owner has ruled a toggle UI; it should use the same daemon start/stop
   implementation, not assume repeating `ptt.start` stops capture. Atomicity/race handling must be
   explicit rather than two clients racing a copied status check.
4. The inspected speech adapter's output-transcription discard is not resolved merely by the
   capture fix. Current branch and newer mainline differ substantially in gateway, streaming,
   cache settings and causal metadata. No obsolete producer-gap claim or silent mainline import
   is being made; the integration basis must be agreed before protected source edits.

## Fidelity first — proposed acceptance pins and limitations

The requested output transcript must come from retained speech output transcription, never the
intended reply string as a fallback. A transcript is model-produced evidence of generated audio;
it does not prove successful playback or perfect word recognition. The owner's ears remain the
hardware acceptance standard. Avoid the stronger claim “agrees by construction” for audible
output: a player can be muted/absent/fail after synthesis, and output transcription can be wrong.

Before UI wiring, the producer contract needs stable turn/session/utterance IDs linking:
- intended reply and existing producer message IDs;
- full route/voice/settings identity;
- generated output transcription, its completion/status, and PCM/WAV content digest;
- player start/end/failure, partial-delivery state, and any cache origin.

The existing reply journal must not be overwritten to hide a mismatch. An append-only delivery
observation should distinguish intended text from generated output and playback evidence.
Unknown/missing transcription is no honest transcript source, never permission to copy reply text.

Ask 25 tests should include two normal turns with deliberately different replies and identical
voice/route settings, asserting request-owned displayed text, exact persisted message IDs/text,
TTS source, retained output transcript and cache identities. Negative tests must additionally
exercise contrary/missing output transcription, wrong/missing cache content receipt, crossed
turn IDs, cache swapping, interrupted generation/playback, and a muted/unavailable player.
A mock accepting the input text as its own “spoken transcript” cannot test the audited defect.

Cache hits need content/receipt linkage, not existence/nonzero length; legacy entries lacking
that evidence must not be silently trusted. Hashing full text still cannot prove PCM wording.
Any fidelity gate that withholds mismatching audio before playback also has to address the newer
streaming path, which can play chunks before a final transcript arrives. Retention alone does
not resolve that ordering. No streaming/player path is changed here under an assumed grant.

Surface negative tests must prove: no renderer audio output even if daemon playback is absent;
no capture implication before capture-open or after close; stale/disconnected events cannot
resurrect recording; no spoken consent asks; empty standing allowlist remains unchanged. These
are future feature gates, not claims made by today's passing installer tests.

## Decisions needed before protected voice implementation

1. **Full spec:** Drive exact-title, broader-title and full-text searches found no accessible
   `CONSOLE-VOICE-SURFACE.md`. Attach it or provide its link. The supplied four rulings are
   recorded; no unseen details are assumed approved.
2. **No-audio-egress scope:** does the rule prohibit all outbound microphone PCM (requiring a
   local capture/transcription policy), or prohibit console/browser audio capture/upload while
   preserving the daemon's existing authorized remote transcription policy? Until resolved,
   no new console action that might transmit microphone audio will be wired.
3. **Protected producer scope/integration basis:** retaining transcription/cache receipts and
   emitting player/capture events reaches `gemini_client.py`, `tts.py`, `daemon.py`, and likely
   protected `transcribe.py` for live levels. Confirm a narrow grant or identify the producer
   revision/interface the consumer must use. Existing eight-line mount regression is not
   silently weakened; no mainline reconciliation is implied by F37 acceptance.

Provisional estimates supplied before implementation: asks 32–33 45–75 minutes; ask 34 60–90
minutes; fidelity/cache 2–4 hours; voice consumer/negative gates 3–5 hours after the contract
and scope are settled. These are estimates, not background work promises.

## Validation

- Focused owner tooling: **41 passed in 0.31s**.
- Full suite: **2798 passed, 9 skipped in 155.23s**.
- F36 full-suite trend: 154.93s accepted report → 155.01s d893719 → **155.23s** (+0.22s).
- Ruff 0.17.2 whole repository: pass. Four native hashes and observer hash: pass. Diff whitespace:
  pass. Initial new observer-test failure (1 failed/39 passed in 0.34s) was an overbroad privacy
  assertion matching a filename; corrected assertion distinguishes metadata from command content.
- Earlier installer listener failures remain documented; no production guard was weakened.
- Workspace Git metadata initially pointed at the original base while accepted file contents
  persisted. After fetching this same branch, all **342** tracked files were compared byte-for-byte
  with d893719; only then was the index/HEAD restored with a mixed reset. No source content or
  branch was switched. Prior uncommitted speech audit remains separate and unmodified.
- No real model, paid route, device capture, audio output, owner store/config, reload or service
  control was used. Consumer and protected producer code remain unchanged.
