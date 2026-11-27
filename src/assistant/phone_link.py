"""Phone link — Elaria's side of the caelestia-connect sidecar.

caelestia-connect (GPL-3.0) runs beside Elaria as a PINNED SIDECAR and
speaks KDE Connect to the owner's Android phone. We speak to that sidecar
over its local IPC socket and import NONE of its Python: LICENSE-DECIDES-
METHOD says a copyleft dependency may be spoken to, never copied into
Elaria's permissive tree. Nothing here imports, vendors or edits upstream.

Pinned upstream (contract IF-3 asks for tag + commit + sha256):
  repo    https://github.com/maylton/caelestia-connect
  tag     v1.1.1
  commit  b49ca2c9f76dd6feccf40fb6b82fc98db344c613
  tarball sha256 fa305344123b481d9ba09b5aee46b31a9cb46ad73fef6ef8dfa3d83ae4ee8bd6

The wire dialect is the sidecar's own (line-delimited JSON over AF_UNIX,
socket mode 0600):

  request   {"id": 1, "method": "device.call", "params": {...}}
  response  {"id": 1, "result": ...}  |  {"id": 1, "error": "message"}
  event     {"event": "state", "data": {...}}

Safety rules this module enforces, each covered by tests/test_phone_link.py:

1. the ONLY write verb is ``sms.send_sms``, and it is reachable ONLY through
   ``send_approved()`` — a draft the owner approved. ``request()`` refuses
   every write;
2. reads are free but ALLOWLISTED: anything not on the read allowlist is
   refused, and the refusal happens BEFORE any packet leaves;
3. the never-allowlist list — share.*, clipboard.send_clipboard, send-text,
   runcommand, remotecommands, remotecontrol, mousepad, remotekeyboard,
   sftp(.browse/.unmount/.mount), lockdevice, phoneaudio.*, the plugins IF-3
   never enables (scrcpy, webcam, android, virtualmonitor, shareinputdevices,
   digitizer) and the GENERIC ``call PLUGIN ACTION`` interpreter — is refused
   even if somebody edits the allowlist (the allowlist is validated at import);
4. inbound texts and notifications are UNTRUSTED INPUT (contract IF-6):
   they are delivered as DATA, tagged untrusted, never dispatched as an
   action;
5. pairing is the OWNER's act. We never accept, request or complete a
   verification code — we only read which devices are paired, and journal
   the pair/unpair transitions;
6. revocation (unpair + key removal) calls ``device.unpair`` on the sidecar
   (or marks ``pending_unpair`` and retries on next link-up if unreachable)
   and blocks every later send locally before any IPC call.

The phone adapter never installs anything, never touches a real device and
never performs a real send: the tests run against a fake peer only.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import socket
import stat
import threading
import time
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Self

from assistant.drafts import APPROVED, DraftRecord

log = logging.getLogger(__name__)

CAELESTIA_UPSTREAM = "https://github.com/maylton/caelestia-connect"
CAELESTIA_TAG = "v1.1.1"
CAELESTIA_COMMIT = "b49ca2c9f76dd6feccf40fb6b82fc98db344c613"
CAELESTIA_TARBALL_SHA256 = (
    "fa305344123b481d9ba09b5aee46b31a9cb46ad73fef6ef8dfa3d83ae4ee8bd6"
)
CAELESTIA_PINNED_ACTION_COUNT = 47

#: Reads are free, but only these. Everything else is refused.
READ_VERBS: frozenset[str] = frozenset(
    {
        "sms.conversations",
        "sms.messages",
        "sms.request_conversation",
        "telephony.read",
        "notifications.read",
        "ping.ping",
        "battery.read",
        "connectivity.read",
    }
)

#: The single write verb. Reachable only through send_approved().
WRITE_VERBS: frozenset[str] = frozenset({"sms.send_sms"})

#: Plugins that may NEVER be allowlisted, whatever a future edit says.
FORBIDDEN_PLUGINS: frozenset[str] = frozenset(
    {
        "runcommand",
        "remotecommands",
        "remotecontrol",
        "mousepad",
        "remotekeyboard",
        "sftp",
        "lockdevice",
        "phoneaudio",
        "android",
    }
)

#: Every plugin.action the pinned upstream release exposes.
#:
#: Enumerated from the upstream v1.1.1 sources at commit
#: CAELESTIA_COMMIT (the release the tarball pin above names). These are
#: NAMES only -- no upstream code is copied, imported or vendored. The list
#: exists so the refusal layer is derived from the real upstream surface
#: instead of from a hand-written guess that can fall behind it.
#:
#: E's own allowlist names five of them; the other 42 are refused.
UPSTREAM_ACTIONS: frozenset[str] = frozenset(
    {
        "clipboard.send_clipboard",
        "contacts.list_contacts",
        "contacts.sync",
        "findmyphone.ring",
        "findthisdevice.stop",
        "lockdevice.set_locked",
        "mprisremote.media_action",
        "mprisremote.refresh",
        "mprisremote.select_player",
        "mprisremote.set_position",
        "mprisremote.set_volume",
        "notifications.dismiss",
        "notifications.dismiss_all",
        "notifications.invoke_action",
        "notifications.refresh",
        "notifications.reply",
        "phoneaudio.set_on_computer",
        "phoneaudio.toggle",
        "ping.ping",
        "remotecommands.edit_commands",
        "remotecommands.trigger",
        "remotecontrol.command",
        "remotecontrol.move",
        "remotekeyboard.send_key",
        "remotekeyboard.send_text",
        "remotesystemvolume.set_muted",
        "remotesystemvolume.set_volume",
        "runcommand.add_command",
        "runcommand.edit_command",
        "runcommand.remove_command",
        "sendnotifications.test",
        "sftp.browse",
        "sftp.mount",
        "sftp.unmount",
        "share.open_folder",
        "share.share_files",
        "share.share_text",
        "share.share_url",
        "sms.conversations",
        "sms.get_attachment",
        "sms.messages",
        "sms.request_conversation",
        "sms.request_conversations",
        "sms.send_sms",
        "telephony.mute",
        "virtualmonitor.start",
        "virtualmonitor.stop",
    }
)

#: The upstream actions E is allowed to reach, mapped from E's own verbs.
#: Everything else upstream exposes is refused.
_ALLOWED_UPSTREAM_ACTIONS: frozenset[str] = frozenset(
    {
        "sms.conversations",
        "sms.messages",
        "sms.request_conversation",
        "ping.ping",
        "sms.send_sms",
    }
)

#: The generic plugin/action interpreter. Never allowlistable.
FORBIDDEN_VERBS: frozenset[str] = frozenset(
    {
        "call",
        "send-text",
        "scrcpy",
        "webcam",
        "android",
        "phoneaudio",
        "virtualmonitor",
        "shareinputdevices",
        "digitizer",
        "share",
        "share.share_files",
        "share.share_url",
        "share.share_text",
        "clipboard.send_clipboard",
        "findmyphone.ring",
        "sftp.browse",
        "sftp.mount",
        "sftp.unmount",
    }
)

#: Prefixes of verbs that may never be allowlisted (plugin.action forms).
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "call.",
    "send-text.",
    "scrcpy.",
    "webcam.",
    "android.",
    "phoneaudio.",
    "virtualmonitor.",
    "shareinputdevices.",
    "digitizer.",
    "share.",
    "clipboard.",
    "findmyphone.",
    "sftp.",
    "runcommand.",
    "remotecommands.",
    "remotecontrol.",
    "mousepad.",
    "remotekeyboard.",
    "lockdevice.",
)

#: Plugin state keys served from the sidecar's `state` response.
_STATE_READS: dict[str, str] = {
    "battery.read": "battery",
    "connectivity.read": "connectivity_report",
    "telephony.read": "telephony",
    "notifications.read": "notifications",
}


class PhoneLinkError(RuntimeError):
    """Any failure of the phone link. The message names the failing stage."""


class TransportError(PhoneLinkError):
    """The sidecar socket could not be reached, or answered badly."""


class Refused(PhoneLinkError):
    """A request was refused. NOTHING was invoked and no packet was sent."""


class NotApproved(Refused):
    """A send was attempted for a draft the owner never approved."""


def _is_forbidden(verb: str) -> bool:
    """True when the verb may never be allowlisted."""
    if verb in FORBIDDEN_VERBS:
        return True
    if verb in FORBIDDEN_PLUGINS:
        return True
    if any(verb.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return True
    plugin = verb.split(".", 1)[0]
    if plugin in FORBIDDEN_PLUGINS:
        return True
    # Any upstream plugin.action that E did not explicitly allow is refused.
    # This is the fail-closed default: a verb that names a real upstream
    # action cannot be allowlisted by accident, and a future upstream
    # release that adds an action fails closed until E re-pins and
    # re-assesses it (IF-3 change control).
    return verb in UPSTREAM_ACTIONS and verb not in _ALLOWED_UPSTREAM_ACTIONS


def _validate_allowlist() -> None:
    """Fail closed at import if the allowlist ever grows a forbidden verb."""
    for verb in READ_VERBS | WRITE_VERBS:
        if _is_forbidden(verb):
            raise RuntimeError(f"allowlist contains the never-allowlist verb {verb!r}")


_validate_allowlist()


class Transport(Protocol):
    """The sidecar's IPC transport. Only the configured socket is allowed."""

    socket_path: Path

    def call(
        self, method: str, params: Mapping[str, Any] | None = None, *, timeout: float | None = None
    ) -> Any: ...


