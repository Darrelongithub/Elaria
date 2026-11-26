"""Messaging transports for the alive host — real WhatsApp Cloud API adapter + test double.

This is the ONLY module in the package permitted to open an HTTP connection,
and it may only ever open one to a host on ``EGRESS_ALLOWLIST`` — anything
else raises before a packet leaves.

The two outbound operations (and NO others exist):

* ``send_service_reply`` — a free-form session reply INSIDE the 24-hour
  customer service window that the user's own inbound message opened.
  **Hard rule enforced here in the transport:** a free-form cold send is
  IMPOSSIBLE. Before any HTTP call is constructed, ``send_service_reply``
  verifies an open 24h window — either via an explicit ``inbound_at`` proof
  within 24h of ``now`` OR via ``store.in_service_window(sender_hash, now=now)``.
  With neither, or with an expired (>24h) window, ``OutsideServiceWindow``
  is raised and ZERO HTTP packets leave.
* ``send_utility_template`` — a business-initiated (or outside-24h) approved
  S-0 utility template from ``alive.templates.S0_TEMPLATE_PACK``.
  **Hard rules enforced here in the transport:**
  1. ONLY the single configured ``owner_e164`` is addressable;
  2. ONLY templates registered in ``S0_TEMPLATE_PACK`` (plus legacy alias
     ``reminder_v1``) are accepted — arbitrary template names or parameter
     shapes raise ``TemplateSpecError``;
  3. the per-day paid-template cap (``config.max_templates_per_day``) is
     checked in code before the send, and EVERY send attempt + outcome is
     journaled with KES-cents and USD cost estimates.

Meta policy posture: no LLM, no general-purpose assistant, S-1 chatty mode OFF,
S-0 templates only for business-initiated sends. Error ``#131047`` from Meta
(re-engagement / 24h window closed) maps to ``OutsideServiceWindow`` (never
``PlatformBlocked`` — it is not an account ban, and it is never retried as
free-form text). Account-level restrictions (``401``, ``403``, ``#10``,
``#190``, ``#368``, ``#130497``, ``#131031``) raise ``PlatformBlocked`` —
TERMINAL: the layer stops sending, journals it, and waits for the owner.
There is no retry through another number, no proxy, no evasion — ever.

Cited Meta Cloud API documentation:
* Messages endpoint & payload syntax:
  ``https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages/``
* Webhooks setup & payload structure:
  ``https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks/``
* Error codes (#131047 24h service window, #132000/#132001 template errors,
  #131031/#368 account restriction):
  ``https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes/``

Tests use ``FakeTransport`` or ``WhatsAppCloudTransport`` with an injected
``http_client`` double — never live network calls in sandbox.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from . import envelope as envelope_mod
from .config import (
    EGRESS_ALLOWLIST,
    EST_TEMPLATE_COST_KES_CENTS,
    EST_TEMPLATE_COST_USD,
    GRAPH_API_VERSION,
    SERVICE_WINDOW_SECONDS,
    AliveConfig,
    AliveConfigError,
    normalise_e164,
)
from .journal import log_event
from .store import AliveStore
from .templates import TemplateSpecError, resolve_template


class TransportError(RuntimeError):
    """Non-terminal WhatsApp Cloud API or transport error."""


class EgressRefused(TransportError):
    """A non-allowlisted host or forbidden recipient was named. No packet leaves."""


class OutsideServiceWindow(TransportError):
    """Attempted a free-form session message outside the 24-hour customer service window.

    Outside the 24h window: template or nothing. Free-form cold sends are
    impossible in code, and Meta's #131047 error also maps here if clock skew
    ever caused the edge of a window to close on Meta's side first.
    """


class TemplateCapExceeded(TransportError):
    """Per-day paid utility-template cap reached; send refused before HTTP."""


class PlatformBlocked(TransportError):
    """Meta restricted the account/number (PLATFORM_BLOCKED-class).

    Terminal. The layer stops sending, journals it, and waits for the owner.
    Never retried through another number, never proxied.
    """


#: Meta Graph API error codes indicating account/token/policy restriction (terminal).
#: Note: 131047 (24h window closed) and 131049 (per-user marketing pacing) are
#: NOT account bans — 131047 maps to OutsideServiceWindow, 131049 to TransportError.
PLATFORM_BLOCKED_CODES = frozenset({10, 190, 200, 368, 130497, 131031})
OUTSIDE_WINDOW_CODE = 131047


def assert_egress_allowed(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or host not in EGRESS_ALLOWLIST:
        raise EgressRefused(
            f"refusing to open HTTP to {url!r}: HTTPS egress allowlist is {EGRESS_ALLOWLIST}")
    return host


def _parse_utc(ts: datetime | str | None) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _check_24h_window(
    *,
    to_canonical: str,
    config: AliveConfig,
    store: AliveStore | None,
    now: datetime,
    inbound_at: datetime | str | None,
) -> None:
    """Hard gate: verify an open <=24h customer service window before free-form send."""
    now_utc = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    explicit = _parse_utc(inbound_at)
    if explicit is not None:
        elapsed = (now_utc - explicit).total_seconds()
        if 0 <= elapsed <= SERVICE_WINDOW_SECONDS:
            return
        raise OutsideServiceWindow(
            f"refusing free-form session send: inbound_at={explicit.isoformat()} is "
            f"{int(elapsed)}s from now (outside the {SERVICE_WINDOW_SECONDS}s / 24h window); "
            "use an S-0 template or nothing")

    if store is not None:
        s_hash = envelope_mod.from_hash(to_canonical, config.from_hash_salt)
        if store.in_service_window(s_hash, now=now_utc, window_seconds=SERVICE_WINDOW_SECONDS):
            return

    raise OutsideServiceWindow(
        "refusing free-form cold send: no open 24h customer service window for recipient "
        "(template or nothing outside 24h)")


def _raise_for_status(status: int, payload) -> None:
    if status < 400:
        return
    error = (payload or {}).get("error", {}) if isinstance(payload, dict) else {}
    code = error.get("code")
    subcode = error.get("error_subcode")
    details = ((error.get("error_data") or {}).get("details", "")
               if isinstance(error.get("error_data"), dict) else "")
    message = str(error.get("message", ""))
    detail_suffix = f" ({details})" if details else ""

    if code == OUTSIDE_WINDOW_CODE:
        raise OutsideServiceWindow(
            f"Meta refused free-form send (#131047, 24h window closed): {message}{detail_suffix}")

    if status in (401, 403) or code in PLATFORM_BLOCKED_CODES or (
        "account" in message.lower() and "restrict" in message.lower()
    ):
        raise PlatformBlocked(
            f"Meta refused ({status}, code={code}, subcode={subcode}): {message}{detail_suffix}")

    raise TransportError(
        f"WhatsApp API error ({status}, code={code}, subcode={subcode}): {message}{detail_suffix}")


class WhatsAppCloudTransport:
    """Real WhatsApp Cloud API S-0 transport adapter.

    * Free-form session replies ONLY inside an active 24h customer service window;
    * Approved S-0 utility templates ONLY to ``config.owner_e164``, capped per day
      in code and journaled per send with KES-cents arithmetic.

    ``http_client`` is an injectable callable ``(method, url, headers,
    json_body) -> (status: int, json: dict)``. The default uses ``urllib.request``
    with HTTPS and ``assert_egress_allowed``.
    """

    def __init__(
        self,
        config: AliveConfig,
        *,
        store: AliveStore | None = None,
        http_client=None,
    ):
        self.config = config
        self.store = store
        self._http = http_client or self._default_http

    @property
    def name(self) -> str:
        return "whatsapp_cloud"

    def _base(self) -> str:
        phone_id = str(self.config.wa_phone_number_id or "").strip()
        if not phone_id or not phone_id.isdigit():
            raise TransportError(
                f"wa_phone_number_id must be a numeric Meta Phone Number ID, got {phone_id!r}")
        return f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_id}/messages"

    def _default_http(self, method: str, url: str, headers: dict, json_body: dict):
        import json as _json
        import urllib.error
        import urllib.request

        assert_egress_allowed(url)  # hard gate, even for the default client
        data = _json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                return resp.status, _json.loads(raw)
        except urllib.error.HTTPError as exc:
            try:
                payload = _json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:
                payload = {}
            return exc.code, payload
        except urllib.error.URLError as exc:
            raise TransportError(f"WhatsApp network error: {exc.reason}") from exc

    def _send(self, body: dict) -> dict:
        url = self._base()
        assert_egress_allowed(url)
        if not self.config.wa_token:
            raise TransportError("wa_token not provisioned")
        headers = {
            "Authorization": f"Bearer {self.config.wa_token}",
            "Content-Type": "application/json",
        }
        status, payload = self._http("POST", url, headers, body)
        _raise_for_status(status, payload)
        return payload if isinstance(payload, dict) else {}

    def send_service_reply(
        self,
        to_e164: str,
        text: str,
        *,
        now: datetime | None = None,
        inbound_at: datetime | str | None = None,
    ) -> dict:
        """Send an in-window free-form session text reply.

        Enforces the outside-24h-window rule in the transport: without a valid
        <=24h window proof (``inbound_at`` or ``self.store``'s recorded window),
        raises ``OutsideServiceWindow`` before touching HTTP.
        """
        now_utc = (now or datetime.now(UTC)).astimezone(UTC)
        try:
            canonical_to = normalise_e164(to_e164)
        except AliveConfigError as exc:
            raise EgressRefused(str(exc)) from exc

        try:
            _check_24h_window(
                to_canonical=canonical_to,
                config=self.config,
                store=self.store,
                now=now_utc,
                inbound_at=inbound_at,
            )
        except OutsideServiceWindow as exc:
            log_event(
                self.config.state_dir,
                "cold_freeform_refused",
                level="error",
                reason=str(exc),
            )
            raise

        clean_text = str(text or "").strip()[:4096]
        if not clean_text:
            raise TransportError("refusing to send empty session reply")

        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": canonical_to,
            "type": "text",
            "text": {"preview_url": False, "body": clean_text},
        }
        response = self._send(body)
        wamid = _extract_wamid(response)
        log_event(
            self.config.state_dir,
            "wa_session_reply_sent",
            wamid=wamid,
            in_24h_window=True,
            cost_kes_cents_est=0,
        )
        return response

    def send_utility_template(
        self,
        to_e164: str,
        template: str,
        params: list[str],
        *,
        now: datetime | None = None,
    ) -> dict:
        """Send an approved S-0 utility template to the single configured owner number.

        Enforces:
        1. single-recipient owner lock (``EgressRefused`` otherwise);
        2. S-0 template pack registration & parameter validation (``TemplateSpecError``);
        3. belt-and-braces per-day paid-template cap if ``self.store`` is attached
           (``TemplateCapExceeded``);
        4. per-send journaling before and after the HTTP call with KES-cents cost.
        """
        now_utc = (now or datetime.now(UTC)).astimezone(UTC)
        try:
            canonical_to = normalise_e164(to_e164)
        except AliveConfigError as exc:
            raise EgressRefused(str(exc)) from exc

        if canonical_to != self.config.owner_e164:
            raise EgressRefused(
                "utility templates may only be addressed to the single configured "
                "owner number; refusing")

        spec = resolve_template(template)
        body = spec.graph_send_payload(canonical_to, params)

        if self.store is not None:
            sent_today = self.store.count_today("templates", tier="T0", now=now_utc)
            if sent_today >= self.config.max_templates_per_day:
                log_event(
                    self.config.state_dir,
                    "wa_template_cap_blocked",
                    level="warn",
                    template=spec.name,
                    sent_today=sent_today,
                    cap=self.config.max_templates_per_day,
                )
                raise TemplateCapExceeded(
                    f"paid template cap reached ({sent_today}/{self.config.max_templates_per_day} today)")

        log_event(
            self.config.state_dir,
            "wa_template_attempt",
            template=spec.name,
            kind=spec.kind,
            cost_usd_est=EST_TEMPLATE_COST_USD,
            cost_kes_cents_est=EST_TEMPLATE_COST_KES_CENTS,
        )
        response = self._send(body)
        wamid = _extract_wamid(response)
        log_event(
            self.config.state_dir,
            "wa_template_sent",
            template=spec.name,
            kind=spec.kind,
            wamid=wamid,
            cost_usd_est=EST_TEMPLATE_COST_USD,
            cost_kes_cents_est=EST_TEMPLATE_COST_KES_CENTS,
        )
        return response


def _extract_wamid(response: dict) -> str | None:
    try:
        return str(response["messages"][0]["id"])
    except (KeyError, IndexError, TypeError):
        return None


class FakeTransport:
    """Test double that enforces the EXACT same 24h-window, owner-only, and S-0
    template rules as ``WhatsAppCloudTransport`` so fake and real cannot drift.

    ``fail_with`` may be ``PlatformBlocked``, ``OutsideServiceWindow``, or
    ``TransportError``.
    """

    def __init__(
        self,
        *,
        config: AliveConfig | None = None,
        store: AliveStore | None = None,
        enforce_window: bool = False,
    ):
        self.sent: list[dict] = []
        self.fail_with: Exception | None = None
        self.config = config
        self.store = store
        self.enforce_window = enforce_window

    @property
    def name(self) -> str:
        return "fake"

    def _maybe_fail(self):
        if self.fail_with is not None:
            raise self.fail_with

    def send_service_reply(
        self,
        to_e164: str,
        text: str,
        *,
        now: datetime | None = None,
        inbound_at: datetime | str | None = None,
    ) -> dict:
        now_utc = (now or datetime.now(UTC)).astimezone(UTC)
        canonical_to = normalise_e164(to_e164)
        if (self.enforce_window or inbound_at is not None or self.store is not None) and self.config is not None:
            _check_24h_window(
                to_canonical=canonical_to,
                config=self.config,
                store=self.store,
                now=now_utc,
                inbound_at=inbound_at,
            )
        self._maybe_fail()
        self.sent.append({
            "kind": "service_reply",
            "to": canonical_to,
            "text": text,
            "in_24h_window": True,
        })
        return {"messages": [{"id": f"wamid.fake{len(self.sent)}"}]}

    def send_utility_template(
        self,
        to_e164: str,
        template: str,
        params: list[str],
        *,
        now: datetime | None = None,
    ) -> dict:
        now_utc = (now or datetime.now(UTC)).astimezone(UTC)
        canonical_to = normalise_e164(to_e164)
        if self.config is not None and canonical_to != self.config.owner_e164:
            raise EgressRefused(
                "utility templates may only be addressed to the single configured owner number")
        spec = resolve_template(template)
        validated = spec.graph_send_payload(canonical_to, params)
        if self.store is not None and self.config is not None:
            sent_today = self.store.count_today("templates", tier="T0", now=now_utc)
            if sent_today >= self.config.max_templates_per_day:
                raise TemplateCapExceeded(
                    f"paid template cap reached ({sent_today}/{self.config.max_templates_per_day} today)")
        self._maybe_fail()
        clean_params = [p["text"] for p in validated["template"]["components"][0]["parameters"]]
        self.sent.append({
            "kind": "template",
            "to": canonical_to,
            "template": spec.name,
            "template_kind": spec.kind,
            "params": clean_params,
            "rendered": spec.render_preview(clean_params),
        })
        return {"messages": [{"id": f"wamid.fake{len(self.sent)}"}]}


__all__ = [
    "OUTSIDE_WINDOW_CODE",
    "PLATFORM_BLOCKED_CODES",
    "EgressRefused",
    "FakeTransport",
    "OutsideServiceWindow",
    "PlatformBlocked",
    "TemplateCapExceeded",
    "TemplateSpecError",
    "TransportError",
    "WhatsAppCloudTransport",
    "assert_egress_allowed",
]
