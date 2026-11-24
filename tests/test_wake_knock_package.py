"""I5 — Wake-knock package (2026-10-20), owner-approved spec, behind tests.

Sections covered here (spec §1–§5):
  * wake-knock model: NO straight hit->listening; uncertain raises a `wake`
    knock; accept opens listening (console in class mode); voice-accept must
    itself be voiceprint-verified; guest door stays show-off's.
  * authority gate: high|uncertain|none, fail closed everywhere; energy
    arming refuses without a real .onnx model; `--unsafe-energy-test` can
    never open command listening; every trigger logged as metadata only.
  * dual-use pending buffer: inherit (verified high owner) / discard
    (unverified, untranscribed) / wake-clip-only fallback on insufficient
    speech, with the AWAITING_COMMAND sub-state.
  * privacy: ring <= 2.0s RAM-only circular overwrite, MADV_DONTDUMP +
    LimitCORE=0 exposure, clips off by default with 24h/0700/purge rules,
    watchdog stall -> disarm + zero + visible "stalled".
  * tooling: plan/freeze-eval script on the production mic path.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from assistant import wake_guard as wg
from assistant.ipc import call
from assistant.transcribe import SilenceLadder
from assistant.voiceprint import EcapaCommandScorer, cosine, load_reference
from assistant.wake_buffers import PcmRam, PreWakeRing

REPO = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# test-side doubles (the production seam refuses to fake any of this)
# ---------------------------------------------------------------------------
class ScriptedScorer:
    name = "scripted-ecapa"

    def __init__(self, score=0.9):
        self.score = score
        self.calls: list[bytes] = []

    def available(self):
        return True

    def score_owner(self, pcm: bytes):
        self.calls.append(bytes(pcm))
        return self.score


def frames(seconds: float, amp: int = 6000, frame_s: float = 0.03):
    count = round(seconds / frame_s)
    frame = struct.pack("<480h", *([amp] * 480))
    return [frame] * count


def pcm(seconds: float, amp: int = 6000) -> bytes:
    return b"".join(frames(seconds, amp))


def silence(seconds: float) -> bytes:
    return pcm(seconds, amp=0)


def _local_owner_principal():
    """I5: synthetic in-process peer identity for WakeGuard unit tests only."""
    from assistant.ipc import IpcPrincipal

    return IpcPrincipal(pid=os.getpid(), uid=os.getuid(), gid=os.getgid())


def make_guard(tmp_path, *, score=0.9, with_knocks=True, **overrides):
    from assistant.initiative import InitiativeService
    from assistant.store import Store

    store = Store(tmp_path / "wake.db")
    initiative = InitiativeService(None, store) if with_knocks else None
    class_mode = overrides.pop("class_mode", None)
    showoff = overrides.pop("showoff", None)
    settings = {
        "ring_window_s": 2.0,
        "pending_window_s": 2.5,
        "pending_speech_threshold_s": 0.5,
        "ecapa_high": 0.75,
        "ecapa_uncertain": 0.5,
        "stall_timeout_s": 2.0,
    }
    settings.update(overrides)
    guard = wg.WakeGuard(settings=settings, store=store,
                         initiative=initiative, scorer=ScriptedScorer(score),
                         class_mode=class_mode, showoff=showoff)
    return guard, store


# ---------------------------------------------------------------------------
# §1 — no straight hit->listening / silent discard / accept paths
# ---------------------------------------------------------------------------
def _command_window(guard, seconds: float = 2.0, amp: int = 6000) -> bytes:
    """Feed `seconds` of command audio into the open pending window."""
    data = pcm(seconds, amp=amp)
    for frame in frames(seconds, amp=amp):
        guard.note_frame(frame)
    return data


def test_a_hit_alone_never_opens_listening(tmp_path):
    guard, _store = make_guard(tmp_path, score=0.99)

    guard.trigger(keyword_score=0.99)
    assert guard.state == wg.TRIGGERED
    with pytest.raises(wg.WakeGuardError, match="hit alone never opens"):
        guard.open_listening()

    # Round J defect 1: with no command window there is NOTHING to verify —
    # and no listening either. Nothing was scored, nothing opens the mic.
    outcome = guard.verify()
    assert outcome["state"] == wg.IDLE
    assert outcome["trigger"]["outcome"] == wg.OUTCOME_DISCARDED
    assert guard.scorer.calls == [], "the wake clip must never be scored"
    with pytest.raises(wg.WakeGuardError, match="hit alone never opens"):
        guard.open_listening()

    # A fresh guard still refuses a bare hit (no verify at all).
    guard2, _store2 = make_guard(tmp_path, score=0.99)
    guard2.trigger(keyword_score=0.5)
    with pytest.raises(wg.WakeGuardError, match="hit alone never opens"):
        guard2.open_listening()


def test_unrecognised_voice_is_silent_and_raises_no_knock(tmp_path):
    """Round J defect 2: an impostor cannot tell they were heard."""
    guard, store = make_guard(tmp_path, score=0.61)
    guard.trigger(keyword_score=0.9, wake_clip=pcm(1.0))
    _command_window(guard, 2.0)

    outcome = guard.verify()
    assert outcome["state"] == wg.IDLE
    assert outcome["knock_id"] is None
    assert outcome["trigger"]["outcome"] == wg.OUTCOME_DISCARDED
    assert outcome["trigger"]["pending_disposition"] == wg.DISP_DISCARDED
    # No knock row of any kind, wake or otherwise.
    assert store.list_knocks(status=None) == []
    # No score in the user-visible record for a discarded window.
    assert outcome["trigger"]["ecapa_score"] is None
    # Zero outbound of any kind.
    assert len(guard.outbound) == 0 and guard.outbound.bytes_out() == 0

    # Uncertain is the ambiguous band, and it is still silence.
    guard.trigger(keyword_score=0.9)
    _command_window(guard, 2.0)
    uncertain = guard.verify()
    assert uncertain["trigger"]["confidence"] == wg.CONF_UNCERTAIN
    assert uncertain["state"] == wg.IDLE
    assert store.list_knocks(status=None) == []


def test_uncertain_discards_pending_untranscribed_and_nothing_resurrects(tmp_path):
    guard, store = make_guard(tmp_path, score=0.61)
    guard.trigger(keyword_score=0.9, wake_clip=pcm(0.5))
    for frame in frames(1.0):
        guard.note_frame(frame)

    outcome = guard.verify()
    assert outcome["trigger"]["pending_disposition"] == "discarded"
    # the pending buffer is gone — no ASR input, no ledger, no transcript row
    assert guard.pending.data() == b""
    assert guard._wake_clip == b""
    row_count = store._conn.execute(
        "SELECT COUNT(*) FROM transcripts").fetchone()[0]
    llm_count = store._conn.execute(
        "SELECT COUNT(*) FROM llm_calls").fetchone()[0]
    assert row_count == 0 and llm_count == 0

    # The discard returned to idle: there is no pending knock to accept, and
    # no path back to listening from a voice the daemon did not recognise.
    with pytest.raises(wg.WakeGuardError):
        guard.wake_knock_accepted(principal=_local_owner_principal())
    with pytest.raises(wg.WakeGuardError, match="hit alone never opens"):
        guard.open_listening()


def test_owner_command_opens_listening_on_verified_audio(tmp_path):
    guard, _store = make_guard(tmp_path, score=0.92)
    guard.trigger(keyword_score=0.9)
    _command_window(guard, 2.0)
    outcome = guard.verify()
    assert outcome["state"] == wg.ATTENDING
    assert outcome["knock_id"] is None

    opened = guard.open_listening()
    assert opened["open"] == "listening"
    assert opened["head_bytes"] > 0
    assert opened["fresh_capture"] is False


def test_verified_owner_flow_never_requires_a_knock_accept(tmp_path):
    """The accept machinery is for an owner PROMPT, never for a stranger.

    It still refuses a caller that is not the kernel-authenticated local
    owner (I5), and a class-mode accept still opens the CONSOLE, not PTT.
    """
    guard, _store = make_guard(tmp_path, score=0.55, class_mode=lambda: True)
    guard.trigger(keyword_score=0.9)
    _command_window(guard, 2.0)
    guard.verify()
    assert guard.state == wg.IDLE

    guard.state = wg.WAKE_KNOCK
    with pytest.raises(wg.WakeGuardError, match="authenticated local owner"):
        guard.wake_knock_accepted(principal=None)
    from assistant.ipc import IpcPrincipal

    wrong_uid = IpcPrincipal(pid=os.getpid(), uid=os.getuid() + 1,
                             gid=os.getgid())
    with pytest.raises(wg.WakeGuardError, match="authenticated local owner"):
        guard.wake_knock_accepted(principal=wrong_uid)

    # An owner-authored prompt still exists (wake_knock_accepted is intact)
    # and still refuses the guest door, still prefers the console in class.
    guard.state = wg.WAKE_KNOCK
    opened = guard.wake_knock_accepted(principal=_local_owner_principal())
    assert opened["open"] == "console"
    assert guard.state != wg.LISTENING


def test_wake_path_never_opens_the_guest_door(tmp_path):
    class ShowoffOn:
        def status(self):
            return {"active": True}

    guard, _store = make_guard(tmp_path, score=0.92, showoff=ShowoffOn())
    guard.trigger(keyword_score=0.9)
    _command_window(guard, 2.0)
    guard.verify()
    assert guard.state == wg.ATTENDING
    with pytest.raises(wg.WakeGuardError, match="guest door is show-off"):
        guard.open_listening()

    # and on the owner-prompt path too
    guard.state = wg.WAKE_KNOCK
    with pytest.raises(wg.WakeGuardError, match="guest door is show-off"):
        guard.wake_knock_accepted(principal=_local_owner_principal())


# ---------------------------------------------------------------------------
# §2 — authority gate + energy refusal
# ---------------------------------------------------------------------------
def test_authority_gate_levels_fail_closed():
    gate = wg.AuthorityGate(high=0.75, uncertain=0.5)
    assert gate.evaluate(0.9, verified=True) == wg.CONF_HIGH
    assert gate.evaluate(0.6, verified=True) == wg.CONF_UNCERTAIN
    assert gate.evaluate(0.4, verified=True) == wg.CONF_NONE
    assert gate.evaluate(0.99, verified=False) == wg.CONF_NONE
    assert gate.evaluate(None, verified=False) == wg.CONF_NONE

    # Round J defect 4: uncertain is never permissive. Only high may attend.
    assert gate.may_attend(0.9, verified=True) is True
    assert gate.may_attend(0.6, verified=True) is False
    assert gate.may_attend(0.4, verified=True) is False
    assert gate.may_attend(None, verified=True) is False
    assert gate.may_attend(0.99, verified=False) is False
    # and the thresholds themselves are untouched
    assert (gate.high, gate.uncertain) == (0.75, 0.5)


def test_hotword_start_refuses_without_a_real_keyword_model(tmp_path):
    guard, _store = make_guard(tmp_path)
    with pytest.raises(wg.KeywordModelUnavailable, match="\\.onnx"):
        guard.arm()
    with pytest.raises(wg.KeywordModelUnavailable, match="\\.onnx"):
        wg.OnnxKeywordModel.load("")
    with pytest.raises(wg.KeywordModelUnavailable, match="\\.onnx"):
        wg.OnnxKeywordModel.load(tmp_path / "missing.onnx")

    # The energy scorer may not arm the wake path without the explicit flag.
    with pytest.raises(wg.KeywordModelUnavailable, match="energy scorer"):
        guard.arm(keyword_model=wg.EnergyTestModel())


def test_unsafe_energy_trigger_can_never_open_command_listening(tmp_path):
    guard, _store = make_guard(tmp_path, score=0.99)
    guard.trigger(keyword_score=0.8, unsafe_energy=True)
    _command_window(guard, 2.0)
    outcome = guard.verify()
    assert outcome["trigger"]["outcome"] == "refused_energy_test"
    assert outcome["trigger"]["unsafe_energy"] is True
    with pytest.raises(wg.WakeGuardError, match="unsafe energy"):
        guard.open_listening()

    # and a short energy trigger cannot even claim "awaiting command"
    guard2, _store2 = make_guard(tmp_path, score=0.2)
    guard2.trigger(keyword_score=0.8, unsafe_energy=True)
    outcome2 = guard2.verify()
    assert outcome2["state"] == wg.CLOSED
    assert outcome2["trigger"]["outcome"] == "refused_energy_test"
    with pytest.raises(wg.WakeGuardError):
        guard2.wake_knock_accepted(
            knock_id=outcome2["knock_id"], principal=_local_owner_principal())
    with pytest.raises(wg.WakeGuardError, match="unsafe energy"):
        guard2.open_listening()


def test_every_trigger_is_logged_metadata_only(tmp_path):
    guard, store = make_guard(tmp_path, score=0.61)
    guard.trigger(keyword_score=0.9)
    _command_window(guard, 2.0)
    guard.verify()

    events = [e for e in store.list_persona_events(kind="wake_trigger")]
    assert len(events) == 1
    meta = json.loads(events[0]["detail"])
    assert meta["keyword_score"] == 0.9
    # Round J defect 2: a discarded window's score is not in the record that
    # anything can read back. The confidence BAND is still reported.
    assert meta["ecapa_score"] is None
    assert meta["confidence"] == "uncertain"
    assert meta["outcome"] == "discarded"
    assert meta["knock_id"] is None
    forbidden = {"audio", "pcm", "bytes", "clip", "frames", "samples"}
    assert forbidden.isdisjoint(meta.keys())

    # The in-process record keeps the number for an operator/debugger only.
    assert guard.last_trigger.ecapa_score == pytest.approx(0.61)


# ---------------------------------------------------------------------------
# §3 — dual-use pending buffer (command-window only)
# ---------------------------------------------------------------------------
def test_verified_owner_inherits_pending_buffer_as_command_head(tmp_path):
    guard, _store = make_guard(tmp_path, score=0.92)
    wake_clip = pcm(0.4)
    guard.trigger(keyword_score=0.9, wake_clip=wake_clip)
    for frame in frames(2.0):            # speechful post-trigger command window
        guard.note_frame(frame)
    pending_pcm = guard.pending.data()

    outcome = guard.verify()
    assert outcome["trigger"]["stage_b_input"] == "command_window"
    assert outcome["trigger"]["pending_disposition"] == "inherited"
    assert guard.state == wg.ATTENDING
    assert guard.attending_detail == wg.ATTEND_INHERIT
    # Round J defect 1: the scorer saw the COMMAND window only — the exact
    # bytes captured after the hit, with no wake clip prepended.
    assert guard.scorer.calls == [pending_pcm]
    assert wake_clip == pcm(0.4) and len(wake_clip) == 12480

    opened = guard.open_listening()
    assert opened["open"] == "listening"
    assert opened["head_bytes"] > 0
    assert guard.session.head[:480 * 2] == frames(0.03)[0]  # head == pending

    # live capture continues seamlessly after the head, as ONE utterance
    class LiveTail:
        target = "mic1"

        async def frames(self):
            for frame in frames(0.3):
                yield frame

    source = guard.session.source(LiveTail())
    collected = asyncio.run(_collect(source))
    assert collected[: opened["head_bytes"]] == guard.session.head
    assert len(collected) == opened["head_bytes"] + 0.3 / 0.03 * 480 * 2


async def _collect(source) -> bytes:
    out = b""
    async for frame in source.frames():
        out += frame
    return out


def test_endpointing_shares_the_one_silence_ladder(tmp_path):
    guard, _store = make_guard(tmp_path, score=0.92, checkin_after_s=1.0,
                               grace_s=8.0)
    guard.trigger(keyword_score=0.9, wake_clip=pcm(0.3))
    for frame in frames(2.0):
        guard.note_frame(frame)
    guard.verify()
    guard.open_listening()

    # One ladder implementation, shared with dictation — not a second copy.
    ladder = guard.session.ladder
    assert isinstance(ladder, SilenceLadder)

    # head + continuation run through the SAME ladder as one utterance
    checkins = 0
    for frame in list(frames(1.0)) + list(frames(6.0, amp=0)):
        if ladder.observe(frame, 0.03):
            checkins += 1
    assert checkins == 1, "one soft check-in per thought, head+continuation"
    assert not ladder.close_due()


def test_short_windows_never_reach_the_scorer(tmp_path):
    """Round J defect 1: below `MIN_WINDOW_S` there is NO scoring call at all."""
    guard, _store = make_guard(tmp_path, score=0.92)
    guard.trigger(keyword_score=0.9, wake_clip=pcm(0.6))
    for frame in frames(1.0, amp=0):     # 1.0 s of post-wake silence
        guard.note_frame(frame)

    outcome = guard.verify()
    assert outcome["trigger"]["stage_b_input"] == "wake_too_short"
    assert outcome["trigger"]["outcome"] == wg.OUTCOME_DISCARDED
    assert outcome["trigger"]["ecapa_score"] is None
    assert guard.scorer.calls == [], "a short window must not be scored"
    # A window too short to verify is too short to open the microphone for.
    assert guard.state == wg.IDLE
    assert guard.pending.data() == b""
    assert guard._wake_clip == b""
    assert len(guard.outbound) == 0
    with pytest.raises(wg.WakeGuardError, match="hit alone never opens"):
        guard.open_listening()


def test_insufficient_speech_low_confidence_is_silent_not_a_knock(tmp_path):
    guard, store = make_guard(tmp_path, score=0.3)
    guard.trigger(keyword_score=0.9, wake_clip=pcm(0.5))
    for frame in frames(0.1, amp=0):
        guard.note_frame(frame)
    outcome = guard.verify()
    assert outcome["trigger"]["stage_b_input"] == "wake_too_short"
    assert outcome["state"] == wg.IDLE
    assert guard.scorer.calls == []
    assert store.list_knocks(status=None) == []
    assert len(guard.outbound) == 0


# ---------------------------------------------------------------------------
# §4 — privacy: ring, crash safety, clips, watchdog
# ---------------------------------------------------------------------------
def test_pre_wake_ring_is_circular_capped_and_ram_only():
    ring = PreWakeRing(2.0)
    assert ring.path is None
    for frame in frames(3.0):            # more than the cap: old audio falls out
        ring.append(frame)
    assert ring.seconds == 2.0
    assert ring.residence_s() == pytest.approx(2.0, abs=0.05)

    # chronological after wrap: oldest resident frame first
    marker = struct.pack("<480h", *([12345] * 480))
    ring.append(marker)
    snap = ring.snapshot()
    assert snap[-960:] == marker

    # the <=2.0s contract holds regardless of config
    assert PreWakeRing(9.0).seconds == 2.0


def test_madv_dontdump_and_limit_core_are_exposed_not_believed():
    ram = PcmRam(1024)
    assert isinstance(ram.madv_dontdump, bool)
    report = wg.crash_safety_report()
    assert report["limit_core"] is True          # systemd/assistant.service
    assert isinstance(report["madv_dontdump"], bool)
    assert "limit_core_runtime" in report

    unit = (REPO / "systemd" / "assistant.service").read_text(encoding="utf-8")
    assert any(line.strip() == "LimitCORE=0" for line in unit.splitlines())


def test_watchdog_stall_disarms_zeroes_and_stays_visible(tmp_path):
    guard, _store = make_guard(tmp_path)
    guard.arm(unsafe_energy_test=True)
    now = time.monotonic()
    for frame in frames(0.3):
        guard.note_frame(frame, now=now)
    assert guard.watchdog.check(now=now + 0.5) is False

    assert guard.watchdog.check(now=now + 2.5) is True   # one visible stall
    assert guard.watchdog.check(now=now + 3.0) is False  # exactly once
    guard.disarm(reason="stalled")

    status = guard.status()
    assert guard.state == wg.STALLED
    assert status["watchdog"]["state"] == "stalled"
    assert status["ring"]["residence_s"] == 0.0
    assert guard.pending.data() == b""


def test_wake_clips_off_by_default_with_0700_purge_and_fail_rules(tmp_path):
    """Clip policy only. Each window is DISTINCT audio: byte-identical command
    windows are a replay and are refused by design (see the D3 tests)."""
    clip_dir = tmp_path / "clips"
    command = pcm(2.0, amp=6000)

    # OFF by default: nothing is ever written.
    guard, _store = make_guard(tmp_path, score=0.9,
                               clip_dir=str(clip_dir), save_wake_clips=False)
    guard.trigger(keyword_score=0.9)
    for frame in frames(2.0):
        guard.note_frame(frame)
    outcome = guard.verify()
    assert outcome["trigger"]["outcome"] == wg.OUTCOME_ATTENDING
    assert outcome["trigger"]["clip_saved"] is False
    assert not clip_dir.exists()

    # A discarded window is NEVER saved — not even a verified-looking one.
    guard_d, _store_d = make_guard(tmp_path, score=0.4,
                                   clip_dir=str(clip_dir),
                                   save_wake_clips=True, debug_save_failed=True)
    guard_d.trigger(keyword_score=0.9)
    for frame in frames(2.0, amp=5000):
        guard_d.note_frame(frame)
    assert guard_d.verify()["trigger"]["clip_saved"] is False
    assert not list(clip_dir.glob("wake-*"))

    # Opt-in: the OWNER's verified command audio is saved, <=5s, 0700 dir.
    guard2, _store2 = make_guard(tmp_path, score=0.92,
                                 clip_dir=str(clip_dir),
                                 save_wake_clips=True, clip_max_s=5.0)
    guard2.trigger(keyword_score=0.9)
    for frame in frames(2.0, amp=7000):
        guard2.note_frame(frame)
    outcome2 = guard2.verify()
    assert outcome2["trigger"]["clip_saved"] is True
    saved = list(clip_dir.glob("wake-*"))
    assert len(saved) == 1
    assert saved[0].stat().st_size <= 5.0 * 16000 * 2
    assert saved[0].read_bytes()[: len(command)] == pcm(2.0, amp=7000)
    assert clip_dir.stat().st_mode & 0o777 == 0o700

    assert guard2.clips.purge() == 1
    assert not list(clip_dir.glob("wake-*"))


def test_hotword_status_surface_has_every_documented_field(tmp_path):
    guard, _store = make_guard(tmp_path, score=0.61)
    guard.trigger(keyword_score=0.9, wake_clip=pcm(0.5))
    for frame in frames(2.0):
        guard.note_frame(frame)
    guard.verify()
    status = guard.status()

    assert status["armed"] is False
    assert status["state"] == wg.IDLE
    assert status["min_window_s"] == 1.75
    assert status["window_close_s"] == 2.5
    assert 0.0 <= status["window_elapsed_s"] <= 2.5
    assert status["ecapa_high"] == 0.75 and status["ecapa_uncertain"] == 0.5
    assert set(status["ring"]) == {"capacity_s", "residence_s", "path"}
    assert status["ring"]["path"] is None
    assert status["scorer"] == "scripted-ecapa"
    trigger = status["last_trigger"]
    for key in ("keyword_score", "ecapa_score", "confidence", "outcome",
                "knock_id", "clip_saved"):
        assert key in trigger
    assert status["pending_speech_s"] == trigger["pending_speech_s"]
    assert status["stage_b_input"] == trigger["stage_b_input"]
    assert status["pending_disposition"] == trigger["pending_disposition"]
    assert set(status["watchdog"]) == {"last_frame_age_ms", "state"}
    assert set(status["crash_safety"]) >= {"limit_core", "madv_dontdump"}


# ---------------------------------------------------------------------------
# voiceprint seam (real subprocess path — no fabricated model)
# ---------------------------------------------------------------------------
def test_ecapa_command_scorer_embedding_and_fail_closed(tmp_path):
    script = tmp_path / "scorer.py"
    script.write_text(
        "import json,sys\n"
        "print(json.dumps({'embedding': [1.0, 0.0, 0.0]}))\n",
        encoding="utf-8")
    scorer = EcapaCommandScorer(f"{sys.executable} {script}",
                                reference=[1.0, 0.0, 0.0])
    assert scorer.available()
    score = scorer.score_owner(pcm(0.2))
    assert score == pytest.approx(1.0)

    # no command, no reference, broken command -> None (fail closed)
    assert EcapaCommandScorer("").score_owner(pcm(0.2)) is None
    assert EcapaCommandScorer(f"{sys.executable} {script}").score_owner(b"") is None
    bad = EcapaCommandScorer(f"{sys.executable} {script}", reference=None)
    assert bad.score_owner(pcm(0.2)) is None       # embedding, no reference
    missing = EcapaCommandScorer("/nonexistent/ecapa")
    assert missing.score_owner(pcm(0.2)) is None
    assert missing.last_error

    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([], [1.0]) == 0.0
    assert load_reference(None) is None
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps({"embedding": [0.0, 1.0]}), encoding="utf-8")
    assert load_reference(ref) == [0.0, 1.0]


# ---------------------------------------------------------------------------
# §1 over REAL socket wiring (daemon + real knock system)
# ---------------------------------------------------------------------------
def _owner_command_over_socket(daemon, *, score):
    """Feed a real 2 s command window through the daemon's guard."""
    daemon.wake_guard.scorer = ScriptedScorer(score)
    daemon.wake_guard.trigger(keyword_score=0.9)
    for frame in frames(2.0):
        daemon.wake_guard.note_frame(frame)
    return daemon.wake_guard.verify()


