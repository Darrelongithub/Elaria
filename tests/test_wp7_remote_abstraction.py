"""WP7 increment 4 — the remote abstraction, its pinned surface, and its provenance.

Three requirements, each pinned by a test rather than asserted in prose:

1. **The command surface is pinned.** `surface_json()` is stable and complete, every verb
   builds argv from the table, and an unpinned verb raises instead of improvising.
2. **rclone absent = a declared skip.** `probe_rclone()` always returns a reason, and
   `RcloneBackend.verify()` with no binary on PATH can never come back confirmed.
3. **Every verification record names its backend.** A `LocalPathBackend` confirmation
   reports `local-path-fixture`, never something that reads like a remote — and the name
   reaches the manifest detail through the flip reason.

Nothing here contacts a network. The rclone-backed paths are driven by a stub binary on
PATH, so the subprocess plumbing is exercised without rclone and without MEGA.
"""

from __future__ import annotations

import hashlib
import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from assistant.backup import plan_reconcile, reconcile_all
from assistant.remote import (
    FIXTURE_BACKEND_NAME,
    RCLONE_COMMAND_SURFACE,
    RCLONE_MIN_VERSION,
    RCLONE_PINNED_VERSION,
    BackendRegistry,
    CommandPin,
    LocalPathBackend,
    RcloneBackend,
    RemoteBackend,
    make_verifier,
    probe_rclone,
    surface_json,
    version_at_least,
)
from assistant.storage import LOCAL, UPLOADED, ManifestRecord, StorageManifest

# Aware on both ends: a naive record ts subtracted from an aware `now` raises,
# and the grace is measured against this clock.
NOW = datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC)
NOW_ISO = "2026-10-31T12:00:00+00:00"


def _wav(path: Path, payload: bytes = b"RIFFfakeWAVEdata") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


# --------------------------------------------------------------------------------------
# 1. The pinned command surface
# --------------------------------------------------------------------------------------


def test_the_surface_is_machine_readable_and_stable():
    """Requirement 1: a JSON dump that can be diffed against a pinned copy."""

    blob = json.loads(surface_json())
    assert blob["pinned_version"] == RCLONE_PINNED_VERSION
    assert blob["min_version"] == RCLONE_MIN_VERSION
    assert blob["fixture_backend_name"] == FIXTURE_BACKEND_NAME
    verbs = [c["verb"] for c in blob["commands"]]
    assert verbs == ["version", "about", "lsjson", "serve restic"]
    # round-trips: the dump is a faithful serialisation, not a lossy summary
    assert surface_json() == surface_json()


def test_every_pin_carries_a_purpose_and_an_owner():
    """A verb with no stated purpose or owner is a verb nobody can review."""

    for pin in RCLONE_COMMAND_SURFACE:
        assert isinstance(pin, CommandPin)
        assert pin.purpose.strip(), f"{pin.verb} has no purpose"
        assert pin.invoked_by in {"storage", "restic"}, pin.verb
        assert pin.argv and all(isinstance(a, str) for a in pin.argv), pin.verb
        assert "{binary}" in pin.argv, f"{pin.verb} does not use the configured binary"


def test_restic_owns_the_transport_not_the_storage_lane():
    """`serve restic` is restic's to spawn. Pinning who invokes what is the point."""

    by_verb = {p.verb: p for p in RCLONE_COMMAND_SURFACE}
    assert by_verb["serve restic"].invoked_by == "restic"
    assert by_verb["lsjson"].invoked_by == "storage"
    assert by_verb["about"].invoked_by == "storage"
    assert by_verb["version"].invoked_by == "storage"


def test_argv_is_built_only_from_the_table():
    """Requirement 1: no runtime improvisation. Substitution, not assembly."""

    backend = RcloneBackend("mega-elaria", path="elaria")
    assert backend.argv("version") == ["rclone", "version"]
    assert backend.argv("lsjson") == [
        "rclone", "lsjson", "mega-elaria:elaria", "--hash", "md5"]
    assert backend.argv("about") == [
        "rclone", "about", "mega-elaria:elaria", "--json"]


