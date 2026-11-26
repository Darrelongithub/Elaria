"""BUILD-10 eye-checks — Real WhatsApp Cloud API transport + S-0 template pack + Meta webhook fixtures.

Evidence labels: every test here is [TESTED] in sandbox against injected HTTP
doubles and Meta-documented webhook payload fixtures (cited below). ZERO live
network calls leave the sandbox; real Meta registration on the owner's spare
SIM is the owner's step in ``reports/RPT-E-whatsapp-runbook-*.md``.

Cited Meta Cloud API documentation shapes:
1. Inbound text / audio / interactive / button / reaction webhooks:
   https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks/
   https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-reply-buttons-messages/
   https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/button/
2. Outbound text & template message request/response syntax:
   https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages/
3. Delivery status receipts (sent / delivered / read / failed + pricing) & error codes (#131047, #131031, #190):
   https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids/
   https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes/
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from alive import envelope as envelope_mod
from alive import journal, provision, reminders, webhook
from alive.config import (
    DEFAULT_MAX_TEMPLATES_PER_DAY,
    EST_TEMPLATE_COST_KES_CENTS,
    GRAPH_API_VERSION,
    AliveConfig,
    AliveConfigError,
    load_config,
    normalise_e164,
)
from alive.store import AliveStore
from alive.sync import FixtureSyncBackend
from alive.templates import (
    S0_TEMPLATE_PACK,
    TEMPLATE_ALREADY_SENT_KNOCK,
    TEMPLATE_COMMITMENT_DUE,
    TEMPLATE_DEADLINE,
    TEMPLATE_MEETING,
    TemplateSpec,
    TemplateSpecError,
    format_laptop_already_sent_knock,
    resolve_template,
    select_template_for_item,
    validate_template_spec,
)
from alive.transport import (
    EgressRefused,
    FakeTransport,
    OutsideServiceWindow,
    PlatformBlocked,
    WhatsAppCloudTransport,
)
from assistant import alive_sync
from assistant.offline_queue import CloudQueue
from assistant.store import Store

NOW = datetime(2026, 11, 26, 8, 0, 0, tzinfo=UTC)
NOW_TS = int(NOW.timestamp())

OWNER_E164 = "+254711000111"
OWNER_WA_ID = "254711000111"  # Meta sends wa_id / messages[].from as digits WITHOUT '+'
STRANGER_WA_ID = "254722000222"
PHONE_NUMBER_ID = "106540352242922"
WABA_ID = "102290129340398"
MAC_KEY = "test-mac-key-0123456789abcdef0123456789abcdef"
SALT = "test-salt-0123456789abcdef"
APP_SECRET = "meta-app-secret-test"
WA_TOKEN = "EAAGtestSystemUserToken"


class RecordingGraphHTTP:
    """In-memory double for Meta's ``https://graph.facebook.com/v21.0/<PHONE_NUMBER_ID>/messages``."""

    def __init__(self):
        self.calls: list[dict] = []
        self.next_response: tuple[int, dict] | None = None

    def __call__(self, method: str, url: str, headers: dict, json_body: dict):
        self.calls.append({
            "method": method,
            "url": url,
            "headers": dict(headers),
            "body": json.loads(json.dumps(json_body)),
        })
        if self.next_response is not None:
            resp = self.next_response
            self.next_response = None
            return resp
        to_digits = str(json_body.get("to", "")).lstrip("+")
        return 200, {
            "messaging_product": "whatsapp",
            "contacts": [{"input": json_body.get("to"), "wa_id": to_digits}],
            "messages": [{"id": f"wamid.HBgM{len(self.calls):06d}", "message_status": "accepted"}],
        }


