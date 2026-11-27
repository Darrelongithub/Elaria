# DISPATCH-PROVIDER-ENABLE — turn on Groq for material (2026-11-27)

Owner decision recorded in `reports/SPEC-PROVIDER-ROUTING.md`
(2026-11-27): **Groq first, ALL material jobs diverted, fallback
to Gemini flash-lite, personality never moves.** Adapters and
quota rows already exist (BUILD-8/9S); REACH summarisation and
the organiser already route through `ProviderRouter.material()`
behind config opt-ins. One gap: the errand runner's
`content.analyze` still calls the Gemini client directly
(`ErrandRunner(client=self.client)`), so errands — the
highest-volume material job — cannot divert today.

## PROVIDER-ENABLE-1 — Agent I (registry/router lane)

> You are Agent I. Wire the errand material path through the
> router and ship the owner enablement pack. Scope:
>
> 1. **Errand diversion.** `content.analyze` (and any other
>    LLM call the errand runner makes for organise/extraction)
>    must call `ProviderRouter.material()` with the configured
>    `[organise] material_provider/material_model` when that
>    provider's `[quota.providers.*]` row is runnable; the
>    envelope stays `UntrustedObservation` material (IF-6),
>    exactly as today. On provider unavailable / 429 / disabled
>    row: fall back to the existing Gemini flash-lite organise
>    call (owner-ruled fallback), and journal which leg served
>    the step (`model=` in step output must tell the truth —
>    `groq/openai/gpt-oss-20b` vs `gemini-3.5-flash-lite`).
>    Personality paths must not change: no Gemini personality
>    call may ever be served by a diverted provider, and no
>    diverted output may reach a speech/owner-facing sink
>    without Gemini re-voicing (existing canaries stay green).
> 2. **Enable-ready config.** Add the disabled-by-default Groq
>    blocks to `config.toml.example` (provider row with
>    `enabled = false`, model cap row for
>    `openai/gpt-oss-20b` rpm=30/rpd=100/tpm=8000 (owner-verified
>    free tier: 1,000 req/day — her cap stays conservative),
>    `[organise] material_provider` unset,
>    `[reach] summarise_*` at zero budget) — shipped inert;
>    the owner flips them in his own config after creating his
>    account. No key material anywhere in the repo.
> 3. **Proof.** Tests with a fixture Groq adapter: errand over
>    fixture files routes analyze to groq (Gemini untouched);
>    groq 429 → Gemini flash-lite serves and the fallback is
>    journaled; groq disabled → Gemini serves, same report
>    shape; `assist cost` shows groq rows after routed calls.
>    Existing provider-routing + errand suites stay green.
>
> Sync `origin/main` first. New `arena/*` branch, merged PR or
> it didn't happen. Never edit OWNERS.yaml.
>
> **Owner sitting (after merge, manager-guided):** create Groq
> account at console.groq.com → API key → add
> `ELARIA_GROQ_API_KEY=...` to `~/.config/assistant/gemini.env`
> (0600, the daemon's EnvironmentFile) → check the account
> limits page → fill `[quota.providers.groq]` verified fields
> with real dates/source → set `[organise] material_provider =
> "groq"`, `material_model = "openai/gpt-oss-20b"`, `[reach]
> summarise_provider/model` + a small `summarise_rpd_budget`
> → restart → Downloads errand re-run must show
> `model=groq/openai/gpt-oss-20b` on `content.analyze`, and
> `assist cost` must show the groq spend at $0.
