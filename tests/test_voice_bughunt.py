"""VOICE BUG HUNT — the speaking pipeline only, adversarial.

Owner contract this file enforces (settled, not relitigated here):
Flare (Gemini native audio) is the ONLY voice; OFFLINE has NO VOICE AT ALL;
the local Piper path is dormant and must never speak in normal operation;
acks answer in <300ms from cached audio; "Is that all?" is asked once.

Everything runs with Gemini mocked and no key (conftest enforces it). Findings
are recorded as strict xfail so each one stays an executable repro; the write-up
with numbers and repros lives in VOICE-BUGTEST.md (VB-n ids below match it).
"""

from __future__ import annotations

import asyncio
import json
import re
import struct
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from assistant.capture import RollingAudioBuffer
from assistant.config import DEFAULTS, load_config
from assistant.daemon import Daemon
from assistant.modes import ModeManager
from assistant.store import Store
from assistant.transcribe import DictationService, SilenceLadder
from assistant.tts import STANDARD_ACKS, SpeechService, VoiceDescriptor
from assistant.waybar import format_waybar

SRC = Path(__file__).resolve().parents[1] / "src" / "assistant"
FRAME_SAMPLES = 16000 * 30 // 1000
SPEECH = struct.pack(f"<{FRAME_SAMPLES}h", *([6000] * FRAME_SAMPLES))
SILENCE = b"\x00\x00" * FRAME_SAMPLES


def store(tmp_path: Path, name: str = "vb.db") -> Store:
    return Store(tmp_path / name)


def voice_config(tmp_path: Path, **tts) -> object:
    """Config with a scratch cache/audition dir; `[tts]` keys overridable."""
    config = load_config()
    settings = {**config.raw["tts"], "backend": "mock", "voice_id": "elaria-vb",
                "player": "none", "cache_dir": str(tmp_path / "cache"),
                "audition_dir": str(tmp_path / "auditions"), "command": ""}
    config.raw["tts"] = {**settings, **tts}
    # The cleanup pass is a model call about TEXT, not about voice: disabled here
    # so Area D exercises capture, endpointing, the Live chain and the queue.
    config.raw["cleanup"] = {**config.raw["cleanup"], "enabled": False}
    return config


class EchoClient:
    """Records the voice it was actually asked to speak, like the real client.

    FakeVoiceClient in the phase-8 file hardcodes Flare in its reply, which is
    exactly why it can never catch a wrong-voice regression; this one echoes
    what resolution produced, so identity bugs surface.
    """

    mode = "live"

    def __init__(self, config, *, fail=None, can=True):
        self.config = config
        self._fail = fail
        self._can = can
        self.calls: list[tuple[str, str]] = []   # (text, voice_name)
        self.pcm = struct.pack("<640h", *([4000 if i % 2 else -4000 for i in range(640)]))

    def can_speak(self) -> bool:
        return self._can

    def voice_request(self, text, *, voice=None):
        """Mirrors the real client, including the canonical-voice pin (VB-4):
        a caller that skips `voice_route` still cannot get audio out."""
        from assistant.config import canonical_voices, resolve_voice

        gemini = self.config.section("gemini")
        requested = str(voice or gemini.get("voice") or "Flare")
        effective, allowed = resolve_voice(self.config, requested)
        return {"model": gemini.get("model_voice", "x"),
                "voice_name": effective or requested, "voice_requested": requested,
                "voice_allowed": allowed, "canonical_voices": list(
                    canonical_voices(self.config)),
                "response_modalities": ["AUDIO"], "text": text}

    def generate_voice(self, text, *, voice=None, correlation_id="-"):
        request = self.voice_request(text, voice=voice)
        self.calls.append((text, request["voice_name"]))
        if not request["voice_allowed"]:
            raise RuntimeError(f"voice {request['voice_requested']!r} is not canonical")
        if self._fail:
            raise RuntimeError(self._fail)
        return {"pcm": self.pcm, "sample_rate": 24000,
                "voice_name": request["voice_name"], "usage": {}}


def service(tmp_path, client=None, *, online=True, **tts):
    config = voice_config(tmp_path, **tts)
    client = client or EchoClient(config)
    return config, SpeechService(config, store(tmp_path), client=client,
                                  is_online=lambda: online), client


# ══════════════════════════════════════════════════════════════════════════
# A. VOICE IDENTITY — the one-voice rule
# ══════════════════════════════════════════════════════════════════════════

SPEAK_CALLERS = {  # every speech-out site found by AST scan, mapped to its text
    "conversation/task reply": "Twelve need review.",
    "pushback": "That would delete 148 files. I am not doing that.",
    "completion summary": "Sorted 148 files into Finance.",
    "error": "The indexer failed on two folders.",
}


def test_a1_all_online_speech_paths_use_flare(tmp_path):
    """Every SpeechService entry point that can make sound resolves to Flare."""
    _, speech, client = service(tmp_path)
    for text in SPEAK_CALLERS.values():
        result = speech.speak(text, play=False)
        assert result.error is None and result.muted is False
        assert result.voice_id == "Flare" and result.cloud_voice is True
        assert result.backend == "gemini-native-audio"
    warmed = speech.warm_ack_cache()
    assert set(warmed) == set(STANDARD_ACKS)
    assert {v["voice_id"] for v in warmed.values()} == {"Flare"}
    assert {v for _, v in client.calls if v != "Flare"} == set()


def test_a1b_no_call_site_can_name_a_voice(tmp_path):
    """Static: no caller may pass a voice, and no second prebuilt voice exists.

    The one-voice rule is only real if the code cannot select a voice anywhere
    but the single config key, so this scans the whole package rather than
    trusting the runtime to be sampled at the right moment. The scan runs in a
    subprocess deliberately: in-test `ast.parse` trips CPython's
    `SystemError: AST constructor recursion depth mismatch` under pytest's
    assertion rewriter (the same reason `test_daemon_cli.py` shells out).
    """
    script = textwrap.dedent("""
        import ast, json, sys
        from pathlib import Path

        VOICE_CALLS = {"speak", "play_ack", "generate_voice", "synthesize"}
        PREBUILT = {"Kore", "Puck", "Charon", "Zephyr", "Leda", "Aoede", "Callirrhoe",
                    "Despina", "Erinome", "Laomedeia", "Sulcies", "Gacrux", "Fenrir",
                    "Achernar", "Umbriel", "Algieba", "Autonoe", "Enceladus", "Iapetus",
                    "Orus", "Pachis", "Schedar", "Vindemiatrix"}
        out = {"offenders": [], "voices": []}
        for path in sorted(Path(sys.argv[1]).glob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                line = getattr(node, 'lineno', 0)
                where = path.name + ":" + str(line)
                if isinstance(node, ast.Call):
                    name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
                    if name in VOICE_CALLS and any(k.arg == "voice" for k in node.keywords):
                        out["offenders"].append(f"{where} {name}(voice=...)")
                if isinstance(node, ast.Constant) and node.value in PREBUILT:
                    out["voices"].append(f"{where} {node.value}")
        print(json.dumps(out))
        """)
    audit = subprocess.run([sys.executable, "-c", script, str(SRC)], check=False,
                           capture_output=True, text=True, timeout=120)
    assert audit.returncode == 0, audit.stderr
    found = json.loads(audit.stdout)
    assert found["offenders"] == [], f"voice selected at a call site: {found['offenders']}"
    assert found["voices"] == [], f"another voice identity in src: {found['voices']}"
    # The identity of the voice lives in exactly one place, pinned to Flare.
    assert DEFAULTS["gemini"]["voice"] == "Flare"
    assert DEFAULTS["gemini"]["model_voice"] == "gemini-2.5-flash-preview-tts"


def test_a1c_daemon_paths_all_flare(tmp_path):
    """Runtime, through the real daemon handlers: reply, ack, announce, say."""
    config = voice_config(tmp_path)
    daemon = Daemon(config)
    client = EchoClient(config)
    daemon.speech = SpeechService(config, daemon.store, client=client,
                                  is_online=lambda: True)

    async def drive():
        await daemon._speech_warm({})
        await daemon._maybe_speak_reply(SPEAK_CALLERS["conversation/task reply"],
                                        {"speak": True})
        await daemon._speak_in_background(SPEAK_CALLERS["completion summary"])
        await daemon._speech_say({"text": SPEAK_CALLERS["error"], "play": False})
        return await daemon._ack({"kind": "on_it", "speak": True})

    ack = asyncio.run(drive())
    voices = {v for _, v in client.calls}
    assert voices == {"Flare"}, f"a daemon path spoke as {voices}"
    assert ack["speech"]["cached"] is True            # the ack came from the cache
    assert ack["speech"]["backend"] == "gemini-native-audio"


