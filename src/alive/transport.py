"""Messaging transports for the alive host.

This is the ONLY module in the package permitted to open an HTTP connection,
and it may only ever open one to a host on ``EGRESS_ALLOWLIST`` — anything
else raises before a packet leaves. The two sends that exist:

* ``send_service_reply`` — a free-form reply inside the 24 h window the
  user's own message opened (stranger concierge replies, owner acks). The
  only caller is the webhook handler, in the same request cycle as the
  inbound message. Never used to initiate.
* ``send_utility_template`` — a business-initiated approved utility
  template (``reminder_v1``). The ONLY business-initiated send in the
  system, and it is capped per day in code at the call site
  (``max_templates_per_day``) and again here as a belt-and-braces check.

Meta policy posture: no LLM, no general-purpose assistant, S-0 templates
only for business-initiated sends. A ``PLATFORM_BLOCKED``-class error is
TERMINAL: the layer stops sending, journals it, and waits for the owner.
There is no retry through another number, no proxy, no evasion — ever.

Tests use ``FakeTransport`` only. ``WhatsAppCloudTransport`` is exercised
in the sandbox with an injected ``http_client`` double, never a network.
"""

from __future__ import annotations

from urllib.parse import urlparse
from datetime import UTC, datetime

from .journal import log_event
from .envelope import from_hash
from .store import AliveStore
from .templates import TEMPLATES

from .config import EGRESS_ALLOWLIST, GRAPH_API_VERSION, AliveConfig


class TransportError(RuntimeError):
    pass


class TemplateCapReached(TransportError):
    pass


class EgressRefused(TransportError):
    """A non-allowlisted host was named. This is a bug or an attack; no
    packet leaves."""


class PlatformBlocked(TransportError):
    """Meta restricted the account/number (PLATFORM_BLOCKED-class).

    Terminal. The layer stops sending, journals it, and waits for the owner.
    Never retried through another number, never proxied.
    """


def assert_egress_allowed(url: str) -> str:
    host = urlparse(url).hostname or ""
    if host not in EGRESS_ALLOWLIST:
        raise EgressRefused(
            f"refusing to open HTTP to {host!r}: egress allowlist is {EGRESS_ALLOWLIST}")
    return host


def _raise_for_status(status: int, payload) -> None:
    if status < 400:
        return
    error = (payload or {}).get("error", {}) if isinstance(payload, dict) else {}
    code = error.get("code")
    subcode = error.get("error_subcode")
    message = str(error.get("message", ""))
    # Account-level restriction shapes: (#10) permission, (#190) token,
    # (#131031) account restricted, or an explicit platform block. Treat
    # anything 401/403 and the known restriction codes as terminal.
    blocked_codes = {10, 190, 131031, 131047, 131049, 368}
    if status in (401, 403) or code in blocked_codes or "block" in message.lower():
        raise PlatformBlocked(f"Meta refused ({status}, code={code}, subcode={subcode}): {message}")
    raise TransportError(f"WhatsApp API error ({status}, code={code}): {message}")


