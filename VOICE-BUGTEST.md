# VOICE-BUGTEST — adversarial hunt on the speaking pipeline only

Run 2026-10-20 in the Arena sandbox. `GEMINI_MODE=mock`, no API key (the suite
fixture deletes `GEMINI_API_KEY`/`GOOGLE_API_KEY` and asserts it stays absent),
`HOME`/XDG redirected to temp dirs — no real folders, no voiceprint, no mic.
`pytest -q tests/test_voice_bughunt.py` → **34 passed, 13 xfailed** (every
`xfail` is a confirmed defect pinned as an executable repro; strict, so a fix
turns the suite red until the pin is removed).

Re-run everything:

```bash
cd ~/Elaria && PYTHONPATH=src pytest -q tests/test_voice_bughunt.py         # all of it
PYTHONPATH=src pytest -q tests/test_voice_bughunt.py --runxfail   # failures as failures
PYTHONPATH=src pytest -q --tb=line                            # whole suite, complete
```

## Verdict up front

**She can be trusted to stay silent, and cannot yet be trusted to speak.**

* Silence: 0 defects. Every offline, unavailable-cloud and mock path was proven
  to make **zero** audio calls, write **zero** files, and report why
  (`A.2`, `A.2b`, `A.4`, `A.4b`, `B.6`, `D.12`, offline ack cost 0.010 ms). The
  Piper path never spoke in any test that left it dormant — except via VB-3.
* Speech: **13 defects**. Three are the wrong-voice class you marked CRITICAL
  (`VB-1`, `VB-3`, `VB-4`); two make the hotkey answer with nothing
  (`VB-2`, `VB-13`); the rest sit in endpointing, the transcript, the doctor,
  process hygiene and the Waybar pill (`VB-5`…`VB-11`, `VB-14`). Detail below.

| # | Area | Result | Severity |
|---|------|--------|----------|
| A.1 | conversation, task reply, pushback, error, completion, acks all resolve to Flare | PASS | — |
| A.1b | no call site may name a voice; no second prebuilt voice in `src/` | PASS | — |
| A.1c | real `Daemon` handlers (`reply`, `ack`, `announce`, `speech.say`) all Flare | PASS | — |
| A.2 | network death mid-conversation → zero audio | PASS | — |
| A.2b | same, driven through `Daemon` + real `ModeManager` | PASS | — |
| A.3 | config poisoning: bogus voice + legacy `tts.selected_voice` row | **FAIL** | **VB-4 CRITICAL** |
| A.4 | `voice status` truthful in ONLINE / OFFLINE / FORCED_OFFLINE | PASS (payload) | — |
| A.4c | the Waybar pill says the same thing | **FAIL** | VB-14 LOW |
| B.5 | ack latency cold / warm / restart | PASS (numbers below) | — |
| B.5b | dormant-path config change must not silence the hotkey | **FAIL** | **VB-2 HIGH** |
| B.5c | ack cache ready before the socket serves | **FAIL** | **VB-13 HIGH** |
| B.6 | deleted / 0-byte / corrupt ack files | PASS (no crash, no bogus play) | — |
| B.7 | voice change invalidates the cache | **FAIL** | **VB-1 CRITICAL** |
| B.7b | pace change invalidates the (dormant) local cache | PASS | — |
| B.7c | local audio must never answer an online ack | **FAIL** | **VB-3 CRITICAL** |
| B.7d | no ack resolves to another ack's file | PASS | — |
| C.8 | 0.6 s / 1.5 s / 3 s narration pauses don't cut | PASS | — |
| C.8b | per-mode thresholds, asked once | PASS | — |
| C.8c | every runtime-requestable mode is configured | PASS | (note: `conversation` unreachable) |
| C.9 | check-in exactly once per thought | **FAIL** | VB-5 MED |
| C.9b | close after grace once asked | **FAIL** | VB-6 MED |
| C.10 | 100× pause/resume fuzz: no lost head/tail, no stuck state | PASS | — |
| D.11 | Live 429 mid-utterance → replay once, one transcript, no error recital | PASS | — |
| D.11b | rotation must not lose the head | **FAIL** | VB-7 MED |
| D.12 | offline low-confidence → redo exactly once | PASS | — |
| D.13 | garbage / 0-byte audio never a confident command | PASS | (VB-12 LOW diagnostic) |
| D.13b | transcribed words must not execute ungated | **FAIL** | VB-8 HIGH |
| E.14 | voiceprint corrupt / world-readable refused in doctor | **FAIL** | VB-9 MED |
| E.14b | no activation path can fall back to "any voice" | PASS (by absence) | — |
| E.15 | missing persona/profile files degrade loudly | PASS | — |
| F.16 | serious gates ban humour (6 gates) | PASS | — |
| F.16b | pushback spoken once, with its evidence | PASS | — |
| F.16c | no softeners/apologies in canned lines | PASS | — |
| F.16d | "do it anyway" by voice | **not implemented** | VB-15 GAP |
| F.17 | ack set stays short, terminal, non-hedging | PASS | — |
| G.18 | SIGKILL mid-playback must not orphan audio | **FAIL** | VB-10 MED |
| G.19 | double hotkey → one session, one ack | **FAIL** (session ok, ack doubled) | VB-11 LOW-MED |
| G.20 | wall-clock jump / session cap must not misfire timers | PASS | — |