def _owner_prompt_over_socket(daemon):
    """An OWNER-authentication knock, raised explicitly (not by a stranger).

    Round J: an unverified voice never knocks. The knock machinery itself is
    unchanged, so it is exercised through its own door.
    """
    knock = daemon.initiative.raise_knock(
        topic="wake phrase 'Elaria'",
        reason="phrase 'Elaria' detected, voice confidence unavailable",
        kind="wake")
    daemon.wake_guard.state = wg.WAKE_KNOCK
    return int(knock["id"])


def test_socket_accept_opens_listening_on_real_knock_system(
        config, running_daemon):
    daemon, _server = running_daemon
    knock_id = _owner_prompt_over_socket(daemon)

    result = call(config.socket_path, "knock.accept",
                  {"id": knock_id}, timeout=5.0)
    assert result["open"] == "listening"
    assert result["wake"]["head_bytes"] == 0
    assert daemon.wake_guard.state == wg.LISTENING
    assert result["knock"]["kind"] == "wake"

    status = call(config.socket_path, "hotword.status", timeout=5.0)
    assert status["hotword"]["state"] == wg.LISTENING


def test_socket_unrecognised_voice_discards_without_a_knock(config, running_daemon):
    """Round J, end to end: no knock row, no reply, gate back to idle."""
    daemon, _server = running_daemon
    outcome = _owner_command_over_socket(daemon, score=0.55)
    assert outcome["knock_id"] is None
    assert daemon.wake_guard.state == wg.IDLE
    assert daemon.store.list_knocks(status=None) == []
    status = call(config.socket_path, "hotword.status", timeout=5.0)
    assert status["hotword"]["state"] == wg.IDLE
    assert status["hotword"]["last_trigger"]["ecapa_score"] is None


