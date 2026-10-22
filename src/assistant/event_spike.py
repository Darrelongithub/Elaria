"""§0 Step 0 spike — BLOCKING before any queue tuning (Blueprint v2 §0).

One closed ~10-minute WAV pushed through the transcribe-live route AS A
BATCH CALL. Three numbers recorded: (a) full transcript yes/no, (b) tokens
consumed for the WAV (real figure, never the 32 tok/s estimate), (c) wall-
clock latency. Exactly one decision-table row applies afterwards:

  1  live batched the WAV, tokens/segment < ~12K   → transcribe-live, 10 min
  2  live works but tokens/segment > ~12K          → transcribe-live, shortened
  3  live cannot batch a closed WAV (or ambiguous) → batch (25/day), 30 min,
     speaker switches log inline markers and do NOT flush

"If the spike is ambiguous, default to the third row: it is the proven
engine." A run without a live API key (mock/record fixtures, estimated
tokens) is ambiguous by construction — row 3. Nothing downstream is built
on assumption: `docs/event-spike.json` holds the measured record.
"""

from __future__ import annotations

import json
import math
import struct
import time
from pathlib import Path

# Row-2 threshold and the live-route TPM ceiling from [quota] (§0 table).
TOKENS_ROW1_MAX = 12_000
TRANSCRIBE_LIVE_TPM = 20_000
TPM_HEADROOM = 0.7


def decide(result: dict) -> dict:
    """Apply the §0 decision table. Ambiguous → row 3, always."""
    tokens = result.get("tokens")
    measured = bool(result.get("tokens_measured"))
    live_ok = bool(result.get("live_ok"))
    full = bool(result.get("full_transcript"))
    if live_ok and full and measured and tokens is not None and tokens < TOKENS_ROW1_MAX:
        return {"row": 1, "route": "transcribe-live", "segment_minutes": 10,
                "switch_flush": True,
                "reason": ("live route returned a full transcript for the closed WAV "
                           f"at {tokens} tokens/segment (< ~{TOKENS_ROW1_MAX:,})")}
    if live_ok and full and measured and tokens is not None:
        # Shorten to fit 20K TPM with headroom for one retry: worst case two
        # submissions land in the same rolling minute.
        minutes = max(1, min(9, int(10 * (TRANSCRIBE_LIVE_TPM * TPM_HEADROOM / 2) / tokens)))
        return {"row": 2, "route": "transcribe-live", "segment_minutes": minutes,
                "switch_flush": True,
                "reason": (f"live route works but {tokens} tokens/segment exceeds "
                           f"~{TOKENS_ROW1_MAX:,} — shortened to {minutes} min segments "
                           "to fit 20K TPM with headroom for one retry")}
    return {"row": 3, "route": "batch", "segment_minutes": 30, "switch_flush": False,
            "reason": ("live route cannot batch a closed WAV, or the spike is "
                       "ambiguous (no measured token figure) — defaulting to the "
                       "third row: the proven batch engine (25 calls/day; speaker "
                       "switches log inline markers and do NOT flush)")}


def synthesize_wav(path: Path, *, minutes: float = 10.0,
                   sample_rate: int = 16000) -> Path:
    """Speech-shaped mono s16 WAV — tone bursts with pauses, not silence.

    Real acoustics need the owner's recording; this measures ROUTE and token
    ACCOUNTING (audio tokens are duration-driven), which is what the queue
    tuning needs. Written in 30 ms frames so a 10-minute spike never holds
    19 MB in RAM.
    """
    from .capture import WavSink

    path = Path(path)
    sink = WavSink(path, sample_rate)
    frame_samples = sample_rate * 30 // 1000
    total_frames = int(minutes * 60 * 1000 / 30)
    for i in range(total_frames):
        phase = (i % 24)                       # 0.72 s cycle: 0.48 s speech …
        if phase < 16:
            amplitude = 6000 + int(3000 * math.sin(i / 7))
            samples = [int(amplitude * math.sin(2 * math.pi * 220 * n / sample_rate))
                       for n in range(frame_samples)]
            frame = struct.pack(f"<{frame_samples}h", *samples)
        else:
            frame = b"\x00\x00" * frame_samples
        sink.write(frame)
    sink.close()
    assert path.stat().st_size > 0
    return Path(path)


def run_spike(config, *, wav_path: Path | str | None = None, minutes: float = 10.0,
              client=None, store=None, wall_clock=time.monotonic) -> dict:
    """Push one closed WAV through the transcribe-live route as a batch call."""
    from .capture import wav_duration_s
    from .config import ensure_private_dir
    from .gemini_client import GeminiClient
    from .store import Store

    own_store = store is None
    store = store or Store(config.db_path)
    client = client or GeminiClient(config, store)
    if wav_path is not None:
        wav = Path(wav_path)
    else:
        wav = synthesize_wav(
            ensure_private_dir(config.data_dir / "audio") / "event-spike.wav",
            minutes=minutes)
    duration = wav_duration_s(wav)
    model = config.model_for_role("transcribe_live")

    text = ""
    error = None
    started = wall_clock()
    try:
        result = client.transcribe_batch(wav, model=model)   # live route, batch call
        text = result.get("text", "") or ""
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    latency_s = max(0.0, wall_clock() - started)

    rows = store.recent_llm_calls(limit=1)
    row = rows[0] if rows else {}
    tokens = None
    if row:
        tokens = int(row.get("tokens_in") or 0) + int(row.get("tokens_out") or 0)
        if tokens <= 0:
            tokens = None
    tokens_measured = (bool(row) and not bool(row.get("tokens_estimated"))
                       and tokens is not None
                       # mock fixtures are synthetic: never a real figure (§0:
                       # "real figure, not the 32 tok/s estimate")
                       and config.gemini_mode != "mock")

    result = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": config.gemini_mode,
        "model": model,
        "wav": str(wav),
        "minutes": round(duration / 60.0, 3),
        "duration_s": round(duration, 3),
        "live_ok": error is None and bool(text.strip()),
        "full_transcript": error is None and bool(text.strip()),
        "text_sample": text[:200],
        "tokens": tokens,
        "tokens_measured": tokens_measured,
        "latency_s": round(latency_s, 3),
        "error": error,
    }
    result["decision"] = decide(result)
    if own_store:
        store.close()
    return result


def write_decision(result: dict, path: Path | str) -> Path:
    path = Path(path)
    ensure = path.parent
    ensure.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2) + "\n")
    tmp.replace(path)
    return path
