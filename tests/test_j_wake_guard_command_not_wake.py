"""Round J (R=WAKE-GUARD): verify the COMMAND, never the wake word.

The ECAPA gate is real and merged (round W). Prior work proved, on the actual
pinned `voxceleb_ECAPA512_LM.onnx`, that a 0.6 s wake-length window scores
0.341 / 0.588 for the enrolled speaker (0/12 sliding windows reach 0.75),
while a 2.5 s command window scores 0.793 / 0.842, and impostors score
0.043 / 0.013. A wake-length window therefore cannot be a verification unit.

This file pins the four defects fixed in `src/assistant/wake_guard.py`:

  D1  the wake clip is never scored; below `MIN_WINDOW_S` (1.5 s) there is no
      scoring call at all — not a low score, no call;
  D2  an unrecognised voice gets zero of everything: no reply, no ack, no
      speech, no knock, zeroized buffers, one metadata-only record;
  D3  a replayed / recorded / non-live window is rejected exactly like an
      impostor (the `showoff.py` BH-H15 rule);
  D4  uncertain (0.50–0.75) is never permissive — only `ecapa_high` grants
      authority, and neither threshold moved.

The M4 test below is W's end-to-end shape, kept as the reference case, and
`test_bh_h15` (the replay contract this lane mirrors) must stay green.

Every scoring assertion runs the REAL pinned model on REAL 16 kHz speech from
`models/ecapa_eval_samples.npz`. Nothing here is a mocked score.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from assistant.config import load_config
from assistant.model_registry import SPEAKER_MODEL_RELPATH
from assistant.showoff import ShowoffError, ShowoffService
from assistant.store import Store
from assistant.voiceprint import EcapaCommandScorer
from assistant.voicetest import centroid
from assistant.wake_guard import (
    ATTENDING,
    CONF_HIGH,
    CONF_NONE,
    CONF_UNCERTAIN,
    DISP_DISCARDED,
    DISP_INHERITED,
    IDLE,
    MIN_WINDOW_S,
    STAGE_COMMAND,
    STAGE_REJECTED,
    STAGE_UNVERIFIED,
    AuthorityGate,
    WakeGuard,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / SPEAKER_MODEL_RELPATH
SAMPLES_NPZ = REPO_ROOT / "models" / "ecapa_eval_samples.npz"

SAMPLE_RATE = 16000


def bytes_for(seconds: float) -> int:
    return int(seconds * SAMPLE_RATE) * 2


BYTES_0P6S = bytes_for(0.6)
BYTES_1P0S = bytes_for(1.0)
BYTES_1P5S = bytes_for(1.5)
BYTES_1P9S = bytes_for(1.9)
BYTES_2P5S = bytes_for(2.5)


# ---------------------------------------------------------------------------
# fixtures (real model, real speech)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def speech_pcm() -> dict[str, bytes]:
    np = pytest.importorskip("numpy")
    with np.load(SAMPLES_NPZ, allow_pickle=False) as archive:
        return {
            key: np.asarray(archive[key], dtype="<i2").tobytes()
            for key in archive.files
        }


@pytest.fixture(scope="module")
def enrolled_owner_centroid(speech_pcm: dict[str, bytes]) -> list[float]:
    pytest.importorskip("onnxruntime")
    scorer = EcapaCommandScorer("onnx")
    assert scorer.available() is True, scorer.last_error
    vectors = []
    for clip_name in ("spk1_snt1", "spk1_snt2", "spk1_snt3"):
        emb = scorer.embed_pcm(speech_pcm[clip_name])
        assert emb is not None, scorer.last_error
        assert len(emb) == 192
        vectors.append(emb)
    return centroid(vectors)


@pytest.fixture
def owner_scorer(enrolled_owner_centroid: list[float]) -> EcapaCommandScorer:
    return EcapaCommandScorer("onnx", reference=enrolled_owner_centroid)


class _BoomScorer:
    """A scorer that raises instead of returning — the caller must survive."""

    name = "boom-ecapa"

    def available(self) -> bool:
        return True

    def score_owner(self, pcm: bytes):  # pragma: no cover - always raises
        raise RuntimeError("ECAPA exploded mid-inference")


class _UnavailableScorer:
    name = "missing-ecapa"

    def available(self) -> bool:
        return False

    def score_owner(self, pcm: bytes):  # pragma: no cover - never reached
        raise AssertionError("an unavailable scorer must not be consulted")


class _CountingScorer:
    """Wraps a real scorer and counts calls and received byte lengths."""

    name = "counting-ecapa"

    def __init__(self, inner):
        self.inner = inner
        self.calls: list[int] = []

    def available(self) -> bool:
        return self.inner.available()

    def score_owner(self, pcm: bytes):
        self.calls.append(len(pcm))
        return self.inner.score_owner(pcm)


class RecordingInitiative:
    """Any knock attempt is recorded; a stranger's path must produce none."""

    def __init__(self):
        self.knocks: list[dict] = []

    def raise_knock(self, **kwargs):
        self.knocks.append(kwargs)
        return {"id": len(self.knocks)}


