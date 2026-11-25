"""Eye-check 2: Closed v0 allowlist, hard denylist, and DNS IP pinning."""

from __future__ import annotations

import pytest

from assistant.reach import ReachConfig, ReachError, TerminalOutcome, validate_url
from assistant.reach.allowlist import resolve_and_pin


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://example.com/page",
        "https://example.com:8443/page",
        "https://user:pass@example.com/page",
        "https://localhost/admin",
        "https://printer.local/status",
        "https://meta.internal/secret",
        "https://router.home.arpa/",
        "https://intranet/page",
        "https://169.254.169.254/latest/meta-data/",
        "https://127.0.0.1/secret",
        "https://10.0.0.1/secret",
        "https://192.168.1.1/secret",
    ],
)
def test_denylist_blocks_non_public_and_unsafe_urls(bad_url):
    with pytest.raises(ReachError) as exc:
        validate_url(bad_url, channel="web", config=ReachConfig(enabled=True))
    assert exc.value.terminal == TerminalOutcome.DENIED


@pytest.mark.parametrize(
    "walled_url",
    [
        "https://x.com/elaria",
        "https://twitter.com/elaria",
        "https://www.instagram.com/elaria",
        "https://www.linkedin.com/in/elaria",
        "https://www.reddit.com/r/python",
    ],
)
def test_login_walled_platforms_blocked(walled_url):
    with pytest.raises(ReachError) as exc:
        validate_url(walled_url, channel="web", config=ReachConfig(enabled=True))
    assert exc.value.terminal == TerminalOutcome.PLATFORM_BLOCKED


def test_github_channel_exact_host_and_get_only():
    norm, host, _ = validate_url("https://api.github.com/repos/python/cpython", channel="github")
    assert host == "api.github.com"
    assert norm.startswith("https://api.github.com/")

    with pytest.raises(ReachError) as exc:
        validate_url("https://github.com/python/cpython", channel="github")
    assert exc.value.terminal == TerminalOutcome.DENIED

    with pytest.raises(ReachError) as exc:
        validate_url("https://api.github.com/repos/python/cpython", channel="github", method="POST")
    assert exc.value.terminal == TerminalOutcome.DENIED


def test_dns_rebinding_private_ip_rejected():
    with pytest.raises(ReachError) as exc:
        resolve_and_pin("evil.example", resolver=lambda _h, _p: ["93.184.216.34", "169.254.169.254"])
    assert exc.value.terminal == TerminalOutcome.DENIED
