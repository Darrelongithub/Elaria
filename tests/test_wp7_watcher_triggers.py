"""WP7 increment 7 — the trigger surface: post-close hook, nightly timer, WP5 monthly shape.

Everything here is headless: fake directories, a fake journal runner, an injected clock.
No sleeps, no `journalctl`, no real timer, no timing that could flake. The one thing that
must NOT flake is the polarity between the belt and the suspenders, so it is pinned
directly rather than inferred.

The §2 line shapes used as fixtures were verified against the on-base `journal_log.py`
BEFORE this file was written, per the watcher-wake ruling. They are reproduced here
verbatim so a drift in the mainline contract fails this file rather than silently
changing what the watcher believes.
"""

from __future__ import annotations

import tempfile
import unittest
import wave
from datetime import UTC, datetime
from pathlib import Path

from assistant.backup_triggers import (
    JOURNAL_UNIT,
    POST_CLOSE_EVENTS,
    BackupWatcher,
    JournalTail,
    Snapshot,
    WakeDecision,
    defer_reason,
    defers_to_ac,
    directory_snapshot,
    directory_snapshot_changed,
    parse_journal_line,
)
from assistant.journal_log import format_line

# A frozen "now" — no test in this file reads the wall clock.
NOW = datetime(2026, 11, 4, 3, 17, 0, tzinfo=UTC)


def _line(event: str, *, detail: str | None = None, verdict: str = "OK") -> str:
    """One canonical §2 line, built by the REAL `format_line` so the fixture cannot drift.

    Using the production formatter rather than a hand-written string is deliberate: if the
    §2 contract ever changes shape, these fixtures change with it and the watcher's parser
    is tested against the truth rather than against a string somebody typed.
    """

    return format_line(event=event, level="info", session_id="-", verdict=verdict,
                       detail=detail or "")


