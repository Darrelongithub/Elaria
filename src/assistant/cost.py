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

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import MappingProxyType

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
        if isinstance(purpose_rows, dict):
            for purpose, count in purpose_rows.items():
                lines.append(f"  {purpose}: {count} call(s)")
        else:
            for row in purpose_rows:
                lines.append(
                    f"  {row['purpose']}: {row['calls']} call(s), "
                    f"{row['tokens']:,} tokens, shadow ${row['cost_usd']:.4f}"
                )
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


# -- BUILD-8: per-provider quota rows and provider ledger ------------------
# Deliberately separate from `quota_rows()` above: the existing `[quota]`
# parser treats 0 as "unlimited" and its `verified` marker belongs to the
# owner's Gemini measurements. Neither may leak into a diverted provider's
# row. Unknown/absent/zero caps here mean UNAVAILABLE, never unlimited.

PROVIDER_LEDGER_COLUMNS: dict[str, str] = {
    "provider": "TEXT NOT NULL DEFAULT 'unknown'",
    "capability": "TEXT DEFAULT 'unknown'",
    "provider_request_id": "TEXT",
    "billing_unit": "TEXT",
    "billing_amount": "REAL",
    "cost_known": "INTEGER NOT NULL DEFAULT 0",
    "quota_bucket": "TEXT",
}
PENDING_MARK = "pending:provider_router"


class LedgerWriteError(RuntimeError):
    """A provider call was refused because its ledger row could not be written."""


@dataclass(frozen=True)
class ProviderModelCap:
    """Positive caps only. `None` means unknown/unavailable, never unlimited."""

    rpm: int | None = None
    tpm: int | None = None
    rpd: int | None = None
    tpd: int | None = None
    billing_unit: str = ""
    reset_tz: str = "UTC"

    def cap(self, unit: str) -> int | None:
        value = getattr(self, unit, None)
        return value if isinstance(value, (int, float)) and value > 0 else None


@dataclass(frozen=True)
class ProviderQuotaRow:
    provider: str
    enabled: bool = False
    verified: bool = False
    verified_at: str = ""
    verified_source: str = ""
    plan: str = ""
    terms_reviewed_at: str = ""
    no_card_required: bool = False
    data_use_policy: str = ""
    models: MappingProxyType[str, ProviderModelCap] = field(
        default_factory=lambda: MappingProxyType({}))

    @property
    def evidence_complete(self) -> bool:
        """Owner-account evidence that the design requires before enablement."""
        return bool(self.verified and self.no_card_required and self.verified_at
                    and self.verified_source and self.plan
                    and self.terms_reviewed_at and self.data_use_policy)

    @property
    def runnable(self) -> bool:
        return bool(self.enabled and self.evidence_complete and self.models)

    def cap_for(self, model: str) -> ProviderModelCap | None:
        return self.models.get(str(model).strip()) if self.runnable else None

    def as_dict(self) -> dict:
        return {
            "provider": self.provider, "enabled": self.enabled,
            "verified": self.verified,
            "verified_at": self.verified_at,
            "verified_source": self.verified_source, "plan": self.plan,
            "terms_reviewed_at": self.terms_reviewed_at,
            "no_card_required": self.no_card_required,
            "data_use_policy": self.data_use_policy,
            "evidence_complete": self.evidence_complete,
            "runnable": self.runnable,
            "models": {name: {"rpm": cap.rpm, "tpm": cap.tpm, "rpd": cap.rpd,
                              "tpd": cap.tpd, "billing_unit": cap.billing_unit,
                              "reset_tz": cap.reset_tz}
                       for name, cap in self.models.items()},
        }


_BOOL_KEYS = ("enabled", "verified", "no_card_required")
_TEXT_KEYS = ("verified_at", "verified_source", "plan", "terms_reviewed_at",
              "data_use_policy")
_CAP_KEYS = ("rpm", "tpm", "rpd", "tpd")


