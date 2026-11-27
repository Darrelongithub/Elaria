"""Daemon-facing REACH facade. No scheduler, model route or navigation loop."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ..cost import day_start_iso
from .allowlist import CHANNELS_V0
from .contract import FetchedDoc, FetchResult, ReachConfig
from .egress import RobotsCache, channel_limit, fetch
from .observe import is_request_action


class ReachService:
    def __init__(self, config, journal, *, is_offline, is_halted):
        self.config = ReachConfig.from_config(config)
        self.journal = journal
        self._is_offline = is_offline
        self._is_halted = is_halted
        self._robots = RobotsCache(ttl_s=self.config.robots_cache_ttl_s)
        interests = config.section("reach").get("interests", [])
        self.interests = [
            item.strip() for item in interests if isinstance(item, str) and item.strip()
        ] if isinstance(interests, list) else []

    async def fetch(
        self, url: str, *, channel: str = "web", time_budget_s: float | None = None,
    ) -> FetchResult:
        # Check runtime mode at worker entry, not before a queued thread starts.
        def run():
            config = replace(
                self.config,
                total_timeout_s=min(self.config.total_timeout_s, time_budget_s)
                if time_budget_s is not None else self.config.total_timeout_s,
                offline=self.config.offline or self._is_offline(),
            )
            return fetch(url, channel=channel, config=config, journal=self.journal,
                         robots_cache=self._robots, halted=self._is_halted())

        return await asyncio.to_thread(run)

    def status(self) -> dict:
        now = datetime.now(UTC)
        start = datetime.fromisoformat(day_start_iso(now))
        cutoff = now - timedelta(hours=1)
        channels = {name: {"cap_per_hour": channel_limit(self.config, name),
                           "used_today": 0, "used_last_hour": 0,
                           "last_terminal": None} for name in CHANNELS_V0}
        action_channels = {}
        for row in self.journal.records():
            if is_request_action(row):
                stats = channels.get(row["detail"].get("channel"))
                if stats is None:
                    continue
                action_channels[row["id"]] = stats
                if row["detail"].get("charged") is True:
                    ts = datetime.fromisoformat(row["ts"])
                    stats["used_today"] += ts >= start
                    stats["used_last_hour"] += ts > cutoff
            elif (stats := action_channels.get(row.get("action_id"))) and (
                terminal := row["detail"].get("terminal")
            ):
                stats["last_terminal"] = {
                    "terminal": terminal, "at": row["ts"], "action_id": row["action_id"],
                }
        return {"enabled": self.config.enabled, "halted": self._is_halted(),
                "offline": self.config.offline or self._is_offline(),
                "interestingness_enabled": self.config.enabled and bool(self.interests),
                "today_since": start.isoformat(), "channels": channels}


def attributed_excerpt(doc: FetchedDoc) -> dict:
    """Phase-0 local extract, explicitly a quote, never a verified claim."""
    return {"origin": "web", "trusted": False, "sources": [doc.final_url],
            "sha256": doc.sha256, "quoted_title": doc.title[:280],
            "quoted_excerpt": doc.excerpt[:280]}
