# RPT-I — Provider routing BUILD-8 (Agent I, 2026-11-25)

**Status:** built in the sandbox, fixture-proven, **not owner-account-enabled**.
**Branch:** `arena/7774ad97-elaria` (base `3f40bda852cc5062a23ddb1aea688130563a4cdb`).
**Dispatch:** `reports/DISPATCH-BUILD-2.md` BUILD-8 (manager gate: PASS).
**Design:** `reports/RPT-I-provider-routing-20261125-design.md`;
**Requirement:** `reports/SPEC-PROVIDER-ROUTING.md`.
**Evidence level:** [TESTED-ONLY] — fixture adapters, fake HTTP client, SQLite
fixtures. No provider account, key, network call, model download, audio device
or laptop measurement was used. `OWNERS.yaml` was not touched.

## 1. What landed

| Requirement | Implementation | Fixture proof |
|---|---|---|
| Personality pinned **in code**, Gemini only, exact role/model ids | `model_registry.py:183-249` (`PERSONALITY_PROVIDER`, `PERSONALITY_ROLE_MODELS`, `provider_boundary()`, `assert_personality_route()`) and `assert_model_permitted()` at `model_registry.py:136` now checks an open route | `test_personality_pin_is_code_owned_and_config_cannot_reroute`; `test_flash_429_falls_down_within_the_pinned_gemini_ladder` |
| No personality failover | `provider_router.py:ProviderRouter.personality()` retries only flash → flash-lite, both Gemini; foreign capability registration refused in `CallbackAdapter.__init__` / `AdapterRegistry.register()`; `provider_boundary()` refuses a foreign provider for personality | `test_personality_never_fails_over_to_another_provider_under_429`; `test_revoice_on_gemini_429_returns_local_notice_not_foreign_text` |
| Diverted material behind the **same** boundary | `ProviderAdapter` protocol, `CallbackAdapter`, `HttpMaterialAdapter` and `AdapterRegistry` in `provider_router.py`; material is returned only as a frozen `MaterialEnvelope(untrusted=True)` | `test_material_is_journaled_wrapped_and_disabled_without_verification`; `test_http_material_adapter_is_host_locked_redirect_closed_and_key_gated` |
| Re-voice, never paste | `ProviderRouter.revoice_material()` uses a generated do-not-repeat canary, a long-verbatim/3-word/distinctive-token guard, and `speakable()` accepts only `PersonalityResponse` or a fixed local `QuietStatus` | `test_revoice_never_pastes_material_into_a_speech_sink` |
| Per-provider quota rows, no inherited verification, `0 != unlimited` | `cost.py:parse_provider_quota_rows()` (`[quota.providers.*]`), `ProviderQuotaRow` evidence gate | `test_provider_rows_do_not_inherit_gemini_verified_or_zero_as_unlimited` |
| Provider column in the cost ledger | `cost.py:PROVIDER_LEDGER_COLUMNS`, `ensure_provider_ledger()`, `reserve_provider_call()`, `finalize_provider_call()`, `provider_cost_report()`, `format_provider_report()` | `test_ledger_migration_backfill_and_write_failure_refuses_dispatch`; `test_concurrent_material_calls_do_not_overspend`; `test_pending_rows_are_visible_and_no_ledger_content_leaks` |
| Degradation ladder as designed | `ProviderRouter.ladder_state()` / `personality()` with persistent atomic `QuotaState` reservations and 429 cooldowns; G0 → G1 → G2 → G3 → auto-recovery at window reset | `test_ladder_degrades_recovers_and_goes_local_only`; `test_state_persists_across_restarts_and_corruption_fails_closed` |
| Every call journaled, fail closed | `_dispatch()` journals `provider.route` (provider/model/capability/purpose/bucket, **never content**) and writes the ledger row *before* the adapter call; ledger failure refuses dispatch | `test_personality_never_fails_over_to_another_provider_under_429` (journal assertions); `test_ledger_migration_backfill_and_write_failure_refuses_dispatch` |
| Async entry point uses the same dispatcher | `personality_async()`, `material_async()`, `revoice_material_async()` delegate to the sync dispatcher via `asyncio.to_thread` | `test_async_entry_points_use_the_same_pinned_dispatcher` |

