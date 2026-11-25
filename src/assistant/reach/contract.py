"""REACH Phase-0 contracts — terminal outcomes, untrusted FetchedDoc, and config.

Structural split (IF-6):
    Fetched content is untrusted data ONLY. ``FetchedDoc`` has ``trusted = False``
    as a read-only property and cannot be marked trusted. No module in
    ``assistant.reach`` may import ``hands.plan``, ``hands.runner``,
    ``hands.executor``, ``intents``, ``planner``, or ``executor``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum

from ..cost import iso_now
from ..hands.injection import DataInput

REACH_ALLOWED_ORIGINS = frozenset({"web", "retrieved"})


class TerminalOutcome(str, Enum):
    """All reach outcomes are terminal — never retried, mirrored, or evaded."""

    OK = "OK"
    NEED_LOGIN = "NEED_LOGIN"
    PLATFORM_BLOCKED = "PLATFORM_BLOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
    ROBOTS_UNREACHABLE = "ROBOTS_UNREACHABLE"
    OFFLINE = "OFFLINE"
    TIMEOUT = "TIMEOUT"
    TOO_LARGE = "TOO_LARGE"
    BAD_CONTENT = "BAD_CONTENT"
    JOURNAL_FAILED = "JOURNAL_FAILED"
    DENIED = "DENIED"


class ReachError(RuntimeError):
    """Raised only for programmer/contract errors, never to evade a terminal block."""

    def __init__(self, terminal: TerminalOutcome, detail: str):
        super().__init__(f"{terminal.value}: {detail}")
        self.terminal = terminal
        self.detail = detail


@dataclass(frozen=True)
class ReachConfig:
    """Runtime configuration for Phase-0 REACH (disabled by default)."""

    enabled: bool = False
    web_host_mode: str = "open-public"  # "open-public" | "named-hosts"
    allowed_web_hosts: tuple[str, ...] = ()
    github_req_per_hr: int = 30
    web_req_per_hr: int = 60
    news_req_per_hr: int = 30
    connect_timeout_s: float = 5.0
    total_timeout_s: float = 20.0
    max_redirects: int = 3
    max_wire_bytes: int = 2 * 1024 * 1024
    max_decoded_bytes: int = 8 * 1024 * 1024
    max_extract_chars: int = 16_000
    robots_cache_ttl_s: float = 86_400.0
    user_agent_contact: str = "elaria-reach@local"
    offline: bool = False

    @classmethod
    def from_config(cls, config) -> ReachConfig:
        sec = config.section("reach") if config is not None else {}
        hosts = sec.get("allowed_web_hosts") or ()
        if isinstance(hosts, str):
            hosts = (hosts,)
        return cls(
            enabled=bool(sec.get("enabled", False)),
            web_host_mode=str(sec.get("web_host_mode", "open-public")),
            allowed_web_hosts=tuple(str(h).strip().lower() for h in hosts if str(h).strip()),
            github_req_per_hr=int(sec.get("github_req_per_hr", 30)),
            web_req_per_hr=int(sec.get("web_req_per_hr", 60)),
            news_req_per_hr=int(sec.get("news_req_per_hr", 30)),
            connect_timeout_s=float(sec.get("connect_timeout_s", 5.0)),
            total_timeout_s=float(sec.get("total_timeout_s", 20.0)),
            max_redirects=int(sec.get("max_redirects", 3)),
            max_wire_bytes=int(sec.get("max_wire_bytes", 2 * 1024 * 1024)),
            max_decoded_bytes=int(sec.get("max_decoded_bytes", 8 * 1024 * 1024)),
            max_extract_chars=int(sec.get("max_extract_chars", 16_000)),
            robots_cache_ttl_s=float(sec.get("robots_cache_ttl_s", 86_400.0)),
            user_agent_contact=str(sec.get("user_agent_contact", "elaria-reach@local")),
            offline=bool(sec.get("offline", False)),
        )


@dataclass(frozen=True)
class FetchedDoc:
    """Provenance-tagged untrusted document produced by REACH.

    ``trusted`` is a read-only property that always returns ``False``.
    The only exits are ``DataInput(origin="web"|"retrieved")`` for planner
    observation, attributed quoting/summarising, or ``Memory.remember`` with
    ``source="inferred", kind="finding", confidence<=0.5``.
    """

    url: str
    final_url: str
    channel: str
    status_code: int
    content_type: str
    title: str
    text: str
    excerpt: str
    sha256: str = ""
    fetched_at: str = field(default_factory=iso_now)
    terminal: TerminalOutcome = TerminalOutcome.OK

    def __post_init__(self):
        if not self.sha256:
            digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
            object.__setattr__(self, "sha256", digest)

    @property
    def trusted(self) -> bool:
        """IF-6: fetched web content is NEVER trusted."""
        return False

    def to_data_input(self, origin: str = "web") -> DataInput:
        """Convert to a provenance-tagged ``DataInput`` for planner observation."""
        if origin not in REACH_ALLOWED_ORIGINS:
            raise ValueError(f"reach origin must be one of {sorted(REACH_ALLOWED_ORIGINS)}, got {origin!r}")
        return DataInput(origin=origin, text=self.text)

    def as_memory_kwargs(self, *, confidence: float = 0.4) -> dict:
        """Return safe kwargs for ``Memory.remember()`` (inferred, <=0.5, with evidence)."""
        capped = min(0.5, max(0.0, float(confidence)))
        summary = self.title.strip() or self.excerpt[:160].strip() or self.final_url
        return {
            "text": f"[{self.channel}] {summary}",
            "kind": "finding",
            "source": "inferred",
            "confidence": capped,
            "evidence": f"{self.final_url} (sha256:{self.sha256[:16]})",
        }


@dataclass(frozen=True)
class FetchResult:
    """Terminal result of a single ``reach.fetch()`` call."""

    ok: bool
    terminal: TerminalOutcome
    doc: FetchedDoc | None = None
    reason: str = ""
    action_id: str | None = None
    plain_message: str = ""