class WhatsAppCloudTransport:
    """S-0 transport: service replies in-window; utility templates outbound.

    ``http_client`` is an injectable callable ``(method, url, headers,
    json_body) -> (status:int, json:dict)``. The default uses urllib and
    is only ever invoked with an allowlisted URL.
    """

    def __init__(self, config: AliveConfig, *, store=None, http_client=None, clock=None):
        self.config = config
        self.store = store or AliveStore(config.state_dir)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._http = http_client or self._default_http

    @property
    def name(self) -> str:
        return "whatsapp_cloud"

    def _base(self) -> str:
        return f"https://graph.facebook.com/{GRAPH_API_VERSION}/{self.config.wa_phone_number_id}/messages"

    def _default_http(self, method, url, headers, json_body):
        import json as _json
        import urllib.request
        assert_egress_allowed(url)  # hard gate, even for the default client
        data = _json.dumps(json_body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise EgressRefused("HTTP redirect refused")
        try_opener = urllib.request.build_opener(NoRedirect())
        try:
            with try_opener.open(req, timeout=15) as resp:
                return resp.status, _json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                payload = _json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:
                payload = {}
            return exc.code, payload

    def _send(self, body: dict) -> dict:
        url = self._base()
        assert_egress_allowed(url)
        if not self.config.wa_token:
            raise TransportError("wa_token not provisioned")
        headers = {"Authorization": f"Bearer {self.config.wa_token}",
                   "Content-Type": "application/json"}
        status, payload = self._http("POST", url, headers, body)
        _raise_for_status(status, payload)
        return payload if isinstance(payload, dict) else {}

    def send_service_reply(self, to_e164: str, text: str) -> dict:
        """In-window reply. Caller MUST be answering an inbound message.

        In-window replies are the counterpart of a conversation the other
        party opened, so any counterpart may be addressed here — but this
        verified inbound timestamp is recorded by the signed webhook and
        checked at this boundary; no timestamp means no free-form send.
        """
        if self.store.platform_blocked():
            raise PlatformBlocked("line is blocked; owner action required")
        try:
            last = int(self.store.kv_get("window:" + from_hash(to_e164, self.config.from_hash_salt), ""))
            age = self._clock().timestamp() - last
        except (TypeError, ValueError):
            age = -1
        if not 0 <= age < 24 * 60 * 60:
            raise EgressRefused("no verified inbound message within the 24-hour window")
        body = {"messaging_product": "whatsapp", "to": to_e164,
                "type": "text", "text": {"body": text[:4096]}}
        log_event(self.config.state_dir, "service_attempt")
        try:
            response = self._send(body)
        except Exception:
            log_event(self.config.state_dir, "service_unknown", level="warn")
            raise
        log_event(self.config.state_dir, "service_accepted")
        return response

    def send_utility_template(self, to_e164: str, template: str, params: list[str]) -> dict:
        """Business-initiated send. ONLY the owner's number is addressable."""
        if to_e164 != self.config.owner_e164:
            raise EgressRefused(
                "utility templates may only be addressed to the single configured "
                "owner number; refusing")
        if template not in TEMPLATES or len(params) != TEMPLATES[template][1]:
            raise EgressRefused("unknown template or incorrect parameter count")
        if self.store.platform_blocked():
            raise PlatformBlocked("line is blocked; owner action required")
        attempt = self.store.reserve_template(template, self.config.max_templates_per_day,
                                              self._clock())
        if attempt is None:
            log_event(self.config.state_dir, "template_cap_reached", template=template)
            raise TemplateCapReached("daily template attempt cap reached")
        log_event(self.config.state_dir, "template_attempt", attempt=attempt, template=template)
        body = {"messaging_product": "whatsapp", "to": to_e164,
                "type": "template",
                "template": {"name": template, "language": {"code": "en"},
                             "components": [{"type": "body", "parameters": [
                                 {"type": "text", "text": str(p)[:200]} for p in params]}]}}
        try:
            response = self._send(body)
            wamid = response.get("messages", [{}])[0].get("id")
            if not wamid:
                raise TransportError("Meta response missing message id; outcome unknown")
            self.store.finish_template(attempt, "accepted", wamid)
            log_event(self.config.state_dir, "template_accepted", attempt=attempt, wamid=wamid)
            return response
        except Exception as exc:
            self.store.finish_template(attempt, "unknown")
            if isinstance(exc, PlatformBlocked):
                self.store.kv_set("platform_blocked", "1")
            log_event(self.config.state_dir, "template_unknown", level="error", attempt=attempt)
            if isinstance(exc, TransportError):
                raise
            raise TransportError("template send outcome unknown") from exc



class FakeTransport:
    """Test double. Records every send; can be armed to fail.

    ``fail_with`` may be ``PlatformBlocked`` or ``TransportError`` or a string.
    """

    def __init__(self):
        self.sent: list[dict] = []
        self.fail_with: Exception | None = None

    @property
    def name(self) -> str:
        return "fake"

    def _maybe_fail(self):
        if self.fail_with is not None:
            raise self.fail_with

    def send_service_reply(self, to_e164: str, text: str) -> dict:
        self._maybe_fail()
        self.sent.append({"kind": "service_reply", "to": to_e164, "text": text})
        return {"messages": [{"id": f"wamid.fake{len(self.sent)}"}]}

    def send_utility_template(self, to_e164: str, template: str, params: list[str]) -> dict:
        self._maybe_fail()
        self.sent.append({"kind": "template", "to": to_e164,
                          "template": template, "params": list(params)})
        return {"messages": [{"id": f"wamid.fake{len(self.sent)}"}]}