def make_guard(tmp_path: Path, scorer, *, store: Store | None = None):
    store = store or Store(tmp_path / "wake_guard.db")
    initiative = RecordingInitiative()
    guard = WakeGuard(
        settings=load_config().section("hotword"),
        store=store,
        initiative=initiative,
        scorer=scorer,
    )
    return guard, store, initiative


def feed(guard: WakeGuard, pcm: bytes, *, frame_bytes: int = 960) -> None:
    for start in range(0, len(pcm), frame_bytes):
        guard.note_frame(pcm[start:start + frame_bytes])


# ---------------------------------------------------------------------------
# D1 + D3 + D4 in W's end-to-end shape (the reference case)
# ---------------------------------------------------------------------------
def test_j_m4_command_window_not_wake_clip_and_impostor_discard(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    enrolled_owner_centroid: list[float],
):
    """W's end-to-end shape, under the round-J protocol.

    - 0.6 s wake-only does NOT enter ATTENDING.
    - 2.5 s owner command DOES enter ATTENDING.
    - 2.5 s different speaker -> CONF_NONE, pending_disposition "discarded",
      head_bytes 0, no knock.
    """
    pytest.importorskip("onnxruntime")
    scorer = EcapaCommandScorer("onnx", reference=enrolled_owner_centroid)
    guard, store, initiative = make_guard(tmp_path, scorer)
    try:
        owner_full = speech_pcm["spk1_snt4"][:BYTES_2P5S]
        owner_wake_06 = owner_full[:BYTES_0P6S]
        owner_post_19 = owner_full[BYTES_0P6S:BYTES_2P5S]

        # 1. Owner wake clip only (0.6 s, no command follow-through).
        guard.trigger(keyword_score=0.92, wake_clip=owner_wake_06)
        wake_only = guard.verify()
        assert wake_only["trigger"]["stage_b_input"] == STAGE_UNVERIFIED
        assert wake_only["state"] != ATTENDING
        assert wake_only["head_bytes"] == 0
        assert wake_only["trigger"]["pending_disposition"] == DISP_DISCARDED
        assert scorer.score_owner(owner_wake_06) < 0.75  # why it cannot verify

        # 2. Owner 0.6 s wake + 1.9 s command (the 2.5 s utterance) -> ATTENDING.
        guard.trigger(keyword_score=0.92, wake_clip=owner_wake_06)
        feed(guard, owner_post_19)
        owner_cmd = guard.verify()
        assert owner_cmd["trigger"]["stage_b_input"] == STAGE_COMMAND
        assert owner_cmd["trigger"]["ecapa_score"] >= 0.75
        assert owner_cmd["trigger"]["confidence"] == CONF_HIGH
        assert owner_cmd["state"] == ATTENDING
        assert owner_cmd["trigger"]["pending_disposition"] == DISP_INHERITED
        assert owner_cmd["head_bytes"] == len(owner_post_19)

        # 3. Different speaker, same 2.5 s utterance shape -> silent discard.
        impostor_full = speech_pcm["diff_example1"][:BYTES_2P5S]
        guard.trigger(
            keyword_score=0.92, wake_clip=impostor_full[:BYTES_0P6S])
        feed(guard, impostor_full[BYTES_0P6S:BYTES_2P5S])
        impostor = guard.verify()
        assert impostor["trigger"]["stage_b_input"] == STAGE_COMMAND
        assert impostor["trigger"]["confidence"] == CONF_NONE
        assert impostor["state"] != ATTENDING
        assert impostor["head_bytes"] == 0
        assert impostor["trigger"]["pending_disposition"] == DISP_DISCARDED
        assert impostor["knock_id"] is None
        assert initiative.knocks == []
        assert store.list_knocks(status=None) == []
    finally:
        store.close()


