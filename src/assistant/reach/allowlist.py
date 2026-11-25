"""Closed v0 egress allowlist, hard denylist, URL hygiene, and DNS IP pinning."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from .contract import ReachConfig, ReachError, TerminalOutcome

ALLOWED_CONTENT_TYPES = frozenset({
    "text/html",
    "text/plain",
    "text/markdown",
    "application/json",
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
})

FEED_CONTENT_TYPES = frozenset({
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
})

LOGIN_WALLED_DOMAINS = frozenset({
    "x.com",
    "twitter.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "reddit.com",
    "youtube.com",
    "pinterest.com",
    "quora.com",
})

DENIED_HOST_SUFFIXES = (".local", ".internal", ".home.arpa", ".localhost")

# Explicit CGNAT range 100.64.0.0/10 (RFC 6598) + AWS/cloud metadata 169.254.169.254
_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")
_METADATA_IP = ipaddress.ip_address("169.254.169.254")


@dataclass(frozen=True)
class ChannelSpec:
    name: str
    methods: frozenset[str]
    exact_hosts: frozenset[str] | None  # None = open-public (subject to denylist & config)
    content_types: frozenset[str]
    require_no_auth: bool = True


CHANNELS_V0: dict[str, ChannelSpec] = {
    "github": ChannelSpec(
        name="github",
        methods=frozenset({"GET"}),
        exact_hosts=frozenset({"api.github.com"}),
        content_types=frozenset({"application/json"}),
        require_no_auth=True,
    ),
    "web": ChannelSpec(
        name="web",
        methods=frozenset({"GET", "HEAD"}),
        exact_hosts=None,
        content_types=ALLOWED_CONTENT_TYPES,
        require_no_auth=True,
    ),
    "news": ChannelSpec(
        name="news",
        methods=frozenset({"GET"}),
        exact_hosts=None,
        content_types=FEED_CONTENT_TYPES,
        require_no_auth=True,
    ),
}


def normalize_host(host: str) -> str:
    """Lowercase, strip trailing dot, and punycode-normalise (IDNA)."""
    raw = str(host or "").strip().rstrip(".").lower()
    if not raw:
        raise ReachError(TerminalOutcome.DENIED, "empty host")
    try:
        ascii_host = raw.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ReachError(TerminalOutcome.DENIED, f"invalid IDNA host {host!r}: {exc}") from exc
    return ascii_host


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def validate_ip_address(ip_str: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Fail-closed: only globally routable public IPs are permitted."""
    try:
        addr = ipaddress.ip_address(ip_str.strip("[]"))
    except ValueError as exc:
        raise ReachError(TerminalOutcome.DENIED, f"invalid IP {ip_str!r}") from exc

    if addr == _METADATA_IP:
        raise ReachError(TerminalOutcome.DENIED, f"metadata IP {addr} is denied")
    if addr.version == 4 and addr in _CGNAT_NET:
        raise ReachError(TerminalOutcome.DENIED, f"CGNAT IP {addr} is denied")
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or not addr.is_global
    ):
        raise ReachError(TerminalOutcome.DENIED, f"non-public IP {addr} is denied")
    return addr


def _is_login_walled(host: str) -> bool:
    for domain in LOGIN_WALLED_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return True
    return False


def check_host_denylist(host: str) -> None:
    """Enforce hard denylist on a punycode-normalised host."""
    if host == "localhost" or any(host.endswith(suf) for suf in DENIED_HOST_SUFFIXES):
        raise ReachError(TerminalOutcome.DENIED, f"internal/local host {host!r} is denied")
    if is_ip_literal(host):
        validate_ip_address(host)
        raise ReachError(TerminalOutcome.DENIED, f"direct IP literal {host!r} is denied; use a public hostname")
    if "." not in host:
        raise ReachError(TerminalOutcome.DENIED, f"bare single-label host {host!r} is denied")
    if _is_login_walled(host):
        raise ReachError(TerminalOutcome.PLATFORM_BLOCKED, f"platform {host!r} is login-walled")


def validate_url(
    url: str,
    *,
    channel: str = "web",
    method: str = "GET",
    config: ReachConfig | None = None,
) -> tuple[str, str, ChannelSpec]:
    """Validate URL hygiene, channel membership, and denylist.

    Returns ``(normalized_url, normalized_host, ChannelSpec)``.
    """
    if channel not in CHANNELS_V0:
        raise ReachError(TerminalOutcome.DENIED, f"unknown channel {channel!r}")
    spec = CHANNELS_V0[channel]
    method_up = str(method or "").upper()
    if method_up not in spec.methods:
        raise ReachError(TerminalOutcome.DENIED, f"method {method_up!r} not allowed on channel {channel!r}")

    parts = urlsplit(str(url or "").strip())
    if parts.scheme.lower() != "https":
        raise ReachError(TerminalOutcome.DENIED, f"only https:// is allowed, got {parts.scheme!r}")
    if parts.username is not None or parts.password is not None:
        raise ReachError(TerminalOutcome.DENIED, "userinfo in URL is denied")
    if parts.port is not None and parts.port != 443:
        raise ReachError(TerminalOutcome.DENIED, f"non-443 port {parts.port} is denied")
    if not parts.hostname:
        raise ReachError(TerminalOutcome.DENIED, "URL has no hostname")

    host = normalize_host(parts.hostname)
    check_host_denylist(host)

    if spec.exact_hosts is not None and host not in spec.exact_hosts:
        raise ReachError(TerminalOutcome.DENIED, f"host {host!r} not in channel {channel!r} allowlist")

    if channel == "web" and config is not None and config.web_host_mode == "named-hosts":
        allowed = {normalize_host(h) for h in config.allowed_web_hosts}
        if host not in allowed:
            raise ReachError(TerminalOutcome.DENIED, f"host {host!r} not in [reach] allowed_web_hosts")

    normalized = urlunsplit(("https", host, parts.path or "/", parts.query, ""))
    return normalized, host, spec


ResolverFn = Callable[[str, int], list[str]]


def default_resolver(host: str, port: int = 443) -> list[str]:
    """Resolve ``host`` once via ``socket.getaddrinfo`` and return unique IP strings."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        if ip not in ips:
            ips.append(ip)
    return ips


def resolve_and_pin(
    host: str,
    port: int = 443,
    *,
    resolver: ResolverFn | None = None,
) -> list[str]:
    """Resolve ``host`` once and require ALL returned IPs to be public."""
    fn = resolver or default_resolver
    try:
        ips = fn(host, port)
    except OSError as exc:
        raise ReachError(TerminalOutcome.OFFLINE, f"DNS resolution failed for {host!r}: {exc}") from exc
    if not ips:
        raise ReachError(TerminalOutcome.OFFLINE, f"DNS returned no addresses for {host!r}")
    for ip in ips:
        validate_ip_address(ip)
    return ips