def _positive_cap(value, label: str, errors: list[str]) -> int | None:
    """Zero, absent, negative, 'unlimited' and bool are NOT positive caps."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        errors.append(f"{label}={value!r} must be a positive number or absent; "
                      "0 is unavailable, not unlimited")
        return None
    return int(value) if float(value).is_integer() else float(value)


def parse_provider_quota_rows(quota: dict) -> tuple[dict[str, ProviderQuotaRow], list[str]]:
    """Parse `[quota.providers.*]` with strict, provider-local verification.

    Does not read `[quota].verified`, `[quota.models.*]` or any Gemini figure.
    Returns `(rows, errors)`; an error makes that provider unrunnable.
    """
    from .model_registry import KNOWN_PROVIDER_IDS

    errors: list[str] = []
    rows: dict[str, ProviderQuotaRow] = {}
    if not isinstance(quota, dict):
        return rows, ["[quota] must be a table"]
    providers = quota.get("providers")
    if providers is None:
        return rows, errors
    if not isinstance(providers, dict):
        return rows, ["[quota.providers] must be a table"]
    for name, raw in providers.items():
        label = f"[quota.providers.{name}]"
        provider = str(name).strip()
        if provider not in KNOWN_PROVIDER_IDS:
            errors.append(f"{label} names unknown provider {name!r}")
            continue
        if not isinstance(raw, dict):
            errors.append(f"{label} must be a table")
            continue
        local_errors: list[str] = []
        unknown = set(raw) - (set(_BOOL_KEYS) | set(_TEXT_KEYS) | {"models"})
        if unknown:
            local_errors.append(f"{label} unknown keys: {', '.join(sorted(unknown))}")
        flags = {}
        for key in _BOOL_KEYS:
            value = raw.get(key, False)
            if not isinstance(value, bool):
                local_errors.append(f"{label} {key}={value!r} must be true or false")
                flags[key] = False
            else:
                flags[key] = value
        texts = {}
        for key in _TEXT_KEYS:
            value = raw.get(key, "")
            if not isinstance(value, str):
                local_errors.append(f"{label} {key} must be a string")
                texts[key] = ""
            else:
                texts[key] = value.strip()
        models: dict[str, ProviderModelCap] = {}
        model_rows = raw.get("models", {})
        if not isinstance(model_rows, dict):
            local_errors.append(f"{label} models must be a table")
            model_rows = {}
        for model_name, model_raw in model_rows.items():
            mlabel = f"{label}.models.{model_name}"
            if not isinstance(model_raw, dict):
                local_errors.append(f"{mlabel} must be a table")
                continue
            m_unknown = set(model_raw) - (set(_CAP_KEYS) | {"billing_unit", "reset_tz"})
            if m_unknown:
                local_errors.append(f"{mlabel} unknown keys: {', '.join(sorted(m_unknown))}")
            caps = {key: _positive_cap(model_raw.get(key), f"{mlabel}.{key}", local_errors)
                    for key in _CAP_KEYS}
            billing_unit = model_raw.get("billing_unit", "")
            reset_tz = model_raw.get("reset_tz", "UTC")
            if not isinstance(billing_unit, str) or not isinstance(reset_tz, str):
                local_errors.append(f"{mlabel} billing_unit/reset_tz must be strings")
                billing_unit, reset_tz = "", "UTC"
            models[str(model_name)] = ProviderModelCap(
                **caps, billing_unit=billing_unit.strip(), reset_tz=reset_tz.strip() or "UTC")
        errors.extend(local_errors)
        row = ProviderQuotaRow(
            provider=provider, enabled=flags["enabled"], verified=flags["verified"],
            no_card_required=flags["no_card_required"], models=MappingProxyType(models),
            verified_at=texts["verified_at"], verified_source=texts["verified_source"],
            plan=texts["plan"], terms_reviewed_at=texts["terms_reviewed_at"],
            data_use_policy=texts["data_use_policy"])
        if local_errors and row.enabled:
            # An invalid row must never be routable. Keep it visible to doctor,
            # with `enabled` retained so the error cannot be mistaken for off.
            row = replace(row, verified=False, no_card_required=False)
            errors.append(f"{label} is NOT runnable: fix the errors above")
        rows[provider] = row
    return rows, errors


def ensure_provider_ledger(store) -> dict:
    """Add provider columns, backfill provable rows, tag future Gemini rows.

    Backfill is deliberately narrow: only model ids that are provably Gemini
    get `provider='gemini'`. Everything else stays `unknown`; capability is
    `unknown` for old rows because purpose alone cannot prove personality.
    """
    conn, lock = store._conn, store._lock
    added: list[str] = []
    with lock:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(llm_calls)")}
        for name, ddl in PROVIDER_LEDGER_COLUMNS.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE llm_calls ADD COLUMN {name} {ddl}")
                added.append(name)
        conn.execute(
            "UPDATE llm_calls SET provider='gemini' "
            "WHERE provider='unknown' AND lower(model) LIKE 'gemini-%'")
        conn.execute(
            "UPDATE llm_calls SET capability='unknown' "
            "WHERE capability IS NULL OR capability=''")
        # Existing writers (gemini_client, asr, transcribe) live in other
        # owners' lanes. An AFTER-INSERT tag attributes their new rows to the
        # only transport they can reach, without editing those files.
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS llm_calls_tag_gemini
            AFTER INSERT ON llm_calls
            WHEN NEW.provider = 'unknown' AND lower(NEW.model) LIKE 'gemini-%'
            BEGIN
              UPDATE llm_calls SET provider='gemini' WHERE id = NEW.id;
            END
        """)
        conn.commit()
    return {"added_columns": added, "trigger": "llm_calls_tag_gemini"}


