"""WP7 increment 3 — the tiering engine and the real trim mover.

Synthetic fixtures only: temp directories, synthetic bytes, an injected clock. No restic,
no rclone, no MEGA, and no real wav. The permanent exclusions are tested against real
directory shapes because getting them wrong would tier something that must never move.
"""

import os
import stat
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from assistant.tiering import (
    DEFAULT_WINDOW_DAYS,
    DEFAULT_WINDOW_GB,
    PERMANENT_EXCLUSIONS,
    WAV_HEADER_BYTES,
    Candidate,
    TrashMover,
    classify,
    is_excluded,
    scan,
)

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)


def _wav(path: Path, seconds: float = 1.0) -> Path:
    """A real, valid, tiny WAV — synthetic audio, never the owner's."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * seconds))
    return path


def _header_only(path: Path) -> Path:
    """A 44-byte WAV with zero audio frames — the never-retry mark shape."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"")
    return path


def _aged(path: Path, days: int) -> Path:
    stamp = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


# -- the HOT window ---------------------------------------------------------

def test_nothing_moves_inside_the_window(tmp_path):
    """A fresh, small HOT set is left alone. `binding` says none."""
    root = tmp_path / "audio"
    a, b = _wav(root / "a.wav"), _wav(root / "b.wav")
    decision = classify([Candidate.from_path(a, data_dir=tmp_path),
                         Candidate.from_path(b, data_dir=tmp_path)], now=NOW)
    assert decision.binding == "none"
    assert decision.send_cold == []
    assert len(decision.keep_hot) == 2


def test_age_window_binds(tmp_path):
    """Past 14 days the artifact goes cold, and `binding` reports age."""
    root = tmp_path / "audio"
    old = _aged(_wav(root / "old.wav"), days=20)
    fresh = _wav(root / "fresh.wav")
    decision = classify([Candidate.from_path(old, data_dir=tmp_path),
                         Candidate.from_path(fresh, data_dir=tmp_path)], now=NOW)
    assert decision.binding == "age"
    assert [c.path for c in decision.send_cold] == [old]
    assert [c.path for c in decision.keep_hot] == [fresh]


def test_size_cap_binds_and_oldest_go_first(tmp_path):
    """Over the 2 GB cap the oldest artifacts go cold until back under.

    Synthetic sizes via mtimes are impractical at GB scale, so the cap is passed small —
    the ordering property (oldest first) is what this pins.
    """
    root = tmp_path / "audio"
    # Candidates are built directly with GB-scale sizes: the engine's job is the decision,
    # not the filesystem, and a 2 GB fixture is not something a test should create.
    paths = [root / f"f{i}.wav" for i in range(4)]
    sizes = [900, 700, 500, 300]                       # MB, paths[0] is oldest
    cands = [Candidate(path=p, size=s * 1000 ** 2,
                       mtime=NOW - timedelta(days=len(paths) - i))
             for i, (p, s) in enumerate(zip(paths, sizes))]
    decision = classify(cands, now=NOW, window_days=365, window_gb=1)
    assert decision.binding == "size"
    assert [c.path for c in decision.send_cold] == paths[:2], "oldest go first"
    assert sum(c.size for c in decision.keep_hot) <= 1 * 1000 ** 3


def test_binding_reports_the_backstop_is_not_live(tmp_path):
    """The census finding, as a test: at measured growth AGE binds, not size."""
    root = tmp_path / "audio"
    # ~13 MiB/day of hot audio for 14 days, one artifact per day
    cands = []
    for day in range(14):
        p = _aged(_wav(root / f"d{day}.wav", seconds=1.0), days=14 - day)
        cands.append(Candidate.from_path(p, data_dir=tmp_path))
    decision = classify(cands, now=NOW, window_days=DEFAULT_WINDOW_DAYS,
                        window_gb=DEFAULT_WINDOW_GB)
    assert decision.binding == "age", (
        "at census growth the 2 GB cap must not be the live constraint")
    assert decision.hot_bytes < DEFAULT_WINDOW_GB * 1000 ** 3


# -- permanent exclusions ---------------------------------------------------

def test_voice_cache_is_never_tiered(tmp_path):
    """0 ms recall contract. This must hold forever, so it is pinned by a test."""
    data = tmp_path / "share" / "assistant"
    cache = _wav(data / "voice-cache" / "speech-abc.wav")
    reason = is_excluded(cache, data_dir=data)
    assert reason is not None and "voice-cache" in reason


def test_test_assets_are_never_tiered(tmp_path):
    """Offline-voice contract, including the relocated event-spike.wav."""
    data = tmp_path / "share" / "assistant"
    spike = _wav(data / "test-assets" / "event-spike.wav", seconds=2)
    reason = is_excluded(spike, data_dir=data)
    assert reason is not None and "test-assets" in reason