def make_env(tmp_path: Path, **cfg_over):
    base = {
        "mac_key": MAC_KEY,
        "from_hash_salt": SALT,
        "owner_e164": OWNER_E164,
        "wa_phone_number_id": PHONE_NUMBER_ID,
        "wa_token": WA_TOKEN,
        "wa_app_secret": APP_SECRET,
        "verify_token": "verify-runbook-token",
        "state_dir": tmp_path / "alive-state",
    }
    base.update(cfg_over)
    config = AliveConfig(**base)
    store = AliveStore(config.state_dir)
    backend = FixtureSyncBackend(tmp_path / "sync-remote")
    http = RecordingGraphHTTP()
    transport = WhatsAppCloudTransport(config, store=store, http_client=http)
    return config, store, backend, transport, http


def post_signed_webhook(config, store, backend, transport, payload: dict, *, now: datetime = NOW):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(APP_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    headers = {
        "X-Hub-Signature-256": f"sha256={sig}",
        "Content-Type": "application/json",
    }
    return webhook.handle_request(
        "POST", headers, raw,
        config=config, store=store, backend=backend,
        transport=transport, now=now,
    )


# ==============================================================================
# 1. S-0 template pack validation & Meta payload shapes
# ==============================================================================

def test_s0_template_pack_contains_exact_four_approved_shapes():
    assert set(S0_TEMPLATE_PACK) == {
        TEMPLATE_MEETING,
        TEMPLATE_DEADLINE,
        TEMPLATE_COMMITMENT_DUE,
        TEMPLATE_ALREADY_SENT_KNOCK,
    }
    for spec in S0_TEMPLATE_PACK.values():
        validate_template_spec(spec)
        sub = spec.meta_submission_payload()
        assert sub["category"] == "UTILITY"
        assert sub["language"] == "en"
        body_comp = sub["components"][0]
        assert body_comp["type"] == "BODY"
        assert len(body_comp["example"]["body_text"][0]) == spec.param_count
        # Render preview works with sample params and has no leftover braces
        preview = spec.render_preview(spec.sample_params)
        assert "{{" not in preview and "}}" not in preview


@pytest.mark.parametrize("bad_kwargs,match", [
    ({"name": "BadUpperCase"}, "invalid Meta template name"),
    ({"category": "MARKETING"}, "must be UTILITY"),
    ({"body": "{{1}} at the start of the body for {{2}}."}, "starts or ends with a variable"),
    ({"body": "Starts fine for {{1}} but ends with {{2}}"}, "starts or ends with a variable"),
    ({"body": "Adjacent vars {{1}} {{2}} are rejected."}, "adjacent variables"),
    ({"body": "Skipped index {{1}} and {{3}} here."}, "sequential"),
    ({"body": "Special sale discount on {{1}} at {{2}}."}, "promotional"),
    ({"body": "I miss you! Remember {{1}} at {{2}}."}, "anti-psychosis"),
    ({"sample_params": ("test", "09:00 EAT")}, "placeholder-like sample"),
])
def test_template_validator_catches_meta_and_elaria_violations(bad_kwargs, match):
    base = S0_TEMPLATE_PACK[TEMPLATE_MEETING]
    mutated = TemplateSpec(
        kind=base.kind,
        name=bad_kwargs.get("name", base.name),
        language=bad_kwargs.get("language", base.language),
        category=bad_kwargs.get("category", base.category),
        body=bad_kwargs.get("body", base.body),
        footer=bad_kwargs.get("footer", base.footer),
        param_names=bad_kwargs.get("param_names", base.param_names),
        sample_params=bad_kwargs.get("sample_params", base.sample_params),
        description=base.description,
    )
    with pytest.raises(TemplateSpecError, match=match):
        validate_template_spec(mutated)


def test_template_selection_covers_meeting_deadline_commitment_and_knock():
    assert select_template_for_item(topic="Team meeting with Amina").name == TEMPLATE_MEETING
    assert select_template_for_item(
        topic="Lab report", due="2026-11-27T17:00:00Z").name == TEMPLATE_DEADLINE
    assert select_template_for_item(topic="Water the plants").name == TEMPLATE_COMMITMENT_DUE
    assert select_template_for_item(
        topic="Team meeting with Amina",
        already_sent_at="2026-11-26T06:55:00Z",
    ).name == TEMPLATE_ALREADY_SENT_KNOCK
    # Legacy BUILD-6 alias resolves cleanly
    assert resolve_template("reminder_v1").name == TEMPLATE_COMMITMENT_DUE


def test_template_param_sanitisation_strips_newlines_and_rejects_empty():
    spec = S0_TEMPLATE_PACK[TEMPLATE_MEETING]
    payload = spec.graph_send_payload(OWNER_E164, ["meeting\nwith\tAmina   now", "19:00 EAT"])
    params = payload["template"]["components"][0]["parameters"]
    assert params[0] == {"type": "text", "text": "meeting with Amina now"}
    assert params[1] == {"type": "text", "text": "19:00 EAT"}
    with pytest.raises(TemplateSpecError):
        spec.graph_send_payload(OWNER_E164, ["   ", "19:00 EAT"])


# ==============================================================================
# 2. Outside-24h-window rule: free-form cold send MUST be impossible
# ==============================================================================

def test_cold_freeform_send_is_impossible_without_24h_window(tmp_path):
    config, _store, _backend, transport, http = make_env(tmp_path)
    with pytest.raises(OutsideServiceWindow, match="no open 24h customer service window"):
        transport.send_service_reply(OWNER_E164, "Hey, remember meeting at 7", now=NOW)
    # Zero HTTP packets left the adapter
    assert http.calls == []
    events = [e["event"] for e in journal.read_events(config.state_dir)]
    assert "cold_freeform_refused" in events


def test_expired_24h_window_blocks_freeform_at_24h_plus_one_second(tmp_path):
    _config, store, _backend, transport, http = make_env(tmp_path)
    owner_hash = envelope_mod.from_hash(OWNER_E164, SALT)
    store.record_inbound_window(owner_hash, NOW)

    # Inside window (23h 59m 59s later): free-form reply succeeds, 0 KES-cents
    inside = NOW + timedelta(hours=23, minutes=59, seconds=59)
    resp = transport.send_service_reply(OWNER_E164, "Still inside window", now=inside)
    assert resp["messages"][0]["id"].startswith("wamid.")
    assert len(http.calls) == 1
    assert http.calls[0]["url"] == f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    assert http.calls[0]["body"] == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": OWNER_E164,
        "type": "text",
        "text": {"preview_url": False, "body": "Still inside window"},
    }

    # Outside window (24h + 1s later): free-form send is IMPOSSIBLE, only template works
    outside = NOW + timedelta(hours=24, seconds=1)
    with pytest.raises(OutsideServiceWindow):
        transport.send_service_reply(OWNER_E164, "Late free-form attempt", now=outside)
    assert len(http.calls) == 1  # no second HTTP call made

    # Template send outside 24h succeeds with exact Meta Cloud API template body
    t_resp = transport.send_utility_template(
        OWNER_E164,
        TEMPLATE_MEETING,
        ["project sync with Amina", "19:00 EAT"],
        now=outside,
    )
    assert t_resp["messages"][0]["id"].startswith("wamid.")
    assert len(http.calls) == 2
    assert http.calls[1]["body"] == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": OWNER_E164,
        "type": "template",
        "template": {
            "name": "elaria_meeting_v1",
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": "project sync with Amina"},
                        {"type": "text", "text": "19:00 EAT"},
                    ],
                }
            ],
        },
    }