def _require_provider_columns(store) -> None:
    try:
        columns = {row[1] for row in store._conn.execute("PRAGMA table_info(llm_calls)")}
    except Exception as exc:
        raise LedgerWriteError(f"provider ledger unreadable: {exc}") from exc
    missing = set(PROVIDER_LEDGER_COLUMNS) - columns
    if missing:
        raise LedgerWriteError(
            "provider ledger columns missing: " + ", ".join(sorted(missing))
            + " — refusing the cloud call")


def reserve_provider_call(store, *, provider: str, capability: str, role: str,
                          model: str, purpose: str, correlation_id: str,
                          quota_bucket: str, mode: str = "mock",
                          is_user_turn: bool = False) -> int:
    """Journal an attempt BEFORE the network send. Failure refuses the call."""
    _require_provider_columns(store)
    columns = [
        "ts", "correlation_id", "role", "model", "mode", "tokens_in", "tokens_out",
        "tokens_estimated", "audio_seconds", "cost_usd", "latency_ms", "ok",
        "verified", "attempt", "fixture_key", "error", "purpose", "is_user_turn",
        "provider", "capability", "provider_request_id", "billing_unit",
        "billing_amount", "cost_known", "quota_bucket",
    ]
    values = [
        iso_now(), correlation_id, str(role), str(model), str(mode), 0, 0, 0, 0.0,
        0.0, 0.0, 0, None, 1, None, PENDING_MARK, purpose or str(role),
        1 if is_user_turn else 0, str(provider), str(capability), None, None,
        None, 0, str(quota_bucket),
    ]
    try:
        with store._lock:
            cur = store._conn.execute(
                f"INSERT INTO llm_calls ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' * len(columns))})", values)
            store._conn.commit()
            return int(cur.lastrowid)
    except Exception as exc:
        raise LedgerWriteError(f"provider reservation not journaled: {exc}") from exc


def finalize_provider_call(store, row_id: int, *, ok: bool, tokens_in: int = 0,
                           tokens_out: int = 0, error: str | None = None,
                           latency_ms: float = 0.0, cost_usd: float = 0.0,
                           provider_request_id: str | None = None,
                           billing_unit: str | None = None,
                           billing_amount: float | None = None) -> None:
    """Close the attempt row. Unknown usage stays nullable, never guessed."""
    _require_provider_columns(store)
    try:
        with store._lock:
            cur = store._conn.execute(
                "UPDATE llm_calls SET ok=?, tokens_in=?, tokens_out=?, error=?, "
                "latency_ms=?, cost_usd=?, provider_request_id=?, billing_unit=?, "
                "billing_amount=?, cost_known=? WHERE id=?",
                (1 if ok else 0, int(tokens_in), int(tokens_out), error,
                 float(latency_ms), float(cost_usd), provider_request_id,
                 billing_unit, billing_amount, 1 if billing_amount is not None else 0,
                 int(row_id)))
            store._conn.commit()
            if cur.rowcount != 1:
                raise LedgerWriteError(f"provider ledger row {row_id} vanished")
    except LedgerWriteError:
        raise
    except Exception as exc:
        raise LedgerWriteError(f"provider result not journaled: {exc}") from exc


def provider_cost_report(store, since_iso: str | None = None) -> dict:
    """Per-provider/per-capability answer to 'what did today cost?'."""
    ensure_provider_ledger(store)
    _require_provider_columns(store)
    where = "WHERE ts >= ?" if since_iso else ""
    params = (since_iso,) if since_iso else ()
    with store._lock:
        rows = store._conn.execute(
            f"""SELECT provider, capability, model,
                       COUNT(*) AS calls,
                       COALESCE(SUM(tokens_in + tokens_out), 0) AS tokens,
                       COALESCE(SUM(cost_usd), 0) AS shadow_usd,
                       COALESCE(SUM(ok = 0), 0) AS failures,
                       COALESCE(SUM(cost_known = 0), 0) AS unknown_cost,
                       COALESCE(SUM(error = ?), 0) AS pending
                FROM llm_calls {where}
                GROUP BY provider, capability, model
                ORDER BY provider, capability, model""",
            (PENDING_MARK, *params)).fetchall()
    return {
        "since": since_iso,
        "rows": [dict(row) for row in rows],
        "providers": sorted({row["provider"] for row in rows}),
    }


def format_provider_report(report: dict) -> str:
    lines = ["Per-provider ledger (shadow USD, not billing):"]
    if not report["rows"]:
        lines.append("  no provider calls recorded")
    for row in report["rows"]:
        extra = []
        if row["unknown_cost"]:
            extra.append(f"{row['unknown_cost']} unknown-cost")
        if row["pending"]:
            extra.append(f"{row['pending']} pending/unclosed")
        suffix = f" ({', '.join(extra)})" if extra else ""
        lines.append(
            f"  {row['provider']} · {row['capability']} · {row['model']}: "
            f"{row['calls']} call(s), {row['tokens']} tokens, "
            f"${row['shadow_usd']:.4f} shadow, {row['failures']} failure(s){suffix}")
    return "\n".join(lines)
