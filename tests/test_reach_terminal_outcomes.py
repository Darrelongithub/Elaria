"""Eye-check 4: Terminal outcomes are journaled, plain-worded, and never evaded."""

from __future__ import annotations

import httpx

from assistant.reach import RateLimiter, ReachConfig, TerminalOutcome, fetch
from assistant.safety_journal import JournalLog


def _resolver(_h: str, _p: int = 443) -> list[str]:
    return ["93.184.216.34"]


def test_http_401_and_soft_login_wall_return_need_login(tmp_path):
    journal = JournalLog(tmp_path / "journal.jsonl")

    def h401(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(401, text="Unauthorized")

    r1 = fetch(
        "https://example.com/private",
        journal=journal,
        config=ReachConfig(enabled=True),
        resolver=_resolver,
        transport=httpx.MockTransport(h401),
    )
    assert r1.ok is False and r1.terminal == TerminalOutcome.NEED_LOGIN
    assert "login" in r1.plain_message.lower()

    def h_soft(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body><form><input type='password'/>Sign in</form></body></html>",
        )

    r2 = fetch(
        "https://example.com/softwall",
        journal=journal,
        config=ReachConfig(enabled=True),
        resolver=_resolver,
        transport=httpx.MockTransport(h_soft),
    )
    assert r2.ok is False and r2.terminal == TerminalOutcome.NEED_LOGIN


def test_robots_disallow_and_unreachable_fail_closed(tmp_path):
    journal = JournalLog(tmp_path / "journal.jsonl")

    def h_disallow(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /secret\n")
        return httpx.Response(200, text="should not be fetched")

    r1 = fetch(
        "https://example.com/secret/data",
        journal=journal,
        config=ReachConfig(enabled=True),
        resolver=_resolver,
        transport=httpx.MockTransport(h_disallow),
    )
    assert r1.ok is False and r1.terminal == TerminalOutcome.ROBOTS_DISALLOWED

    def h_503(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    r2 = fetch(
        "https://example.com/anything",
        journal=journal,
        config=ReachConfig(enabled=True),
        resolver=_resolver,
        transport=httpx.MockTransport(h_503),
    )
    assert r2.ok is False and r2.terminal == TerminalOutcome.ROBOTS_UNREACHABLE


def test_rate_limit_is_terminal(tmp_path):
    journal = JournalLog(tmp_path / "journal.jsonl")
    limiter = RateLimiter()
    cfg = ReachConfig(enabled=True, github_req_per_hr=1)

    def h_ok(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, headers={"content-type": "application/json"}, text='{"ok": true}')

    r1 = fetch(
        "https://api.github.com/zen",
        channel="github",
        journal=journal,
        config=cfg,
        limiter=limiter,
        resolver=_resolver,
        transport=httpx.MockTransport(h_ok),
    )
    assert r1.ok is True

    r2 = fetch(
        "https://api.github.com/zen",
        channel="github",
        journal=journal,
        config=cfg,
        limiter=limiter,
        resolver=_resolver,
        transport=httpx.MockTransport(h_ok),
    )
    assert r2.ok is False and r2.terminal == TerminalOutcome.RATE_LIMITED
