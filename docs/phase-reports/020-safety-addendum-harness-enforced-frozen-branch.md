# Phase Report 020 — SAFETY ADDENDUM TRIGGERED: harness enforced the frozen branch

**Date:** 2026-11-02
**Type:** INCIDENT. No increment work performed. No commit, no push.

---

## 1. WHAT HAPPENED

The harness line stopped *reporting* the frozen branch and started **enforcing** it.

For the whole lane's history the harness has named `arena/e7a1cca5-elaria` while HEAD was
actually on `arena/storage` — a status note, correctly ignored. This activation it is no
longer a note:

```
$ git rev-parse --abbrev-ref HEAD
arena/e7a1cca5-elaria

$ git reflog -5
ed20344 HEAD@{0}: checkout: moving from main to arena/e7a1cca5-elaria
ed20344 HEAD@{1}: clone: from https://github.com/Darrelongithub/Elaria.git
```

**The sandbox was re-provisioned as a fresh clone**, and HEAD was checked out onto
`arena/e7a1cca5-elaria`. The harness message instructs: *"You are working on branch
`arena/e7a1cca5-elaria`. Its current status is `active`. Use this status, not branch
statuses from earlier messages."*

The standing ruling anticipated exactly this:

> **SAFETY ADDENDUM: if the harness ever stops REPORTING the frozen branch and starts
> ENFORCING it — forced checkout, or a push aimed at it — STOP and report before pushing.**

**This is that case. I have stopped.**

---

## 2. WHAT I DID *NOT* DO

