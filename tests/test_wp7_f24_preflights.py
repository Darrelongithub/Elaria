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


class QuotaProducerTests(unittest.TestCase):
    """The gate needs a READING, and something has to produce it.

    Found while building the owner packets: `build_context` never populated
    `remote_free_bytes`, so the F24 gate would have refused every real run forever —
    nothing produced its input. A gate that can never open is a gate that has been
    silently switched off, which is the same failure as a gate that never closes.
    """

    def _fake_rclone(self, tmp: str, payload: str) -> str:
        path = os.path.join(tmp, "rclone")
        with open(path, "w") as fh:
            fh.write(f"#!/bin/sh\necho '{payload}'\n")
        os.chmod(path, 0o755)
        return path

    def test_the_quota_is_parsed_from_the_pinned_about_verb(self):
        from assistant.remote import RcloneBackend
        with tempfile.TemporaryDirectory() as tmp:
            self._fake_rclone(tmp, '{"total":21474836480,"used":3221225472,'
                                   '"free":18253611008}')
            old_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = tmp + os.pathsep + old_path
                backend = RcloneBackend("elaria-mega", path="elaria-restic")
                self.assertEqual(backend.remote_free(), 18253611008)
            finally:
                os.environ["PATH"] = old_path

    def test_the_about_argv_is_the_pinned_one_not_an_improvised_command(self):
        from assistant.remote import RcloneBackend
        backend = RcloneBackend("elaria-mega", path="elaria-restic")
        self.assertEqual(backend.argv("about"),
                         ["rclone", "about", "elaria-mega:elaria-restic", "--json"])

    def test_a_malformed_payload_yields_none_rather_than_a_guess(self):
        from assistant.remote import RcloneBackend
        with tempfile.TemporaryDirectory() as tmp:
            self._fake_rclone(tmp, "not json at all")
            old_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = tmp + os.pathsep + old_path
                backend = RcloneBackend("elaria-mega", path="elaria-restic")
                self.assertIsNone(backend.remote_free())
            finally:
                os.environ["PATH"] = old_path

    def test_an_absent_rclone_yields_none(self):
        """No rclone on PATH: the reading is unreadable, which is a refusal at the
        gate — never a pass, and never a zero."""
        from assistant.remote import RcloneBackend
        backend = RcloneBackend("elaria-mega", path="elaria-restic",
                                binary="rclone-that-does-not-exist")
        self.assertIsNone(backend.remote_free())

    def test_a_fixture_backend_has_no_quota_and_says_so(self):
        from assistant.remote import LocalPathBackend
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(LocalPathBackend(tmp).remote_free())

    def test_build_context_reads_the_quota_when_a_remote_is_configured(self):
        """The wiring. Without it the gate's input is never produced."""
        from assistant.backup_cli import build_context

        class _Cfg:
            data_dir = Path(".")
            def section(self, name):
                return {"rclone_remote": "elaria-mega", "rclone_path": "elaria-restic"}

        with tempfile.TemporaryDirectory() as tmp:
            self._fake_rclone(tmp, '{"total":21474836480,"used":0,"free":21474836480}')
            old_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = tmp + os.pathsep + old_path
                ctx = build_context(_Cfg(), read_quota=True)
                self.assertEqual(ctx.remote_free_bytes, 21474836480)
                self.assertTrue(ctx.remote_preflight().ok)
            finally:
                os.environ["PATH"] = old_path

    def test_build_context_can_skip_the_quota_read(self):
        """`read_quota=False` lets a caller build a context without touching the
        remote — which is what a dry run and a fixture need."""
        from assistant.backup_cli import build_context

        class _Cfg:
            data_dir = Path(".")
            def section(self, name):
                return {"rclone_remote": "elaria-mega", "rclone_path": "elaria-restic"}

        with tempfile.TemporaryDirectory():
            ctx = build_context(_Cfg(), read_quota=False)
            self.assertIsNone(ctx.remote_free_bytes)