def test_socket_wake_accept_rejects_caller_channel_and_score_claims(
        config, running_daemon):
    """I5: caller labels and scores are rejected; the local owner action works."""
    daemon, _server = running_daemon
    knock_id = _owner_prompt_over_socket(daemon)

    for forged in (
            {"channel": "voice"},
            {"channel": "voice", "voiceprint_score": 0.1},
            {"channel": "voice", "voiceprint_score": 0.95},
            {"channel": "voice_unavailable", "voiceprint_score": 0.01}):
        with pytest.raises(RuntimeError, match="caller-supplied"):
            call(config.socket_path, "knock.accept",
                 {"id": knock_id, **forged}, timeout=5.0)
        assert daemon.wake_guard.state == wg.WAKE_KNOCK

    result = call(config.socket_path, "knock.accept",
                  {"id": knock_id}, timeout=5.0)
    assert result["open"] == "listening"


def test_socket_wake_accept_in_class_mode_opens_console(config, running_daemon):
    daemon, _server = running_daemon
    knock_id = _owner_prompt_over_socket(daemon)
    # class mode via the real presence service
    call(config.socket_path, "class.set", {"enabled": True}, timeout=5.0)
    result = call(config.socket_path, "knock.accept",
                  {"id": knock_id}, timeout=5.0)
    assert result["open"] == "console"
    assert daemon.wake_guard.state != wg.LISTENING


