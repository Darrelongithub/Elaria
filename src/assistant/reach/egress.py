"""REACH Phase-0 egress gauntlet — single-hop validated, journal-first, fail-closed."""

from __future__ import annotations

import time
import urllib.robotparser
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from threading import Lock
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
from .observe import (
    begin_fetch,
    finish_fetch,
    journal_target,
    record_untrusted_load,
    request_actions,
)

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
        max_bytes: int,
        deadline: float,
    ) -> None:
        now = self._now()
        cached = self._cache.get(host)
        if cached is not None and (now - cached[0]) < self._ttl_s:
            rp = cached[1]
            if not rp.can_fetch(user_agent, url):
                raise ReachError(TerminalOutcome.ROBOTS_DISALLOWED, "target path disallowed by robots.txt")
            return

        robots_url = f"https://{host}/robots.txt"
        try:
            resp = _request(client, "GET", robots_url, {"User-Agent": user_agent},
                            max_bytes, deadline)
        except (httpx.HTTPError, httpx.InvalidURL, ReachError) as exc:
            raise ReachError(TerminalOutcome.ROBOTS_UNREACHABLE,
                             "could not read robots.txt") from exc

        if resp.status_code in (401, 407):
            raise ReachError(TerminalOutcome.NEED_LOGIN, f"robots.txt returned {resp.status_code}")
        if resp.status_code == 403:
            raise ReachError(TerminalOutcome.PLATFORM_BLOCKED, "robots.txt returned 403")
        if resp.status_code == 429:
            raise ReachError(TerminalOutcome.RATE_LIMITED, "robots.txt returned 429")
        # BUG-C1: never mistake a redirect for an empty allow-all ruleset.
        # Do not follow it: an unresolved robots policy fails closed.
        if resp.status_code not in (200, 404):
            raise ReachError(TerminalOutcome.ROBOTS_UNREACHABLE,
                             f"robots.txt returned {resp.status_code}")

        rp = urllib.robotparser.RobotFileParser()
        if resp.status_code == 404:
            rp.parse([])
        else:
            rp.parse(resp.text.splitlines())
        self._cache[host] = (now, rp)
        if not rp.can_fetch(user_agent, url):
            raise ReachError(TerminalOutcome.ROBOTS_DISALLOWED, "target path disallowed by robots.txt")


def channel_limit(config: ReachConfig, channel: str) -> int:
    if channel == "github":
        return config.github_req_per_hr
    if channel == "news":
        return config.news_req_per_hr
    return config.web_req_per_hr



# The cap check and its write-ahead charge are atomic within the daemon.
_ADMISSION_LOCK = Lock()


def _journal_allows(journal: JournalLog, channel: str, limit: int) -> bool:
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    used = sum(
        row["detail"].get("channel") == channel
        and row["detail"].get("charged") is True
        and datetime.fromisoformat(row["ts"]) > cutoff
        for row in request_actions(journal)
    )
    return used < limit


class _PinnedTransport(httpx.HTTPTransport):
    """Dial only the validated IP; keep the original Host and TLS identity.

    Each instance serves one origin/hop only (including its robots check).
    No environmental proxy, connection retries, or DNS re-resolution of the host.
    """

    def __init__(self, ip: str):
        super().__init__(trust_env=False, retries=0)
        self.ip = ip

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        pinned = httpx.Request(
            request.method, request.url.copy_with(host=self.ip), headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": request.url.host},
        )
        return super().handle_request(pinned)


