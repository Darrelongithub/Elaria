# RPT-I — BUILD-9S: provider-routing activation, remaining core (Agent I)

**Completion: merged PR.** This report is filed in the PR as required.
Everything below is sandbox evidence. **No provider call, account, key or
credential was created, read, or used.** All providers stay DISABLED until
the owner marks each `[quota.providers.*]` row verified — this build ends at
enable-ready.

Sync note: branched from `main` at `b7e86a3` (merge of PR #137), which
already carried PR #136 (checklist + per-provider/per-purpose ledger
grouping) and the dispatch for this lane.

## 1. What landed

### 1.1 Routed diverted workloads — all through `ProviderRouter.material()`

| Workload | Call site | Route | Purpose string |
|---|---|---|---|
| Planner Tier 1/2 classification/extraction (`planner_llm.py`) | `LlmPlanner._classify()` | `material()` | `housekeeping:organise:tier{1,2}` |
| REACH summarisation seam (`reach/summarise.py`, new) | `ReachSummariser.summarise()` | `material()` | `reach:summarise` |
| Pointer VLM grounding (`nus_pointer.py` BUILD-3 role) | `RouterVlmGrounder.__call__()` (wired in `daemon.py` only when `[quota.grounding] enabled` and `rpd_cap > 0`) | `material()` | `nus_pointer.grounding` |

No workload holds a model client any more:

```
$ grep -n "GeminiClient\|client.generate\|LiveClient\|httpx\|requests\.\|HttpMaterialAdapter\|CloudflareMaterialAdapter" \
    src/assistant/planner_llm.py src/assistant/organiser.py src/assistant/reach/summarise.py src/assistant/nus_pointer.py
(no matches)
$ grep -rn "\.material(\|material_async(" src --include=*.py
src/assistant/nus_pointer.py:411:        envelope = self.router.material(
src/assistant/planner_llm.py:179:                envelope = self.router.material(
src/assistant/reach/summarise.py:108:        return router.material(
```

Anything else that reaches a model (the pinned personality path,
`cleanup.py`, `offline_queue.py`, Gemini clients elsewhere) is outside the
three diverted workloads and was not re-routed, per dispatch scope. The
planner envelope reaches only `_parse_batch` (frozen taxonomy, safe
filenames, 0..1 confidence): hostile material cannot name a folder, a path,
or a second destination; unverifiable ⇒ abstain. `speakable()` refuses every
`MaterialEnvelope`; owner-facing text from material goes through
`revoice_material()` (canary + verbatim-overlap drop) or stays data.

### 1.2 Cloudflare Workers AI adapter (new) — neuron budget, never requests

`CloudflareMaterialAdapter` in `provider_router.py`:

* Code-owned OpenAI-compatible endpoint
  `https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions`;
  the account id comes ONLY from `ELARIA_CLOUDFLARE_ACCOUNT_ID` (must match
  the 32-hex shape or the adapter refuses), the token only from
  `ELARIA_CLOUDFLARE_API_TOKEN`. No config URL, no redirects
  (`follow_redirects=False`), no proxy env (`trust_env=False`), no token in
  ledger/journal, `MATERIAL` capability only.
* Neuron accounting is explicit at the quota layer: a Cloudflare model row
  must declare **`neurons_per_day`** (the account's free daily allocation
  devoted to that model) and **`neurons_per_request`** (the per-call
  estimate reserved atomically before dispatch). `material()` reserves
  `neurons_per_request` neurons against the day bucket; `rpd` on a
  Cloudflare row is NOT read as a budget and neuron rows WITHOUT the two
  keys are refused with a neuron-specific error. Test asserts 7×130 = 910
  of 1000 neurons reserved, the 8th call refused, and
  `state.used(bucket) == 910.0 != 7.0`.
* Ledger rows carry `billing_unit='neurons'`; `billing_amount` stays
  `NULL`/unknown (cost_known=0) because this wire surface cannot report
  neurons — it is never guessed. On dispatch failure the reservation is
  released (tested: 3 outages ⇒ bucket back to 0.0).

### 1.3 Owner surfaces — CLI (`assist cost`), documented

