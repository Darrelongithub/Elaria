# Phase report — voice-chain resilience, window findings order v1 (2026-11-02)

Date: 2026-11-02 · Lane: mainline · Branch: `arena/c2a7085d-elaria` ·
Base: `0320c11` · Authority: window findings order v1 (design chat,
2026-11-02) + the owner's protected-scope grant (§2 of the order).
Sandbox: headless container (not the Fedora laptop); everything below
is fakes-and-journals unless tagged otherwise. No PR, nothing merged;
merge hold era continues.

## Branch + commits

| commit | item | files |
| --- | --- | --- |
| `ff529f6` | F1 av pin | `pyproject.toml`, `uv.lock` |
| `ee3514a` | F2 quota knowledge + pacing | `src/assistant/model_registry.py`, `src/assistant/gemini_client.py` |
| `8ed363a` | F3 empty-leg semantics | `src/assistant/journal_log.py`, `src/assistant/asr.py`, `src/assistant/transcribe.py`, `scripts/file_leg_probe.py` |
| `305f4ef` | pins | `tests/test_voice_chain_resilience.py` |
| (this commit) | scene card + report | `docs/scene-cards/2026-11-02-voice-chain-resilience.md`, this file |

## Gate outputs (verbatim)

```
$ uv run pytest -q
2001 passed, 6 skipped in 168.63s (0:02:48)

$ uv run ruff check .
All checks passed!
```

Local runner only — no automated CI is claimed. Baseline at `0320c11`
was 1,982/6; +19 = the resilience pins.

## Diffstat (9 files, +751 / −73)

```
 pyproject.toml                       |  12 +
 scripts/file_leg_probe.py            |   4 +-
 src/assistant/asr.py                 |  30 +-
 src/assistant/gemini_client.py       |  92 ++++++-
 src/assistant/journal_log.py         |  52 ++++
 src/assistant/model_registry.py      |  20 ++
 src/assistant/transcribe.py          |  49 +++-
 tests/test_voice_chain_resilience.py | 518 +++++++++++++++++++++
 uv.lock                              |  47 +---
```

## Protected-file touches, itemized against §2 grants

