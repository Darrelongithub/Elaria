# Hotword submission — external review (adopt/reject)

Date: 2026-10-20
Branch: `arena/c863aa3f-elaria` (base `ef7f82a`)
Reviewer: Arena agent (integration pass for Bugs 6/7/8 + hotword submission)

**Diff caveat:** the submission tree is not present in this workspace or on the
GitHub remote (no `hotword.py`, no hotword branch/PR; `/tmp/arena-workspace`
patch files are empty). Each item is judged against this tree's actual code at
`ef7f82a` and the submission behavior documented in the review brief. Line-level
conflicts cannot be enumerated; behavioral conflicts are enumerated below.

## ADOPT

### A1 — Phrase hotword layer (start-anchored transcript matching) — ADOPT
- **Why sound:** text-level wake matching is passive — it cannot open a command
  session from a loud sound, so it cannot violate the speaker-verified
  activation requirement. Start-anchoring matches `intents.py`'s narrow-grammar
  discipline ("a false local match is worse than an honest model call").
- **Integration:** `src/assistant/hotword.py` (new), wired into `Daemon._ask`
  (the single funnel for `assist talk`, `console.say`, `ask`, dictate-command).
  `"Elaria, status"` / `"Elaria, cost"` strip the wake phrase and resolve as
  local intents (zero Gemini calls). `"Elaria"` alone = check-in. Mid-sentence
  mentions never trigger (start anchor + word-boundary check).

### A2 — BUG A: attribute/method-name collision class — ADOPT
- **Why:** their `self._hotword_stop` (Event) shadowed a `_hotword_stop` method,
  so `hotword.stop` resolved to a non-callable → `TypeError` at dispatch. This
  tree currently has no such collision (now proven by test), but the class of
  bug (instance attribute shadowing a bound handler method) must fail CI.
- **Integration:** `Daemon._handlers()` is the real, inspectable mapping;
  `tests/test_ipc_handler_integrity.py` asserts every entry resolves to a
  callable bound method of the instance (no shadowing) and invokes every
  handler by name through the dict.

### A3 — BUG F: streaming first-token deadline + generous total bound — ADOPT
- **Confirmed root cause of Bug 8 in this tree:** `daemon.py` hard-coded
  `self._chat_timeout_s = 4.0`; `_generate` wrapped `asyncio.to_thread(
  client.generate, …)` in `asyncio.wait_for(…, 4.0)`. Cancelling `to_thread`
  does not stop the worker thread: the call completes and lands in the ledger
  (the owner's `assist cost` evidence: live call, 550 tokens in, ~15 out,
  failure count unchanged) while `TimeoutError` substituted
  `"I am now. What do you need?"`, which `_ask` then persisted ("console stores
  the fallback too"). Every real turn exceeds 4 s → every turn got the canned
  line.
- **Integration:** `[gemini] chat_timeout_s` (generous total bound) plus
  `[gemini] chat_first_token_s` (streaming stall deadline); transports report
  first token through `on_first_token` (SDK transport streams
  `generate_content_stream`). A generation that completes within the bounds is
  delivered **verbatim**. A timed-out/failed turn gets a **turn-aware** fallback
  (`persona.timeout_fallback_reply`) — never an answer to a different question.
  Every substitution is logged (`reply_substituted` persona event: reason,
  original text length, rule hit) and surfaced in `assist cost` + `status`.

## REJECT

### R1 — EnergyScorer / loudness-triggered acoustic start — REJECT
Any path where a loud sound opens a command session violates the
speaker-verified activation requirement. This tree's `voicetest.EnergyScorer` is
self-labelled "plumbing only, not keyword accuracy" and must never act as a wake
fallback. Carve-out per brief: an acoustic monitor may open **listening only**,
must refuse to run without a real keyword model (no energy stub), and every
trigger must pass the same authority gate (owner voiceprint) before command
execution. This integration adds **no acoustic monitor** — the adopted layer is
transcript-phrase only — so no energy path exists to gate.

### R2 — BUG E: replace invalid replies with a fixed canned line — REJECT
That silent-substitution pattern **is** Bug 8. Adopted replacement (per brief):
`is_valid_chat_reply` rejection → regenerate **once**; if still invalid, deliver
the **best attempt** and log the rejection with the rule hit
(`persona.chat_reply_violation`). A successful generation is never silently binned.

### R3 — Fixed-sleep auto-stop (`sleep(8)` then `ptt.stop`) — REJECT
Conflicts with settled endpointing: `SilenceLadder` (one soft "Is that all?" +
grace close) is mode-adaptive; a hard 8 s cut truncates long dictations and
re-opens the VB-5/VB-6 bug class. Dictate keeps `stop_event` + the ladder.

## Still open (same integration — not dropped)

- **Bug 6:** dictate captured nothing despite a proven mic. `ptt.start` used
  `params["target"]` only (which `assist dictate` never sets) — `mic_target` was
  unused, `pw-record` ran with no `--target`; captured bytes/RMS were logged
  nowhere; a wedged `pw-record` left `readexactly` hanging so `stop_event` was
  never observed and `ptt.result` sat the full 60 s. Fixed: target resolution
  (param → `[capture] mic_target` → `[meeting] mic_target`), per-session capture
  diagnostics (node/bytes/peak), doctor live level check, fail-fast
  "no speech captured", regression tests vs fake/silent AND real-signal sources.
- **Bug 7:** `list_pw_nodes` missing from `assistant.capture` (ImportError at
  cli.py:380) — restored; smoke test invokes every CLI subcommand entry point.
- **Bug 8 delivery:** fake generation returning "Four" to "2 plus 2" must reach
  the user verbatim over the real socket (in
  `tests/test_hotword_and_reply_delivery.py`).

## Verification policy
Mock-only results do not count as fixed for anything on the Live path. Every
adopted item has tests exercising the real socket/handler wiring; the final
report separates "verified in tests" from "needs hardware check" per item.