13 pinned defects (`--runxfail` shows each as a failure with its own message);
VB-12 and VB-15 are observations, not pins.

---

## CRITICAL class — wrong voice

### VB-1 · a voice change replays the previous voice's audio
`src/assistant/tts.py:342-348`

The cache key is `{text, backend, voice: descriptor.voice_id, model, speaker,
length_scale}` — that is the **local Piper descriptor**. `[gemini] voice` and
`[gemini] model_voice` are not in it. So Flare-era files keep answering after
the voice changes, and `assist voice status` reports the new voice while the
player replays the old one.

```
_, speech, _ = service(tmp_path)
speech.warm_ack_cache()
before = Path(speech.cached_ack("on_it"))
config.raw["gemini"] = {**config.section("gemini"), "voice": "Kore"}
assert speech.cached_ack("on_it") != before     # FAILS: same path, same old bytes
```

Blast radius: all four acks (fixed strings ⇒ always a hit) and any repeated
identical reply. Fix: for the cloud route key on `("gemini-native-audio",
gemini.voice, gemini.model_voice)` and nothing else.

### VB-3 · a dormant Piper render answers an online ack
`src/assistant/tts.py:538-542`

```python
if route == "gemini" and not (path.exists() and path.stat().st_size > 0):
    # A warmed local copy beats silence on the <300ms ack path.
    local = self._cache_path(STANDARD_ACKS[kind], descriptor, backend.name)
```

That comment is the old contract, and it is the amendment's exact prohibition:
the local voice may not speak in normal operation. Any leftover local ack file
(one `assist voice warm` while `online_voice = "local"`, or the audition era)
makes her voice Piper on an *online* turn — and `status()["cached_acks"]`
reports the ack as healthy, so nothing looks wrong. This one is mine, from the
interim commit, and it is reachable today.

```
local_path = speech._cache_path("On it.", speech.descriptor(), "mock-local")
local_path.write_bytes(b"RIFFfake-piper-audio")
assert speech.cached_ack("on_it") is None       # FAILS: returns the Piper file
```

Fix: delete the fallback — a missing online ack is a miss, and a miss is a
re-warm, not a substitute voice. Interim relief on the box:
`rm -rf ~/.local/share/assistant/voice-cache && assist voice warm`.

### VB-4 · any config string silently becomes her voice
`src/assistant/gemini_client.py:253`, no validation anywhere

`[gemini] voice = "Zephyr"` ⇒ she speaks Zephyr. A legacy `tts.selected_voice`
row is (correctly) ignored online, but nothing documents that, and doctor stays
green. Requirement: honour exactly one documented precedence **or** fail
loudly. Current state: silent honouring of whatever string is there.

```
config.raw["gemini"]["voice"] = "Zephyr"
assert speech.speak("On it.", play=False).voice_id == "Flare"   # got 'Zephyr'
```

Fix (small, no new machinery): treat Flare as the pin — resolve the voice, and
if it is not the shipped default, doctor reports `warn` with the resolved name
and `voice_request()` refuses unless `[tts] allow_experimental_voice = true`.
Owner said one voice ever, so a warning is the minimum honest behaviour.

---

## HIGH — the ack that never arrives

### VB-2 · an unrelated setting kills every cached ack, forever
`src/assistant/tts.py:342-348` (same key, opposite direction)

`length_scale`, `speaker`, `model`, the selected local voice — all dormant-path
knobs — are in the **online** key. Change one and every online ack becomes
`cache_miss` permanently, because `play_ack` deliberately never synthesises on
the hot path. Measured: warm ack 1.286 ms → after `length_scale = 1.0`:
**0.063 ms of silence**, no warning, no doctor row, until someone remembers
`assist voice warm`. Re-warming costs 0.9 ms, so there is no excuse for the
permanence.

