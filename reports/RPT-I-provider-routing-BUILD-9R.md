# BUILD-9R — Agent I provider routing status

**Completion: blocked; implementation and verification details are in this PR.** Owner checklist (per provider):

| Candidate | Owner must verify in account UI before enabling |
|---|---|
| Groq | Free plan active; no card/payment method or paid auto-upgrade; exact selected model’s RPM, TPM, RPD/TPD, concurrency and reset window; model available on free tier; retention/training/human review/region/subprocessors/deletion terms reviewed. Record evidence/date privately. |
| OpenRouter `:free` | The exact model has the `:free` suffix and is currently free-tier available; no card/payment method or automatic paid fallback; per-model and shared RPM/TPM/RPD, concurrency/context limits and reset window; retention/training/region/subprocessors terms reviewed. |
| Cloudflare Workers AI | Free allocation active for the account and exact model; no card/payment method or automatic paid overage; account/model-specific daily/monthly unit limits, concurrency, reset period and model availability; Workers AI retention/training/region/subprocessor terms reviewed. |

For all: leave disabled unless free status, no-card, caps and data terms are affirmatively confirmed. Populate `[quota.providers.<id>]` with `verified`, evidence date/source, plan, `no_card_required`, terms review date/data policy, and positive per-model caps. No account or credential was created, inspected or stored by this agent. Zero/absent caps mean unavailable. No provider cap is shipped as an enabled default; default state is off.

## Verification and blockers recorded for review

`python -m pytest -q tests/test_i_provider_routing.py`: **14 passed**. Coverage includes personality pinning under diverted-provider 429 and outage (2 cases), injection containment by revoice-or-drop and refusal of foreign text on personality 429 (2 cases), and ladder degradation/recovery/local-only (1 case), plus quota/ledger/HTTP boundary tests. No live provider calls or credentials were used. In this suite, diverted 429/outage cannot alter the personality provider; injection material is not accepted as speakable output.

The previous router provides material envelopes and a quota ledger; provider ledger report rows now distinguish purpose as well as provider/capability/model. However BUILD-9R remains incomplete: live planner, REACH summarisation and pointer VLM call sites still have independent paths; Cloudflare lacks a safe, tested adapter; and the requested `assist cost` per-day provider/purpose display and observable current ladder rung/reason are not wired into the owner command surface. These are material release blockers, not owner verification tasks. Do not enable external provider rows for these workloads until the bypasses are removed and tested. This report is filed in the PR as required.
