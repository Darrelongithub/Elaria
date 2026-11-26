# Agent I — BUILD-9 provider-routing activation report

Status: **partial / not ready to enable**. This checkout contains the BUILD-8 router seam and per-provider ledger support. Account verification cannot be done from this checkout; no accounts were created and no credentials requested or stored. Do not mark a provider verified or enable it until every applicable check below is completed by the owner.

## Owner verification checklist (complete separately for each provider)

For **Groq**, **OpenRouter (`:free` models only)**, and **Cloudflare Workers AI**, open the provider's account, billing/quota, model limits, and privacy/data-processing pages and record:

- [ ] Free tier/trial is active for this exact account and selected model; capture the page/date and the model identifier.
- [ ] No payment card/payment method is on file, and no paid auto-upgrade or automatic top-up is enabled. If either cannot be confirmed, leave disabled.
- [ ] Model-specific limits are recorded: requests/minute, tokens/minute, requests/day (and any daily/monthly token ceiling), concurrency, context/output ceiling, and reset timezone. A provider-wide advertised limit is not sufficient.
- [ ] The intended model is actually available on the free tier (OpenRouter model suffix `:free`); note whether limits are shared across models/projects.
- [ ] Data terms are reviewed: prompts and outputs retention, training use, human review, region/subprocessors, and deletion controls. Do not route sensitive/private material unless the terms and owner's data policy allow it.
- [ ] `[quota.providers.<id>]` is populated with the exact model-specific caps and `verified = true` only after the above are confirmed; zero/absent cap remains unavailable. Store keys only in the owner's local secret environment, never in config, reports, or logs.

Record the provider-specific evidence/date in the owner's private notes, not this repository. Cloudflare is **not activated** by this report; the current router's HTTP adapter supports Groq and OpenRouter only.

## Activation and audit findings

- Existing `ProviderRouter.material()` enforces the verified provider row, a positive model RPD cap, adapter registration, provider boundary, and a journaled call. `MaterialEnvelope` remains untrusted; only `revoice_material()` can send its content toward personality output.
- Existing `HttpMaterialAdapter` is a disabled-by-default-by-configuration adapter for Groq/OpenRouter; credentials are read from `ELARIA_GROQ_API_KEY` / `ELARIA_OPENROUTER_API_KEY`. No Cloudflare adapter exists.
- **Failed activation gates:** `planner_llm.py` still calls its legacy `self.client.generate(...)`; the pointer VLM path remains callback/legacy-client based; no REACH summarisation workload was identified/wired to `ProviderRouter.material()`. Thus the demanded real workload activation and bypass audit are not complete. Do not describe these as routed or enable external providers on their behalf.
- `provider_cost_report()` already groups ledger entries by provider/capability/model, but not by purpose and does not itself filter to today. The existing router's ladder is exposed through `report()` but is not yet an owner-facing degradation-status command. `assist cost` still needs these surfaces wired.
- Router candidates are Gemini Flash / Flash-Lite under positive configured caps, with diverted material as a separately observable availability rung; absent/zero caps are unavailable. **No diverted-provider daily cap default is shipped by this activation** (provider rows must be explicitly configured and verified). No unlimited default is asserted.

## Remaining BUILD-9 work

1. Route planner classification/extraction, REACH summarisation, and pointer VLM through `material()` and verify no ad-hoc client bypass remains.
2. Add the Cloudflare adapter if account verification and a code-owned API/model contract justify it; never accept endpoints from config.
3. Extend ledger reporting/grouping to today × provider × purpose, hook to `assist cost`, and add a status command showing ladder rung and reason.
4. Add integration tests for actual workload routing, 429/outage personality pinning, injection containment/revoice-or-drop, ladder descent/recovery, and reporting.

This is a truthful checkpoint, not a claim that BUILD-9 is complete. No PR/merge was made: this workspace is already on Arena's assigned `arena/51294f79-elaria` branch, which must not be replaced by a different branch.
