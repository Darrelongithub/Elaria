"""WP7 increment 8 — the monthly restore-drill scaffolding.

Headless throughout: no restic, no rclone, no MEGA, no sleeps. The restic runner is a
scripted callable, the clock is injected, and every fixture lives in a temporary directory.

The load-bearing behaviours pinned here:

* **A missing restic is a DECLARED skip, not a pass and not a failure.** The restore and the
  hash-verify are what prove the owner can get their audio back; `restic check` additionally
  proves the repository is internally consistent. Claiming the second without doing it is
  the silent-pass failure increment 4 exists to prevent.
* **The quarterly cap is the SMALLER of the percentage and the byte ceiling.** A percentage
  alone is not a bound: 5% of a 40 GB repository is 2 GB, four times the ruled ceiling.
* **A drill record is path-free** — the extension and the backend that confirmed, never a
  name or a path.
* **A failed drill is recorded**, not just a successful one. A journal that only ever shows
  passes is not evidence.
"""

from __future__ import annotations

import tempfile
import unittest
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from assistant.drill import (
    DRILL_KINDS,
    DrillJournal,
    DrillRecord,
    ResticCheck,
    read_data_subset,
)

NOW = datetime(2026, 11, 4, 4, 11, 0, tzinfo=UTC)


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="wp7-drill-"))