def test_fake_transport_also_enforces_24h_window_and_template_pack(tmp_path):
    config, store, _backend, _real_transport, _http = make_env(tmp_path)
    fake = FakeTransport(config=config, store=store, enforce_window=True)
    with pytest.raises(OutsideServiceWindow):
        fake.send_service_reply(OWNER_E164, "cold send", now=NOW)
    with pytest.raises(TemplateSpecError):
        fake.send_utility_template(OWNER_E164, "unregistered_template", ["a", "b"], now=NOW)


def test_meta_131047_error_maps_to_outside_window_not_platform_blocked(tmp_path):
    _config, store, _backend, transport, http = make_env(tmp_path)
    owner_hash = envelope_mod.from_hash(OWNER_E164, SALT)
    store.record_inbound_window(owner_hash, NOW)
    http.next_response = (400, {
        "error": {
            "message": "(#131047) Re-engagement message",
            "type": "OAuthException",
            "code": 131047,
            "error_data": {
                "messaging_product": "whatsapp",
                "details": "Message failed to send because more than 24 hours have passed since the customer last replied to this number.",
            },
            "fbtrace_id": "AbCdEfGhIjK",
        }
    })
    with pytest.raises(OutsideServiceWindow, match="131047"):
        transport.send_service_reply(OWNER_E164, "edge of window", now=NOW + timedelta(hours=23))
    # Account is NOT marked platform_blocked on a 24h-window expiry
    assert store.platform_blocked() is False