`LOCAL_NOTICES` are fixed code strings ("I'm on budget for now…", "I'm local-only
right now…"). They are not model-generated and never contain diverted text.

The only shipped diverted HTTP adapter is `HttpMaterialAdapter`: two **code-owned**
endpoints (Groq, OpenRouter), no config-supplied URL, `follow_redirects=False`,
`trust_env=False`, a response byte cap, key only from `ELARIA_GROQ_API_KEY` /
`ELARIA_OPENROUTER_API_KEY`, and `MATERIAL` capability only. It is inert unless a
complete owner-verified config row exists and the owner's key is present. No
Mistral/Cohere/Cloudflare adapter is shipped: their terms/account evidence is
still unresolved in the design report, so they stay deferred.

## 2. Call-site census (read before claiming full runtime coverage)

| Path | Current fact | This build |
|---|---|---|
| `gemini_client.py:677` `_call_once`, `:743` `_call_once_async`, `:952` `generate_audio`, `:1294`/`:1343` transcribe | Call `assert_model_permitted(model)` at the Gemini transport boundary | That shared guard now enforces the open router boundary (provider/capability/model); no other transport is reachable from these callers. They still use their own limiter/ledger. |
| `gemini_client.py:1415` `_sdk_transcribe` direct SDK upload + `generate_content` | Gemini model from `config.model_for_role("transcribe_batch")`, ledgered after the fact | Gemini-only today; not routed through the new dispatcher. Owner/A-lane follow-up if transcription is ever diverted. |
| `asr.py:709` | Calls the shared guard | Same as above. |
| `live_client.py:705`/`:727` `aio.live.connect` | Direct Gemini Live session, model from Gemini config | Untouched, no foreign transport. Streaming/Live is **not** routed by this build. |
| `daemon.py:4273` `_generate` → `client.generate("chat")`; `offline_queue.py:295`, `planner_llm.py:149`, `cleanup.py:151` | Direct `GeminiClient` callers | Untouched (Z/A-owned lanes); all Gemini-only. To route a new provider capability, those owners must construct a `ProviderRouter` and call `personality()` / `material()`. The router is a real seam, **not** a claim that the daemon was rewired. |
| `tts.py`, voice catalogues | Flare/Gemini Live audible identity | **Not touched.** The Piper-vs-Gemini voice question remains the OWNER's ears. |

Because `config.py`, `daemon.py`, `store.py`, `gemini_client.py` and `tts.py`
belong to other clusters, this lane did not edit them. Static census above is
the honest boundary of the claim: personality cannot leave Gemini on any path
that exists today; routed calls are now checked in code; a future diverted
call cannot be given PERSONALITY by config or by adapter registration.

## 3. Evidence (sandbox, 2026-11-25)

- New suite: `tests/test_i_provider_routing.py` — **14 passed**, 0 failed.
- Regression suite: `3189 passed, 32 skipped, 1 deselected (slow)` — full run
  with pytest 9.2.0 in a local venv with `numpy`, `websockets`, `google-genai`,
  `httpx` installed. No failures.
- Lint: `ruff check` clean on the four changed/new files.
- Ownership lint delta: one new unclaimed path (`src/assistant/provider_router.py`),
  matching the BUILD-1 precedent for new files; `OWNERS.yaml` was not edited,
  so the owner/manager may claim it. 0 multi-owner rules.
- Provider API budget for this lane: **Gemini flash 0, flash-lite 0, diverted
  0, tokens 0, $0, uploaded bytes 0**. All adapter responses are fixtures;
  `HttpMaterialAdapter` was exercised against a monkeypatched `httpx.Client`.

## 4. Owner steps (laptop only, in order)

1. Decide the Piper-vs-Gemini voice question with your own ears. This build does
   not change audible identity; `tts.py` and voice config are untouched.
2. For ONE provider you own, open its account limits/billing page and confirm,
   on that page, free/no-card status, plan, model and exact caps. Record source
   and date. Do not set `verified = true` from memory or from a third-party blog.
3. Add `[quota.providers.<id>]` to the owner's config with positive numeric caps
   only, e.g.:

   ```toml
   [quota.providers.groq]
   enabled = true
   verified = true
   verified_at = "YYYY-MM-DD"
   verified_source = "account limits page URL + what it showed"
   plan = "free"
   no_card_required = true
   terms_reviewed_at = "YYYY-MM-DD"
   data_use_policy = "owner-reviewed reference"
   [quota.providers.groq.models.llama-test]
   rpm = 30
   rpd = 100
   tpm = 8000
   billing_unit = "requests_tokens"
   reset_tz = "UTC"
   ```

   `enabled` alone is not enough: incomplete evidence or a zero/absent cap keeps
   the row unrunnable. The `[quota].verified` Gemini marker is never inherited.
4. Put the provider key in the service environment (`ELARIA_GROQ_API_KEY` or
   `ELARIA_OPENROUTER_API_KEY`), never in `config.toml`, the ledger or a prompt.
5. Register `HttpMaterialAdapter("<id>")` in the daemon's code-owned adapter set
   (owner/A-lane wiring), and call `ProviderRouter.material(...)` only for
   `MATERIAL` work. Owner-facing replies must go through
   `revoice_material(...)` → Gemini → local TTS/UI. A material envelope must
   never be passed to a speech sink; `speakable()` refuses it.
6. Inspect the route surface on the laptop:

   ```sh
   PYTHONPATH=src python3 - <<'PY'
   from assistant.config import load_config
   from assistant.provider_router import ProviderRouter
   from assistant.store import Store
   config = load_config()
   store = Store(config.db_path)
   try:
       router = ProviderRouter(config, store)
       print(router.report())
   finally:
       store.close()
   PY
   ```

   Expected before step 3: no provider rows enabled, `runnable=False` for any
   draft row, `level` is `G0` while Gemini has budget. Expected after: the
   chosen row shows `runnable=True`, adapters list `material`, and the ledger
   shows `provider=...` per call with `unknown_cost`/`pending` visible.
7. With the owner's account and ears, watch a diverted summary: it must arrive
   as Elaria's own Gemini-voiced words, never as a pasted foreign sentence;
   then exhaust flash and flash-lite in fixture/sandbox first, and confirm on
   the laptop that she only gets quieter and recovers at quota reset.

## 5. Honest limits

- No provider is enabled in shipped config; no account was created or verified.
- No real 429, real rate-limit header, real provider response, or real invoice
  was observed. Cooldowns and quotas are fixture-driven.
- G3 ("wake, lock, transcription, memory, reminders still work") is not
  end-to-end proven by this lane: those subsystems are untouched and need the
  owner's laptop test with dependencies/models installed.
- Ledger rows backfilled as `gemini` are limited to provable `gemini-*` model
  ids; older rows keep `capability=unknown`. Shadow USD is an estimate, not
  billing. A crash between reservation and finalization leaves a visible
  `pending:provider_router` row rather than a silent success.
- The structural re-voice guard is defence in depth: a model can independently
  reproduce a phrase. The deterministic canary check catches literal copying,
  not semantic paraphrase; the owner eye-check in step 7 is still required.
- `provider_router.py` is unclaimed in `OWNERS.yaml` until the owner assigns it.

## 6. Files changed

- `src/assistant/model_registry.py` — code-owned personality pin + shared
  boundary checks.
- `src/assistant/cost.py` — provider quota parser, ledger migration/reservation/
  finalisation, per-provider report.
- `src/assistant/provider_router.py` — new dispatcher, adapters, `QuotaState`,
  envelope/re-voice guard (new, unowned path).
- `tests/test_i_provider_routing.py` — 14 sandbox tests.
- `reports/RPT-I-provider-routing-BUILD-8.md` — this report.

*End of report.*