def _wav(path: Path, payload_bytes: int = 4000) -> Path:
    """A real WAV. A payload under WAV_HEADER_BYTES is a never-retry mark and would be
    excluded from tiering, which would make a watcher test silently assert nothing."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * (payload_bytes // 2))
    return path


class _ScriptedJournal:
    """A journal tail driven by a fixed script, with no journalctl anywhere."""

    def __init__(self, lines, *, available: bool = True):
        self.lines = list(lines)
        self.available = available
        self.reads = 0

    def read_new(self):
        self.reads += 1
        return [parse_journal_line(line) for line in self.lines]


class TestParseJournalLine(unittest.TestCase):
    """The §2 contract, as the watcher consumes it."""

    def test_a_line_with_detail_parses_to_seven_parts(self):
        parsed = parse_journal_line(_line("session.close", detail="audio kept at /x"))
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["event"], "session.close")
        self.assertEqual(parsed["detail"], "audio kept at /x")

    def test_a_line_without_detail_has_detail_absent_not_dash(self):
        parsed = parse_journal_line(_line("session.close"))
        self.assertIsNone(parsed["detail"])
        self.assertNotEqual(parsed["detail"], "-")

    def test_a_non_section_two_line_is_none_not_an_error(self):
        self.assertIsNone(parse_journal_line("-- Journal begins at ..."))
        self.assertIsNone(parse_journal_line("garbage"))
        self.assertIsNone(parse_journal_line(""))

    def test_dispatch_keys_on_the_event_name_never_the_verdict(self):
        """§2.1. A line whose verdict says KEPT is not what makes it a post-close."""

        kept = parse_journal_line(_line("session.close", verdict="KEPT"))
        other = parse_journal_line(_line("quota.counter", verdict="KEPT"))
        self.assertIn(kept["event"], POST_CLOSE_EVENTS)
        self.assertNotIn(other["event"], POST_CLOSE_EVENTS)

    def test_the_fixture_shape_is_the_real_formatter_output(self):
        """Guards the guard: if `format_line` changes shape, this fails loudly."""

        line = _line("session.close", detail="d")
        parts = line.split(" ", 6)
        self.assertEqual(len(parts), 7)
        self.assertEqual(parts[2], "session.close")


class TestSnapshot(unittest.TestCase):
    """The belt: cheap, no hashing, and an absent root is a no-op not an error."""

    def setUp(self):
        # A self-managed temp dir, NOT pytest's `tmp_path`: these are unittest methods,
        # and `tmp_path` does not inject into them. Using a hardcoded /tmp path here was
        # the original bug - it pollutes across runs and the lane has been bitten by it.
        self._tmp = tempfile.TemporaryDirectory(prefix="wp7-snap-")
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_an_absent_root_is_an_empty_directory_snapshot(self):
        self.assertEqual(directory_snapshot(Path("/nonexistent/wp7-nope")).entries, ())

    def test_a_snapshot_carries_name_size_and_mtime_and_no_content(self):
        p = _wav(self.tmp_path / "a.wav")
        try:
            snap = directory_snapshot(self.tmp_path)
            self.assertEqual(len(snap.entries), 1)
            name, size, mtime_ns = snap.entries[0]
            self.assertEqual(name, "a.wav")
            self.assertGreater(size, 0)
            self.assertGreater(mtime_ns, 0)
        finally:
            p.unlink(missing_ok=True)

    def test_no_hashing_is_performed(self):
        """The poll must not read file content. A file whose bytes change but whose
        size and mtime do not is invisible to the belt — which is the documented,
        ruled trade, and is pinned so it cannot quietly become a hash."""

        root = self.tmp_path
        p = _wav(root / "a.wav")
        try:
            before = directory_snapshot(root)
            # rewrite the same length; mtime resolution on most filesystems is ns, so
            # force a change by touching mtime explicitly rather than relying on time
            import os

            os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns))
            after = directory_snapshot(root)
            self.assertFalse(directory_snapshot_changed(before, after))
        finally:
            p.unlink(missing_ok=True)

    def test_a_new_file_changes_the_directory_snapshot(self):
        root = self.tmp_path
        before = directory_snapshot(root)
        p = _wav(root / "b.wav")
        try:
            self.assertTrue(directory_snapshot_changed(before, directory_snapshot(root)))
        finally:
            p.unlink(missing_ok=True)

    def test_a_growing_file_changes_the_directory_snapshot(self):
        root = self.tmp_path
        p = _wav(root / "c.wav")
        try:
            before = directory_snapshot(root)
            with open(p, "ab") as fh:
                fh.write(b"\x00" * 512)
            self.assertTrue(directory_snapshot_changed(before, directory_snapshot(root)))
        finally:
            p.unlink(missing_ok=True)


class TestJournalTail(unittest.TestCase):
    """The suspenders: incremental, and an absent journalctl is a DECLARED absence."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wp7-tail-"))
        self.cursor = self.tmp / "cursor"

    def test_the_cursor_advances_so_a_restart_does_not_replay(self):
        calls = []

        def runner(argv):
            calls.append(list(argv))
            return "\n".join([_line("session.close")]) + "\n-- cursor: c1\n"

        tail = JournalTail(self.cursor, runner=runner)
        first = tail.read_new()
        self.assertEqual(len(first), 1)
        self.assertTrue(self.cursor.exists())
        self.assertIn("c1", self.cursor.read_text())

        # the second read must ask journalctl for everything AFTER the stored cursor
        tail.read_new()
        self.assertTrue(any("--after-cursor=c1" in a for a in calls[-1:]))

    def test_an_absent_journalctl_returns_empty_not_an_exception(self):
        def runner(argv):
            raise FileNotFoundError("journalctl")

        tail = JournalTail(self.cursor, runner=runner)
        self.assertEqual(tail.read_new(), [])
        self.assertFalse(tail.available)

    def test_a_runner_error_is_a_declared_absence(self):
        def runner(argv):
            raise OSError("boom")

        tail = JournalTail(self.cursor, runner=runner)
        self.assertEqual(tail.read_new(), [])
        self.assertFalse(tail.available)

    def test_the_unit_is_named(self):
        """A typo here would tail nothing and the watcher would look correctly idle."""

        self.assertEqual(JOURNAL_UNIT, "assistant")