class SocketTransport:
    """Line-delimited JSON over the sidecar's AF_UNIX socket."""

    def __init__(
        self,
        socket_path: str | Path,
        *,
        connect_timeout: float = 5.0,
        request_timeout: float = 10.0,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.connect_timeout = float(connect_timeout)
        self.request_timeout = float(request_timeout)
        self._sock: socket.socket | None = None
        self._reader: Any = None
        self._thread: threading.Thread | None = None
        self._pending: dict[int, queue.Queue] = {}
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._next_id = 1
        self._event_handlers: list[Callable[[str, Any], None]] = []

    # -- lifecycle -----------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        """Connect to the configured socket. Fails closed on a lax socket."""
        if self._sock is not None:
            return
        path = self.socket_path
        try:
            info = os.stat(path)
        except FileNotFoundError as exc:
            raise TransportError(f"the sidecar socket is missing at {path}") from exc
        except OSError as exc:
            raise TransportError(f"cannot stat the sidecar socket {path}: {exc}") from exc
        if not stat.S_ISSOCK(info.st_mode):
            raise TransportError(f"{path} is not a socket")
        if info.st_mode & 0o077:
            raise TransportError(
                f"the sidecar socket {path} is not owner-only"
                f" (mode {stat.S_IMODE(info.st_mode):04o}); refusing to use it"
            )
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.connect_timeout)
        try:
            sock.connect(str(path))
        except OSError as exc:
            sock.close()
            raise TransportError(f"cannot connect to the sidecar socket {path}: {exc}") from exc
        sock.settimeout(None)
        self._sock = sock
        self._reader = sock.makefile("rb")
        self._thread = threading.Thread(target=self._read_loop, name="caelestia-ipc", daemon=True)
        self._thread.start()

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        with self._state_lock:
            waiting = list(self._pending.values())
            self._pending.clear()
        for box in waiting:
            box.put({"error": "the sidecar connection closed"})

    # -- requests ------------------------------------------------------------

    def call(
        self, method: str, params: Mapping[str, Any] | None = None, *, timeout: float | None = None
    ) -> Any:
        """One request, one response. The deadline is total, not per-leg."""
        self.connect()
        limit = self.request_timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + limit
        with self._state_lock:
            mid = self._next_id
            self._next_id += 1
            box: queue.Queue = queue.Queue(maxsize=1)
            self._pending[mid] = box
        payload = json.dumps(
            {"id": mid, "method": method, "params": dict(params or {})},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            with self._write_lock:
                sock = self._sock
                if sock is None:
                    raise TransportError("the sidecar connection is closed")
                sock.sendall(payload.encode() + b"\n")
        except OSError as exc:
            self._drop(mid)
            self.close()
            raise TransportError(f"cannot write to the sidecar: {exc}") from exc
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            self._drop(mid)
            raise TransportError(f"the sidecar did not answer {method} within {limit:.1f}s")
        try:
            message = box.get(timeout=remaining)
        except queue.Empty:
            self._drop(mid)
            raise TransportError(f"the sidecar did not answer {method} within {limit:.1f}s") from None
        if "error" in message:
            raise TransportError(f"the sidecar refused {method}: {message['error']}")
        return message.get("result")

    def on_event(self, handler: Callable[[str, Any], None]) -> None:
        self._event_handlers.append(handler)

    # -- internals -----------------------------------------------------------

    def _drop(self, mid: int) -> None:
        with self._state_lock:
            self._pending.pop(mid, None)

    def _read_loop(self) -> None:
        reader = self._reader
        if reader is None:
            return
        try:
            for line in reader:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                if "event" in message:
                    self._dispatch_event(str(message.get("event")), message.get("data"))
                    continue
                mid = message.get("id")
                with self._state_lock:
                    box = self._pending.pop(mid, None)
                if box is not None:
                    box.put(message)
        except (OSError, ValueError):
            pass
        finally:
            with self._state_lock:
                waiting = list(self._pending.values())
                self._pending.clear()
            for box in waiting:
                box.put({"error": "the sidecar connection closed"})

    def _dispatch_event(self, name: str, data: Any) -> None:
        for handler in list(self._event_handlers):
            try:
                handler(name, data)
            except Exception:  # a broken handler must not kill the reader
                log.exception("sidecar event handler failed")


#: A conservative synthetic trap detector, mirroring the shape of cluster
#: O's injection.py (the canonical detector lives in hands/injection.py; it
#: does not know the phone origins yet — hook request HR-E-5 asks O for them).
#: It only decides whether to RECORD a refusal; the content is delivered as
#: data either way, and can never become an action.
_INBOUND_TRAP = re.compile(
    r"\b(?:delete|remove|erase|wipe|execute|run|ignore|send|upload|append|add|pretend)"
    r"\s+\S+"
    r'|"(?:steps|argv|env_diff)"\s*:',
    re.IGNORECASE,
)


def suspected_inbound(text: str) -> bool:
    """True when the content LOOKS like an embedded instruction."""
    return bool(_INBOUND_TRAP.search(unicodedata.normalize("NFKC", str(text))))


@dataclass(frozen=True, slots=True)
class InboundItem:
    """Content that arrived from the phone. UNTRUSTED DATA, never an action."""

    kind: str
    payload: Mapping[str, Any]
    received_at: str
    suspected: bool = False

    @property
    def trusted(self) -> bool:
        """Inbound content is never trusted. There is no way to mark it so."""
        return False

    def as_text(self) -> str:
        """The content as plain text for a human or for cluster C to read."""
        title = str(self.payload.get("title") or "").strip()
        body = str(self.payload.get("body") or "").strip()
        if title and body and title != body:
            return f"{title}: {body}"
        return body or title


class PairingRegistry:
    """Local record of paired devices and of revoked ones.

    The owner performs the pairing (and the verification code) — this
    registry only remembers what the sidecar reports, and it never stores a
    verification key. Revocation asks the sidecar to ``device.unpair`` and
    removes the local record; if the sidecar is unreachable, local refusal
    still stands immediately while ``pending_unpair`` keeps the sidecar
    unpair queued until the next link-up.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._paired: dict[str, dict[str, Any]] = {}
        self._revoked: set[str] = set()
        self._pending_unpair: set[str] = set()
        self._unpaired: set[str] = set()
        self.has_synced: bool = False
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            paired = data.get("paired")
            if isinstance(paired, dict):
                self._paired = {str(k): dict(v) for k, v in paired.items() if isinstance(v, dict)}
            revoked = data.get("revoked")
            if isinstance(revoked, list):
                self._revoked = {str(x) for x in revoked}
            pending_unpair = data.get("pending_unpair")
            if isinstance(pending_unpair, list):
                self._pending_unpair = {str(x) for x in pending_unpair}
                # Pending-unpair devices must always stay refused locally too.
                self._revoked.update(self._pending_unpair)
            unpaired = data.get("unpaired")
            if isinstance(unpaired, list):
                self._unpaired = {str(x) for x in unpaired}
            if "has_synced" in data:
                self.has_synced = bool(data["has_synced"])

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "paired": self._paired,
            "revoked": sorted(self._revoked),
            "pending_unpair": sorted(self._pending_unpair),
            "unpaired": sorted(self._unpaired),
            "has_synced": self.has_synced,
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:  # pragma: no cover - exotic filesystems only
            pass

    def paired_devices(self) -> dict[str, dict[str, Any]]:
        return {
            did: dict(info)
            for did, info in self._paired.items()
            if did not in self._revoked and did not in self._pending_unpair
        }

    def is_paired(self, device_id: str) -> bool:
        did = str(device_id)
        return (
            did in self._paired
            and did not in self._revoked
            and did not in self._pending_unpair
        )

    def is_revoked(self, device_id: str) -> bool:
        return str(device_id) in self._revoked

    def is_pending_unpair(self, device_id: str) -> bool:
        return str(device_id) in self._pending_unpair

    def pending_unpairs(self) -> list[str]:
        return sorted(self._pending_unpair)

    def unpaired_devices(self) -> list[str]:
        return sorted(self._unpaired)

    def is_unpaired(self, device_id: str) -> bool:
        return str(device_id) in self._unpaired

    def mark_synced(self) -> None:
        self.has_synced = True
        self._save()

    def record_paired(self, device_id: str, name: str = "") -> None:
        did = str(device_id)
        if self.is_revoked(did) or self.is_pending_unpair(did):
            return
        self._unpaired.discard(did)
        self._paired[did] = {"name": str(name), "paired_at": time.time()}
        self._save()

    def record_unpaired(self, device_id: str) -> None:
        did = str(device_id)
        self._paired.pop(did, None)
        self._unpaired.add(did)
        self._save()

    def mark_pending_unpair(self, device_id: str) -> None:
        """Keep local refusal standing while waiting to flush device.unpair."""
        did = str(device_id)
        self._revoked.add(did)
        self._pending_unpair.add(did)
        if did in self._paired:
            self._paired[did]["status"] = "pending-unpair"
        self._save()

    def revoke(self, device_id: str) -> None:
        """Unpair + key removal. Later sends to this device are refused."""
        device_id = str(device_id)
        self._paired.pop(device_id, None)
        self._unpaired.discard(device_id)
        self._pending_unpair.discard(device_id)
        self._revoked.add(device_id)
        self._save()

    def revoked_devices(self) -> list[str]:
        return sorted(self._revoked)


class PhoneLink:
    """Elaria's adapter for the caelestia-connect sidecar.

    The socket path is REQUIRED and comes from the configuration (hook
    request HR-E-2, contract IF-3): the adapter connects to the configured
    socket and to no other.
    """

    def __init__(
        self,
        socket_path: str | Path,
        *,
        device_id: str | None = None,
        transport: Transport | None = None,
        registry: PairingRegistry | None = None,
        journal: Callable[..., None] | None = None,
        trap_detector: Callable[[str], bool] | None = None,
        connect_timeout: float = 5.0,
        request_timeout: float = 10.0,
    ) -> None:
        if socket_path is None or not str(socket_path).strip():
            raise PhoneLinkError("the phone link needs a configured sidecar socket")
        self.socket_path = Path(socket_path)
        self.device_id = (
            str(device_id).strip()
            if device_id is not None and str(device_id).strip()
            else None
        )
        self._journal = journal
        self.request_timeout = float(request_timeout)
        self._registry = registry if registry is not None else PairingRegistry()
        self._trap_detector = trap_detector if trap_detector is not None else suspected_inbound
        self.refusals: list[dict[str, Any]] = []
        self._inbound_handlers: list[Callable[[InboundItem], None]] = []
        if transport is not None:
            configured = Path(getattr(transport, "socket_path", ""))
            if configured != self.socket_path:
                raise PhoneLinkError(
                    "the phone link may only use the configured socket"
                    f" ({self.socket_path}), not {configured or 'an unnamed socket'}"
                )
            self._transport: Transport = transport
        else:
            self._transport = SocketTransport(
                self.socket_path,
                connect_timeout=connect_timeout,
                request_timeout=request_timeout,
            )

    def close(self) -> None:
        """Close the sidecar connection, if one was opened."""
        closer = getattr(self._transport, "close", None)
        if callable(closer):
            closer()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    # -- the allowlisted surface --------------------------------------------

    def request(self, verb: str, **params: Any) -> Any:
        """Perform an ALLOWLISTED read. Writes and unknown verbs are refused."""
        self._guard(verb)
        if verb in _STATE_READS:
            return self._read_plugin_state(verb)
        if verb == "sms.conversations":
            return self._call_plugin("sms", "conversations", {})
        if verb == "sms.messages":
            return self._call_plugin("sms", "messages", {"thread_id": _thread_id(params)})
        if verb == "sms.request_conversation":
            args: dict[str, Any] = {"thread_id": _thread_id(params)}
            if "start" in params:
                args["start"] = int(params["start"])
            if "count" in params:
                args["count"] = int(params["count"])
            return self._call_plugin("sms", "request_conversation", args)
        if verb == "ping.ping":
            return self._call_plugin("ping", "ping", {"message": str(params.get("message", ""))})
        raise Refused(f"refused {verb}: it has no read implementation")  # pragma: no cover

    def send_approved(
        self,
        draft: DraftRecord | str,
        *,
        store: Any = None,
        device: str | None = None,
    ) -> Any:
        """Send an APPROVED draft. The only write path in Elaria.

        The body and the recipient come from the STORED draft — never from
        the caller — so the sent body is the stored body by construction.
        The draft must already be ``approved``; anything else is refused
        before a single packet leaves.

        Local pairing state is checked BEFORE any IPC call: revoked,
        pending-unpair, or unpaired devices are refused locally with zero
        IPC packets sent.
        """
        resolved = self._resolve_draft(draft, store)
        if resolved.state != APPROVED:
            raise NotApproved(
                f"refused to send draft {resolved.draft_id}: it is {resolved.state!r},"
                " not 'approved'"
            )
        # S-C2: when the adapter is bound to a configured device_id, an explicit
        # device= argument targeting any other device (or an empty device id)
        # must NEVER silently override that binding — refuse and journal locally
        # before a single IPC packet leaves.
        requested_id: str | None = None
        if device is not None:
            requested_id = str(device).strip()
            if not requested_id:
                self._refuse(
                    "sms.send_sms",
                    "explicit device argument was empty; refusing",
                    device_id=str(device),
                    configured_device_id=self.device_id,
                )
            if self.device_id is not None and requested_id != self.device_id:
                self._refuse(
                    "sms.send_sms",
                    f"explicit device {requested_id!r} differs from configured"
                    f" device binding {self.device_id!r}; refusing to override"
                    " configured device",
                    device_id=requested_id,
                    configured_device_id=self.device_id,
                )
        target_id = self.device_id if self.device_id is not None else requested_id
        if target_id is not None:
            target_id = str(target_id)
            if self._registry.is_revoked(target_id) or self._registry.is_pending_unpair(
                target_id
            ):
                self._refuse(
                    "sms.send_sms",
                    f"device {target_id} was unpaired and its key removed;"
                    " the owner must pair it again before sending",
                    device_id=target_id,
                )
            if not self._registry.is_paired(target_id):
                self._refuse(
                    "sms.send_sms",
                    f"device {target_id} is not paired locally;"
                    " the owner must pair it before sending",
                    device_id=target_id,
                )
            state = self._read_state()
            dev = self._find_device(state, target_id)
            if dev is None or not dev.get("paired"):
                self._registry.record_unpaired(target_id)
                self._audit("phone.unpaired", device_id=target_id)
                self._refuse(
                    "sms.send_sms",
                    f"device {target_id} is not paired on the sidecar;"
                    " the owner must pair it before sending",
                    device_id=target_id,
                )
            if not dev.get("reachable"):
                raise PhoneLinkError(f"device {target_id} is not reachable")
            device_id = target_id
        else:
            if not self._registry.paired_devices() and (
                self._registry.has_synced
                or self._registry.revoked_devices()
                or self._registry.unpaired_devices()
            ):
                self._refuse(
                    "sms.send_sms",
                    "no paired device in local pairing registry;"
                    " the owner must pair a phone before sending",
                )
            state = self._read_state()
            selected = self._select_device(state, refuse_unpaired=True)
            device_id = str(selected.get("id"))
            if self._registry.is_revoked(device_id) or self._registry.is_pending_unpair(
                device_id
            ):
                self._refuse(
                    "sms.send_sms",
                    f"device {device_id} was unpaired and its key removed;"
                    " the owner must pair it again before sending",
                    device_id=device_id,
                )
        self._audit(
            "phone.send.attempt",
            draft_id=resolved.draft_id,
            device_id=device_id,
            recipient=resolved.recipient,
            body_length=len(resolved.body),
        )
        try:
            result = self._call_plugin(
                "sms",
                "send_sms",
                {"addresses": [resolved.recipient], "message": resolved.body},
                device=device_id,
            )
        except Exception as exc:
            if store is not None:
                store.mark_failed(resolved.draft_id, outcome="send-error", detail=str(exc))
            self._audit(
                "phone.send.failed",
                draft_id=resolved.draft_id,
                device_id=device_id,
                reason=str(exc),
            )
            raise
        if result is False:
            if store is not None:
                store.mark_failed(
                    resolved.draft_id,
                    outcome="send-error",
                    detail="the sidecar refused the message",
                )
            self._audit(
                "phone.send.failed",
                draft_id=resolved.draft_id,
                device_id=device_id,
                reason="the sidecar refused the message",
            )
            raise PhoneLinkError("the sidecar refused to send the message")
        if store is not None:
            store.mark_sent(resolved.draft_id)
        self._audit(
            "phone.send.sent",
            draft_id=resolved.draft_id,
            device_id=device_id,
            recipient=resolved.recipient,
            body_length=len(resolved.body),
        )
        return result

    # -- pairing -------------------------------------------------------------

    def flush_pending_unpairs(self) -> list[str]:
        """Retry any queued ``device.unpair`` calls on the sidecar."""
        if not self._registry.pending_unpairs():
            return []
        state = self._transport.call("state", {}, timeout=self.request_timeout)
        return self._flush_pending_unpairs(state if isinstance(state, dict) else None)

    def sync_pairing(self) -> dict[str, list[str]]:
        """Read which devices are paired and journal pair/unpair transitions.

        The owner performs the pairing and the verification code. This only
        observes what the sidecar reports, after flushing any pending
        unpair requests queued while the sidecar was unreachable.
        """
        if self._registry.pending_unpairs():
            self.flush_pending_unpairs()
        state = self._read_state()
        return self._sync_pairing_from_state(state)

    def inspect_state(self) -> dict[str, Any]:
        """Read sidecar state on demand and synchronize local pairing registry.

        Uses only the existing sidecar ``state`` query (no extra verbs).
        """
        if self._registry.pending_unpairs():
            self.flush_pending_unpairs()
        state = self._read_state()
        transitions = self._sync_pairing_from_state(state)
        devices: list[dict[str, Any]] = []
        configured_device: dict[str, Any] | None = None
        for raw in state.get("devices") or []:
            if not isinstance(raw, Mapping):
                continue
            did = str(raw.get("id") or "")
            plugins = raw.get("state") if isinstance(raw.get("state"), Mapping) else {}
            entry: dict[str, Any] = {
                "id": did,
                "name": str(raw.get("name") or did),
                "type": str(raw.get("type") or ""),
                "paired": bool(raw.get("paired")),
                "reachable": bool(raw.get("reachable")),
                "pair_state": str(raw.get("pairState") or raw.get("pair_state") or ""),
                "revoked": self._registry.is_revoked(did),
                "pending_unpair": self._registry.is_pending_unpair(did),
            }
            if "battery" in plugins:
                entry["battery"] = plugins["battery"]
            if "connectivity_report" in plugins:
                entry["connectivity"] = plugins["connectivity_report"]
            elif "connectivity" in plugins:
                entry["connectivity"] = plugins["connectivity"]
            devices.append(entry)
            if self.device_id is not None and did == self.device_id:
                configured_device = entry
        return {
            "sidecar_version": state.get("version"),
            "devices": devices,
            "configured_device_id": self.device_id,
            "configured_device": configured_device,
            "paired_devices": self._registry.paired_devices(),
            "revoked_devices": self._registry.revoked_devices(),
            "pending_unpairs": self._registry.pending_unpairs(),
            "transitions": transitions,
        }

    def _sync_pairing_from_state(self, state: Mapping[str, Any]) -> dict[str, list[str]]:
        self._registry.mark_synced()
        devices = state.get("devices") or []
        paired_now = {
            str(device.get("id")): str(device.get("name") or device.get("id"))
            for device in devices
            if device.get("paired")
        }
        known = set(self._registry.paired_devices())
        events: dict[str, list[str]] = {"paired": [], "unpaired": []}
        for device_id, name in paired_now.items():
            if device_id in known:
                continue
            if self._registry.is_revoked(device_id) or self._registry.is_pending_unpair(
                device_id
            ):
                continue
            self._registry.record_paired(device_id, name)
            events["paired"].append(device_id)
            self._audit("phone.paired", device_id=device_id, name=name)
        for device_id in sorted(known - set(paired_now)):
            if self._registry.is_revoked(device_id):
                continue
            self._registry.record_unpaired(device_id)
            events["unpaired"].append(device_id)
            self._audit("phone.unpaired", device_id=device_id)
        for device in devices:
            device_id = str(device.get("id") or "")
            if (
                device_id
                and not device.get("paired")
                and not self._registry.is_revoked(device_id)
                and not self._registry.is_unpaired(device_id)
            ):
                self._registry.record_unpaired(device_id)
        return events

    def revoke(self, device_id: str) -> None:
        """Unpair on the sidecar + remove local state.

        If the sidecar is unreachable, the local refusal stands immediately
        and the pairing is marked ``pending-unpair`` so ``device.unpair``
        is retried on the next link-up.
        """
        did = str(device_id)
        try:
            self._transport.call(
                "device.unpair",
                {"device": did},
                timeout=self.request_timeout,
            )
        except TransportError as exc:
            self._registry.mark_pending_unpair(did)
            self._audit(
                "phone.revoked",
                device_id=did,
                sidecar_unpaired=False,
                pending_unpair=True,
                reason=str(exc),
            )
            return
        self._registry.revoke(did)
        self._audit("phone.revoked", device_id=did, sidecar_unpaired=True)

    def revoked_devices(self) -> list[str]:
        return self._registry.revoked_devices()

    # -- inbound (untrusted) -------------------------------------------------

    def on_inbound(self, handler: Callable[[InboundItem], None]) -> None:
        """Register a handler for inbound content. It receives DATA, not actions."""
        self._inbound_handlers.append(handler)

    def deliver_inbound(self, kind: str, items: Iterable[Any]) -> list[InboundItem]:
        """Hand inbound content to the rail as untrusted DATA.

        Nothing in the content is interpreted here: an inbound message that
        says "send an SMS to ..." is data, never an action.
        """
        delivered: list[InboundItem] = []
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for item in items:
            payload = item if isinstance(item, Mapping) else {"body": str(item)}
            text = str(payload.get("body") or payload.get("title") or "")
            suspected = bool(self._trap_detector(text))
            record = InboundItem(
                kind=str(kind),
                payload=dict(payload),
                received_at=stamp,
                suspected=suspected,
            )
            delivered.append(record)
            # Loading untrusted content is itself journaled (IF-6): an
            # observation, attributable and on record.
            self._audit(
                "phone.inbound",
                kind=record.kind,
                length=len(record.as_text()),
                suspected=suspected,
            )
            if suspected:
                # The embedded instruction is DENIED, not consented to. The
                # content still travels as data; what is refused is the idea
                # that it could drive a tool.
                self._audit(
                    "phone.inbound.refused",
                    kind=record.kind,
                    reason="the inbound content carries an embedded instruction",
                )
            for handler in list(self._inbound_handlers):
                try:
                    handler(record)
                except Exception:  # untrusted content must never break the link
                    log.exception("inbound handler failed")
        return delivered

    # -- internals -----------------------------------------------------------

    def _guard(self, verb: str) -> None:
        if not isinstance(verb, str) or not verb.strip():
            self._refuse(str(verb), "no verb was given")
        verb = verb.strip()
        if _is_forbidden(verb):
            self._refuse(
                verb,
                "it is on the never-allowlist list (the generic call interpreter"
                " and the input-control plugins stay refused)",
            )
        if verb in WRITE_VERBS:
            self._refuse(verb, "writes go through send_approved() only")
        if verb not in READ_VERBS:
            self._refuse(verb, "it is not on the read allowlist")

    def _refuse(self, verb: str, reason: str, **fields: Any) -> None:
        record = {"verb": verb, "reason": reason}
        record.update(fields)
        self.refusals.append(record)
        self._audit("phone.refused", verb=verb, reason=reason, **fields)
        log.warning("refused %s: %s", verb, reason)
        raise Refused(f"refused {verb}: {reason}")

    def _read_state(self) -> dict[str, Any]:
        result = self._transport.call("state", {}, timeout=self.request_timeout)
        state = result if isinstance(result, dict) else {}
        if self._registry.pending_unpairs():
            self._flush_pending_unpairs(state)
        return state

    def _flush_pending_unpairs(self, state: Mapping[str, Any] | None = None) -> list[str]:
        pending = self._registry.pending_unpairs()
        if not pending:
            return []
        devices = (
            {
                str(d.get("id")): d
                for d in (state.get("devices") or [])
                if d.get("id") is not None
            }
            if state is not None
            else None
        )
        flushed: list[str] = []
        for did in pending:
            dev = devices.get(did) if devices is not None else None
            if devices is not None and (dev is None or not dev.get("paired")):
                if dev is not None:
                    try:
                        self._transport.call(
                            "device.unpair",
                            {"device": did},
                            timeout=self.request_timeout,
                        )
                    except TransportError:
                        pass
                self._registry.revoke(did)
                self._audit("phone.unpair.synced", device_id=did)
                flushed.append(did)
                continue
            try:
                self._transport.call(
                    "device.unpair",
                    {"device": did},
                    timeout=self.request_timeout,
                )
            except TransportError as exc:
                if devices is not None and did not in devices:
                    self._registry.revoke(did)
                    self._audit("phone.unpair.synced", device_id=did)
                    flushed.append(did)
                    continue
                self._audit(
                    "phone.unpair.retry_failed",
                    device_id=did,
                    reason=str(exc),
                )
                continue
            self._registry.revoke(did)
            self._audit("phone.unpair.synced", device_id=did)
            flushed.append(did)
        return flushed

    def _read_plugin_state(self, verb: str) -> Any:
        state = self._read_state()
        device = self._select_device(state)
        plugins = device.get("state") or {}
        key = _STATE_READS[verb]
        if key not in plugins:
            raise PhoneLinkError(f"the device reported no {key} state")
        return plugins[key]

    def _find_device(
        self, state: Mapping[str, Any], device_id: str
    ) -> dict[str, Any] | None:
        for device in state.get("devices") or []:
            if str(device.get("id")) == str(device_id):
                return device
        return None

    def _select_device(
        self,
        state: Mapping[str, Any],
        *,
        refuse_unpaired: bool = False,
    ) -> dict[str, Any]:
        devices = list(state.get("devices") or [])
        if self.device_id:
            device = self._find_device(state, self.device_id)
            if device is None:
                raise PhoneLinkError(
                    f"the configured device {self.device_id} is not known to the sidecar"
                )
            if not device.get("paired"):
                if refuse_unpaired:
                    self._refuse(
                        "sms.send_sms",
                        f"device {self.device_id} is not paired;"
                        " the owner must pair it before sending",
                        device_id=str(self.device_id),
                    )
                raise PhoneLinkError(
                    f"the configured device {self.device_id} is not paired"
                )
            if not device.get("reachable"):
                raise PhoneLinkError(
                    f"the configured device {self.device_id} is not reachable"
                )
            return device
        usable = [
            device
            for device in devices
            if device.get("paired") and device.get("reachable")
        ]
        if not usable:
            if refuse_unpaired:
                self._refuse(
                    "sms.send_sms",
                    "no paired and reachable device — the owner must pair the phone",
                )
            raise PhoneLinkError(
                "no paired and reachable device — the owner must pair the phone"
            )
        if len(usable) > 1:
            raise PhoneLinkError(
                "several paired devices are connected; configure one explicitly"
            )
        return usable[0]

    def _call_plugin(
        self,
        plugin: str,
        action: str,
        args: Mapping[str, Any],
        *,
        device: str | None = None,
    ) -> Any:
        if _is_forbidden(f"{plugin}.{action}"):
            self._refuse(f"{plugin}.{action}", "it is on the never-allowlist list")
        if device is not None:
            requested = str(device).strip()
            if not requested:
                self._refuse(
                    f"{plugin}.{action}",
                    "explicit device argument was empty; refusing",
                    device_id=str(device),
                    configured_device_id=self.device_id,
                )
            if self.device_id is not None and requested != self.device_id:
                self._refuse(
                    f"{plugin}.{action}",
                    f"explicit device {requested!r} differs from configured"
                    f" device binding {self.device_id!r}; refusing to override"
                    " configured device",
                    device_id=requested,
                    configured_device_id=self.device_id,
                )
            device_id = requested
        else:
            device_id = str(self._select_device(self._read_state()).get("id"))
        return self._transport.call(
            "device.call",
            {"device": device_id, "plugin": plugin, "action": action, "args": dict(args)},
            timeout=self.request_timeout,
        )

    def _resolve_draft(self, draft: DraftRecord | str, store: Any) -> DraftRecord:
        """The stored draft is authoritative: the sent body is the stored body."""
        if isinstance(draft, str):
            if store is None:
                raise PhoneLinkError("a draft id can only be resolved through the store")
            stored = store.get(draft)
            if stored is None:
                raise PhoneLinkError(f"no draft {draft!r} in the store")
            return stored
        if store is not None:
            stored = store.get(getattr(draft, "draft_id", ""))
            if stored is None:
                raise PhoneLinkError("the draft is not in the store")
            if stored.body != draft.body or stored.recipient != draft.recipient:
                raise PhoneLinkError(
                    "the draft in the store differs from the draft handed over; refusing"
                )
            return stored
        return draft

    def _audit(self, event: str, **fields: Any) -> None:
        if self._journal is None:
            return
        try:
            self._journal(event, **fields)
        except Exception:
            log.exception("journal write failed for %s", event)


def _need(params: Mapping[str, Any], key: str) -> Any:
    if key not in params or params[key] in (None, ""):
        raise PhoneLinkError(f"the {key} parameter is required")
    return params[key]


def _thread_id(params: Mapping[str, Any]) -> int:
    """The KDE Connect thread id is NUMERIC.

    Upstream's sms plugin does ``int(thread_id)`` on the value it is handed,
    so a non-numeric id fails inside the sidecar. The adapter converts it
    here instead: the number goes out, and a bad id is refused LOCALLY with
    a message that names the fault.
    """
    raw = _need(params, "thread_id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise PhoneLinkError(
            "the thread id must be the numeric KDE Connect thread id"
            f" (the value sms.conversations reports), not {raw!r}"
        ) from None
