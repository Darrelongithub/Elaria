"""BH-K12 — a daemon REFUSAL is not "daemon unavailable".

ipc.call raised plain RuntimeError for ok:False replies, and ~37 CLI sites
caught (DaemonUnavailable, RuntimeError, OSError) around the call and
silently re-ran the operation against the local store. A live daemon's
refusal ("no review item 999") was therefore masked: the CLI fell back,
the local write also did nothing, and the user was told it worked.
Post-fix: ok:False raises ipc.DaemonError; local fallbacks trigger ONLY on
DaemonUnavailable; refusals print as refusals and exit 2.
"""

from __future__ import annotations

import pytest

from assistant import ipc
from assistant.cli import main
from assistant.ipc import DaemonUnavailable, call


def test_ok_false_raises_daemon_error_not_unavailable(config, running_daemon):
    with pytest.raises(ipc.DaemonError) as err:
        call(config.socket_path, "review.decide",
             {"item_id": 999, "verdict": "approve"}, timeout=5.0)
    assert "no review item 999" in str(err.value)
    assert not isinstance(err.value, DaemonUnavailable), (
        "the daemon ANSWERED — that must be distinguishable from unreachable")


def test_missing_socket_still_raises_unavailable(tmp_path):
    with pytest.raises(DaemonUnavailable):
        call(tmp_path / "nope.sock", "status", timeout=1.0)


def test_cli_surfaces_daemon_refusal_instead_of_local_fallback(
        config, running_daemon, capsys):
    _daemon, _server = running_daemon
    rc = main(["review", "approve", "999"])
    captured = capsys.readouterr()
    assert rc == 2, f"a refusal is an answer: exit 2, got {rc}"
    assert "no review item 999" in captured.err
    assert "approved" not in captured.out, (
        "pre-fix this printed 'item 999: approved' and exited 0 while "
        "nothing had happened (daemon refusal masked by local fallback)")


def test_cli_local_path_is_honest_about_missing_item(capsys):
    # No running_daemon: the local fallback runs — and must report the
    # missing item instead of claiming success (set_item_decision's
    # rowcount was previously ignored).
    rc = main(["review", "approve", "999"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "no review item 999" in captured.err
    assert "approved" not in captured.out


def test_cli_daemon_down_fallback_still_works_for_reads(capsys):
    # The narrowing must not break the legitimate daemon-down paths.
    rc = main(["cost"])
    assert rc == 0
    assert "Tier:" in capsys.readouterr().out
