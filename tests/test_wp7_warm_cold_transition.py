"""Tests for scripts/warm-cold-transition.py — the STEP-3 machinery proof.

These drive the real reconcile state machine through every state the manifest defines,
against a local-path backend fixture. They prove the *machinery*; they do not and cannot
prove the network, and they say so rather than implying otherwise.

The behaviours worth pinning are the ones that make a cold transition trustworthy:
the flip refuses to be asserted without a confirmed remote copy, a fixture backend's
confirmation is never readable as real remote confirmation, the grace clock produces
silence while it runs, and the purge only happens after it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "warm-cold-transition.py")


def _run(root: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT, "--root", root, *extra],
        check=False, capture_output=True,
        text=True,
    )


class WarmColdTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_the_full_walk_reaches_purged(self):
        r = _run(self.root, "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(
            payload["final_state"], "purged",
            "the artifact must walk every state and end purged",
        )
        self.assertEqual(
            [s["step"] for s in payload["steps"]],
            ["local", "uploaded", "flipped", "trimmed", "grace_running", "purged",
             "quiesced"],
        )

    def test_each_state_lands_exactly_once(self):
        r = _run(self.root, "--json")
        payload = json.loads(r.stdout)
        by_step = {s["step"]: s for s in payload["steps"]}
        self.assertEqual(by_step["flipped"]["before"], "uploaded")
        self.assertEqual(by_step["flipped"]["after"], "flipped")
        self.assertEqual(by_step["trimmed"]["before"], "flipped")
        self.assertEqual(by_step["trimmed"]["after"], "trashed")
        self.assertEqual(by_step["purged"]["before"], "trashed")
        self.assertEqual(by_step["purged"]["after"], "purged")

    def test_the_flip_names_the_backend_that_confirmed_it(self):
        """Increment 4's third requirement, made structural: every verification record
        names the backend that produced it. A bare bool would report `opaque-verifier`."""
        r = _run(self.root, "--json")
        payload = json.loads(r.stdout)
        reasons = {s["step"]: s for s in payload["steps"]}["flipped"]["plan"]["reasons"]
        self.assertTrue(reasons, "the flip must carry a reason")
        self.assertIn("local-path-fixture", reasons[0])
        self.assertNotIn("opaque-verifier", reasons[0])

    def test_the_grace_clock_is_silent_while_it_runs(self):
        """Two copies remain during the grace, and that silence is the copy-count
        invariant holding — not a missed action."""
        r = _run(self.root, "--json")
        by_step = {s["step"]: s for s in json.loads(r.stdout)["steps"]}
        self.assertEqual(by_step["grace_running"]["actions"], 0)

    def test_the_purge_happens_only_after_the_grace(self):
        r = _run(self.root, "--json", "--grace-days", "14")
        by_step = {s["step"]: s for s in json.loads(r.stdout)["steps"]}
        self.assertIn("grace elapsed", by_step["purged"]["plan"]["reasons"][0])

    def test_a_longer_grace_delays_the_purge(self):
        """The grace is a real clock, not a constant."""
        r = _run(self.root, "--json", "--grace-days", "365")
        payload = json.loads(r.stdout)
        by_step = {s["step"]: s for s in payload["steps"]}
        self.assertEqual(by_step["grace_running"]["actions"], 0)
        self.assertEqual(by_step["grace_running"]["actions"], 0)
        # Day 13 of 365 is nowhere near the grace, and day 366 is well past it.
        self.assertIn("366d >= 365d", by_step["purged"]["plan"]["reasons"][0])
        self.assertEqual(payload["final_state"], "purged")

    def test_reconcile_reaches_quiescence(self):
        r = _run(self.root, "--json")
        by_step = {s["step"]: s for s in json.loads(r.stdout)["steps"]}
        self.assertEqual(by_step["quiesced"]["actions"], 0)
        self.assertEqual(by_step["quiesced"]["problems"], [])

    def test_the_record_is_path_blind(self):
        """No filesystem path and no filename may appear in the output. The privacy
        fence is what lets a manifest record be shown at all."""
        r = _run(self.root)
        combined = r.stdout + r.stderr
        self.assertNotIn(self.root, combined)
        self.assertNotIn("synthetic-capture.wav", combined)
        self.assertNotIn("fixture-remote", combined)

    def test_the_output_says_it_does_not_prove_the_network(self):
        """The honest limit is stated, not implied. A reader must not be able to mistake
        this fixture run for a live MEGA transition."""
        r = _run(self.root)
        self.assertIn("DOES NOT PROVE", r.stdout)
        self.assertIn("local-path-fixture", r.stdout)


if __name__ == "__main__":
    unittest.main()
