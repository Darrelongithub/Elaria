"""Agent REACH — Phase-0 bounded, journal-first, untrusted-only internet fetcher."""

from .accounts import AccountRegistry, ReachAccount
from .allowlist import CHANNELS_V0, ChannelSpec, validate_url
from .contract import (
    REACH_ALLOWED_ORIGINS,
    FetchedDoc,
    FetchResult,
    ReachConfig,
    ReachError,
    TerminalOutcome,
)
from .egress import RateLimiter, RobotsCache, fetch, plain_outcome_message
from .observe import reconcile_outstanding
from .surface import InterestingnessGate

__all__ = [
    "AccountRegistry",
    "CHANNELS_V0",
    "ChannelSpec",
    "FetchedDoc",
    "FetchResult",
    "InterestingnessGate",
    "REACH_ALLOWED_ORIGINS",
    "RateLimiter",
    "ReachAccount",
    "ReachConfig",
    "ReachError",
    "RobotsCache",
    "TerminalOutcome",
    "fetch",
    "plain_outcome_message",
    "reconcile_outstanding",
    "validate_url",
]
