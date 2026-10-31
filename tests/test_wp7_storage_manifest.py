"""WP7 increment 1 — the storage manifest.

Every test here runs against synthetic fixtures in a temp dir. No restic, no
rclone, no MEGA, and no real wav: this increment is the state machine and the
durability guarantee, both of which are pure filesystem behaviour and can be
pinned exactly.

The crash-point tests in this file are the ones that matter most — a manifest
that can record a half-state, or let a trim precede a durable flip, is worse
than no manifest at all.
"""

import json
import os
import stat
from pathlib import Path

import pytest

from assistant.storage import (
    FLIPPED,
    LOCAL,
    PURGED,
    TRASHED,
    UPLOADED,
    ManifestRecord,
    StorageManifest,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "assistant" / "config.py"


def _rec(artifact, state, **kw):
    return ManifestRecord(artifact=str(artifact), state=state,
                          ts="2026-10-31T00:00:00+00:00", **kw)


# -- the state machine ------------------------------------------------------

def test_full_lifecycle_records_every_state(tmp_path):
    """local -> uploaded -> flipped -> trashed -> purged, in order."""
    man = StorageManifest(tmp_path / "manifest.jsonl")
    art = tmp_path / "a.wav"
    for state in (LOCAL, UPLOADED, FLIPPED, TRASHED, PURGED):
        assert man.append(_rec(art, state, sha256="ab" * 32, size=1024,
                               tier="hot"), expect_from=None) is True
    assert [r.state for r in man.records()] == [LOCAL, UPLOADED, FLIPPED,
                                                TRASHED, PURGED]
    assert man.state_of(art) == PURGED


def test_current_is_latest_per_artifact(tmp_path):
    """The journal is append-only; exactly one record per artifact is current."""
    man = StorageManifest(tmp_path / "manifest.jsonl")
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    man.append(_rec(a, LOCAL))
    man.append(_rec(b, LOCAL))
    man.append(_rec(a, UPLOADED))
    man.append(_rec(b, FLIPPED))
    man.append(_rec(a, FLIPPED))
    current = man.current()
    assert set(current) == {str(a), str(b)}
    assert current[str(a)].state == FLIPPED
    assert current[str(b)].state == FLIPPED
    # append-only: nothing was rewritten
    assert len(man.records()) == 5


def test_illegal_transitions_refused(tmp_path):
    """The copy-count invariant, enforced by the machine rather than trusted.

    local -> trashed would trash the ONLY copy. uploaded -> trashed would trim
    without ever recording the flip decision. Both are refused.
    """
    man = StorageManifest(tmp_path / "manifest.jsonl")
    art = tmp_path / "a.wav"
    man.append(_rec(art, LOCAL))
    assert man.append(_rec(art, TRASHED), expect_from=LOCAL) is False
    assert man.append(_rec(art, PURGED), expect_from=LOCAL) is False
    assert man.append(_rec(art, FLIPPED), expect_from=LOCAL) is False
    assert man.state_of(art) == LOCAL  # unchanged — nothing was recorded
    assert len(man.records()) == 1


def test_uploaded_must_flip_before_trim(tmp_path):
    """Trim without a durable flip is refused even when the caller is honest."""
    man = StorageManifest(tmp_path / "manifest.jsonl")
    art = tmp_path / "a.wav"
    man.append(_rec(art, LOCAL))
    man.append(_rec(art, UPLOADED), expect_from=LOCAL)
    assert man.append(_rec(art, TRASHED), expect_from=UPLOADED) is False
    assert man.append(_rec(art, FLIPPED), expect_from=UPLOADED) is True
    assert man.append(_rec(art, TRASHED), expect_from=FLIPPED) is True


def test_purged_is_terminal(tmp_path):
    man = StorageManifest(tmp_path / "manifest.jsonl")
    art = tmp_path / "a.wav"
    man.append(_rec(art, PURGED))
    for state in (LOCAL, UPLOADED, FLIPPED, TRASHED, PURGED):
        assert man.append(_rec(art, state), expect_from=PURGED) is False


def test_unknown_state_raises(tmp_path):
    man = StorageManifest(tmp_path / "manifest.jsonl")
    with pytest.raises(ValueError):
        man.append(_rec(tmp_path / "a.wav", "bogus"))


# -- crash consistency ------------------------------------------------------

def test_flip_is_durable_before_trim(tmp_path):
    """The flip's fsync lands before the trim record is even written.

    The ordering the spec demands, expressed as: the trim path calls
    append(FLIPPED) and only proceeds on True. A False here must stop the trim.
    """
    man = StorageManifest(tmp_path / "manifest.jsonl")
    art = tmp_path / "a.wav"
    man.append(_rec(art, LOCAL))
    man.append(_rec(art, UPLOADED), expect_from=LOCAL)
    flipped = man.append(_rec(art, FLIPPED), expect_from=UPLOADED)
    assert flipped is True
    # a second process reading the manifest cold must see the flip already
    cold = StorageManifest(tmp_path / "manifest.jsonl")
    assert cold.state_of(art) == FLIPPED


def test_partial_trailing_line_is_discarded(tmp_path):
    """A crash before fsync leaves a fragment with no newline. It is not a state.

    Parsing it would let the reconciler act on a half-written decision — the
    exact failure the append protocol exists to prevent.
    """
    path = tmp_path / "manifest.jsonl"
    man = StorageManifest(path)
    man.append(_rec(tmp_path / "a.wav", LOCAL))
    good = path.read_text(encoding="utf-8")
    # simulate a crash mid-append: a complete JSON object, no trailing newline
    path.write_text(good + json.dumps({"artifact": "x", "state": "flipped",
                                       "ts": "t"}), encoding="utf-8")
    assert len(StorageManifest(path).records()) == 1
    assert StorageManifest(path).state_of(tmp_path / "a.wav") == LOCAL


def test_malformed_line_is_skipped_not_fatal(tmp_path):
    """The manifest is the audit trail; one bad line must not stop the reader."""
    path = tmp_path / "manifest.jsonl"
    man = StorageManifest(path)
    man.append(_rec(tmp_path / "a.wav", LOCAL))
    with path.open("a", encoding="utf-8") as handle:
        handle.write("this is not json\n")
    man.append(_rec(tmp_path / "b.wav", UPLOADED))
    records = StorageManifest(path).records()
    assert len(records) == 2
    assert records[0].state == LOCAL


def test_absent_manifest_is_a_correct_noop(tmp_path):
    """No manifest yet is the normal first-run state, never an error."""
    man = StorageManifest(tmp_path / "nowhere" / "manifest.jsonl")
    assert man.exists() is False
    assert man.records() == []
    assert man.current() == {}
    assert man.state_of(tmp_path / "a.wav") is None
    assert man.summary()["artifacts"] == 0


# -- privacy fence ----------------------------------------------------------

def test_manifest_file_is_owner_only(tmp_path):
    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    man.append(_rec(tmp_path / "a.wav", LOCAL))
    mode = stat.S_IMODE(os.stat(man.path).st_mode)
    assert mode == 0o600, oct(mode)
    assert stat.S_IMODE(os.stat(man.path.parent).st_mode) == 0o700


def test_summary_carries_no_paths(tmp_path):
    """The only shape allowed to leave the laptop is blind to which is which."""
    man = StorageManifest(tmp_path / "manifest.jsonl")
    for name in ("secret-owner-name.wav", "private.wav", "confidential.wav"):
        man.append(_rec(tmp_path / name, UPLOADED, size=100, tier="cold"))
    summary = man.summary()
    blob = json.dumps(summary)
    for name in ("secret-owner-name", "private", "confidential", "wav"):
        assert name not in blob
    assert summary["artifacts"] == 3
    assert summary["by_state"] == {UPLOADED: 3}
    assert summary["by_tier"] == {"cold": 3}


# -- config registration ----------------------------------------------------

def test_backup_section_is_registered_in_defaults(config):
    """doctor must not warn 'unknown section [backup]' on a real config."""
    backup = config.section("backup")
    assert backup["rclone_remote"] == ""
    assert backup["hot_window_days"] == 14
    assert backup["hot_window_gb"] == 2
    assert backup["trim_grace_days"] == 14
    assert backup["restic_timeout"] == "5m"
    assert backup["capacity_floor_gb"] == 2
    assert backup["watcher_poll_s"] == 30
    assert backup["nightly_oncalendar"] == "03:17"


def test_every_sheet_dependent_value_is_labelled_interim():
    """A Sheet-dependent default must never be mistaken for a tuned one.

    The label lives in a source comment, so this reads config.py and asserts
    the marker sits on the same line as each key. Removing a label is a defect
    this test catches, not a cleanup.
    """
    labelled = {"restic_pack_size_mib", "hot_window_days", "hot_window_gb",
                "trim_grace_days", "capacity_floor_gb"}
    text = SRC.read_text(encoding="utf-8")
    start = text.index('"backup": {')
    block = text[start:text.index("\n    },", start)]
    for key in labelled:
        for line in block.splitlines():
            if f'"{key}"' in line:
                assert "INTERIM-PENDING-SHEETS" in line, (
                    f"[backup] {key} lost its INTERIM-PENDING-SHEETS label")
                break
        else:
            raise AssertionError(f"[backup] {key} not found in DEFAULTS")
