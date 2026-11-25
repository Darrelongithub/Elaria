"""Round Z: the verified hit actually goes somewhere.

PROVEN BEFORE THIS LANE (J, present since `221ad22`):

    daemon.py:1547 discarded WakeGuard.feed()'s return value
    open_listening() had ZERO call sites in src/ outside wake_guard.py

so with the daemon's exact loop body a verified owner produced
``state=attending, session=None``. Every round-J test passed because they
called ``guard.open_listening()`` themselves; nothing asserted the daemon did.

This file pins the wiring, and only the wiring. The microscope is the seam
that starts a session (``_start_wake_listen``) and the ``capture.state``
events that leave the daemon, because those are the two things a verified hit
is allowed to cause — and the two things an unverified one must never cause.

RULES THIS FILE MAKES EXECUTABLE:

1. ``open_listening()`` runs ONLY on a verified ATTENDING feed() result.
2. The session is bounded: a hard audio-time ceiling, and a silent close on
   the same ``SilenceLadder`` dictation uses.
3. Half-duplex: never a second capture while ``_MutedCapture``/PTT holds the
   mic; a busy mic drops the session silently.
4. ``capture.state`` on every transition; a rejected hit emits NOTHING.
5. Scorer unavailable / guard unconfigured: no session, no state, no reply.

No hardware, no live mic, no model download: frames are synthetic s16le and
the "verified owner" is a scorer double returning 0.92 above the real
``ecapa_high`` gate. Where the REAL pinned model is used it is marked.
"""

from __future__ import annotations

import asyncio
import itertools
import struct
from pathlib import Path

import pytest

from assistant.config import DEFAULTS
from assistant.daemon import (
    WAKE_LISTEN_CEILING_S,
    WAKE_LISTEN_WINDOW_S,
    Daemon,
)
from assistant.wake_guard import (
    CONF_HIGH,
    CONF_NONE,
    CONF_UNCERTAIN,
    MIN_WINDOW_S,
    OUTCOME_ATTENDING,
    SAMPLE_RATE,
)

FRAME_S = 0.03
FRAME_BYTES = int(SAMPLE_RATE * FRAME_S) * 2
PENDING_WINDOW_S = 2.5          # the shipped pending window the daemon verifies
HITS = 4                        # enough command audio for the 1.75 s floor


#: A per-stream nonce: two verified windows must never be byte-identical, or
#: the guard's own BH-H15 replay rule refuses the second one (correctly — and
#: it is exactly what a replayed recording looks like).
_NONCE = itertools.count()


def speech_frame(amp: int = 6000, nonce: int | None = None) -> bytes:
    samples = SAMPLE_RATE * 30 // 1000
    seed = next(_NONCE) if nonce is None else nonce
    # Deterministic, distinct bytes per frame; still well above the RMS gate.
    values = [amp if index % 7 != seed % 7 else amp - (seed % 512)
              for index in range(samples)]
    return struct.pack(f"<{samples}h", *values)


