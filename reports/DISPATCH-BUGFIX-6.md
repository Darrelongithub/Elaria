# DISPATCH-BUGFIX-6 — FIX-HW5: one bad file must not kill an errand (2026-11-27)

Proven on owner hardware (`bugs.md` BUG-HW5, errand #3):
`--root ~/Downloads` over 11,719 files died at step 5/12 because
`file.read` raised `UnicodeDecodeError` on a PDF — a file whose
own inspection skeleton had already declared "streaming this
target will fail loudly". The remaining queued files were never
read and no grouping was produced.

## FIX-HW5 — Agent E (errand lane)

> You are Agent E. Fix BUG-HW5 in `src/assistant/errand.py` (and
> the small CLI wart in `src/assistant/cli.py`). Three parts:
>
> 1. **Per-file read failures are non-fatal.** A `file.read` /
>    `file.read_batch` exception on one candidate (decode errors,
>    parse errors, unreadable bytes) must be recorded exactly the
>    way inspection failures already are: step marked
>    failed/refused, a named entry in the report's
>    `parse_failures` / `unanswered_or_unasked` with path + error,
>    then the queue CONTINUES. The errand still terminates
>    `failed` only for genuinely fatal conditions (cancel, budget
>    exhaustion stays `budget_exhausted`, root-scope violations,
>    internal errors outside a single file's read). A run where
>    every file fails still completes with an honest report, not
>    an exception.
> 2. **Don't queue reads that are known to fail.** Formats the
>    stream reader declares inspect-only (PDF today —
>    `streamread.py` inspection note) route to `file.inspect`
>    only in `_read_step_for` / the adaptive queue, never to the
>    UTF-8 byte reader. Keep this data-driven from the same
>    source that emits the note, no duplicated suffix folklore
>    that can drift.
> 3. **Plain status tells the truth in words.**
>    `assist errand status <id>` (non-JSON) must print each
>    `unanswered_or_unasked` reason and each parse failure
>    (path + short error), not just counts in the summary line.
>
> Tests: an errand over a temp root mixing one readable text
> file and one binary-masquerading-as-readable file (e.g. a
> `.pdf` with non-UTF-8 bytes) completes, inspects/reports the
> good file, and lists the bad one by name; a PDF candidate is
> never queued for `file.read`; plain-status rendering includes
> the reason strings. Existing errand/GAP-3 tests stay green —
> the GAP-3 "fail loudly" contract means loud per file, it was
> never a licence to abort the run. Sync `origin/main` first.
> New `arena/*` branch, merged PR or it didn't happen. Never
> edit OWNERS.yaml. Owner retest after merge: re-run
> `assist errand start --root ~/Downloads "Tell me what's
> there, and group it by what it seems to be for"` and paste
> `status --json`; expect a completed report with named parse
> failures, not a step-5 death.