def test_meta_190_or_131031_error_maps_to_terminal_platform_blocked(tmp_path):
    _config, _store, _backend, transport, http = make_env(tmp_path)
    http.next_response = (401, {
        "error": {
            "message": "Error validating access token: Session has expired",
            "type": "OAuthException",
            "code": 190,
            "error_subcode": 463,
        }
    })
    with pytest.raises(PlatformBlocked, match="code=190"):
        transport.send_utility_template(
            OWNER_E164, TEMPLATE_COMMITMENT_DUE, ["call dentist", "10:00 EAT"], now=NOW)


def test_non_https_or_wrong_host_refused_before_socket():
    from alive.transport import assert_egress_allowed
    with pytest.raises(EgressRefused):
        assert_egress_allowed("http://graph.facebook.com/v21.0/123/messages")
    with pytest.raises(EgressRefused):
        assert_egress_allowed("https://api.whatsapp.com/send")


# ==============================================================================
# 3. Meta documented webhook payload fixtures (wa_id without '+', statuses, buttons, etc.)
# ==============================================================================

def test_documented_meta_inbound_text_fixture_without_plus_matches_owner_t0(tmp_path):
    """Meta Cloud API sends ``contacts[].wa_id`` and ``messages[].from`` as bare
    digits WITHOUT '+' (e.g. ``'254711000111'``), while ``owner_e164`` is ``'+254711000111'``.
    Cited: https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks/
    """
    config, store, backend, transport, http = make_env(tmp_path)
    fixture = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA_ID,
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "254799000999",
                                "phone_number_id": PHONE_NUMBER_ID,
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Owner"},
                                    "wa_id": OWNER_WA_ID,  # no leading '+'
                                }
                            ],
                            "messages": [
                                {
                                    "from": OWNER_WA_ID,   # no leading '+'
                                    "id": "wamid.HBgMMjU0NzExMDAwMTExFQIAEhgUM0E0QTY1OTlBRUUwMzgxMDE0NEY=",
                                    "timestamp": str(NOW_TS),
                                    "type": "text",
                                    "text": {"body": "Remind me to bring the lab kit tomorrow"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    status, body = post_signed_webhook(config, store, backend, transport, fixture)
    assert status == 200 and body == b"EVENT_RECEIVED"

    # Queued as T0 owner instruction (NOT stranger_turn!) and normalises from_hash to +254711000111
    names = backend.list("inbox")
    assert len(names) == 1
    env, err = envelope_mod.load_verified(names[0], backend.get("inbox", names[0]), MAC_KEY)
    assert err is None and env is not None
    assert env["kind"] == "instruction"
    assert env["from_hash"] == envelope_mod.from_hash(OWNER_E164, SALT)

    # Real WhatsAppCloudTransport sent one in-window free-form session ack to +254711000111
    assert len(http.calls) == 1
    assert http.calls[0]["body"]["type"] == "text"
    assert http.calls[0]["body"]["to"] == OWNER_E164
    assert "nothing happens until it's on" in http.calls[0]["body"]["text"]["body"]


def test_documented_meta_status_receipt_fixture_delivered_and_failed(tmp_path):
    """Meta status callback fixture (sent / delivered / read / failed with pricing).
    Cited: https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids/
    """
    config, store, backend, transport, http = make_env(tmp_path)
    status_fixture = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA_ID,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "254799000999",
                                "phone_number_id": PHONE_NUMBER_ID,
                            },
                            "statuses": [
                                {
                                    "id": "wamid.HBgM000001",
                                    "status": "delivered",
                                    "timestamp": str(NOW_TS),
                                    "recipient_id": OWNER_WA_ID,
                                    "conversation": {
                                        "id": "conv_abc",
                                        "origin": {"type": "utility"},
                                    },
                                    "pricing": {
                                        "billable": True,
                                        "pricing_model": "PMP",
                                        "category": "utility",
                                        "type": "regular",
                                    },
                                },
                                {
                                    "id": "wamid.HBgM000002",
                                    "status": "failed",
                                    "timestamp": str(NOW_TS + 5),
                                    "recipient_id": OWNER_WA_ID,
                                    "errors": [
                                        {
                                            "code": 131047,
                                            "title": "Re-engagement message",
                                            "href": "https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes/",
                                        }
                                    ],
                                },
                            ],
                        },
                    }
                ],
            }
        ],
    }
    status, _ = post_signed_webhook(config, store, backend, transport, status_fixture)
    assert status == 200
    assert backend.list("inbox") == []   # status callbacks never create inbox envelopes
    assert http.calls == []              # status callbacks never send replies
    rows_1 = store.delivery_statuses_for("wamid.HBgM000001")
    assert len(rows_1) == 1 and rows_1[0]["status"] == "delivered" and rows_1[0]["billable"] == 1
    rows_2 = store.delivery_statuses_for("wamid.HBgM000002")
    assert len(rows_2) == 1 and rows_2[0]["error_code"] == 131047
    assert store.platform_blocked() is False