def test_socket_decline_returns_gate_to_sleep(config, running_daemon):
    daemon, _server = running_daemon
    knock_id = _owner_prompt_over_socket(daemon)
    result = call(config.socket_path, "knock.decline",
                  {"id": knock_id}, timeout=5.0)
    assert result["knock"]["status"] == "declined"
    assert daemon.wake_guard.state == wg.CLOSED


def test_socket_hotword_start_refuses_then_unsafe_arms(config, running_daemon):
    daemon, _server = running_daemon

    class IdleSource:
        async def frames(self):
            for _ in range(5):
                yield b"\x00" * 960
                await asyncio.sleep(0.005)

    daemon._hotword_capture_factory = lambda: IdleSource()

    with pytest.raises(RuntimeError, match="\\.onnx"):
        call(config.socket_path, "hotword.start", {}, timeout=5.0)
    assert daemon.wake_guard.armed is False

    out = call(config.socket_path, "hotword.start",
               {"unsafe_energy_test": True}, timeout=5.0)
    assert daemon.wake_guard.armed is True
    assert out["hotword"]["armed_with"] == "unsafe-energy-test"

    status = call(config.socket_path, "hotword.status", timeout=5.0)
    assert status["hotword"]["armed"] is True
    assert "UNSAFE" in out["note"]

    stopped = call(config.socket_path, "hotword.stop", {}, timeout=5.0)
    assert stopped["hotword"]["armed"] is False
    assert call(config.socket_path, "hotword.purge", {}, timeout=5.0)["purged"] == 0