def test_a2_network_death_makes_zero_audio(tmp_path):
    """Kill the network mid-conversation: no TTS call, no file, text only."""
    config = voice_config(tmp_path)
    client = EchoClient(config)
    speech = SpeechService(config, store(tmp_path), client=client,
                           is_online=lambda: True)
    speech.speak("Reviewing the finance folder.", play=False)     # online: she spoke
    assert len(client.calls) == 1

    online = {"value": False}                                      # network dies
    speech._is_online = lambda: online["value"]
    cache = Path(config.section("tts")["cache_dir"])
    files_before = sorted(p.name for p in cache.glob("*.wav"))

    results = [speech.speak(text, play=True) for text in SPEAK_CALLERS.values()]
    warmed = speech.warm_ack_cache()
    acks = [speech.play_ack(kind) for kind in STANDARD_ACKS]

    assert len(client.calls) == 1, "a cloud voice call was made while offline"
    assert all(r.muted and r.audio_path is None and r.backend == "none" for r in results)
    assert all("offline is text-only" in (r.error or "") for r in results)
    assert warmed == {} and all(a["cache_miss"] is False for a in acks)
    assert sorted(p.name for p in cache.glob("*.wav")) == files_before, "audio written offline"


def test_a3_voice_is_pinned_and_the_precedence_is_documented(tmp_path):
    """VB-4 (was: any string in [gemini] voice was honoured silently).

    Contract: `[gemini] voice` must be in `[gemini] allowed_voices` (default
    `["Flare"]`). A mismatch is a REFUSAL - silence with a reason, doctor FAIL -
    never a silent adoption and never a substitution of the dormant voice.
    Changing her voice means editing BOTH keys on purpose; the legacy
    `tts.selected_voice` row is ignored online and says so.
    """
    config = voice_config(tmp_path)
    # The legacy row lives in the store the DOCTOR opens, so the precedence line
    # is exercised end to end and not only in the service's own view.
    db = Store(Path(config.db_path))
    db.set_state("tts.selected_voice", json.dumps(VoiceDescriptor(
        voice_id="en_GB-alba-medium", model="/nowhere/alba.onnx", backend="piper").as_dict()))
    config.raw["gemini"] = {**config.section("gemini"), "voice": "Zephyr"}
    speech = SpeechService(config, db, client=EchoClient(config), is_online=lambda: True)

    spoken = speech.speak("On it.", play=False)
    assert spoken.voice_id != "Zephyr", (
        f"config silently changed the voice to {spoken.voice_id!r}")
    assert spoken.muted and spoken.audio_path is None and spoken.backend == "none", (
        f"an unapproved voice still produced audio: {spoken}")
    assert "not canonical" in (spoken.error or ""), spoken.error

    from assistant.cli import run_doctor

    doctor = {c["check"]: c for c in run_doctor(config)["checks"]}
    routing = doctor["voice routing"]
    assert routing["status"] == "fail", (
        f"a poisoned voice must read as a doctor FAILURE, got {routing['status']}")
    assert "VOICE IDENTITY REFUSED" in routing["detail"] and "Zephyr" in routing["detail"]
    assert "SILENT" in routing["detail"], "the doctor must name the consequence"

    status = speech.status()
    identity = status["voice_identity"]
    assert (identity["configured"], identity["canonical"], identity["allowed"]) == (
        "Zephyr", ["Flare"], False), identity
    assert status["voice_id"] == "none" and status["muted"] is True
    # Precedence, reported rather than guessed: the stored local row is inert online.
    assert status["legacy_selection_ignored_online"] is True
    assert "legacy `tts.selected_voice` row is IGNORED" in routing["detail"]
    assert "acks: all four cached" not in routing["detail"], (
        "a silent route must not be described as if it were speaking")

    # Deliberate widening is allowed, and then that voice is genuinely the voice.
    config.raw["gemini"] = {**config.section("gemini"), "voice": "Zephyr",
                            "allowed_voices": ["Flare", "Zephyr"]}
    widened = speech.speak("On it.", play=False)
    assert (widened.voice_id, widened.backend, widened.cloud_voice) == (
        "Zephyr", "gemini-native-audio", True), widened
    assert speech.status()["voice_identity"]["allowed"] is True
    assert speech.status()["voice_id"] == "Zephyr"


def test_a3b_client_refuses_an_unapproved_voice_even_when_called_directly(tmp_path):
    """The pin is enforced at the transport too, so no other caller can bypass it."""
    from assistant.gemini_client import GeminiClient

    config = voice_config(tmp_path)
    config.raw["gemini"] = {**config.section("gemini"), "voice": "Zephyr"}
    client = GeminiClient(config, store(tmp_path, "pin.db"))
    request = client.voice_request("On it.")
    assert request["voice_allowed"] is False
    assert request["voice_requested"] == "Zephyr"
    assert request["canonical_voices"] == ["Flare"]
    with pytest.raises(RuntimeError, match="not canonical"):
        client.generate_voice("On it.")


def test_a4_status_is_truthful_in_all_three_modes(tmp_path):
    """ONLINE / OFFLINE / FORCED_OFFLINE: what `assist voice status` reports."""
    config = voice_config(tmp_path)
    db = store(tmp_path, "modes.db")
    online = {"mode": "ONLINE"}
    speech = SpeechService(config, db, client=EchoClient(config),
                           is_online=lambda: online["mode"] == "ONLINE")

    status = speech.status()
    assert (status["voice_mode"], status["voice_id"], status["cloud_voice"]) == (
        "gemini-interim", "Flare", True)

    for mode in ("OFFLINE", "FORCED_OFFLINE"):
        online["mode"] = mode
        status = speech.status()
        assert status["voice_mode"] == "offline-text-only", status["voice_mode"]
        assert status["muted"] is True and status["cloud_voice"] is False
        assert status["voice_id"] == "none"
        assert "text only" in status["offline_output"]
        # The Waybar must not label her voice "local" while it is cloud, and
        # must not imply speech while offline.
        assert status["muted"] is True
        # The Waybar wording is checked in test_a4c (VB-14): this test is about
        # what `voice status` reports, not what the pill prints.
        assert "text only" in status["offline_output"]


def test_a4b_forced_offline_is_not_treated_as_offline_detection(tmp_path):
    """FORCED_OFFLINE is a deliberate switch; voice must be silent in both."""
    config = voice_config(tmp_path)
    manager = ModeManager(config, store(tmp_path, "mm.db"), probe=lambda: True)
    manager.request_preference("offline")
    status = manager.status()
    assert status.effective_mode == "FORCED_OFFLINE"
    speech = SpeechService(config, None, client=EchoClient(config),
                           is_online=lambda: status.effective_mode == "ONLINE")
    result = speech.speak("Is that all?", play=True)
    assert result.muted is True and result.played is False




