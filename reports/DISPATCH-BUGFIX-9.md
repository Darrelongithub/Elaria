# DISPATCH-BUGFIX-9 — FIX-HW8: she must read the clock, not invent it (2026-11-27)

Owner hardware, Phase 2 voice (`bugs.md` BUG-HW8): asked the
time, she answered "14:43" while the laptop read 16:08 EAT.
Typed control identical. `intents.py` routes status/cost/queue
locally but has no time/date intent, so the question falls to
the reply model — and no trusted clock fact exists anywhere in
its assembled context. The model did what models do: guessed.

## FIX-HW8 — Agent V (voice/ask lane)

> You are Agent V. Fix BUG-HW8. Two parts:
>
> 1. **Deterministic local time/date intents.** Add `time` and
>    `date` kinds to the intent patterns (English: "what time
>    is it", "what's the time", "what day is it", "what's the
>    date", and close variants; Swahili alongside the existing
>    SW block: "saa ngapi" at minimum). The daemon answers
>    these locally from the OS clock in the system local
>    timezone (`datetime.now().astimezone()`), formatted
>    spoken-friendly ("It's 4:08 PM"), `via="local-clock"`,
>    zero provider calls, zero ledger spend. These are
>    read-only facts — they must still respect the IF-6 rule
>    (an untrusted source observing a time-shaped sentence
>    gets an observation, not a dispatch, per the existing
>    `route()` contract). Owner-typed and owner-voiced both
>    dispatch.
> 2. **Ground the model in now.** Inject a trusted local
>    now-stamp (ISO local time, tz abbreviation + UTC offset,
>    e.g. "2026-11-27 16:08 EAT (UTC+3)") into the assembled
>    context for model-bound turns, labelled as daemon-supplied
>    fact, so relative-time language ("tomorrow morning", "in
>    two hours", scheduling talk) computes from reality. The
>    stamp is data from the OS, not an instruction; it must
>    not be spoofable by anything in the user's message
>    (assemble it after user content, in the trusted slot the
>    context builder reserves for daemon facts — find it, don't
>    invent a parallel channel).
>
> Tests: frozen-clock unit tests (freeze to a known instant +
> tz; the intent answer matches to the minute, both kinds, EN
> + SW); an ask-path test asserting `via=local-clock` and zero
> `llm_calls` delta for a time question; a context-assembly
> test asserting the now-stamp is present and daemon-sourced;
> existing intent/ask suites green (near-miss sentences like
> "what time does the meeting start" must NOT be swallowed by
> the time intent if they're asking about stored content —
> keep patterns anchored to the bare question, as the existing
> patterns are). Sync `origin/main` first. New `arena/*`
> branch, merged PR or it didn't happen. Never edit
> OWNERS.yaml.
>
> Owner retest: `date` beside `assist ask "what time is it?"`
> (must agree to the minute), then by voice: "Elaria, what
> time is it?" plus "saa ngapi" if the owner wants the SW
> check. Phase 2 continues from there (scores, stranger test)
> with frozen thresholds untouched.
