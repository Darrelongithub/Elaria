# DISPATCH-BUGFIX-8 — FIX-HW6B: survey sweep must be per-file bulletproof (2026-11-27)

Owner errand #6 (`bugs.md` BUG-HW6B): the new `fs.survey`
breadth step died on `KeyError: 'estimate'`; the errand was
stamped `failed` with 0/32 coverage even though the grouping
answer it produced was correct. Two defects, one chain:

1. `streamread.inspect()` writes
   `result.skeleton["estimate"]["exact"] = False` whenever the
   file exceeds the sample budget, but `_skeleton_html()` builds
   a skeleton with no `estimate` key. Any HTML/XML file larger
   than the sample budget crashes inspection.
2. `skill_fs_survey` catches only a named list of exception
   types per target. `KeyError` isn't on it, so a single
   candidate aborted the sweep and the runner failed the whole
   errand — the FIX-HW5 principle ("loud per file, never
   fatal") was not carried into the new code.

## FIX-HW6B — Agent E (errand lane)

> You are Agent E. Fix BUG-HW6B:
>
> 1. **Source fix in `streamread.py`:** inspection must never
>    assume a skeleton key exists. Guard the `estimate` write
>    (or give `_skeleton_html` a well-formed estimate — pick the
>    one consistent with the other skeleton builders, and say
>    which). Audit the surrounding `inspect()` paths for the
>    same assumption pattern while you're there; fix any twin.
> 2. **Total per-target isolation in `skill_fs_survey`:** any
>    exception while surveying one candidate becomes a named
>    `error` on that record (type + message), counted in
>    `survey_errors`, and the sweep continues. The sweep may
>    only raise for non-file causes (e.g. a broken roots
>    argument), never for a candidate's content. Keep the
>    FIX-HW5 honesty contract: failed files are named in the
>    report, coverage counts only real coverage.
> 3. **Regression tests:** a survey errand over a temp root
>    containing a >4 KiB `.html` file (plus a readable text
>    file) completes with the HTML file either covered or
>    named-failed — never an errand-level `KeyError`; a direct
>    `inspect()` test on that HTML file returns a skeleton
>    without raising; a candidate whose inspection raises an
>    *unexpected* exception type (monkeypatched) lands as a
>    named survey error while siblings complete. Existing
>    HW5/HW6 suites stay green.
>
> Sync `origin/main` first. New `arena/*` branch, merged PR or
> it didn't happen. Never edit OWNERS.yaml. Owner retest: the
> same Downloads survey command must end `completed` (or
> honest partial), with coverage > 0 and no step error.