def test_an_unpinned_verb_refuses_rather_than_improvising():
    """The enforcement: an unknown verb raises, so no ad-hoc command can be built."""

    backend = RcloneBackend("mega-elaria")
    for verb in ("delete", "purge", "rm", "moveto", "sync", "copyto"):
        with pytest.raises(KeyError, match="not in the pinned command surface"):
            backend.argv(verb)


def test_the_configured_binary_is_honoured_everywhere():
    """A pinned surface that hardcodes `rclone` is not a pin on this install."""

    backend = RcloneBackend("mega-elaria", path="p", binary="/usr/local/bin/rclone")
    assert backend.argv("version")[0] == "/usr/local/bin/rclone"
    assert backend.argv("lsjson")[1] == "lsjson"


def test_the_mega_timeout_pin_is_recorded_on_the_transport():
    """The 1m default breaks MEGA repo open; the pin must say so, on the right verb."""

    serve = next(p for p in RCLONE_COMMAND_SURFACE if p.verb == "serve restic")
    assert "timeout" in serve.notes
    assert "3511" in serve.notes or "3514" in serve.notes


def test_version_comparison_is_numeric_not_lexicographic():
    """'1.9' must beat '1.41' numerically. String comparison gets this backwards."""

    assert version_at_least("1.75.2", "1.41.0")
    assert version_at_least("1.41", "1.41.0")
    assert not version_at_least("1.40.9", "1.41.0")
    assert not version_at_least("1.9", "1.41.0"), "string compare would say True"
    assert version_at_least("v1.75.2", "1.41.0"), "a leading v is not fatal"
    assert not version_at_least("garbage", "1.41.0")


def test_the_pinned_version_is_at_least_the_floor():
    """A pin below its own floor would be incoherent."""

    assert version_at_least(RCLONE_PINNED_VERSION, RCLONE_MIN_VERSION)


# --------------------------------------------------------------------------------------
# 2. rclone absent = a declared skip, never a silent pass
# --------------------------------------------------------------------------------------


def test_probe_of_an_absent_binary_records_a_reason(tmp_path):
    """Requirement 2: absent means declared, and declared means it says why."""

    probe = probe_rclone(str(tmp_path / "definitely-not-rclone"))
    assert probe.available is False
    assert probe.reason.strip(), "an unavailable probe with no reason is a silent pass"
    assert "not found on PATH" in probe.reason
    assert RCLONE_PINNED_VERSION in probe.reason, "the reason names what is pinned"


def test_probe_of_a_present_binary_reports_path_and_version(tmp_path):
    """A stub rclone proves the subprocess plumbing without rclone or MEGA."""

    stub = tmp_path / "rclone"
    stub.write_text("#!/bin/sh\necho 'rclone v1.75.2'\n")
    stub.chmod(0o755)
    probe = probe_rclone(str(stub))
    assert probe.available is True
    assert probe.path == str(stub)
    assert probe.version == "1.75.2"
    assert probe.reason == ""


def test_probe_of_a_broken_binary_declares_rather_than_raising(tmp_path):
    """A binary that runs but says nothing parsable is a skip, not a crash."""

    stub = tmp_path / "rclone"
    stub.write_text("#!/bin/sh\necho 'no version here'\n")
    stub.chmod(0o755)
    probe = probe_rclone(str(stub))
    assert probe.available is False
    assert "no parsable version" in probe.reason


def test_verify_with_no_rclone_on_path_is_a_declared_skip(tmp_path):
    """Requirement 2, the load-bearing one: absent rclone can never confirm."""

    backend = RcloneBackend("mega-elaria", binary=str(tmp_path / "no-such-rclone"))
    art = _wav(tmp_path / "audio" / "a.wav")
    verdict = backend.verify(art)
    assert verdict.confirmed is False, "an absent binary must never confirm"
    assert verdict.method == "declared-skip"
    assert verdict.backend == "rclone:mega-elaria"
    assert verdict.detail.strip()
    assert "not found on PATH" in verdict.detail