SILENT_FRAME = b"\x00\x00" * (SAMPLE_RATE * 30 // 1000)


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------
class ScriptedSttModel:
    """Keyword seam: hit for the first HITS frames, then quiet.

    A hit only OPENS the pending window (round J); verification happens when
    the window closes, which takes PENDING_WINDOW_S of frames.
    """

    name = "scripted-keyword"

    def __init__(self, hits: int = HITS):
        self.hits = int(hits)
        self.calls = 0

    def score_window(self, pcm: bytes) -> float:
        self.calls += 1
        return 0.99 if self.calls <= self.hits else 0.0


class ScriptedScorer:
    name = "scripted-ecapa"

    def __init__(self, score=0.92, *, available: bool = True, boom: bool = False):
        self.score = score
        self._available = available
        self.boom = boom
        self.calls: list[int] = []

    def available(self) -> bool:
        return self._available

    def score_owner(self, pcm: bytes):
        self.calls.append(len(pcm))
        if self.boom:
            raise RuntimeError("ECAPA exploded mid-inference")
        return None if self.score is None else float(self.score)


class WindowSource:
    """A capture that yields exactly `frames`, then ends (a bounded stream)."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.target = "scripted-mic"
        self.closed = False

    async def frames(self):
        for frame in self._frames:
            yield frame

    async def aclose(self):
        self.closed = True


class HangingSource(WindowSource):
    """Never ends by itself: only a close can stop it (the bounded-session test)."""

    async def frames(self):
        index = 0
        while True:
            yield self._frames[index % len(self._frames)]
            index += 1
            await asyncio.sleep(0)


@pytest.fixture
def daemon(config):
    d = Daemon(config)
    try:
        yield d
    finally:
        d.store.close()


def _events(daemon) -> list:
    events: list = []

    async def collect(event):
        events.append(event)

    daemon.broadcast = collect
    return events


def _states(events) -> list:
    return [e.get("state") for e in events if e.get("event") == "capture.state"]


def _after_arm(events) -> list:
    """States from the first "verifying" on — the hit's own emissions.

    The always-on loop announces "armed" the moment it starts (BH-K7's
    behaviour, unchanged by this lane); that is not part of a hit.
    """
    states = _states(events)
    return states[states.index("verifying"):] if "verifying" in states else states


def _arm(daemon, *, scorer=None, hits: int = HITS, unsafe: bool = False):
    guard = daemon.wake_guard
    guard.scorer = scorer if scorer is not None else ScriptedScorer()
    guard.arm(unsafe_energy_test=unsafe,
              keyword_model=ScriptedSttModel(hits))
    # A completed session from an earlier phase of a test must not shadow the
    # one this phase opens (it would guard against a second, unrelated hit).
    daemon._wake_listen_task = None
    daemon._wake_listen_source = None
    return guard


def _owner_stream(frames: int) -> list:
    """Enough speechful frames for the pending window to close verified.

    The window closes at `pending_window_s` (2.5 s = 84 frames) and needs at
    least `MIN_WINDOW_S` of command audio to be scored at all.
    """
    need = int(PENDING_WINDOW_S / FRAME_S) + 2
    assert need * FRAME_S >= MIN_WINDOW_S
    return [speech_frame()] * max(frames, need)


#: The ladder the last started session actually read from (see _sessions_started).
_LAST_LADDER: list = []


def _sessions_started(daemon) -> list:
    """Spy on the one seam that may open a session."""
    opened: list = []
    original = daemon._start_wake_listen

    def spy():
        original()
        session = getattr(daemon.wake_guard, "session", None)
        _LAST_LADDER.clear()
        _LAST_LADDER.append(getattr(session, "ladder", None))
        opened.append(daemon._wake_listen_source)

    daemon._start_wake_listen = spy
    return opened


def _run_hotword(daemon, source) -> list:
    events = _events(daemon)
    daemon._hotword_capture_factory = lambda: source

    async def drive():
        # Give the loop a hard stop of its own: a session that survived it
        # would be exactly the unbounded microphone this lane forbids.
        task = asyncio.create_task(daemon._hotword_loop())
        listen = None
        for _ in range(400):
            listen = daemon._wake_listen_task
            if listen is not None and not listen.done():
                break
            if task.done():
                break
            await asyncio.sleep(0.01)
        if listen is not None:
            await asyncio.wait_for(asyncio.shield(listen), timeout=10.0)
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True),
                               timeout=10.0)

    asyncio.run(drive())
    return events


def _control_events(config, frames) -> list:
    """The SAME stream with NO hit at all — the always-on path's own emissions.

    A rejected hit must be indistinguishable from this: if a stranger could
    see one extra `capture.state`, they would know the microphone was
    consulted about them.
    """
    control = Daemon(config)
    try:
        _arm(control, hits=0)
        return _run_hotword(control, WindowSource(frames))
    finally:
        control.store.close()


def _assert_a_rejected_hit_is_indistinguishable(config, daemon, events, frames):
    assert _states(events) == _states(_control_events(config, frames)), (
        f"a rejected hit emitted something the no-hit stream did not: "
        f"{_states(events)!r}")
    assert "open" not in _states(events) and "verifying" not in _states(events)


# ---------------------------------------------------------------------------
# 1. A verified result opens exactly ONE session, and it is bounded
# ---------------------------------------------------------------------------
def test_verified_hit_opens_exactly_one_bounded_session(daemon):
    guard = _arm(daemon)
    assert guard.gate.high == 0.75, "the real threshold, not a test override"
    source = WindowSource(_owner_stream(400))
    opened = _sessions_started(daemon)
    events = _run_hotword(daemon, source)

    assert len(opened) == 1, (
        f"a verified ATTENDING result must open ONE session; opened {len(opened)}")
    assert source.closed, "the always-on capture is closed, never leaked"

    # The session is bounded: an audio-time ceiling plus the shared ladder.
    assert 0.0 < WAKE_LISTEN_CEILING_S <= 60.0
    ceiling = opened[0]
    assert ceiling is not None
    assert ceiling.ceiling_s == WAKE_LISTEN_CEILING_S
    assert _LAST_LADDER[0] is not None
    assert _LAST_LADDER[0].checkin_after_s == WAKE_LISTEN_WINDOW_S, (
        "a wake session may not wait out a dictation-shaped 30 s window")
    # Rule 4: the contract's pair, in that order, exactly once each.
    states = _states(events)
    assert states.count("verifying") == 1 and states.count("open") == 1, states
    assert _after_arm(events)[:2] == ["verifying", "open"], states


def test_a_verified_hit_emits_verifying_then_open(daemon):
    """Rule 4, pinned on its own: the pair, adjacent, in order, once."""
    _arm(daemon)
    source = WindowSource(_owner_stream(400))
    daemon._hotword_capture_factory = lambda: source
    events = _events(daemon)

    async def drive():
        task = asyncio.create_task(daemon._hotword_loop())
        for _ in range(400):
            if daemon._wake_listen_source is not None or task.done():
                break
            await asyncio.sleep(0.01)
        daemon._wake_listen_abort("test")
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True),
                               timeout=5.0)

    asyncio.run(drive())
    states = _states(events)
    assert _after_arm(events)[:2] == ["verifying", "open"], states
    assert states.count("verifying") == 1, states


# ---------------------------------------------------------------------------
# 2. Unverified / uncertain / impostor: ZERO sessions AND ZERO capture.state
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("score,label", [
    (0.60, "uncertain-band"),
    (0.10, "impostor"),
    (None, "no-embedding"),
])
def test_unverified_uncertain_and_impostor_open_nothing_and_emit_nothing(
        daemon, score, label):
    """A stranger must not be able to detect the mic was consulted."""
    guard = _arm(daemon, scorer=ScriptedScorer(score))
    source = WindowSource(_owner_stream(400))
    opened = _sessions_started(daemon)
    events = _run_hotword(daemon, source)

    assert opened == [], f"{label}: no session may open"
    assert guard.state != "attending", f"{label}: {guard.state}"
    assert guard.session is None, f"{label}: no listen session"
    _assert_a_rejected_hit_is_indistinguishable(
        daemon.config, daemon, events, _owner_stream(400))


def test_short_window_never_reaches_listening(daemon):
    """A window too short to verify is too short to open the microphone for.

    The stream ends 0.4 s after the hit: below `MIN_WINDOW_S`, so there is no
    scoring call at all and no close — and a hit that never verifies opens
    nothing. (The guard's own floor is pinned in the round-J suite; this is
    the daemon-level consequence.)
    """
    guard = _arm(daemon, hits=1)
    frames = [speech_frame()] * 14
    source = WindowSource(frames)
    scorer = guard.scorer
    opened = _sessions_started(daemon)
    events = _run_hotword(daemon, source)

    assert opened == []
    assert scorer.calls == [], "below the floor there is no scoring call"
    _assert_a_rejected_hit_is_indistinguishable(
        daemon.config, daemon, events, frames)


def test_an_exception_in_the_guard_opens_nothing(daemon):
    """Rule 1: an exception means no session — and no state change either."""
    guard = _arm(daemon, scorer=ScriptedScorer(boom=True))
    frames = _owner_stream(400)
    opened = _sessions_started(daemon)
    events = _run_hotword(daemon, WindowSource(frames))

    assert opened == []
    assert guard.state != "attending"
    _assert_a_rejected_hit_is_indistinguishable(
        daemon.config, daemon, events, frames)


def test_a_guard_exception_in_feed_is_contained(daemon, monkeypatch):
    """feed() raising must not kill the loop NOR open anything."""
    guard = _arm(daemon)

    def boom(frame, **kwargs):
        raise RuntimeError("guard exploded")

    monkeypatch.setattr(guard, "feed", boom)
    frames = _owner_stream(60)
    opened = _sessions_started(daemon)
    events = _run_hotword(daemon, WindowSource(frames))

    assert opened == []
    assert "open" not in _states(events) and "verifying" not in _states(events)
    assert guard.state != "attending"


def test_unavailable_scorer_means_no_session_no_state_no_reply(daemon):
    """Rule 5: model unavailable -> nothing at all."""
    guard = _arm(daemon, scorer=ScriptedScorer(0.99, available=False))
    frames = _owner_stream(400)
    opened = _sessions_started(daemon)
    events = _run_hotword(daemon, WindowSource(frames))

    assert opened == []
    _assert_a_rejected_hit_is_indistinguishable(
        daemon.config, daemon, events, frames)
    assert len(guard.outbound) == 0
    assert guard.outbound.bytes_out() == 0


def test_an_unconfigured_guard_never_opens_a_session(daemon):
    """No keyword model configured -> hotword.start refuses; no loop, no mic."""
    daemon.config.raw["hotword"]["keyword_model"] = ""

    async def drive():
        with pytest.raises(ValueError, match="wake word paused"):
            await daemon._hotword_start({})

    asyncio.run(drive())
    assert daemon._hotword_task is None
    assert daemon._wake_listen_task is None
    assert daemon.wake_guard.session is None
    assert daemon.wake_guard.state != "attending"


def test_an_attending_label_without_a_verified_verdict_opens_nothing(daemon):
    """Defence in depth: `verified` is a verdict, not a state name.

    A result that claims ATTENDING but does not carry the verified bit — a
    mislabelled guard, a future caller, a forged dict — must open nothing
    and emit nothing. The daemon never infers authority from a label.
    """
    guard = _arm(daemon)
    guard.state = "attending"                  # the dangerous lie
    opened = _sessions_started(daemon)
    events = _events(daemon)

    forged = {"state": "attending", "outcome": OUTCOME_ATTENDING,
              "verified": False, "head_bytes": 0, "trigger": {}}

    async def drive():
        await daemon._wake_listen_after_feed(forged)

    asyncio.run(drive())
    assert opened == []
    assert guard.session is None
    assert _states(events) == []


def test_a_non_attending_outcome_cannot_open_even_with_the_verified_bit(daemon):
    """The mirror case: the bit without the outcome is equally worthless."""
    guard = _arm(daemon)
    guard.state = "attending"
    opened = _sessions_started(daemon)
    events = _events(daemon)

    async def drive():
        await daemon._wake_listen_after_feed(
            {"state": "attending", "outcome": "discarded", "verified": True})

    asyncio.run(drive())
    assert opened == []
    assert _states(events) == []


def test_the_session_ladder_is_bounded_and_is_the_dictation_ladder(daemon):
    """The silence close stays the ONE `SilenceLadder`, with a bounded window.

    `[hotword] checkin_after_s` ships as a dictation-shaped 30 s; with nothing
    transcribed on this path the ladder's silent close would be 30 + grace.
    The session runner clamps the window before a frame is observed, keeps
    `grace_s` as configured, and still uses the same ladder class dictation
    uses — one ladder, no second copy, no second endpointing rule.
    """
    from assistant.transcribe import SilenceLadder

    _arm(daemon)
    opened = _sessions_started(daemon)
    _run_hotword(daemon, WindowSource(_owner_stream(400)))

    assert len(opened) == 1
    ladder = _LAST_LADDER[0]
    assert isinstance(ladder, SilenceLadder), "one ladder, no second copy"
    assert ladder.checkin_after_s == WAKE_LISTEN_WINDOW_S, ladder.checkin_after_s
    assert ladder.grace_s == float(DEFAULTS["hotword"]["grace_s"])
    assert WAKE_LISTEN_WINDOW_S <= 12.0, (
        "a wake session may not wait out a dictation-length window")


# ---------------------------------------------------------------------------
# 3. Half-duplex: a busy mic is zero sessions and zero outbound bytes
# ---------------------------------------------------------------------------
def test_busy_mic_speaking_drops_the_session_silently(daemon):
    """`_MutedCapture` holds the mic while she speaks: no session, no bytes."""
    guard = _arm(daemon)
    daemon._speaking_until = float("inf")        # she is still playing
    assert daemon.is_speaking() is True
    frames = _owner_stream(400)
    opened = _sessions_started(daemon)
    events = _run_hotword(daemon, WindowSource(frames))

    assert opened == [], "no second capture while the mic is muted"
    assert guard.session is None
    assert "open" not in _states(events) and "verifying" not in _states(events)
    assert len(guard.outbound) == 0
    assert guard.outbound.bytes_out() == 0


def test_busy_mic_ptt_drops_the_session_silently(daemon):
    """A PTT press (or a released press still transcribing) owns the mic."""
    guard = _arm(daemon)
    daemon._ptt_session_id = "ptt-live"
    daemon._ptt_finishing = {"ptt-live"}
    opened = _sessions_started(daemon)
    events = _run_hotword(daemon, WindowSource(_owner_stream(400)))

    assert opened == []
    assert guard.session is None
    assert "open" not in _states(events) and "verifying" not in _states(events)
    assert len(guard.outbound) == 0


def test_a_dropped_session_leaves_the_wake_path_intact(daemon):
    """A busy mic drops ONE session; it does not disable the wake path.

    (The stream ending still disarms with "stalled" — BH-K7's rule — so the
    next round re-arms exactly as a restart of the always-on path would.)
    """
    guard = _arm(daemon)
    daemon._speaking_until = float("inf")
    _run_hotword(daemon, WindowSource(_owner_stream(400)))
    assert guard.session is None, "a busy mic must not leave a session behind"

    # The gate reopens and the path re-arms: a verified hit opens one session.
    daemon._speaking_until = 0.0
    _arm(daemon)
    opened = _sessions_started(daemon)
    _run_hotword(daemon, WindowSource(_owner_stream(400)))
    assert len(opened) == 1


def test_a_mic_taken_mid_session_drops_it_without_a_second_capture(daemon):
    """Half-duplex is not only checked at open: the gate can close under us.

    If she starts speaking (or a PTT press lands) while the wake session is
    open, that session is the second capture — it closes, and it does not
    add a *new* signal of its own beyond the honest close.
    """
    guard = _arm(daemon)
    source = WindowSource([speech_frame()] * 3000)
    daemon._hotword_capture_factory = lambda: source
    events = _events(daemon)
    opened = _sessions_started(daemon)

    async def drive():
        task = asyncio.create_task(daemon._hotword_loop())
        for _ in range(400):
            if daemon._wake_listen_source is not None:
                break
            if task.done():
                break
            await asyncio.sleep(0.01)
        listen = daemon._wake_listen_task
        assert listen is not None
        daemon._speaking_until = float("inf")     # the mic is now hers
        await asyncio.wait_for(asyncio.shield(listen), timeout=5.0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(drive())
    assert len(opened) == 1, "one session, opened before the gate closed"
    assert daemon._wake_listen_source is None
    assert guard.session is None, "the session released the mic"
    reasons = [e.get("reason") for e in events if e.get("event") == "capture.state"]
    assert not any("half-duplex" in (r or "") for r in reasons), (
        f"a half-duplex drop is silent about itself: {reasons!r}")


# ---------------------------------------------------------------------------
# 4. The session closes on timeout AND on silence, both emitting capture.state
# ---------------------------------------------------------------------------
def test_session_closes_on_silence_and_emits_capture_state(daemon):
    guard = _arm(daemon)
    # 2.5 s of command audio closes the window verified, then pure silence:
    # the ladder's own silent close ends the session (the dictation schedule).
    frames = _owner_stream(400)[:100] + [SILENT_FRAME] * 2000
    source = WindowSource(frames)
    opened = _sessions_started(daemon)
    events = _run_hotword(daemon, source)

    assert len(opened) == 1
    states = _states(events)
    assert "open" in states, states
    assert states[-1] in ("armed", "released"), (
        f"the close must be visible, got {states!r}")
    assert any("wake session closed" in (e.get("reason") or "")
               for e in events if e.get("event") == "capture.state"), events
    assert guard.session is None
    assert guard.state in ("closed", "idle"), guard.state


def test_session_closes_on_the_hard_ceiling(daemon, monkeypatch):
    """Continuous audio above the floor never earns a ladder close on its own.

    The hard ceiling is what keeps that from being an unbounded microphone.
    """
    guard = _arm(daemon)
    # A 0.3 s ceiling is far below the config's 5 s floor; patch the reader so
    # the bound is exercised in real time rather than 60 s of it.
    monkeypatch.setattr(daemon, "_wake_listen_ceiling_s", lambda: 0.3)
    source = HangingSource([speech_frame()] * 100)
    opened = _sessions_started(daemon)

    events = _events(daemon)
    daemon._hotword_capture_factory = lambda: source

    async def drive():
        task = asyncio.create_task(daemon._hotword_loop())
        listen = None
        for _ in range(400):
            listen = daemon._wake_listen_task
            if listen is not None and not listen.done():
                break
            if task.done():
                break
            await asyncio.sleep(0.01)
        assert listen is not None, "the verified hit must start a session"
        assert opened and opened[0].ceiling_s == 0.3, opened
        await asyncio.wait_for(asyncio.shield(listen), timeout=5.0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(drive())

    assert len(opened) == 1
    assert daemon._wake_listen_source is None, "the bounded session ended"
    states = _states(events)
    assert "open" in states, states
    assert any("ceiling" in (e.get("reason") or "")
               for e in events if e.get("event") == "capture.state"), (
        f"the timeout close must be visible, got {events!r}")
    assert guard.session is None


def test_the_hard_ceiling_cannot_be_configured_away(daemon):
    """Unbounded listening is not a configuration option.

    The ceiling is a code constant and the reader ignores config entirely, so
    no `[hotword]` value — a number, a string, an infinity — can raise it.
    """
    for poisoned in (10 ** 9, "nonsense", float("inf"), -1, None):
        daemon.config.raw["hotword"]["listen_ceiling_s"] = poisoned
        assert daemon._wake_listen_ceiling_s() == WAKE_LISTEN_CEILING_S
    assert WAKE_LISTEN_CEILING_S > 0


def test_hotword_stop_ends_an_open_wake_session(daemon):
    """A session never outlives the path that feeds it."""
    guard = _arm(daemon)
    source = HangingSource([speech_frame()] * 100)
    daemon._hotword_capture_factory = lambda: source
    events = _events(daemon)

    async def drive():
        daemon._hotword_task = asyncio.create_task(daemon._hotword_loop())
        for _ in range(200):
            if daemon._wake_listen_task is not None:
                break
            await asyncio.sleep(0.01)
        assert daemon._wake_listen_task is not None
        await daemon._hotword_stop({})

    asyncio.run(drive())
    assert guard.session is None
    assert daemon._wake_listen_task is None
    assert "released" in _states(events), _states(events)
    assert guard.armed is False


# ---------------------------------------------------------------------------
# 4b. The same wiring on the REAL pinned model (skipped when it cannot load)
# ---------------------------------------------------------------------------
REAL_LEAD = b"\x00\x00" * 4800        # 0.3 s: the hit lands on real speech
REAL_TAIL = b"\x00\x00" * 24000       # 1.5 s: the ladder's silent close


def _real_owner_scorer():
    pytest.importorskip("onnxruntime")
    import numpy as np

    from assistant.voiceprint import EcapaCommandScorer
    from assistant.voicetest import centroid

    root = Path(__file__).resolve().parents[1]
    with np.load(root / "models" / "ecapa_eval_samples.npz",
                 allow_pickle=False) as archive:
        pcm = {key: np.asarray(archive[key], dtype="<i2").tobytes()
               for key in archive.files}
    scorer = EcapaCommandScorer("onnx")
    if scorer.available() is not True:
        pytest.skip(f"pinned speaker model unavailable: {scorer.last_error}")
    vectors = [scorer.embed_pcm(pcm[name])
               for name in ("spk1_snt1", "spk1_snt2", "spk1_snt3")]
    if any(vector is None for vector in vectors):
        pytest.skip(f"pinned speaker model cannot embed: {scorer.last_error}")
    owner = EcapaCommandScorer("onnx", reference=centroid(vectors))
    return owner, pcm, root


def test_real_owner_clip_opens_one_session_and_real_impostor_opens_none(daemon):
    """The measuring stick: the REAL model, a REAL owner clip, a REAL stranger.

    `spk1_snt4` scores 0.7929 >= ecapa_high on the real 2.5 s command window
    and must open exactly one session; `diff_example1` scores 0.042 and must
    open none, with no `verifying`/`open` on the wire.
    """
    owner, pcm, _root = _real_owner_scorer()

    # Traced at the seam: the keyword hit lands once the ring holds ~0.65 s of
    # real audio, which puts the whole command phrase inside the pending
    # window (the same offset the round-J measurements used).
    events = asyncio.run(_two_rounds(daemon, owner, pcm))
    (owner_states, owner_outcome), (impostor_states, impostor_outcome) = events
    assert owner_outcome == OUTCOME_ATTENDING, owner_outcome
    assert owner_states[:2] == ["verifying", "open"], owner_states
    assert impostor_outcome not in (OUTCOME_ATTENDING, None), impostor_outcome
    assert "verifying" not in impostor_states and "open" not in impostor_states, (
        f"a real stranger must emit nothing: {impostor_states!r}")


async def _two_rounds(daemon, owner, pcm):
    """Owner clip, then impostor clip, on one daemon — the guard's own record
    for the owner round is captured before the impostor round overwrites it."""
    results = []
    for name, clip_key in (("owner", "spk1_snt4"), ("impostor", "diff_example1")):
        daemon.wake_guard.scorer = owner
        daemon.wake_guard.arm(keyword_model=_hit_model())
        daemon._wake_listen_task = None
        daemon._wake_listen_source = None
        data = REAL_LEAD + pcm[clip_key] + REAL_TAIL
        events = _events(daemon)
        daemon._hotword_capture_factory = lambda data=data: WindowSource(
            [data[i:i + 960] for i in range(0, len(data), 960)])
        task = asyncio.create_task(daemon._hotword_loop())
        listen = None
        for _ in range(400):
            listen = daemon._wake_listen_task
            if listen is not None and not listen.done():
                break
            if task.done():
                break
            await asyncio.sleep(0.01)
        if listen is not None:
            await asyncio.wait_for(asyncio.shield(listen), timeout=10.0)
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if name == "owner":
            states = _states(events)
            # The always-on loop's own boot "armed" is not part of a hit.
            results.append((_after_arm(events) if "verifying" in states else states,
                            daemon.wake_guard.last_trigger.outcome
                            if daemon.wake_guard.last_trigger else None))
        else:
            results.append((_states(events),
                            daemon.wake_guard.last_trigger.outcome
                            if daemon.wake_guard.last_trigger else None))
    return results


def _hit_model():
    """A keyword seam that hits exactly once the ring holds real audio."""

    class _Model:
        name = "scripted-keyword"

        def __init__(self):
            self.calls = 0

        def score_window(self, pcm_window: bytes) -> float:
            self.calls += 1
            return 0.99 if 10 <= self.calls <= 12 else 0.0

    return _Model()


# ---------------------------------------------------------------------------
# 5. The wiring itself: feed()'s return value is no longer discarded
# ---------------------------------------------------------------------------
def test_the_daemon_acts_on_feed_return_value_not_just_on_state(daemon):
    """The exact 221ad22 defect: a verified result that goes nowhere."""
    guard = _arm(daemon)
    opened = _sessions_started(daemon)
    daemon._hotword_capture_factory = lambda: WindowSource(_owner_stream(400))
    events = _events(daemon)

    async def drive():
        # One frame at a time with the daemon's own body: the frame that closes
        # the window must produce ATTENDING *and* a session.
        for frame in _owner_stream(200):
            if not guard.armed:
                break
            result = guard.feed(frame)
            await daemon._wake_listen_after_feed(result)
            if result is not None:
                assert result["trigger"]["outcome"] == OUTCOME_ATTENDING, result
                assert result["trigger"]["confidence"] == "high", result
                return
        pytest.fail("the verified window never closed with a result")

    asyncio.run(drive())
    assert guard.state in ("listening", "closed"), (
        "the frame that verified must have opened listening, not idled: "
        f"{guard.state}")
    assert len(opened) == 1, (
        "ATTENDING without a session is exactly the 221ad22 defect")
    # The hit's own pair comes first; the close that follows is the session's.
    assert _states(events)[:2] == ["verifying", "open"], _states(events)
    assert _states(events).count("verifying") == 1, _states(events)


def test_open_listening_has_a_call_site_in_the_daemon():
    """A source-level guard against the regression returning: zero call sites."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    callers = {
        path.name for path in src.rglob("*.py")
        if "open_listening(" in path.read_text(encoding="utf-8")
    }
    assert callers == {"daemon.py", "wake_guard.py"}, (
        f"open_listening() must be called by the daemon, not only defined by "
        f"the guard; callers={sorted(callers)}")


def test_rules_frozen_by_this_lane_are_untouched():
    """This lane wires; it does not retune the verification policy."""
    cfg = DEFAULTS["hotword"]
    assert cfg["ecapa_high"] == 0.75
    assert cfg["ecapa_uncertain"] == 0.50
    assert MIN_WINDOW_S == 1.75
    assert CONF_HIGH == "high" and CONF_UNCERTAIN == "uncertain" and CONF_NONE == "none"
    assert OUTCOME_ATTENDING == "attending"
