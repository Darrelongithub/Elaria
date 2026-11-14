"""Tests for the F24 pre-flights: headroom that PREVENTS, rather than an interruption.

Spec v6 made these non-optional. The behaviour worth pinning is not "the gate exists"
but the three things that make it trustworthy:

* an unreadable `remote_free` is a REFUSAL, never a pass — a gate that waves through a
  reading it never got is the silent-pass failure increment 4 exists to prevent;
* the gate runs BEFORE the upload, so the capacity-floor knock prevents rather than
  interrupts — a knock that fires halfway through has already cost the owner the upload;
* the local gate names the required headroom in the record, so a refusal can be checked
  rather than re-measured.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from assistant import preflight
from assistant.backup_cli import backup_command
from assistant.storage import UPLOADED

# The existing fixture helpers, reused rather than re-invented: a manifest holding one
# aged artifact, so a run actually reaches the point where it would start.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from test_wp7_backup_cli_sensors import _age, _fixture_ctx

GB = 1000 ** 3
SCRATCH = preflight.bench_scratch_bytes()


class ScratchDerivationTests(unittest.TestCase):
    """The required bytes must be derived from the benchmark's own parameters, not
    asserted, so a reader can check the number against the script."""

    def test_scratch_is_payload_plus_restic_temp_space(self):
        payload = preflight.BENCH_TREE_MIB * preflight.MIB * preflight.BENCH_REPOS
        temp = preflight.RESTIC_PACK_MIB * (preflight.RESTIC_BACKEND_CONNECTIONS + 1) * preflight.MIB
        self.assertEqual(SCRATCH, payload + temp)

    def test_scratch_is_over_a_gigabyte(self):
        """~1 GB of synthetic upload plus temp space. If this ever drops below the
        payload the derivation has silently lost a term."""
        self.assertGreater(SCRATCH, preflight.BENCH_TREE_MIB * preflight.MIB * preflight.BENCH_REPOS)

    def test_temp_space_scales_with_pack_size(self):
        bigger = preflight.bench_scratch_bytes(pack_mib=256)
        delta = (256 - 128) * (preflight.RESTIC_BACKEND_CONNECTIONS + 1) * preflight.MIB
        self.assertEqual(bigger - SCRATCH, delta)


class RemoteHeadroomTests(unittest.TestCase):
    def test_an_unreadable_remote_free_is_a_refusal_not_a_pass(self):
        d = preflight.remote_headroom(None, scratch_bytes=SCRATCH, margin_bytes=GB)
        self.assertFalse(d.ok)
        self.assertEqual(d.reason, "remote_free unreadable")

    def test_below_scratch_plus_margin_refuses(self):
        d = preflight.remote_headroom(SCRATCH + GB - 1, scratch_bytes=SCRATCH, margin_bytes=GB)
        self.assertFalse(d.ok)
        self.assertEqual(d.reason, "below scratch-plus-margin headroom")

    def test_exactly_at_the_requirement_proceeds(self):
        d = preflight.remote_headroom(SCRATCH + GB, scratch_bytes=SCRATCH, margin_bytes=GB)
        self.assertTrue(d.ok)

    def test_the_decision_names_every_number(self):
        d = preflight.remote_headroom(5, scratch_bytes=SCRATCH, margin_bytes=GB)
        detail = d.detail()
        for expected in ("REFUSED", "free=5", f"required={SCRATCH + GB}",
                         f"scratch={SCRATCH}", f"margin={GB}"):
            self.assertIn(expected, detail)

    def test_the_capacity_floor_alone_is_not_a_refusal(self):
        """The floor is 10 GB consumed; the scratch gate is about the benchmark's own
        footprint. A 20 GB tier sitting exactly at the floor still has room to run,
        and refusing it would be the gate over-reaching."""
        d = preflight.remote_headroom(10 * GB, scratch_bytes=SCRATCH, margin_bytes=GB)
        self.assertTrue(d.ok)


class LocalHeadroomTests(unittest.TestCase):
    def test_restore_headroom_is_size_plus_margin(self):
        self.assertEqual(preflight.restore_headroom_bytes(100, margin_bytes=50), 150)

    def test_a_negative_size_is_refused_not_clamped(self):
        with self.assertRaises(ValueError):
            preflight.restore_headroom_bytes(-1, margin_bytes=0)

    def test_an_unreadable_filesystem_is_a_refusal(self):
        d = preflight.local_headroom("/nonexistent-directory-xyz", required_bytes=1)
        self.assertFalse(d.ok)
        self.assertEqual(d.reason, "local free space unreadable")

    def test_a_real_directory_reports_its_free_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = preflight.local_headroom(tmp, required_bytes=1)
            self.assertTrue(d.ok)
            self.assertGreater(d.free_bytes, 0)

    def test_a_huge_requirement_refuses_on_a_real_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = preflight.local_headroom(tmp, required_bytes=10 ** 18)
            self.assertFalse(d.ok)
            self.assertEqual(d.reason, "below local restore headroom")


class GatePrecedenceTests(unittest.TestCase):
    """The gate must run BEFORE the work, so a run that cannot finish never starts."""

    def _ctx(self, tmp, *, remote_free, state=UPLOADED):
        """A context holding one artifact aged past the hot window, so a real run
        reaches the point where it would start — and therefore the gate."""
        ctx, art = _fixture_ctx(Path(tmp), state=state)
        _age(art, days=30)
        ctx.with_remote_free(remote_free)
        return ctx

    def test_the_run_refuses_before_starting_without_headroom(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._ctx(tmp, remote_free=None)   # unreadable
            ctx.verifier = None                      # ALSO broken
            out = io.StringIO()
            code = backup_command(_Args("run", dry_run=False), None, out=out, ctx=ctx)
            text = out.getvalue()
            self.assertEqual(code, 2)
            # The headroom refusal must win the race: prevention, not interruption.
            self.assertIn("REFUSED", text)
            self.assertIn("remote_free unreadable", text)
            self.assertNotIn("no remote verifier", text)

    def test_the_run_proceeds_past_the_gate_with_headroom(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._ctx(tmp, remote_free=20 * GB)
            out = io.StringIO()
            code = backup_command(_Args("run", dry_run=True), None, out=out, ctx=ctx)
            text = out.getvalue()
            self.assertEqual(code, 0)
            self.assertNotIn("REFUSED", text)
            self.assertIn("dry run", text)

    def test_a_dry_run_never_needs_headroom(self):
        """A dry run makes no remote traffic, so it must not be gated on the remote."""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._ctx(tmp, remote_free=None)
            out = io.StringIO()
            code = backup_command(_Args("run", dry_run=True), None, out=out, ctx=ctx)
            self.assertEqual(code, 0)
            self.assertIn("dry run", out.getvalue())


class DrillLocalGateTests(unittest.TestCase):
    """The drill pre-checks local free space before any restore write, and names the
    required headroom in the record."""

    def test_the_drill_refuses_before_writing_without_local_headroom(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, art = _fixture_ctx(Path(tmp), state="flipped")
            _age(art, days=30)
            # An absurd margin: the gate must refuse rather than start the restore.
            ctx.section = {"restore_headroom_margin_gb": 10_000_000}
            out = io.StringIO()
            code = backup_command(_Args("check", artifact=None, kind="monthly"),
                                  None, out=out, ctx=ctx)
            text = out.getvalue()
            self.assertEqual(code, 2)
            self.assertIn("REFUSED", text)
            self.assertIn("below local restore headroom", text)
            # The record must name the requirement AND its derivation.
            self.assertIn("required=", text)
            self.assertIn("scratch=", text)
            self.assertIn("margin=", text)
            # And it must never name the artifact's path.
            self.assertNotIn(str(art), text)

    def test_the_drill_record_names_the_artifact_size_not_its_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx, art = _fixture_ctx(Path(tmp), state="flipped")
            _age(art, days=30)
            ctx.section = {"restore_headroom_margin_gb": 10_000_000}
            out = io.StringIO()
            backup_command(_Args("check", artifact=None, kind="monthly"),
                           None, out=out, ctx=ctx)
            self.assertIn(f"scratch={art.stat().st_size}", out.getvalue())


class _Args:
    def __init__(self, backup_action, *, dry_run=True, **kw):
        self.backup_action = backup_action
        self.dry_run = dry_run
        self.__dict__.update(kw)


if __name__ == "__main__":
    unittest.main()