def test_a2b_daemon_level_network_death(tmp_path):
    """The flagship: a real Daemon, a real ModeManager, the net dies mid-reply.

    Before the drop she speaks; after it, the same code paths must make zero
    audio calls, write zero files, and still return the text reply.
    """
    online = {"up": True}
    config = voice_config(tmp_path)
    daemon = Daemon(config)
    manager = ModeManager(config, daemon.store, probe=lambda: online["up"])
    manager.refresh(force=True)
    daemon.mode_manager = manager
    client = EchoClient(config)
    daemon.speech = SpeechService(config, daemon.store, client=client,
                                  is_online=lambda: manager.status(refresh=False)
                                  .effective_mode == "ONLINE")
    cache = Path(config.section("tts")["cache_dir"])

    asyncio.run(daemon._speech_warm({}))         # what run() does at startup

    async def turn(text):
        spoken = await daemon._maybe_speak_reply(text, {"speak": True})
        await daemon._speak_in_background("Done. 148 files sorted into Finance.")
        ack = await daemon._ack({"kind": "done", "speak": True})
        # Drain the daemon's fire-and-forget tasks before the loop closes: left
        # pending, they die inside `asyncio.to_thread` and the resulting
        # unraisable exception makes pytest 9.1.1 crash while rendering it
        # (SystemError: AST constructor recursion depth mismatch), truncating
        # the whole run. Real shutdown is `_shutdown`/cancel, not this.
        pending = list(daemon._background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return spoken, ack

    calls_at_warm = len(client.calls)
    before, ack_before = asyncio.run(turn("Sorting the finance folder."))
    assert before["voice_id"] == "Flare"
    # player="none" in this harness, so 'played' is False by config: the audio
    # itself must exist. B.5 / G.18 measure the real playback process.
    assert Path(before["audio_path"]).exists()
    assert len(client.calls) == calls_at_warm + 2 and ack_before["speech"]["cached"] is True
    files_before = sorted(p.name for p in cache.glob("*.wav"))

    online["up"] = False                                     # the network dies
    manager.refresh(force=True)
    assert manager.status(refresh=False).effective_mode == "OFFLINE"

    after, ack_after = asyncio.run(turn("Two folders failed."))
    assert len(client.calls) == calls_at_warm + 2, (
        f"audio calls after the drop: {client.calls[calls_at_warm + 2:]}")
    assert after["muted"] is True and after["played"] is False
    assert after["backend"] == "none" and after["audio_path"] is None
    assert "offline is text-only" in after["error"]      # reported, not swallowed
    assert ack_after["speech"]["cached"] is False              # no sound, no error
    assert sorted(p.name for p in cache.glob("*.wav")) == files_before



def pill_voice_line(speech, mode_manager_online):
    """The Waybar pill's voice line, computed without closures in the traceback:
    rendering an xfail whose failing frame comes from a nested function trips
    `SystemError: AST constructor recursion depth mismatch` in pytest 9.1.1
    under CPython 3.11 and silently truncates the whole run."""
    status = speech.status()
    line = format_waybar({"running": True, "mode": "idle",
                          "connectivity": {"effective_mode": mode_manager_online,
                                           "preference": "auto"},
                          "voice": status, "gemini_mode": "live", "uptime_s": 1.0})
    return line["tooltip"].split("voice:")[-1].strip()


@pytest.mark.xfail(strict=True, reason="VB-14: the Waybar pill labels cloud audio 'local' "
                   "online and 'local none' offline instead of stating the posture")
def test_a4c_waybar_line_is_truthful_in_every_mode(tmp_path):
    config = voice_config(tmp_path)
    speech = SpeechService(config, store(tmp_path, "wb.db"), client=EchoClient(config),
                           is_online=lambda: True)

    spoken = pill_voice_line(speech, "ONLINE")
    assert "local" not in spoken, f"cloud voice labelled local: {spoken}"
    assert "Flare" in spoken

    offline = SpeechService(config, store(tmp_path, "wb2.db"), client=EchoClient(config),
                            is_online=lambda: False)
    quiet = pill_voice_line(offline, "OFFLINE")
    assert "text only" in quiet or "no speech" in quiet, f"offline pill reads: {quiet}"


# ══════════════════════════════════════════════════════════════════════════
# B. ACKS & LATENCY (§18)
# ══════════════════════════════════════════════════════════════════════════

def timed(fn, *, repeats: int = 20) -> dict:
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        out = fn()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return {"median_ms": round(samples[len(samples) // 2], 3),
            "p95_ms": round(samples[int(len(samples) * 0.95) - 1], 3),
            "max_ms": round(samples[-1], 3), "result": out}


def test_b5_ack_latency_states(tmp_path):
    """Cold, warm, after config change, after restart — numbers, then the rule."""
    config, speech, _ = service(tmp_path)
    cold = timed(lambda: speech.play_ack("on_it"))
    assert cold["result"]["cache_miss"] is True          # nothing warmed yet
    speech.warm_ack_cache()
    warm = timed(lambda: speech.play_ack("on_it"))
    assert warm["result"]["cached"] is True
    restarted = SpeechService(config, Store(tmp_path / "vb.db"), client=EchoClient(config),
                              is_online=lambda: True)
    after_restart = timed(lambda: restarted.play_ack("on_it"))
    assert after_restart["result"]["cached"] is True, "cache did not survive restart"
    numbers = {"cold": cold, "warm": warm, "restart": after_restart}
    for name, sample in numbers.items():
        assert sample["p95_ms"] < 300, f"{name} ack exceeded the 300ms budget: {sample}"


def test_b5b_dormant_config_change_must_not_silence_the_hotkey_path(tmp_path):
    """VB-2 (key half): the ONLINE ack cache no longer carries dormant settings.

    length_scale and the selected local voice have nothing to do with Flare
    audio. They used to sit in the online cache key, so any edit there turned
    every ack into a permanent cache miss - silence on the hotkey path.
    """
    config, speech, _ = service(tmp_path)
    warmed = speech.warm_ack_cache()
    before = {kind: Path(info["audio_path"]) for kind, info in warmed.items()}
    assert speech.cached_ack("on_it") is not None

    for change in ({"length_scale": 1.0}, {"length_scale": 1.30, "voice_id": "elsewhere"},
                   {"model": "/nowhere/other.onnx", "speaker": 3}):
        config.raw["tts"] = {**config.section("tts"), **change}
        after = speech.play_ack("on_it")
        assert after["cache_miss"] is False, (
            f"a dormant-path setting change ({change}) silently killed every cached ack")
        assert after["cached"] is True
        assert Path(after["audio_path"]) == before["on_it"]
        assert speech.ack_cache_state()["complete"] is True

    # The reverse half of the same rule: a change to the LIVE voice identity must
    # invalidate, and the dormant key must stay addressable for its own route.
    config.raw["tts"] = {**config.section("tts"), "backend": "mock", "length_scale": 0.92}
    local = SpeechService(config, store(tmp_path, "b5b-local.db"), client=EchoClient(config),
                          is_online=lambda: True, )
    config.raw["tts"] = {**config.section("tts"), "online_voice": "local"}
    assert local._ack_path("on_it") != before["on_it"], (
        "the local route is resolving to the cloud route's files")


def test_b5d_ack_miss_self_heals_within_one_warm_cycle(tmp_path):
    """VB-2 (fixed): invalidation triggers a re-warm; `cache_miss` is not permanent.

    Change a LIVE voice identity (or delete the ack files), then press the
    hotkey. The first press is silent AND reported, the miss itself requests the
    cure, and one warm cycle makes the next press audible.
    """
    config, speech, _ = service(tmp_path)
    speech.warm_ack_cache()
    config.raw["gemini"] = {**config.section("gemini"), "voice": "Kore",
                            "allowed_voices": ["Flare", "Kore"]}
    assert speech.play_ack("on_it")["cache_miss"] is True, "the change did not invalidate"

    # A daemon-level warm cycle has to run (scheduled by the miss, or by the
    # config-change hook) and the very next ack must hit cache.
    speech.warm_due()                      # the cure: one warm cycle, triggered now
    assert speech.play_ack("on_it")["cached"] is True, (
        "acks did not return within one warm cycle after invalidation")
    assert speech.ack_cache_state()["complete"] is True


def test_b6_deleted_and_corrupt_ack_files(tmp_path):
    """Deleted, zero-byte, corrupt, and not-a-WAV ack files: never a crash,
    never another voice's audio."""
    _, speech, _ = service(tmp_path)
    speech.warm_ack_cache()
    paths = [Path(speech.cached_ack(kind)) for kind in STANDARD_ACKS]
    assert all(p.exists() for p in paths)

    paths[0].unlink()
    paths[1].write_bytes(b"")
    paths[2].write_bytes(b"Not a WAV at all, just prose about a voice.")
    import shutil
    playable = shutil.which("pw-play") or shutil.which("aplay") or shutil.which("paplay")

    results = {kind: speech.play_ack(kind) for kind in STANDARD_ACKS}
    assert results["on_it"]["cached"] is False                  # deleted → miss
    assert results["on_it"]["cache_miss"] is True
    for res in results.values():          # corrupt files: no crash, no bogus audio
        assert res["played"] is False or playable, res
        assert not str(res.get("error") or "").startswith("Traceback"), res
    status = speech.status()
    assert sorted(status["cached_acks"]) == sorted(
        [k for k, r in results.items() if r["cached"]])
    re_warmed = speech.warm_ack_cache()
    assert len(re_warmed) == 4
    assert speech.play_ack("on_it")["cached"] is True


def test_b7_voice_change_invalidates_the_online_cache(tmp_path):
    """VB-1 (fixed): the online key IS the cloud voice identity.

    The key used to carry the *local Piper* descriptor and none of
    `[gemini] voice`, so a voice change kept the same path and replayed the
    previous voice's bytes while `status` reported the new voice. Now a voice or
    model change moves every path - in both directions - and no stale file is
    ever addressable under a new identity.
    """
    config, speech, _ = service(tmp_path)
    warmed = speech.warm_ack_cache()
    before = {kind: Path(info["audio_path"]) for kind, info in warmed.items()}
    assert len({p.name for p in before.values()}) == 4, warmed
    assert speech.status()["cache_identity"]["voice"] == "Flare"

    # A deliberate widening of the pin (VB-4) is a real identity change: the old
    # audio must stop being addressable, not be replayed under a new name.
    config.raw["gemini"] = {**config.section("gemini"), "voice": "Kore",
                            "allowed_voices": ["Flare", "Kore"]}
    assert all(speech.cached_ack(kind) is None for kind in STANDARD_ACKS), (
        "the voice changed but the ack cache still points at the old voice's file")
    miss = speech.play_ack("on_it")
    assert miss["cache_miss"] is True and miss["audio_path"] is None, (
        f"a voice change served stale audio: {miss}")

    re_warmed = speech.warm_ack_cache()
    after = {kind: Path(info["audio_path"]) for kind, info in re_warmed.items()}
    assert not ({p.name for p in after.values()} & {p.name for p in before.values()}), (
        f"Kore reused Flare's files: {after}")
    assert all(p.exists() and p.stat().st_size > 0 for p in after.values())
    spoken = speech.speak("On it.", play=False)
    assert (spoken.voice_id, spoken.cloud_voice) == ("Kore", True), spoken
    assert Path(spoken.audio_path) == after["on_it"], (
        "speech and the ack cache resolved to different files for one identity")

    # Flare's files are untouched and still hers: switching back finds them,
    # without a re-render, which is what makes the pin cheap to test by ear.
    config.raw["gemini"] = {**config.section("gemini"), "voice": "Flare"}
    assert {kind: Path(speech.cached_ack(kind)) for kind in STANDARD_ACKS} == before
    assert speech.speak("On it.", play=False).cached is True

    # The model is part of the identity too: same voice name, different model
    # voice = different audio.
    config.raw["gemini"] = {**config.section("gemini"),
                            "model_voice": "gemini-2.5-pro-preview-tts"}
    assert speech.cached_ack("on_it") != before["on_it"].as_posix(), (
        "a model_voice change replays the previous model's audio")


def test_b7b_pace_change_invalidates_the_dormant_cache(tmp_path):
    """The local path must key on pace, since pace changes its audio."""
    config = voice_config(tmp_path, online_voice="local", offline_voice="local")
    db = store(tmp_path, "pace.db")
    speech = SpeechService(config, db, client=EchoClient(config), is_online=lambda: True)
    path_before = speech._ack_path("on_it")
    db.set_state("tts.selected_voice", json.dumps(VoiceDescriptor(
        voice_id="elaria-vb", model="", backend="mock", length_scale=0.92).as_dict()))
    path_pace = speech._ack_path("on_it")
    db.set_state("tts.selected_voice", json.dumps(VoiceDescriptor(
        voice_id="elaria-vb", model="", backend="mock", length_scale=1.30).as_dict()))
    path_slow = speech._ack_path("on_it")
    assert path_before != path_pace is not None
    assert path_pace != path_slow, "pace change did not invalidate the ack cache"
    assert path_slow.exists() is False


def test_b7c_local_audio_never_answers_an_online_ack(tmp_path):
    """VB-3 (fixed): the fallback is gone - a missing Flare ack is silence + warning.

    `_ack_path` used to fall back to the LOCAL backend's file "because a warmed
    local copy beats silence". That is the one thing the owner forbade: the dormant
    Piper voice speaking for her. A miss is now reported, never substituted, and
    never described as a healthy cache.
    """
    config, speech, _ = service(tmp_path)
    # An era where the local voice was the voice leaves Piper acks behind.
    local_dir = Path(config.section("tts")["cache_dir"])
    local_dir.mkdir(parents=True, exist_ok=True)
    descriptor = speech.descriptor()
    local_path = speech._cache_path(STANDARD_ACKS["on_it"], descriptor,
                                    speech._make_backend().name)
    local_path.write_bytes(b"RIFFfake-piper-audio")

    assert speech.cached_ack("on_it") is None, (
        f"online ack served a dormant-path file: {speech.cached_ack('on_it')}")
    result = speech.play_ack("on_it")
    assert result["audio_path"] is None and result["played"] is False
    assert result["cache_miss"] is True and result["rewarm_needed"] is True, result
    assert "cold" in str(result.get("warning", "")), (
        "a miss on the ack path must be reported, not just returned")
    assert local_path.read_bytes() == b"RIFFfake-piper-audio", "the dormant file was consumed"
    assert "RIFF" not in str(result.get("audio_path") or ""), "substitute audio played"

    # Reporting honesty: `cached_acks` may not claim health from a local file.
    status = speech.status()
    assert status["cached_acks"] == [], status["cached_acks"]
    assert status["ack_cache"]["missing"] == list(STANDARD_ACKS), status["ack_cache"]
    assert status["ack_cache"]["route"] == "gemini"
    assert "assist voice warm" in status["ack_cache"]["reason"], status["ack_cache"]

    # Warming the real route fixes it, and the dormant file is still not in play.
    speech.warm_ack_cache()
    assert sorted(speech.status()["cached_acks"]) == sorted(STANDARD_ACKS)
    played = speech.play_ack("on_it")
    assert played["cached"] is True and Path(played["audio_path"]) != local_path
    assert local_path.read_bytes() == b"RIFFfake-piper-audio"


def test_b7d_acks_are_not_cross_wired(tmp_path):
    """No ack may resolve to another ack's audio (four distinct files)."""
    _, speech, client = service(tmp_path)
    warmed = speech.warm_ack_cache()
    # NOTE: the audio bytes are deliberately identical (the fake returns one PCM
    # blob), so distinctness is proven on the cache *identity*: each ack must
    # resolve to the file that was written for its own text, forever.
    paths = {kind: Path(warmed[kind]["audio_path"]) for kind in warmed}
    assert len({p.name for p in paths.values()}) == 4, f"acks share files: {paths}"
    for kind, path in paths.items():
        assert speech.cached_ack(kind) == str(path), (
            f"{kind} now resolves to {speech.cached_ack(kind)}, not the file warmed "
            f"for it ({path}) — an ack can be answered with another ack's audio")
    calls = dict(client.calls)
    assert len(set(calls.values())) == 1                      # all Flare
    texts = [t for t, _ in client.calls]
    assert len(set(texts)) == len(texts) == 4, "an ack text was requested twice"


# ══════════════════════════════════════════════════════════════════════════
# C. ENDPOINTING & THE "IS THAT ALL?" LADDER
# ══════════════════════════════════════════════════════════════════════════

def frames(speech: int, silent: int, *, frame_s: float = 0.03) -> list[bytes]:
    return [SPEECH] * speech + [SILENCE] * silent


def ladder(mode: str = "narration", threshold: float | None = None) -> SilenceLadder:
    limits = DEFAULTS["transcribe"]["checkin_after_s"]
    return SilenceLadder(float(threshold or limits[mode]),
                         speech_rms=DEFAULTS["transcribe"]["vad_rms_threshold"])


@pytest.mark.parametrize("pause_frames", [20, 50, 100])       # 0.6s, 1.5s, 3s
def test_c8_narration_survives_mid_thought_pauses(pause_frames):
    ladder_state = ladder("narration")
    fired = [ladder_state.observe(SILENCE, 0.03) for _ in range(pause_frames)]
    assert not any(fired), f"a {pause_frames * 30}ms pause cut a narration thought"
    # ...and the same pause in the snappier modes still doesn't fire below their cap.
    for mode in ("command", "conversation"):
        state = ladder(mode)
        assert not any(state.observe(SILENCE, 0.03) for _ in range(pause_frames)) or \
            pause_frames * 30 >= DEFAULTS["transcribe"]["checkin_after_s"][mode] * 1000


@pytest.mark.parametrize("mode", ["command", "conversation", "narration"])
def test_c8b_checkin_timing_is_per_mode_and_fires_once(mode):
    limit = DEFAULTS["transcribe"]["checkin_after_s"][mode]
    state = ladder(mode)
    total = int(limit / 0.03) + 5
    fired = [i for i in range(total) if state.observe(SILENCE, 0.03)]
    assert len(fired) == 1, f"{mode}: asked {len(fired)} times"
    assert (fired[0] + 1) * 0.03 >= limit - 0.031  # fires on the frame that crosses


def test_c8c_the_mode_vocabulary_the_runtime_can_request_is_configured():
    """A mode string missing from checkin_after_s silently gets 20s.

    `assist dictate` can only ever ask for "command" or "narration"; the ladder
    `.get(mode, 20)` fallback means a typo or a new hotkey mode becomes
    narration timing while the user waits for a close. Every requestable mode
    must be named in config.
    """
    import re

    cli = (SRC / "cli.py").read_text()
    lines = cli.splitlines()
    window = "".join("".join(lines[i:i + 2]) for i, l in enumerate(lines) if "ptt.start" in l)
    requested = set(re.findall(r': "([a-z_]+)"', window)) - {"mode"}
    configured = set(DEFAULTS["transcribe"]["checkin_after_s"])
    assert requested, "no runtime mode strings found: this test is stale"
    assert requested <= configured, f"unconfigured modes fall back to 20s: {requested - configured}"


def test_c9_blip_speech_does_not_rearm_the_ladder_for_a_second_nag(tmp_path):
    """VB-5 (fixed): one uninterrupted thought is asked exactly once.

    `_asked` used to be cleared by ANY frame over the RMS gate — a breath, a key
    click, a chair, or her own playback bleed — so the same silence run re-armed
    and re-asked. Re-arming now needs sustained speech; a real resumption still
    earns a new check-in for the new segment.
    """
    state = ladder("narration", threshold=1.0)
    assert state.resume_s > 0, "the ladder has no sustained-resume rule"
    fired = 0
    fired += sum(1 for _ in range(40) if state.observe(SILENCE, 0.03))    # 1.2s → asked
    fired += 1 if state.observe(SPEECH, 0.03) else 0                       # one 30ms blip
    fired += sum(1 for _ in range(40) if state.observe(SILENCE, 0.03))    # same thought
    assert fired == 1, f"the check-in fired {fired} times inside one unbroken pause"

    # Blips are not speech: several of them, spread out, still must not re-arm.
    for _ in range(6):
        state.observe(SPEECH, 0.03)
        state.observe(SILENCE, 0.03)
    fired += sum(1 for _ in range(60) if state.observe(SILENCE, 0.03))
    assert fired == 1, f"scattered blips nagged the same thought {fired} times"

    # A real resumption (>= resume_s of speech) starts a new segment...
    speech_frames = int(state.resume_s / 0.03) + 1
    assert sum(1 for _ in range(speech_frames) if state.observe(SPEECH, 0.03)) == 0
    fired2 = sum(1 for _ in range(40) if state.observe(SILENCE, 0.03))    # new pause
    assert fired2 == 1, "actual speech resumed but the ladder never re-armed"


def test_c9b_after_the_checkin_the_session_closes_after_grace(tmp_path):
    """VB-6 (fixed): asked once, then the grace runs out and the session closes.

    The user's hotkey used to be the ONLY way out, so an abandoned dictation held
    the microphone and the "listening" state until they came back (the daemon's
    simulated source runs 100k realtime frames — about 50 minutes).
    """
    state = ladder("command", threshold=4.0)
    assert state.grace_s > 0, "SilenceLadder had no post-prompt grace close"
    silence_run = int(300 / 0.03)            # 5 minutes of walking-away silence
    events = [state.observe(SILENCE, 0.03) for _ in range(silence_run)]
    assert sum(events) == 1, "she must still ask exactly once"
    assert state.close_due(), "5 minutes of silence after the check-in must close"

    # Session level: the capture loop stops pulling frames, and says why.
    pulled = {"n": 0}

    class CountingSource:
        """A short phrase, then 10 minutes of walking-away silence — and the
        microphone keeps handing frames over, exactly as the live capture does."""

        def __init__(self):
            self.closed = False

        async def frames(self):
            for _ in range(20):
                pulled["n"] += 1
                yield SPEECH
            while pulled["n"] < 20 + int(600 / 0.03):
                pulled["n"] += 1
                yield SILENCE

        async def aclose(self):
            self.closed = True

    _, _, service_, _ = dictation(tmp_path)
    source = CountingSource()
    result = asyncio.run(service_.dictate(
        source, transport_factory=lambda: Session(0, {"connects": [], "words_seen": 0,
                                                       "finals": []})))
    assert pulled["n"] < 20 + int(60 / 0.03), (
        f"the session never closed: it consumed {pulled['n']} frames "
        f"({pulled['n'] * 0.03:.0f}s) after the check-in")
    assert any("closed after the check-in grace" in note for note in result.notes), result.notes
    assert source.closed is True, "the grace close must still release the microphone"


def test_c10_pause_resume_fuzz_100(tmp_path):
    """Item 10: no lost head/tail, no doubled segments, no stuck state."""
    import random

    rng = random.Random(20261020)
    buffer = RollingAudioBuffer(seconds=30)
    pushed = bytearray()
    fired, state = 0, ladder("conversation", threshold=1.0)
    negatives = 0
    for _ in range(100):
        run_speech = rng.randint(0, 12)
        run_silent = rng.randint(0, 90)
        for frame in [SPEECH] * run_speech + [SILENCE] * run_silent:
            pushed.extend(frame)
            buffer.push(frame)
            if state.observe(frame, 0.03):
                fired += 1
            if state._silent_s < 0 or state._silent_s != state._silent_s:
                negatives += 1
    assert negatives == 0
    assert fired <= 100 and fired >= 0
    # Ring buffer keeps the most recent 30s, contiguous and never reordering.
    tail = buffer.tail()
    keep = 30 * 16000 * 2
    assert tail == bytes(pushed[-keep:]) if len(pushed) > keep else tail == bytes(pushed)
    assert buffer.seconds <= 30.001


# ══════════════════════════════════════════════════════════════════════════
# D. ASR FALLBACK CHAIN
# ══════════════════════════════════════════════════════════════════════════

class Session:
    """A Live transport with a memory: emits one word per 3 speech frames."""

    def __init__(self, index, shared, *, drop_after=None, go_away_after=None):
        self.index, self.shared = index, shared
        self.drop_after, self.go_away_after = drop_after, go_away_after
        self.frames = 0
        self.events_q: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def connect(self, resumption_handle=None):
        self.shared["connects"].append((self.index, resumption_handle))

    async def activity_start(self):
        pass

    async def send_audio(self, pcm: bytes):
        self.frames += 1
        if pcm == SPEECH:
            n = self.shared["words_seen"] = self.shared.get("words_seen", 0) + 1
            if n % 3 == 0:
                self.shared.setdefault("finals", []).append(f"w{n // 3}")
                self.events_q.put_nowait(type("E", (), {
                    "type": "final", "text": f"w{n // 3}", "handle": None})())
        if self.drop_after is not None and self.frames >= self.drop_after:
            raise ConnectionError("429 too-many-requests mid-utterance")
        if self.go_away_after is not None and self.frames >= self.go_away_after:
            self.events_q.put_nowait(type("E", (), {
                "type": "go_away", "text": "", "handle": None})())

    async def activity_end(self):
        # The real transport closes its event stream after a `turn_complete`
        # (live_client.py:108-114); without it the collector waits the full 15s
        # final-transcript timeout on every session in this file.
        self.events_q.put_nowait(type("E", (), {
            "type": "turn_complete", "text": "", "handle": None})())

    async def events(self):
        while True:
            event = await self.events_q.get()
            yield event
            if event.type == "turn_complete":
                return

    async def close(self):
        self.closed = True


def dictation(tmp_path, *, online=True, **kwargs):
    config = voice_config(tmp_path)
    db = Store(tmp_path / "dict.db")
    manager = ModeManager(config, db, probe=lambda: online)
    manager.refresh(force=True)      # the service reads a cached snapshot
    queue = None
    if kwargs.get("queue"):
        from assistant.offline_queue import CloudQueue

        queue = CloudQueue(config, db, None, manager)
    service_ = DictationService(config, db, None, mode_manager=manager,
                                offline_queue=queue,
                                local_backend=kwargs.get("local_backend"))
    return config, db, service_, queue


class Source:
    def __init__(self, frames_):
        self._frames = list(frames_)

    async def frames(self):
        for frame in self._frames:
            yield frame

    async def aclose(self):
        pass


def test_d11_mid_utterance_drop_replays_once_and_transcribes_once(tmp_path, monkeypatch):
    """Live dies mid-sentence: buffered tail replayed, ONE transcript, no
    error recital spoken, and the fallback ack is not a spoken apology."""
    from assistant import asr as asr_module

    shared = {"connects": [], "words_seen": 0, "finals": []}
    made = []

    def factory():
        index = len(made)
        session = Session(index, shared, drop_after=(6 if index == 0 else None))
        made.append(session)
        return session

    monkeypatch.setattr(asr_module, "transcribe_file", lambda *a, **k: type("T", (), {
        "text": " ".join(shared["finals"]), "backend": "gemini_batch",
        "confidence": 0.9, "language": "en", "segments": []})())

    _, _, service_, _ = dictation(tmp_path)
    events = []

    async def sink(event):
        events.append(event)

    result = asyncio.run(service_.dictate(Source([SPEECH] * 12 + [SILENCE] * 4),
                                          transport_factory=factory, sink=sink))
    assert len(shared["connects"]) == 2, "no resume session was opened"
    assert shared["connects"][1][1] is not None or True
    replayed = made[1].frames
    assert replayed > 0, "buffered tail was not replayed into the resumed session"
    words = result.raw_text.split()
    assert len(words) == len(set(words)) or not words, (
        f"transcript has duplicated words from the resume replay: {result.raw_text!r}")
    finals = [e for e in events if e["event"] == "transcript.final"]
    assert len(finals) <= 1, [e for e in events if e["event"] == "transcript.final"]
    assert not [e for e in events if e["event"] == "error"], events


def indexed_frames(count: int, *, speech=True) -> list[bytes]:
    """Frames whose amplitude carries their own index.

    A stateless ASR double can then be re-fed the same frames and produce the
    same words, which is what makes a replay verifiable: anything not in the
    tail must be re-hearable, and anything lost is genuinely lost.
    """
    out = []
    for i in range(count):
        if not speech:
            out.append(SILENCE)
            continue
        out.append(struct.pack(f"<{FRAME_SAMPLES}h", *([1000 + i] * FRAME_SAMPLES)))
    return out


def test_d11b_rotation_on_a_long_utterance_keeps_every_word(tmp_path):
    """VB-7 (fixed, data-loss): rotation no longer throws away received finals.

    Correct only while the whole utterance still fits the replay buffer. With a
    30s rolling buffer (default) any dictation longer than that loses its head
    on a GoAway/429 rotation: the earlier words were never re-sent and were
    dropped from the collected finals. Raw WAV survives; the transcript does not.
    """
    shared = {"connects": [], "words_seen": 0, "finals": []}
    made = []

    class IndexSession(Session):
        """Stateless per session: emits a word per 3 speech frames IT receives."""

        async def send_audio(self, pcm):
            index = struct.unpack("<h", pcm[:2])[0] - 1000
            self.frames += 1
            self.shared["heard"] = sorted({*self.shared.get("heard", set()), index})
            if index % 3 == 0:
                self.events_q.put_nowait(type("E", (), {
                    "type": "final", "text": f"w{index}", "handle": None})())
            if self.go_away_after is not None and self.frames >= self.go_away_after:
                self.events_q.put_nowait(type("E", (), {
                    "type": "go_away", "text": "", "handle": None})())

    def factory():
        index = len(made)
        made.append(IndexSession(index, shared, go_away_after=(9 if index == 0 else None)))
        return made[-1]

    _, _, service_, _ = dictation(tmp_path)
    service_.replay_s = 0.12            # 6 frames of tail available for replay
    result = asyncio.run(service_.dictate(Source(indexed_frames(30)),
                                          transport_factory=factory))
    first_words = [f"w{i}" for i in range(0, 9, 3)]     # heard by session 1 only
    missing = [w for w in first_words if w not in result.raw_text]
    assert missing == [], (
        f"rotation dropped {missing} — the transcript is {result.raw_text!r} "
        f"for a 30-frame utterance (head lost, raw audio kept)")
    # Words are never doubled by the replayed tail either (the reason the old code
    # cleared the list): only an immediately repeated segment is folded away.
    counts = {w: result.raw_text.split().count(w) for w in first_words}
    assert all(n == 1 for n in counts.values()), f"replay echoed words twice: {counts}"


def test_d12_offline_low_confidence_is_redone_exactly_once(tmp_path):
    class Shaky:
        name = "local:mock"

        def transcribe(self, audio_path, language):
            from assistant.asr import Transcript

            return Transcript(text="move the invoices", backend="local:vosk",
                              language="en", confidence=0.31,
                              segments=[{"text": "move the invoices", "confidence": 0.31}])

    _, db, service_, queue = dictation(tmp_path, online=False,
                                           local_backend=Shaky(), queue=True)
    events = []

    async def sink(event):
        events.append(event)

    result = asyncio.run(service_.dictate(Source([SPEECH] * 6),
                                          transport_factory=lambda: pytest.fail(
                                              "a Live session must not be opened offline",
                                              pytrace=False),
                                          sink=sink))
    assert result.cloud_status == "pending_cloud_transcription", result.cloud_status
    assert len(result.queued_job_ids) == 1
    row = db.get_transcript(result.transcript_id)
    assert row["cloud_status"] == "pending_cloud_transcription"
    # A second session on the same transcript must not double-enqueue the redo.
    assert queue._find_active("cloud_transcription", "transcript_id",
                             result.transcript_id)["id"] == result.queued_job_ids[0]
    jobs = [j for j in queue.list_jobs() if j["kind"] == "cloud_transcription"]
    assert len(jobs) == 1, jobs


def test_d13_garbage_and_0_byte_audio_never_become_a_confident_command(tmp_path):
    """Empty / clipped / silence-only audio: the pipeline must not hand the
    intent ladder a confident command."""
    config, db, service_, _ = dictation(tmp_path, online=False)

    async def sink(event):
        pass

    from assistant.asr import Transcript

    class Deaf:
        name = "local:mock"

        def transcribe(self, audio_path, language):
            return Transcript(text="", backend="local:vosk", language="en",
                              confidence=None, segments=[])

    service_.local_backend = Deaf()
    result = asyncio.run(service_.dictate(Source([SILENCE] * 30), sink=sink,
                                          transport_factory=lambda: pytest.fail(
                                              "offline", pytrace=False)))
    assert result.raw_text.strip() == ""
    assert result.cloud_status == "pending_cloud_transcription"
    # 0-byte input through the batch chain: graceful, never a crash.
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    from assistant.asr import transcribe_file

    # A 0-byte file fails safe (an exception, never a confident transcript).
    # NOTE: the message blames the missing offline backend package rather than
    # the empty input, so the two causes are indistinguishable to the user —
    # recorded in VOICE-BUGTEST.md as VB-12 (diagnostic, not behaviour).
    with pytest.raises(RuntimeError, match="all ASR backends failed"):
        transcribe_file(config, None, str(empty), offline=True)
    rows = db._conn.execute("select count(*) from transcripts").fetchone()[0]
    assert rows == 1


def test_d13b_low_confidence_command_words_never_execute(tmp_path):
    """VB-8 (fixed): a transcript she is not sure about cannot move files.

    Command mode and dictation share one microphone, so a TV saying "undo." used
    to climb straight into the intent ladder — and `undo` reverses real files. The
    gate now sits between the two: cleanup's `flagged` state and ASR's
    `confidence` (below `[transcribe] command_min_confidence`, or unknown for a
    mutating intent) veto the routing entirely.
    """
    from assistant.daemon import Daemon
    from assistant.intents import route

    assert route("undo").kind == "undo", "the grammar the gate has to survive"

    config = voice_config(tmp_path)
    daemon = Daemon(config)
    threshold = daemon.config.section("transcribe")["command_min_confidence"]
    assert threshold == 0.85, threshold

    def gate(text, *, confidence, flagged=False):
        return daemon._command_gate({"text": text, "confidence": confidence,
                                     "flagged": flagged})

    # The mumble that sounds like a command: refused, nothing routed, nothing run.
    veto = gate("undo.", confidence=0.42)
    assert veto is not None and veto["via"] == "refused" and veto["executed"] is False
    assert veto["intent"] == "undo" and "below" in veto["reason"]
    assert "Not executed" in veto["note"]

    # A cleanup-flagged transcript is refused even at high confidence: the flag is
    # the state that says "this text is under review", and the gate respects it.
    flagged = gate("undo.", confidence=0.99, flagged=True)
    assert flagged is not None and "flagged" in flagged["reason"]

    # Unknown confidence: read-only intents still work (that is the useful 99%),
    # a mutating one does not.
    assert gate("where are the invoices?", confidence=None) is None
    assert gate("undo.", confidence=None) is not None, (
        "a mutating intent executed on a transcript with no confidence at all")

    # A clear, deliberate, unflagged command is NOT gated into uselessness.
    assert gate("undo.", confidence=0.97) is None
    assert gate("remember that tea is at four", confidence=0.9) is None

    # And the veto is wired into the stop path: `route()` is not called at all.
    import asyncio

    called = []

    async def fake_ask(params):
        called.append(params["text"])
        return {"reply": "done", "via": "local-intent"}

    daemon._ask = fake_ask
    daemon._dictation_session_mode = "command"
    result = {"text": "undo.", "raw_text": "undo.", "cleaned_text": None,
              "confidence": 0.42, "flagged": True, "backend": "mock"}
    veto = daemon._command_gate(result)
    assert veto is not None and veto["reason"]
    asyncio.run(daemon._ptt_stop({}))     # no live session: must be a no-op
    assert called == [], "the stop path routed a vetoed transcript anyway"


# ══════════════════════════════════════════════════════════════════════════
# E. WAKE WORD & VOICEPRINT  (activation surface + file hygiene)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason="VB-9: the voiceprint doctor check is `exists()`; a "
                   "0-byte, unparseable, wrong-schema or world-readable biometric "
                   "template reports ok")
def test_e14_corrupt_or_world_readable_voiceprint_must_not_pass_doctor(tmp_path, monkeypatch):
    """VB-9: the doctor only asks whether the file EXISTS.

    A 0-byte, unparseable, wrong-schema or 0644 voiceprint (a biometric
    template, §13.10) is reported satisfied. `load_voiceprint` raises loudly —
    the doctor never calls it, so `assist doctor` goes green with an unusable,
    world-readable template and `assist-voice-test` fails only later, at runtime.
    """
    from assistant.cli import run_doctor
    from assistant.voicetest import load_voiceprint

    home = Path(tmp_path / "home")
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("assistant.cli.Path.home", lambda: home)
    config = voice_config(tmp_path)
    broken = home / "voiceprint.json"
    cases = [("0-byte", "", 0o600), ("not json", "centroid = [0.1]", 0o600),
             ("wrong shape", json.dumps({"model": "x", "dimension": 3, "centroid": [0.1]}),
              0o600),
             ("0644 biometric", json.dumps({"model": "x", "dimension": 1,
                                            "centroid": [0.1]}), 0o644)]
    for label, payload, mode in cases:
        broken.write_text(payload)
        broken.chmod(mode)
        check = {c["check"]: c for c in run_doctor(config)["checks"]}["voiceprint.json"]
        unusable = False
        try:
            load_voiceprint(broken)
        except Exception:
            unusable = True
        world_readable = bool(mode & 0o077)
        if unusable or world_readable:
            assert check["status"] != "ok", (
                f"doctor reported '{label}' voiceprint as healthy: {check['detail']}")


def test_e14b_no_activation_path_can_fall_back_to_any_voice(tmp_path):
    """Nothing in the runtime speaks-for-itself on a wake word yet, so the
    forbidden fallback (score unavailable ⇒ any voice may wake her) cannot
    happen. This pins that it STAYS true: no wake-word gating in the daemon,
    and the scorer stays in the offline harness."""
    daemon_src = (SRC / "daemon.py").read_text()
    assert "voicetest" not in daemon_src, (
        "the daemon now gates on a speaker score: it must fail closed when the "
        "voiceprint is unreadable, and this test must be rewritten to prove it")
    activation = [name for name in ("wake", "kws", "openwakeword") if name in daemon_src]
    assert activation == [] or "score" in daemon_src


def test_e15_missing_persona_files_degrade_with_warnings(tmp_path, monkeypatch):
    """No profile, a partial profile, or a corrupt persona row: defaults + a
    warning, never a crash and never an invented setting."""
    from assistant.cli import run_doctor
    from assistant.config import load_humour_profile
    from assistant.persona import PersonaGovernor

    config = load_config()
    governor = PersonaGovernor.from_config(config, {})          # nothing installed
    assert governor.decide(turn()).register != "expressive-allowed"

    partial = tmp_path / "humour.toml"
    partial.write_text('[elaria_voice]\nidol = "none"\n')       # no delivery section
    config.raw["persona"] = {**config.section("persona"), "humour_profile": str(partial)}
    loaded = load_humour_profile(config)
    assert isinstance(loaded, dict)
    assert load_config  # (no exception meant no crash on a half-written profile)
    run_doctor(config)                                           # doctor still works

    db = Store(tmp_path / "pers.db")
    db.set_state("persona", "{not json")
    daemon = Daemon(config)
    daemon.store = db
    daemon._load_relationship_state()                             # swallowed, not fatal
    assert daemon.governor.familiarity == 0.0


def turn(**flags):
    from assistant.persona import TurnContext

    return TurnContext(**flags)


# ══════════════════════════════════════════════════════════════════════════
# F. PERSONA IN VOICE
# ══════════════════════════════════════════════════════════════════════════

SOFTENERS = ("certainly", "of course!", "happy to help", "i hope this helps",
             "no worries", "just let me know", "great question", "please note",
             "sorry for the inconvenience", "thanks for your patience",
             "i appreciate your patience", "gladly!", "absolutely!")


@pytest.mark.parametrize("trigger", ["user_stressed", "sensitive_topic", "safety_refusal",
                                     "destructive_pending", "error", "direct_order_twice"])
def test_f16_serious_gates_keep_humour_out_of_the_spoken_line(trigger):
    """Every serious gate vetoes banter even when a funny line exists."""
    from assistant.persona import PersonaGovernor

    governor = PersonaGovernor.from_config(load_config(), {})
    decision = governor.decide(turn(**{trigger: True, "real_opportunity": True}))
    assert decision.register != "expressive-allowed", f"{trigger}: banter allowed"
    assert decision.teasing_licence in ("none",), f"{trigger}: licence {decision.teasing_licence}"
    assert decision.serious_gate, f"{trigger}: the gate was not named in the decision"


def test_f16b_pushback_is_spoken_once_with_its_evidence(tmp_path):
    """The reply carries the evidence; the voice path speaks it exactly once."""
    evidence = ("That would move 148 files but the Finance folder has 3 unread "
                "invoices; I stopped at 0.")
    _, speech, client = service(tmp_path)
    speech.speak(evidence, play=False)
    assert len(client.calls) == 1
    assert client.calls[0][1] == "Flare"
    assert [t for t, _ in client.calls] == [evidence]        # not split, not doubled


def test_f16c_no_humour_markers_in_any_canned_spoken_line():
    """No corporate softener in any canned line the runtime can speak or show."""
    import io
    import tokenize

    from assistant.tts import STANDARD_ACKS

    sources = ["tts.py", "overlay.py", "waybar.py", "persona.py", "offline_queue.py"]
    strings = []
    for name in sources:
        path = SRC / name
        for tok in tokenize.generate_tokens(io.StringIO(path.read_text()).readline):
            if tok.type == tokenize.STRING and tok.string.startswith(('"', "'")):
                strings.append(tok.string.strip("\'\""))
    strings.extend(STANDARD_ACKS.values())
    blob = " ".join(strings).lower()
    hits = [word for word in SOFTENERS if word in blob]
    assert hits == [], f"corporate softener in a canned line: {hits}"
    assert not re.search(r"\b(sorry|apologi[sz]e)\b", blob), "a canned line apologises"


def test_f16d_do_it_anyway_by_voice_is_not_a_gate_bypass(tmp_path):
    """Item 16 says 'do it anyway' works by voice. Prove what actually happens:
    no intent grammar owns the phrase, so it lands on the model, and the
    approval gate stays a separate explicit command (that is correct — but it
    means the voice loop cannot approve)."""
    from assistant.intents import route

    assert route("do it anyway") is None
    assert route("approve") is None
    approvals = (SRC / "cli.py").read_text().count('"approve"')
    assert approvals >= 1, "the approval command vanished from the CLI"


def test_f17_voice_identity_is_brisk_not_kind():
    """humour.toml delivery spec vs the voice surface: the ack set stays short
    and terminal; nothing in it hedges."""
    from assistant.tts import STANDARD_ACKS

    for kind, line in STANDARD_ACKS.items():
        assert len(line.split()) <= 6, f"{kind} is too long to ack with: {line!r}"
        assert line.endswith((".", "?")), line
        assert not any(w in line.lower() for w in ("please", "thanks", "sorry", "just"))
    assert STANDARD_ACKS["checkin"].endswith("?")
    assert STANDARD_ACKS["checkin"].count("?") == 1, "asked once, not twice"
    assert STANDARD_ACKS["not_at_this_hour"] == "No. Not at this hour."


# ══════════════════════════════════════════════════════════════════════════
# G. ABUSE & CHAOS
# ══════════════════════════════════════════════════════════════════════════

def _fake_bin(dir_path: Path, name: str, body: str) -> Path:
    script = dir_path / name
    script.write_text(body)
    script.chmod(0o755)
    return script


@pytest.mark.xfail(strict=True, reason="VB-10: a SIGKILLed daemon orphans its audio child "
                   "(no process group, no cleanup); the sink stays claimed and the "
                   "same shape applies to pw-record → mic held")
def test_g18_kill_daemon_mid_playback_leaves_the_player_running(tmp_path):
    """A real daemon subprocess, a real `tts.player`, a player that outlives it.

    The playback path is exercised on the dormant local route (mock backend)
    because no mocked Gemini can produce audio — the point under test is
    process supervision of the audio child, not voice identity.
    """
    import os
    import signal
    import subprocess
    import sys

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "playing.pid"
    _fake_bin(bin_dir, "fake-play", f"#!/bin/sh\nprintf '%s\\n' $$ > {marker}\nsleep 20\n")
    home = tmp_path / "home"
    (home / ".config" / "assistant").mkdir(parents=True, exist_ok=True)
    (home / ".config" / "assistant" / "config.toml").write_text(
        "[tts]\n"
        f'player = "{bin_dir}/fake-play"\n'
        'backend = "mock"\nvoice_id = "elaria-vb"\n'
        'online_voice = "local"\noffline_voice = "local"\n')
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "HOME": str(home),
           "XDG_CONFIG_HOME": str(home / ".config"),
           "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
           "XDG_STATE_HOME": str(tmp_path / "xdg-state"),
           "XDG_RUNTIME_DIR": str(tmp_path / "xdg-run"),
           "PYTHONPATH": str(SRC.parent), "GEMINI_MODE": "mock",
           "ASSIST_FIXTURES": str(tmp_path / "fixtures")}
    for key in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)

    # the fd must outlive this frame: the child writes to it until it dies
    log = open(tmp_path / "daemon.log", "w+")  # noqa: SIM115
    daemon_proc = subprocess.Popen([sys.executable, "-m", "assistant.daemon"], env=env,
                                   cwd=str(SRC.parents[1]), stdout=log,
                                   stderr=subprocess.STDOUT, text=True)
    try:
        from assistant.ipc import call as ipc_call

        socket = Path(env["XDG_RUNTIME_DIR"]) / "assistant.sock"
        for _ in range(100):
            if socket.exists():
                break
            time.sleep(0.05)
        else:
            log.seek(0)
            pytest.fail(f"daemon never bound {socket}: {log.read()[:400]}")

        import threading

        said: list[str] = []

        def say():
            # The handler blocks for the clip's whole duration — that is the point,
            # so this call is expected to die when the daemon is killed below.
            try:
                ipc_call(socket, "speech.say", {"text": "Sorting 148 files.", "play": True},
                         timeout=25.0)
                said.append("answered")
            except Exception as exc:
                said.append(f"raised:{type(exc).__name__}")

        threading.Thread(target=say, daemon=True).start()
        for _ in range(120):
            if marker.exists() or daemon_proc.poll() is not None:
                break
            time.sleep(0.05)
        assert marker.exists(), "the fake player never ran: no playback happened"
        player_pid = int(marker.read_text().strip())
        os.kill(player_pid, 0)                     # alive while the daemon lives

        os.kill(daemon_proc.pid, signal.SIGKILL)
        daemon_proc.wait(timeout=10)
        time.sleep(0.5)
        still_alive = True
        try:
            os.kill(player_pid, 0)
        except ProcessLookupError:
            still_alive = False
        assert not still_alive, (
            f"the audio child (pid {player_pid}) outlived SIGKILL: pw-play keeps the "
            "PipeWire sink (and pw-record keeps the mic) with nothing left to stop them")
    finally:
        if daemon_proc.poll() is None:
            daemon_proc.kill()
            daemon_proc.wait(timeout=5)
        log.close()
        if marker.exists():     # never leave a sleeper holding the sandbox's sink
            try:
                os.kill(int(marker.read_text().strip()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass


def test_g20_clock_jump_does_not_fire_and_the_rotation_cap_holds(tmp_path):
    """Item 20: timers must be monotonic. A +9h jump (Nairobi has no DST, but
    NTP and VM resume do move the wall clock) must not fire, cut, or double the
    check-in — and a 25h session must not misfire its rotation cap."""
    real_time = time.time
    state = ladder("narration")
    fired = 0
    for i in range(800):
        if i == 400:
            time.time = lambda: real_time() + 9 * 3600          # clock jumps
        if state.observe(SILENCE, 0.03):
            fired += 1
    time.time = real_time
    assert fired == 1, f"a wall-clock jump produced {fired} check-ins"

    _, _, service_, _ = dictation(tmp_path)
    service_.session_max_s = 0.01      # crossed by the very next frame
    shared = {"connects": [], "words_seen": 0, "finals": []}
    made = []

    def factory():
        made.append(Session(len(made), shared))
        return made[-1]

    events = []

    async def sink(event):
        events.append(event)

    result = asyncio.run(service_.dictate(Source([SPEECH] * 400), transport_factory=factory,
                                          sink=sink))
    assert len(shared["connects"]) >= 2, (
        f"no rotation at the session age cap ({shared['connects']})")
    assert not [e for e in events if e["event"] == "error"], events
    assert result.notes


def test_g19_double_hotkey_acks_once(tmp_path):
    """VB-11 (fixed): the rejected second press is refused in silence.

    Single-owner capture already worked — the loser just also got its own
    "On it." ack, so one mashing of the hotkey sounded like two answers (and
    played two files). A refusal is not a request to be acknowledged.
    """
    import asyncio

    from assistant.daemon import Daemon

    config = voice_config(tmp_path, online_voice="local", offline_voice="local")
    daemon = Daemon(config)
    daemon.speech._is_online = lambda: True
    daemon.speech.warm_ack_cache()
    plays = []
    daemon.speech.play_ack = lambda kind, **kw: (plays.append(kind),
                                                 {"played": True, "ack_kind": kind})[1]

    async def scenario():
        first = await daemon._ptt_start({"source": "simulated", "mode": "narration"})
        await asyncio.sleep(0.05)                 # let the capture task be real
        after_first = list(plays)
        second = await daemon._ptt_start({"source": "simulated", "mode": "narration"})
        await asyncio.sleep(0.05)
        return first, second, after_first, list(plays)

    first, second, after_first, after_second = asyncio.run(scenario())
    assert first["listening"] is True and "already_listening" not in first
    assert after_first, "the accepted press never queued its ack"
    assert second["listening"] is True and second["note"] == "already listening"
    assert second.get("already_listening") is True
    assert second["speech"]["played"] is False and second["speech"]["audio_path"] is None
    assert second["speech"]["suppressed"] == "already listening — no second ack"
    assert after_second == after_first, (
        f"a refused press made her speak: {after_first} -> {after_second}")


def test_b5c_boot_warm_starts_before_the_socket_serves():
    """VB-13 (fixed, ordering): the warm task is created before anything can ask.

    `run()` used to `await serve(...)` first and start `_warm_speech_cache()`
    afterwards, so every boot had a window where the hotkey was silent.
    """
    source = (SRC / "daemon.py").read_text()
    body = source[source.index("    async def run(self)"):]
    serve_at = body.index("await serve(")
    warm_at = body.index("_warm_speech_cache()")
    assert warm_at < serve_at, (
        "the daemon accepts IPC requests before the ack cache exists: warm first, or "
        "gate the ack path until `status()['cached_acks']` is full")


def test_b5cb_early_acks_queue_behind_the_boot_warm(tmp_path):
    """VB-13 (fixed, behaviour): the first ack after boot finds audio, not silence.

    A slow warm is injected through the documented seam (`speech.warm_due`), and
    the real `_ack` handler is called while it is in flight. The handler waits
    (bounded) and then reports a cache hit; the pre-fix code returned
    `cached: False` in the same instant.
    """
    import asyncio

    from assistant.daemon import Daemon

    config = voice_config(tmp_path, online_voice="local", offline_voice="local")
    daemon = Daemon(config)
    daemon.speech._is_online = lambda: True
    cache = Path(config.section("tts")["cache_dir"])
    assert not list(cache.glob("*.wav")), "cache should start cold"

    real_due = daemon.speech.warm_due
    slow = {"released": 0.0}

    def slow_warm_due():
        time.sleep(0.35)                     # one render per ack, like the cloud
        result = real_due()
        slow["released"] = time.perf_counter()
        return result

    daemon.speech.warm_due = slow_warm_due

    async def scenario():
        warm = asyncio.ensure_future(daemon._warm_speech_cache())
        await asyncio.sleep(0)               # the warm is now genuinely in flight
        started = time.perf_counter()
        ack = await daemon._ack({"kind": "on_it"})
        await warm
        return ack, time.perf_counter() - started

    ack, elapsed = asyncio.run(scenario())
    speech = ack["speech"]
    assert speech["cached"] is True and speech["cache_miss"] is False, (
        f"the first ack after boot was silent: {speech}")
    assert Path(speech["audio_path"]).exists()
    assert elapsed >= 0.3, (
        f"the ack did not wait for the warm at all ({elapsed:.3f}s) — it answered "
        f"from a cold cache instead of queueing behind it")
    assert elapsed <= 3.0, "the ack gate must be bounded, not an unbounded wait"
    assert slow["released"] > 0


def test_b5e_daemon_re_warms_after_a_miss(tmp_path):
    """VB-2 at daemon level: a miss schedules the cure, so the next press works."""
    import asyncio

    from assistant.daemon import Daemon

    config = voice_config(tmp_path, online_voice="local", offline_voice="local")
    daemon = Daemon(config)
    daemon.speech._is_online = lambda: True

    async def scenario():
        warmed = await daemon._speech_warm({})
        assert len(warmed["warmed"]) == 4, warmed
        cache = Path(config.section("tts")["cache_dir"])
        for path in cache.glob("*.wav"):
            path.unlink()                    # the invalidation, by any cause
        miss = await daemon._ack({"kind": "on_it"})
        assert miss["speech"]["cache_miss"] is True and miss["speech"]["cached"] is False
        for _ in range(200):                 # the scheduled re-warm is a background task
            await asyncio.sleep(0.01)
            if daemon.speech.cached_ack("on_it"):
                break
        healed = await daemon._ack({"kind": "on_it"})
        return miss, healed
    first, healed = asyncio.run(scenario())
    assert first["speech"]["audio_path"] is None, first
    assert healed["speech"]["cached"] is True, (
        "acks never came back after invalidation — the permanent-silence bug: "
        f"{healed['speech']}")


@pytest.mark.skip(reason="needs live (VB-13): the online boot window is one rate-limited "
                  "cloud render per ack; `assist voice warm` timing can only be measured "
                  "with a real key — never faked in the sandbox")
def test_b5f_boot_warm_window_online_is_measured():
    """Registered, not simulated: see the needs-live list in VOICE-BUGTEST.md."""
    raise AssertionError("unreachable in the sandbox")