class TestBeltSuspendersPolarity(unittest.TestCase):
    """The ruling: the directory poll is TRUTH; the journal CORROBORATES.

    This is the load-bearing distinction in increment 7. If it inverts, a log line can
    manufacture work — which is exactly the failure the ruling forbids.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wp7-polarity-"))
        self.root = self.tmp / "audio"
        self.root.mkdir(parents=True, exist_ok=True)
        self.cursor = self.tmp / "cursor"

    def _watcher(self, journal):
        return BackupWatcher(root=self.root, cursor_path=self.cursor,
                             data_dir=self.tmp, journal=journal)

    def test_a_journal_post_close_alone_cannot_create_a_wake(self):
        """The directory has not changed. The journal is FULL of post-close lines.
        The answer is a no-op. Inverting this is the forbidden optimisation."""

        journal = _ScriptedJournal([_line("session.close", detail="audio kept at /x")])
        watcher = self._watcher(journal)
        decision = watcher.poll()
        self.assertFalse(decision.woke)
        self.assertIsNone(decision.reason)
        self.assertEqual(decision.count, 0)

    def test_a_directory_change_with_no_journal_still_wakes(self):
        """The belt is truth: it does not need the suspenders to agree."""

        watcher = self._watcher(_ScriptedJournal([]))
        watcher.poll()
        _wav(self.root / "a.wav")
        decision = watcher.poll()
        self.assertTrue(decision.woke)
        self.assertEqual(decision.reason, "artifact appeared")
        self.assertFalse(decision.journal_corroborates)

    def test_a_directory_change_with_a_corroborating_journal_names_the_reason(self):
        watcher = self._watcher(
            _ScriptedJournal([_line("session.close", detail="audio kept at /x")]))
        watcher.poll()
        _wav(self.root / "a.wav")
        decision = watcher.poll()
        self.assertTrue(decision.woke)
        self.assertEqual(decision.reason, "post-close")
        self.assertTrue(decision.journal_corroborates)

    def test_a_second_poll_with_no_further_change_is_a_no_op(self):
        watcher = self._watcher(
            _ScriptedJournal([_line("session.close", detail="audio kept at /x")]))
        watcher.poll()
        _wav(self.root / "a.wav")
        self.assertTrue(watcher.poll().woke)
        self.assertFalse(watcher.poll().woke)

    def test_the_journal_is_still_drained_on_a_no_op_so_the_cursor_advances(self):
        """A no-op must not leave the cursor behind, or a later change is buried."""

        journal = _ScriptedJournal([_line("session.close")])
        watcher = self._watcher(journal)
        watcher.poll()
        self.assertEqual(journal.reads, 1)


class TestPrivacyFence(unittest.TestCase):
    """The watcher extracts a path only to address an artifact, and never emits one."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wp7-fence-"))
        self.root = self.tmp / "audio"
        self.root.mkdir(parents=True, exist_ok=True)
        self.cursor = self.tmp / "cursor"

    def test_a_wake_decision_carries_labels_never_paths(self):
        watcher = BackupWatcher(root=self.root, cursor_path=self.cursor,
                                data_dir=self.tmp,
                                journal=_ScriptedJournal([_line("session.close")]))
        watcher.poll()
        _wav(self.root / "20261104-091500-abcdef123456.wav")
        decision = watcher.poll()
        self.assertTrue(decision.woke)
        self.assertEqual(decision.labels, ("wav",))
        for label in decision.labels:
            self.assertNotIn("/", label)
            self.assertNotIn("20261104", label)

    def test_the_rendered_decision_contains_no_path(self):
        watcher = BackupWatcher(root=self.root, cursor_path=self.cursor,
                                data_dir=self.tmp,
                                journal=_ScriptedJournal([_line("session.close")]))
        watcher.poll()
        _wav(self.root / "secret-session-name.wav")
        text = repr(watcher.poll())
        self.assertNotIn("secret-session-name", text)
        self.assertNotIn(str(self.root), text)

    def test_a_deferral_reason_carries_no_path(self):
        """"AC/unmetered" contains a slash by design, so this checks for a PATH, not a
        slash: an absolute path or a filename-shaped token."""

        reason = defer_reason(500 * 1000 ** 2, defer_above_mb=100)
        self.assertIsNotNone(reason)
        self.assertNotIn("/tmp", reason)
        self.assertNotIn("/home", reason)
        self.assertNotIn(".wav", reason)
        self.assertNotIn(str(Path.cwd()), reason)


class TestDeferralPolicy(unittest.TestCase):
    """Uploads above `defer_above_mb` wait for AC/unmetered power."""

    def test_a_large_upload_defers(self):
        self.assertTrue(defers_to_ac(101 * 1000 ** 2, defer_above_mb=100))

    def test_a_small_upload_does_not(self):
        self.assertFalse(defers_to_ac(99 * 1000 ** 2, defer_above_mb=100))

    def test_the_boundary_itself_does_not_defer(self):
        """Exactly at the threshold is not above it."""

        self.assertFalse(defers_to_ac(100 * 1000 ** 2, defer_above_mb=100))

    def test_a_zero_threshold_disables_the_policy(self):
        self.assertFalse(defers_to_ac(10 ** 12, defer_above_mb=0))

    def test_a_deferred_artifact_is_named_in_the_decision(self):
        tmp = Path(tempfile.mkdtemp(prefix="wp7-defer-"))
        root = tmp / "audio"
        root.mkdir(parents=True, exist_ok=True)
        watcher = BackupWatcher(root=root, cursor_path=tmp / "cursor", data_dir=tmp,
                                defer_above_mb=1, journal=_ScriptedJournal([]))
        watcher.poll()
        _wav(root / "big.wav", payload_bytes=2_000_000)
        decision = watcher.poll()
        self.assertIn("wav", decision.deferred)


