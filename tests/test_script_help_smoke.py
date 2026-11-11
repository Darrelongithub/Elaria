"""Scripts `--help` smoke — the paired half of the upstream `%%` fix
(2026-10-26 stream-3 judgment).

argparse %-expands help strings: a bare `20%` in `help=` raises
"unsupported format character '/'" whenever help is displayed. The fix
escapes it as `%%` in help text ONLY — plain print() strings keep a
literal `%` (`%%` there would print doubled).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "record_elaria_samples.py"


def _run_help(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--help"],
        capture_output=True, text=True, timeout=30, check=False)


def test_record_elaria_samples_help_shows_twenty_percent_not_crash():
    # Top-level help lists every subcommand's help= string — this is where
    # argparse's %-expansion used to die on `20%/bucket`.
    out = _run_help()
    assert out.returncode == 0, out.stderr
    assert "freeze-eval" in out.stdout
    assert "20%/bucket" in out.stdout          # `%%` rendered as one `%`
    assert "20%%" not in out.stdout


def test_record_elaria_samples_each_subcommand_help_runs():
    for leaf in ("plan", "freeze-eval", "status"):
        out = _run_help(leaf)
        assert out.returncode == 0, f"{leaf} --help failed: {out.stderr}"
