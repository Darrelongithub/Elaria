"""GATE-FIX ROUND (hardware 2026-10-25): three failures, written red first.

* A keybind exec gives `assist dictate` no stdin. The old unconditional
  `input()` produced EOFError before any session reached the daemon; the
  non-TTY path must use the daemon's own until-quiet endpointing instead.
* The session-open ack must be a neutral, non-verbal cue, never a sentence.
* Real speech that matches no local intent must earn a model-generated plain
  clarification in the registered voice, never the owner's canned line
  "Understood, how may I help you?".

The hold-to-talk `assist ptt start` / `assist ptt stop` pair is the owner's
live wake key and is pinned here as a subprocess smoke test.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from assistant.daemon import Daemon
from assistant.gemini_client import GeminiClient
from assistant.ipc import call
from assistant.transcribe import SessionResult
from assistant.tts import SpeechResult

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "assistant"
SILENT_FRAME = b"\x00\x00" * (16000 * 30 // 1000)
CANNED_LINE = "Understood, how may I help you?"
PLAIN_REPLY = "I heard you, but I didn't catch a task — say it again?"
UNPARSED_TEXT = "the Thursday draft needs another look"

# The exact line and its customer-service family. A validator constant may
# name these to REJECT them; no reply-producing literal may contain them.
BANNED_REPLY_PHRASES = (
    "understood, how may i help you",
    "understood, what are you working on",
    "how may i help",
    "how may i assist",
    "how can i help",
    "i am here to help",
    "at your service",
    "is there anything i can help",
    "is there something i can assist",
)
VALIDATOR_CONSTANTS = frozenset({
    "FILLER_PHRASES", "CANNED_ACK_PHRASES", "CANNED_REPLY_PHRASES",
})


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _reply_literals(path: Path) -> list[str]:
    """String literals in src, minus docstrings and validator word lists."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    validator_literals = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in VALIDATOR_CONSTANTS
                for target in node.targets):
            for child in ast.walk(node.value):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    validator_literals.add(id(child))
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings and id(node) not in validator_literals
    ]


def _cli_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(REPO / "src"),
            "GEMINI_MODE": "mock"}


class FakeChatTransport:
    """Scripted model replies; records the prompts it was actually given."""

    def __init__(self, texts: list[str]):
        self.texts = list(texts)
        self.prompts: list[str] = []

    def generate(self, model, contents, config, on_first_token=None, **kwargs):
        self.prompts.append(str(contents))
        text = self.texts[min(len(self.prompts) - 1, len(self.texts) - 1)]
        if on_first_token is not None:
            on_first_token()
        return {"text": text, "usage": {"tokens_in": 7, "tokens_out": 3}}


class ShortSilentCapture:
    """Finite silent source: the daemon's ladder reaches its quiet endpoint."""

    target = "fixture-silence"
    stalled = False

    def __init__(self, *args, **kwargs):
        pass

    async def frames(self):
        for _ in range(12):
            yield SILENT_FRAME

    async def aclose(self):
        return None


# -- Failure 3a: grep-level sentinel over every voice-reply source literal ----
def test_the_canned_customer_service_line_is_unreachable_from_src():
    hits = []
    for path in sorted(SRC.glob("*.py")):
        for literal in _reply_literals(path):
            normalised = _normalise(literal)
            for phrase in BANNED_REPLY_PHRASES:
                if phrase in normalised:
                    hits.append(f"{path.name}: {phrase!r} in {literal[:80]!r}")
    assert hits == [], "canned customer-service reply is reachable from src"


# -- Failure 3a: session-open ack is a sound cue, not a spoken sentence ------
def test_session_open_ack_is_a_neutral_nonverbal_cue(config, running_daemon,
                                                    monkeypatch):
    daemon, _server = running_daemon
    config.raw["tts"]["speak_acks"] = True
    plays: list[str] = []
    routed_texts: list[str] = []

    def route(text):
        routed_texts.append(text)
        return {"muted": False, "voice_id": "Flare", "backend": "local"}

    monkeypatch.setattr(daemon.speech, "voice_route",
                        lambda: ("local", "test posture"))
    monkeypatch.setattr(daemon.speech, "route", route)
    monkeypatch.setattr(daemon.speech, "cached_ack",
                        lambda kind: "/tmp/neutral-session-cue.wav")
    monkeypatch.setattr(daemon.speech, "play_ack",
                        lambda kind: (plays.append(kind), {"played": True})[1])

    started = call(config.socket_path, "ptt.start",
                   {"source": "simulated"}, timeout=5.0)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not plays:
        time.sleep(0.01)
    try:
        assert plays == ["session_open"], (
            f"session open still played a verbal ack: {plays}")
        assert "" in routed_texts, "the cue was routed as spoken text"
        assert started["ack"] is True
        assert started["speech"]["cue"] is True
        assert started["speech"]["ack_kind"] == "session_open"
    finally:
        call(config.socket_path, "ptt.stop", timeout=5.0)


