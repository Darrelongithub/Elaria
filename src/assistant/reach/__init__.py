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
from .summarise import ReachSummariser, summarisation_settings
from .surface import InterestingnessGate

__all__ = [
    "CHANNELS_V0",
    "REACH_ALLOWED_ORIGINS",
    "AccountRegistry",
    "ChannelSpec",
    "FetchResult",
    "FetchedDoc",
    "InterestingnessGate",
    "RateLimiter",
    "ReachAccount",
    "ReachConfig",
    "ReachError",
    "ReachSummariser",
    "RobotsCache",
    "TerminalOutcome",
    "fetch",
    "plain_outcome_message",
    "reconcile_outstanding",
    "summarisation_settings",
    "validate_url",
]