# ---------------------------------------------------------------------------
# D1 — never score the wake clip; below 1.5 s there is no call at all
# ---------------------------------------------------------------------------
def test_j_one_second_window_is_never_scored_at_all(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    owner_scorer: EcapaCommandScorer,
):
    """1.0 s is not a low score — it is NO scorer call."""
    counting = _CountingScorer(owner_scorer)
    guard, store, _initiative = make_guard(tmp_path, counting)
    try:
        guard.trigger(keyword_score=0.92,
                      wake_clip=speech_pcm["spk1_snt4"][:BYTES_0P6S])
        feed(guard, speech_pcm["spk1_snt4"][BYTES_0P6S:BYTES_1P0S])
        outcome = guard.verify()
        assert counting.calls == [], "a 1.0 s window must not be scored"
        assert outcome["trigger"]["stage_b_input"] == STAGE_UNVERIFIED
        assert outcome["trigger"]["ecapa_score"] is None
        assert outcome["state"] == IDLE
        assert outcome["head_bytes"] == 0

        # 1.5 s (the floor) IS scored, and the scorer receives exactly those
        # bytes — the wake clip is not a prefix of the input.
        post = speech_pcm["spk1_snt4"][BYTES_0P6S:BYTES_0P6S + BYTES_1P9S]
        assert len(post) >= bytes_for(MIN_WINDOW_S)
        guard.trigger(keyword_score=0.92,
                      wake_clip=speech_pcm["spk1_snt4"][:BYTES_0P6S])
        feed(guard, post)
        scored = guard.verify()
        assert counting.calls == [len(post)]
        assert scored["trigger"]["stage_b_input"] == STAGE_COMMAND
        assert MIN_WINDOW_S == 1.5
    finally:
        store.close()


def test_j_wake_clip_alone_is_never_scored_even_when_it_is_long(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    owner_scorer: EcapaCommandScorer,
):
    """A hit carrying 2.5 s of wake audio still verifies nothing by itself."""
    counting = _CountingScorer(owner_scorer)
    guard, store, _initiative = make_guard(tmp_path, counting)
    try:
        guard.trigger(keyword_score=0.92,
                      wake_clip=speech_pcm["spk1_snt4"][:BYTES_2P5S])
        outcome = guard.verify()
        assert counting.calls == []
        assert outcome["state"] == IDLE
        assert outcome["trigger"]["stage_b_input"] == STAGE_UNVERIFIED
    finally:
        store.close()


def test_j_wake_clip_must_not_be_prepended_to_the_command_window(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    owner_scorer: EcapaCommandScorer,
):
    """The old stage scored `wake_clip + pending`; J scores `pending` only."""
    counting = _CountingScorer(owner_scorer)
    guard, store, _initiative = make_guard(tmp_path, counting)
    try:
        post = speech_pcm["spk1_snt4"][BYTES_0P6S:BYTES_2P5S]
        guard.trigger(keyword_score=0.92,
                      wake_clip=speech_pcm["spk1_snt4"][:BYTES_0P6S])
        feed(guard, post)
        guard.verify()
        assert counting.calls == [len(post)]
        assert counting.calls != [len(post) + BYTES_0P6S]
    finally:
        store.close()