def test_documented_meta_interactive_button_and_reaction_fixtures(tmp_path):
    """Interactive button_reply, template quick-reply button, and reaction payloads.
    Cited:
    - https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-reply-buttons-messages/
    - https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/button/
    """
    config, store, backend, transport, _http = make_env(tmp_path)

    # 1) Template quick-reply button click -> queued as text instruction
    button_fixture = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": WABA_ID,
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "254799000999",
                                 "phone_number_id": PHONE_NUMBER_ID},
                    "contacts": [{"profile": {"name": "Owner"}, "wa_id": OWNER_WA_ID}],
                    "messages": [{
                        "context": {"from": "254799000999", "id": "wamid.prev"},
                        "from": OWNER_WA_ID,
                        "id": "wamid.btn1",
                        "timestamp": str(NOW_TS),
                        "type": "button",
                        "button": {"payload": "SNOOZE_1H", "text": "Snooze 1 hour"},
                    }],
                },
            }],
        }],
    }
    post_signed_webhook(config, store, backend, transport, button_fixture)

    # 2) Interactive button_reply -> queued as text instruction
    interactive_fixture = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": WABA_ID,
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "254799000999",
                                 "phone_number_id": PHONE_NUMBER_ID},
                    "contacts": [{"profile": {"name": "Owner"}, "wa_id": OWNER_WA_ID}],
                    "messages": [{
                        "context": {"from": "254799000999", "id": "wamid.prev2"},
                        "from": OWNER_WA_ID,
                        "id": "wamid.inter1",
                        "timestamp": str(NOW_TS + 1),
                        "type": "interactive",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {"id": "reschedule-8pm", "title": "Move to 8pm"},
                        },
                    }],
                },
            }],
        }],
    }
    post_signed_webhook(config, store, backend, transport, interactive_fixture)

    # 3) Emoji reaction -> ignored cleanly (no junk envelope, no error)
    reaction_fixture = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": WABA_ID,
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "254799000999",
                                 "phone_number_id": PHONE_NUMBER_ID},
                    "contacts": [{"profile": {"name": "Owner"}, "wa_id": OWNER_WA_ID}],
                    "messages": [{
                        "from": OWNER_WA_ID,
                        "id": "wamid.react1",
                        "timestamp": str(NOW_TS + 2),
                        "type": "reaction",
                        "reaction": {"message_id": "wamid.prev2", "emoji": "👍"},
                    }],
                },
            }],
        }],
    }
    post_signed_webhook(config, store, backend, transport, reaction_fixture)

    names = backend.list("inbox")
    assert len(names) == 2  # button + interactive queued; reaction ignored
    bodies = [
        envelope_mod.load_verified(n, backend.get("inbox", n), MAC_KEY)[0]["body"]
        for n in names
    ]
    assert bodies == ["Snooze 1 hour", "Move to 8pm"]