def test_exclusions_hold_at_any_depth(tmp_path):
    data = tmp_path / "share" / "assistant"
    nested = _wav(data / "voice-cache" / "deep" / "deeper" / "x.wav")
    assert is_excluded(nested, data_dir=data) is not None


def test_config_can_add_but_never_remove_exclusions(tmp_path):
    """A config key adds; it cannot subtract the census-ruled ones."""
    data = tmp_path / "share" / "assistant"
    cache = data / "voice-cache" / "x.wav"
    assert is_excluded(cache, data_dir=data, extra=()) is not None
    # even an explicit empty extra list must not unlock it
    assert is_excluded(cache, data_dir=data, extra=("",)) is not None


def test_config_exclusion_is_honoured(tmp_path):
    data = tmp_path / "share" / "assistant"
    scratch = _wav(data / "scratch" / "x.wav")
    assert is_excluded(scratch, data_dir=data) is None
    reason = is_excluded(scratch, data_dir=data, extra=("scratch",))
    assert reason is not None and "config exclusion" in reason


def test_permanent_exclusions_are_the_census_two():
    names = {name for name, _ in PERMANENT_EXCLUSIONS}
    assert names == {"voice-cache", "test-assets"}


def test_header_only_wav_is_a_never_retry_mark(tmp_path):
    """44 bytes, zero audio frames: a mark, not a recording. Counts zero forever."""
    mark = _header_only(tmp_path / "20261025-181730-4d90bf.wav")
    assert mark.stat().st_size == 44
    reason = is_excluded(mark, data_dir=tmp_path)
    assert reason is not None and "never-retry mark" in reason


def test_a_real_wav_is_not_a_mark(tmp_path):
    real = _wav(tmp_path / "real.wav", seconds=0.5)
    assert is_excluded(real, data_dir=tmp_path) is None


def test_a_chunked_wav_with_zero_frames_is_still_a_mark(tmp_path):
    """A never-retry mark carrying a LIST/INFO chunk is LONGER than 44 bytes.

    The canonical PCM header is 44 bytes, so a total-size comparison reads a chunked
    mark as a recording — and it would then be tiered, trimmed and purged as if it were
    audio. The `data` chunk's declared size is what actually says whether there are
    frames, so that is what the classifier reads. Pinned so this cannot drift back.
    """
    body = _header_only(tmp_path / "chunked.wav").read_bytes()
    payload = b"INFO" + b"INAM" + (2).to_bytes(4, "little") + b"x\x00"
    chunked = body[:12] + b"LIST" + len(payload).to_bytes(4, "little") + payload + body[12:]
    assert len(chunked) > WAV_HEADER_BYTES, "the whole point: longer than 44 bytes"

    mark = tmp_path / "20261025-181730-4d90bf.wav"
    mark.write_bytes(chunked)
    reason = is_excluded(mark, data_dir=tmp_path)
    assert reason is not None and "never-retry mark" in reason


def test_a_chunked_wav_with_frames_is_not_a_mark(tmp_path):
    """The same walk must not over-correct: a chunked recording is still a recording."""
    body = _wav(tmp_path / "rec.wav", seconds=0.5).read_bytes()
    payload = b"INFO" + b"INAM" + (2).to_bytes(4, "little") + b"x\x00"
    chunked = body[:12] + b"LIST" + len(payload).to_bytes(4, "little") + payload + body[12:]
    real = tmp_path / "real_chunked.wav"
    real.write_bytes(chunked)
    assert is_excluded(real, data_dir=tmp_path) is None


def test_a_non_wav_file_is_not_a_mark(tmp_path):
    """A classifier, not a validator: unreadable input falls through to size and mtime."""
    other = tmp_path / "notaudio.bin"
    other.write_bytes(b"PK\x03\x04not a riff file")
    assert is_excluded(other, data_dir=tmp_path) is None


def test_scan_excludes_and_classifies_together(tmp_path):
    """The belt: a directory walk that partitions hot / cold / excluded in one pass."""
    data = tmp_path / "share" / "assistant"
    root = data / "audio"
    keep = _wav(root / "keep.wav")
    cold = _aged(_wav(root / "cold.wav"), days=30)
    cache = _wav(data / "voice-cache" / "speech-x.wav")
    mark = _header_only(root / "mark.wav")

    decision = scan(root, now=NOW, data_dir=data)
    assert [c.path for c in decision.send_cold] == [cold]
    assert keep in [c.path for c in decision.keep_hot]
    # the cache file is outside the scanned root, so it is simply not a candidate —
    # which is the same outcome by a different route
    assert cache not in [c.path for c in decision.send_cold]
    assert mark in [c.path for c in decision.excluded]


def test_scan_of_absent_root_is_a_correct_noop(tmp_path):
    decision = scan(tmp_path / "nowhere", now=NOW, data_dir=tmp_path)
    assert decision.summary() == {"keep_hot": 0, "send_cold": 0, "excluded": 0,
                                  "binding": "none", "hot_bytes": 0, "hot_count": 0}


