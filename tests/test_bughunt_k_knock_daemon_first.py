"""BH-K32: `assist knock accept|decline|…` bypassed the running daemon.

_recon suspect S10, proven_: the mutating knock actions never called
the daemon — they drove a local InitiativeService directly, even with
the daemon up. Consequences:

* accept printed "voice · first line: <reason>" but the reason was
  never appended to the daemon's conversation and never spoken (the
  local service has no sessions) — a fabricated success;
* a WAKE-knock could be "accepted" with no WakeGuard authentication
  or plumbing at all, while the guard stayed wedged in `wake_knock`
  state holding the pending utterance;
* decline/ignore of a wake-knock never told the guard, so its
  RAM-only pending audio was never zeroed by the deny path;
* raise/due delivered no knock signal (no notification, no sound).

Fix: knock actions go to the daemon first (it owns the guard, the
conversation, and the signal); the local store is the fallback only
when the daemon is unreachable, and a wake-knock *accept* refuses
locally — only the guard can settle it, and its pending audio died
with the daemon process.
"""

from __future__ import annotations

from assistant.cli import _initiative, main

REASON = "While filing, I noticed the Q3 invoice is still unsorted."


def _raise(config, *, kind="finding"):
    service, store, owned = _initiative(config)
    try:
        knock = service.raise_knock(topic="the Q3 invoice", reason=REASON,
                                    kind=kind, referent="the Q3 invoice")
        return knock["id"]
    finally:
        if owned:
            store.close()


def test_cli_accept_reaches_the_daemon_conversation(config, running_daemon):
    daemon, _server = running_daemon
    knock_id = _raise(config)
    rc = main(["knock", "accept", str(knock_id)])
    assert rc == 0
    messages = daemon.sessions.history()["messages"]
    assert any(m.get("via") == "knock" and m.get("text") == REASON
               for m in messages), (
        "her reason must open the daemon's conversation — the local "
        f"CLI accept used to claim this without doing it: {messages!r}")


def test_cli_decline_of_wake_knock_releases_the_guard(config, running_daemon):
    daemon, _server = running_daemon
    knock_id = _raise(config, kind="wake")
    daemon.wake_guard.state = "wake_knock"
    rc = main(["knock", "decline", str(knock_id)])
    assert rc == 0
    assert daemon.wake_guard.state != "wake_knock", (
        "the guard must be told (deny path zeroes the pending audio); "
        "a CLI-local decline left it wedged in wake_knock")


def test_wake_knock_accept_refuses_without_the_daemon(config, capsys):
    # No running_daemon fixture: the socket is absent, as on a stopped box.
    knock_id = _raise(config, kind="wake")
    rc = main(["knock", "accept", str(knock_id)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "wake" in err.lower() and "daemon" in err.lower(), err
    service, store, owned = _initiative(config)
    try:
        assert service.get(knock_id)["status"] == "pending"
    finally:
        if owned:
            store.close()
