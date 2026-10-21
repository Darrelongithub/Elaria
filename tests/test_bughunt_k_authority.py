"""BH-K10/K11 — posture checks fail closed; stored posture is the truth.

K10: WakeGuard._in_class_mode()/_guest_door_blocked() returned False on
    ANY exception from the wired presence/showoff probe — fail OPEN. A
    broken probe let an accepted wake-knock open voice listening during
    class mode or an active show-off. (WakeGuardError's own docstring says
    "fail closed"; these two helpers were the exception.)
K11: DisclosureService.company() cached the first read per process. The
    daemon therefore never observed company state written by another
    process (the CLI's local path writes the same store directly), so its
    disclosure posture silently diverged from the stored truth.
    PresenceService already reads fresh; disclosure now does too.
"""

from __future__ import annotations

from assistant.disclosure import STATE_KEY, DisclosureService
from assistant.store import Store
from assistant.wake_guard import WakeGuard


def _boom():
    raise RuntimeError("presence probe exploded")


class _BoomShowoff:
    def status(self):
        raise RuntimeError("showoff probe exploded")


def test_class_mode_probe_failure_fails_closed():
    guard = WakeGuard(settings={}, class_mode=_boom)
    assert guard._in_class_mode() is True, (
        "a broken class-mode probe must restrict (console, not PTT), "
        "never silently open the voice path")


def test_showoff_probe_failure_fails_closed():
    guard = WakeGuard(settings={}, showoff=_BoomShowoff())
    assert guard._guest_door_blocked() is True, (
        "a broken showoff probe must block the guest door, not open it")


def test_unwired_posture_is_not_a_failure():
    guard = WakeGuard(settings={})
    assert guard._in_class_mode() is False
    assert guard._guest_door_blocked() is False


def test_posture_probe_error_is_visible_in_status():
    guard = WakeGuard(settings={}, class_mode=_boom)
    guard._in_class_mode()
    status = guard.status()
    assert status.get("posture_error"), (
        "fail-closed must be diagnosable, not silent: status() names the "
        "broken probe")


def test_company_state_is_read_fresh_from_the_store(tmp_path):
    store = Store(tmp_path / "disclosure.db")
    try:
        svc = DisclosureService(config=None, store=store)
        assert svc.company() is False
        # Another process (the CLI's local path) writes the same store:
        store.set_state(STATE_KEY, "1")
        assert svc.company() is True, (
            "the daemon must observe company state written elsewhere; "
            "a per-process cache speaks secrets on stale posture")
        store.set_state(STATE_KEY, "0")
        assert svc.company() is False
    finally:
        store.close()


def test_set_company_still_persists_for_other_readers(tmp_path, config):
    store = Store(tmp_path / "disclosure2.db")
    try:
        writer = DisclosureService(config, store)
        writer.set_company(True)
        reader = DisclosureService(config=None, store=store)
        assert reader.company() is True
        writer.set_company(False)
        assert reader.company() is False
    finally:
        store.close()
