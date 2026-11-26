"""Cloud API shape and safety checks; no Meta account/network involved."""
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest

from alive.config import AliveConfig
from alive.store import AliveStore
from alive.sync import FixtureSyncBackend
from alive.transport import WhatsAppCloudTransport, EgressRefused, TemplateCapReached
from alive.webhook import handle_request
from alive.templates import TEMPLATES

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)
OWNER = "+254711000111"

@pytest.fixture
def setup(tmp_path):
    config = AliveConfig(mac_key="x" * 32, from_hash_salt="y" * 16,
                         owner_e164=OWNER, wa_phone_number_id="123456", wa_token="test",
                         wa_app_secret="secret", state_dir=tmp_path / "state",
                         max_templates_per_day=2)
    store = AliveStore(config.state_dir)
    sends = []
    def http(method, url, headers, body):
        sends.append((method, url, headers, body))
        return 200, {"messaging_product": "whatsapp", "messages": [{"id": "wamid.out"}]}
    transport = WhatsAppCloudTransport(config, store=store, http_client=http, clock=lambda: NOW)
    return config, store, FixtureSyncBackend(tmp_path / "remote"), transport, sends


def payload(ts, phone="123456", message_type="text"):
    message = {"from": OWNER[1:], "id": "wamid.in", "timestamp": str(ts),
               "type": message_type}
    if message_type == "text":
        message["text"] = {"body": "Hello"}
    else:
        message["image"] = {"id": "media-id", "mime_type": "image/jpeg"}
    return {"object": "whatsapp_business_account", "entry": [{"id": "waba", "changes": [
        {"field": "messages", "value": {"messaging_product": "whatsapp",
         "metadata": {"display_phone_number": "254700000000", "phone_number_id": phone},
         "contacts": [{"profile": {"name": "Owner"}, "wa_id": OWNER[1:]}],
         "messages": [message]}}]}]}


def post(setup, p):
    config, store, backend, tr, _ = setup
    raw = json.dumps(p).encode()
    sig = hmac.new(b"secret", raw, hashlib.sha256).hexdigest()
    return handle_request("POST", {"X-Hub-Signature-256": "sha256=" + sig}, raw,
                          config=config, store=store, backend=backend, transport=tr, now=NOW)


def test_real_meta_shape_owner_and_session_window(setup):
    config, store, _, tr, sends = setup
    with pytest.raises(EgressRefused):
        tr.send_service_reply(OWNER, "cold")
    assert post(setup, payload(int(NOW.timestamp())))[0] == 200
    assert sends[0][3]["type"] == "text"
    assert sends[0][3]["to"] == OWNER
    assert store.count_today("envelopes", now=NOW) == 1  # digits were normalized to owner
    tr._clock = lambda: NOW + timedelta(hours=24)
    with pytest.raises(EgressRefused):
        tr.send_service_reply(OWNER, "too late")
    tr.send_utility_template(OWNER, "meeting_reminder_v1", ["Review", "tomorrow"])
    assert sends[-1][3]["template"]["components"][0]["parameters"][0]["text"] == "Review"


def test_untrusted_timestamp_and_other_number_do_not_open_window(setup):
    _, _, _, tr, sends = setup
    assert post(setup, payload(int(NOW.timestamp()), phone="wrong"))[0] == 200
    with pytest.raises(EgressRefused): tr.send_service_reply(OWNER, "x")
    assert not sends
    assert post(setup, payload(int((NOW + timedelta(seconds=1)).timestamp())))[0] == 200
    with pytest.raises(EgressRefused): tr.send_service_reply(OWNER, "x")


def test_status_and_media_payloads(setup):
    p = payload(int(NOW.timestamp()), message_type="image")
    assert post(setup, p)[0] == 200
    assert setup[1].count_today("envelopes", now=NOW) == 1
    value = p["entry"][0]["changes"][0]["value"]
    value.pop("messages")
    value["statuses"] = [{"id": "wamid.out", "status": "delivered",
                          "recipient_id": OWNER[1:], "timestamp": str(int(NOW.timestamp()))}]
    assert post(setup, p)[0] == 200
    assert len(setup[4]) == 1


def test_attempts_are_atomic_persistent_and_unknown_consumes_cap(setup):
    config, store, _, tr, sends = setup
    def fail(*args): raise OSError("ambiguous timeout")
    tr._http = fail
    from alive.transport import TransportError
    with pytest.raises(TransportError): tr.send_utility_template(OWNER, "reminder_v1", ["x", "y"])
    tr._http = lambda *args: (200, {"messages": [{"id": "wamid.1"}]})
    other = WhatsAppCloudTransport(config, store=AliveStore(config.state_dir), http_client=tr._http,
                                   clock=lambda: NOW)
    def attempt(transport):
        try:
            transport.send_utility_template(OWNER, "reminder_v1", ["x", "y"])
            return "sent"
        except TemplateCapReached:
            return "capped"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [tr, other])) == ["capped", "sent"]
    rows = store._conn.execute("SELECT status FROM template_attempts ORDER BY id").fetchall()
    assert [r[0] for r in rows] == ["unknown", "accepted"]


def test_only_reviewed_templates_owner_and_expected_slots(setup):
    tr = setup[3]
    with pytest.raises(EgressRefused): tr.send_utility_template(OWNER, "anything", [])
    with pytest.raises(EgressRefused): tr.send_utility_template(OWNER, "reminder_v1", ["x"])
    with pytest.raises(EgressRefused): tr.send_utility_template("+254722000222", "reminder_v1", ["x", "y"])
    assert "already sent" in TEMPLATES["already_sent_knock_v1"][0]