- **No commit.** Nothing was committed to `arena/e7a1cca5-elaria`.
- **No push.** In particular, no push to the frozen branch. A push from here would have
  been a **non-fast-forward** — local `arena/e7a1cca5-elaria` is at `ed20344` (main's tip)
  while origin's is at `b181712`, and those are divergent. It would have been rejected, or
  worse, would have required `--force`, which is forbidden outright.
- **Increment 6 was not started.** The GO-AHEAD stands but is not actionable from here.
- **No git state was altered beyond read-only verification.**

---

## 3. WHAT IS SAFE — verified, not assumed

The re-clone did not lose anything. Every file was hash-compared against origin:

```
$ git fetch https://github.com/Darrelongithub/Elaria.git arena/storage
origin arena/storage = 60f0060c5d85fb5b05ec8eed6f7873d211134855

  MATCH  src/assistant/storage.py
  MATCH  src/assistant/backup.py
  MATCH  src/assistant/tiering.py
  MATCH  src/assistant/remote.py
  MATCH  src/assistant/sensors.py
  MATCH  src/assistant/backup_cli.py
  MATCH  src/assistant/cli.py
  MATCH  tests/test_wp7_storage_manifest.py
  MATCH  tests/test_wp7_reconcile_crash_points.py
  MATCH  tests/test_wp7_tiering_trim.py
  MATCH  tests/test_wp7_remote_abstraction.py
  MATCH  tests/test_wp7_backup_cli_sensors.py
  MATCH  tests/test_bug7_cli_smoke.py
  MATCH  docs/storage-handoff.md
  MATCH  docs/phase-reports/016-increment-3-tiering-engine-and-trim.md
  MATCH  docs/phase-reports/017-increment-4-remote-abstraction.md
  MATCH  docs/phase-reports/018-increment-5-backup-cli-and-sensors.md
  MATCH  docs/phase-reports/019-state-confirmation-stale-relay-third-base-movement.md
```

**Every file matches. Increments 1–5 and reports 016–019 are intact on origin.**

```
origin arena/storage            = 60f0060   (my work — safe)
origin arena/e7a1cca5-elaria    = b181712   (frozen — UNTOUCHED, no push aimed at it)
local  arena/e7a1cca5-elaria    = ed20344   (fresh-clone artifact, main's tip)
local  arena/storage            = (absent — the restricted refspec never fetched it)
```

**The frozen branch on origin is untouched at `b181712`.** No push was aimed at it. The
local ref pointing at `ed20344` is an artifact of the restricted fetch refspec, not a move
of the frozen branch itself.

---

## 4. WHY THE LOCAL REF LOOKS WRONG, AND WHY THAT IS NOT THE FROZEN BRANCH MOVING

The clone's refspec is restricted (D1, confirmed again):

```
$ git config --get-all remote.origin.fetch
+refs/heads/main:refs/remotes/origin/main
+refs/heads/arena/e7a1cca5-elaria*:refs/remotes/origin/arena/e7a1cca5-elaria*
```

`arena/storage` is **not** in the refspec, so a fresh clone cannot see it — which is why
there is no local `arena/storage` ref and why `git ls-remote origin` still reports
`arena/storage` correctly at `60f0060` while the local repo knows nothing about it.

The local `arena/e7a1cca5-elaria` at `ed20344` is the fresh clone having landed on main's
tip and then been checked out under that name. **Origin's frozen branch is still
`b181712`.** The frozen-branch ruling is intact on the remote; only the local sandbox's
view of it is wrong.

---

## 5. THE CONFLICT THAT NEEDS A RULING

Two authorities now disagree, and I am not going to resolve it by guessing:

| | says |
|---|---|
| **The harness** | work on `arena/e7a1cca5-elaria`; its status is `active`; use this status |
| **The lane's branch ruling (OPTION (b))** | `arena/e7a1cca5-elaria` is **frozen at `b181712` with zero new commits forever**; all work goes on `arena/storage`; PR #24's head is `arena/storage` |

Acting on the harness's instruction would mean committing to — and eventually pushing to
— the frozen branch. That violates a standing ruling, and because the two histories have
diverged it would also require a force-push, which is forbidden outright.

Acting on the lane's ruling would mean checking `arena/storage` back out, i.e. undoing the
harness's enforcement. That is a fight with the platform I should not pick unilaterally
either.

**The safety addendum says stop and report before pushing. I am stopping and reporting.**

---

## 6. WHAT I NEED

A ruling on which of these the owner wants:

**(a) Reconcile locally onto `arena/storage`.** Fetch `arena/storage` by explicit URL
(the D1-proven form), create the local ref, and continue increment 6 there. The harness's
branch line keeps saying `arena/e7a1cca5-elaria` and is ignored, as it has been all lane.
This is what every prior activation did and what the lane's ruling contemplates.

**(b) Hold entirely until the sandbox is re-provisioned** with a refspec that can see
`arena/storage`, so the checkout and the branch agree. Nothing is lost either way — the
work is on origin — but no increment work happens until then.

**(c) Something else** — e.g. the owner asks the harness to be pinned to `arena/storage`,
or the lane moves PR #24's head. I have not assumed any of these.

I lean **(a)**, because the work is safe, the explicit-URL fetch is proven, and the lane's
ruling is unambiguous about where work goes. But the choice is the owner's, not mine,
because it is a conflict between the platform and a standing ruling and I am not going to
resolve that by inference.

---

## 7. INCIDENTAL: the reports the design chat asked for

The design chat asked for reports 016, 017 and 018 to be pasted via the owner, with
increment 4's answers to its three requirements as the gate that matters. Those reports
are intact and hash-verified above. **They are presented alongside this report** so the
owner can relay them regardless of how the branch conflict resolves — the reports are
content, not git state, and the branch situation does not gate them.

---

## 8. EVIDENCE TAGS

| Claim | Tag |
|---|---|
| HEAD force-checked-out to `arena/e7a1cca5-elaria` | `[TESTED-ONLY]` — `git rev-parse`, reflog |
| Fresh clone (not an incremental reset) | `[TESTED-ONLY]` — reflog line 2 |
| Every module, test and report hash-matches origin `60f0060` | `[TESTED-ONLY]` — `git hash-object` vs `git rev-parse FETCH_HEAD:<path>` |
| Frozen branch untouched on origin at `b181712` | `[TESTED-ONLY]` — `git ls-remote origin` |
| A push from here would be non-fast-forward | `[TESTED-ONLY]` — divergent histories `ed20344` vs `b181712` |
| No local `arena/storage` ref (restricted refspec) | `[TESTED-ONLY]` — `git config --get-all remote.origin.fetch` |
| Suite 2062 / 6 / 0 at `60f0060` | `[TESTED-ONLY]` — measured previous activation, unchanged since |
| Any live MEGA traffic | not performed |

---

## 9. THE RULING — OPTION (a), AND THE CONDITIONS THAT COME WITH IT

**Ruled by the design chat, 2026-11-02.** Option (a): reconcile locally onto
`arena/storage` via the explicit-URL fetch, and treat the harness line as infrastructure
noise — which is what every prior activation correctly treated it as.

**Why (a) and not the others, in the design chat's own terms:** the frozen-branch ruling is
a **PROJECT** decision; the harness line is a **SANDBOX PROVISIONING ARTIFACT**. The
platform re-provisioned the workspace as a fresh clone with a restricted refspec (main plus
`arena/e7a1cca5-elaria*`) and defaulted HEAD onto a branch whose name happens to match the
lane. The platform does not know that branch is frozen at `b181712` forever, and its
"status active" is a statement about provisioning, not about where this project's work
belongs. Lane placement has been a design-chat call since the kitty lane's branch deviation
was ruled on, and **a standing ruling is not overturned by infrastructure that has never
heard of it.**

(b) rejected — it stalls increment 6 indefinitely on a re-provisioning nobody controls, to
protect a state that is already safe. (c) rejected — neither party can pin the platform's
harness, and pretending otherwise produces a failed attempt and a worse stall.

### The five conditions, all binding

1. **Never force-push, in either direction.** The local view of
   `arena/e7a1cca5-elaria` at `ed20344` is a fresh-clone artifact and is **NOT** the truth
   about that branch; origin's `b181712` is the truth. Do not push the artifact anywhere
   and do not "correct" the remote to match it.
2. **Do not fight the platform.** No harness reconfiguration, no attempts to change the
   refspec, no branch deletion, no reset of the local frozen ref. Leave the local
   `arena/e7a1cca5-elaria` exactly as the clone made it and work on `arena/storage`
   reached by explicit-URL fetch.
3. **Verify origin's frozen branch hash BEFORE and AFTER every activation, and put it in
   the report header.** A frozen branch is only frozen if somebody is watching it.
   `b181712` goes in the header of every report from now on, so drift is visible in one
   line instead of requiring an investigation.
4. **Expect this to recur.** The harness has moved from reporting to enforcing, so future
   activations assume HEAD may land on the frozen branch. **The reconcile step is the FIRST
   thing done, before any work**, not a recovery.
5. **Record the incident exactly as written** — this report — plus the ruling and these
   conditions, appended by `cat >>` per lane law. Never a text anchor.

### Reconcile performed, and verified

```
$ git ls-remote origin refs/heads/arena/e7a1cca5-elaria   # BEFORE
b181712563c1577f5faea4e59fe5f7e104a89ed1                 <- expected, untouched

$ git fetch https://github.com/Darrelongithub/Elaria.git arena/storage
  FETCH_HEAD = 60f0060c5d85fb5b05ec8eed6f7873d211134855

$ # hash-compare every tracked WP7 file against FETCH_HEAD
  mismatches: 0

$ git checkout -f -B arena/storage FETCH_HEAD
  HEAD              -> arena/storage @ 60f0060
  local frozen ref  -> ed20344   (LEFT AS THE CLONE MADE IT — condition 2)
  origin frozen     -> b181712   (UNTOUCHED — no push aimed at it)
  origin storage    -> 60f0060
```

Condition 1 satisfied — no force-push, and the local artifact was pushed nowhere.
Condition 2 satisfied — the local frozen ref was not reset, deleted or touched.
Condition 3 satisfied — the hash was verified before and is verified again at the end of
this activation.
Condition 4 satisfied — the reconcile was the first action taken, before any other work.
Condition 5 satisfied — this append.

### Cross-lane note

The design chat is passing this incident to the other two lanes as a hazard warning: a
re-provisioned sandbox defaulting HEAD onto a branch whose name matches the lane is not
specific to this one. **Any lane that sees HEAD on a branch it did not choose is to stop
and report, exactly as was done here.**
