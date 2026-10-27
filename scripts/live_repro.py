#!/usr/bin/env python3
"""Stream H.3 — the decisive live-transcription repro (owner-run, scene 7).

Standalone by design: a bare google-genai Live session OUTSIDE the
daemon, the transcribe docs' Manual-VAD setup VERBATIM (live-transcribe
§Manual VAD (Push-to-Talk), Python example, fetched 2026-10-27), one
known-good kept wav streamed in 100 ms chunks, ActivityEnd at the end,
and EVERY raw message the SDK yields printed unfiltered. Our parser is
not imported anywhere in this file — whatever lands in this transcript
is what the wire actually said.

Two arms (two short housekeeping sessions, $0):

  ARM A  model = gemini-3.5-transcribe-live   (our pin)
         uv run python scripts/live_repro.py --arm A

  ARM B  model = gemini-3.8-live              (the docs' example
         conversational model, same Manual-VAD config with
         input_audio_transcription — the side-channel)
         uv run python scripts/live_repro.py --arm B

Outcomes (the ruling tree):

  (i)   transcripts in ARM A's raw stream  ->  the model does speak and
        our stack drops it despite the sensors  ->  deep-dive the parse
        path with this transcript as ground truth.
  (ii)  zero on ARM A, transcripts on ARM B  ->  the transcribe-live
        pin/transport combination is the deviation  ->  design-chat
        ruling on re-pinning to the side-channel (quota math in the
        stream-H report's H.5 section).
  (iii) zero on both  ->  account/model gating (unknown #5)  ->  AI
        Studio entitlement check + bug-report evidence pack for Google
        (this script's output IS the evidence pack core).

Requires: uv sync --extra live, GEMINI_API_KEY in the environment (the
key is never printed or logged anywhere). Costs at most one short Live
session per arm.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import sys
import time
import wave

# 100 ms at 16 kHz mono 16-bit — the documented chunk shape
# (audio/pcm;rate=16000; scene sessions used exactly this cadence).
CHUNK_SAMPLES = 1600
CHUNK_BYTES = CHUNK_SAMPLES * 2
RATE = 16000

ARM_MODELS = {
    "A": "gemini-3.5-transcribe-live",
    "B": "gemini-3.8-live",
}

DEFAULT_WAV = os.path.join("audio", "20261027-064450-77cc4e.wav")


def _ts(started: float) -> str:
    now = datetime.datetime.now().astimezone()
    return (f"{now.strftime('%H:%M:%S.%f')[:-3]} "
            f"(+{time.monotonic() - started:6.3f}s)")


def _dump(msg) -> str:
    """Full object repr, then the parsed dict when the SDK offers one.
    Single values clip at 4000 chars so a stray blob cannot eat the
    terminal — the SHAPE and the text stay unfiltered."""
    parts = [repr(msg)]
    dumped = getattr(msg, "model_dump", None)
    if callable(dumped):
        try:
            data = dumped(exclude_none=True)
            flat = repr(data)
            if len(flat) > 12000:
                flat = flat[:12000] + f"... (clipped {len(flat) - 12000} chars)"
            parts.append(f"  dump: {flat}")
        except Exception as exc:  # a dump failure must not kill the run
            parts.append(f"  dump failed: {exc}")
    return "\n".join(parts)


def _read_wav(path: str) -> bytes:
    with wave.open(path, "rb") as wav:
        channels, width, rate, frames = (
            wav.getnchannels(), wav.getsampwidth(), wav.getframerate(),
            wav.getnframes())
        pcm = wav.readframes(frames)
    if (channels, width, rate) != (1, 2, RATE):
        raise SystemExit(
            f"{path}: expected 16 kHz mono 16-bit PCM, got "
            f"{rate} Hz {channels}-ch {width * 8}-bit — repro only speaks "
            "the kept-wav format")
    return pcm


async def _run(arm: str, model: str, wav_path: str, listen_s: float,
               pace: str) -> int:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise SystemExit("google-genai missing — run: uv sync --extra live")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set (the key is never "
                         "printed; export it from your keyring/notes)")

    pcm = _read_wav(wav_path)
    chunks = [pcm[i:i + CHUNK_BYTES]
              for i in range(0, len(pcm), CHUNK_BYTES)]
    started = time.monotonic()
    seen = {"input_final": 0, "interim": 0, "voice_activity": 0,
            "turn_complete": 0, "other": 0}
    transcript_texts: list[str] = []

    print(f"=== H.3 arm {arm} — model {model} ===", flush=True)
    print(f"wav: {wav_path} ({len(pcm)} bytes = "
          f"{len(pcm) / 2 / RATE:.3f}s, {len(chunks)} chunks)", flush=True)
    print("config: VERBATIM Manual VAD — the live-transcribe docs' Python "
          "example, verbatim", flush=True)
    print(f"start: {_ts(started)}", flush=True)

    client = genai.Client(api_key=api_key,
                          http_options={"api_version": "v1beta"})

    # --- the documented Manual-VAD setup, verbatim ---------------------
    config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=True
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
    )
    # ------------------------------------------------------------------

    async with client.aio.live.connect(model=model, config=config) as session:
        print(f"connected: {_ts(started)}  (note: the SDK consumes the "
              "first message inside connect() — setup_complete may never "
              "reach this transcript; its absence here proves nothing)",
              flush=True)

        async def receive_all() -> None:
            try:
                async for msg in session.receive():
                    print(f"[{_ts(started)}] MSG", flush=True)
                    print(_dump(msg), flush=True)
                    content = getattr(msg, "server_content", None)
                    if content is None:
                        seen["other"] += 1
                        continue
                    interim = getattr(content, "interim_input_transcription",
                                      None)
                    if interim is not None and getattr(interim, "text", None):
                        seen["interim"] += 1
                    final = getattr(content, "input_transcription", None)
                    if final is not None and getattr(final, "text", None):
                        seen["input_final"] += 1
                        transcript_texts.append(final.text)
                    if getattr(content, "turn_complete", False):
                        seen["turn_complete"] += 1
                    if getattr(content, "voice_activity", None) is not None:
                        seen["voice_activity"] += 1
            except Exception as exc:  # the receiver reports, never dies silent
                print(f"[{_ts(started)}] receive() ended: "
                      f"{type(exc).__name__}: {exc}", flush=True)

        receiver = asyncio.create_task(receive_all())

        # Button pressed: signal speech start (docs' example comment).
        await session.send_realtime_input(
            activity_start=types.ActivityStart())
        print(f"activity_start sent: {_ts(started)}", flush=True)

        for i, chunk in enumerate(chunks):
            await session.send_realtime_input(
                audio=types.Blob(data=chunk,
                                 mime_type="audio/pcm;rate=16000"))
            if pace == "realtime":
                await asyncio.sleep(len(chunk) / 2 / RATE)
            if i % 50 == 0:
                print(f"  chunk {i}/{len(chunks)} {_ts(started)}", flush=True)

        # Button released: signal speech end (docs' example comment).
        await session.send_realtime_input(activity_end=types.ActivityEnd())
        print(f"activity_end sent: {_ts(started)} — listening "
              f"{listen_s:g}s for messages", flush=True)

        await asyncio.sleep(listen_s)
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)

    print(f"=== arm {arm} summary ===", flush=True)
    for key, value in seen.items():
        print(f"  {key}: {value}", flush=True)
    for text in transcript_texts:
        print(f"  heard: {text!r}", flush=True)

    if seen["input_final"] or seen["interim"]:
        if arm == "A":
            print("VERDICT (i): ARM A spoke — the wire carries transcripts "
                  "outside our stack. Deep-dive the parse path.", flush=True)
        else:
            print("VERDICT (ii or i): ARM B spoke", flush=True)
    else:
        print(f"VERDICT: arm {arm} silent — see the ruling tree in the "
              "script docstring", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="H.3 live-transcription repro (see module docstring)")
    parser.add_argument("--arm", choices=sorted(ARM_MODELS), default="A")
    parser.add_argument("--model", default=None,
                        help="override the arm's model id")
    parser.add_argument("--wav", default=DEFAULT_WAV,
                        help=f"16 kHz mono 16-bit wav (default: {DEFAULT_WAV})")
    parser.add_argument("--listen", type=float, default=30.0,
                        help="seconds to listen after activity_end (default 30)")
    parser.add_argument("--pace", choices=("realtime", "burst"),
                        default="realtime",
                        help="stream the wav in real time (default) or burst")
    args = parser.parse_args()
    model = args.model or ARM_MODELS[args.arm]
    return asyncio.run(_run(args.arm, model, args.wav, args.listen,
                            args.pace))


if __name__ == "__main__":
    sys.exit(main())
