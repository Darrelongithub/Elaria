"""H · DESKTOP — step 2: presence reports DEVICE-presence, not only posture.

The phone-connected state has to reach the orb/pill as a *fact about a link*, so the
surface can be trustworthy about it: connected, dropped, or — the case a naive feed
gets wrong — heard-about-then-silent. That last one renders as NOT connected with a
reason, never as a stuck "connected" dot.

H consumes E's notion through events only (the daemon folds them in — HR-H-1); these
tests never import E, never touch a socket, and never let a presence event do
anything but be recorded.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from assistant.presence import (
    DEFAULT_DEVICE_STALE_AFTER_S,
    DEVICE_STATE_KEY,
    STATE_KEY,
    DevicePresence,
    PresenceService,
    format_device_line,
)

T0 = datetime(2026, 11, 19, 12, 0, 0)


class FakeStore:
    """Only the two state calls presence makes — a typo'd key fails loudly."""

    def __init__(self):
        self.state: dict[str, str] = {}
        self.writes: list[str] = []

    def get_state(self, key, default=None):
        return self.state.get(key, default)

    def set_state(self, key, value):
        self.writes.append(key)
        self.state[key] = value


class FakeConfig:
    def __init__(self, presence=None):
        self._presence = presence or {}

    def section(self, name):
        return dict(self._presence) if name == "presence" else {}


def service(store=None, config=None, clock=lambda: T0):
    return PresenceService(config or FakeConfig(), store if store is not None else FakeStore(),
                           now=clock)


# ---------------------------------------------------------------------------
# desktop case · nothing has been heard yet
# ---------------------------------------------------------------------------
def test_no_event_yet_reports_unknown_not_disconnected():
    presence = service().device()
    assert presence == DevicePresence(
        phone_connected=False, source="none",
        detail="no phone-sidecar event received yet (device-presence waits on HR-H-1)")
    # "never heard from" and "we heard it drop" are different claims; the line says so.
    assert format_device_line(presence.as_dict()).startswith("phone: unknown")


def test_dropped_link_reports_not_connected():
    svc = service()
    svc.apply_event({"event": "phone.connected", "source": "fake-android"})
    after = svc.apply_event({"event": "phone.disconnected", "source": "fake-android"})
    assert after.phone_connected is False
    assert format_device_line(after.as_dict()).startswith("phone: not connected")


def test_unreadable_state_is_reported_not_guessed():
    store = FakeStore()
    store.state[DEVICE_STATE_KEY] = "{not json"
    presence = service(store=store).device()
    assert presence.phone_connected is False
    assert presence.source == "corrupt"
    assert "not connected" in format_device_line(presence.as_dict())


# ---------------------------------------------------------------------------
# device case · the fold
# ---------------------------------------------------------------------------
def test_connected_event_folds_to_connected_and_persists_once():
    store = FakeStore()
    svc = service(store=store)
    presence = svc.apply_event({"event": "phone.connected", "source": "fake-android"},
                               now=T0)
    assert (presence.phone_connected, presence.source) == (True, "event")
    assert "fake-android" in presence.detail
    assert store.writes == [DEVICE_STATE_KEY]          # exactly one write, one key
    # and it survives a "daemon restart" — i.e. it is read back, not remembered in RAM
    assert service(store=store).device(now=T0).phone_connected is True


@pytest.mark.parametrize("event", ["phone.pairing.paired", "pairing.paired"])
def test_the_recognised_pairing_tokens_count_as_connected(event):
    assert service().apply_event({"event": event}).phone_connected is True


def test_unknown_events_are_ignored_rather_than_interpreted():
    store = FakeStore()
    svc = service(store=store)
    for event in ({"event": "phone.locked"}, {"event": "sms.received"},
                  {"event": "session.started"}, {}, {"nonsense": True}):
        assert svc.apply_event(event).phone_connected is False
    assert store.writes == []                          # nothing fabricated, nothing stored


def test_age_is_measured_and_a_quiet_link_goes_stale():
    store = FakeStore()
    svc = service(store=store)
    svc.apply_event({"event": "phone.connected"}, now=T0)
    fresh = svc.device(now=T0 + timedelta(seconds=10))
    assert (fresh.phone_connected, fresh.stale, fresh.age_s) == (True, False, 10.0)
    old = svc.device(now=T0 + timedelta(seconds=DEFAULT_DEVICE_STALE_AFTER_S + 5))
    assert (old.phone_connected, old.stale) == (False, True)
    assert "quiet" in format_device_line(old.as_dict())
    # the stored record is not rewritten by a read — staleness is derived, not stored
    assert store.writes == [DEVICE_STATE_KEY]


def test_stale_window_is_configurable_and_bad_values_fall_back():
    def probe(value):
        svc = service(store=FakeStore(), config=FakeConfig({"device_stale_after_s": value}))
        svc.apply_event({"event": "phone.connected"}, now=T0)
        return svc.device(now=T0 + timedelta(seconds=10))

    assert probe(5).stale is True
    assert probe(60).stale is False
    assert probe("nonsense").stale is False            # falls back to 45s, never crashes
    assert DEFAULT_DEVICE_STALE_AFTER_S == 45.0


def test_owner_can_switch_the_notion_off():
    store = FakeStore()
    store.state[DEVICE_STATE_KEY] = json.dumps({"connected": True, "observed_at": 1.0,
                                                "detail": "stale record"})
    svc = service(store=store, config=FakeConfig({"device_presence": False}))
    assert svc.device().source == "disabled"
    assert svc.device().phone_connected is False
    assert format_device_line(svc.device().as_dict()) == ""     # silent, not "off-ish"


