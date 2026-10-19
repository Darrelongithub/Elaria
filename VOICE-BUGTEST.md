# VOICE-BUGTEST — adversarial hunt on the speaking pipeline only

Run 2026-10-20 in the Arena sandbox. `GEMINI_MODE=mock`, no API key (the suite
fixture deletes `GEMINI_API_KEY`/`GOOGLE_API_KEY` and asserts it stays absent),
`HOME`/XDG redirected to temp dirs — no real folders, no voiceprint, no mic.
`pytest -q tests/test_voice_bughunt.py` → **34 passed, 13 xfailed** at hunt time
(every `xfail` was a confirmed defect pinned as an executable repro; strict, so a
fix turns the suite red until the pin is removed).

**After the fix passes (Gates A–D, 2026-10-20): 59 passed, 1 skipped, 0 xfailed** —
all 13 pins were converted into passing regressions and each one was re-run against
the pre-fix source to prove it still bites. The skipped test is the needs-live
placeholder (`test_b5f`), never faked. See **FIXES** below and the ledgers in
[`bugs.md`](bugs.md) / [`change.md`](change.md).

Re-run everything:

```bash
cd ~/Elaria && PYTHONPATH=src pytest -q tests/test_voice_bughunt.py         # all of it
# prove a guard still bites (hide the fix, keep the test):
git stash push -u -- src/assistant/tts.py src/assistant/proc.py && \
  PYTHONPATH=src pytest -q tests/test_voice_bughunt.py -k "b7 or g18b"; git stash pop
PYTHONPATH=src pytest -q --tb=line                            # whole suite, complete
```

## Verdict up front

**Hunt verdict (before the fixes): she could be trusted to stay silent, and could
not be trusted to speak.** Post-fix verdict: **both halves hold in the sandbox** —
she stays silent on every text-only path and speaks only as Flare, from cached
audio, with every refusal and every cold cache reported. Two things remain open by
nature, not by neglect: the *ear-level* confirmation of the voice pin and the size
of the online boot-warm window, both on the needs-live list below.

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

**Status:** FIXED in `3d2b9e5` — the online cache key is now the cloud identity (`[gemini] voice` + `model_voice` + sample rate); guarded by `test_b7_voice_change_invalidates_the_online_cache`. The *ear* verdict still needs a live key: see needs-live item 2.
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

**Status:** FIXED in `3d2b9e5` — the local fallback in `_ack_path` is deleted; a missing Flare ack is silence + warning + re-warm; `test_b7c`.
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
~~`rm -rf ~/.local/share/assistant/voice-cache && assist voice warm`~~ — no longer needed: the fallback that made the stale local file playable is deleted (`3d2b9e5`), so an online box now re-warms on its own after any invalidation and `assist voice status` reports `ack_cache` instead of implying health.

### VB-4 · any config string silently becomes her voice

**Status:** FIXED in `3d2b9e5` — `[gemini] voice` must be in `[gemini] allowed_voices` (default `["Flare"]`) or she refuses and `assist doctor` FAILs; `test_a3`, `test_a3b`.
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

**Status:** FIXED in `3d2b9e5` + `d63f0de` — the dormant descriptor left the online key, and a miss now requests one warm cycle (never permanent silence); `test_b5b`, `test_b5d`, `test_b5e`.
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

**Status:** FIXED in `d63f0de` — the warm task is created before `serve()` and `_ack` queues behind it (bounded 2 s); `test_b5c`, `test_b5cb`. The *size* of the online window is needs-live (`test_b5f`, skipped by design).
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

**Status:** FIXED in `c1469cc` — `Daemon._command_gate` vetoes flagged / low-confidence transcripts (and any mutating intent at unknown confidence); `test_d13b`.
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

* **VB-5 — one thought, two nags.** **FIXED `c1469cc`** · `test_c9_blip_speech_does_not_rearm_the_ladder_for_a_second_nag` `transcribe.py:61` clears `_asked` on any
  frame over the RMS gate, so a breath, a key click, or her own playback bleed
  mid-pause re-arms the ladder and "Is that all?" fires again inside the same
  silence. The docstring promises otherwise. Repro: 1.2 s silence (ask) → one
  30 ms blip → 1.2 s silence → **asked twice**. Needs the (currently missing —
  see the note at the end) energy-VAD or a minimum re-arm window
  (e.g. speech sustained ≥250 ms) to tell a thought-resumes from a noise.