# ---------------------------------------------------------------------------
# §5 — capture tooling (plan + the ONE split)
# ---------------------------------------------------------------------------
def _load_script():
    path = REPO / "scripts" / "record_elaria_samples.py"
    spec = importlib.util.spec_from_file_location("record_elaria_samples", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_freeze_eval_is_the_single_split_and_manifest_has_no_split_flag(tmp_path):
    script = _load_script()
    root = tmp_path / "samples"
    for bucket, count in (("elaria-close-normal", 10), ("nearwords", 5)):
        for index in range(count):
            take = root / "train" / bucket / f"{bucket}-{index:03d}.wav"
            take.parent.mkdir(parents=True, exist_ok=True)
            take.write_bytes(b"RIFF")
            script.append_manifest(root, {
                "id": take.name, "bucket": bucket, "phrase": "Elaria",
                "path": f"train/{bucket}/{take.name}", "duration_s": 2.5})

    result = script.freeze_eval(root, fraction=0.2, seed=7)
    assert result["moved"]["elaria-close-normal"] == 2   # 20% of 10
    assert result["moved"]["nearwords"] == 1             # 20% of 5, >=1

    for bucket in ("elaria-close-normal", "nearwords"):
        eval_dir = root / "eval" / bucket
        assert eval_dir.is_dir()
        moved = list(eval_dir.glob("*.wav"))
        assert moved, f"{bucket} eval split is empty"
        for take in moved:
            assert not (root / "train" / bucket / take.name).exists()

    rows = script.read_manifest(root)
    assert rows and all("split" not in row for row in rows)
    assert (root / "eval" / ".frozen").is_file()


def test_plan_and_record_refuse_cleanly():
    script = _load_script()
    plan = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "record_elaria_samples.py"),
         "plan"], capture_output=True, text=True, timeout=60, check=False)
    assert plan.returncode == 0
    assert "Milestone A" in plan.stdout
    assert "elaria-close-normal" in plan.stdout

    # no pw-record in this sandbox: the production path refuses, never
    # substitutes another recorder
    with pytest.raises(RuntimeError, match="pw-record"):
        script.record_take(out_path=Path("/tmp/x.wav"), seconds=0.1,
                           mic_target="mic1")