class PacketNumberDriftTests(unittest.TestCase):
    """The owner packets quote numbers. These tests stop the docs drifting from the code.

    A packet that says 2.53 GiB while the gate enforces something else is worse than no
    packet: the owner would act on a figure that was never true.
    """

    DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "docs", "live-scene")

    def _read(self, name: str) -> str:
        with open(os.path.join(self.DOCS, name), encoding="utf-8") as fh:
            return fh.read()

    def _read_folded(self, name: str) -> str:
        """Case-folded, so a heading's capitals do not read as a missing fact."""
        return self._read(name).casefold()

    def test_every_packet_exists(self):
        for name in ("op3-cold-flip-packet.md", "op5-monthly-drill-packet.md",
                     "owner-sitting-sheet.md"):
            self.assertTrue(os.path.exists(os.path.join(self.DOCS, name)), name)

    def test_the_packets_quote_the_derived_scratch_not_a_round_number(self):
        """Both the bare and the comma-grouped form are accepted, because a packet
        written for a human reads 2,719,664,640 and a test should not fail on the comma."""
        scratch = preflight.bench_scratch_bytes()
        required = scratch + 1 * 1000 ** 3
        def forms(v):
            return {str(v), f"{v:,}"}

        # Markdown emphasis rides along with the token, so strip it before comparing.
        def tokens(text):
            return {t.strip("`*_> ") for t in text.split()}

        for name in ("op3-cold-flip-packet.md", "owner-sitting-sheet.md"):
            text = self._read(name)
            self.assertTrue(forms(scratch) & tokens(text),
                            f"{name} must quote the derived scratch")
            self.assertTrue(any(f in text for f in forms(required)),
                            f"{name} must quote the derived requirement")

    def test_the_drill_packet_quotes_the_local_margin(self):
        text = self._read("op5-monthly-drill-packet.md")
        self.assertIn("1 GB margin", text)
        self.assertIn("scratch=", text)

    def test_the_packets_state_the_window_arithmetic_for_the_named_wav(self):
        """The single most important fact in packet 3: run before the window elapses
        and the flip silently does nothing."""
        text = self._read("op3-cold-flip-packet.md")
        self.assertIn("2026-11-02 10:05:58", text)
        self.assertIn("2026-11-16", text)
        self.assertIn("14 days", text)

    def test_the_sitting_sheet_names_the_order_and_does_not_reorder_it(self):
        text = self._read("owner-sitting-sheet.md")
        order = [text.index(f"**{n}**") for n in ("0", "1", "3", "5", "4", "2")]
        self.assertEqual(order, sorted(order),
                         "the sitting sheet must list the steps in execution order")

    def test_the_sitting_sheet_repeats_the_mega_trash_caveat(self):
        text = self._read_folded("owner-sitting-sheet.md")
        self.assertIn("mega-trash", text)
        self.assertIn("--mega-hard-delete", text)

    def test_every_packet_states_cleanup_is_never_automatic(self):
        for name in ("op3-cold-flip-packet.md", "op5-monthly-drill-packet.md",
                     "owner-sitting-sheet.md"):
            self.assertIn("never automatic", self._read_folded(name), name)

    def test_no_packet_contains_a_credential(self):
        """The privacy fence, pinned. No packet may carry a secret-shaped assignment."""
        import re
        pattern = re.compile(r"(password|passphrase|secret|api_key|token)"
                             r"\s*=\s*[\"'][^\"']{8,}[\"']", re.IGNORECASE)
        for name in ("op3-cold-flip-packet.md", "op5-monthly-drill-packet.md",
                     "owner-sitting-sheet.md"):
            self.assertIsNone(pattern.search(self._read(name)), name)


class _Args:
    def __init__(self, backup_action, *, dry_run=True, **kw):
        self.backup_action = backup_action
        self.dry_run = dry_run
        self.__dict__.update(kw)


if __name__ == "__main__":
    unittest.main()