* **VB-6 — asked, then never closed.** **FIXED `c1469cc`** · `test_c9b_after_the_checkin_the_session_closes_after_grace` Item 9: asked once, *then closes after
  grace*. Nothing closes: the only exit is the user's own hotkey release, and
  the daemon's capture source is `speech_frames=100_000` (~50 min). Walk away
  mid-dictation and the mic, the `listening` state and the PipeWire stream stay
  held, silently. `SilenceLadder` has no grace concept at all.
* **VB-7 — rotation eats the head.** **FIXED `c1469cc`** (data-loss) · `test_d11b_rotation_on_a_long_utterance_keeps_every_word` `transcribe.py:247` does
  `collected.clear()` on a server GoAway, discarding finals already received;
  only the ≤30 s replay buffer is re-heard. Repro (replay window shrunk to
  0.12 s so it fits one test): 30-frame utterance, session 1 emits `w0 w3 w6`,
  transcript ends up `w24 w27…` — **the first words are gone**. Beyond ~30 s of
  dictation any rotation loses the beginning. Raw WAV survives, the transcript
  does not, and `assist events` already showed the words — so the user watches
  text evaporate. Fix: keep the earlier finals and append (dedupe by frame
  offset), or persist interim finals as they arrive.
* **VB-9 — doctor trusts a broken biometric.** **FIXED `b058ea2`** · `test_e14_corrupt_or_world_readable_voiceprint_fails_the_doctor` (6 cases) + `test_e14c` `cli.py:196-201` checks
  `voiceprint.exists()` only. A 0-byte, unparseable, wrong-schema or **0644**
  `voiceprint.json` prints `ok — present (path only…)`, while
  `load_voiceprint()` raises on the same file. Refuse loudly (and check mode
  `& 0o077`) instead of green-lighting an unusable, world-readable template.
* **VB-14 — the pill mislabels the voice** **FIXED `b058ea2`** · `test_a4c_waybar_line_is_truthful_in_every_mode` (`waybar.py:71`): it prints
  `voice: local <backend> / <voice_id>`, so **online** it reads
  "voice: local gemini-native-audio / Flare" (cloud audio, labelled local) and
  **offline** "voice: local none / none" — which reads as broken, not as the
  posture. The `voice status` *payload* is truthful (A.4 passes); only this
  label is stale. Pinned; LOW because it misinforms rather than misbehaves.
* **VB-10 — SIGKILL orphans the audio child.** **FIXED `b058ea2`** · `test_g18_kill_daemon_mid_playback_leaves_no_player_running` + `test_g18b` `tts.py:503` runs the player via
  `subprocess.run` with no `start_new_session`/process group, so a killed daemon
  leaves `pw-play` holding the sink. Proven with a real daemon subprocess and a
  real player: after `kill -9`, the player pid **11712 was still alive**. Same
  shape for `pw-record` (`capture.py:211`) → the mic stays claimed; the graceful
  path is fine (`aclose` → `terminate()` + `await wait()`, `capture.py:225-228`).
  Fix: `start_new_session=True` + a systemd user scope with
  `Delegate=yes`/`KillMode=control-group`, or track and kill children on exit.
* **VB-11 — a rejected double-press still speaks.** **FIXED `c1469cc`** · `test_g19_double_hotkey_acks_once` `daemon.py:412-414` answers
  the *loser* of the race with its own `on_it` ack, so one double-press sounds
  like two answers (measured: 2 plays across two starts, 3 including the
  release ack). The single-owner guard itself works — `note: "already
  listening"` and no second session — so this is wording, not correctness:
  the rejected press should return the note with no ack speech.
* **VB-12 — one diagnostic that lies by omission.** **OPEN (unpinned, LOW)** 0-byte audio offline raises
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

## FIXES — Gates A–D, in the order the gate rule required

Each gate went green before the next one started. Every fix converted its
strict-xfail pin into a passing regression, and every converted test was re-run
against the pre-fix source (a `git worktree` at `9b0e4dd` for Gates A/B, `git
stash` of the source files for C/D) to confirm it still fails there.

**Gate A — voice identity, before anything else is trusted (`3d2b9e5`)**