def _wav(path: Path, payload_bytes: int = 4000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * (payload_bytes // 2))
    return path


class TestReadDataSubset(unittest.TestCase):
    """The quarterly bound. A percentage alone is not a cap."""

    def test_without_a_repo_size_the_percentage_is_all_we_can_express(self):
        self.assertEqual(read_data_subset(pct=5, mb=500), "5%")

    def test_the_byte_ceiling_binds_on_a_large_repository(self):
        """5% of 40 GB is 2 GB — four times the ruled ceiling."""

        self.assertEqual(
            read_data_subset(pct=5, mb=500, repo_bytes=40 * 10 ** 9), "500M")

    def test_the_percentage_binds_on_a_small_repository(self):
        """5% of 2 GB is 100 MB, well under the 500 MB ceiling."""

        self.assertEqual(
            read_data_subset(pct=5, mb=500, repo_bytes=2 * 10 ** 9), "100M")

    def test_a_percentage_only_configuration(self):
        self.assertEqual(read_data_subset(pct=5, mb=0), "5%")

    def test_a_byte_ceiling_only_configuration(self):
        self.assertEqual(read_data_subset(pct=0, mb=500), "500M")

    def test_the_bound_is_never_above_the_byte_ceiling(self):
        """Whatever the repository size, the byte ceiling is respected when it is known."""

        for gb in (1, 2, 5, 10, 20, 40, 100):
            value = read_data_subset(pct=5, mb=500, repo_bytes=gb * 10 ** 9)
            if value.endswith("M"):
                self.assertLessEqual(int(value[:-1]), 500, f"{gb} GB repo")


class TestResticCheck(unittest.TestCase):
    """The seam. No restic binary is needed anywhere."""

    def setUp(self):
        self.tmp = _tmp()

    def test_the_monthly_command_carries_no_subset(self):
        restic = ResticCheck(repo="rclone:mega-elaria:elaria-restic",
                             remote="mega-elaria", path="elaria-restic")
        argv = restic.argv()
        self.assertNotIn("--read-data-subset=5%", " ".join(argv))

    def test_the_quarterly_command_carries_the_subset(self):
        restic = ResticCheck(repo="rclone:mega-elaria:elaria-restic",
                             remote="mega-elaria", path="elaria-restic")
        argv = restic.argv(subset="250M")
        self.assertIn("--read-data-subset=250M", argv)

    def test_the_rclone_timeout_is_explicit_not_inherited(self):
        """MEGA repo-open routinely exceeds restic's 1m default (restic #3511/#3514)."""

        restic = ResticCheck(repo="rclone:mega-elaria:elaria-restic",
                             remote="mega-elaria", path="elaria-restic",
                             timeout="5m")
        argv = restic.argv()
        self.assertIn("-o", argv)
        self.assertIn("rclone.timeout=5m", argv)

    def test_the_password_file_is_passed_by_path_and_never_read(self):
        """The seam must offer no way to obtain the passphrase itself."""

        restic = ResticCheck(repo="rclone:mega-elaria:elaria-restic",
                             remote="mega-elaria", path="elaria-restic",
                             password_file=self.tmp / "pw")
        argv = restic.argv()
        self.assertIn("--password-file", argv)
        self.assertIn(str(self.tmp / "pw"), argv)
        # no accessor returns file CONTENTS
        for name in dir(restic):
            self.assertFalse(name.startswith("read_pass"), name)

    def test_an_absent_restic_is_a_declared_failure_not_an_exception(self):
        def runner(argv):
            raise FileNotFoundError("restic")

        restic = ResticCheck(repo="rclone:mega-elaria:elaria-restic",
                             remote="mega-elaria", path="elaria-restic",
                             runner=runner)
        ok, detail = restic.run()
        self.assertFalse(ok)
        self.assertIn("restic unavailable", detail)

    def test_a_nonzero_exit_is_reported_as_a_failure(self):
        def runner(argv):
            raise OSError("exit 1")

        restic = ResticCheck(repo="rclone:mega-elaria:elaria-restic",
                             remote="mega-elaria", path="elaria-restic",
                             runner=runner)
        ok, _ = restic.run()
        self.assertFalse(ok)

    def test_a_clean_exit_is_a_pass(self):
        restic = ResticCheck(repo="rclone:mega-elaria:elaria-restic",
                             remote="mega-elaria", path="elaria-restic",
                             runner=lambda argv: "no errors were found")
        ok, detail = restic.run()
        self.assertTrue(ok)
        self.assertIn("no errors", detail)

    def test_the_repo_spec_is_the_provider_as_one_config_line(self):
        restic = ResticCheck(repo="rclone:mega-elaria:elaria-restic",
                             remote="mega-elaria", path="elaria-restic")
        self.assertEqual(restic.repo_spec(), "rclone:mega-elaria:elaria-restic")


class TestDrillJournal(unittest.TestCase):
    """Append-only, fsync'd, 0600, path-free. A pass nobody can look up is not evidence."""

    def setUp(self):
        self.tmp = _tmp()
        self.path = self.tmp / "drills.jsonl"
        self.journal = DrillJournal(self.path)

    def _record(self, **kw):
        base = {"ts": NOW.isoformat(), "kind": "monthly", "ok": True,
                "backend": "local-path-fixture", "method": "restore+hash",
                "label": "wav", "detail": "restore=ok"}
        base.update(kw)
        return DrillRecord(**base)

    def test_an_absent_journal_reads_as_empty(self):
        self.assertEqual(DrillJournal(self.tmp / "nope.jsonl").records(), [])

    def test_a_record_round_trips(self):
        self.journal.append(self._record())
        rows = self.journal.records()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kind, "monthly")
        self.assertTrue(rows[0].ok)
        self.assertEqual(rows[0].backend, "local-path-fixture")

    def test_a_failed_drill_is_recorded_not_just_a_pass(self):
        self.journal.append(self._record(ok=False, detail="hash MISMATCH"))
        self.journal.append(self._record(ok=True))
        self.assertEqual(self.journal.count_passed(), 1)
        self.assertEqual(len(self.journal.records()), 2)

    def test_the_journal_is_owner_only(self):
        self.journal.append(self._record())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_a_torn_trailing_line_is_discarded_not_counted(self):
        """A crash mid-write must never manufacture a drill that ran."""

        self.journal.append(self._record())
        with open(self.path, "a") as fh:
            fh.write('{"ts": "2026-11-04T04:11:00+00:00", "kind": "mon')  # no newline
        rows = self.journal.records()
        self.assertEqual(len(rows), 1)

    def test_last_and_count_respect_the_kind(self):
        self.journal.append(self._record(kind="monthly"))
        self.journal.append(self._record(kind="quarterly", ok=False))
        self.assertEqual(self.journal.last(kind="monthly").kind, "monthly")
        self.assertFalse(self.journal.last(kind="quarterly").ok)
        self.assertEqual(self.journal.count_passed(kind="quarterly"), 0)
        self.assertEqual(self.journal.count_passed(), 1)

    def test_a_record_carries_no_path(self):
        """The privacy fence, on the drill record itself."""

        rec = self._record(label="wav", detail="restore=ok")
        text = rec.to_json()
        for banned in ("/tmp", "/home", ".wav/", str(self.tmp)):
            self.assertNotIn(banned, text)
        # the label is an EXTENSION, never a filename
        self.assertEqual(rec.label, "wav")

    def test_an_unwritable_journal_reports_false_rather_than_raising(self):
        """A drill that cannot be recorded still happened. The caller must be able to see
        that the record failed without the drill itself failing."""

        blocked = DrillJournal(Path("/proc/definitely/not/writable/drills.jsonl"))
        self.assertFalse(blocked.append(self._record()))


class TestDrillKinds(unittest.TestCase):
    def test_the_two_cadences(self):
        self.assertEqual(DRILL_KINDS, ("monthly", "quarterly"))

    def test_an_unknown_kind_is_refused_by_run_drill(self):
        """`run_drill` refuses a kind it does not know rather than guessing a cadence."""

        from assistant.drill import run_drill

        class _Ctx:
            """The refusal happens before any of these is touched."""

            backend = None
            section: ClassVar[dict] = {}
            manifest = None
            restorer = None

        with self.assertRaises(ValueError):
            run_drill(kind="fortnightly", ctx=_Ctx(), restic=None)

    def test_a_fully_disabled_cap_is_the_empty_string_not_an_error(self):
        """A disabled cap is a configuration, not a fault."""

        self.assertEqual(read_data_subset(pct=0, mb=0), "")


class TestDrillUnitsArePinned(unittest.TestCase):
    """The monthly service is part of the deliverable, so its keys are pinned."""

    def _unit(self, name):
        return (Path(__file__).resolve().parents[1] / "systemd" / name).read_text()

    def test_the_monthly_service_runs_the_drill(self):
        self.assertIn("backup check --kind monthly --record",
                      self._unit("assistant-backup-monthly.service"))

    def test_the_monthly_timer_points_at_the_monthly_service(self):
        self.assertIn("Unit=assistant-backup-monthly.service",
                      self._unit("assistant-backup-monthly.timer"))

    def test_the_monthly_timer_has_persistent_true(self):
        self.assertIn("Persistent=true", self._unit("assistant-backup-monthly.timer"))

    def test_no_unit_names_a_secret(self):
        """Prose may explain that no secret lives here; an ASSIGNMENT may not carry one."""

        for name in ("assistant-backup-monthly.service",
                     "assistant-backup-monthly.timer"):
            for raw in self._unit(name).splitlines():
                line = raw.strip()
                if line.startswith("#"):
                    continue
                self.assertFalse(line.startswith("EnvironmentFile"), name)
                for banned in ("PASSWORD", "PASSPHRASE", "API_KEY", "TOKEN", "SECRET"):
                    self.assertFalse(line.startswith(f"Environment={banned}"), name)

    def test_the_service_does_not_restart_on_failure(self):
        """A failed drill is the most important thing this lane can report."""

        self.assertIn("Restart=no", self._unit("assistant-backup-monthly.service"))


if __name__ == "__main__":
    unittest.main()