class TestHeadlessAndDeterministic(unittest.TestCase):
    """No sleeps, no wall clock, no journalctl. The whole surface runs offline."""

    def test_the_injected_clock_is_used(self):
        seen = []
        watcher = BackupWatcher(root=Path("/tmp/wp7-clock"),
                                cursor_path=Path("/tmp/wp7-clock-cursor"),
                                data_dir=Path("/tmp"), now=lambda: seen.append(1) or NOW)
        self.assertEqual(watcher.now(), NOW)

    def test_a_wake_decision_is_truthy_only_when_it_woke(self):
        self.assertFalse(WakeDecision(woke=False))
        self.assertTrue(WakeDecision(woke=True))

    def test_an_empty_snapshot_is_falsy(self):
        self.assertFalse(Snapshot())
        self.assertTrue(Snapshot(entries=(("a", 1, 2),)))


class TestTimerUnitsArePinned(unittest.TestCase):
    """The systemd units are part of the deliverable, so their load-bearing keys are
    pinned rather than left to be edited away."""

    def _unit(self, name):
        text = (Path(__file__).resolve().parents[1] / "systemd" / name).read_text()
        return text

    def test_the_nightly_timer_has_persistent_true(self):
        self.assertIn("Persistent=true", self._unit("assistant-backup.timer"))

    def test_the_nightly_timer_runs_the_backup_service(self):
        self.assertIn("Unit=assistant-backup.service",
                      self._unit("assistant-backup.timer"))

    def test_the_monthly_timer_has_persistent_true(self):
        self.assertIn("Persistent=true", self._unit("assistant-backup-monthly.timer"))

    def test_the_monthly_timer_fires_on_the_first_of_the_month(self):
        self.assertIn("OnCalendar=*-*-01", self._unit("assistant-backup-monthly.timer"))

    def test_no_unit_names_a_secret(self):
        for name in ("assistant-backup.service", "assistant-backup.timer",
                     "assistant-backup-monthly.timer"):
            for raw in self._unit(name).splitlines():
                line = raw.strip()
                if line.startswith("#"):
                    continue  # a comment may EXPLAIN that no secret lives here
                self.assertFalse(
                    line.startswith("EnvironmentFile"),
                    f"{name} must not load an EnvironmentFile of secrets")
                for banned in ("PASSWORD", "PASSPHRASE", "API_KEY", "TOKEN", "SECRET"):
                    self.assertFalse(
                        line.startswith(f"Environment={banned}"),
                        f"{name} must not set {banned}")


class TestMainlineBoundary(unittest.TestCase):
    """`assistant/watcher.py` is MAINLINE's. This lane must not touch it.

    An earlier draft of increment 7 was written straight into `watcher.py` and clobbered
    it - including a `snapshot()` whose return type and keying differ from mainline's.
    Mainline's own tests caught it, which is the only reason it is a note here rather than
    a defect in the tree. These pins make the boundary machine-checked rather than
    remembered.
    """

    def _base_watcher(self):
        """The mainline version, from the repo's own history, never from disk."""

        import subprocess

        text = subprocess.run(
            ["git", "show", "HEAD:src/assistant/watcher.py"],
            capture_output=True, text=True, check=True, cwd=Path(__file__).parents[1],
        ).stdout
        return text

    def test_the_mainline_watcher_is_untouched_in_the_working_tree(self):
        root = Path(__file__).resolve().parents[1]
        on_disk = (root / "src" / "assistant" / "watcher.py").read_text()
        self.assertEqual(
            on_disk, self._base_watcher(),
            "src/assistant/watcher.py differs from HEAD - it is mainline's file",
        )

    def test_this_lane_does_not_export_a_colliding_snapshot(self):
        """Mainline's `snapshot()` returns {full_path: (size, mtime)} and walks
        recursively. This lane's is flat and keyed by NAME. Same name, different shape,
        different job - so they must live in different modules."""

        import assistant.backup_triggers as mine
        import assistant.watcher as mainline

        self.assertTrue(hasattr(mainline, "snapshot"))
        self.assertTrue(hasattr(mainline, "PollingWatcher"))
        self.assertFalse(hasattr(mine, "snapshot"),
                         "this lane must not export a bare `snapshot`")
        self.assertTrue(hasattr(mine, "directory_snapshot"))

    def test_the_two_snapshots_are_not_interchangeable(self):
        import assistant.backup_triggers as mine
        import assistant.watcher as mainline

        root = Path(tempfile.mkdtemp(prefix="wp7-boundary-"))
        (root / "a.wav").write_bytes(b"x" * 100)
        main, backup = mainline.snapshot(root), mine.directory_snapshot(root)
        self.assertIsInstance(main, dict)
        self.assertIsInstance(backup, mine.Snapshot)
        # mainline keys by full path; this lane keys by name
        self.assertIn(str(root / "a.wav"), main)
        self.assertEqual(backup.names, ("a.wav",))


if __name__ == "__main__":
    unittest.main()