# -- Failure 3b: unparsed command goes to the model clarification ladder -----
def test_command_mode_unparsed_transcript_asks_for_a_model_clarification(
        config, monkeypatch):
    daemon = Daemon(config)
    asked: list[dict] = []

    async def fake_ask(params):
        asked.append(dict(params))
        return {"reply": PLAIN_REPLY, "narration": PLAIN_REPLY,
                "via": "gemini-unparsed-command"}

    monkeypatch.setattr(daemon, "_ask", fake_ask)
    session = SessionResult(
        session_id="sid", raw_text=UNPARSED_TEXT, cleaned_text=None,
        backend="gemini_live", language="en", audio_path=None, inbox_path=None,
        clipboard={"copied": False}, flagged=False, duration_s=1.0,
        confidence=0.95)

    async def scenario():
        daemon._ptt_session_id = "sid"
        task = asyncio.create_task(asyncio.sleep(0, result=session))
        await daemon._finish_dictation(task, {"speak": True}, "sid", "command")
        await daemon.aclose()

    asyncio.run(scenario())
    assert asked, "an unparsed command never reached the reply path"
    assert asked[0]["text"] == UNPARSED_TEXT
    assert asked[0]["speak"] is True
    assert asked[0].get("unparsed_command") is True, (
        "real speech with no local intent used the generic chat door")


def test_parse_failure_reply_is_model_generated_in_the_registered_voice(
        config, running_daemon, monkeypatch):
    daemon, _server = running_daemon
    transport = FakeChatTransport([CANNED_LINE, PLAIN_REPLY])
    daemon.client = GeminiClient(daemon.config, daemon.store, transport=transport)
    spoken: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        daemon.speech, "route",
        lambda text: {"muted": False, "voice_id": "Flare", "backend": "local"})

    def speak(text, *, play=True):
        spoken.append((text, play))
        return SpeechResult(text=text, backend="local", voice_id="Flare",
                            played=play)

    monkeypatch.setattr(daemon.speech, "speak", speak)

    result = call(config.socket_path, "ask",
                  {"text": UNPARSED_TEXT, "unparsed_command": True,
                   "speak": True}, timeout=15.0)

    assert result["reply"] == PLAIN_REPLY
    assert result["via"] == "gemini-unparsed-command"
    assert CANNED_LINE not in json.dumps(result)
    assert len(transport.prompts) == 2, "the canned line was not rejected"
    assert "do not greet" in transport.prompts[0].lower()
    assert spoken == [(PLAIN_REPLY, True)]
    assert result["speech"]["voice_id"] == "Flare"


# -- Failure 2: no stdin must not produce an EOFError traceback ---------------
def test_dictate_with_devnull_stdin_closes_on_endpointing(
        config, running_daemon, monkeypatch):
    daemon, _server = running_daemon
    # The daemon owns endpointing; shorten its real ladder for a sandbox test.
    daemon.dictation.checkin_after = {
        "command": 0.09, "conversation": 0.09, "narration": 0.09}
    daemon.dictation.grace_s = 0.09
    daemon.dictation.resume_s = 0.03
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", ShortSilentCapture)

    out = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "dictate"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        env=_cli_env(), timeout=40, check=False)

    assert out.returncode == 0, out.stdout + out.stderr
    assert "Traceback" not in out.stderr, out.stderr
    assert "EOFError" not in out.stderr, out.stderr
    assert "she will stop when you go quiet" in out.stdout
    assert "no speech captured" in out.stdout
    assert daemon.store.list_persona_events(
        kind="session.silent_close", limit=5), "endpointing never closed"
    status = call(config.socket_path, "status", timeout=3.0)
    assert status["dictation_active"] is False


# -- the live hold-to-talk key is not regressed -------------------------------
def test_hold_to_talk_ptt_start_stop_still_works(config, running_daemon):
    env = _cli_env()
    start = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "ptt", "start"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        env=env, timeout=10, check=False)
    assert start.returncode == 0, start.stdout + start.stderr
    assert json.loads(start.stdout)["listening"] is True
    stop = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "ptt", "stop"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        env=env, timeout=10, check=False)
    assert stop.returncode == 0, stop.stdout + stop.stderr
    assert json.loads(stop.stdout)["listening"] is False


def test_session_open_cue_is_a_cached_local_earcon(config, tmp_path, monkeypatch):
    """No spoken text or Gemini synth on the §18 session-open cue path."""
    from assistant.tts import SESSION_CUE_KIND, SpeechService

    config.raw["tts"]["online_voice"] = "local"
    config.raw["tts"]["offline_voice"] = "local"
    config.raw["tts"]["cache_dir"] = str(tmp_path / "cue-cache")
    speech = SpeechService(config)
    played: list[Path] = []
    monkeypatch.setattr(speech, "play_audio",
                        lambda path: (played.append(Path(path)), True)[1])

    path = speech.cached_ack(SESSION_CUE_KIND)
    assert path and Path(path).exists()
    with __import__("wave").open(path, "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 24000
        assert 0 < wav.getnframes() / wav.getframerate() < 0.2
    result = speech.play_ack(SESSION_CUE_KIND)
    assert result["cue"] is True and result["text"] == ""
    assert result["played"] is True and played == [Path(path)]
    assert speech.cached_ack(SESSION_CUE_KIND) == path