```
speech.warm_ack_cache(); assert speech.cached_ack("on_it")
config.raw["tts"]["length_scale"] = 1.0
assert speech.play_ack("on_it")["cache_miss"] is False   # FAILS: True forever
```

Fix: key the cloud route on cloud identity only (VB-1's fix does both), and
make `_ack` self-heal: on a miss, schedule a warm task and say so in doctor
until it clears.

### VB-13 · the socket opens before the cache exists
`src/assistant/daemon.py:903-905`

```python
server = await serve(self.config.socket_path, self.handle)   # accepts now
connectivity_task = asyncio.create_task(self._connectivity_loop())
warm_task = asyncio.create_task(self._warm_speech_cache())    # warms later
```

Offline that window is ~1 ms. Online, warming is one rate-limited cloud render
per ack, so after every boot there is a seconds-long stretch where the first
press answers with text only — the hotkey path going silent on a healthy
config is the §18 failure mode. Fix: `await` the warm before `serve()`, or hold
`ack` at the text surface (as now) plus a `voice warming` doctor line.

### VB-8 · transcribed words reach the intent ladder with no confidence gate
`src/assistant/daemon.py:489`

```python
if self._dictation_session_mode == "command" and result["text"].strip():
    result["command"] = await self._ask({"text": result["text"], ...})
```

`result["text"]` is the *cleaned* text **or, when cleanup flagged it, the raw**
— flagging means the rewrite diverged >35%, i.e. "this ASR output is suspect".
`confidence` and `cloud_status` are not consulted. `route()` owns `undo`
(reverses journal operations) and `remember`/`forget` (mutates memory), so a
mic that hears "undo." from a TV can move files, in the mode the user selects
with `assist dictate --command`. Not a voice-identity defect, but the voice
pipeline is what hands text to it.

Fix: in command mode require `confidence >= asr.offline_low_confidence_threshold`
**and** `not flagged`, and restrict the voice-reachable grammar to read-only
rungs (`status`, `cost`, `where`, `search`) — `undo`/`remember`/`forget`
need the typed path or an explicit confirm.

---

## MED — endpointing, transcripts, abuse

* **VB-5 — one thought, two nags.** `transcribe.py:61` clears `_asked` on any
  frame over the RMS gate, so a breath, a key click, or her own playback bleed
  mid-pause re-arms the ladder and "Is that all?" fires again inside the same
  silence. The docstring promises otherwise. Repro: 1.2 s silence (ask) → one
  30 ms blip → 1.2 s silence → **asked twice**. Needs the (currently missing —
  see the note at the end) energy-VAD or a minimum re-arm window
  (e.g. speech sustained ≥250 ms) to tell a thought-resumes from a noise.
* **VB-6 — asked, then never closed.** Item 9: asked once, *then closes after
  grace*. Nothing closes: the only exit is the user's own hotkey release, and
  the daemon's capture source is `speech_frames=100_000` (~50 min). Walk away
  mid-dictation and the mic, the `listening` state and the PipeWire stream stay
  held, silently. `SilenceLadder` has no grace concept at all.
* **VB-7 — rotation eats the head.** `transcribe.py:247` does
  `collected.clear()` on a server GoAway, discarding finals already received;
  only the ≤30 s replay buffer is re-heard. Repro (replay window shrunk to
  0.12 s so it fits one test): 30-frame utterance, session 1 emits `w0 w3 w6`,
  transcript ends up `w24 w27…` — **the first words are gone**. Beyond ~30 s of
  dictation any rotation loses the beginning. Raw WAV survives, the transcript
  does not, and `assist events` already showed the words — so the user watches
  text evaporate. Fix: keep the earlier finals and append (dedupe by frame
  offset), or persist interim finals as they arrive.
* **VB-9 — doctor trusts a broken biometric.** `cli.py:196-201` checks
  `voiceprint.exists()` only. A 0-byte, unparseable, wrong-schema or **0644**
  `voiceprint.json` prints `ok — present (path only…)`, while
  `load_voiceprint()` raises on the same file. Refuse loudly (and check mode
  `& 0o077`) instead of green-lighting an unusable, world-readable template.
* **VB-14 — the pill mislabels the voice** (`waybar.py:71`): it prints
  `voice: local <backend> / <voice_id>`, so **online** it reads
  "voice: local gemini-native-audio / Flare" (cloud audio, labelled local) and
  **offline** "voice: local none / none" — which reads as broken, not as the
  posture. The `voice status` *payload* is truthful (A.4 passes); only this
  label is stale. Pinned; LOW because it misinforms rather than misbehaves.
* **VB-10 — SIGKILL orphans the audio child.** `tts.py:503` runs the player via
  `subprocess.run` with no `start_new_session`/process group, so a killed daemon
  leaves `pw-play` holding the sink. Proven with a real daemon subprocess and a
  real player: after `kill -9`, the player pid **11712 was still alive**. Same
  shape for `pw-record` (`capture.py:211`) → the mic stays claimed; the graceful
  path is fine (`aclose` → `terminate()` + `await wait()`, `capture.py:225-228`).
  Fix: `start_new_session=True` + a systemd user scope with
  `Delegate=yes`/`KillMode=control-group`, or track and kill children on exit.
* **VB-11 — a rejected double-press still speaks.** `daemon.py:412-414` answers
  the *loser* of the race with its own `on_it` ack, so one double-press sounds
  like two answers (measured: 2 plays across two starts, 3 including the
  release ack). The single-owner guard itself works — `note: "already
  listening"` and no second session — so this is wording, not correctness:
  the rejected press should return the note with no ack speech.
* **VB-12 — one diagnostic that lies by omission.** 0-byte audio offline raises
  `RuntimeError: all ASR backends failed — local: offline ASR needs
  faster-whisper…`: an empty file is blamed on a missing package. Fails safe
  (no confident transcript, no crash, no phantom queue row), but the message
  sends the user to install something they already have.

## Observations (not pinned)

* **VB-15 · "do it anyway" is not a voice path.** `route("do it anyway")` and
  `route("approve")` are both `None`; approval lives in
  `assist approve`/`queue.approve` only. Fine as a safety choice, wrong as a
  claim: an approval-gated action cannot be cleared by voice at all.
* `checkin_after_s` configures `conversation: 6` but no entry point can select
  that mode — the runtime vocabulary is `{narration, command}`. Dead setting,
  one line to either wire or document.
* The serious-gate work holds: all six gates veto banter even when a funny line
  is available (`register != expressive-allowed`, `teasing_licence == "none"`,
  gate named in the decision), no canned line anywhere in `tts.py`,
  `overlay.py`, `waybar.py`, `persona.py`, `offline_queue.py` contains a
  softener or an apology, and the ack set is ≤6 words, terminal-punctuated,
  non-hedging.

## Latency numbers (§18 budget = 300 ms)

`tests/measure_voice_latency.py` (in the repo, so these are re-runnable), 200 samples
in-process / 120 over a real Unix socket, fake
player that forks and exits (`sh` → `exit 0`), i.e. real fork+exec cost included:

| state | median | p95 | max | audible? |
|---|---|---|---|---|
| cold, nothing warmed | 0.061 ms | 0.097 ms | 0.234 ms | **no — silent miss** (VB-13) |
| warm, Flare route, player spawned | 1.286 ms | 1.495 ms | 1.653 ms | yes |
| same, after daemon restart | 1.327 ms | 1.619 ms | 2.424 ms | yes — cache survives ✓ |
| after a dormant `length_scale` change | 0.063 ms | 0.104 ms | 0.267 ms | **no — silent miss** (VB-2) |
| warm lookup alone, `player = "none"` | 0.052 ms | 0.089 ms | 0.131 ms | n/a (no sink) |
| offline, `play_ack` | 0.010 ms | 0.013 ms | 0.082 ms | intentionally silent ✓ |
| **end-to-end `ack` over IPC** | **2.68 ms** | **3.40 ms** | **3.82 ms** | yes — **~90× inside budget** |

Warm-up of all four acks: 0.8 ms total (0.2 ms/ack, mock) / 0.9 ms to re-warm
after VB-2 — i.e. the missing auto-re-warm costs nothing, which is why VB-2 and
VB-13 are not excused by the budget.

Re-run spread across two invocations of the harness: warm 1.286 / 1.346 ms, IPC
2.68 / 2.51 ms median — i.e. the numbers are stable to well under a millisecond,
and nothing near the budget.

Caveats, stated plainly: playback *audibility* was measured with the local mock
route because a mocked Gemini produces no audio; on a live box the hot path is
identical (file lookup + spawn) and only the *warm* step gains network latency.
Real `pw-play`/`pipewire` queueing, device wake latency, and per-clip
wall-clock duration are needs-live.

## needs-live list — parked, not faked

1. **VB-13 online warm window** — time `assist voice warm` with a real key:
   `GEMINI_MODE=live GEMINI_API_KEY=… PYTHONPATH=src python -m assistant.cli
   voice warm`, and press the hotkey immediately after `systemctl --user restart
   assistant` to see whether the first ack is silent.
2. **VB-1/VB-4 on real audio** — set `[gemini] voice` to a second prebuilt name,
   `assist voice warm`, then confirm by ear whether the ack still sounds like
   the previous voice. Also confirm Flare is the voice you want before pinning
   it in code.
3. **VB-10 with real PipeWire** — `kill -9` the daemon mid-`pw-play` and
   mid-dictation; check `pw-cli ls Node` for the leaked stream and
   `pactl list source-outputs` for the held mic.
4. **VB-5/VB-6 acoustics** — narration with real 0.6/1.5/3 s pauses, a cough
   after the check-in, and walking away mid-session; confirm the double-nag and
   the 50-minute `listening` hold on hardware.
5. **E.14 wake word + voiceprint** — no wake-word activation exists in the
   runtime (`voicetest.py` is the offline harness only), so "other speakers / TV
   / playback must not wake her" and "never fall back to any voice" are true
   **by absence**, not by a tested gate. Needs: enrolment, false-trigger rate
   over a day, and the `OpenWakeWordScorer` path on the Fedora box.
6. **D.13 real garbage audio** — silence-only, music, TV speech, clipped
   screaming through the *actual* ASR, then `assist dictate --command` on a TV
   saying "undo." The structural gate (or lack of one) is proven; the acoustic
   behaviour cannot be.
7. **A.2 with a live call in flight** — `GEMINI_MODE=live`, start a reply, pull
   the cable mid-stream: expect a *reported* silence, and check that no partial
   Flare clip is played.

## Harness hazard found while hunting (not a voice bug, but it eats findings)

`pytest -q` on the whole suite **silently truncates** in this sandbox: 1005 of
1108 tests report, then the session dies inside pytest's own traceback
formatting — `_pytest/_code/code.py:916 _getentrysource → ast.parse →
SystemError: AST constructor recursion depth mismatch`. It predates this hunt
(seen at 793 passed before any of these files existed), the crash point moves
with the run, and `-p no:warnings` / `-p no:assert` do not help while
`--tb=line` / `--tb=no` fix it completely (verified: 1044 passed, 5 skipped,
59 xfailed = all 1108, twice). Two consequences worth stating: a short green
run proves nothing unless you check the collected count, and my `A.1b` source
scan now runs in a subprocess — the same convention `test_daemon_cli.py`
already uses for exactly this bug.

## One note on the sandbox, not a bug

Section C is measured against the ladder that is actually in the tree
(RMS-energy gate in `transcribe.py`). The VAD/barge-in work that would change
VB-5 and VB-6 (`src/assistant/vad.py`, commit `f692212`) exists in no ref here
— `origin/main` sits at `0bb40c7`, behind the `ca97a41` this branch is on — so
if that work survives on your clone, re-run C before accepting those two
findings. A, B, D, E, F, G are unaffected.

---

**Can she be trusted to speak — and to stay silent — correctly?**

**Stay silent: yes.** Twelve offline/unavailable probes across service and
daemon level — `speak`, `synthesize`, `cached_ack`, `warm_ack_cache`, `play_ack`,
`_ack`, `_maybe_speak_reply`, `_speak_in_background`, `speech.say`, the
check-in sink, mid-conversation network death, FORCED_OFFLINE and a killed
socket — produced **zero** TTS calls, **zero** files, and a stated reason every
time. No offline-speaking defect was found, including under fuzzing and cache
corruption.

**Speak correctly: no.** Three separate ways to hear the wrong voice already
exist: a voice change that replays the old voice's ack audio (VB-1), a dormant
Piper file that answers an online ack while doctor reports everything healthy
(VB-3, my own interim code and reachable on a box that ever ran
`online_voice = "local"`), and a config string that silently *is* her voice
with no warning anywhere (VB-4). Two more make the hotkey say nothing at all
after an unrelated tweak or a reboot (VB-2, VB-13). Fix VB-1/VB-2 together in
the cache key, delete the VB-3 fallback, pin Flare with a loud doctor
mismatch — about 25 lines and one test file already written to prove each — and
the answer becomes yes.
