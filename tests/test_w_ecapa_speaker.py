"""Round 3 W (WAKE) tests: M1–M4 for pinned WeSpeaker ECAPA-TDNN ONNX speaker verification.

Covers:
  - M1: `PINNED_ROLES["speaker"]` + `PINNED_ARTIFACTS["speaker"]` in
    `model_registry.py` and SHA-256 verification on load in `model_pins.py`
    (failing closed with `PinMismatch` on missing, truncated, corrupted, or
    wrong-hash artifacts).
  - M2: `EcapaCommandScorer` ONNX backend in `voiceprint.py` returning real
    cosine floats on real 16 kHz human speech, `available() == True` iff the
    artifact resolves and its SHA-256 matches, and `score_owner() -> None`
    (zero authority) on any missing/corrupt/unverified input.
  - M3: Replay and recorded-audio rejection (`test_bh_h15` pattern) against
    real 192-d `voxceleb_ECAPA512_LM.onnx` embeddings through `ShowoffService`
    and `EcapaCommandScorer`.
  - M4: `0.6 s` (wake-word length) vs `2.5 s` (command length) window
    evaluation on the SAME speaker and on DIFFERENT speakers at the unchanged
    `0.75` threshold.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from assistant.config import Config, load_config
from assistant.model_pins import (
    PinMismatch,
    parse_pinned_role_spec,
    resolve_pinned_artifact,
    sha256_file,
)
from assistant.model_registry import (
    PINNED_ARTIFACTS,
    PINNED_ROLES,
    SPEAKER_MODEL_BYTES,
    SPEAKER_MODEL_RELPATH,
    SPEAKER_MODEL_REPO,
    SPEAKER_MODEL_REVISION,
    SPEAKER_MODEL_SHA256,
    SPEAKER_VERIFICATION,
    registry_report,
)
from assistant.showoff import ShowoffError, ShowoffService
from assistant.store import Store
from assistant.voiceprint import EcapaCommandScorer, load_reference
from assistant.voicetest import centroid, enroll
from assistant.wake_guard import (
    ATTENDING,
    CONF_HIGH,
    CONF_NONE,
    CONF_UNCERTAIN,
    DISP_DISCARDED,
    DISP_INHERITED,
    STAGE_WAKE_ONLY,
    STAGE_WAKE_PLUS_POST,
    AuthorityGate,
    WakeGuard,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / SPEAKER_MODEL_RELPATH
SAMPLES_NPZ = REPO_ROOT / "models" / "ecapa_eval_samples.npz"

SAMPLE_RATE = 16000
BYTES_0P6S = int(0.6 * SAMPLE_RATE) * 2   # 9,600 samples = 19,200 bytes
BYTES_2P5S = int(2.5 * SAMPLE_RATE) * 2   # 40,000 samples = 80,000 bytes


def _sandbox_config(tmp_path: Path) -> Config:
    cfg = load_config()
    cfg.raw["tts"]["cache_dir"] = str(tmp_path / "data" / "tts_cache")
    cfg.raw["tts"]["audition_dir"] = str(tmp_path / "data" / "auditions")
    cfg.raw["voice_test"]["voiceprint_path"] = str(
        tmp_path / "data" / "voiceprint.json"
    )
    cfg.raw["voice_test"]["embedding_dim"] = 192
    cfg.raw["showoff"]["sandbox"] = str(tmp_path / "data" / "demo_sandbox")
    cfg.ensure_dirs()
    return cfg


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


# ===========================================================================
# M1 — Model Registry Pin + SHA-256 Verification on Load (Fail Closed)
# ===========================================================================


def test_m1_speaker_role_recorded_in_pinned_roles_without_registry_drift():
    assert "speaker" in PINNED_ROLES
    assert "speaker" in PINNED_ARTIFACTS
    assert PINNED_ROLES["speaker"] == SPEAKER_VERIFICATION
    assert SPEAKER_MODEL_REPO == "Wespeaker/wespeaker-ecapa-tdnn512-LM"
    assert SPEAKER_MODEL_REVISION == "a2f3dcb1c8702caccc7a55ceb57f5e8d1842112b"
    assert (
        SPEAKER_MODEL_SHA256
        == "d71b85d9b48058ef68004f04f1b78acebefb9dfcf542e19b976a12a5ad1f10b0"
    )

    parsed = parse_pinned_role_spec(PINNED_ROLES["speaker"])
    assert parsed == {
        "artifact_id": SPEAKER_MODEL_REPO,
        "revision": SPEAKER_MODEL_REVISION,
        "sha256": SPEAKER_MODEL_SHA256,
    }

    report = registry_report(load_config())
    assert report["ok"] is True
    assert report["role_drift"] == []
    assert report["unregistered"] == []
    assert report["forbidden"] == []


def test_m1_resolve_pinned_artifact_verifies_sha256_on_load():
    verified = resolve_pinned_artifact("speaker")
    assert verified.role == "speaker"
    assert verified.artifact_id == SPEAKER_MODEL_REPO
    assert verified.revision == SPEAKER_MODEL_REVISION
    assert verified.sha256 == SPEAKER_MODEL_SHA256
    assert verified.path == MODEL_PATH
    assert len(verified.data) == SPEAKER_MODEL_BYTES
    assert sha256_file(MODEL_PATH) == SPEAKER_MODEL_SHA256


def test_m1_resolve_pinned_artifact_fails_closed_on_mismatch_or_corruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # 1. Unknown role
    with pytest.raises(PinMismatch, match="unknown pinned artifact role"):
        resolve_pinned_artifact("nonexistent_role")

    # 2. Missing file
    with pytest.raises(PinMismatch, match="missing or not a regular file"):
        resolve_pinned_artifact("speaker", path=tmp_path / "missing.onnx")

    # 3. Directory instead of file
    with pytest.raises(PinMismatch, match="missing or not a regular file"):
        resolve_pinned_artifact("speaker", path=tmp_path)

    # 4. Truncated artifact
    truncated = tmp_path / "truncated.onnx"
    truncated.write_bytes(MODEL_PATH.read_bytes()[:4096])
    with pytest.raises(PinMismatch, match="sha256 mismatch"):
        resolve_pinned_artifact("speaker", path=truncated)

    # 5. Single-bit flip at identical byte length
    corrupted = tmp_path / "corrupted.onnx"
    raw = bytearray(MODEL_PATH.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    corrupted.write_bytes(bytes(raw))
    with pytest.raises(PinMismatch, match="sha256 mismatch"):
        resolve_pinned_artifact("speaker", path=corrupted)

    # 6. Wrong expected_sha256 against the intact file
    with pytest.raises(PinMismatch, match="does not match registry pin"):
        resolve_pinned_artifact("speaker", expected_sha256="0" * 64)

    # 7. Corrupt model-pins.json in config.data_dir fails closed
    bad_dir = tmp_path / "bad_pins"
    bad_dir.mkdir()
    (bad_dir / "model-pins.json").write_text("{not-json", encoding="utf-8")
    fake_cfg = type("Cfg", (), {"data_dir": bad_dir})()
    with pytest.raises(PinMismatch, match="unreadable"):
        resolve_pinned_artifact("speaker", config=fake_cfg)

    # 8. Registry pin tamper fails closed
    wrong_spec = (
        f"{SPEAKER_MODEL_REPO}@{SPEAKER_MODEL_REVISION}#sha256:{'f' * 64}"
    )
    monkeypatch.setitem(PINNED_ROLES, "speaker", wrong_spec)
    with pytest.raises(PinMismatch, match="drift"):
        resolve_pinned_artifact("speaker")


# ===========================================================================
# M2 — EcapaCommandScorer Real ONNX Backend + Corrupt/Wrong-Hash Fail-Closed
# ===========================================================================


def test_m2_ecapa_command_scorer_returns_real_float_from_real_audio(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    enrolled_owner_centroid: list[float],
):
    pytest.importorskip("onnxruntime")
    ref_path = tmp_path / "voiceprint.json"
    ref_path.write_text(
        json.dumps(
            {
                "model": SPEAKER_VERIFICATION,
                "dimension": 192,
                "centroid": enrolled_owner_centroid,
            }
        ),
        encoding="utf-8",
    )
    loaded_ref = load_reference(ref_path)
    assert loaded_ref is not None and len(loaded_ref) == 192

    for cmd in ("onnx", str(MODEL_PATH), f"onnx:{MODEL_PATH}"):
        scorer = EcapaCommandScorer(cmd, reference=loaded_ref)
        assert scorer.available() is True, scorer.last_error
        same_score = scorer.score_owner(speech_pcm["spk1_snt4"][:BYTES_2P5S])
        diff_score = scorer.score_owner(speech_pcm["diff_example1"][:BYTES_2P5S])
        assert isinstance(same_score, float)
        assert isinstance(diff_score, float)
        assert 0.75 <= same_score < 1.0
        assert -1.0 <= diff_score < 0.25
        # Deterministic across repeated calls
        assert scorer.score_owner(speech_pcm["spk1_snt4"][:BYTES_2P5S]) == pytest.approx(
            same_score
        )


def test_m2_corrupted_artifact_or_wrong_hash_yields_unavailable_and_no_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    gate = AuthorityGate()  # unchanged 0.75 threshold
    fake_ref = [1.0] + [0.0] * 191
    sample_pcm = b"\x10\x00\xf0\xff" * 20000  # 2.5 s non-zero 16 kHz PCM

    # 1. Corrupted copy (single byte flipped, exact 24,861,931-byte size preserved)
    corrupted_onnx = tmp_path / "corrupt_ecapa.onnx"
    buf = bytearray(MODEL_PATH.read_bytes())
    buf[1024] ^= 0xFF
    corrupted_onnx.write_bytes(bytes(buf))

    corrupt_scorer = EcapaCommandScorer(
        "onnx", reference=fake_ref, model_path=corrupted_onnx
    )
    assert corrupt_scorer.available() is False
    assert "sha256 mismatch" in (corrupt_scorer.last_error or "")
    corrupt_score = corrupt_scorer.score_owner(sample_pcm)
    assert corrupt_score is None
    band = gate.evaluate(
        corrupt_score,
        verified=corrupt_scorer.available() and corrupt_score is not None,
    )
    assert band == CONF_NONE

    # 2. Wrong expected SHA-256 against the intact ONNX artifact
    wrong_hash_scorer = EcapaCommandScorer(
        "onnx",
        reference=fake_ref,
        model_path=MODEL_PATH,
        expected_sha256="a" * 64,
    )
    assert wrong_hash_scorer.available() is False
    assert wrong_hash_scorer.score_owner(sample_pcm) is None
    band2 = gate.evaluate(
        wrong_hash_scorer.score_owner(sample_pcm),
        verified=wrong_hash_scorer.available(),
    )
    assert band2 == CONF_NONE

    # 3. Missing artifact path
    missing_scorer = EcapaCommandScorer(
        "onnx", reference=fake_ref, model_path=tmp_path / "does_not_exist.onnx"
    )
    assert missing_scorer.available() is False
    assert missing_scorer.score_owner(sample_pcm) is None

    # 4. Post-load in-place corruption revokes availability and authority immediately
    pytest.importorskip("onnxruntime")
    live_copy = tmp_path / "live_copy.onnx"
    shutil.copyfile(MODEL_PATH, live_copy)
    live_scorer = EcapaCommandScorer(
        "onnx", reference=fake_ref, model_path=live_copy
    )
    assert live_scorer.available() is True
    assert isinstance(live_scorer.score_owner(sample_pcm), float)

    tampered = bytearray(live_copy.read_bytes())
    tampered[2048] ^= 0x01
    live_copy.write_bytes(bytes(tampered))

    assert live_scorer.available() is False
    assert live_scorer.score_owner(sample_pcm) is None
    band3 = gate.evaluate(None, verified=live_scorer.available())
    assert band3 == CONF_NONE

    # 5. Missing onnxruntime package fails closed without crashing
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    no_ort = EcapaCommandScorer("onnx", reference=fake_ref)
    assert no_ort.available() is False
    assert no_ort.score_owner(sample_pcm) is None


def test_m2_missing_reference_or_bad_audio_returns_none_never_default(
    speech_pcm: dict[str, bytes],
    enrolled_owner_centroid: list[float],
):
    pytest.importorskip("onnxruntime")
    valid_pcm = speech_pcm["spk1_snt4"][:BYTES_2P5S]

    # Unconfigured command
    assert EcapaCommandScorer("").available() is False
    assert EcapaCommandScorer("").score_owner(valid_pcm) is None
    assert EcapaCommandScorer(None).available() is False
    assert EcapaCommandScorer(None).score_owner(valid_pcm) is None

    # Missing or malformed reference vector
    assert EcapaCommandScorer("onnx", reference=None).score_owner(valid_pcm) is None
    assert EcapaCommandScorer("onnx", reference=[]).score_owner(valid_pcm) is None
    assert (
        EcapaCommandScorer("onnx", reference=[1.0, 0.0, 0.0, 0.0]).score_owner(
            valid_pcm
        )
        is None
    )
    assert (
        EcapaCommandScorer(
            "onnx", reference=[float("nan")] * 192
        ).score_owner(valid_pcm)
        is None
    )

    # Empty, sub-frame (<25ms), odd-byte, silent, or wrong-rate audio
    scorer = EcapaCommandScorer("onnx", reference=enrolled_owner_centroid)
    assert scorer.score_owner(b"") is None
    assert scorer.score_owner(b"\x01") is None
    assert scorer.score_owner(b"\x01\x00" * 399) is None  # < 400 samples (25 ms)
    assert scorer.score_owner(b"\x00\x00" * 40000) is None  # pure digital silence
    wrong_rate = EcapaCommandScorer(
        "onnx", reference=enrolled_owner_centroid, sample_rate=48000
    )
    assert wrong_rate.available() is False
    assert wrong_rate.score_owner(valid_pcm) is None


# ===========================================================================
# M3 — Replay & Recorded Owner Audio Rejection Against Real ECAPA Backend
# ===========================================================================


def test_m3_bh_h15_showoff_rejects_recorded_or_replayed_owner_audio_real_ecapa(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
):
    """M3: Reuses `test_bh_h15_showoff_rejects_recorded_or_replayed_owner_audio`
    against the real 192-d `voxceleb_ECAPA512_LM.onnx` backend.
    """
    pytest.importorskip("onnxruntime")
    cfg = _sandbox_config(tmp_path)
    store = Store(cfg.db_path)
    try:
        scorer = EcapaCommandScorer("onnx")
        assert scorer.available() is True

        sidecar_dir = tmp_path / "enroll_sidecars"
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        for idx, name in enumerate(("spk1_snt1", "spk1_snt2", "spk1_snt3")):
            clip_bytes = speech_pcm[name]
            vec = scorer.embed_pcm(clip_bytes)
            assert vec is not None and len(vec) == 192
            (sidecar_dir / f"{idx:02d}_{name}.embedding.json").write_text(
                json.dumps(
                    {
                        "embedding": vec,
                        "speech_seconds": len(clip_bytes) / (2.0 * SAMPLE_RATE),
                    }
                ),
                encoding="utf-8",
            )
        voiceprint_path = Path(cfg.section("voice_test")["voiceprint_path"])
        voiceprint_path.parent.mkdir(parents=True, exist_ok=True)
        enroll_summary = enroll(
            sidecar_dir,
            voiceprint_path,
            model=SPEAKER_VERIFICATION,
        )
        assert enroll_summary["dimension"] == 192
        assert enroll_summary["file_count"] == 3

        # Held-out genuine owner utterance (spk1_snt4, 2.53 s)
        owner_clip = speech_pcm["spk1_snt4"]
        emb = scorer.embed_pcm(owner_clip)
        assert emb is not None and len(emb) == 192
        clip_hash = hashlib.sha256(owner_clip).hexdigest()

        # Also check EcapaCommandScorer itself rejects recorded/replayed flags
        scorer_with_ref = EcapaCommandScorer(
            "onnx",
            reference=load_reference(cfg.section("voice_test")["voiceprint_path"]),
        )
        assert scorer_with_ref.score_owner(owner_clip) >= 0.75
        for bad_kwargs in (
            {"source": "file"},
            {"source": "loopback"},
            {"replayed": True},
            {"live_mic": False},
        ):
            assert scorer_with_ref.score_owner(owner_clip, **bad_kwargs) is None

        showoff = ShowoffService(cfg, store)

        # 1. Recorded / file / loopback / replayed owner audio MUST fail even
        #    with a real owner ECAPA embedding scoring >= 0.75.
        for bad_kwargs in (
            {"source": "file"},
            {"source": "loopback"},
            {"replayed": True},
            {"live_mic": False},
        ):
            with pytest.raises(ShowoffError, match="live|record|replay"):
                showoff.enter(
                    command="Elaria, show off",
                    embedding=emb,
                    owner_present=True,
                    **bad_kwargs,
                )
            assert showoff.active() is False

        # 2. First live mic entry with genuine owner audio succeeds, then exits.
        entered = showoff.enter(
            command="Elaria, show off",
            embedding=emb,
            owner_present=True,
            source="mic",
            audio_sha256=clip_hash,
        )
        assert entered["entered"] is True
        assert showoff.active() is True
        assert entered["verification"]["verified"] is True
        assert entered["verification"]["score"] >= 0.75
        showoff.exit_hotkey()
        assert showoff.active() is False

        # 3. Replaying the exact same owner audio clip (audio_sha256) MUST fail.
        with pytest.raises(ShowoffError, match="replay|live"):
            showoff.enter(
                command="Elaria, show off",
                embedding=emb,
                owner_present=True,
                source="mic",
                audio_sha256=clip_hash,
            )
        assert showoff.active() is False

        # 4. Different speaker's real audio on live mic MUST ALSO fail (< 0.75).
        impostor_clip = speech_pcm["diff_example1"]
        impostor_emb = scorer.embed_pcm(impostor_clip)
        assert impostor_emb is not None
        with pytest.raises(ShowoffError, match="0.75|verify|speaker"):
            showoff.enter(
                command="Elaria, show off",
                embedding=impostor_emb,
                owner_present=True,
                source="mic",
                audio_sha256=hashlib.sha256(impostor_clip).hexdigest(),
            )
        assert showoff.active() is False
    finally:
        store.close()


# ===========================================================================
# M4 — 0.6 s (Wake-Word Length) vs 2.5 s (Command Length) Real Window Test
# ===========================================================================


def test_m4_window_0p6s_vs_2p5s_same_and_different_speakers(
    speech_pcm: dict[str, bytes],
    enrolled_owner_centroid: list[float],
):
    """M4: Feed real `voxceleb_ECAPA512_LM.onnx` 0.6 s and 2.5 s windows on the
    SAME speaker (`spk1` held-out utterances) and on DIFFERENT speakers
    (`diff_example1` and `spk2`), keeping `ecapa_high = 0.75` unchanged.
    """
    pytest.importorskip("onnxruntime")
    scorer = EcapaCommandScorer("onnx", reference=enrolled_owner_centroid)
    assert scorer.available() is True
    gate = AuthorityGate()  # unchanged ecapa_high = 0.75

    # --- Same speaker (held-out spk1_snt4 & spk1_snt5) ---
    same_a_06 = scorer.score_owner(speech_pcm["spk1_snt4"][:BYTES_0P6S])
    same_a_25 = scorer.score_owner(speech_pcm["spk1_snt4"][:BYTES_2P5S])
    same_b_06 = scorer.score_owner(speech_pcm["spk1_snt5"][:BYTES_0P6S])
    same_b_25 = scorer.score_owner(speech_pcm["spk1_snt5"][:BYTES_2P5S])

    assert same_a_06 is not None and same_a_25 is not None
    assert same_b_06 is not None and same_b_25 is not None

    # 2.5 s command windows pass the unchanged 0.75 authority threshold
    assert same_a_25 >= 0.75
    assert same_b_25 >= 0.75
    assert gate.evaluate(same_a_25, verified=True) == CONF_HIGH
    assert gate.evaluate(same_b_25, verified=True) == CONF_HIGH

    # 0.6 s wake-length windows are meaningfully lower than 2.5 s and fail 0.75
    assert same_a_06 < 0.75
    assert same_b_06 < 0.75
    assert (same_a_25 - same_a_06) >= 0.20
    assert (same_b_25 - same_b_06) >= 0.20
    assert gate.evaluate(same_a_06, verified=True) in {CONF_NONE, CONF_UNCERTAIN}
    assert gate.evaluate(same_b_06, verified=True) in {CONF_NONE, CONF_UNCERTAIN}

    # --- Different speakers (single-clip diff_example1 & spk2) ---
    diff_a_06 = scorer.score_owner(speech_pcm["diff_example1"][:BYTES_0P6S])
    diff_a_25 = scorer.score_owner(speech_pcm["diff_example1"][:BYTES_2P5S])

    spk2_concat = speech_pcm["spk2_snt1"] + speech_pcm["spk2_snt2"]
    diff_b_06 = scorer.score_owner(spk2_concat[:BYTES_0P6S])
    diff_b_25 = scorer.score_owner(spk2_concat[:BYTES_2P5S])

    assert diff_a_06 is not None and diff_a_25 is not None
    assert diff_b_06 is not None and diff_b_25 is not None

    # Unrecognised speakers fail 0.75 at BOTH 0.6 s and 2.5 s -> CONF_NONE
    for imp_score in (diff_a_06, diff_a_25, diff_b_06, diff_b_25):
        assert imp_score < 0.25
        band = gate.evaluate(imp_score, verified=True)
        assert band == CONF_NONE


def test_m4_wake_guard_real_ecapa_command_window_vs_wake_clip_and_impostor_discard(
    tmp_path: Path,
    speech_pcm: dict[str, bytes],
    enrolled_owner_centroid: list[float],
):
    """End-to-end `WakeGuard` + real `EcapaCommandScorer("onnx")` verification:
    - 0.6 s wake clip alone does NOT grant ATTENDING even on the enrolled owner.
    - 2.5 s owner command window (0.6 s wake + 1.9 s post-wake speech) grants ATTENDING.
    - 2.5 s different-speaker utterance yields CONF_NONE and discards pending audio
      untranscribed (`head_bytes == 0`, metadata-only trigger row).
    """
    pytest.importorskip("onnxruntime")
    store = Store(tmp_path / "wake_guard.db")
    try:
        scorer = EcapaCommandScorer("onnx", reference=enrolled_owner_centroid)
        guard = WakeGuard(
            settings=load_config().section("hotword"),
            store=store,
            scorer=scorer,
        )

        owner_full = speech_pcm["spk1_snt4"][:BYTES_2P5S]
        owner_wake_06 = owner_full[:BYTES_0P6S]
        owner_post_19 = owner_full[BYTES_0P6S:BYTES_2P5S]

        # 1. Owner 0.6 s wake clip ONLY (no command follow-through) -> NOT attending
        guard.trigger(keyword_score=0.92, wake_clip=owner_wake_06)
        wake_only_res = guard.verify()
        assert wake_only_res["trigger"]["stage_b_input"] == STAGE_WAKE_ONLY
        assert wake_only_res["trigger"]["ecapa_score"] < 0.75
        assert wake_only_res["state"] != ATTENDING
        assert wake_only_res["head_bytes"] == 0
        assert wake_only_res["trigger"]["pending_disposition"] == DISP_DISCARDED

        # 2. Owner 0.6 s wake + 1.9 s command (total 2.5 s) -> CONF_HIGH + ATTENDING
        guard.trigger(keyword_score=0.92, wake_clip=owner_wake_06)
        guard.note_frame(owner_post_19)
        owner_cmd_res = guard.verify()
        assert owner_cmd_res["trigger"]["stage_b_input"] == STAGE_WAKE_PLUS_POST
        assert owner_cmd_res["trigger"]["ecapa_score"] >= 0.75
        assert owner_cmd_res["trigger"]["confidence"] == CONF_HIGH
        assert owner_cmd_res["state"] == ATTENDING
        assert owner_cmd_res["trigger"]["pending_disposition"] == DISP_INHERITED
        assert owner_cmd_res["head_bytes"] == len(owner_post_19)

        # 3. Unrecognised speaker 2.5 s utterance -> CONF_NONE, pending discarded
        impostor_full = speech_pcm["diff_example1"][:BYTES_2P5S]
        guard.trigger(
            keyword_score=0.92, wake_clip=impostor_full[:BYTES_0P6S]
        )
        guard.note_frame(impostor_full[BYTES_0P6S:BYTES_2P5S])
        imp_res = guard.verify()
        assert imp_res["trigger"]["stage_b_input"] == STAGE_WAKE_PLUS_POST
        assert imp_res["trigger"]["ecapa_score"] < 0.25
        assert imp_res["trigger"]["confidence"] == CONF_NONE
        assert imp_res["state"] != ATTENDING
        assert imp_res["head_bytes"] == 0
        assert imp_res["trigger"]["pending_disposition"] == DISP_DISCARDED
    finally:
        store.close()