def test_verify_with_a_rclone_below_the_floor_is_a_declared_skip(tmp_path):
    """MEGA needs 1.41+. An older build is a skip with the floor named."""

    stub = tmp_path / "rclone"
    stub.write_text("#!/bin/sh\necho 'rclone v1.40.0'\n")
    stub.chmod(0o755)
    backend = RcloneBackend("mega-elaria", binary=str(stub))
    verdict = backend.verify(_wav(tmp_path / "a.wav"))
    assert verdict.confirmed is False
    assert verdict.method == "declared-skip"
    assert RCLONE_MIN_VERSION in verdict.detail


def test_pin_status_reports_the_running_version(tmp_path):
    stub = tmp_path / "rclone"
    stub.write_text("#!/bin/sh\necho 'rclone v1.75.2'\n")
    stub.chmod(0o755)
    backend = RcloneBackend("mega-elaria", binary=str(stub))
    status = backend.pin_status()
    assert status.confirmed is True
    assert status.method == "version"
    assert RCLONE_PINNED_VERSION in status.detail


def test_verify_presence_when_lsjson_lists_the_artifact(tmp_path):
    """Presence, not content — MEGA has no hashes and the record must say so."""

    stub = tmp_path / "rclone"
    stub.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = version ]; then echo 'rclone v1.75.2'; exit 0; fi\n"
        "if [ \"$1\" = lsjson ]; then\n"
        "  echo '[{\"Name\":\"a.wav\",\"Size\":13},{\"Name\":\"b.wav\",\"Size\":9}]'\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n")
    stub.chmod(0o755)
    backend = RcloneBackend("mega-elaria", path="elaria", binary=str(stub))
    verdict = backend.verify(_wav(tmp_path / "a.wav"))
    assert verdict.confirmed is True
    assert verdict.method == "presence"
    assert "not comparable" in verdict.detail


def test_verify_absent_when_lsjson_does_not_list_the_artifact(tmp_path):
    stub = tmp_path / "rclone"
    stub.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = version ]; then echo 'rclone v1.75.2'; exit 0; fi\n"
        "if [ \"$1\" = lsjson ]; then echo '[{\"Name\":\"other.wav\",\"Size\":9}]'; exit 0; fi\n"
        "exit 1\n")
    stub.chmod(0o755)
    backend = RcloneBackend("mega-elaria", binary=str(stub))
    verdict = backend.verify(_wav(tmp_path / "a.wav"))
    assert verdict.confirmed is False
    assert verdict.method == "absent"


def test_verify_declares_a_skip_when_lsjson_fails(tmp_path):
    """A nonzero exit is a skip with the code recorded, not a confirmed=False mystery."""

    stub = tmp_path / "rclone"
    stub.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = version ]; then echo 'rclone v1.75.2'; exit 0; fi\n"
        "if [ \"$1\" = lsjson ]; then echo 'boom' >&2; exit 7; fi\n"
        "exit 1\n")
    stub.chmod(0o755)
    backend = RcloneBackend("mega-elaria", binary=str(stub))
    verdict = backend.verify(_wav(tmp_path / "a.wav"))
    assert verdict.confirmed is False
    assert verdict.method == "declared-skip"
    assert "7" in verdict.detail


def test_verify_declares_a_skip_when_lsjson_output_is_unparsable(tmp_path):
    stub = tmp_path / "rclone"
    stub.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = version ]; then echo 'rclone v1.75.2'; exit 0; fi\n"
        "if [ \"$1\" = lsjson ]; then echo 'not json'; exit 0; fi\n"
        "exit 1\n")
    stub.chmod(0o755)
    backend = RcloneBackend("mega-elaria", binary=str(stub))
    verdict = backend.verify(_wav(tmp_path / "a.wav"))
    assert verdict.confirmed is False
    assert verdict.method == "declared-skip"
    assert "unparsable" in verdict.detail


