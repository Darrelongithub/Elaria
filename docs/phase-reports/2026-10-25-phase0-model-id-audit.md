# Phase 0 — model-ID audit (step zero, before any code)

Date: 2026-10-25 · Branch: `arena/c2a7085d-elaria` · Base: `ed20344`
Authority: MASTER BUILD PROMPT — ELARIA, BLUEPRINT V2 WIRING SPEC (2026-10-25)
Sandbox: headless container (not the Fedora laptop). No API key, no Hyprland,
no PipeWire, no quickshell. CPython 3.11 here vs 3.14 on the laptop. Everything
below is reproducible with the commands shown; nothing here is a hardware claim.

Baseline before any change: `uv run pytest -q` → **1780 passed, 6 skipped**
[TESTED-ONLY] — matches the INVARIANTS baseline exactly.

---

## DONE

Full dump of every model ID in every config file and code path, compared
against the §4.1 registry and the forbidden list.

### The retired ID (the reply-regression question)

`gemini-2.5-flash-lite` — **0 occurrences anywhere in the repository**, code,
config, tests, fixtures, docs or history-of-docs:

```
grep -rnoE "gemini-2\.5-flash-lite[a-z0-9.\-]*" .   # (repo tree) → no hits
```

[TESTED-ONLY] The retired ID is *not* named by any repo config default or code
path. What the reply/chat path actually calls today (traced end to end):

| step | evidence | value |
| --- | --- | --- |
| reply generation | `daemon.py` `_generate` → `client.generate("chat", …)` | role `chat` |
| role → model | `config.py` `model_for_role("chat")` → `gemini.model_chat` | `gemini-flash-latest` |
| escalation ladder | `config.py` `escalation_ladder` | `gemini-flash-lite-latest`, `gemini-flash-latest` |
| housekeeping roles | `model_default` / `model_organise` / `model_cleanup` | `gemini-flash-lite-latest` |

[UNVERIFIED → laptop] Root-cause candidate stands, one level deeper: these are
`-latest` **aliases**. If the alias `gemini-flash-latest` (or the owner's live
`~/.config/assistant/config.toml`, which is not in this repo) resolves
server-side to the retired `gemini-2.5-flash-lite`, every reply call dies after
the 2026-10-20 retirement while PTT transcription (pinned
`gemini-3.5-transcribe-live`) keeps working — exactly the observed “she
sometimes never replies **after PTT**” shape. This cannot be proven from the
sandbox; it is proven or refuted by `assist cost` failure rows / a live call on
the laptop.

### Diff against the §4.1 registry (config + code, repo tree)

| §4.1 registry entry | pinned ID | found in repo | verdict |
| --- | --- | --- | --- |
| Voice conversation | `gemini-3.8-live` | `DEFAULT_VOICE_MODEL`, `[gemini] gemini_voice_model` | **match** |
| PTT/dictation transcription | `gemini-3.5-transcribe-live` | `model_transcribe_live` | **match** |
| Event segments / saved WAV | `gemini-3.5-transcribe` | `model_transcribe_batch` | **match** |
| File fallback | `gemini-3.5-flash-lite` | *absent* — no fallback key exists | **gap** |
| Chat/intent (cap 400 RPD) | `gemini-3.5-flash-lite` | `model_chat = gemini-flash-latest` (alias) | **defect** |
| Chat/intent housekeeping | `gemini-3.5-flash-lite` (implied) | `model_default/organise/cleanup = gemini-flash-lite-latest` (alias) | **defect** |
| Escalation | `gemini-3.8-flash` | `escalation_ladder = [gemini-flash-lite-latest, gemini-flash-latest]` | **defect** |
| Cached TTS | `gemini-3.8-flash-lite-tts` | *absent* — speech rides `gemini-3.8-live` native audio (interim owner decision 2026-10-20) | **gap — voice-identity adjacent, WP1 with the owner's ear** |
| Ack/earcon | local cached WAV | `ui/sounds/knock.wav` exists (knock only); PTT ack path is cached native-audio WAVs | **partial — WP1 orders the earcon before capture** |

Quota-table note: `[quota.models.flash-lite] rpd = 500` today; §4.1 says
“free ~500 RPD; **config cap 400**”. The chat cap is a config change bundled
into the pin fix.

### Forbidden list scan

| forbidden ID | occurrences (code/config/tests) | role of the occurrence | docs (prose history) |
| --- | --- | --- | --- |
| `gemini-2.5-flash-lite` | **0** | — | 0 |
| `gemini-2.5-flash-native-audio-preview-12-2025` | **0** | — | 0 |
| `gemini-2.5-flash-preview-tts` | 5 | `config.py:109` `REMOVED_TTS_MODEL` **guard constant** (used to *reject* the legacy default), `config.py:232` comment, `voice_catalogue.py:6` docstring, 2 negative tests asserting rejection | 5 mentions (BUGHUNT.md, README.md, bugs.md) |
| `gemini-3.1-flash-live-preview` | 8 | `config.py:101` comment, `voice_catalogues.json` historical catalogue data (key + source URL), 3 test fixtures (precedence logic), 1 negative assertion | 0 |