| Finding | What changed | Now guarded by |
| --- | --- | --- |
| VB-1 | `_cache_path` takes the *route's own audio identity*: `[gemini] voice` + `model_voice` + sample rate online, and voice/model/speaker/length_scale on the dormant local path. A voice or model change moves every path in both directions, so stale audio is not addressable under a new identity. | `test_b7_voice_change_invalidates_the_online_cache` |
| VB-3 | `_ack_path`'s "a warmed local copy beats silence" fallback is deleted, comment included. A missing Flare ack is silence + `warning` + `rewarm_needed`, and `cached_acks`/`ack_cache` cannot report health off a local file. | `test_b7c_local_audio_never_answers_an_online_ack` |
| VB-4 | `[gemini] voice` is validated against `[gemini] allowed_voices` (default `["Flare"]`) in `config.py`; a mismatch refuses at the route *and* at the transport, and `assist doctor` prints `VOICE IDENTITY REFUSED` as a **FAIL**. Precedence is documented in README + `config.toml.example`, and `legacy_selection_ignored_online` reports the inert `tts.selected_voice` row. | `test_a3_voice_is_pinned_and_the_precedence_is_documented`, `test_a3b_client_refuses_an_unapproved_voice_even_when_called_directly` |

**Gate B — she speaks when she should (`d63f0de`, with the key half in A)**

| Finding | What changed | Now guarded by |
| --- | --- | --- |
| VB-2 | A miss on a speaking route *is* the trigger: `request_rewarm` / `take_rewarm_request` / `warm_due`, consumed by the daemon after `_ack`, so the next press is audible. Never a permanent silent `cache_miss`; `voice status` + doctor state the cold cache. | `test_b5b`, `test_b5d_ack_miss_self_heals_within_one_warm_cycle`, `test_b5e_daemon_re_warms_after_a_miss` |
| VB-13 | `run()` creates the warm task **before** `serve(...)`, and `_ack` queues a would-be miss behind the in-flight warm through a bounded (2 s), pending-aware gate. `speech.warm` opens the gate, so `assist voice warm` stays the documented cure. | `test_b5c_boot_warm_starts_before_the_socket_serves`, `test_b5cb_early_acks_queue_behind_the_boot_warm` |

**Gate C — session behaviour (`c1469cc`)**

| Finding | What changed | Now guarded by |
| --- | --- | --- |
| VB-5 | Re-arming needs speech sustained ≥ `speech_resume_s` (0.4 s); a blip never nags twice, a real resumption still earns a new check-in. | `test_c9_blip_speech_does_not_rearm_the_ladder_for_a_second_nag` |
| VB-6 | After the check-in, `checkin_grace_s` (8 s) of continued silence closes the session: `session.grace_close`, a note, and the capture source released. | `test_c9b_after_the_checkin_the_session_closes_after_grace` |
| VB-7 (data-loss) | Rotation consumes only the GoAway markers; received finals are kept, and the replayed tail's echo is folded by suppressing an immediately repeated segment — no lost head, no doubled words. | `test_d11b_rotation_on_a_long_utterance_keeps_every_word` |
| VB-8 | `Daemon._command_gate` between transcript and ladder: `flagged`, `confidence < command_min_confidence` (0.85), or unknown confidence **for a mutating intent** → nothing is routed; the veto reports the text, the numbers, the intent and "Not executed". | `test_d13b_low_confidence_command_words_never_execute` |
| VB-11 | The refused press gets no ack at all (`suppressed: "already listening — no second ack"`). | `test_g19_double_hotkey_acks_once` |

**Gate D — integrity and surfaces (`b058ea2`)**

| Finding | What changed | Now guarded by |
| --- | --- | --- |
| VB-9 | `voicetest.voiceprint_health()`: size, JSON, schema, centroid/dimension agreement, finite values, configured dimension + model, and mode `0600`. Wrong = doctor **FAIL** with the cure; absent = warning; `enroll` chmods as it writes. | `test_e14_…` (6 parametrised cases), `test_e14c_…` |
| VB-10 | `assistant/proc.py`: player and recorder spawn with `PR_SET_PDEATHSIG` in their own session; because that kernel promise does not hold for every thread arrangement (this sandbox proves it), the daemon also sweeps parentless audio children **before it serves**, `assist doctor` FAILs on `orphaned audio` naming the pids, and `assist voice cleanup` works with the daemon dead. A custom `[tts] player` is part of the match list. | `test_g18_kill_daemon_mid_playback_leaves_no_player_running`, `test_g18b_the_sweep_names_a_parentless_audio_child` |
| VB-14 | `waybar.format_voice_line()`: cloud says cloud, the deliberately un-dormanted path says local, silence says silent and why. | `test_a4c_waybar_line_is_truthful_in_every_mode` |

