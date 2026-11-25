"""REACH Phase-0 egress gauntlet — single-hop validated, journal-first, fail-closed."""

from __future__ import annotations

import time
import urllib.robotparser
from collections import defaultdict, deque
from urllib.parse import urljoin, urlsplit

import httpx

from ..safety_journal import JournalLog
from .allowlist import (
    ResolverFn,
    resolve_and_pin,
    validate_url,
)
from .contract import (
    FetchedDoc,
    FetchResult,
    ReachConfig,
    ReachError,
    TerminalOutcome,
)
from .extract import extract_content, is_soft_login_wall
from .observe import begin_fetch, finish_fetch, record_untrusted_load

_PLAIN_MESSAGES: dict[TerminalOutcome, str] = {
    TerminalOutcome.OK: "Fetched successfully.",
    TerminalOutcome.NEED_LOGIN: "This page requires a login; I cannot access it.",
    TerminalOutcome.PLATFORM_BLOCKED: "This platform blocked automated access.",
    TerminalOutcome.RATE_LIMITED: "Rate limit reached for this channel; stopping.",
    TerminalOutcome.ROBOTS_DISALLOWED: "Disallowed by the site's robots.txt.",
    TerminalOutcome.ROBOTS_UNREACHABLE: "Could not reach robots.txt; failing closed.",
    TerminalOutcome.OFFLINE: "Cannot reach the host (offline or unreachable).",
    TerminalOutcome.TIMEOUT: "The request timed out.",
    TerminalOutcome.TOO_LARGE: "The response exceeded the size limit.",
    TerminalOutcome.BAD_CONTENT: "Unsupported or invalid content type.",
    TerminalOutcome.JOURNAL_FAILED: "Could not write to the safety journal; aborted.",
    TerminalOutcome.DENIED: "Blocked by egress allowlist policy.",
}


def plain_outcome_message(terminal: TerminalOutcome, detail: str = "") -> str:
    base = _PLAIN_MESSAGES.get(terminal, terminal.value)
    return f"{base} ({detail})" if detail else base


class RateLimiter:
    """Sliding 1-hour per-channel request budget."""

    def __init__(self, *, now_fn=time.monotonic):
        self._now = now_fn
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, channel: str, limit_per_hour: int) -> bool:
        if limit_per_hour <= 0:
            return False
        now = self._now()
        cutoff = now - 3600.0
        q = self._hits[channel]
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= limit_per_hour:
            return False
        q.append(now)
        return True