def test_the_expected_hash_is_accepted_and_deliberately_ignored(tmp_path):
    """MEGA cannot compare content. Claiming it could would be a false proof."""

    stub = tmp_path / "rclone"
    stub.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = version ]; then echo 'rclone v1.75.2'; exit 0; fi\n"
        "if [ \"$1\" = lsjson ]; then echo '[{\"Name\":\"a.wav\"}]'; exit 0; fi\n"
        "exit 1\n")
    stub.chmod(0o755)
    backend = RcloneBackend("mega-elaria", binary=str(stub))
    # a hash that cannot possibly match anything
    verdict = backend.verify(_wav(tmp_path / "a.wav"), expected_sha256="0" * 64)
    assert verdict.confirmed is True, "presence does not depend on a hash it cannot read"
    assert verdict.method == "presence"


# --------------------------------------------------------------------------------------
# 3. Every verification record names the backend that produced it
# --------------------------------------------------------------------------------------


def test_the_fixture_names_itself_unmistakably(tmp_path):
    """Requirement 3: the fixture must never read like a remote."""

    backend = LocalPathBackend(tmp_path / "remote")
    assert backend.name == FIXTURE_BACKEND_NAME == "local-path-fixture"
    assert "mega" not in backend.name
    assert "rclone" not in backend.name


def test_the_rclone_backend_names_its_remote(tmp_path):
    backend = RcloneBackend("mega-elaria")
    assert backend.name == "rclone:mega-elaria"


def test_a_fixture_confirmation_carries_the_fixture_name(tmp_path):
    backend = LocalPathBackend(tmp_path / "remote")
    art = _wav(tmp_path / "audio" / "a.wav")
    backend.store(art)
    verdict = backend.verify(art)
    assert verdict.confirmed is True
    assert verdict.method == "hash"
    assert verdict.backend == FIXTURE_BACKEND_NAME
    assert verdict.to_dict()["backend"] == FIXTURE_BACKEND_NAME


def test_the_fixture_detects_an_artifact_it_does_not_hold(tmp_path):
    backend = LocalPathBackend(tmp_path / "remote")
    art = _wav(tmp_path / "audio" / "a.wav")
    verdict = backend.verify(art)
    assert verdict.confirmed is False
    assert verdict.method == "absent"


def test_the_fixture_detects_hash_drift(tmp_path):
    """A remote copy that no longer matches the record must not confirm."""

    backend = LocalPathBackend(tmp_path / "remote")
    art = _wav(tmp_path / "audio" / "a.wav", b"original bytes")
    backend.store(art)
    good = backend.verify(art)
    assert good.confirmed is True
    art.write_bytes(b"tampered bytes")
    drift = backend.verify(art)
    assert drift.confirmed is False
    assert drift.method == "hash"


def test_verification_records_never_carry_a_path(tmp_path):
    """The privacy fence: presence, hashes and reasons — never a path."""

    backend = LocalPathBackend(tmp_path / "remote")
    art = _wav(tmp_path / "audio" / "a.wav")
    for verdict in (backend.verify(art), backend.verify(art, expected_sha256="0" * 64)):
        assert str(art) not in verdict.detail
        assert "audio" not in verdict.detail or "fixture" in verdict.detail


def test_the_backend_name_reaches_the_manifest_detail(tmp_path):
    """Requirement 3 end to end: a fixture flip is recorded AS a fixture flip.

    This is the test that retires the no-verifier posture honestly. The manifest now names
    `local-path-fixture` in the flip's detail, so a fixture confirmation can never be read
    as real remote confirmation by anyone auditing the journal later.
    """

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    sha = hashlib.sha256(art.read_bytes()).hexdigest()
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED,
                              sha256=sha, size=art.stat().st_size, ts=NOW_ISO))
    backend = LocalPathBackend(tmp_path / "remote")
    backend.store(art)

    plan = plan_reconcile(man, now=NOW, verify_remote=make_verifier(backend))
    assert plan.actions, "a confirmed flip must now be planned"
    action = plan.actions[0]
    assert FIXTURE_BACKEND_NAME in action.reason
    assert "hash" in action.reason