Two shipped contract changes were made *deliberately* and are commented in place:
`test_silence_ladder_asks_once_per_segment` (phase 1 — a single frame no longer
re-arms) and the phase-8 offline command (a 0.30-confidence local transcript is
**refused**, transcript kept, cloud redo queued). One test-integrity fix came out
of Gate C: `test_g19_double_hotkey_acks_once` had carried the clock-jump/rotation
body under the wrong name, with the VB-11 marker hiding a fixture too short to
cross the age cap — it is now `test_g20_clock_jump_does_not_fire_and_the_rotation_cap_holds`,
with a cap it really crosses, and the VB-11 repro is the real double-press test.
The `Session` fake also gained the `turn_complete` the real transport sends, which
removed a 15 s stall from every session test: whole-suite time 73 s → 32 s.

## needs-live list — parked, not faked

1. **VB-13 online warm window** — time `assist voice warm` with a real key:
   `GEMINI_MODE=live GEMINI_API_KEY=… PYTHONPATH=src python -m assistant.cli
   voice warm`, and press the hotkey immediately after `systemctl --user restart
   assistant` to see whether the first ack is silent.
2. **VB-1/VB-4 by ear (still required after the fix)** — the cache-key half is
   proven in the sandbox (`test_b7`: the file paths move with the identity, so a
   stale clip *cannot* be served), but only ears can settle the sound. With a
   real key: `assist voice status` → note the acks; set
   `[gemini] voice = "Kore"` **plus** `[gemini] allowed_voices = ["Flare", "Kore"]`;
   `assist doctor` (must stay green), `assist voice warm`, press the hotkey —
   the ack must sound like the NEW voice immediately, and setting the voice back
   must sound like Flare again with no re-render (`cached: true`). Remove
   `Kore` from `allowed_voices` while leaving `voice = "Kore"`: she must go
   silent and the doctor must FAIL — the pin is the fix, so a *silent* refusal is
   a pass, and only the ear test can prove the audio itself changed.
3. **VB-10 with real PipeWire** — `kill -9` the daemon mid-`pw-play` and
   mid-dictation; check `pw-cli ls Node` for the leaked stream and
   `pactl list source-outputs` for the held mic. On a normal Fedora kernel
   PR_SET_PDEATHSIG should kill the child outright; the sandbox kernel does not
   deliver it for the threaded spawn, which is why the sweep exists. Confirm both
   halves: after `kill -9`, `assist doctor` must name any survivor and
   `assist voice cleanup` (or a plain restart) must free the sink/mic.
4. **VB-5/VB-6 acoustics** — narration with real 0.6/1.5/3 s pauses, a cough
   after the check-in, and walking away mid-session. The double-nag and the
   held-mic behaviour are fixed at the ladder level (`speech_resume_s`,
   `checkin_grace_s`); what hardware decides is whether those two numbers are
   *comfortable* — raise `checkin_grace_s` if she closes while you are still
   thinking, lower `speech_resume_s` if a genuine restart of a sentence fails to
   re-arm. Log first, tune second (E.14).
5. **E.14 wake word + voiceprint** — no wake-word activation exists in the
   runtime (`voicetest.py` is the offline harness only), so "other speakers / TV
   / playback must not wake her" and "never fall back to any voice" are true
   **by absence**, not by a tested gate. Needs: enrolment, false-trigger rate
   over a day, and the `OpenWakeWordScorer` path on the Fedora box.
6. **D.13 real garbage audio** — silence-only, music, TV speech, clipped
   screaming through the *actual* ASR, then `assist dictate --command` on a TV
   saying "undo." The structural gate now exists (`command_min_confidence`,
   `flagged`, mutating-intent veto) and `test_d13b` proves the veto; what only
   hardware can answer is whether real ASR reports confidence *high enough to be
   trusted* for a TV voice — if it reports 0.95 on a mumble, the number is the
   thing to fix, not the gate.
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
