#!/usr/bin/env python3
"""W1 — file-transcription leg probe (owner scene, paste-safe).

Scene-7 work order (2026-10-31), item W1: the file leg heard 7 chars of a
29-char sentence (session 94129ec0e4b5, `fallback.outcome landed … 7
chars`). This probe replays kept wavs through the leg EXACTLY as
production invokes it — `asr.transcribe_file(config, client, path)`, the
same call the dictate gate makes — and then runs one raw SDK pass in the
same wire shape (`files.upload` + `generate_content([prompt, file])`, per
the generateContent Files docs fetched 2026-10-31) to print the response
metadata production discards: finish_reason, usage_metadata, candidate
parts, raw text + char count. That is the truncation discriminator:

  finish_reason=MAX_TOKENS        -> output truncation (gen-config fix)
  finish_reason=STOP with a stump -> the model heard a stump (file
                                     processing / encoding / rate)
  usage_metadata                 -> what the API actually billed/consumed

Sections printed per wav:
  1. WAV facts     — stdlib-wave header values + raw header hex + a
                     header/data consistency check (header/rate question).
  2. Production    — model id, fallback chain order, and the exact prompt
                     (imported from gemini_client.batch_transcription_prompt,
                     so the printed prompt IS production's prompt).
  3. File leg      — asr.transcribe_file result: raw text + char count.
  4. Raw SDK pass  — the full response metadata (skipped in mock mode).

Paste-safe by construction: the API key is never printed, logged, or
interpolated anywhere in this file. Paste the whole output back.

MINI ORDER M-2 (2026-10-31) — arm C: the same production wire
(`files.upload` + `generate_content([prompt, file])`) retried on the
REGISTRY files model (`gemini-3.5-transcribe`, `--model` overrides),
printed in the SAME shape as section 4 (raw text + char count,
finish_reason, usage_metadata). The W1 root-cause record named registry
drift as the suspect: production's leg ran `gemini-3.5-flash-lite` (a
chat model) while the registry pins the files route to
`gemini-3.5-transcribe`. Arm C is the causal discriminator — same wav,
same wire, only the model differs. Section 3/4 stay on PRODUCTION's
resolved model (the root-cause record); section 5 is arm C.

Usage (owner runtime, GEMINI_API_KEY exported):
  uv run python scripts/file_leg_probe.py
  uv run python scripts/file_leg_probe.py --wav /path/to/one.wav
  uv run python scripts/file_leg_probe.py --model gemini-3.5-transcribe

Default wavs (resolved under ~/.local/share/assistant/audio then ./audio):
  20261031-145603-94129e.wav   (W1's stump capture)
  20261027-064450-77cc4e.wav   (second known-good sample)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import wave

DEFAULT_WAV_NAMES = (
    "20261031-145603-94129e.wav",
    "20261027-064450-77cc4e.wav",
)


def _find_default_wavs() -> list[str]:
    """Kept wavs live in the daemon's audio dir on the owner's machine."""
    found: list[str] = []
    for name in DEFAULT_WAV_NAMES:
        candidates = [
            os.path.join(os.path.expanduser("~"), ".local", "share",
                         "assistant", "audio", name),
            os.path.join("audio", name),
        ]
        found.append(next((p for p in candidates if os.path.exists(p)),
                          candidates[0]))
    return found


def wav_facts(path: str) -> dict:
    """Header facts + a header/data consistency check — no network."""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        header = fh.read(44)
    with wave.open(path, "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.getnframes()
    expected = 44 + frames * channels * width
    return {
        "path": path,
        "size_bytes": size,
        "header_hex": header.hex(),
        "channels": channels,
        "sampwidth_bits": width * 8,
        "rate_hz": rate,
        "frames": frames,
        "duration_s": round(frames / rate, 3) if rate else None,
        "expected_size_bytes": expected,
        "consistent": size == expected,
        "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest()[:16],
    }


def format_wav_facts(facts: dict) -> str:
    lines = [
        f"  path: {facts['path']}",
        (f"  size: {facts['size_bytes']} bytes "
         f"(header-declared payload would be {facts['expected_size_bytes']})"),
        f"  header (first 44 bytes): {facts['header_hex']}",
        (f"  format: {facts['rate_hz']} Hz, {facts['channels']}-ch, "
         f"{facts['sampwidth_bits']}-bit, {facts['frames']} frames "
         f"= {facts['duration_s']}s"),
        f"  header/data consistent: {facts['consistent']}",
        f"  sha256[:16]: {facts['sha256']}",
    ]
    return "\n".join(lines)


def production_facts(config, client) -> dict:
    """What the leg sends: model, chain order, exact prompt."""
    from assistant import asr
    from assistant.gemini_client import batch_transcription_prompt

    languages = asr.configured_languages(config)
    chain = [b.name for b in asr.batch_chain(config, client)]
    return {
        "model": config.model_for_role("transcribe_batch"),
        "chain": chain,
        "languages": languages,
        "prompt": batch_transcription_prompt(languages[0]),
    }


def raw_sdk_pass(sdk, model: str, prompt: str, path: str, *, printer=print) -> None:
    """One raw wire pass: `files.upload` + `generate_content([prompt, file])`,
    printing the response metadata production discards (finish_reason,
    usage_metadata, candidate parts, raw text + char count). This is the
    output shape sections 4 (production model) and 5 (arm C) share —
    same wire, same fields, only the model differs."""
    try:
        uploaded = sdk.files.upload(file=str(path))
        response = sdk.models.generate_content(
            model=model, contents=[prompt, uploaded])
        text = response.text or ""
        printer(f"  model: {model}")
        printer(f"  raw model text ({len(text)} chars): {text!r}")
        candidates = getattr(response, "candidates", None) or []
        for i, cand in enumerate(candidates):
            printer(f"  candidate[{i}] finish_reason="
                    f"{getattr(cand, 'finish_reason', None)}")
            content = getattr(cand, "content", None)
            for j, part in enumerate(getattr(content, "parts", None) or []):
                printer(f"    part[{j}]: {repr(part)[:400]}")
        usage = getattr(response, "usage_metadata", None)
        printer(f"  usage_metadata: {usage}")
        printer("  reading: finish_reason=MAX_TOKENS -> truncation; "
                "STOP with a stump -> the model heard a stump")
    except Exception as exc:
        printer(f"  raw pass raised: {type(exc).__name__}: {exc}")


def run(config, client, wav_paths: list[str], *, printer=print,
        raw_pass: bool = True, arm_c_model: str | None = None) -> int:
    from assistant import asr

    printer("=== W1 file-leg probe (paste-safe; the key is never printed) ===")
    printer(f"GEMINI_API_KEY: {'present' if os.environ.get('GEMINI_API_KEY') else 'MISSING'}")
    facts = production_facts(config, client)
    printer(f"production model: {facts['model']}")
    printer(f"production chain: {facts['chain']}")
    printer(f"production languages: {facts['languages']}")
    printer(f"production prompt (verbatim): {facts['prompt']!r}")
    if arm_c_model:
        printer(f"arm C model (section 5): {arm_c_model}")

    sdk = getattr(getattr(client, "_transport", None), "_client", None)
    for path in wav_paths:
        printer(f"\n--- wav: {path} ---")
        if not os.path.exists(path):
            printer("  MISSING on disk — pass --wav explicitly")
            continue
        printer("section 1 — WAV facts:")
        printer(format_wav_facts(wav_facts(path)))

        printer("section 3 — production file leg (asr.transcribe_file):")
        try:
            transcript = asr.transcribe_file(config, client, path)
            text = transcript.text or ""
            printer(f"  raw model text ({len(text)} chars): {text!r}")
            printer(f"  backend={transcript.backend} language={transcript.language!r} "
                    f"confidence={transcript.confidence} "
                    f"language_ok={transcript.language_ok}")
        except Exception as exc:
            printer(f"  leg raised: {type(exc).__name__}: {exc}")

        if raw_pass and sdk is not None:
            printer("section 4 — raw SDK pass (production wire shape; "
                    "response metadata production discards):")
            raw_sdk_pass(sdk, facts["model"], facts["prompt"], path,
                         printer=printer)
        elif raw_pass:
            printer("section 4 — raw SDK pass skipped: no SDK transport "
                    "(mock/fixture mode — the raw pass needs the live client)")
        else:
            printer("section 4 — raw SDK pass skipped (--no-raw)")
        if raw_pass and sdk is not None and arm_c_model:
            printer("section 5 — arm C (registry files model; M-2 causal "
                    "discriminator — same wav, same wire, only the model "
                    "differs):")
            raw_sdk_pass(sdk, arm_c_model, facts["prompt"], path,
                         printer=printer)
        elif raw_pass and arm_c_model:
            printer("section 5 — arm C skipped: no SDK transport "
                    "(mock/fixture mode — the raw pass needs the live client)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="W1 file-leg probe (see module docstring; paste-safe)")
    parser.add_argument("--wav", action="append", default=None,
                        help="wav to replay (repeatable; default: the two "
                             "known kept wavs)")
    parser.add_argument("--no-raw", action="store_true",
                        help="skip the raw SDK passes (file-leg call only)")
    parser.add_argument("--model", default=None,
                        help="arm C model (section 5; default: the registry "
                             "files model gemini-3.5-transcribe)")
    args = parser.parse_args(argv)

    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set — export it first "
              "(the key is never printed)", file=sys.stderr)
        return 2

    from assistant.config import load_config
    from assistant.gemini_client import GeminiClient
    from assistant.store import Store

    config = load_config()
    store = Store(config.state_dir / "file-leg-probe.db")
    try:
        from assistant.model_registry import EVENT_TRANSCRIPTION

        client = GeminiClient(config, store)
        return run(config, client,
                   args.wav or _find_default_wavs(),
                   raw_pass=not args.no_raw,
                   arm_c_model=args.model or EVENT_TRANSCRIPTION)
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