class RobotsCache:
    """RFC 9309 robots.txt cache (<= 24h TTL, fail-closed on 5xx/unreachable)."""

    def __init__(self, *, ttl_s: float = 86_400.0, now_fn=time.monotonic):
        self._ttl_s = min(float(ttl_s), 86_400.0)
        self._now = now_fn
        self._cache: dict[str, tuple[float, urllib.robotparser.RobotFileParser]] = {}

    def check(
        self,
        url: str,
        host: str,
        *,
        user_agent: str,
        client: httpx.Client,
    ) -> None:
        now = self._now()
        cached = self._cache.get(host)
        if cached is not None and (now - cached[0]) < self._ttl_s:
            rp = cached[1]
            if not rp.can_fetch(user_agent, url):
                raise ReachError(TerminalOutcome.ROBOTS_DISALLOWED, f"robots.txt disallows {url}")
            return

        robots_url = f"https://{host}/robots.txt"
        try:
            resp = client.get(robots_url, headers={"User-Agent": user_agent})
        except httpx.TimeoutException as exc:
            raise ReachError(TerminalOutcome.ROBOTS_UNREACHABLE, f"robots.txt timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ReachError(TerminalOutcome.ROBOTS_UNREACHABLE, f"robots.txt unreachable: {exc}") from exc

        if resp.status_code in (401, 407):
            raise ReachError(TerminalOutcome.NEED_LOGIN, f"robots.txt returned {resp.status_code}")
        if resp.status_code == 403:
            raise ReachError(TerminalOutcome.PLATFORM_BLOCKED, "robots.txt returned 403")
        if resp.status_code >= 500:
            raise ReachError(TerminalOutcome.ROBOTS_UNREACHABLE, f"robots.txt returned {resp.status_code}")

        rp = urllib.robotparser.RobotFileParser()
        if resp.status_code == 404:
            rp.parse([])
        else:
            rp.parse(resp.text.splitlines())
        self._cache[host] = (now, rp)
        if not rp.can_fetch(user_agent, url):
            raise ReachError(TerminalOutcome.ROBOTS_DISALLOWED, f"robots.txt disallows {url}")


def _channel_limit(config: ReachConfig, channel: str) -> int:
    if channel == "github":
        return config.github_req_per_hr
    if channel == "news":
        return config.news_req_per_hr
    return config.web_req_per_hr


def fetch(
    url: str,
    *,
    channel: str = "web",
    method: str = "GET",
    journal: JournalLog,
    config: ReachConfig | None = None,
    limiter: RateLimiter | None = None,
    robots_cache: RobotsCache | None = None,
    resolver: ResolverFn | None = None,
    transport: httpx.BaseTransport | None = None,
    origin: str = "web",
) -> FetchResult:
    """Execute one bounded, journal-first, fail-closed fetch."""
    cfg = config or ReachConfig(enabled=True)
    if not cfg.enabled:
        return FetchResult(
            ok=False,
            terminal=TerminalOutcome.DENIED,
            reason="reach is disabled in config ([reach] enabled = false)",
            plain_message=plain_outcome_message(TerminalOutcome.DENIED, "reach disabled"),
        )
    if cfg.offline:
        return FetchResult(
            ok=False,
            terminal=TerminalOutcome.OFFLINE,
            reason="reach is in offline mode",
            plain_message=plain_outcome_message(TerminalOutcome.OFFLINE),
        )

    rate_limiter = limiter or RateLimiter()
    robots = robots_cache or RobotsCache(ttl_s=cfg.robots_cache_ttl_s)
    ua = f"Elaria-Reach/0.1 (+{cfg.user_agent_contact})"
    timeout = httpx.Timeout(cfg.total_timeout_s, connect=cfg.connect_timeout_s)

    action_id: str | None = None
    try:
        current_url, host, spec = validate_url(url, channel=channel, method=method, config=cfg)

        if not rate_limiter.allow(channel, _channel_limit(cfg, channel)):
            raise ReachError(TerminalOutcome.RATE_LIMITED, f"channel {channel!r} hourly cap reached")

        pinned_ips = resolve_and_pin(host, 443, resolver=resolver)

        # Journal-first: write-ahead fsynced action BEFORE any socket opens.
        action_id = begin_fetch(
            journal,
            url=current_url,
            channel=channel,
            method=method.upper(),
            detail={"pinned_ips": pinned_ips[:4]},
        )

        with httpx.Client(
            trust_env=False,
            verify=True,
            follow_redirects=False,
            timeout=timeout,
            transport=transport,
        ) as client:
            hops = 0
            while True:
                robots.check(current_url, host, user_agent=ua, client=client)

                try:
                    resp = client.request(
                        method.upper(),
                        current_url,
                        headers={"User-Agent": ua, "Accept": ", ".join(sorted(spec.content_types))},
                    )
                except httpx.TimeoutException as exc:
                    raise ReachError(TerminalOutcome.TIMEOUT, str(exc)) from exc
                except httpx.HTTPError as exc:
                    raise ReachError(TerminalOutcome.OFFLINE, str(exc)) from exc

                if resp.status_code in (301, 302, 303, 307, 308):
                    hops += 1
                    if hops > cfg.max_redirects:
                        raise ReachError(TerminalOutcome.DENIED, f"exceeded max_redirects={cfg.max_redirects}")
                    loc = resp.headers.get("location")
                    if not loc:
                        raise ReachError(TerminalOutcome.BAD_CONTENT, "redirect without Location header")
                    next_url = urljoin(current_url, loc)
                    current_url, host, spec = validate_url(
                        next_url, channel=channel, method=method, config=cfg
                    )
                    resolve_and_pin(host, 443, resolver=resolver)
                    continue
                break

        # Status classification (all non-OK are terminal)
        if resp.status_code in (401, 407):
            raise ReachError(TerminalOutcome.NEED_LOGIN, f"HTTP {resp.status_code}")
        if resp.status_code == 403:
            raise ReachError(TerminalOutcome.PLATFORM_BLOCKED, "HTTP 403")
        if resp.status_code == 429:
            raise ReachError(TerminalOutcome.RATE_LIMITED, "HTTP 429")
        if resp.status_code >= 400:
            raise ReachError(TerminalOutcome.BAD_CONTENT, f"HTTP {resp.status_code}")

        raw_bytes = resp.content
        if len(raw_bytes) > cfg.max_wire_bytes or len(raw_bytes) > cfg.max_decoded_bytes:
            raise ReachError(TerminalOutcome.TOO_LARGE, f"{len(raw_bytes)} bytes exceeds cap")

        ctype_raw = resp.headers.get("content-type", "text/plain")
        ctype = ctype_raw.split(";", 1)[0].strip().lower()
        if ctype not in spec.content_types:
            raise ReachError(TerminalOutcome.BAD_CONTENT, f"content-type {ctype!r} not allowed for {channel!r}")

        if ctype == "text/html" and is_soft_login_wall(resp.text, resp.status_code):
            raise ReachError(TerminalOutcome.NEED_LOGIN, "soft login wall detected on 200 OK")

        title, text, excerpt = extract_content(
            raw_bytes, content_type=ctype, max_chars=cfg.max_extract_chars
        )
        doc = FetchedDoc(
            url=url,
            final_url=str(urlsplit(current_url).geturl()),
            channel=channel,
            status_code=resp.status_code,
            content_type=ctype,
            title=title,
            text=text,
            excerpt=excerpt,
        )
        finish_fetch(
            journal,
            action_id,
            terminal=TerminalOutcome.OK,
            detail={"status_code": resp.status_code, "sha256": doc.sha256},
        )
        record_untrusted_load(journal, doc, origin=origin)
        return FetchResult(
            ok=True,
            terminal=TerminalOutcome.OK,
            doc=doc,
            action_id=action_id,
            plain_message=plain_outcome_message(TerminalOutcome.OK),
        )

    except ReachError as exc:
        if action_id is not None:
            finish_fetch(
                journal,
                action_id,
                terminal=exc.terminal,
                detail={"reason": exc.detail[:300]},
            )
        return FetchResult(
            ok=False,
            terminal=exc.terminal,
            reason=exc.detail,
            action_id=action_id,
            plain_message=plain_outcome_message(exc.terminal, exc.detail),
        )
