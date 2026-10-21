"""The sample recorder and frozen eval split must stay inside their root."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record_elaria_samples.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("record_elaria_samples_bug", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _take(root: Path, split: str, bucket: str, name: str, data: bytes = b"wav") -> Path:
    path = root / split / bucket / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_bug_sample_record_rejects_bucket_escape_before_recording(tmp_path, monkeypatch):
    script = _load_script()
    root = tmp_path / "samples"
    root.mkdir()
    called = []
    monkeypatch.setattr(script.time, "sleep", lambda _seconds: None)

    def fake_record_take(*, out_path, **_kwargs):
        called.append(Path(out_path))
        return {"bytes": 3, "device": "synthetic"}

    monkeypatch.setattr(script, "record_take", fake_record_take)
    args = SimpleNamespace(bucket="../../escaped", device="", takes=1,
                           phrase="Elaria", seconds=1.0)
    result = script.cmd_record(args, root)

    assert result == 2, "unsafe bucket must be refused before capture starts"
    assert not called, f"recorder received out-of-root path {called[0] if called else None}"


@pytest.mark.parametrize("takes,seconds", [
    (-1, 1.0), (0, 1.0), (1, 0.0), (1, -1.0), (1, float("nan")),
])
def test_bug_sample_record_rejects_invalid_capture_parameters(
        tmp_path, monkeypatch, takes, seconds):
    script = _load_script()
    root = tmp_path / "samples"
    root.mkdir()
    called = []
    monkeypatch.setattr(script.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(script, "record_take", lambda **kwargs: (
        called.append(kwargs) or {"device": "synthetic", "bytes": 0}))
    args = SimpleNamespace(bucket="safe-bucket", device="", takes=takes,
                           phrase="Elaria", seconds=seconds)

    assert script.cmd_record(args, root) == 2
    assert not called, "invalid capture parameters reached the recorder"


def test_bug_sample_record_never_overwrites_a_same_second_take(tmp_path, monkeypatch):
    script = _load_script()
    root = tmp_path / "samples"
    root.mkdir()
    existing = root / "train" / "safe-bucket" / "safe-bucket-20261021-195302-000.wav"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"keep this take")
    monkeypatch.setattr(script.time, "strftime", lambda fmt: (
        "20261021-195302" if "%Y%m%d" in fmt else "2026-10-21T19:53:02"))
    monkeypatch.setattr(script.time, "sleep", lambda _seconds: None)
    recorded = []

    def fake_record_take(*, out_path, **_kwargs):
        path = Path(out_path)
        recorded.append(path)
        path.write_bytes(b"new take")
        return {"bytes": 8, "device": "synthetic"}

    monkeypatch.setattr(script, "record_take", fake_record_take)
    args = SimpleNamespace(bucket="safe-bucket", device="", takes=1,
                           phrase="Elaria", seconds=1.0)
    assert script.cmd_record(args, root) == 0

    assert existing.read_bytes() == b"keep this take"
    assert recorded and recorded[0] != existing


def test_bug_record_refuses_manifest_symlink_before_capture(tmp_path, monkeypatch):
    script = _load_script()
    root = tmp_path / "samples"
    root.mkdir()
    outside_manifest = tmp_path / "outside.jsonl"
    outside_manifest.write_text("keep outside data\n", encoding="utf-8")
    (root / script.MANIFEST).symlink_to(outside_manifest)
    called = []
    monkeypatch.setattr(script, "record_take", lambda **kwargs: called.append(kwargs))
    args = SimpleNamespace(bucket="safe-bucket", device="", takes=1,
                           phrase="Elaria", seconds=1.0)

    assert script.cmd_record(args, root) == 2
    assert not called
    assert outside_manifest.read_text(encoding="utf-8") == "keep outside data\n"


def test_bug_freeze_eval_refuses_symlinked_train_bucket(tmp_path):
    script = _load_script()
    root = tmp_path / "samples"
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "outside.wav"
    source.write_bytes(b"private outside take")
    train = root / "train"
    train.mkdir(parents=True)
    (train / "bucket").symlink_to(outside, target_is_directory=True)

    refused = False
    try:
        script.freeze_eval(root, fraction=1.0, seed=7)
    except (OSError, ValueError, RuntimeError):
        refused = True

    assert refused, "freeze-eval followed a bucket symlink outside its root"
    assert source.read_bytes() == b"private outside take"


def test_bug_freeze_eval_refuses_symlinked_eval_bucket(tmp_path):
    script = _load_script()
    root = tmp_path / "samples"
    outside = tmp_path / "outside"
    outside.mkdir()
    original = outside / "take.wav"
    original.write_bytes(b"outside eval bytes")
    source = _take(root, "train", "bucket", "take.wav", b"training bytes")
    eval_root = root / "eval"
    eval_root.mkdir()
    (eval_root / "bucket").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        script.freeze_eval(root, fraction=1.0, seed=7)

    assert source.read_bytes() == b"training bytes"
    assert original.read_bytes() == b"outside eval bytes"


def test_bug_freeze_eval_never_overwrites_an_existing_eval_take(tmp_path):
    script = _load_script()
    root = tmp_path / "samples"
    source = _take(root, "train", "bucket", "take.wav", b"new training bytes")
    destination = _take(root, "eval", "bucket", "take.wav", b"existing eval bytes")

    refused = False
    try:
        script.freeze_eval(root, fraction=1.0, seed=7)
    except (OSError, ValueError, RuntimeError):
        refused = True

    assert refused, "existing eval destination must refuse the split"
    assert source.read_bytes() == b"new training bytes"
    assert destination.read_bytes() == b"existing eval bytes"


def test_bug_freeze_eval_zero_fraction_moves_no_take(tmp_path):
    script = _load_script()
    root = tmp_path / "zero"
    source = _take(root, "train", "bucket", "take.wav")

    result = script.freeze_eval(root, fraction=0.0, seed=7)

    assert result["moved"].get("bucket", 0) == 0
    assert source.exists()


@pytest.mark.parametrize("fraction", [-0.1, 1.1, 2.0, float("nan"), float("inf")])
def test_bug_freeze_eval_rejects_invalid_fraction_without_mutation(
        tmp_path, fraction):
    script = _load_script()
    root = tmp_path / "invalid"
    source = _take(root, "train", "bucket", "take.wav")

    with pytest.raises(ValueError):
        script.freeze_eval(root, fraction=fraction, seed=7)

    assert source.read_bytes() == b"wav"
    assert not (root / "eval").exists()


def test_bug_freeze_eval_updates_manifest_and_cannot_run_twice(tmp_path):
    script = _load_script()
    root = tmp_path / "samples"
    bucket = "elaria-close-normal"
    names = [f"take-{index}.wav" for index in range(5)]
    for name in names:
        _take(root, "train", bucket, name)
        script.append_manifest(root, {
            "id": name, "bucket": bucket, "path": f"train/{bucket}/{name}"})

    first = script.freeze_eval(root, fraction=0.2, seed=7)
    moved = set((root / "eval" / bucket).glob("*.wav"))
    moved_names = {path.name for path in moved}
    assert first["moved"].get(bucket) == 1
    rows = script.read_manifest(root)
    expected_eval_paths = {f"eval/{bucket}/{name}" for name in moved_names}
    actual_eval_paths = {row["path"] for row in rows if row["path"].startswith("eval/")}
    assert actual_eval_paths == expected_eval_paths, "manifest paths stayed stale under train/"

    remaining_before = {path.name for path in (root / "train" / bucket).glob("*.wav")}
    with pytest.raises(RuntimeError, match="already frozen"):
        script.freeze_eval(root, fraction=0.2, seed=7)
    remaining_after = {path.name for path in (root / "train" / bucket).glob("*.wav")}
    assert remaining_after == remaining_before


def test_bug_freeze_eval_rolls_back_partial_moves_on_failure(tmp_path, monkeypatch):
    script = _load_script()
    root = tmp_path / "samples"
    bucket = "bucket"
    names = ["first.wav", "second.wav"]
    for name in names:
        _take(root, "train", bucket, name, name.encode())
        script.append_manifest(root, {
            "id": name, "bucket": bucket, "path": f"train/{bucket}/{name}"})
    manifest_before = (root / script.MANIFEST).read_bytes()
    real_move = script._move_without_overwrite
    calls = 0

    def fail_second_move(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected move failure")
        return real_move(source, destination)

    monkeypatch.setattr(script, "_move_without_overwrite", fail_second_move)
    with pytest.raises(OSError, match="injected move failure"):
        script.freeze_eval(root, fraction=1.0, seed=7)

    assert {path.name for path in (root / "train" / bucket).glob("*.wav")} == set(names)
    assert not list((root / "eval" / bucket).glob("*.wav"))
    assert (root / script.MANIFEST).read_bytes() == manifest_before
    assert not (root / "eval" / ".frozen").exists()


def test_bug_freeze_eval_keeps_marker_if_a_move_cannot_be_rolled_back(
        tmp_path, monkeypatch):
    script = _load_script()
    root = tmp_path / "samples"
    source = _take(root, "train", "bucket", "take.wav", b"same bytes")
    destination = root / "eval" / "bucket" / "take.wav"

    def leave_duplicate_and_fail(src, dest):
        assert src == source
        dest.write_bytes(src.read_bytes())
        raise script._IncompleteMoveError("injected incomplete move")

    monkeypatch.setattr(script, "_move_without_overwrite", leave_duplicate_and_fail)
    with pytest.raises(RuntimeError, match="rollback was incomplete"):
        script.freeze_eval(root, fraction=1.0, seed=7)

    assert source.read_bytes() == b"same bytes"
    assert destination.read_bytes() == b"same bytes"
    assert (root / "eval" / ".frozen").exists()
    with pytest.raises(RuntimeError, match="already frozen"):
        script.freeze_eval(root, fraction=1.0, seed=7)


def test_bug_freeze_eval_rolls_back_when_manifest_write_fails(tmp_path, monkeypatch):
    script = _load_script()
    root = tmp_path / "samples"
    bucket = "bucket"
    source = _take(root, "train", bucket, "take.wav")
    script.append_manifest(root, {
        "id": "take.wav", "bucket": bucket,
        "path": f"train/{bucket}/take.wav"})
    manifest_before = (root / script.MANIFEST).read_bytes()
    real_write = script._atomic_write_text

    def fail_manifest(path, text):
        if path.name == script.MANIFEST:
            raise OSError("injected manifest failure")
        return real_write(path, text)

    monkeypatch.setattr(script, "_atomic_write_text", fail_manifest)
    with pytest.raises(OSError, match="injected manifest failure"):
        script.freeze_eval(root, fraction=1.0, seed=7)

    assert source.read_bytes() == b"wav"
    assert not (root / "eval" / bucket / "take.wav").exists()
    assert (root / script.MANIFEST).read_bytes() == manifest_before
    assert not (root / "eval" / ".frozen").exists()


def test_bug_freeze_eval_leaves_in_progress_marker_after_finalize_failure(
        tmp_path, monkeypatch):
    script = _load_script()
    root = tmp_path / "samples"
    bucket = "bucket"
    source = _take(root, "train", bucket, "take.wav")
    script.append_manifest(root, {
        "id": "take.wav", "bucket": bucket,
        "path": f"train/{bucket}/take.wav"})
    real_write = script._atomic_write_text

    def fail_marker(path, text):
        if path.name == ".frozen":
            raise OSError("injected marker failure")
        return real_write(path, text)

    monkeypatch.setattr(script, "_atomic_write_text", fail_marker)
    with pytest.raises(RuntimeError, match="could not be finalized"):
        script.freeze_eval(root, fraction=1.0, seed=7)

    assert not source.exists()
    assert (root / "eval" / bucket / "take.wav").read_bytes() == b"wav"
    assert script.read_manifest(root)[0]["path"] == f"eval/{bucket}/take.wav"
    marker = root / "eval" / ".frozen"
    assert json.loads(marker.read_text(encoding="utf-8"))["status"] == "in_progress"
    with pytest.raises(RuntimeError, match="already frozen"):
        script.freeze_eval(root, fraction=1.0, seed=7)
    assert (root / "eval" / bucket / "take.wav").read_bytes() == b"wav"
