"""H · DESKTOP — step 2 (round 2): presence reports the phone honestly.

Round 1 built this against tokens it invented (`phone.connected`) because the
contracts were unread. Round 2 read IF-4 (387fa084… verified) and E's landed
emission (RPT-E-r2 §D), and the model was corrected to match:

  * pairing is durable and is NOT presence — `phone.paired` must not light the orb;
  * presence needs a liveness signal, which no frozen contract emits yet → the orb's
    `phone-connected` state stays unclaimed (IF-4: a signal the daemon did not
    produce makes the orb lie; unknown states THROW, so H emits contract tokens only);
  * staleness applies to liveness only — round 1 decayed a *pairing record* after
    45 s, which would have made a perfectly paired phone read as absent.

Every test below is a claim about what the surface is allowed to SAY.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from assistant.presence import (
    DEFAULT_DEVICE_STALE_AFTER_S,
    DEVICE_STATE_KEY,
    NOT_PRESENCE_EVENTS,
    ORB_STATE_PHONE_CONNECTED,
    PHONE_PAIRED_EVENTS,
    PHONE_UNPAIRED_EVENTS,
    STATE_KEY,
    PresenceService,
    format_device_line,
)

REPO = Path(__file__).resolve().parents[1]
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


def service(store=None, config=None, clock=None):
    return PresenceService(config or FakeConfig(),
                           store if store is not None else FakeStore(),
                           now=clock if clock is not None else (lambda: T0))


# ---------------------------------------------------------------------------
# the desktop case · nothing has been reported
# ---------------------------------------------------------------------------
def test_nothing_reported_says_nothing_invented():
    presence = service().device()
    assert presence.source == "absent"
    assert (presence.paired, presence.link_up, presence.phone_connected) == (False, False, False)
    assert presence.orb_states == ()
    assert format_device_line(presence.as_dict()).startswith("phone: never reported")


def test_corrupt_state_is_reported_not_guessed():
    store = FakeStore()
    store.state[DEVICE_STATE_KEY] = "{not json"
    presence = service(store=store).device()
    assert presence.source == "corrupt"
    assert presence.phone_connected is False
    assert "unreadable" in format_device_line(presence.as_dict())


# ---------------------------------------------------------------------------
# pairing: a fact about configuration, not about presence
# ---------------------------------------------------------------------------
def test_pairing_is_recorded_and_does_not_claim_presence():
    store = FakeStore()
    svc = service(store=store)
    presence = svc.apply_event({"event": "phone.paired", "source": "caelestia-connectd"},
                               now=T0)
    assert (presence.paired, presence.link_up, presence.phone_connected) == (True, False, False)
    assert presence.source == "paired"
    assert presence.orb_states == ()                 # the orb must stay dark
    assert store.writes == [DEVICE_STATE_KEY]        # 1 write, the device key only
    line = format_device_line(presence.as_dict())
    assert line.startswith("phone: paired — presence unknown")
    assert "no liveness signal yet" in line          # says why, not just what


def test_a_pairing_record_does_not_decay_and_never_touches_posture():
    """Round 1's defect, pinned away: staleness was applied to the whole record, so
    a paired phone with no ping went quiet in the pill after 45s. Pairing is
    durable; only liveness ages."""
    store = FakeStore()
    svc = service(store=store)
    svc.apply_event({"event": "phone.paired"}, now=T0)
    much_later = svc.device(now=T0 + timedelta(days=1))
    assert (much_later.paired, much_later.stale, much_later.source) == (True, False, "paired")
    assert store.writes == [DEVICE_STATE_KEY]        # reads wrote nothing
    assert STATE_KEY not in store.state


@pytest.mark.parametrize("event", ["phone.unpaired", "phone.revoked"])
def test_unpair_and_revocation_clear_presence_too(event):
    """IF-3: revocation = unpair + key removal. A revoked device is not 'here'.
    Round 1 stored a single boolean and could not express this at all."""
    store = FakeStore()
    svc = service(store=store)
    svc.apply_event({"event": "phone.paired"}, now=T0)
    svc.apply_liveness(link_up=True, source="ping.ping", now=T0)
    assert svc.device(now=T0).phone_connected is True
    after = svc.apply_event({"event": event}, now=T0)
    assert (after.paired, after.link_up, after.phone_connected) == (False, False, False)
    assert after.source == "unpaired"
    assert after.orb_states == ()
    record = json.loads(store.state[DEVICE_STATE_KEY])
    for dropped in ("link_seen_at", "link_detail", "link_reported_at"):
        assert dropped not in record                 # the whole liveness history goes


# ---------------------------------------------------------------------------
# events that are NOT presence
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("event", NOT_PRESENCE_EVENTS)
def test_send_refusal_inbound_and_draft_events_change_nothing(event):
    """A send proves the link was alive at some past instant; a draft event proves
    nothing about the phone. Neither may move presence — and neither may write."""
    store = FakeStore()
    svc = service(store=store)
    svc.apply_event({"event": "phone.paired"}, now=T0)
    before = svc.device(now=T0).as_dict()
    store.writes.clear()
    after = svc.apply_event({"event": event, "draft": {"draft_id": 1}}, now=T0).as_dict()
    assert after == before
    assert store.writes == []


def test_unknown_and_empty_events_are_ignored_not_interpreted():
    store = FakeStore()
    svc = service(store=store)
    for event in ({"event": "phone.locked"}, {"event": "session.started"}, {},
                  {"nonsense": True}, None):
        assert svc.apply_event(event, now=T0).phone_connected is False
    assert store.writes == []


def test_round1_invented_tokens_are_gone_from_the_lane():
    """`phone.connected` / `phone.pairing.paired` were invented here in round 1 and
    exist in no contract and no cluster. Leaving them accepted would be a surface
    that lights for an event nobody will ever send."""
    src = (REPO / "src/assistant/presence.py").read_text()
    for invented in ("phone.connected", "phone.pairing.paired", "pairing.paired",
                     "phone.disconnected", "pairing.unpaired"):
        assert f'"{invented}"' not in src, f"{invented} is still an accepted token"
    assert PHONE_PAIRED_EVENTS == ("phone.paired",)
    assert PHONE_UNPAIRED_EVENTS == ("phone.unpaired", "phone.revoked")


# ---------------------------------------------------------------------------
# liveness: the only road to `phone-connected`
# ---------------------------------------------------------------------------
def test_only_liveness_claims_presence_and_uses_the_contract_token():
    svc = service()
    presence = svc.apply_liveness(link_up=True, source="ping.ping", now=T0)
    assert (presence.phone_connected, presence.source) == (True, "event")
    assert presence.orb_states == (ORB_STATE_PHONE_CONNECTED,)
    assert ORB_STATE_PHONE_CONNECTED == "phone-connected"      # IF-4's spelling
    assert "liveness seen via ping.ping" in format_device_line(presence.as_dict())
    # ...and this is the ONLY line in the module that may claim presence:
    src = (REPO / "src/assistant/presence.py").read_text()
    assert src.count("phone_connected=True") == 1


def test_liveness_survives_a_restart_and_ages_out():
    store = FakeStore()
    svc = service(store=store)
    svc.apply_event({"event": "phone.paired"}, now=T0)
    svc.apply_liveness(link_up=True, source="connectivity_report", now=T0)
    fresh = service(store=store).device(now=T0 + timedelta(seconds=10))
    assert (fresh.phone_connected, fresh.age_s, fresh.orb_states) == (
        True, 10.0, (ORB_STATE_PHONE_CONNECTED,))
    old = service(store=store).device(now=T0 + timedelta(seconds=DEFAULT_DEVICE_STALE_AFTER_S + 1))
    assert (old.phone_connected, old.stale, old.orb_states) == (False, True, ())
    assert "went quiet" in format_device_line(old.as_dict())
    # derived, never rewritten: reads wrote exactly the 2 fold writes
    assert store.writes == [DEVICE_STATE_KEY, DEVICE_STATE_KEY]


def test_explicit_liveness_down_reports_paired_link_down():
    store = FakeStore()
    svc = service(store=store)
    svc.apply_event({"event": "phone.paired"}, now=T0)
    presence = svc.apply_liveness(link_up=False, source="ping.ping timeout", now=T0)
    assert (presence.paired, presence.phone_connected, presence.source) == (
        True, False, "link-down")
    assert format_device_line(presence.as_dict()).startswith("phone: paired, link down")


def test_stale_window_is_configurable_and_bad_values_fall_back():
    def probe(value):
        svc = service(store=FakeStore(), config=FakeConfig({"device_stale_after_s": value}))
        svc.apply_liveness(link_up=True, now=T0)
        return svc.device(now=T0 + timedelta(seconds=10))

    assert probe(5).stale is True
    assert probe(60).stale is False
    assert probe("nonsense").stale is False          # falls back to 45 s, never crashes
    assert DEFAULT_DEVICE_STALE_AFTER_S == 45.0


def test_owner_can_switch_the_notion_off_entirely():
    store = FakeStore()
    store.state[DEVICE_STATE_KEY] = json.dumps({"paired": True, "link_up": True,
                                                "link_seen_at": 1.0})
    svc = service(store=store, config=FakeConfig({"device_presence": False}))
    assert svc.device().source == "disabled"
    assert format_device_line(svc.device().as_dict()) == ""   # silent, not "off-ish"


# ---------------------------------------------------------------------------
# the surface side: one line, one snapshot, no new class token
# ---------------------------------------------------------------------------
def test_snapshot_shape_is_what_hr_h_1_and_h_2_hand_z():
    snap = service().snapshot(now=T0)
    assert sorted(snap) == ["class_mode", "device_presence"]
    assert sorted(snap["device_presence"]) == [
        "age_s", "detail", "link_up", "liveness_known", "observed_at", "orb_states",
        "paired", "phone_connected", "source", "stale"]
    assert snap["device_presence"]["orb_states"] == []
    assert snap["class_mode"]["enabled"] is False
    assert json.dumps(snap)                                  # IPC-safe


def test_all_sayers_of_the_line_agree_with_the_pill():
    """Three readings, three distinct sentences — and `device_line` is just the
    shared formatter, so pill/console cannot drift."""
    svc = service()
    for presence, head in ((svc.device(now=T0), "phone: never reported"),
                           (svc.apply_event({"event": "phone.paired"}, now=T0), "phone: paired"),
                           (svc.apply_liveness(link_up=True, now=T0), "phone: connected")):
        assert svc.device_line(presence).startswith(head)
        assert svc.device_line(presence) == format_device_line(presence.as_dict())


def test_waybar_says_the_phone_state_and_invents_no_class():
    from assistant.waybar import format_waybar
    base = {"running": True, "mode": "listening", "gemini_mode": "live"}
    assert "phone:" not in format_waybar(base)["tooltip"]

    paired = format_waybar({**base, "device_presence": {
        "paired": True, "link_up": False, "phone_connected": False, "source": "paired",
        "liveness_known": False, "detail": "phone.paired via caelestia-connectd"}})
    assert "phone: paired — presence unknown" in paired["tooltip"]
    assert paired["class"] == ["listening"]                # no new class token invented

    connected = format_waybar({**base, "device_presence": {
        "paired": True, "link_up": True, "phone_connected": True, "source": "event",
        "liveness_known": True, "detail": "ping.ping"}})
    assert "phone: connected — liveness seen via ping.ping" in connected["tooltip"]
    assert connected["class"] == ["listening"]
    assert connected["text"] == format_waybar(base)["text"]  # the pill's face unchanged


def test_the_follow_stream_needs_no_new_refresh_path():
    from assistant import waybar
    assert "immediately on daemon events" in (waybar.stream_waybar.__doc__ or "")
    body = (REPO / "src/assistant/waybar.py").read_text()
    assert body.count("yield format_waybar(_safe_status(socket_path))") == 3


# ---------------------------------------------------------------------------
# the posture seam and the clock seam (unchanged guarantees)
# ---------------------------------------------------------------------------
def test_no_phone_signal_can_touch_posture():
    store = FakeStore()
    svc = service(store=store)
    before = svc.status(now=T0).as_dict()
    for event in ("phone.paired", "phone.unpaired", "phone.revoked"):
        svc.apply_event({"event": event}, now=T0)
    svc.apply_liveness(link_up=True, now=T0)
    assert svc.status(now=T0).as_dict() == before
    assert set(store.writes) == {DEVICE_STATE_KEY}


def test_toggle_writes_only_the_posture_key():
    store = FakeStore()
    svc = service(store=store)
    svc.set_enabled(True)
    assert store.writes == [STATE_KEY]
    assert svc.status(now=T0).knock_style == "silent-visual"


def test_a_numeric_or_absent_clock_still_works():
    """All 16 existing construction sites use `PresenceService(config, store)`, and
    the daemon may hand epoch seconds; neither may crash a surface."""
    svc = service(clock=lambda: T0.timestamp() + 10)
    snap = svc.snapshot(now=T0.timestamp() + 10)
    assert snap["device_presence"]["source"] == "absent"
    plain = PresenceService(FakeConfig(), FakeStore())
    assert plain.device().source == "absent"
    assert plain.schedule_match() is None


def test_a_real_schedule_window_still_suggests():
    """Device-presence must not have eaten the class-mode suggestion it was built beside."""
    config = FakeConfig({"class_schedule": [
        {"days": ["thu"], "start": "11:00", "end": "13:00", "label": "lecture block"}]})
    assert service(config=config).schedule_match(T0)["label"] == "lecture block"
    numeric = service(config=config, clock=lambda: T0.timestamp())
    assert numeric.status().suggested is True


def test_presence_opens_no_socket_and_spawns_nothing():
    """Device-presence is a store read + a dict. If it grows connect() or a
    subprocess it has become a second sidecar, and this lane is the wrong place
    for that (the adapter is E's, and IF-3 keeps it out of this tree)."""
    src = (REPO / "src/assistant/presence.py").read_text()
    for banned in ("socket", "subprocess", "httpx", "requests", ".connect(", "Popen",
                   "caelestia", "phone_link"):
        assert banned not in src, f"presence.py reached for {banned}"
