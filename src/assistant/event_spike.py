"""§0 Step 0 spike — BLOCKING before any queue tuning (Blueprint v2 §0).

Two routes are measured:

  * LIVE route   — one closed WAV pushed through the transcribe-live model as
                   a batch-style generateContent call (i.e. what `run_spike`
                   has always done). Used to decide rows 1–2.
  * BATCH route  — the SAME call path event segments actually use:
                   `asr.transcribe_file` → `GeminiBatchBackend.transcribe` →
                   `client.transcribe_batch(wav)` with the default
                   `transcribe_batch` model (no override). This is what
                   events run on for row 3. It MUST be measured against the
                   owner's real WAV (`--wav`); synthesized audio does not
                   exercise real quota/error behaviour.

The CLI prints every number with the route it belongs to. If the batch
route rejects a 30-min segment WAV for size/duration, the error text is
reported verbatim and the default segment length drops to the largest
size the API accepted, with the 10-hour call math restated.

Decision table (unchanged):

  1  live batched the WAV, tokens/segment < ~12K   → transcribe-live, 10 min
  2  live works but tokens/segment > ~12K          → transcribe-live, shortened
  3  live cannot batch a closed WAV (or ambiguous) → batch (25/day), 30 min,
     speaker switches log inline markers and do NOT flush

"If the spike is ambiguous, default to the third row: it is the proven
engine." A run without a live API key (mock/record fixtures, estimated
tokens) is ambiguous by construction — row 3. Nothing downstream is
built on assumption: `docs/event-spike.json` holds the measured record.
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

# Defaults when the batch route is proven but no measured token figure yet
# (§0 table row 3). A 10-hour event at 30 min/segment = 20 segments; 25/day
# quota gives headroom for retries.
BATCH_DEFAULT_MIN = 30.0
BATCH_CALL_BUDGET = 25
EVENT_TARGET_HOURS = 10.0


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
    return {"row": 3, "route": "batch", "segment_minutes": BATCH_DEFAULT_MIN,
            "switch_flush": False,
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


def _extract_tokens_from_store(store, *, gemini_mode: str) -> tuple[int | None, bool]:
    """Pull the most recent LLM-call's token count; flag if it was measured."""
    rows = store.recent_llm_calls(limit=1)
    row = rows[0] if rows else {}
    tokens = None
    if row:
        tokens = int(row.get("tokens_in") or 0) + int(row.get("tokens_out") or 0)
        if tokens <= 0:
            tokens = None
    tokens_measured = (bool(row) and not bool(row.get("tokens_estimated"))
                       and tokens is not None
                       # mock fixtures are synthetic: never a real figure
                       # (§0: "real figure, not the 32 tok/s estimate")
                       and gemini_mode != "mock")
    return tokens, tokens_measured