# ---------------------------------------------------------------------------
# the no-autonomy seam, behaviourally (step 4's other half)
# ---------------------------------------------------------------------------
def test_a_phone_event_cannot_touch_posture():
    """The whole point of the separate state key: a link state must never be able
    to set, clear or suggest class mode."""
    store = FakeStore()
    svc = service(store=store)
    before = svc.status(now=T0).as_dict()
    svc.apply_event({"event": "phone.connected"}, now=T0)
    svc.apply_event({"event": "phone.disconnected"}, now=T0)
    assert svc.status(now=T0).as_dict() == before
    # 2 events folded → 2 writes, and every one of them is the device key.
    assert store.writes == [DEVICE_STATE_KEY, DEVICE_STATE_KEY]
    assert STATE_KEY not in store.state


def test_toggle_still_only_ever_writes_the_posture_key():
    store = FakeStore()
    svc = service(store=store)
    svc.set_enabled(True)
    assert store.writes == [STATE_KEY]
    assert svc.status(now=T0).enabled is True
    assert svc.status(now=T0).knock_style == "silent-visual"


# ---------------------------------------------------------------------------
# the surface side: snapshot for the orb, one line for every renderer
# ---------------------------------------------------------------------------
def test_snapshot_shape_is_what_hr_h_1_hands_z():
    snap = service().snapshot(now=T0)
    assert sorted(snap) == ["class_mode", "device_presence"]
    assert sorted(snap["device_presence"]) == [
        "age_s", "detail", "observed_at", "phone_connected", "source", "stale"]
    assert snap["device_presence"]["phone_connected"] is False
    assert snap["class_mode"]["enabled"] is False
    assert json.dumps(snap)                            # IPC-safe


def test_snapshot_survives_a_numeric_clock():
    """A daemon may hand epoch seconds rather than a datetime; the schedule side
    resolves it instead of dying on a `weekday()` call it never needed."""
    svc = service(clock=lambda: T0.timestamp() + 10)
    snap = svc.snapshot(now=T0.timestamp() + 10)
    assert snap["device_presence"]["phone_connected"] is False
    assert snap["class_mode"]["enabled"] is False


def test_a_real_schedule_window_still_suggests_with_a_numeric_clock():
    """The numeric clock must not silently disable the class-mode suggestion —
    that would be device-presence eating a feature it was only supposed to join."""
    config = FakeConfig({"class_schedule": [
        {"days": ["thu"], "start": "11:00", "end": "13:00", "label": "lecture block"}]})
    svc = service(config=config, clock=lambda: T0)
    assert svc.schedule_match(T0)["label"] == "lecture block"
    numeric = service(config=config, clock=lambda: T0.timestamp())
    assert numeric.schedule_match()["label"] == "lecture block"
    assert numeric.status().suggested is True


def test_no_injected_clock_at_all_still_works():
    """PresenceService(config, store) is how daemon.py and cli.py build it; the
    default must not have to change for device-presence to exist."""
    svc = PresenceService(FakeConfig(), FakeStore())
    assert svc.device().source == "none"
    assert svc.schedule_match() is None
    assert svc.snapshot()["class_mode"]["enabled"] is False


def test_format_device_line_handles_the_shapes_surfaces_send():
    assert format_device_line({}) == ""
    assert format_device_line({"phone_connected": True}) == "phone: connected — device-presence from event"
    assert format_device_line({"phone_connected": True, "source": "state",
                               "detail": "x"}).endswith("from state (x)")
    assert format_device_line({"stale": True, "detail": "gone quiet"}) == "phone: stale — gone quiet"
    assert format_device_line({"stale": True}) == "phone: stale — the link went quiet"
    assert format_device_line({"source": "corrupt"}) == "phone: not connected — corrupt"


def test_waybar_shows_the_phone_line_and_waits_for_z_to_feed_it():
    """Desktop case (key absent → nothing said) and device case (key present →
    the line appears). No class token is invented for it."""
    from assistant.waybar import format_waybar
    base = {"running": True, "mode": "listening", "gemini_mode": "live"}
    without = format_waybar(base)
    assert "phone:" not in without["tooltip"]

    with_phone = format_waybar({**base, "device_presence": {
        "phone_connected": True, "source": "event", "detail": "phone.connected via fake-android",
        "observed_at": 1.0, "age_s": 2.0, "stale": False}})
    assert "phone: connected — device-presence from event (phone.connected via fake-android)" \
        in with_phone["tooltip"]
    assert with_phone["class"] == without["class"] == ["listening"]
    assert with_phone["text"] == without["text"]        # the pill's face is unchanged

    stale = format_waybar({**base, "device_presence": {
        "phone_connected": False, "source": "stale", "stale": True,
        "detail": "last heard 50s ago"}})
    assert "phone: stale — last heard 50s ago" in stale["tooltip"]


def test_the_follow_stream_needs_no_new_refresh_path():
    """Once Z broadcasts the presence change, the pill follows with no further H
    edit: `stream_waybar` already re-renders on every broadcast and on every tick.
    Asserted by counting the existing re-render sites, not by trusting the claim."""
    from assistant import waybar

    assert "immediately on daemon events" in (waybar.stream_waybar.__doc__ or "")
    body = (Path(__file__).resolve().parents[1] / "src/assistant/waybar.py").read_text()
    assert body.count("yield format_waybar(_safe_status(socket_path))") == 3  # boot + tick + event


def test_presence_never_opens_a_socket_or_spawns_anything():
    """Device-presence is a store read + a dict. If it ever grows a connect() or a
    subprocess, it has become a second sidecar and this lane is the wrong place."""
    src = (Path(__file__).resolve().parents[1] / "src/assistant/presence.py").read_text()
    for banned in ("socket", "subprocess", "httpx", "requests", ".connect(", "Popen"):
        assert banned not in src, f"presence.py reached for {banned}"
