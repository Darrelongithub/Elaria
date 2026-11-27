# DISPATCH-BUGFIX-7 — FIX-HW6: errands must deliver the answer, not just survive (2026-11-27)

Owner errand #4 (`bugs.md` BUG-HW6): FIX-HW5 did its job — the
PDF went inspect-only, the `.torrent` failure was named and
non-fatal, plain status printed reasons. But the errand ended
`budget_exhausted` at 12/12 having read 2 of 32 selected files,
never presented a grouping, and `memory.infer` auto-stored 13
snippet "facts" (mislabelled `kind=preference`) from a survey
the owner never asked to be remembered. Survival ≠ delivery.

## FIX-HW6 — Agent E (errand lane)

> You are Agent E. Fix BUG-HW6 in the errand runner. Required
> outcomes, design is yours within the existing rails:
>
> 1. **Breadth before depth on survey asks.** For "what's
>    there / group it" instructions over large roots, the plan
>    must cover the selected candidate set cheaply first
>    (names, formats, sizes, digests — inspection metadata)
>    before spending steps on full reads; dedupe by digest so
>    a zip member and its loose twin cost one read, not two;
>    metadata-only formats (PDF) count as covered-by-inspection
>    and must not crowd out readable files. The step budget
>    reserve must guarantee `content.analyze` + `errand.report`
>    always run — an errand that ends without its report step
>    is a planning failure, and `budget_exhausted` on a survey
>    of a normal folder is a bug, not a personality trait.
>    Honest scoping stays: if coverage is partial, the report
>    says what fraction was covered and what was skipped.
> 2. **The report answers the question.** For a grouping ask,
>    the terminal report (plain + JSON) must state the groups:
>    group label, member count, representative names, and the
>    evidence basis — labelled inferred where inferred. Counts
>    of steps/files are accounting, not the answer; they stay,
>    but below the answer.
> 3. **Surveys don't seed memory.** `memory.infer` must not
>    auto-store candidate inferences from a read-only survey
>    instruction ("tell me what's there", "look through X") —
>    inferences from such runs live in the report ONLY, marked
>    as unconfirmed candidates for the owner to promote via the
>    existing question/answer seam. Where inference extraction
>    does run, a content snippet is not a `preference` fact:
>    kind classification must not label document contents as
>    owner preferences. Zero clarifying questions on an
>    ambiguous grouping is also a smell — if the grouping axis
>    is genuinely unclear, ask ONE question through the existing
>    pending-question seam rather than silently picking one.
>
> Tests: fixture root with many small readable files + PDFs +
> a duplicate inside a zip; a survey errand completes within
> default budget, report contains named groups covering the
> readable set, zero facts stored, duplicate read once.
> Existing errand tests stay green (esp. FIX-HW5's: per-file
> failures named/non-fatal, PDF inspect-only, plain status
> prints reasons). Sync `origin/main` first. New `arena/*`
> branch, merged PR or it didn't happen. Never edit
> OWNERS.yaml. Owner retest: same Downloads command; expect
> `completed`, a stated grouping, and `assist memory` showing
> no new facts from the run.