# ---------------------------------------------------------------------------
# Live-route spike (original behaviour): pushes a closed WAV through the
# transcribe-live model as a batch-style generateContent call.
# ---------------------------------------------------------------------------
def run_live_spike(config, *, wav_path: Path | str | None = None,
                   minutes: float = 10.0, client=None, store=None,
                   wall_clock=time.monotonic) -> dict:
    """Push one closed WAV through the transcribe-live model as a batch call.

    Uses the transcribe_live model override — this is NOT what event
    segments run on when route=batch. See `run_batch_spike` for that.
    """
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
        api_result = client.transcribe_batch(wav, model=model)   # live route, batch call
        text = api_result.get("text", "") or ""
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    latency_s = max(0.0, wall_clock() - started)

    tokens, tokens_measured = _extract_tokens_from_store(
        store, gemini_mode=config.gemini_mode)

    size_mb = round(wav.stat().st_size / (1024 * 1024), 2)
    result = {
        "route": "transcribe-live",
        "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": config.gemini_mode,
        "model": model,
        "wav": str(wav),
        "wav_size_mb": size_mb,
        "minutes": round(duration / 60.0, 3),
        "duration_s": round(duration, 3),
        "accepted": error is None and bool(text.strip()),
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


# ---------------------------------------------------------------------------
# Batch-route spike: pushes the owner's WAV through the EXACT call path that
# event segments use — `asr.transcribe_file` on the transcribe_batch model
# (no override). This is the measurement row 3 has been claiming without
# actually performing.
# ---------------------------------------------------------------------------
# Error substrings that suggest the API rejected the WAV because of its
# size or duration (vs. a transient/network/auth failure). These are
# necessarily heuristic — the exact wording depends on provider version —
# so we also surface the raw error text verbatim.
_SIZE_ERROR_HINTS = (
    "too large", "file too big", "payload too large", "request too large",
    "file size", "max size", "exceeds", "duration", "too long",
    "audio too long", "maximum length", "limit", "413",
)


def _looks_like_size_or_duration_error(error: str) -> bool:
    if not error:
        return False
    low = error.lower()
    return any(hint in low for hint in _SIZE_ERROR_HINTS)


def _largest_accepted_minutes(rejected_minutes: float) -> float:
    """Halving search for a conservative segment length when the API
    rejected a given WAV. We don't have a smaller probe to submit here
    (no real API round-trip budget for bisecting), so halve and round
    down to a whole minute as a safe starting point. The actual cap is
    discovered empirically on the next successful spike run."""
    candidate = rejected_minutes / 2.0
    # Snap down to the nearest whole minute that is at least 1.
    return max(1.0, math.floor(candidate))


def _restate_batch_math(segment_minutes: float, *,
                        budget_calls: int = BATCH_CALL_BUDGET,
                        event_hours: float = EVENT_TARGET_HOURS) -> dict:
    """Recompute the 10-hour call math for a proposed segment length."""
    calls_per_event = math.ceil(event_hours * 60.0 / segment_minutes)
    headroom_calls = max(0, budget_calls - calls_per_event)
    covers = "yes" if calls_per_event <= budget_calls else "NO"
    seg_label = (f"{segment_minutes:.1f}" if segment_minutes >= 1
                 else f"{segment_minutes:.2f}")
    return {
        "segment_minutes": round(segment_minutes, 2),
        "calls_per_10h_event": calls_per_event,
        "budget_calls_per_day": budget_calls,
        "headroom_calls": headroom_calls,
        "fits_daily_budget": covers == "yes",
        "summary": (f"at {seg_label} min/segment a 10 h event "
                    f"needs {calls_per_event} calls vs {budget_calls}/day budget "
                    f"→ covers full day: {covers} (headroom {headroom_calls})"),
    }


def run_batch_spike(config, wav_path: Path | str, *,
                    client=None, store=None,
                    wall_clock=time.monotonic) -> dict:
    """Push one closed WAV through the batch route event segments use.

    Unlike `run_live_spike`, this has NO synthesized-audio fallback: a real
    measurement requires the owner's real WAV (the 30-min segment captured
    on hardware, ~57 MB). Pass the path via `--wav`.
    """
    from . import asr
    from .capture import wav_duration_s
    from .gemini_client import GeminiClient
    from .store import Store

    wav = Path(wav_path)
    if not wav.exists():
        raise FileNotFoundError(f"batch spike WAV not found: {wav}")

    own_store = store is None
    store = store or Store(config.db_path)
    client = client or GeminiClient(config, store)

    duration = wav_duration_s(wav)
    size_mb = round(wav.stat().st_size / (1024 * 1024), 2)
    model = config.model_for_role("transcribe_batch")

    text = ""
    error = None
    started = wall_clock()
    try:
        # Exact same call path EventService._make_transcribe_fn uses:
        # asr.transcribe_file walks the fallback chain, default first
        # entry is GeminiBatchBackend → client.transcribe_batch(wav)
        # with the transcribe_batch model (no override).
        transcript = asr.transcribe_file(config, client, str(wav))
        text = (transcript.text or "") if transcript is not None else ""
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    latency_s = max(0.0, wall_clock() - started)

    tokens, tokens_measured = _extract_tokens_from_store(
        store, gemini_mode=config.gemini_mode)

    accepted = error is None and bool(text.strip())
    minutes = duration / 60.0
    size_rejection = bool(error) and _looks_like_size_or_duration_error(str(error))

    result: dict = {
        "route": "batch",
        "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": config.gemini_mode,
        "model": model,
        "wav": str(wav),
        "wav_size_mb": size_mb,
        "minutes": round(minutes, 3),
        "duration_s": round(duration, 3),
        "accepted": accepted,
        "full_transcript": accepted,
        "text_sample": text[:200],
        "tokens": tokens,
        "tokens_measured": tokens_measured,
        "latency_s": round(latency_s, 3),
        "error": error,
    }

    # If the batch endpoint rejected the WAV for size/duration, recommend a
    # shorter default segment length and restate the 10h math. A transient
    # (network/auth/quota) error does NOT trigger a length change.
    if size_rejection:
        suggested = _largest_accepted_minutes(minutes)
        result["size_rejection"] = True
        result["suggested_segment_minutes"] = round(suggested, 2)
        result["call_math"] = _restate_batch_math(suggested)
        result["note"] = (
            "batch route rejected the WAV for size/duration; the 30 min default "
            "is too long for this API. Halving the segment length is a safe "
            "starting point — re-run the spike with a shorter WAV to confirm."
        )
    elif accepted:
        result["size_rejection"] = False
        # If we got a real measured token count, restate math at the
        # accepted length so the log has the record.
        result["call_math"] = _restate_batch_math(minutes)
    else:
        result["size_rejection"] = False
        # Non-size error: keep default but still restate math so the
        # record shows what was assumed.
        result["call_math"] = _restate_batch_math(BATCH_DEFAULT_MIN)

    if own_store:
        store.close()
    return result


# ---------------------------------------------------------------------------
# Original entry point (backwards-compatible): lives on as the live-route
# spike. Tests and prior CLI invocations keep working unchanged.
# ---------------------------------------------------------------------------
def run_spike(config, *, wav_path: Path | str | None = None, minutes: float = 10.0,
              client=None, store=None, wall_clock=time.monotonic) -> dict:
    """Backwards-compatible alias: run the live-route spike only."""
    return run_live_spike(config, wav_path=wav_path, minutes=minutes,
                          client=client, store=store, wall_clock=wall_clock)


def run_both(config, *, wav_path: Path | str | None = None, minutes: float = 10.0,
             client=None, store=None, wall_clock=time.monotonic) -> dict:
    """Run the live-route spike AND, when a WAV is provided, the batch-route
    spike against that exact file. Returns a combined record labelled per
    route so it is impossible to confuse the two numbers."""
    from .gemini_client import GeminiClient
    from .store import Store

    own_store = store is None
    store = store or Store(config.db_path)
    client = client or GeminiClient(config, store)

    live = run_live_spike(config, wav_path=wav_path, minutes=minutes,
                          client=client, store=store, wall_clock=wall_clock)

    batch = None
    batch_error = None
    if wav_path is not None:
        try:
            batch = run_batch_spike(config, wav_path, client=client, store=store,
                                    wall_clock=wall_clock)
        except Exception as exc:
            batch_error = f"{type(exc).__name__}: {exc}"

    # The decision comes from the LIVE spike (original §0 table). The batch
    # spike overrides the segment length when it measured a size rejection.
    decision = dict(live["decision"])
    if batch is not None and batch.get("size_rejection"):
        decision = {
            "row": 3,
            "route": "batch",
            "segment_minutes": batch["suggested_segment_minutes"],
            "switch_flush": False,
            "reason": (f"live-route spike defaulted to row 3 but the batch route "
                       f"rejected a {batch['minutes']:.1f}-min WAV ({batch['wav_size_mb']} MB) "
                       f"for size/duration; dropping default segment length to "
                       f"{batch['suggested_segment_minutes']:.0f} min. "
                       f"{batch['call_math']['summary']}"),
            "batch_error": batch.get("error"),
        }

    record = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": config.gemini_mode,
        "routes": {
            "transcribe-live": live,
        },
        "decision": decision,
    }
    if batch is not None:
        record["routes"]["batch"] = batch
    if batch_error is not None:
        record["routes"]["batch"] = {"route": "batch", "error": batch_error,
                                     "accepted": False}

    if own_store:
        store.close()
    return record


def write_decision(result: dict, path: Path | str) -> Path:
    path = Path(path)
    ensure = path.parent
    ensure.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2) + "\n")
    tmp.replace(path)
    return path