def _request(client: httpx.Client, method: str, url: str, headers: dict,
             max_bytes: int, deadline: float) -> httpx.Response:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ReachError(TerminalOutcome.TIMEOUT, "fetch deadline reached")
    client.cookies.clear()  # no site cookies on subsequent requests
    with client.stream(method, url, headers={**headers, "Accept-Encoding": "identity"},
                       timeout=httpx.Timeout(remaining, connect=min(
                           remaining, client.timeout.connect))) as response:
        if not response.is_success:
            return response  # classify the status without downloading its body
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise ReachError(TerminalOutcome.BAD_CONTENT, "unexpected content encoding")
        body = bytearray()
        for chunk in response.iter_bytes():
            if time.monotonic() >= deadline:
                raise ReachError(TerminalOutcome.TIMEOUT, "fetch deadline reached")
            if len(body) + len(chunk) > max_bytes:
                raise ReachError(TerminalOutcome.TOO_LARGE, "response exceeds the byte cap")
            body.extend(chunk)
        return httpx.Response(response.status_code, headers=response.headers, content=bytes(body))


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
    halted: bool = False,
) -> FetchResult:
    """Execute one bounded, journal-first, fail-closed fetch."""
    cfg = config or ReachConfig(enabled=True)
    robots = robots_cache or RobotsCache(ttl_s=cfg.robots_cache_ttl_s)
    ua = f"Elaria-Reach/0.1 (+{cfg.user_agent_contact})"
    timeout = httpx.Timeout(cfg.total_timeout_s, connect=cfg.connect_timeout_s)
    max_bytes = min(cfg.max_wire_bytes, cfg.max_decoded_bytes)
    deadline = time.monotonic() + cfg.total_timeout_s
    method = method.upper()
    target = journal_target(url)
    action_id: str | None = None
    closing = False
    pinned: list[dict] = []

    def close(terminal: TerminalOutcome, detail: dict) -> None:
        nonlocal closing
        closing = True
        try:
            if pinned:
                detail = {**detail, "pinned": pinned}
            finish_fetch(journal, action_id, terminal=terminal, detail=detail)
        except Exception as exc:
            raise ReachError(TerminalOutcome.JOURNAL_FAILED,
                             "could not record terminal outcome") from exc

    try:
        if halted:
            raise ReachError(TerminalOutcome.DENIED, "assistant is halted")
        if not cfg.enabled:
            raise ReachError(TerminalOutcome.DENIED, "reach disabled in config")
        if cfg.offline:
            raise ReachError(TerminalOutcome.OFFLINE, "reach is in offline mode")
        current_url, host, spec = validate_url(url, channel=channel, method=method, config=cfg)

        with _ADMISSION_LOCK:
            limit = channel_limit(cfg, channel)
            try:
                allowed = (limiter.allow(channel, limit) if limiter is not None
                           else _journal_allows(journal, channel, limit))
            except Exception as exc:
                raise ReachError(TerminalOutcome.JOURNAL_FAILED,
                                 "could not read channel usage") from exc
            if not allowed:
                raise ReachError(TerminalOutcome.RATE_LIMITED, f"channel {channel!r} hourly cap reached")
            # Fsync intent and charge BEFORE DNS or HTTP can open a socket.
            action_id = begin_fetch(journal, url=target, channel=channel, method=method,
                                    detail={"charged": True})

        for hops in range(cfg.max_redirects + 1):
            if time.monotonic() >= deadline:
                raise ReachError(TerminalOutcome.TIMEOUT, "fetch deadline reached")
            # Check robots against the path HTTPX will actually request.
            # In particular, HTTPX removes dot segments from paths.
            try:
                current_url = str(httpx.URL(current_url))
            except httpx.InvalidURL as exc:
                raise ReachError(TerminalOutcome.DENIED, "malformed request URL") from exc
            ips = resolve_and_pin(host, 443, resolver=resolver)
            pinned.append({"host": host, "ips": ips[:4]})
            with httpx.Client(
                trust_env=False, follow_redirects=False, timeout=timeout,
                transport=transport if transport is not None else _PinnedTransport(ips[0]),
            ) as client:
                robots.check(current_url, host, user_agent=ua, client=client,
                             max_bytes=max_bytes, deadline=deadline)
                try:
                    resp = _request(client, method, current_url,
                                    {"User-Agent": ua, "Accept": ", ".join(sorted(spec.content_types))},
                                    max_bytes, deadline)
                except httpx.TimeoutException as exc:
                    raise ReachError(TerminalOutcome.TIMEOUT, "HTTP request timed out") from exc
                except httpx.InvalidURL as exc:
                    raise ReachError(TerminalOutcome.DENIED, "malformed request URL") from exc
                except httpx.HTTPError as exc:
                    raise ReachError(TerminalOutcome.OFFLINE, "HTTP request failed") from exc

            if resp.status_code not in (301, 302, 303, 307, 308):
                break
            if hops == cfg.max_redirects:
                raise ReachError(TerminalOutcome.DENIED, f"exceeded max_redirects={cfg.max_redirects}")
            loc = resp.headers.get("location")
            if not loc:
                raise ReachError(TerminalOutcome.BAD_CONTENT, "redirect without Location header")
            # Redirect text is untrusted and may not enter receipts or the journal.
            try:
                current_url, host, spec = validate_url(
                    urljoin(current_url, loc), channel=channel, method=method, config=cfg,
                )
            except (ValueError, ReachError) as exc:
                terminal = exc.terminal if isinstance(exc, ReachError) else TerminalOutcome.DENIED
                raise ReachError(terminal, "redirect refused by egress policy") from exc
        else:
            raise ReachError(TerminalOutcome.DENIED, "invalid redirect limit")

        # Status classification (all non-OK are terminal)
        if resp.status_code in (401, 407):
            raise ReachError(TerminalOutcome.NEED_LOGIN, f"HTTP {resp.status_code}")
        if resp.status_code == 403:
            raise ReachError(TerminalOutcome.PLATFORM_BLOCKED, "HTTP 403")
        if resp.status_code == 429:
            raise ReachError(TerminalOutcome.RATE_LIMITED, "HTTP 429")
        if not resp.is_success:
            raise ReachError(TerminalOutcome.BAD_CONTENT, f"HTTP {resp.status_code}")

        raw_bytes = resp.content
        ctype_raw = resp.headers.get("content-type", "text/plain")
        ctype = ctype_raw.split(";", 1)[0].strip().lower()
        if ctype not in spec.content_types:
            raise ReachError(TerminalOutcome.BAD_CONTENT, f"response content type is not allowed for {channel!r}")

        if ctype == "text/html" and is_soft_login_wall(resp.text, resp.status_code):
            raise ReachError(TerminalOutcome.NEED_LOGIN, "soft login wall detected on 200 OK")

        try:
            title, text, excerpt = extract_content(
                raw_bytes, content_type=ctype, max_chars=cfg.max_extract_chars
            )
        except (ValueError, RecursionError) as exc:
            raise ReachError(TerminalOutcome.BAD_CONTENT, "content could not be extracted") from exc
        doc = FetchedDoc(
            url=url,
            final_url=str(urlsplit(current_url).geturl()),
            channel=channel,
            status_code=resp.status_code,
            content_type=ctype,
            title=title[:cfg.max_extract_chars],
            text=text,
            excerpt=excerpt,
        )
        try:
            record_untrusted_load(journal, doc, origin=origin)
        except Exception as exc:
            raise ReachError(TerminalOutcome.JOURNAL_FAILED,
                             "could not journal untrusted content") from exc
        close(TerminalOutcome.OK, {"status_code": resp.status_code, "sha256": doc.sha256})
        return FetchResult(
            ok=True,
            terminal=TerminalOutcome.OK,
            doc=doc,
            action_id=action_id,
            plain_message=plain_outcome_message(TerminalOutcome.OK),
        )

    except ReachError as exc:
        try:
            if action_id is None and exc.terminal != TerminalOutcome.JOURNAL_FAILED:
                # Terminal preflight refusals get a pair too, but do not use quota.
                action_id = begin_fetch(journal, url=target, channel=channel, method=method,
                                        detail={"charged": False})
            if action_id is not None and not closing:
                close(exc.terminal, {"reason": exc.detail[:300]})
        except ReachError as journal_error:
            exc = journal_error
        return FetchResult(
            ok=False,
            terminal=exc.terminal,
            reason=exc.detail,
            action_id=action_id,
            plain_message=plain_outcome_message(exc.terminal, exc.detail),
        )