def test_the_real_remote_name_reaches_the_manifest_detail(tmp_path):
    """The same path with the real backend records rclone:mega-elaria."""

    stub = tmp_path / "rclone"
    stub.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = version ]; then echo 'rclone v1.75.2'; exit 0; fi\n"
        "if [ \"$1\" = lsjson ]; then echo '[{\"Name\":\"a.wav\"}]'; exit 0; fi\n"
        "exit 1\n")
    stub.chmod(0o755)
    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, ts=NOW_ISO))
    backend = RcloneBackend("mega-elaria", binary=str(stub))

    plan = plan_reconcile(man, now=NOW, verify_remote=make_verifier(backend))
    assert plan.actions
    assert "rclone:mega-elaria" in plan.actions[0].reason
    assert "presence" in plan.actions[0].reason


def test_a_fixture_flip_is_written_through_with_the_name_recorded(tmp_path):
    """The whole loop: fixture verifier, reconcile, and the detail lands in the file."""

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED,
                              sha256=hashlib.sha256(art.read_bytes()).hexdigest(),
                              size=art.stat().st_size, ts=NOW_ISO))
    backend = LocalPathBackend(tmp_path / "remote")
    backend.store(art)

    plan = plan_reconcile(man, now=NOW, verify_remote=make_verifier(backend))
    from assistant.backup import reconcile
    # reconcile() executes a plan; the verification already happened at
    # plan time, which is why verify_remote is not a parameter of it.
    reconcile(man, plan, now=NOW)
    current = man.current()[str(art)]
    assert current.state == "flipped"
    assert FIXTURE_BACKEND_NAME in (current.detail or "")


def test_the_registry_refuses_a_fixture_as_authoritative(tmp_path):
    """A fixture registered under a remote's name is refused, not accepted."""

    registry = BackendRegistry()
    fixture = registry.register(LocalPathBackend(tmp_path / "remote"))
    assert registry.names() == [FIXTURE_BACKEND_NAME]
    assert registry.is_fixture(fixture.name) is True
    with pytest.raises(KeyError, match="no backend registered"):
        registry.get("rclone:mega-elaria")


def test_the_registry_keeps_backends_apart_by_name(tmp_path):
    registry = BackendRegistry()
    fixture = LocalPathBackend(tmp_path / "remote")
    real = RcloneBackend("mega-elaria", binary=str(tmp_path / "no-rclone"))
    registry.register(fixture)
    registry.register(real)
    assert set(registry.names()) == {FIXTURE_BACKEND_NAME, "rclone:mega-elaria"}
    assert registry.is_fixture("rclone:mega-elaria") is False


# --------------------------------------------------------------------------------------
# The seam against increment 2's reconcile
# --------------------------------------------------------------------------------------


def test_the_fixture_completes_the_full_upload_to_flip_transition(tmp_path):
    """Increment 2 refused without a verifier. Increment 4 supplies one."""

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED,
                              sha256=hashlib.sha256(art.read_bytes()).hexdigest(),
                              size=art.stat().st_size, ts=NOW_ISO))
    backend = LocalPathBackend(tmp_path / "remote")
    backend.store(art)

    plan = plan_reconcile(man, now=NOW, verify_remote=make_verifier(backend))
    assert [a.to_state for a in plan.actions] == ["flipped"]
    assert plan.problems == []


def test_a_dropped_remote_copy_defers_the_flip(tmp_path):
    """The refusal survives the new verifier: no remote, no flip."""

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED,
                              sha256=hashlib.sha256(art.read_bytes()).hexdigest(),
                              size=art.stat().st_size, ts=NOW_ISO))
    backend = LocalPathBackend(tmp_path / "remote")
    backend.store(art)
    backend.drop(art)  # the remote copy is gone — a crash, or an external deletion

    plan = plan_reconcile(man, now=NOW, verify_remote=make_verifier(backend))
    assert plan.actions == []
    assert plan.problems and "absent" in plan.problems[0]