Choice: **CLI**, not console. `assist cost` (daemon path and daemon-down
fallback path, both verified) now prints two additional blocks after the
existing report:

```
Today by provider and purpose (ledger):
  no provider calls recorded          # or one line per provider · purpose · capability · model
Degradation ladder: G0 — both pinned Gemini routes available
  pinned Gemini flash (escalation, cap 20): available
  pinned Gemini flash-lite (workhorse, cap 400): available
  diverted material providers (verified + enabled + adapter): none — all diverted lanes disabled
```

The per-provider block is `provider_cost_report(store, day_start_iso())`
(PR #136 grouping: provider × capability × model × purpose). The ladder
line renders `ladder_state()`, which now carries a `reason` computed from
the same caps/buckets that gate dispatch (G0/G1/G2/G3 with per-rung
reason: e.g. `flash escalation exhausted (…); flash-lite workhorse still
available`, or `local-only … wake, lock, transcription, memory, reminders
still work`, or G2 with a verified diverted provider). It cannot disagree
with enforcement. Ledger reads are local SQLite; a corrupt state file
degrades the ladder block to an explicit "ladder unreadable" line, never a
crash and never a false "all clear". `assist cost` help text updated.

### 1.4 Per-provider caps shipped as defaults

**None.** No diverted-provider cap is shipped enabled. `[quota.providers.*]`
is absent by default ⇒ every diverted lane is unavailable
(zero/absent cap = unavailable, never unlimited, BUILD-8 semantics
preserved and extended to neurons). Gemini defaults are unchanged
(flash 5 RPM / 20 RPD; flash-lite 15 RPM / 500 RPD measured, 400 RPD config
cap). The router-state cost unit is now float to carry neuron reserves;
existing integer bucket files load unchanged.

## 2. Tests — run with numbers

`python -m pytest -q` (CPython 3.11 sandbox; deps `pytest`, `httpx`,
`websockets`, `numpy`, `google-genai` installed via pip because the sandbox
lacked them — `httpx` is a declared runtime dependency; `google-genai`
fixes 32 pre-existing unrelated A-lane failures):

**3365 passed, 32 skipped, 1 deselected** (full suite).

Lane slices:
- `tests/test_i_build9s_routing.py` (new): **21 passed** — planner routed +
  journaled with provider+purpose; planner default abstains without
  config; unverified row refuses before dispatch; hostile/injected
  envelopes (path escape, 1.7 confidence, canary) stay data; planner
  outage/429 leaves personality unmoved; REACH zero-budget default, spends
  the 1/day workload budget exactly once; pointer grounder round-trip
  (attachment in memory only, no pixels in ledger rows), oversize frame
  refused pre-reservation, Gemini refused as grounding provider;
  Cloudflare neuron caps, release-on-failure, env gating, 429 →
  `RateLimited(retry_after=120)`; ladder reasons across G0→G1→G3→G2→G0 with
  recovery; `assist cost` end-to-end subprocess assertions for both new
  blocks.
- `tests/test_i_provider_routing.py`: **14 passed** — personality pinned
  under diverted 429 AND outage; revoice-or-drop canaries; ladder
  degrades/recovers/local-only; concurrency overspend (2/2 under 8 threads);
  corruption fails closed.
- `tests/test_phase4_executor.py` (rewritten to the router seam): **20
  passed** — Tier 1/2 classification through the fixture diverted provider,
  recall-as-data hinting, verifier rejects invented folders.
- `tests/test_nus_build_3.py`, `test_reach_*`, `test_phase3_organiser`,
  `test_daemon_cli`, `test_stage_abcd_bughunt`, `test_config_and_store`,
  `test_bughunt_k_quota`: all green (156 / 66 in their slices).
- `test_build_with_tiers_counts_api_calls` now passes a fixture router to
  `OrganiserService(..., router=...)` and asserts the ledger delta from the
  routed call.

## 3. Owner enable-ready — paste-then-verify blocks (disabled as shipped)

Provider rows (keep `enabled = false` until EVERY checklist item in
`reports/RPT-I-provider-routing-BUILD-9R.md` is confirmed; zero/absent cap
= unavailable):

```toml
[quota.providers.groq]                  # plan/model per checklist
enabled = true                          # set ONLY after verification
verified = true
verified_at = "YYYY-MM-DD"
verified_source = "owner's account limits page"
plan = "free"
no_card_required = true
terms_reviewed_at = "YYYY-MM-DD"
data_use_policy = "owner-reviewed"
[quota.providers.groq.models."<model-id>"]
rpm = 30
rpd = 100
tpm = 8000
billing_unit = "requests_tokens"

[quota.providers.openrouter]            # same shape; `:free` model ids only
# ...

[quota.providers.cloudflare]
enabled = true                          # set ONLY after verification
verified = true
verified_at = "YYYY-MM-DD"
verified_source = "owner's Workers AI allocation page"
plan = "free"
no_card_required = true
terms_reviewed_at = "YYYY-MM-DD"
data_use_policy = "owner-reviewed"
[quota.providers.cloudflare.models."@cf/meta/llama-3.1-8b-instruct"]
neurons_per_day = 10000                 # the account's free daily allocation
neurons_per_request = 130               # owner-recorded estimate per call
billing_unit = "neurons"
```

Workload opt-ins (all inert until the provider row verifies):

```toml
[organise]    # Tier 1/2 material lane for the planner (diverted, never Gemini)
material_provider = "groq"              # must NOT be "gemini" (refused)
material_model = "llama-3.1-8b-instant" # the owner's chosen free-tier model id
[reach]       # REACH summarisation (Phase-0 ruling: 0 budget default)
summarise_provider = "groq"
summarise_model = "llama-3.1-8b-instant"
summarise_rpd_budget = 20               # per-day workload cap; all journaled
[quota.grounding]                       # pointer VLM (BUILD-3 lane, unchanged gate)
enabled = true
verified = true                          # per-lane marker, not inherited
verified_at = "YYYY-MM-DD"
provider = "openrouter"                  # never gemini
model = "<vendor/model:free>"
rpd_cap = 30
```

Keys and account ids live in the owner's process environment only
(`ELARIA_GROQ_API_KEY`, `ELARIA_OPENROUTER_API_KEY`,
`ELARIA_CLOUDFLARE_ACCOUNT_ID`, `ELARIA_CLOUDFLARE_API_TOKEN`) — never in
config, reports or the ledger.

## 4. Behaviour change (deliberate, flagged)

The planner's Tier 1/2 LLM upgrade previously ran on the pinned Gemini
flash-lite/`chat` route via `GeminiClient`. It now abstains unless the
owner opts into a verified diverted provider as above — this is what
"route the material path through the router" requires (`material()` refuses
Gemini by construction). Tier-0 (deterministic local) is unaffected.
If the manager wants Gemini-as-material-lane as an option, that is a design
ruling for a new lane (it would widen `material()`), not a silent fallback.

## 5. Notes, limits, follow-ups

* **Double journal by design**: a grounding call writes (a) the router's
  provider row (provider+purpose `nus_pointer.grounding`) and (b) the
  BUILD-3 `vision_grounding` row that feeds the `[quota.grounding]`
  daily-cap accounting. Different consumers, different keys; both ledgered.
* **Config surface**: the blocks in §3 are paste-ready but the
  `[quota.providers.*]`, `[organise] material_*`, `[reach] summarise_*`
  keys are not yet in `DEFAULTS`/`config.toml.example` (owned by Z/L; the
  BH-H22 example↔DEFAULTS parity test gates that). Until they land there,
  doctor's schema check prints visible *warnings* (never silent, never a
  failure). Follow-up for the config owners; not edited here.
* **Pixels**: the frame rides in memory only (max 1 attachment, ≤ 1.5 MB,
  png/jpeg/webp); oversize is refused before any reservation is consumed.
  No pixels in disk/ledger/journal — asserted in tests.
* **Ladder CLI scope**: owner surfaces are CLI-only by choice; nothing was
  added to the console lane.
* Live verification is impossible from this sandbox (no accounts); every
  number above is a sandbox number. `billing_amount` for Cloudflare is
  unknown until the owner records a measured neuron cost — the ledger
  carries `cost_known = 0` for those rows and says so.
* `OWNERS.yaml` untouched.