[TESTED-ONLY] No forbidden ID is configured as an active model or passed to the
API by any code path. The occurrences are: guard constants (naming the enemy to
reject it), historical catalogue data, negative-test fixtures, comments.

### Other IDs in code (not registry, not forbidden — recorded for the doctor scan)

- `gemini-native-audio`, `gemini-interim`, `gemini-queued`,
  `gemini-unparsed-command` — internal labels/ledger pseudo-models, never sent
  to the API. Not model IDs.
- Test fixtures only: `gemini-live-2.5-flash`, `gemini-3.5-transcribe-live-preview`,
  `gemini-2.5-pro-preview-tts`, `gemini-pro`, `gemini-3.8-flash` (as a fake
  models.list entry).
- `fixtures/61ee…json` records `gemini-flash-latest` (sample fixture; follows
  the pin fix).

### Machine facts (must be confirmed on the laptop — not reachable from sandbox)

- `rpm -q hyprland` — exact version [UNVERIFIED], owner action in the gate
  checklist. WP3 promotion trigger watches for 0.57 in Fedora 44 repos.
- quickshell 0.2.1 frozen snapshot [UNVERIFIED]; not upgradeable.
- Mic1 capture node presence/non-silence [UNVERIFIED] — doctor check lands in
  WP0 and is run on the laptop.

---

## DEFECTS FOUND (logged, not fixed)

1. **Reply/chat path runs on `-latest` aliases** (`gemini-flash-latest`,
   `gemini-flash-lite-latest`) instead of the §4.1 pinned IDs. Alias policy
   allows `-latest` only for non-identity chat experimentation; the reply path
   is identity-critical. Root-cause candidate for the reply regression (above).
   Fix proposed below — **waiting on owner go** (Phase 0 gate).
2. **`[quota]` chat cap 500 vs §4.1 “config cap 400”** — rides along with the
   pin fix.
3. **No file-fallback key** (`gemini-3.5-flash-lite`) and **no cached-TTS model
   key** (`gemini-3.8-flash-lite-tts`) exist yet. WP1/WP5 scope.
4. **Forbidden IDs named in guard constants / catalogue history / negative
   tests / prose docs** (table above). Tension with “doctor hard-fails if any
   appear anywhere” — see OPEN QUESTIONS.
5. **`HANDOFF.md` does not exist** although the master prompt says to read it
   first and §6 mandates maintaining it. The repo's state lives in README.md /
   docs/console-home/hardware-gate.md today.
6. **`elaria-ladder` is referenced** (docs/console-home/hardware-gate.md, tests)
   **but ships nowhere in the repo** — rung semantics (A–E) must be
   reconstructed from the wiring spec §4.8 + the gate doc's E definition during
   WP0 productisation. [UNVERIFIED what the owner's ad-hoc script checked]
7. Sandbox machine mismatch: CPython 3.11 here vs 3.14 on the laptop; `uv`
   had to be bootstrapped. Test baseline is still exactly 1,780/6 — the
   invariant holds, but `uv sync` on 3.14 remains [UNVERIFIED] until the
   laptop runs it.

## NEXT GATE

**Update (2026-10-25, later same day): the owner approved the full §4.1 pin
set in the accompanying question round, and it has been applied** (model pins,
`model_file_fallback`, escalation ladder, chat RPD config cap 400, doctor
registry/forbidden-ID scan). Applied as part of the WP0 EYES change set; see
`2026-10-25-wp0-eyes.md` for the evidence. WP0 EYES follows; its gate is the
owner's hardware scene.

## OPEN QUESTIONS

1. **Pin fix scope** (the Phase 0 WAIT): the retired ID is not literally in the
   repo, so “the one-line pin fix” has two candidate shapes — see the owner
   question accompanying this report.
2. **Forbidden-ID scan semantics**: “doctor hard-fails if any appear anywhere”
   read literally makes the doctor's own scan list, `REMOVED_TTS_MODEL`
   guard, negative tests and prose history self-trigger. Proposed reading:
   hard-fail when a forbidden ID is **configured or invoked** (any role, any
   config file including the owner's live one); warn-and-report on code/comment
   /history occurrences. Needs the owner's word before WP0's doctor scan is
   built on it.
3. **Sandbox pre-gate vs phase scope**: the §1 pre-gates (qmllint failing on
   undefined-id) currently fail on the known `eventSnap` defect, whose fix is
   WP2's named scope. Also, this sandbox has no quickshell/Qt toolchain, so
   qmllint cannot run here at all. Proposed reading: the WP0 hardware scene
   proceeds with the pre-gate recorded BLOCKED-known (WP2 owns the fix; the
   WP0 scene touches daemon/logs/ladder, not the QML). Needs the owner's word.
4. **Cached-TTS model vs interim voice posture**: §4.1 names
   `gemini-3.8-flash-lite-tts` for cached TTS, but the owner's 2026-10-20
   decision routes all speech through `gemini-3.8-live` native audio (Flare).
   Confirm this is a WP1 change with the owner's ear (it is a voice-identity
   adjacent route change), not part of the pin fix.
