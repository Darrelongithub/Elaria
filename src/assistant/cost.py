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


# Failure categories, matched in order. The point is not taxonomy for its own
# sake: "5 failures" must be attributable to a known key/voice problem or show
# up as a Live transport failure, never remain a mystery count (BUG6).
FAILURE_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("key", ("api key", "api_key", "api-key", "unauthenticated", "permission denied",
             "401", "403", "invalid_argument: api key", "credentials")),
    ("voice", ("voice name", "voice is not supported", "voice not supported",
               "prebuilt_voice", "speech_config")),
    ("quota", ("429", "resource_exhausted", "rate limit", "quota", "too-many-requests",
               "daily soft cap")),
    ("network", ("network is unreachable", "network unreachable", "timed out", "timeout",
                 "connection reset", "connection refused", "name resolution",
                 "temporary failure in name resolution", "ssl")),
    ("live_transport", ("live connect", "live send", "live reconnect", "goaway",
                        "go away", "no transcript produced", "rotation limit",
                        "session resume", "live session")),
    ("parse", ("json", "decode", "parse", "schema")),
]


def classify_failure(error: str | None) -> str:
    """Coarse, stable category for a ledger failure row."""
    lowered = (error or "").lower()
    for label, needles in FAILURE_CATEGORIES:
        if any(needle in lowered for needle in needles):
            return label
    return "unknown"


def summarise_failures(rows: list[dict] | None) -> dict:
    """Counts by category plus whether anything Live failed.

    `rows` are `Store.failure_summary_since` rows. An untagged row is reported
    as such — it is a ledger bug, not a category.
    """
    rows = rows or []
    by_category: dict[str, int] = {}
    untagged: list[dict] = []
    live_failures: list[dict] = []
    for row in rows:
        category = classify_failure(row.get("error"))
        count = int(row.get("n") or 0)
        by_category[category] = by_category.get(category, 0) + count
        if not row.get("purpose") or row.get("purpose") == "(untagged)":
            untagged.append(row)
        purpose = str(row.get("purpose") or "")
        model = str(row.get("model") or "")
        if (category == "live_transport"
                or "transcribe_live" in purpose
                or "transcribe-live" in model):
            live_failures.append(row)
    return {
        "total": sum(int(r.get("n") or 0) for r in rows),
        "by_category": by_category,
        "live_failures": sum(int(r.get("n") or 0) for r in live_failures),
        "untagged": sum(int(r.get("n") or 0) for r in untagged),
        "rows": rows,
    }


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
    # BUG3: breakdown by purpose — user turns vs housekeeping
    purpose_rows = month.get("by_purpose") or today.get("by_purpose")
    if purpose_rows:
        lines.append("By purpose:")
        for row in purpose_rows:
            lines.append(f"  {row['purpose']}: {row['calls']} call(s), {row['tokens']:,} tokens, shadow ${row['cost_usd']:.4f}")
    elif today.get("by_purpose"):
        lines.append("By purpose:")
        for k, v in today["by_purpose"].items():
            lines.append(f"  {k}: {v} call(s)")
    # BUG6 cost audit: failures must be attributable, not just counted.
    failure_rows = month.get("failures_detail") or []
    if month.get("failures") or failure_rows:
        summary = summarise_failures(failure_rows)
        if summary["total"]:
            parts = ", ".join(f"{label} {n}" for label, n in
                              sorted(summary["by_category"].items(),
                                     key=lambda item: (-item[1], item[0])))
            lines.append(f"Failures this month: {summary['total']} ({parts})")
            if summary["live_failures"]:
                lines.append(
                    f"  LIVE failures: {summary['live_failures']} — these are not "
                    "key/voice housekeeping; see rows below")
            else:
                lines.append("  none from the Live dictation path")
            for row in failure_rows:
                error = " ".join(str(row.get("error") or "").split())
                if len(error) > 140:
                    error = error[:137] + "…"
                lines.append(
                    f"  {row.get('purpose')} [{row.get('mode')}] "
                    f"{classify_failure(row.get('error'))}: {row.get('n')}× {error}")
            if summary["untagged"]:
                lines.append(
                    f"  WARNING: {summary['untagged']} failure(s) carry no purpose tag "
                    "— ledger bug, not a call category")
        else:
            lines.append(f"Failures this month: {month.get('failures')} "
                         "(no error detail recorded — pre-BUG6 ledger rows)")
    # Explicit user vs housekeeping split
    if "user_turn_calls" in today:
        lines.append(f"Today breakdown: {today.get('user_turn_calls',0)} user turn(s) · {today.get('housekeeping_calls',0)} housekeeping call(s) (housekeeping does not count toward quota)")
    if today.get("by_purpose") and isinstance(today["by_purpose"], dict):
        # dict case from _cost
        pass
    # Bug 8: generated replies that never reached the user must be VISIBLE —
    # silent replacement hid the canned-fallback bug behind a working ledger.
    substitutions = today.get("reply_substitutions") or []
    if substitutions:
        lines.append(
            f"Reply substitutions (generated text NOT delivered): "
            f"{len(substitutions)} recorded")
        for sub in substitutions[:5]:
            reason = sub.get("reason") or "?"
            rule = f" rule={sub['rule']}" if sub.get("rule") else ""
            length = ("original_len=pending"
                      if sub.get("original_len") is None
                      else f"original_len={sub['original_len']}")
            turn = f" · turn={str(sub.get('turn') or '')[:40]!r}" if sub.get("turn") else ""
            lines.append(f"  {sub.get('ts', '')} [{reason}]{rule} {length}{turn}")
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