def test_scan_survives_an_unreadable_entry(tmp_path):
    """A poll that crashes on one odd file stops protecting anything."""
    root = tmp_path / "audio"
    good = _wav(root / "good.wav")
    (root / "broken.wav").write_bytes(b"not audio at all")
    decision = scan(root, now=NOW, data_dir=tmp_path)
    assert good in [c.path for c in decision.keep_hot]


# -- the trim mover ---------------------------------------------------------

def test_move_puts_the_artifact_in_trash(tmp_path):
    art = _wav(tmp_path / "audio" / "a.wav")
    mover = TrashMover(tmp_path / "trash")
    dest = mover.move(art)
    assert dest.exists() and dest.parent == mover.trash_dir
    assert not art.exists(), "the HOT copy must be gone — that is what trim means"


def test_move_never_overwrites(tmp_path):
    """Two same-name artifacts land as two files, never one clobbering the other."""
    mover = TrashMover(tmp_path / "trash")
    first = _wav(tmp_path / "one" / "a.wav")
    second = _wav(tmp_path / "two" / "a.wav")
    d1, d2 = mover.move(first), mover.move(second)
    assert d1 != d2
    assert d1.exists() and d2.exists()


def test_trash_dir_is_owner_only(tmp_path):
    art = _wav(tmp_path / "audio" / "a.wav")
    mover = TrashMover(tmp_path / "trash")
    mover.move(art)
    assert stat.S_IMODE(os.stat(mover.trash_dir).st_mode) == 0o700


def test_purge_removes_the_file(tmp_path):
    trash = tmp_path / "trash"
    trash.mkdir()
    gone = trash / "a.wav"
    gone.write_bytes(b"x")
    assert TrashMover(trash).purge(gone) is True
    assert not gone.exists()


def test_purge_of_absent_file_is_false_not_an_error(tmp_path):
    assert TrashMover(tmp_path / "trash").purge(tmp_path / "nope.wav") is False


def test_purge_reraises_rather_than_swallowing(tmp_path):
    """A purge that cannot complete must not look like success."""
    trash = tmp_path / "trash"
    trash.mkdir()
    target = trash / "a.wav"
    target.write_bytes(b"x")
    os.chmod(trash, 0o500)          # read-only dir: unlink must fail
    try:
        with pytest.raises(OSError):
            TrashMover(trash).purge(target)
    finally:
        os.chmod(trash, 0o700)


# -- privacy fence ----------------------------------------------------------

def test_decision_summary_carries_no_paths(tmp_path):
    root = tmp_path / "audio"
    for name in ("secret-owner.wav", "private.wav"):
        _wav(root / name)
    decision = scan(root, now=NOW, data_dir=tmp_path)
    blob = str(decision.summary())
    for name in ("secret-owner", "private", "wav"):
        assert name not in blob


# -- the mover is what increment 2's seam expects ---------------------------

def test_mover_fits_the_reconcile_seam(tmp_path):
    """Increment 3's mover must be drop-in for increment 2's trim_mover."""
    from assistant.backup import plan_reconcile, reconcile
    from assistant.storage import FLIPPED, ManifestRecord, StorageManifest

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=FLIPPED,
                              sha256="ab" * 32))
    mover = TrashMover(tmp_path / "trash")
    reconcile(man, plan_reconcile(man, now=NOW), trim_mover=mover.move)
    assert man.state_of(art) == "trashed"
    assert list(mover.trash_dir.iterdir()), "the artifact really moved"


def test_full_trim_lifecycle(tmp_path):
    """HOT -> trash -> grace -> purge, end to end with the real mover."""
    from assistant.backup import reconcile_all
    from assistant.storage import FLIPPED, LOCAL, PURGED, ManifestRecord, StorageManifest

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=LOCAL, ts=NOW.isoformat()))
    mover = TrashMover(tmp_path / "trash")

    # crash between flip and trim: the flip is durable, the trim never ran
    man.append(ManifestRecord(artifact=str(art), state=FLIPPED, ts=NOW.isoformat()))
    reconcile_all(man, now=NOW, trim_mover=mover.move)
    assert man.state_of(art) == "trashed"
    assert not art.exists(), "the hot copy is in trash"
    assert len(list(mover.trash_dir.iterdir())) == 1

    # grace still running: nothing happens, two copies remain
    reconcile_all(man, now=NOW + timedelta(days=5), purge_mover=mover.purge)
    assert man.state_of(art) == "trashed"
    assert len(list(mover.trash_dir.iterdir())) == 1

    # grace elapsed: the file goes, then the state is recorded
    reconcile_all(man, now=NOW + timedelta(days=15), purge_mover=mover.purge)
    assert man.state_of(art) == PURGED
    assert not list(mover.trash_dir.iterdir()), "trash is empty after the grace"