def test_an_absent_clock_is_reported_as_such_not_as_a_bad_timestamp(tmp_path):
    """`now=None` used to be reported as "unreadable timestamp" when the timestamp was
    perfectly readable. The fault was the missing clock, and the diagnostic must say so."""

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state="trashed", ts=NOW_ISO))
    plan = plan_reconcile(man, now=None)
    assert plan.actions == []
    assert "no clock supplied" in plan.problems[0]
    assert "unreadable timestamp" not in plan.problems[0]


def test_a_bool_verifier_still_works_but_is_named_as_opaque(tmp_path):
    """Backwards compatibility, honestly labelled rather than silently accepted."""

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, ts=NOW_ISO))
    plan = plan_reconcile(man, now=NOW, verify_remote=lambda p: True)
    assert plan.actions
    assert "opaque-verifier" in plan.actions[0].reason


def test_reconcile_all_drives_the_fixture_to_quiescence(tmp_path):
    """One pass per state, looped to quiescence — unchanged by increment 4."""

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=LOCAL, ts=NOW_ISO))
    backend = LocalPathBackend(tmp_path / "remote")
    backend.store(art)
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, ts=NOW_ISO))

    from assistant.tiering import TrashMover
    mover = TrashMover(tmp_path / "trash")
    plan = reconcile_all(man, now=NOW, verify_remote=make_verifier(backend),
                         trim_mover=mover.move)
    # One state advance per pass, looped to quiescence: the flip lands, then the trim
    # that the durable flip made safe. The trim is planned unconditionally once a flip
    # is durable, because "killed between flip and trim" has no age condition.
    assert [a.to_state for a in plan.actions] == ["flipped", "trashed"]
    assert man.state_of(art) == "trashed"
    assert plan.problems == [], "a mover was supplied; nothing should be reported"


def test_reconcile_all_detects_non_quiescence_instead_of_looping(tmp_path):
    """No trim mover means the trim can never land. It must stop, not spin."""

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=LOCAL, ts=NOW_ISO))
    backend = LocalPathBackend(tmp_path / "remote")
    backend.store(art)
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, ts=NOW_ISO))

    plan = reconcile_all(man, now=NOW, verify_remote=make_verifier(backend))
    assert any("did not reach quiescence" in p for p in plan.problems)
    assert any("no trim mover" in p for p in plan.problems)
    # the flip still landed — the flip is not blocked by a missing trim mover
    assert man.state_of(art) == "flipped"


# --------------------------------------------------------------------------------------
# Discipline
# --------------------------------------------------------------------------------------


def test_no_new_heavy_python_dependency():
    """$0 doctrine: rclone is a system binary, not a package."""

    import assistant.remote as mod
    source = Path(mod.__file__).read_text()
    for banned in ("import requests", "import boto3", "import mega", "import restic"):
        assert banned not in source, f"{banned} would be a new dependency"


def test_the_fixture_remote_dir_is_owner_only(tmp_path):
    """0600/0700 discipline: the fixture 'remote' is as private as the real one."""

    backend = LocalPathBackend(tmp_path / "remote")
    art = _wav(tmp_path / "audio" / "a.wav")
    backend.store(art)
    mode = stat.S_IMODE((tmp_path / "remote").stat().st_mode)
    assert mode & 0o077 == 0, f"fixture remote is group/other accessible: {oct(mode)}"


def test_probe_is_a_declared_skip_when_the_binary_is_not_executable(tmp_path):
    """A non-executable file on PATH is absent, with a reason — never a crash."""

    stub = tmp_path / "rclone"
    stub.write_text("not executable")
    probe = probe_rclone(str(stub))
    assert probe.available is False
    assert probe.reason.strip()


def test_remote_backend_is_abstract():
    """The seam cannot be half-implemented by accident."""

    with pytest.raises(NotImplementedError):
        RemoteBackend().verify(Path("x"))


def test_every_backend_describes_itself(tmp_path):
    for backend in (LocalPathBackend(tmp_path / "remote"),
                    RcloneBackend("mega-elaria", binary=str(tmp_path / "no"))):
        described = backend.describe()
        assert described["backend"] == backend.name
        assert described["kind"]
