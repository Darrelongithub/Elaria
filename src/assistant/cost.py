"""Cost accounting — Phase 0, not later (§1.5, §3.2).

Budget is $0 (§0): on the free tier nothing is billed, so `billed_usd` is
always 0.00 and the numbers that matter are REQUESTS and TOKENS against
quota (§12.1). We still compute a "shadow cost" at paid rates for every
call — it's what turns a future pricing change (§7: Flash promo pricing
ends 2026-12-31) into a line in a report instead of a surprise.

Rates are USD per 1M tokens, from §3.2/§7 (Oct 2026). They are data, not
truth: `assist doctor` flags them for re-verification alongside the quota
shape. Audio bills at 25 tokens/second (§7).
"""

from __future__ import annotations

from datetime import UTC, datetime

# (input, output) USD per 1M tokens. Matched by substring, cheapest first.
PRICES_PER_1M: list[tuple[str, float, float]] = [
    ("flash-lite", 0.25, 1.50),
    ("transcribe-live", 3.00, 3.00),   # live audio-in ~$3/1M (§7)
    ("flash", 0.75, 3.75),             # promo pricing through 2026-12-31 (§7)
    ("pro", 2.00, 12.00),              # paid-only since Apr 2026 (§12.1)
]

AUDIO_TOKENS_PER_SECOND = 25


def rates_for(model: str) -> tuple[float, float]:
    lowered = model.lower()
    for needle, rate_in, rate_out in PRICES_PER_1M:
        if needle in lowered:
            return rate_in, rate_out
    return 0.75, 3.75  # unknown model: assume flash-class, visible in ledger


def shadow_cost_usd(model: str, tokens_in: int, tokens_out: int, audio_seconds: float = 0.0) -> float:
    rate_in, rate_out = rates_for(model)
    audio_tokens = audio_seconds * AUDIO_TOKENS_PER_SECOND
    return ((tokens_in + audio_tokens) * rate_in + tokens_out * rate_out) / 1_000_000


def estimate_tokens(text: str) -> int:
    """Rough token estimate when the API/mock gives no usage metadata.

    Marked `tokens_estimated=1` in the ledger so estimates are never
    mistaken for measured usage.
    """
    return max(1, len(text) // 4) if text else 0


def iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def month_start_iso(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def day_start_iso(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def format_cost_report(month: dict, today: dict, quota: dict, tier: str = "free") -> str:
    """Human `assist cost` output. Free tier: billed $0, quota is the story."""
    cap_day = quota.get("max_requests_per_day", 1200)
    lines = [
        f"Tier: {tier} — billed this month: $0.00 (free tier bills nothing; quota is the budget)",
        f"Shadow cost at paid rates (what this would bill off free tier): ${month['cost_usd']:.4f}",
        (f"This month: {month['calls']} call(s), {month['tokens_in']:,} in / "
         f"{month['tokens_out']:,} out tokens, {month['audio_seconds']:.0f}s audio, "
         f"{month['failures']} failure(s)"),
        (f"Today: {today['calls']} call(s) "
         f"({today.get('live_calls', 0)} live against soft cap {cap_day}/day)"),
    ]
    if month["by_model"]:
        lines.append("By model:")
        for row in month["by_model"]:
            lines.append(
                f"  {row['model']} [{row['mode']}]: {row['calls']} call(s), "
                f"{row['tokens']:,} tokens, shadow ${row['cost_usd']:.4f}"
            )
    from .config import quota_is_verified, quota_rows

    if quota_is_verified(quota):
        rows = quota_rows(quota)
        summary = " · ".join(
            f"{row['model']}: "
            + ("unlimited RPM" if row["unlimited_rpm"] else f"{row['rpm']} RPM")
            + " / "
            + (f"{int(row['tpm']):,} TPM" if row.get("tpm") not in (None, "")
               else "TPM n/a")
            + " / "
            + ("unlimited RPD" if row["unlimited_rpd"] else f"{row['rpd']} RPD")
            for row in rows)
        lines.append(f"Quota: VERIFIED {quota.get('verified_at', '')} — {summary} "
                     "(from [quota] in config; not assumed).")
    else:
        lines.append(
            "Reminder: quota shape in config is ASSUMED until verified at "
            "aistudio.google.com/rate-limit (blueprint §11).")
    return "\n".join(lines)