def test_wrong_phone_number_id_or_non_messages_field_ignored(tmp_path):
    config, store, backend, transport, http = make_env(tmp_path)
    wrong_phone = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": WABA_ID,
            "changes": [
                {
                    "field": "message_template_status_update",
                    "value": {"event": "APPROVED", "message_template_name": TEMPLATE_MEETING},
                },
                {
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "999999999999999"},
                        "messages": [{
                            "from": OWNER_WA_ID,
                            "id": "wamid.other_number",
                            "timestamp": str(NOW_TS),
                            "type": "text",
                            "text": {"body": "wrong phone number id"},
                        }],
                    },
                },
            ],
        }],
    }
    status, _ = post_signed_webhook(config, store, backend, transport, wrong_phone)
    assert status == 200
    assert backend.list("inbox") == []
    assert http.calls == []


# ==============================================================================
# 4. Cost guard: small default cap, KES-cents arithmetic, journaled per send, S-1 OFF
# ==============================================================================

def test_default_paid_template_cap_is_small_and_s1_chatty_mode_refused(tmp_path):
    config, *_ = make_env(tmp_path)
    assert config.max_templates_per_day == DEFAULT_MAX_TEMPLATES_PER_DAY == 5
    assert config.s1_chatty_mode is False

    with pytest.raises(AliveConfigError, match="s1_chatty_mode is refused"):
        make_env(tmp_path / "s1", s1_chatty_mode=True)

    cfg_file = tmp_path / "s1.toml"
    cfg_file.write_text(
        f'[alive]\nmac_key = "{MAC_KEY}"\nfrom_hash_salt = "{SALT}"\n'
        f'owner_e164 = "{OWNER_E164}"\nresponder_mode = "S-1"\n'
    )
    with pytest.raises(AliveConfigError, match="S-1 chatty mode stays OFF"):
        load_config(cfg_file)