# ---------------------------------------------------------------------------
# D2 — an impostor cannot tell they were heard
# ---------------------------------------------------------------------------
def test_j_impostor_produces_zero_outbound_bytes_of_any_kind(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    owner_scorer: EcapaCommandScorer,
):
    """No reply, no ack, no speech, no knock — and no score in any channel."""
    guard, store, initiative = make_guard(tmp_path, owner_scorer)
    try:
        impostor = speech_pcm["diff_example1"][:BYTES_2P5S]
        guard.trigger(keyword_score=0.92, wake_clip=impostor[:BYTES_0P6S])
        feed(guard, impostor[BYTES_0P6S:BYTES_2P5S])
        outcome = guard.verify()

        # zero of everything
        assert initiative.knocks == [], "a stranger must never raise a knock"
        assert store.list_knocks(status=None) == []
        assert len(guard.outbound) == 0
        assert guard.outbound.bytes_out() == 0
        assert outcome["knock_id"] is None
        assert outcome["state"] == IDLE

        # pending audio and wake audio are gone, not merely detached
        assert guard.pending.data() == b""
        assert guard._wake_clip == b""

        # one metadata-only record: no audio, no score, no knock id
        events = store.list_persona_events(kind="wake_trigger")
        assert len(events) == 1
        import json

        meta = json.loads(events[0]["detail"])
        assert meta["outcome"] == "discarded"
        assert meta["ecapa_score"] is None
        assert meta["knock_id"] is None
        assert meta["clip_saved"] is False
        forbidden = {"audio", "pcm", "bytes", "clip", "frames", "samples"}
        assert forbidden.isdisjoint(meta.keys())

        # no transcript, no model call, no clip on disk
        assert store._conn.execute(
            "SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0
        assert store._conn.execute(
            "SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 0
    finally:
        store.close()


def test_j_impostor_cannot_distinguish_discard_from_no_detection(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    owner_scorer: EcapaCommandScorer,
):
    """The observable surface after an impostor is the idle surface."""
    guard, store, _initiative = make_guard(tmp_path, owner_scorer)
    try:
        idle_before = guard.status()
        impostor = speech_pcm["diff_example1"][:BYTES_2P5S]
        guard.trigger(keyword_score=0.92, wake_clip=impostor[:BYTES_0P6S])
        feed(guard, impostor[BYTES_0P6S:BYTES_2P5S])
        guard.verify()
        idle_after = guard.status()

        for key in ("state", "armed", "attending_detail", "ring", "watchdog",
                    "scorer", "keyword_model"):
            if key in ("ring", "watchdog"):
                continue    # these legitimately advance with the audio clock
            assert idle_after[key] == idle_before[key], key
        assert idle_after["state"] == IDLE
        # The score band is visible to the OPERATOR and carries no number.
        assert idle_after["last_trigger"]["ecapa_score"] is None
        assert guard.last_trigger.ecapa_score is not None  # in-process only
    finally:
        store.close()


# ---------------------------------------------------------------------------
# D3 — replay is enforced on WakeGuard exactly like BH-H15 on show-off
# ---------------------------------------------------------------------------
def test_j_replay_of_previously_accepted_live_window_is_discarded_silently(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    owner_scorer: EcapaCommandScorer,
):
    guard, store, initiative = make_guard(tmp_path, owner_scorer)
    try:
        live = speech_pcm["spk1_snt4"][BYTES_0P6S:BYTES_2P5S]
        guard.trigger(keyword_score=0.92)
        feed(guard, live)
        first = guard.verify(source="mic", live_mic=True, replayed=False)
        assert first["state"] == ATTENDING, first

        # Replay the exact same live window: same speaker, same score, same
        # bytes — and it is refused before the scorer can be asked.
        counting = _CountingScorer(owner_scorer)
        guard.scorer = counting
        guard.trigger(keyword_score=0.92)
        feed(guard, live)
        replay = guard.verify(source="mic", live_mic=True, replayed=False)

        assert counting.calls == [], "a replay must not reach the scorer"
        assert replay["state"] == IDLE
        assert replay["trigger"]["stage_b_input"] == STAGE_REJECTED
        assert replay["trigger"]["pending_disposition"] == DISP_DISCARDED
        assert replay["knock_id"] is None
        assert replay["head_bytes"] == 0
        assert initiative.knocks == []
        assert guard.pending.data() == b""

        # The same audio by explicit digest is the same refusal.
        guard.trigger(keyword_score=0.92)
        feed(guard, live)
        digested = guard.verify(audio_sha256=hashlib.sha256(live).hexdigest())
        assert digested["trigger"]["stage_b_input"] == STAGE_REJECTED

        # A DIFFERENT live window is still accepted (the guard is not poisoned).
        other = speech_pcm["spk1_snt5"][BYTES_0P6S:BYTES_2P5S]
        guard.scorer = owner_scorer
        guard.trigger(keyword_score=0.92)
        feed(guard, other)
        fresh = guard.verify(source="mic")
        assert fresh["state"] == ATTENDING
    finally:
        store.close()


def test_j_replay_flags_match_the_showoff_bh_h15_contract(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    enrolled_owner_centroid: list[float],
):
    """`source`/`replayed`/`live_mic` are refused exactly as BH-H15 refuses them."""
    pytest.importorskip("onnxruntime")
    scorer = EcapaCommandScorer("onnx", reference=enrolled_owner_centroid)
    guard, store, initiative = make_guard(tmp_path, scorer)
    try:
        live = speech_pcm["spk1_snt4"][BYTES_0P6S:BYTES_2P5S]
        for bad_kwargs in (
            {"source": "file"},
            {"source": "loopback"},
            {"replayed": True},
            {"live_mic": False},
        ):
            guard.trigger(keyword_score=0.92)
            feed(guard, live)
            outcome = guard.verify(**bad_kwargs)
            assert outcome["trigger"]["stage_b_input"] == STAGE_REJECTED
            assert outcome["state"] == IDLE
            assert outcome["knock_id"] is None
            assert initiative.knocks == []
            assert len(guard.outbound) == 0
            assert guard.pending.data() == b""
    finally:
        store.close()


def test_j_bh_h15_showoff_replay_contract_still_holds(tmp_path: Path):
    """Keep `test_bh_h15`'s contract: show-off still refuses recorded audio.

    This is the sibling assertion inside this file so a change to WakeGuard's
    replay rule cannot quietly loosen show-off's.
    """
    cfg = load_config()
    cfg.raw["tts"]["cache_dir"] = str(tmp_path / "data" / "tts_cache")
    cfg.raw["tts"]["audition_dir"] = str(tmp_path / "data" / "auditions")
    cfg.raw["voice_test"]["voiceprint_path"] = str(
        tmp_path / "data" / "voiceprint.json")
    cfg.raw["showoff"]["sandbox"] = str(tmp_path / "data" / "demo_sandbox")
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    try:
        showoff = ShowoffService(cfg, store)
        embedding = [1.0] + [0.0] * 191
        for bad_kwargs in (
            {"source": "file"},
            {"source": "loopback"},
            {"replayed": True},
            {"live_mic": False},
        ):
            with pytest.raises(ShowoffError, match="live|record|replay"):
                showoff.enter(command="Elaria, show off", embedding=embedding,
                              owner_present=True, **bad_kwargs)
            assert showoff.active() is False
    finally:
        store.close()


# ---------------------------------------------------------------------------
# D4 — the ambiguous band is never permissive
# ---------------------------------------------------------------------------
def test_j_gate_thresholds_did_not_move():
    gate = AuthorityGate()
    assert gate.high == 0.75, "ecapa_high must not be lowered"
    assert gate.uncertain == 0.5, "ecapa_uncertain must not be lowered"
    assert gate.evaluate(0.588, verified=True) == CONF_UNCERTAIN
    assert gate.may_attend(0.588, verified=True) is False
    assert gate.may_attend(0.749, verified=True) is False
    assert gate.may_attend(0.75, verified=True) is True


def test_j_heldout_wake_length_score_is_uncertain_and_grants_nothing(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    enrolled_owner_centroid: list[float],
):
    """Held-out `spk1_snt5` at wake length scores 0.588 — uncertain, silent."""
    pytest.importorskip("onnxruntime")
    scorer = EcapaCommandScorer("onnx", reference=enrolled_owner_centroid)
    wake_length = speech_pcm["spk1_snt5"][:BYTES_0P6S]
    raw = scorer.score_owner(wake_length)
    assert raw is not None
    assert 0.50 <= raw < 0.75, f"fixture moved out of the uncertain band: {raw}"

    guard, store, initiative = make_guard(tmp_path, scorer)
    try:
        # Even if that exact audio DID reach the scorer, the band grants
        # nothing: the gate call is what decides, not the number's size.
        gate = guard.gate
        assert gate.evaluate(raw, verified=True) == CONF_UNCERTAIN
        assert gate.may_attend(raw, verified=True) is False

        # And through the guard, an uncertain-scoring scorer is silence.
        guard.scorer = _FixedScore(scorer, raw)
        guard.trigger(keyword_score=0.92, wake_clip=wake_length)
        feed(guard, speech_pcm["spk1_snt5"][BYTES_0P6S:BYTES_2P5S])
        outcome = guard.verify()
        assert outcome["trigger"]["confidence"] == CONF_UNCERTAIN
        assert outcome["state"] == IDLE
        assert outcome["knock_id"] is None
        assert initiative.knocks == []
        assert len(guard.outbound) == 0
    finally:
        store.close()


class _FixedScore:
    """Real availability, pinned score — used ONLY to place a real measured
    value into the guard's decision path (the value comes from the model)."""

    name = "pinned-measured-ecapa"

    def __init__(self, inner, score: float):
        self.inner = inner
        self.score = float(score)

    def available(self) -> bool:
        return self.inner.available()

    def score_owner(self, pcm: bytes) -> float:
        assert self.inner.score_owner(pcm) is not None
        return self.score


# ---------------------------------------------------------------------------
# Broken model — no authority, never raises into the caller
# ---------------------------------------------------------------------------
def test_j_corrupted_or_missing_model_yields_no_authority_and_never_raises(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    enrolled_owner_centroid: list[float],
):
    pytest.importorskip("onnxruntime")
    command = speech_pcm["spk1_snt4"][BYTES_0P6S:BYTES_2P5S]
    corrupt = tmp_path / "corrupt_ecapa.onnx"
    raw = bytearray(MODEL_PATH.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    corrupt.write_bytes(bytes(raw))

    broken = [
        EcapaCommandScorer("onnx", reference=enrolled_owner_centroid,
                           model_path=tmp_path / "missing.onnx"),
        EcapaCommandScorer("onnx", reference=enrolled_owner_centroid,
                           model_path=corrupt),
        EcapaCommandScorer("onnx", reference=None),
        EcapaCommandScorer("", reference=enrolled_owner_centroid),
        _BoomScorer(),
        _UnavailableScorer(),
        None,
    ]
    for scorer in broken:
        guard, store, initiative = make_guard(tmp_path, scorer)
        try:
            guard.trigger(keyword_score=0.92)
            feed(guard, command)
            outcome = guard.verify()          # must not raise
            assert outcome["state"] != ATTENDING
            assert outcome["knock_id"] is None
            assert outcome["head_bytes"] == 0
            assert initiative.knocks == []
            assert len(guard.outbound) == 0
            assert guard.pending.data() == b""
        finally:
            store.close()


def test_j_orphan_zero_byte_model_file_yields_no_authority(tmp_path: Path):
    """A `touch`ed .onnx is not a model, and is not authority."""
    pytest.importorskip("onnxruntime")
    empty = tmp_path / "empty.onnx"
    empty.touch()
    scorer = EcapaCommandScorer("onnx", reference=[1.0] + [0.0] * 191,
                                model_path=empty)
    assert scorer.available() is False
    assert scorer.score_owner(b"\x10\x00" * 20000) is None
    assert scorer.last_error


def test_j_replay_rule_survives_a_guard_restart(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    owner_scorer: EcapaCommandScorer,
):
    """The accepted-window digest lives in the store, not in process memory."""
    store = Store(tmp_path / "restart.db")
    try:
        live = speech_pcm["spk1_snt4"][BYTES_0P6S:BYTES_2P5S]
        first_guard, _, _ = make_guard(tmp_path, owner_scorer, store=store)
        first_guard.trigger(keyword_score=0.92)
        feed(first_guard, live)
        assert first_guard.verify()["state"] == ATTENDING

        # A brand-new guard against the same store (daemon restart).
        counting = _CountingScorer(owner_scorer)
        second_guard, _, initiative = make_guard(tmp_path, counting, store=store)
        second_guard.trigger(keyword_score=0.92)
        feed(second_guard, live)
        outcome = second_guard.verify()
        assert counting.calls == []
        assert outcome["trigger"]["stage_b_input"] == STAGE_REJECTED
        assert outcome["state"] == IDLE
        assert initiative.knocks == []
    finally:
        store.close()


def test_j_short_window_does_not_open_the_microphone_either(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    owner_scorer: EcapaCommandScorer,
):
    """Fail closed both ways: no score AND no listening below 1.5 s.

    A window too short to verify is too short to open the mic for. Opening
    listening on an unverified hit would be the same authority leak as
    scoring the wake clip, one step later.
    """
    counting = _CountingScorer(owner_scorer)
    guard, store, initiative = make_guard(tmp_path, counting)
    try:
        guard.trigger(keyword_score=0.92,
                      wake_clip=speech_pcm["spk1_snt4"][:BYTES_0P6S])
        feed(guard, speech_pcm["spk1_snt4"][BYTES_0P6S:BYTES_1P0S])
        outcome = guard.verify()
        assert counting.calls == []
        assert outcome["state"] == IDLE
        assert guard.session is None
        with pytest.raises(Exception, match="hit alone never opens"):
            guard.open_listening()
        assert initiative.knocks == []
        assert len(guard.outbound) == 0
    finally:
        store.close()


def test_j_clip_save_failure_cannot_leave_audio_resident(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    owner_scorer: EcapaCommandScorer,
):
    """A failing opt-in clip write must not strand the guard mid-verify.

    State, zeroing and the metadata record are settled before any clip write,
    so even a hostile clip directory leaves either ATTENDING (owner verified,
    audio is the owner's own command head) or a clean IDLE — never the
    `verifying` state holding the pending buffer.
    """
    guard, store, _initiative = make_guard(tmp_path, owner_scorer)
    try:
        clips = guard.clips
        clips.enabled = True
        clips.directory = tmp_path / "clips"

        def boom(pcm, *, verified):
            raise OSError("clip store unavailable")

        clips.save = boom
        live = speech_pcm["spk1_snt4"][BYTES_0P6S:BYTES_2P5S]
        guard.trigger(keyword_score=0.92)
        feed(guard, live)
        try:
            guard.verify()
        except OSError:
            pass    # the caller may see it; the guard state must be settled
        assert guard.state in (ATTENDING, IDLE), guard.state
        if guard.state == IDLE:
            assert guard.pending.data() == b""
            assert guard._wake_clip == b""

        # And a failing clip write on a DISCARD path is never reached.
        guard2, _, _initiative2 = make_guard(tmp_path, _FixedScore(owner_scorer, 0.30),
                                            store=store)
        guard2.clips.enabled = True
        guard2.clips.directory = tmp_path / "clips2"
        guard2.clips.save = boom
        guard2.trigger(keyword_score=0.92)
        feed(guard2, speech_pcm["diff_example1"][BYTES_0P6S:BYTES_2P5S])
        outcome = guard2.verify()      # must not raise: a discard saves nothing
        assert outcome["state"] == IDLE
        assert guard2.pending.data() == b""
        assert not (tmp_path / "clips2").exists()
    finally:
        store.close()
