#!/usr/bin/env python3
"""H.3 — the decisive live-transcription repro (owner-run).  W2 rebuilt 2026-10-31.

Standalone by design: a bare google-genai Live session OUTSIDE the
daemon, one known-good kept wav streamed in 100 ms chunks, and EVERY raw
message the SDK yields printed unfiltered. Our parser is not imported
anywhere in this file — whatever lands in this transcript is what the
wire actually said.

Two arms, each with ITS OWN documented config shape (W2, 2026-10-31 —
the old arm B died at the door: WS 1007 "response modalities (TEXT) not
supported" against gemini-3.8-live; the Manual-VAD TEXT config belongs
to transcription models):

  ARM A  model = gemini-3.5-transcribe-live   (our pin)
         config = the live-transcribe docs' Manual-VAD Python example
         VERBATIM (fetched 2026-10-27): response_modalities ["TEXT"],
         automatic_activity_detection disabled, input_audio_transcription
         — plus ActivityStart/ActivityEnd around the stream.

  ARM B  model = gemini-3.8-live              (the docs' conversational
         model) — config = {"response_modalities": ["AUDIO"],
         "input_audio_transcription": {}} VERBATIM from the Live API
         capabilities guide "Audio transcriptions" input example
         (fetched 2026-10-31): raw PCM blobs audio/pcm;rate=16000, then
         read msg.server_content.input_transcription.text as the
         side-channel. No activity markers — the conversational model's
         own VAD owns the turn (the get-started-sdk "Receiving text"
         section reads the same side-channel).

Run (owner runtime, GEMINI_API_KEY exported — the key is never printed):

  uv run python scripts/live_repro.py --arm A
  uv run python scripts/live_repro.py --arm B

Verdicts (both are results):
  ARM B VERDICT: SPOKE  — transcription text present on the side-channel
  ARM B VERDICT: SILENT — connected, audio acknowledged, zero transcription
  ARM B VERDICT: NO-RUN — connect/send failed (e.g. another 1007); not a
                          transcription result, and never misreported as SILENT

Ruling tree:
  (i)   transcripts in ARM A's raw stream  ->  the model does speak and
        our stack drops it despite the sensors  ->  deep-dive the parse
        path with this transcript as ground truth.
  (ii)  SILENT on ARM A, SPOKE on ARM B  ->  the transcribe-live
        pin/transport combination is the deviation  ->  design-chat
        ruling on re-pinning to the side-channel (quota math in the
        stream-H report's H.5 section).
  (iii) SILENT on both  ->  account/model gating (unknown #5)  ->  AI
        Studio entitlement check + bug-report evidence pack for Google
        (this script's output IS the evidence pack core).

Robustness (W2): every send is guarded — a send to a closed socket is a
result, not a traceback — and the summary counters classify each family
from every known attribute location (the old counter reported
voice_activity: 0 while dumping two voice-activity messages).

Requires: uv sync (google-genai is a base dependency). Costs at most one
short Live session per arm ($0 housekeeping).
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

DEFAULT_WAV_NAME = "20261027-064450-77cc4e.wav"

# W2: the summary counts exactly what the dump shows. A family is marked
# from EVERY known attribute location on the message and its
# server_content — the old counter checked one location and lied.
FAMILIES = ("input_final", "interim", "voice_activity", "turn_complete",
            "output_transcription", "model_turn", "tool_call",
            "setup_complete", "go_away", "other")


def _find_default_wav() -> str:
    """The kept wavs live in the daemon's audio dir on the owner's
    machine (XDG data home); ./audio works for a repo-local copy."""
    candidates = [
        os.path.join(os.path.expanduser("~"), ".local", "share",
                     "assistant", "audio", DEFAULT_WAV_NAME),
        os.path.join("audio", DEFAULT_WAV_NAME),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


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


def _classify_message(msg) -> set[str]:
    """Every summary family this message evidences — from any location."""
    families: set[str] = set()
    content = getattr(msg, "server_content", None)
    objects = [obj for obj in (msg, content) if obj is not None]

    def text_of(name: str):
        for obj in objects:
            node = getattr(obj, name, None)
            if node is not None:
                text = getattr(node, "text", None)
                if text:
                    return text
        return None

    if text_of("input_transcription") or text_of("input_audio_transcription"):
        families.add("input_final")
    if text_of("interim_input_transcription"):
        families.add("interim")
    if text_of("output_transcription") or text_of("output_audio_transcription"):
        families.add("output_transcription")
    for name in ("voice_activity", "activity_start", "activity_end"):
        for obj in objects:
            if getattr(obj, name, None) is not None:
                families.add("voice_activity")
    for obj in objects:
        if getattr(obj, "turn_complete", False):
            families.add("turn_complete")
        if getattr(obj, "model_turn", None) is not None:
            families.add("model_turn")
        if getattr(obj, "tool_call", None) is not None:
            families.add("tool_call")
        if getattr(obj, "setup_complete", None) is not None:
            families.add("setup_complete")
        if getattr(obj, "go_away", None) is not None:
            families.add("go_away")
    if not families:
        families.add("other")
    return families


def _harvest_texts(msg) -> tuple[str | None, str | None]:
    """(final input text, interim input text) as the side-channel carries
    them — the same attribute walk the classifier uses."""
    content = getattr(msg, "server_content", None)
    objects = [obj for obj in (msg, content) if obj is not None]

    def text_of(name: str):
        for obj in objects:
            node = getattr(obj, name, None)
            if node is not None:
                text = getattr(node, "text", None)
                if text:
                    return text
        return None

    final = text_of("input_transcription") or text_of("input_audio_transcription")
    interim = text_of("interim_input_transcription")
    return final, interim


async def _safe_send(session, started: float, label: str, **kwargs) -> bool:
    """W2 robustness: sending into a closed socket is a result, not a
    crash (arm B died with a traceback on send to a 1007-closed
    connection). Returns False on refusal."""
    try:
        await session.send_realtime_input(**kwargs)
        return True
    except Exception as exc:
        print(f"[{_ts(started)}] send refused ({label}): "
              f"{type(exc).__name__}: {exc}", flush=True)
        return False


def _verdict(arm: str, *, spoke: bool, connected: bool, audio_ack: bool,
             messages_seen: int) -> str:
    if arm == "B":
        if not connected or not audio_ack:
            reason = ("connect failed" if not connected else
                      "send refused before the audio was fully acknowledged")
            return (f"ARM B VERDICT: NO-RUN ({reason} — not a transcription "
                    "result, never misreported as SILENT)")
        return ("ARM B VERDICT: SPOKE — transcription text present "
                "on the input_transcription side-channel"
                if spoke else
                "ARM B VERDICT: SILENT — connected, audio acknowledged, "
                f"zero transcription ({messages_seen} message(s) seen, "
                "none carrying transcription text)")
    if spoke:
        return ("VERDICT (i): ARM A spoke — the wire carries transcripts "
                "outside our stack. Deep-dive the parse path.")
    return ("VERDICT: ARM A SILENT — ruling tree arms (ii)/(iii) are "
            "decided by arm B's run")


async def _run(arm: str, model: str, wav_path: str, listen_s: float,
               pace: str, client_factory=None) -> int:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise SystemExit("google-genai missing — run: uv sync")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and client_factory is None:
        raise SystemExit("GEMINI_API_KEY is not set (the key is never "
                         "printed; export it from your keyring/notes)")

    pcm = _read_wav(wav_path)
    chunks = [pcm[i:i + CHUNK_BYTES]
              for i in range(0, len(pcm), CHUNK_BYTES)]
    started = time.monotonic()
    seen = {family: 0 for family in FAMILIES}
    transcript_texts: list[str] = []
    interim_texts: list[str] = []
    messages_seen = 0

    if arm == "A":
        config_label = ("VERBATIM Manual VAD — the live-transcribe docs' "
                        "Python example, verbatim (fetched 2026-10-27)")
        # --- the documented Manual-VAD setup, verbatim -----------------
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
    else:
        config_label = ("VERBATIM conversational side-channel — the Live "
                        "capabilities guide 'Audio transcriptions' input "
                        "example (fetched 2026-10-31)")
        # --- the documented conversational shape, verbatim --------------
        config = {"response_modalities": ["AUDIO"],
                  "input_audio_transcription": {}}
        # ------------------------------------------------------------------

    print(f"=== H.3 arm {arm} — model {model} ===", flush=True)
    print(f"wav: {wav_path} ({len(pcm)} bytes = "
          f"{len(pcm) / 2 / RATE:.3f}s, {len(chunks)} chunks)", flush=True)
    print(f"config: {config_label}", flush=True)
    print(f"start: {_ts(started)}", flush=True)

    if client_factory is not None:
        client = client_factory()
    else:
        client = genai.Client(api_key=api_key,
                              http_options={"api_version": "v1beta"})

    connected = False
    audio_ack = False
    sent = 0
    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            connected = True
            print(f"connected: {_ts(started)}  (note: the SDK consumes the "
                  "first message inside connect() — setup_complete may never "
                  "reach this transcript; its absence here proves nothing)",
                  flush=True)

            async def receive_all() -> None:
                nonlocal messages_seen
                try:
                    async for msg in session.receive():
                        messages_seen += 1
                        print(f"[{_ts(started)}] MSG", flush=True)
                        print(_dump(msg), flush=True)
                        for family in _classify_message(msg):
                            seen[family] += 1
                        final, interim = _harvest_texts(msg)
                        if final:
                            transcript_texts.append(final)
                        if interim:
                            interim_texts.append(interim)
                except Exception as exc:  # the receiver reports, never dies silent
                    print(f"[{_ts(started)}] receive() ended: "
                          f"{type(exc).__name__}: {exc}", flush=True)

            receiver = asyncio.create_task(receive_all())

            if arm == "A":
                # Button pressed: signal speech start (docs' example comment).
                ok = await _safe_send(session, started, "activity_start",
                                      activity_start=types.ActivityStart())
                print(f"activity_start sent: {_ts(started)}", flush=True)
            else:
                ok = True  # arm B: the model's own VAD owns the turn

            sent = 0
            for i, chunk in enumerate(chunks):
                if not ok:
                    break
                ok = await _safe_send(
                    session, started, f"chunk {i}",
                    audio=types.Blob(data=chunk,
                                     mime_type="audio/pcm;rate=16000"))
                if ok:
                    sent += 1
                if pace == "realtime" and ok:
                    await asyncio.sleep(len(chunk) / 2 / RATE)
                if i % 50 == 0:
                    print(f"  chunk {i}/{len(chunks)} {_ts(started)}", flush=True)
            audio_ack = (sent == len(chunks) and sent > 0)

            if arm == "A":
                # Button released: signal speech end (docs' example comment).
                await _safe_send(session, started, "activity_end",
                                 activity_end=types.ActivityEnd())
                print(f"activity_end sent: {_ts(started)}", flush=True)
            print(f"audio sent: {sent}/{len(chunks)} chunks — listening "
                  f"{listen_s:g}s for messages", flush=True)

            await asyncio.sleep(listen_s)
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
    except Exception as exc:
        # W2: the run must COMPLETE and report — a connect that dies at the
        # door (e.g. WS 1007) is a NO-RUN verdict, never a traceback.
        print(f"[{_ts(started)}] session failed: "
              f"{type(exc).__name__}: {exc}", flush=True)

    print(f"=== arm {arm} summary ===", flush=True)
    for family in FAMILIES:
        print(f"  {family}: {seen[family]}", flush=True)
    print(f"  messages_seen: {messages_seen}", flush=True)
    print(f"  audio_acked: {audio_ack} ({sent}/{len(chunks)} chunks)",
          flush=True)
    for text in transcript_texts:
        print(f"  heard: {text!r}", flush=True)
    for text in interim_texts:
        print(f"  interim: {text!r}", flush=True)

    print(_verdict(arm, spoke=bool(transcript_texts or interim_texts),
                   connected=connected, audio_ack=audio_ack,
                   messages_seen=messages_seen), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="H.3 live-transcription repro (see module docstring)")
    parser.add_argument("--arm", choices=sorted(ARM_MODELS), default="A")
    parser.add_argument("--model", default=None,
                        help="override the arm's model id")
    parser.add_argument("--wav", default=None,
                        help="16 kHz mono 16-bit wav (default: the kept "
                             f"{DEFAULT_WAV_NAME} under ~/.local/share/"
                             "assistant/audio or ./audio)")
    parser.add_argument("--listen", type=float, default=30.0,
                        help="seconds to listen after the audio (default 30)")
    parser.add_argument("--pace", choices=("realtime", "burst"),
                        default="realtime",
                        help="stream the wav in real time (default) or burst")
    args = parser.parse_args()
    model = args.model or ARM_MODELS[args.arm]
    wav = args.wav or _find_default_wav()
    return asyncio.run(_run(args.arm, model, wav, args.listen,
                            args.pace))


if __name__ == "__main__":
    sys.exit(main())