def test_paid_templates_journaled_per_send_in_kes_cents_and_capped(tmp_path):
    config, store, backend, transport, http = make_env(tmp_path, max_templates_per_day=2)
    t1 = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    t2 = (NOW + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Export 3 due items (meeting, deadline, second knock on the meeting)
    mirror_body = {
        "v": 1,
        "kind": "commitments",
        "generated_at": t1,
        "laptop_seq": 1,
        "items": [
            {
                "id": 10,
                "topic": "Meeting with supervisor",
                "due": "2026-11-26T10:00:00Z",
                "remind_at": [t1, t2],
                "origin": "user-request",
                "knock_id": 1,
                "content_free": False,
            },
            {
                "id": 11,
                "topic": "Submit OS project",
                "due": "2026-11-26T17:00:00Z",
                "remind_at": [t1],
                "origin": "user-request",
                "knock_id": 2,
                "content_free": False,
            },
        ],
    }
    signed = envelope_mod.sign(mirror_body, MAC_KEY)
    m_bytes = envelope_mod.envelope_bytes(signed)
    backend.put("commitments", envelope_mod.envelope_name(NOW, 1, m_bytes), m_bytes)

    # Tick 1 at NOW: fires meeting (#10 -> elaria_meeting_v1) + deadline (#11 -> elaria_deadline_v1)
    res1 = reminders.tick(backend=backend, config=config, store=store, transport=transport, now=NOW)
    assert res1["sent"] == 2 and res1["capped"] == 0
    assert http.calls[0]["body"]["template"]["name"] == TEMPLATE_MEETING
    assert http.calls[1]["body"]["template"]["name"] == TEMPLATE_DEADLINE

    # Tick 2 at NOW + 5m: cap=2 reached, so #10's second reminder is capped before HTTP
    res2 = reminders.tick(
        backend=backend, config=config, store=store, transport=transport,
        now=NOW + timedelta(minutes=5))
    assert res2["sent"] == 0 and res2["capped"] == 1
    assert len(http.calls) == 2

    # Check KES-cents journaling per send
    events = journal.read_events(config.state_dir)
    journaled = [e for e in events if e["event"] == "paid_template_journaled"]
    assert len(journaled) == 2
    assert journaled[0]["cost_kes_cents_est"] == EST_TEMPLATE_COST_KES_CENTS == 52
    assert journaled[0]["spent_kes_cents_today_est"] == 52
    assert journaled[1]["spent_kes_cents_today_est"] == 104
    assert any(e["event"] == "template_cap_reached" for e in events)


def test_second_reminder_uses_already_sent_knock_template_and_laptop_reads_log(tmp_path):
    config, store, backend, transport, http = make_env(tmp_path, max_templates_per_day=5)
    t1 = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    t2 = (NOW + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    mirror_body = {
        "v": 1,
        "kind": "commitments",
        "generated_at": t1,
        "laptop_seq": 1,
        "items": [{
            "id": 91,
            "topic": "Meeting with Amina",
            "due": "2026-11-26T19:00:00Z",
            "remind_at": [t1, t2],
            "origin": "user-request",
            "knock_id": 44,
            "content_free": False,
        }],
    }
    signed = envelope_mod.sign(mirror_body, MAC_KEY)
    m_bytes = envelope_mod.envelope_bytes(signed)
    backend.put("commitments", envelope_mod.envelope_name(NOW, 1, m_bytes), m_bytes)

    reminders.tick(backend=backend, config=config, store=store, transport=transport, now=NOW)
    reminders.tick(
        backend=backend, config=config, store=store, transport=transport,
        now=NOW + timedelta(hours=2))

    assert http.calls[0]["body"]["template"]["name"] == TEMPLATE_MEETING
    assert http.calls[1]["body"]["template"]["name"] == TEMPLATE_ALREADY_SENT_KNOCK
    assert http.calls[1]["body"]["template"]["components"][0]["parameters"] == [
        {"type": "text", "text": "Meeting with Amina"},
        {"type": "text", "text": t1},
    ]

    # Laptop side reads reminder_log and builds the short "already sent" knock line
    sync_cfg = alive_sync.AliveSyncConfig(
        state_dir=tmp_path / "laptop-sync",
        mac_key=MAC_KEY,
        from_hash_salt=SALT,
        owner_e164=OWNER_E164,
    )
    knock_line = alive_sync.already_sent_knock_for_commitment(
        backend, sync_cfg, commitment_id=91, topic="Meeting with Amina")
    assert knock_line is not None
    assert "Already sent to your phone at" in knock_line
    assert "Meeting with Amina" in knock_line


# ==============================================================================
# 5. Runbook end-to-end eye-check simulation (sandbox fixture)
# ==============================================================================

def test_runbook_eye_check_in_window_free_then_over_24h_template_knock(tmp_path):
    """Simulates the exact runbook eye-check sequence:
    1. Owner messages her number while laptop is off -> she answers in-window FREE;
    2. >24h silence passes -> free-form cold send is refused, S-0 template knock arrives;
    3. Laptop comes back on -> drains instruction into awaiting_approval.
    """
    config, store, backend, transport, http = make_env(tmp_path)

    # Step 1: Owner texts her number at T=0 while laptop is off
    inbound_payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": WABA_ID,
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "254799000999",
                                 "phone_number_id": PHONE_NUMBER_ID},
                    "contacts": [{"profile": {"name": "Owner"}, "wa_id": OWNER_WA_ID}],
                    "messages": [{
                        "from": OWNER_WA_ID,
                        "id": "wamid.eyecheck1",
                        "timestamp": str(NOW_TS),
                        "type": "text",
                        "text": {"body": "Queue reminder: submit thesis draft"},
                    }],
                },
            }],
        }],
    }
    status, _ = post_signed_webhook(config, store, backend, transport, inbound_payload, now=NOW)
    assert status == 200
    assert len(http.calls) == 1
    assert http.calls[0]["body"]["type"] == "text"  # free in-window session reply
    assert store.count_today("paid_template_kes_cents", tier="T0", now=NOW) == 0

    # Step 2: >24h silence (25 hours later)
    after_25h = NOW + timedelta(hours=25)
    with pytest.raises(OutsideServiceWindow):
        transport.send_service_reply(OWNER_E164, "Cold free-form ping", now=after_25h)

    remind_iso = after_25h.strftime("%Y-%m-%dT%H:%M:%SZ")
    mirror_body = {
        "v": 1,
        "kind": "commitments",
        "generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "laptop_seq": 2,
        "items": [{
            "id": 205,
            "topic": "submit thesis draft",
            "due": remind_iso,
            "remind_at": [remind_iso],
            "origin": "user-request",
            "knock_id": 12,
            "content_free": False,
        }],
    }
    signed = envelope_mod.sign(mirror_body, MAC_KEY)
    m_bytes = envelope_mod.envelope_bytes(signed)
    backend.put("commitments", envelope_mod.envelope_name(NOW, 2, m_bytes), m_bytes)

    tick_res = reminders.tick(
        backend=backend, config=config, store=store, transport=transport, now=after_25h)
    assert tick_res["sent"] == 1
    assert len(http.calls) == 2
    assert http.calls[1]["body"]["type"] == "template"
    assert http.calls[1]["body"]["template"]["name"] == TEMPLATE_DEADLINE
    assert store.count_today("paid_template_kes_cents", tier="T0", now=after_25h) == 52

    # Step 3: Laptop wakes up and drains the queued instruction into awaiting_approval
    laptop_store = Store(tmp_path / "assistant.db")
    queue = CloudQueue(config=None, store=laptop_store, client=None, mode_manager=None)
    sync_cfg = alive_sync.AliveSyncConfig(
        state_dir=tmp_path / "laptop-sync",
        mac_key=MAC_KEY,
        from_hash_salt=SALT,
        owner_e164=OWNER_E164,
    )
    sync_state = alive_sync.AliveSyncState(tmp_path / "laptop-sync")
    ingested = alive_sync.ingest(backend, queue, sync_cfg, sync_state, now=after_25h)
    assert len(ingested.queued) == 1
    jobs = laptop_store.list_cloud_jobs(status="awaiting_approval")
    assert len(jobs) == 1


def test_provision_templates_cli_outputs_valid_json(capsys):
    rc = provision.main(["templates"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert len(parsed) == 4
    assert {item["name"] for item in parsed} == set(S0_TEMPLATE_PACK)


def test_normalise_e164_handles_plus_and_bare_wa_id_and_rejects_junk():
    assert normalise_e164("+254711000111") == "+254711000111"
    assert normalise_e164("254711000111") == "+254711000111"
    with pytest.raises(AliveConfigError):
        normalise_e164("0711000111")  # national format with leading 0 rejected
    with pytest.raises(AliveConfigError):
        normalise_e164("not-a-number")
    assert format_laptop_already_sent_knock("Meeting", "06:55Z") == (
        "Already sent to your phone at 06:55Z: Meeting."
    )