| file | grant | touch |
| --- | --- | --- |
| `pyproject.toml` | F1 ONLY (av / faster-whisper dependency pins) | **touched — within grant**: one dependency constraint `"av>=15.1,<19"` + its justification comment (12 lines, `dependencies` block only). `uv.lock` rides the same dependency-pin change (its lockfile half; re-resolves av 18.1.0). Nothing else in either file. |
| `daemon.py` | F3a/F3b/F3c only | **NOT touched** (the fixes live in transcribe.py / asr.py). |
| `transcribe.py` | F3a/F3b/F3c only | **touched — within grant**, 12 hunks, all named fixes: F3a error_text at the failure surfaces (the `_await_lifecycle` timeout branch that produced tonight's `error ""`, `fallback.outcome` error detail, `fallback_error_emit` payloads, wav-close/connect ledger errors); F3b `session_id` pass-through at the leg call sites; F3c `fallback_class` tracking + `transcription.starvation` at the gate + file-service session id. No other change (the M-4 early-dispatch code is untouched). |
| `live_client.py` | frozen | NOT touched. |
| `cli.py` | frozen | NOT touched (doctor's quota shape line stays `RPM n/a` until the owner-side config line below — the shape reads `[quota]`). |
| `config.py` | frozen | NOT touched (the transcribe-batch quota row keeps `rpm=None`; the registry fallback carries the figure). |
| `ladder.py` | frozen | NOT touched. |
| `HANDOFF.md` | frozen | NOT touched (its scene-7 addendum still points at the mini-M state; the next unfrozen order should fold this one in). |

Unlisted files touched under standing discipline (additive): `asr.py`,
`gemini_client.py`, `journal_log.py`, `model_registry.py`,
`scripts/file_leg_probe.py` (2 lines: never-empty leg-raised text),
`tests/test_voice_chain_resilience.py` (new).

## F1 — dependency choice justification

- **Bump faster-whisper is impossible:** 1.2.1 is the LATEST release —
  the PyPI simple index (checked 2026-11-02) shows nothing newer, and
  1.2.1's `audio.py` passes `metadata_errors="ignore"` unconditionally.
  There is no av-19-compatible faster-whisper to move to. [PyPI-VERIFIED]
- **The wall is exactly 19.0.0:** sdist source greps —
  `av-18.1.0/av/container/core.py` `def open(..., metadata_encoding="utf-8",
  metadata_errors="strict", ...)`; `av-19.0.2`'s `av.open` carries
  NEITHER kwarg. The owner's `TypeError: open() got an unexpected
  keyword argument 'metadata_errors'` matches 19.0.2 exactly.
  [PyPI-VERIFIED, sdist source]
- **The pin `av>=15.1,<19` wheels both targets:** 18.1.0 ships
  `cp311-abi3-manylinux_2_28_x86_64` (sandbox CPython 3.11) and
  `cp314-manylinux_2_28_x86_64` (owner CPython 3.14) — plain `uv sync`,
  no source builds, no FFmpeg-dev toolchain. cp314 wheels start at
  15.1.0 (the floor). [PyPI-VERIFIED, wheel index]
- **Behavioral proof under the pin** [TESTED-ONLY]: `av.open(...,
  metadata_errors="ignore")` decodes a wav on the resolved 18.1.0; the
  W3 compat pre-check (`_faster_whisper_compat`) returns ok. Acceptance
  is scene S1 (owner hardware, both standing wavs).

No collateral dependency drift: only the av constraint changed;
`faster-whisper>=1.1` untouched; `uv lock` re-resolved av 18.1.0.

## F2 — where the 3 RPM lives + owner config line

Knowledge homes (the order's list, builder's pick under the freeze):
1. **Registry** (`model_registry.VERIFIED_FREE_TIER_RPM`) — the figure
   with its 429 provenance (quotaValue 3, retryDelay 36s, verbatim).
2. **Enforcement** (`gemini_client`) — `rpm_for` resolves an rpm-less
   config row to the registry figure before the flash-derived alias
   default; the wire seams (`_sdk_transcribe`, `transcribe_batch_async`
   — the meeting path shares the quota) acquire the per-model limiter
   before sending. Retry-after: a 429's retryDelay is parsed and held;
   later sends wait it out or refuse; the 429 text surfaces verbatim.
3. **Doctor's shape line** — cli.py frozen; the shape reads `[quota]`:

   **Owner-facing config line (owner's file, owner's edit):**

   ```toml
   [quota.models.transcribe-batch]
   rpm = 3
   ```

   With that line doctor shows `transcribe-batch: 3 RPM / … / 25 RPD`
   and enforcement agrees from config; without it the registry fallback
   still paces at 3.

Pacing semantics: 3 sends / 60 s window; a slot wait beyond 2 s would
eat the leg's 8 s budget — the leg refuses fast and the chain falls to
local. [TESTED-ONLY]; acceptance = scene S3.

## F3 — tonight's shapes, replayed

The starved turn's `error: ""` is now explained and closed: the W6
speculative leg wraps `asyncio.wait_for(..., 8.0)` — `wait_for` raises a
**message-less TimeoutError** and the failure line formatted `str(exc)`.
F3a makes every failure surface name the class. The four acceptance
shapes replay green in `tests/test_voice_chain_resilience.py`
[TESTED-ONLY]: 200-empty → local lands (class-mark + `fallback.outcome
landed`, no starvation); 429 → class-marked with the reason → local
lands; live-final-missing + all-backends-failed → marks →
`fallback.outcome` carrying `all ASR backends failed — <per-backend
reasons>` → `transcription.starvation outcome=error` (wav kept,
retained for retry) → `transcription.deferred`; the message-less
timeout replay → `fallback.outcome timeout` + `starvation outcome=timeout`
+ the lifecycle failure line naming `TimeoutError`. No empty error
string appears in any sequence; the M-5 stump tests are unaffected
(suite-wide green).

## Scene card

`docs/scene-cards/2026-11-02-voice-chain-resilience.md` — S1 (terminal:
probe sections 3 land whole sentences via `backend=local`,
`local_asr.degraded` GONE), S2 (ears then terminal: she ANSWERS on the
local-whisper chain; legible journal greps; clause-3 re-measure
candidate — measured, not promised), S3 (leg call count + 429s).
Unscheduled until the design chat slots it.

## DEFECTS FOUND

- **[TESTED-ONLY]** S1's probe raw passes (sections 4/5) remain UNPACED
  diagnostic sends on the same 3-RPM quota — a 429 printed there is the
  F2 surface itself (retryDelay included), not a leg-pacing failure.
  The scene card says so explicitly; if the design chat wants the probe
  paced too, it is a small script-side change outside this order's
  named scope.
- **[UNVERIFIED]** The 2 s pacing-decline constant (`PACE_MAX_WAIT_S`)
  is a design judgment (decline rather than eat the 8 s leg budget);
  the scene's numbers may justify tuning it.
- **[TESTED-ONLY]** `transcription.backend` marks carry the failure
  reason text (diagnostic, e.g. the 429 body) — never transcript text;
  chars+sha16 only where transcript text exists. If the reason text
  ever risks carrying owner words (a backend that echoes input in its
  error), that needs its own redaction pass — named, not assumed fixed.

## NEXT GATE

Design schedules the S1/S2/S3 scene (≤30 min daylight, owner runs).
Green = the chain survives Google's silence; then gate v2-AMENDED
clause (ii) has production-path whole sentences (local leg) and
clause 3 re-measures `release_to_first_slice_s` on the answering chain.

## OPEN QUESTIONS

None beyond the DEFECTS items — the order was self-contained and R1–R8
stayed settled. HANDOFF.md remains frozen by §2; its mini-M addendum is
one order stale and should be folded in when a future order unfreezes it.
