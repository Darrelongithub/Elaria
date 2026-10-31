# docs/storage-handoff.md — WP7 COLD STORAGE & BACKUP builder log

Append-only. Newest entries at the BOTTOM. One dated block per turn or per
ruling received. Never rewrite an old block; supersede it with a new one.

Scope of this log: WP7 (cold storage & backup) only. WP8 (corpus package) is
DEFERRED by owner order — not started, not designed, not stubbed, not mentioned
again here except as a "still deferred" line.

Privacy rules that govern every line below:

- Real backed-up content (audio wavs, journals, databases) never appears in
  this repo, in a PR, in a log line, or in chat. Everything here is built and
  tested against synthetic fixtures and LOCAL-PATH rclone remotes only.
- Credentials never transit chat. The owner opens the MEGA account and runs
  `rclone config` himself. The builder writes the scene sheet and never sees a
  password.
- `rclone.conf` OBFUSCATES the MEGA password, it does not encrypt it. Accepted
  at mode 0600, outside the repo. Optional hardening (systemd-creds / keyring)
  is documented as a decision, NOT built.

---

## 2026-10-27 — Turn 1: environment discovery, branch reconciliation, T0 citations

**Environment discovery (all [HW-PROVEN] — measured in this sandbox, not assumed):**

| Fact | Value | Tag |
|---|---|---|
| Python | 3.11.2 (`/usr/bin/python3`) | [HW-PROVEN] |
| `uv` | NOT installed | [HW-PROVEN] |
| `pytest` / `ruff` | NOT installed system-wide; installed into `/home/user/Elaria/.venv` (gitignored) | [HW-PROVEN] |
| `restic` | NOT installed in sandbox (expected — it is a `dnf` binary on the owner's laptop) | [HW-PROVEN] |
| `rclone` | NOT installed in sandbox (same) | [HW-PROVEN] |
| Suite baseline | **1780 passed, 6 skipped** in ~97 s | [HW-PROVEN] |
| `ruff check .` | All checks passed | [HW-PROVEN] |

Suite baseline note: the WP7 brief expected 1,887 passed / 6 skipped on the
mainline branch. This checkout measures **1780 passed / 6 skipped**. The gap is
consistent with the mainline's not-yet-landed work, not with a regression here
(see the branch reconciliation defect below). The 6 skips match exactly.

**Branch reconciliation — DEFECT, surfaced not worked around:**

The WP7 brief says: *"Cut branch `arena/storage` from `origin/arena/c2a7085d-elaria`
@ 0c08cb5."*

- `origin/arena/c2a7085d-elaria` **does not exist** on the remote. `git fetch
  origin --prune` yields exactly two remote refs: `origin/HEAD -> origin/main`
  and `origin/main`.
- Commit `0c08cb5` is **not a valid object** in this repository.
- The Arena harness pins this session to `arena/e7a1cca5-elaria`, which is at
  `ed20344` — byte-identical to `origin/main` (`git log arena/e7a1cca5-elaria
  ^origin/main` is empty).

Decision taken (recorded, awaiting design-chat ruling): all WP7 work happens on
**`arena/e7a1cca5-elaria`** at `ed20344`, which is the only reachable mainline
tip, and the separate PR is opened FROM that branch. No branch is created,
switched to, or force-pushed. Rationale: the harness tracks the session by its
branch, and `arena/storage` would be untracked work. If the design chat wants
the branch literally named `arena/storage`, that is a one-line rename the owner
can do on the PR — it does not change a single byte of the diff.

**Second defect — the mainline foundations WP7 is specified against do not exist
in this checkout.** All [HW-PROVEN] by grep over `src/`, `tests/`, `docs/`:

| WP7 spec references | Present? | Evidence |
|---|---|---|
| `ladder.py` + chain #5 "backup chain" | **NO** | no `ladder.py`; "ladder" in `src/` only ever means the §13.4 intent ladder / model escalation ladder |
| append-only schema-event journal with `session.close` / `transcription.landed` / `transcription.deferred` lines | **NO** | zero matches for `schema_event`, `schema-event`, `transcription.landed`, `transcription.deferred` |
| sensor events `backup.started` / `backup.done` / `backup.verify` / `backup.check` / `storage.gauge` | **NO** | zero matches for `sensor` in `src/`; zero matches for `restic`, `rclone`, `MEGA` in `src/` |
| trash discipline with a 14-day grace window then purge | **PARTIAL** | `executor.trash()` moves to `<data_dir>/trash/<stamp>-<name>` and appends `trash/manifest.jsonl`; there is **no grace window and no purge** |
| `docs/phase-reports/` | **NO** | directory created by this turn |

The trigger ruling (design chat, 2026-10-27) is therefore not directly
implementable as written: the watcher is told to *tail the existing append-only
schema-event journal READ-ONLY*, and that journal does not exist yet. It will be
written by the mainline's active theatre. See OPEN QUESTIONS below.

**T0 citations — collected BEFORE any WP7 code.** Full text, with URLs, in
`docs/phase-reports/000-environment-branch-t0-citations.md`. Headlines:

1. restic's `rclone:` backend auto-spawns `rclone serve restic --stdio` as a
   subprocess and speaks HTTP/2 over its stdin/stdout. No separate server is
   ever run, no TCP port is opened. [restic.net blog 2018-04-01; restic
   "Preparing a new repository"]
2. `-o rclone.timeout` defaults to **1m** and was raised for MEGA specifically
   (restic issue #3511 → PR #3514). MEGA can take >1 min just to open a repo.
3. restic's `--pack-size` defaults to **16 MiB**, is capped at **128 MiB**
   (`MaxPackSize` in `internal/repository/repository.go`), must be given on
   every command that modifies the repo, and costs temp space = pack size ×
   (backend connections + 1).
4. rclone's MEGA backend is **Tier 2**, does not support mtimes or hashes,
   permits duplicate names, and **blocks logins under "heavy use"** (fast-paced
   successive rclone commands) for about a week.
5. rclone's own MEGA page says **MEGA S4 Object Storage is "recommended for new
   projects"** — but S4 is a paid product, so the $0 doctrine keeps us on the
   classic backend. Recorded as a risk, not a workaround.
6. MEGA free-tier inactivity: **no login for 3 months ⇒ warnings; the whole
   process takes at least 10 months from last activity**, after which files,
   chats, Pass and meetings are deleted (the account itself survives, empty).
7. MEGA transfer quota applies to **downloads/streams only** — "Uploading files
   uses your storage quota, but not your transfer quota." For free accounts it
   is **per-IP over a rolling ~6-hour window**, not per-account, and is dynamic
   (MEGA publishes no fixed number). It only starts applying to a given file
   once that file has been transferred in full **more than 10 times**.
8. systemd user timer `Persistent=true` stores the last-trigger timestamp on
   disk and, on activation, fires immediately if it *would have* fired while
   the timer was inactive. It only has an effect on `OnCalendar=` timers.
   Separate, always-on behaviour: a calendar timer that elapses while the
   machine sleeps catches up on resume — and **if it elapsed more than once
   during one continuous sleep, that collapses to a SINGLE activation**.

**Capacity model headline (the number that decides FLAC):**

16 kHz mono 16-bit = 32,000 B/s = **115.2 MB/hour**.

| Quantity | Value |
|---|---|
| 20 GB free tier ÷ 115.2 MB/h | **173.6 h ≈ 7.2 days of continuous audio** |
| Continuous monthly burn | **84.2 GB/month** (4.2× the entire quota) |
| Daily kept-audio budget for a **12-month** runway | **≤ 54.8 MB/day ≈ 28.6 min/day** |
| … for 6 months | ≤ 109.6 MB/day ≈ 57 min/day |
| … for 3 months | ≤ 219 MB/day ≈ 114 min/day |
| Usable before the 2 GB knock floor | 18 GB |

Dedup gains are modelled at **ZERO** for audio (unique streams), per the brief.
Compression is modelled at **1.0 (zero gain) until Scene Sheet 2 measures it** —
so the table above is the pessimistic floor, and every measured point of zstd
saving multiplies the runway. Even so, the 12-month bar needs the owner to keep
resolved-audio volume under ~29 minutes/day. **The FLAC / second-target /
tighter-hot-window decision is therefore likely to fire, and it fires from the
owner's real aggregates, not from this model.** The model is the sensor that
tells us to ask.

**"Fetch in seconds" is an [UNVERIFIED-TARGET], not a fact.** The benchmark
scene runs BEFORE any machinery is built. No latency claim appears anywhere in
this repo until Scene Sheet 1 comes back with numbers.

**What was deliberately NOT done this turn:** no WP7 code, no new Python
module, no config sections, no CLI subcommand, no systemd units, no
`pyproject.toml` dependency change. The benchmark script in `scripts/` is the
measurement instrument Scene Sheet 1 requires, not WP7 machinery — it is
paste-safe shell that reads every credential from the environment the owner
sets, and it prints aggregates only.

---

## 2026-10-27 — Rulings received (append below; none yet)

*(empty — awaiting the design chat's ruling on the OPEN QUESTIONS in
`docs/phase-reports/000-environment-branch-t0-citations.md`)*

---

## 2026-10-27 — Turn 1 (cont.): Scene Sheet 1 instrument built and stub-tested

**`scripts/storage-benchmark.sh` — status [TESTED-ONLY].**

What was proven in this sandbox, with stub `restic`/`rclone` binaries on `PATH`
and synthetic random payload only:

| Check | Result |
|---|---|
| `bash -n` | syntax OK |
| Full run, both repos, 10-line per-repo output | exit 0, every measurement line produced |
| Restore byte-identity guard | correctly **fails the run** when the restored payload differs (verified by pointing the stub at a no-op restore) |
| Scratch-repo guard | refuses to run when `rclone lsf` reports a non-empty repo |
| Missing `RESTIC_REPOSITORY_BASE` | clean `BENCH-FAIL`, exit 1 |
| Unreadable `RESTIC_PASSWORD_FILE` | clean `BENCH-FAIL`, exit 1 |
| Credential leak scan | 0 hits for the passphrase content, 0 hits for prompt text, 0 hits for any MEGA URL or email pattern |
| Suite after adding the script | 1780 passed / 6 skipped (unchanged) |
| `ruff check .` | All checks passed |

What was **not** proven, and is not claimed anywhere: anything about MEGA
itself. No `restic init` over `rclone:`, no upload, no fetch latency, no
`restic check`, no `--read-data-subset` has touched a real backend. Those
numbers exist only on the owner's laptop, and they arrive through Scene Sheet 1.
Until then every latency statement in this repo stays labelled
**[UNVERIFIED-TARGET]**.

Two properties of the instrument worth recording because they shaped it:

1. **It sets `-o rclone.timeout=10m` explicitly** rather than trusting restic's
   default, because the default is 1m and MEGA routinely needs longer just to
   open a repository (restic issue #3511 → PR #3514). Relying on the shipped
   default is the single most likely way this benchmark fails for a reason that
   has nothing to do with the backend.
2. **It leaves restic's default `rclone.args` alone.** That default is
   `serve restic --stdio --b2-hard-delete`; `--b2-hard-delete` is a B2-only flag
   and inert for MEGA. Overriding `rclone.args` to strip it would be tidier but
   would bet the whole scene on an argv a future rclone still accepts, so the
   default is kept and the reasoning is written into the script.

**Repo state after this turn:** no WP7 machinery exists. No new Python module,
no config section, no CLI subcommand, no systemd unit, no `pyproject.toml`
dependency change, and zero edits to `daemon.py`, `transcribe.py`,
`live_client.py` or `HANDOFF.md`. The only additions are three documents under
`docs/phase-reports/`, one log under `docs/`, and one paste-safe shell script
under `scripts/`.

---

## 2026-10-27 — RULINGS RECEIVED (design chat). Four rulings, recorded in substance.

Appended as required. Rulings bind. None implemented yet; one is blocked on the
branch question in Q8.

### RULING 1 — BRANCH (supersedes all three options I offered)

> "none of the three options as written. Diagnose first, then a corrected option
> 2. Option 1 is REJECTED with reasons: main @ ed20344 predates PR #23 — the
> schema-event journal the watcher must tail (stop.requested, ack.played,
> final.*, ws.histogram, audio.sent, latency.table), the current ladder, the
> trash/manifest-era machinery the storage manifest generalizes, and the
> 1,901-test suite all live only on arena/c2a7085d-elaria. WP7 built on ed20344
> cannot implement its own spec and its PR could never merge cleanly. A stalled
> WP7 (option 3) is recoverable; a stale-base PR is wasted days."

**STEP 1 — DIAGNOSE.** Done; verbatim outputs in report 003.
**STEP 2 — the PR branch IS visible.** Live tip `f915d8e396d3fed0b3c77af7b21b2031c09ede5b`
(PR #23 head, open). The ruling expected `3509818` or newer; actual is four
commits newer (Stream G.7 landed). `0c08cb5` is confirmed a genuine ancestor, so
the brief's SHA is stale exactly as the ruling said.
**STEP 2 — ordered actions.** Fetch the branch, cut `arena/storage` from
FETCH_HEAD, build there with the additive-only firewall unchanged, push
`arena/storage` as a NEW branch, never touch or force-push
`arena/e7a1cca5-elaria`, open the PR with BASE = `arena/c2a7085d-elaria`
(stacked; retarget to `main` after PR #23 merges), note the harness session
branch in the PR description, record the exact base SHA in the first phase report.

**STATUS: DIAGNOSED, NOT EXECUTED.** The ordered action collides with the Arena
harness constraint that pins this session to `arena/e7a1cca5-elaria` and forbids
creating or pushing any other branch. Not resolved unilaterally in either
direction — raised as Q8 in report 003 for a ruling.

**Base SHA recorded, as ordered: `f915d8e396d3fed0b3c77af7b21b2031c09ede5b`.**

### RULING 2 — MISSING FOUNDATIONS (the question is void; the fetch succeeded)

> "the question is premature — the diagnosis ordered in the previous ruling was
> not reported. Run it and paste outputs FIRST … IF THE FETCH SUCCEEDS: this
> multiple-choice is void."

The fetch succeeded, so the contingency (amended option 1, self-contained build
against evidenced seams) is **correctly declined and recorded as available but
not invoked**. Defect D2 from report 000 is RESOLVED: `ladder.py`,
`journal_log.py`, the schema events, the trash manifest and the 1,901-test suite
are all present on the real base.

The ruling's four binding amendments are retained for the contingency case, and
the first is already satisfied by evidence:

1. *"The verbatim journal-line contract is below … Your journal-line reader must
   be contract-tested against these exact shapes. Whether the tail mechanism is
   journald (`journalctl --user -u assistant -f`) or a file journal is CONFIRMED
   IN THE INTEGRATION ROUND, not guessed."*
   **CONFIRMED FROM CODE, NOT GUESSED: the mechanism is journald.**
   `journal_log.py` writes `ts level event session_id peak verdict detail` lines
   to **stdout**, and the unit's `StandardOutput=journal` captures them. There is
   no append-only file to `tail`; journald itself is the append-only record, and
   `journalctl` is a pure read — so the trigger ruling's "must NOT touch the
   daemon" holds literally. See report 003 §2.2.
2. *"Watcher is a correct no-op when no journal exists."* — stands.
3. *"Grace-then-purge: executor.trash() move+manifest exists … the purge policy is
   additive there (executor is not on the forbidden list)."* — stands.
4. *"Ladder chain #5 ships as a standalone module +…"* — truncated in the ruling as
   received. Retained verbatim; the remainder is not guessed.

### RULING 3 — RUNWAY: OPTION 1 ENDORSED

> "OPTION 1 — endorsed as recommended. Options 2 and 3 rejected for the reason
> you named yourselves: the spec says DOCUMENTED-NOT-BUILT until the real
> aggregates fire the decision; pre-building either lever is the silent
> workaround the capacity clause exists to prevent. The model's job was to tell
> us to ask. Scene Sheet 2's numbers decide."

Three binding amendments to the capacity report, all implemented in report 004:

1. **TWO USAGE PROFILES.** (a) CURRENT — avg kept-audio min/day over the last 30
   days from existing kept-wav sizes + mtimes, aggregates only. (b) WP5-ERA —
   hours-long flight recordings, with the flood math shown explicitly.
2. **COMPRESSION IS A MULTIPLIER, NOT A FOOTNOTE.** zstd on 16-bit speech PCM
   commonly lands ~1.5–2× [UNVERIFIED-MODEL]. Every runway number reported twice:
   pessimistic floor and measured.
3. **THE OWNER MENU IS FOUR LEVERS**, presented with numbers, never chosen
   silently: (a) FLAC cold-only; (b) second target; (c) retention-class prune;
   (d) truncated in the ruling as received.

**Headline from the amended model:** one 8-hour event day = 921.6 MB =
**~16.8 days of the entire 12-month budget consumed in one afternoon**. At the
compression floor, even *monthly* 8-hour events barely clear 12 months (21.7
months). At 2.0×, fortnightly clears (20.1 months) and **weekly never clears at
any ratio in the 1.5–2.0× band (10.0 months)**. That last number decides whether
a second target is optional or mandatory.

### RULING 4 — WATCHER WAKE: OPTION 1, AND THE SPEC IS FORMALLY AMENDED

> "OPTION 1 — poll on the same seam as watcher.py (stdlib snapshot-diff,
> headless-testable) — AND the spec text is hereby formally amended (the
> substance of option 3), so the record stays honestly"

**SPEC AMENDMENT (binding, recorded here as required):** every occurrence of
*"inotify wake on the data dirs"* in the WP7 spec and rulings reads from now on:

> **"prompt wake via stdlib polling snapshot-diff, interval `[backup]
> watcher_poll_s` (default 30 s, configurable)"**

Rationale in the ruling: *"The requirement was never inotify; it was promptness —
'a flight recording does not wait 24 h' — which a 30 s poll satisfies completely,
with the nightly timer as the belt behind it."*

**OPTION 2 REJECTED for the record:** inotifywait adds a binary dependency and a
second code path to test, and there is no consumer of sub-second promptness
anywhere in WP7. Revisitable ONLY if a real requirement appears, as an
owner-visible decision — never as builder convenience.

**IMPLEMENTATION NOTES (binding):**
- Poll must be cheap: directory listing + mtime/size per pass. **NO hashing during
  polls** — hash only new/changed candidates once, then hand to the manifest
  pipeline.
- The journal tail uses the same polling seam, read incrementally from a
  **persisted offset, never re-read whole**. For journald that offset is
  journald's own cursor.
- Pattern reuse, not file capture: follow `watcher.py`'s architecture in the new
  module; if sharing its base requires touching `watcher.py` at all,
  **additive-only**, and say so in the report. The firewall list is unchanged.
- Headless pins: tests drive the poller with fake directories and a fake clock —
  no sleeps, no real inotify, no timing flake. The watcher's correct-no-op
  behaviour (absent journal, empty dirs) is pinned too.

---

## 2026-10-27 — Correction to the Turn 1 entry (append-only discipline)

The Turn 1 entry reported, as [HW-PROVEN], that "`origin` carries only `main` @
`ed20344`" and that `arena/c2a7085d-elaria` "does not exist". **That was wrong**,
and the error was mine, not the repository's: `remote.origin.fetch` in this
checkout is refspec-restricted to `main` plus this session's own branch, so
`git fetch origin --prune` could never see the mainline PR branches.
`git ls-remote origin` proves `arena/c2a7085d-elaria` exists at
`f915d8e396d3fed0b3c77af7b21b2031c09ede5b` and is PR #23's open head.

Consequences recorded so they are not re-derived:
- The WP7 brief's base is real and reachable. Defect D1 in report 000 was an
  artefact of my method and is corrected in report 003.
- **Every future fetch of mainline work must use the explicit-URL form**
  `git fetch https://github.com/Darrelongithub/Elaria.git <branch>`, or the owner
  must widen the refspec. Widening it is an owner decision, not a builder
  convenience, so the explicit-URL form is used and the restriction is documented.
- The 1780-passed suite baseline I measured is the **stale** number from
  `ed20344`. The real base has 98 test files (vs 87) and the ruling cites a
  1,901-test suite. The baseline WP7 must hold is measured on `f915d8e`.

---

## 2026-10-27 — RULINGS RECEIVED (round 2). Branch executed; levers corrected; sizing target set.

### RULING 5 — BRANCH MECHANICS: THE HYBRID, EXECUTED

> "OPTION (b), THE HYBRID. Substance beats bookkeeping. Execute: 1. Cut
> `arena/storage` at f915d8e (the verified live tip — PR #23's open head, carrying
> all of Stream G + G.7). Push it as a NEW branch. 2. `arena/e7a1cca5-elaria` is
> untouched from this moment: no force-push, no rewrite, no new commits. Your
> pre-flight docs stay as its historical record; the harness keeps attribution of
> what lives there. The WP7 machinery's lost session-attribution is ACCEPTED — the
> PR description is the durable provenance record. 3. Open the PR with base =
> `arena/c2a7085d-elaria` (stacked; retarget to main after #23 merges). In the PR
> description record: base SHA f915d8e, the session branch name, the
> harness-attribution caveat, and the four verified seams. 4. Record the base SHA
> + this ruling as a dated entry in docs/storage-handoff.md §5 (append-only).
> 5. CONTINGENCY (pinned): if the push of `arena/storage` is TECHNICALLY blocked,
> STOP and report the exact error. No stale-base fallback, no force-push, no
> improvisation. The invariant stands: WP7 is built on the live mainline tip or it
> is not built today."

**EXECUTED.** `arena/storage` cut at `f915d8e396d3fed0b3c77af7b21b2031c09ede5b`;
pre-flight commits cherry-picked clean; session branch left at `b181712` with no
new commits, no force-push, no rewrite.

**Relay discrepancy recorded, not silently resolved:** the ruling says "OPTION
(b)", but the hybrid was option **(c)** in the three options I offered — option
(b) was "follow the harness, build on ed20344". The ruling's *substance* is
unambiguous and matches (c) exactly, so (c) is what was executed. Flagged in
report 005 so the letter/substance mismatch is on the record.

**Refspec widening: DENIED as a gate** by the ruling — diagnosis complete, the
direct-URL fetch is proven, sandbox config does not persist between turns, no
owner action owed. The explicit-URL fetch form remains the standing method.

### RULING 6 — LEVER (d) CORRECTED VERBATIM (relay corruption re-issued)

> "Your truncation handling is ENDORSED AS PROTOCOL: a truncated relay is recorded
> incomplete and re-requested verbatim; it is never reconstructed by inference."

**The corrected owner menu, verbatim and complete — FOUR levers, with numbers,
never silent:**

- **(a) FLAC cold-only** — decode-back hash-verified, manifest-state-changed,
  never silent; build only on explicit owner go.
- **(b) Second target** — new free-tier account; owner account decision.
- **(c) Retention-class prune** — resolved PTT wavs with transcripts landed, past
  an owner-set age, as an owner-visible recorded restic forget/prune decision;
  **auto-delete never exists; event/flight recordings never pruned without
  explicit owner order.**
- **(d) Do nothing** — capacity-floor knock at `remote_free < 2 GB` is the designed
  pressure gauge; the owner picks among (a)/(b)/(c) when the knock fires, with real
  numbers in hand.

**The fragment "(d) event/flight recordin…" was lever (c)'s guard clause, mis-fused
onto (d) in the relay.** My three reconstruction candidates were rejected as
substitutes: my (b) *is* lever (b); my (c) lives inside lever (c) but its default is
forbidden by (c)'s guard clause; and my (a) — **excluding event/flight recordings
from the cold class — is a NEW lever, never ruled**, which contradicts
audio-never-lost (flight recordings with no offsite copy = the single-copy risk
class this whole design fences). Recorded as a rejected non-lever.

**Standing protocol adopted:** a truncated relay is recorded incomplete and
re-requested verbatim; never reconstructed by inference.

### RULING 7 — WP5 EVENT FREQUENCY: SIZING TARGET = MONTHLY

> "DESIGN TARGET: MONTHLY 8-hour events (11.06 GB/yr raw). Rationale: monthly is
> the highest frequency that survives the zero-compression floor (21.7 months) —
> nothing unverified is load-bearing. The measured compression ratio from scene
> sheet 2 is HEADROOM, not a requirement."

**Combined-profile allowance, per the ruling, and my independent verification of
it (no drift):**

```
usable-before-knock ≈ 18 GB (20 GB − 2 GB gauge floor) − 11.06 GB events
                   ≈ 6.9 GB/yr daily budget
                   ≈ ~10 kept-min/day at floor, ~20 at 2×   (1.92 MB/kept-min)
```

My check: 6.9 GB/yr ÷ 365 = 18.9 MB/day; ÷ 1.92 MB/kept-min = **9.8 ≈ 10
kept-min/day** at the floor and **19.6 ≈ 20** at 2×. The ruling's arithmetic holds.

**Relief path if Scene Sheet 2's CURRENT profile measures above the allowance:
lever (c) only** — retention-class prune of resolved PTT wavs, transcripts landed,
owner-set age, owner-visible recorded decision. Auto-delete never exists;
event/flight recordings never pruned without explicit owner order.

**Standing rejections unchanged:** FLAC and second-target PRE-BUILD remain rejected
("documented, not built") — monthly needs neither at the floor. Event-class
exclusion from the cold class remains a rejected non-lever. If sheet-2 reality
measures fortnightly+, the menu re-opens WITH NUMBERS via the gauge or the sheet —
never before, never silently.

**Scene Sheet 2 row 15 stands:** it measures actual event frequency *against* this
sizing target. The decision sets the target; the sheet checks it. Report the
comparison, not a re-litigation.

### RULING 8 — the base's G.7 sensors are a bonus: contract-check before building

> "your base carries G.7's sensors. The journal-line contract from the design chat
> is now checkable against real machinery — verify your watcher fixtures against
> the on-base journal_log.py output shapes before writing the watcher, and report
> any drift from the contract verbatim."

**DONE — see report 005 §3 for the verbatim shapes and two drifts found.** Summary
of what the verification established:

- Mechanism is **journald**, not a file: `journal_log.py` writes
  `ts level event session_id peak verdict detail` to stdout and the unit's
  `StandardOutput=journal` captures them. No append-only file to tail; `journalctl`
  is a pure read, so "must NOT touch the daemon" holds literally.
- **DRIFT 1:** the field count is **variable** (6, 7 or 8 parts depending on which
  optionals are present). The watcher must parse with `split(" ", 6)` and never
  assume a column count.
- **DRIFT 2:** the WP7 brief's claim is **verified true** — the kept-audio path
  rides inside the free-text `detail` field (`audio kept at {path}` at
  `transcribe.py:1390` and `:415`). **Privacy consequence, now a written rule:**
  the watcher extracts the path to address the artifact and must never write it to
  a log line, a sensor event, a PR, a chat message, or the manifest's
  human-readable fields. `journalctl` output is never pasted anywhere.

### Baseline on the real base — and a pre-existing defect I did not fix

| Measurement | Value on `f915d8e` |
|---|---|
| `pytest -q` | **1913 passed, 6 skipped, 1 error** |
| `ruff check .` | All checks passed |

Two environment corrections were needed before those numbers meant anything, both
recorded in report 005 §2.1: `.venv` was wiped by the same reset, and 21 tests
failed until the project's OWN declared deps (`google-genai`, `httpx`) were
installed — a sandbox artefact, not a base defect.

**D7 — pre-existing, owned by the mainline, deliberately NOT fixed by me.**
`tests/conftest.py:108` teardown raises
`AttributeError: 'async_generator_athrow' object has no attribute '__qualname__'`
on CPython 3.11. Present on the base before any WP7 work; deterministic;
teardown-only; does not block WP7. `conftest.py` is the mainline's active theatre
and a fix inside a stacked PR would collide with theirs for zero WP7 benefit.
Reported for them to own.

**Baseline WP7 must hold: 1913 passed / 6 skipped / 1 error (pre-existing, 3.11
only), ruff clean.**

### Sandbox `.git` reset — handled, standing rule adopted

Between turns the sandbox reset `.git` to a single commit at `ed20344`, dropping my
turn-1 commit locally while origin retained it. The turn-2 work had already been
committed on the stale base, which would have pushed as a **non-fast-forward** —
a silent rewrite of shared history on the session branch. Caught before push;
reconciled by re-fetching from origin and rebasing, so the session branch history
stayed `ed20344 → 2320e1d → b181712` and the push was a clean fast-forward.

**Standing rule:** before every commit on `arena/storage`, verify
`git merge-base --is-ancestor <origin tip of the PR base> HEAD`. Never `--force`.

---

## 2026-10-27 — CROSS-LANE CONTRACT DRIFT (Stream H addendum §A.2 answered)

Report 006 is the answer. Summary for the log, because this is the entry a future
turn will read first.

**The addendum's statement of the journal contract is WRONG, and Stream H / WP1 may
be coding against it.** It lists `ts · level · event · session · detail`. The real
schema is **seven** fields:

```
ts · level · event · session_id · peak · verdict · detail(optional)
```

`peak` and `verdict` were omitted entirely. `parts[4]` is `peak`, `parts[5]` is
`verdict`, `parts[6]` is `detail`. A parser built to the addendum's prose would read
`0.42` or `closed` as the detail, find no `audio kept at …` phrase, look correct, and
quietly never fire.

**What is correct in the addendum and must not be "fixed":** the `split(" ", 6)`
binding (maxsplit 6 → 7 parts, exactly right), RFC3339 `ts`, the
`"audio kept at {path}"` phrasing, and the privacy fence.

**Three further drifts found:**
- Field count is **6..N, unbounded** — `detail` is free text and the real
  `transcription.deferred` detail is a long sentence. Not "6, 7 or 8".
- `detail` is **optional and absent**, not `-`. The `-` placeholder applies to
  `session_id`, `peak`, `verdict` only. A line with no detail ends at `verdict`.
- `session_id` is 12-hex on the PTT/dictation path (`daemon.py:1764`,
  `transcribe.py:1406`) but **32-hex** at `daemon.py:2646` and `:2694`. Not a schema
  invariant; a hard `^[0-9a-f]{12}$` check would drop every stream-F/G sensor line.

**Correction to my own report 005:** §3.3 claimed `quota.counter` (all-empty) gives
7 parts. It gives **6**. And its "6, 7 or 8 parts" framing should read "6..N".
Corrected in report 006, not silently patched.

**Privacy fence accepted verbatim and made operational** (five rules in report 006
§6): the watcher extracts the kept-audio path only to address the artifact in the
manifest, and never writes it to a log line, a sensor event, a phase report, a PR,
or a chat message. `journalctl` output is never pasted anywhere.

**A.1 conftest defect: STOOD DOWN, confirmed Stream H's.** The storage lane will not
touch `tests/conftest.py`. Baseline WP7 must hold, unchanged: **1913 passed / 6
skipped / 1 error (pre-existing, CPython 3.11 only), ruff clean.**

**Time-sensitive consequence, recorded as GATE 1e:** because no watcher exists yet,
Stream H / WP1 can still change the journal line shape or the `audio kept at {path}`
phrasing at **zero** migration cost. Once the watcher's fixtures are authored, any
shape change becomes a storage-lane migration. The window is open now.

**Sandbox reset, third occurrence.** `.git` was reset to a single commit at
`ed20344`, dropping local branch refs and `.venv` while leaving the working tree
intact. Work was safe on origin (`arena/storage` @ `7fc190a`). Reconciled by
re-fetching `arena/storage` and force-checking-out (safe: every local file was
verified present in the target tree, and everything of mine was already pushed).
Local `arena/e7a1cca5-elaria` was also re-pinned to origin's `b181712` so a stray
push could not rewrite shared history.

---

## 2026-10-27 — A.2-R RECEIVED AND VERIFIED (supersedes A.2; A.1 stands unchanged)

Report 007 is the answer. This is the entry a future turn reads first.

**A.2-R adopts the storage lane's corrections and is itself correct on every point** —
the first relay in this exchange to survive verification unchanged. Verified by running
`journal_log.py`, not by trusting the relay:

- `split(" ", 6)` → **6 parts (no detail) or 7 (detail present)**, with `parts[6]`
  byte-intact and spaces preserved. Confirmed against the two REAL detail strings.
- `parts[4]` is `peak`, `parts[5]` is `verdict`, `parts[6]` is `detail`.
- Detail absence = **ABSENT** (line rstrip'd, ends at `verdict`), never `-`. Dash
  placeholders apply to `session_id`/`peak`/`verdict` only.
- `session_id` is 12-hex on PTT/dictation, 32-hex at `daemon.py:2646`/`:2694`, or `-`.
  **Never regex-gate `^[0-9a-f]{12}$`** — it silently drops Stream-F/G sensor lines.
- `"audio kept at {path}"` phrasing CONFIRMED at `transcribe.py:1390` and `:415`.

**THE VERIFIED BINDING CONTRACT** is recorded verbatim in report 007 §2, with six
reference output lines straight from `journal_log.py`, so no future turn ever re-derives
it from a relay.

**GATE 1e — WINDOW STILL OPEN, AND THE BASE HAS NOT MOVED.**
`git ls-remote origin refs/heads/arena/c2a7085d-elaria` is still
`f915d8e396d3fed0b3c77af7b21b2031c09ede5b`; `git log f915d8e..FETCH_HEAD` is empty.
**No shape drift and no phrasing drift since the window opened.** A.2-R's "flag any
change" instruction is satisfied by this negative result: the flag is *no change,
contract stands as verified at `f915d8e`*. No fixtures authored, nothing in PR #24
consumes the contract yet, and the window closes only after the owner's scene numbers.

**A.1 — conftest defect: STOOD DOWN, unchanged.** Stream H's. Report 006 is
authoritative over report 005 §3.3, as A.2-R directs. Baseline to hold: **1913 passed /
6 skipped / 1 error (pre-existing, CPython 3.11 only), ruff clean.**

**One residual risk A.2-R does not cover, carried forward and still open:**
`_flat()` normalises whitespace in every field, so a kept-audio path containing a
newline, tab or repeated spaces is **not byte-faithful** inside `detail`. Not a schema
change, so A.2-R's flag instruction does not reach it. Mitigation is the existing
design: directory poll = belt, journal tail = suspenders; the manifest resolves
artifacts from the filesystem scan and treats the journal as corroboration, never as
the authoritative path source. Recorded so nobody "optimises" the poll away later.

**Standing commitment:** every time the PR base moves, the §1 verification table is
re-run and the §2 contract re-issued or drift reported. That is the mechanism that
keeps GATE 1e honest without anyone having to remember to ask.

---

## 2026-10-27 — DESIGN-CHAT RULINGS ACKNOWLEDGED (round 4) + GATE 1e RE-VERIFICATION: BASE MOVED

Report 008 is the record. Five rulings received, all confirming the storage lane's
position, plus one standing commitment that fired.

### RULING 9 — report 007 §2 is CANONICAL, in both lanes

> "Report 007 §2 is CANONICAL for the journal contract in both lanes. It supersedes
> A.2-R, the original evidence-carrier contract, and any relay prose — including this
> chat's own prior statements. Future consumers cite 007 §2's reference lines, never a
> summary."

**RECORDED.** §2's heading now carries the canonical designation. Consequence: §2 is the
single source of truth; no relay — not even the design chat's own — overrides it. Any
future consumer that cites a summary instead of the reference lines is wrong.

### RULING 10 — negative drift result accepted; window open; closing event dated to baseline

> "The negative drift result is accepted as recorded: contract stands as verified at
> f915d8e; GATE 1e window open; the window's closing event (fixture authorship) will be
> dated against that baseline."

**RECORDED.** Canonical baseline = `f915d8e396d3fed0b3c77af7b21b2031c09ede5b`. Fixture
authorship is dated against it.

### RULING 11 — belt/suspenders is a RULING, not a comment

> "Belt/suspenders restatement in 007 endorsed — directory poll is truth, journal
> corroborates. That ordering is a ruling, not a comment; it may not be inverted or
> 'optimised' without a design-chat entry."

**RECORDED AS BINDING.** Directory poll = **truth**. Journal tail = **corroboration**.
This may **not** be inverted or "optimised" away without a design-chat entry. This is
the ruling that makes report 006 DRIFT 6's mitigation mandatory rather than advisory.

### RULING 12 — A.1 stand-down and baseline confirmed

`tests/conftest.py:108` remains Stream H's. Baseline to hold, unchanged: **1913 passed
/ 6 skipped / 1 error (pre-existing, CPython 3.11 only), ruff clean.**

### RULING 13 — posture unchanged

> "STOPPED AT GATE 1. Nothing to build until the owner's Sheet 1 + Sheet 2 numbers
> arrive and the design chat rules go/no-go on the MEGA target and the compression
> multiplier."

**RECORDED.** Nothing built this turn. No module, no parser, no fixtures, no config, no
CLI, no systemd unit.

### GATE 1e RE-VERIFICATION — THE BASE MOVED (standing commitment fired)

Two Stream H commits landed: `8a72939` and `eae1d01`. New tip
`eae1d01b402dc2cef9d788956c0851ea1d38c14e`.

**Result: NO schema drift, NO phrasing drift.**

- `git diff f915d8e..eae1d01 -- src/assistant/journal_log.py` → **empty** (byte-identical).
- The four `audio kept at` sites are **character-identical** on both bases; only line
  numbers shifted (`daemon.py` 2327→2404, `transcribe.py` 1381→1438 and 1394→1451,
  `transcribe.py:418` unchanged).
- All three WP7 event names still emitted; all §2 invariants re-verified by running
  `journal_log.py`.

**Self-correction:** report 007 said `audio kept at` went "from 2 to 4 occurrences". My
miscount — it is **4 on both bases**. Corrected in report 008.

**What DID change, and the trap it creates:** Stream H added four new events
(`capture.node_state`, `stream.closed`, `post_timeout_route`, `fallback.outcome`). Two of
them emit `verdict` values that **collide** with WP7's:

| event | verdict | WP7-relevant? |
|---|---|---|
| `transcription.landed` | `landed` | YES |
| `fallback.outcome` **(new)** | `landed`/`empty`/`error` | no |
| `transcription.deferred` | `deferred` | YES |
| `post_timeout_route` **(new)** | `fallback`/`deferred` | no |

`parts[5] == "landed"` matches **both** `transcription.landed` and `fallback.outcome`.
Proven by running the module on both shapes.

**BINDING ADDITION TO THE CANONICAL CONTRACT (report 007 §2.1):** the watcher dispatches
on the **event name** (`parts[2]`) and nothing else. A watcher keyed on verdict would
treat a fallback file-transcription leg as a WP7 cold-storage candidate — a **silent
misfire**. Verdict is corroborating state after a match, never the dispatch key.

**Standing commitment re-armed:** the next base movement triggers another full re-run.

---

## 2026-10-27 — RULINGS ROUND 5 + GATE 1e RE-DATED TO 462fa98 + A.1 FIXED, BASELINE CORRECTED

Report 009 is the record. Five rulings received, the tip moved again, and one of my own
recorded baselines turned out to be stale.

### RULING 14 — dispatch rule ADOPTED as canonical amendment (007 §2.1)

Consumers key on event name (`parts[2]`), **never** on verdict; verdict is corroborating
state after a match only. Baseline, not window-contingent. Recorded as the contract
mechanic's **second pre-code save**. The collision was created by Stream H's new
visibility sensors and fenced the same day by the standing commitment.

### RULING 15 — rename option DECLINED on the merits

Mainline code is correct, verdict values are event-local semantics, the fence is
consumer-side and costs nothing. **Recorded as declined-with-reasons, and it must not
drift into a mainline work queue.** Flagged explicitly so a future turn does not
"helpfully" re-raise it as a mainline TODO.

### RULING 16 — report 008 self-correction endorsed (canonical-document propagation
awareness).

### RULING 17 — tip note: re-verify against `462fa98`, do not trust the relay. DISCHARGED.

Ran `diff eae1d01..462fa98` and the full verification table against `462fa98`'s **actual
`journal_log.py`**, extracted and executed — not inferred from a diff:

| Check | Result |
|---|---|
| `git diff eae1d01..462fa98 -- src/assistant/journal_log.py` | **EMPTY — byte-identical** |
| `audio kept at` sites | **4, character-identical** (only line numbers shifted) |
| All three WP7 event names emitted | **YES** |
| Full §2 verification table vs 462fa98's real module | **ALL 12 CHECKS PASS** |
| Verdict collision | **STILL PRESENT** → dispatch rule still required |

`462fa98` changed only `scripts/live_repro.py` (default `--wav` resolves the daemon's XDG
audio dir first), `HANDOFF.md` §4 (manifest wav name corrected to the session-id-prefix
form), and `daemon._mic_release_probe` (capture target read at spawn time). **No journal
touch.**

**GATE 1e window re-dated to `462fa98fba34e3939ad0ba896df95bf69b7977cf`**, drift-free.

### RULING 18 — posture confirmed: STOPPED AT GATE 1. Sheets 1+2 numbers gate everything.

### A.1 IS FIXED — MY BASELINE WAS STALE, CORRECTED

Stream H adopted the one-liner from report 005. `tests/conftest.py` now reads
`getattr(task.get_coro(), "__qualname__", "")`. It landed in `8a72939`, after my report
008 measurement.

**I did not trust the commit message's "1,925 passed / 6 skipped" — I measured it
myself** in a throwaway worktree at `462fa98` on this sandbox's CPython 3.11:

```
1925 passed, 6 skipped in 167.84s
ruff: All checks passed!
```

**CORRECTED BASELINE TO HOLD: 1925 passed / 6 skipped / 0 errors, ruff clean.**
The earlier "1913 passed / 6 skipped / 1 error (pre-existing, CPython 3.11 only)" is
**superseded** — there is no open pre-existing defect any more. Every earlier report
quoting 1913/1-error is historical, not current.

### Cross-lane fact recorded for the manifest

Kept wavs live at `~/.local/share/assistant/audio/{when}-{session_id[:6]}.wav`
(e.g. `20261027-064450-77cc4e.wav` for session `77cc4efb1886…`). This is the shape the
kept-audio path in the journal's `detail` field will follow, so the manifest's path
handling is designed against the real convention rather than an assumption. It also
sharpens the privacy fence: that path is a real filesystem location on the owner's
laptop and must never leave it.

### Standing commitment re-armed, with one new clause

On every base movement: re-run the drift check **and** re-measure the suite. A.1 proved
a mainline fix can silently change my recorded baseline, so the drift check alone is not
enough.

---

## 2026-10-27 — PROTOCOL REFINEMENT RULED + GATE 1e RE-DATED TO 018d109 + `capture.lifecycle` VERIFIED INERT

Report 010 is the record. The tip moved again; the notice's SHA was right, but it was
confirmed by fetch, not taken on trust.

### RULING 19 — protocol refinement: re-verify against the ORIGIN TIP AT ACTIVATION TIME

The standing re-verification targets the **origin tip at activation time**, never a fixed
SHA from a notice. **Cross-lane notices are conveniences, never gates.** At the next
activation (scene numbers arrival), diff the then-tip against the last verified baseline
before authoring fixtures.

**Discharged in full.** Fetched the real tip first (`018d109437bba4a779c3293aa801c9e17465ec14`,
matching the notice — confirmed, not assumed), then ran everything below against it.

### RULING 20 — the notice's own claim checked first, and it holds

The notice said `journal_log.py` was "believed untouched". **It is untouched** — empty
diff, byte-identical blob. The hedge was unnecessary, but the check was still run.

### What `018d109` changed

Three files, `+25/-4`. Only one in `src/`: **`transcribe.py` +13**, adding
`capture.lifecycle` to the schema journal — aggregate-only mic numbers
(`node`, `first_frame_latency_ms`, `first_speech_frame_s`, `frames`, `bytes`), verdicts
`ok`/`no-frames`. Plus Stream H's own sensor tests and HANDOFF. **No journal machinery
change, no phrasing change.**

### Full drift table vs `018d109` — CLEAN

| Check | Result |
|---|---|
| `journal_log.py` `462fa98..018d109` | **byte-identical** |
| `audio kept at` sites | **4, character-identical, same line numbers** (transcribe.py 418/1451/1464, daemon.py 2405) |
| All three WP7 event names | **still emitted** (daemon.py:2395, transcribe.py:1460/415/425/1448) |
| Full §2 verification table vs 018d109's actual module | **ALL 12 CHECKS PASS** |

### The new event, checked for the collision trap

Every additive schema line is a fresh chance for another verdict collision, so the new
shape was executed, not reasoned about:

- `capture.lifecycle` verdicts are **`ok` / `no-frames`** — **NO collision** with the WP7
  set (`landed`/`deferred`/`closed`/`rejected`).
- Its detail carries **no content and no filesystem path** — the notice's
  "aggregate-only, never content" claim verified in the string itself.
- **The pre-existing collision is still present** (`fallback.outcome` and
  `transcription.landed` both emit `landed`), so §2.1 remains load-bearing.

`capture.lifecycle` is **inert to the watcher**: nothing to dispatch on, no path to
extract, nothing to fence.

### Baseline re-measured — UNCHANGED

Throwaway worktree at `018d109` on CPython 3.11: **1925 passed / 6 skipped / 0 errors,
ruff clean.** Same as `462fa98`. The corrected baseline holds.

### Standing commitment re-armed, both clauses

On every base movement: re-run the drift check **and** re-measure the suite.

---

## 2026-10-27 — DOCTRINE RATIFIED (TWO CLAUSES) + GATE 1e RE-DATED TO b3db316 + THE STALE-NOTICE CATCH

Report 011 is the record. The design chat adopted both flags as doctrine and immediately
supplied a test case — which the test case itself failed.

### RULING 21 — FLAG 1 ADOPTED AS DOCTRINE

The standing commitment is **two clauses**: every base movement requires the drift check
**and** a suite re-measure at activation time. A.1 proved a baseline can move without the
contract moving.

### RULING 22 — FLAG 2 CONFIRMED

The GATE 1e window re-dates and the full check re-runs on ANY further base movement
before fixture authorship.

### RULING 23 — NEW CANONICAL SUITE BASELINE (both lanes)

**1,925 passed / 6 skipped / 0 errors, ruff clean.** My measurement supersedes the commit
message and every prior report. The A.1 arc — found in my lane, offered as a one-liner,
adopted by mainline, measured back by me — is recorded as the cross-lane doctrine's first
full closed loop.

### RULING 24 — manifest path shape accepted; Q13 confirmed as pre-fixture next-activation
work, correctly flagged.

### RULING 25 — posture unchanged: STOPPED AT GATE 1. Sheets 1+2 numbers gate everything;
PR #24 stands as the durable record.

### THE STALE-NOTICE CATCH — the doctrine's first real payoff

The design chat's own notice named `018d109` as the current tip and told me to verify
rather than trust it. **The actual origin tip at activation was
`b3db316914235caee40f4c650072c9e06fb0288c`** — one commit beyond the notice.

Not Stream H's fault: their `HANDOFF.md` record shows their activation verified
`origin tip = 018d109`, and `b3db316` **is the commit that records that verification**.
The notice was accurate when written and had been overtaken by the very commit it
described.

**Had I accepted the notice's SHA, I would have re-dated GATE 1e to a baseline that was no
longer the tip** and reported a clean check against the wrong commit. Fetching the origin
tip at activation time is not ceremony — it paid for itself on the first try.

### Two-clause check vs `b3db316` — CLEAN

| Check | Result |
|---|---|
| `git diff 018d109..b3db316 -- src/assistant/journal_log.py` | **empty — untouched** |
| `git diff 018d109..b3db316 -- src/` | **empty — no source change at all** |
| `audio kept at` sites | **4, character-identical, same line numbers** |
| Three WP7 event names | **all still emitted** |
| Full §2 verification table vs b3db316's actual module | **ALL 12 CHECKS PASS** |
| Pre-existing verdict collision | **still present** → §2.1 still load-bearing |
| Suite, measured in a throwaway worktree on CPython 3.11 | **1925 passed / 6 skipped / 0 errors, ruff clean — UNCHANGED** |

A docs-only commit could not have moved the suite, and it did not. The measurement ran
anyway, because the doctrine is unconditional and A.1 taught that assuming a change is
inert is how a baseline goes stale.

### Useful structural fact from Stream H's record

`journal_log.py` was last touched by `30abf30` (stream G), and **`log_event` is generic —
"event is the caller's naming", no allowlist**. That is why `capture.lifecycle` needed no
journal-side change. For my lane it means new schema events need no coordination with the
journal machinery, so future additive lines are **inert by construction** unless they
collide on verdict.

### Standing commitment re-armed (two clauses, now doctrine)

On every base movement: re-run the drift check **and** re-measure the suite, against the
**origin tip at activation time**.

---

## 2026-10-31 — MEASURED COMPRESSION BAND (design-chat ratio addendum); CAPACITY TABLE RECOMPUTED

Report 013 is the record. The zero-compression floor that every WP7 number was built on
has been replaced by a **measured** band. The direction is favorable and the ruling raises
no retune flag — but it moves three thresholds, and one of them moves enough to matter.

### RULING 34 — measured real-voice zstd -19 ratios are the FINAL band

| Measurement | Ratio | Source artifact |
|---|---|---|
| Watchdog capture | **0.475** | 9,637,484 B |
| Session wav | **0.582** | 330,284 B |

**Cold weighs 48–58% of hot.** This **supersedes the expected 0.6–0.9**, which was
conservative; the direction is favorable and raises no retune flag. All else per the
config-finalization block stands.

### What this replaces

Report 004's capacity model carried an explicit standing assumption:
*"compression gain = 0 until Scene Sheet 2 measures one real restic/zstd ratio on a real
kept wav."* **That line is now discharged** — Sheet 2's "one measured zstd ratio"
obligation is met, and met with two measurements rather than one. The census (`du`
aggregates, kept-wav count) is still owed and still gates the final numeric defaults.

### Evidence class — recorded, not glossed

These are **zstd -19 ratios measured on real voice wavs**: [TESTED-ONLY], measured on real
audio, but **not** an end-to-end restic-over-MEGA round trip. restic's own compression is
zstd, so the ratio is the right shape — but restic adds pack overhead, dedup metadata and
the rclone/MEGA transport, none of which is in these numbers. **The end-to-end cold weight
will therefore be ≥48% of hot, probably somewhat more.** Capacity planning uses the
conservative end of the band (0.582) as the working figure; the favourable end (0.475) is
headroom, not a plan. Only Sheet 1's benchmark can close the gap.

### A size observation worth carrying

The 9.6 MB watchdog capture compressed **better** (0.475) than the 330 KB session wav
(0.582). zstd's window means larger inputs compress better, so **the band is
size-dependent, not a single constant**. Any future measurement should record the artifact
size alongside the ratio, and the band should be re-derived if the kept-wav census shows a
very different size mix than these two samples.

### The three thresholds that moved

1. **WP5 daily allowance (the headline):** `~10 kept-min/day at the floor, ~20 at 2x`
   becomes **28.4–38.3 kept-min/day** — **2.9x–3.9x the floor**. The owner's practical
   daily budget is roughly three times what the conservative floor implied.
2. **12-month bar:** `28.5 kept-min/day` at the floor becomes **49.0–60.1 kept-min/day**
   (**1.7x–2.1x**).
3. **Flood math:** one 8-hour event day consumed **16.8 days** of the 12-month budget at
   the floor; it now consumes **8.0–9.8 days**. Still a heavy day, but no longer
   catastrophic.

### The event-frequency verdict table, recomputed

Months to fill 20 GB with 8-hour events alone (raw 921.6 MB each):

| Frequency | raw GB/yr | cold @0.475 | cold @0.582 | **months @0.475** | **months @0.582** | old floor |
|---|---|---|---|---|---|---|
| daily | 336.38 | 159.78 | 195.78 | 1.5 | 1.2 | 0.7 |
| 2x/week | 95.85 | 45.53 | 55.78 | 5.3 | 4.3 | 2.5 |
| weekly | 47.92 | 22.76 | 27.89 | 10.5 | 8.6 | 5.0 |
| fortnightly | 23.96 | 11.38 | 13.95 | **21.1** | **17.2** | 10.0 |
| **monthly (ruled target)** | 11.06 | 5.25 | 6.44 | **45.7** | **37.3** | 21.7 |
| quarterly | 3.69 | 1.75 | 2.15 | 137.1 | 111.9 | 65.1 |

**The ruled design target stands: MONTHLY.** It now has **37.3–45.7 months** of headroom
against a 12-month requirement — roughly double the floor's 21.7 — so the target is
comfortable rather than marginal.

**But one threshold genuinely moved, and it is recorded rather than smoothed over:**
**fortnightly now clears 12 months (17.2–21.1) where the floor said it did not (10.0).**
Weekly still does not clear (8.6–10.5). So the "highest frequency that survives" line has
shifted from monthly to fortnightly. Monthly remains the ruled target — the ruling says
compression is headroom, not a requirement — but the owner now has a measured basis to
choose fortnightly if a denser event calendar is wanted. **That is a design-chat decision,
not a lane decision, and it is raised as Q24 rather than acted on.**

### Config impact

No `[backup]` default changes. The measured band informs the capacity model and the
capacity-floor knock threshold, which are `INTERIM-PENDING-SHEETS` pending the census. The
`hot_window_days` / `hot_window_gb` pair governs how long audio stays HOT before going
cold and is unaffected by the compression ratio.

---

## 2026-10-31 — CENSUS DELIVERED; DEFAULTS FINAL; Q24 RULED; CAPACITY RECOMPUTED

Report 014 is the record. The owed Sheet-2 census line has been discharged, four
`[backup]` values have moved from interim to FINAL, and the capacity table has been
recomputed with census and band together.

### RULING 35 — THE CENSUS (discharges the owed line)

| Fact | Value |
|---|---|
| Files in `audio/` | **37** = 35 session wavs + 2 artifacts |
| Kept-session bytes | **80,698,682 B** (80.70 MB / 76.96 MiB) |
| `du -sb audio/` | **138,298,770 B** |
| Assistant tree | 372 M |
| `event-spike.wav` | 57,600,044 B — synthetic 30-min test tone, **relocated by owner order** to `~/.local/share/assistant/test-assets/`; WP5 spike-path paperwork = **M-1, mainline's** |
| `20261025-181730-4d90bf.wav` | **44 bytes**, header-only, **never-retry mark under the deferred-audio contract, counts zero forever** |
| Growth | **≈11–13 MiB/day**, including one 9.6 MB runaway outlier |

**Census arithmetic self-checks exactly:** 80,698,682 + 57,600,044 + 44 = 138,298,770 =
`du -sb audio/`. Tierable = **80.70 MB**; excluded = 57.60 MB.

**Average kept session wav = 2.306 MB = 1.20 kept-minutes** (raw, at 1.92 MB/min). The
typical kept session is about a minute and a quarter — a fact worth having when reading
every capacity number below.

**PERMANENT EXCLUSIONS from tiering and trim (ruled, forever):** voice-cache and
test-assets. The reasons are contracts, not tidiness — **0 ms recall** for the voice cache
and **offline-voice** for test-assets. Neither may ever be trimmed to reclaim space.

### RULING 36 — DEFAULTS FINAL (INTERIM tags removed for these four)

| Key | Was (interim) | **Now (FINAL-CENSUS)** |
|---|---|---|
| `hot_window_days` | 14 | **14** — value unchanged, status final |
| `hot_window_gb` | 2 | **2** — value unchanged, status final |
| `restic_pack_size_mib` | 16 | **128** — fewer MEGA objects/requests; temp-space cost accepted |
| `capacity_floor_gb` | 2 | **10** — 50% of the free tier |

`trim_grace_days` **stays `INTERIM-PENDING-SHEETS`** — the grace period was not part of
the census and no measurement bounds it. It is the last interim value in `[backup]`.

**HOT window confirmed: the 14-day WINDOW binds, not the 2 GB cap.** At measured growth,
14 days of hot audio is 154–182 MiB ≈ 0.15–0.18 GiB, about **11x under** the cap. The cap
is a backstop, not the operative limit — the ruling's parenthetical is confirmed by
arithmetic.

**Capacity-floor semantic note, recorded so it cannot be misread:** the key is expressed
as `remote_free` (knock when free < 10 GB), which on a 20 GB tier is **equivalent to
"10 GB consumed"** — the ruling's phrasing. Same threshold, two spellings.

**Capacity ruling: GO** — the machinery is built and the numbers below are the basis.

### RULING 37 — Q24 RULED = (c) then (a)

- Event frequency stays **MONTHLY** until Sheet 1 measures the end-to-end
  restic-over-MEGA ratio.
- **Fortnightly is recorded as a measured, owner-available option (17.2–21.1 months) that
  ONLY the owner may pick, by number, on their own initiative.**
- **Weekly remains ruled out** (8.6–10.5 months).
- **The lane does not re-propose frequency absent an owner word.**
- Sheet 1's added job is ratified: measure the end-to-end ratio so the overhead between
  the zstd band and the true cold weight closes. Until then the conservative end plans.

### THE RECOMPUTED CAPACITY TABLE (census + band; old-floor column RETIRED to history)

**Cold growth:** hot 11.53–13.63 MB/day (6.0–7.1 kept-min/day) → **cold 5.48–7.93 MB/day**.
**Monthly 8-hour events cold:** 5.25–6.44 GB/yr = **14.39–17.64 MB/day**.

| Scenario | 10 GB knock | 20 GB full tier |
|---|---|---|
| Daily audio only, best (0.475) | **5.00 yr** | **10.00 yr** |
| Daily audio only, worst (0.582) | **3.45 yr** | **6.91 yr** |
| Daily audio **+ monthly events**, best | **1.38 yr** | **2.76 yr** |
| Daily audio **+ monthly events**, worst | **1.07 yr** | **2.14 yr** |

**The old-floor column is retired to history per the ruling.** Report 004's zero-compression
figures remain as the historical record of what was assumed before measurement.

### TWO STRUCTURAL FINDINGS THE CENSUS PRODUCED

1. **Monthly events dominate daily audio by 2–3x** (14.39–17.64 vs 5.48–7.93 MB/day cold).
   The event calendar is the dominant capacity driver, not daily usage — consistent with
   the whole flood-math thread, and the reason frequency is an owner decision rather than
   a lane one.
2. **Actual usage is well under plan:** the census implies 6.0–7.1 kept-min/day against the
   WP5 allowance of 28.4–38.3 — **16–25% of budget**. The owner is not near the allowance,
   which is the favourable reading.

### AN HONEST DISAGREEMENT, RECORDED RATHER THAN SMOOTHED OVER

The ruling states *"at the measured band the floor clears in decades."* **My arithmetic
does not reproduce that**, and the gap is large enough that it must be surfaced rather
than absorbed:

- daily audio alone reaches the 10 GB knock in **3.45–5.00 years**, and fills the tier in
  **6.91–10.00 years**;
- adding the ruled monthly events brings the knock to **1.07–1.38 years** and a full tier
  to **2.14–2.76 years**.

**None of those is decades.** The GO ruling stands — the machinery is built either way, and
the knock is a *designed pressure gauge* that is supposed to fire so the owner can act on a
lever. But the owner should know the gauge will fire in **roughly one to five years**, not
in decades, and that the monthly event calendar is what pulls it forward from ~4 years to
~1 year. Raised as **Q26**.

### Config applied

`src/assistant/config.py` `DEFAULTS["backup"]` and `config.toml.example` both updated;
parity verified. The label test was **evolved rather than deleted**: it now enforces the
two-marker split (`INTERIM-PENDING-SHEETS` vs `FINAL-CENSUS`) so an unmeasured value cannot
be quietly promoted, and a census-backed value must say so. A second test pins the FINAL
numbers. Full suite **1928 passed / 6 skipped / 0 errors**, ruff clean.

---

## 2026-10-27 — DOCTRINE RE-TIMED: POLLING ENDS, CONSUMPTION-TIME BEGINS. LANE SLEEPS UNTIL OWNER NUMBERS

Report 011 was accepted and the verification doctrine is **re-timed**. This activation
recorded the ruling and did nothing else, by instruction. No phase report was written for
this activation — there was no phase work to report, and manufacturing one would be
exactly the thing the ruling forbids. The next report is at consumption time or when the
owner's numbers arrive.

### RULING 26 — the two-clause check is re-timed to CONSUMPTION TIME

- The two-clause check (drift + suite) now runs **ONCE at fixture authorship / any
  code-consumption event**, against the origin tip at that moment. That is the only
  load-bearing check — **no consumer of the contract exists before fixtures, so late
  discovery costs zero.**
- **Bare base movements trigger NOTHING.** No activation is spent re-dating.
  **`b3db316` is the last per-movement re-dating; GATE 1e re-dates once, at closing.**
- **Sole early trigger:** a **NAMED shape/phrasing change flag from mainline** (their
  A.2-R phase-report obligation) — never a bare SHA move.

**Standing reason this re-timing is safe (recorded):** `log_event` is generic, no
allowlist, so new schema events are **inert by construction** absent a verdict collision.
The structural fact from report 011 is now the load-bearing justification, not a
footnote.

### RULING 27 — the stale-notice catch is recorded as the protocol's first real catch

It caught the design chat's own freshest relay. The notice was accurate when written and
overtaken by the commit that recorded its verification. **Fetch-not-read paid for itself
against the best-case source. Relays are claims; the relay was treated as one. Correct.**

### RULING 28 — LANE POSTURE: SLEEP UNTIL OWNER NUMBERS

**No manufactured work.** The contract-shaped design is already canonical (007 §2/§2.1);
tiers/windows wait on Sheet 2, backend details on Sheet 1, fixtures on Q13 plus the
consumption-time check. Drafting them now would be **unverified assumptions in
design-document clothes. Waiting is the gate working.**

**If activated before numbers arrive: acknowledge, do nothing.**

### RULING 29 — baseline unchanged: 1925/6/0, ruff clean. PR #24 stands as the durable
record. Posture: STOPPED AT GATE 1 — the real gate, the owner's hands.

### What this entry exists to prevent

A future activation, seeing "the base moved", re-running the two-clause check and
re-dating GATE 1e. **That is now forbidden.** The check fires once, at consumption time.
The only thing that can wake this lane early is a **named** shape/phrasing change flag
from mainline — never a bare SHA move, and never an inference from a relay's silence.

---

## 2026-10-31 — RECORD-ONLY ACTIVATION APPROVED; SAFETY ADDENDUM; IDLE CADENCE; LANE ASLEEP

Report 011's re-timing is in force. This entry records three rulings received on
2026-10-31. No phase report was written — no phase work occurred, and "no phase report
without phase work" is standing doctrine from the previous activation forward.

### RULING 30 — the record-only activation is approved as-is

Recording the re-timing ruling plus the prevention note was the entire correct output.
**Skipping the two-clause check was compliance with the ruling, not an omission.**
"No phase report without phase work" is standing doctrine from this point forward.

### RULING 31 — FLAG 1: the harness branch line is a STATUS NOTE, not an instruction

`arena/e7a1cca5-elaria` **remains frozen at `b181712` with zero new commits, forever.**
All storage commits land on `arena/storage`.

**SAFETY ADDENDUM (binding, new):** if the harness ever stops **reporting** the frozen
branch and starts **enforcing** it — a forced checkout, or a push aimed at it — **STOP and
report to the design chat BEFORE pushing.** A misread status line is cheap; a push into
frozen history is not.

### RULING 32 — FLAG 2: idle cadence approved

Woken with no new input = one line, *"stopped at Gate 1, waiting on owner numbers"*, then
sleep. **Wake triggers are exactly three and exhaustive:**

1. The owner's Sheets numbers.
2. A named shape change flagged by mainline.
3. A design-chat wake.

**No polling, no re-dating, no reporting nothing.**

### Posture

**ASLEEP AT GATE 1.** Next expected wake carries the owner's **Sheet 2** numbers — `du`
aggregates, kept-wav census (**now 35+ wavs, including the 9.6 MB watchdog capture**), and
one measured zstd ratio — then **Sheet 1** (MEGA in browser, owner-run rclone config,
benchmark).

**Until then, silence is the correct output.**

### What this entry exists to prevent

A future activation treating a bare harness status line as a reason to switch branches,
or treating silence from mainline as a wake trigger. The frozen branch is frozen **by
ruling**, the only exception path is the enforcement contingency in Ruling 31, and idle
means idle.

---

## 2026-10-31 — GATE 1 AMENDED: MACHINERY CONSTRUCTION BEGINS NOW (owner order)

**Owner, verbatim: "lets start building the storage."**

Recorded **before any other work this activation**, per the owner's explicit instruction.

### RULING 33 — Gate 1 is AMENDED

The owner's Sheet numbers are **re-scoped from build-blocker to config-finalization and
live-traffic gate.** Machinery construction begins **now**.

- **Unblocked for construction (synthetic fixtures only, sandbox):** storage manifest;
  reconcile-on-start; crash-point tests; tiering engine with HOT window/GB in config under
  interim defaults (**HOT=14d/2GB**, every such value labeled `INTERIM-PENDING-SHEETS`);
  event-sized post-close hook + nightly timer unit; WP5 monthly trigger shape; cold read
  path written against the **rclone remote abstraction** and tested with a **local rclone
  backend fixture** — never MEGA in sandbox; `assist backup fetch`; sensors `backup.*` /
  `storage.gauge` per the additive schema contract (report 007 §2: seven fields,
  `split(" ", 6)`, session_id rules); ladder chain #5; monthly restore-drill scaffolding;
  restic-over-rclone wiring per §2.12 including the documented MEGA config pins
  (`timeout = 5m` et al) as a **config template, not live usage**.
- **STILL GATED, unchanged:**
  - ANY live MEGA traffic until Sheet 1 benchmark output pastes to design and a go/no-go
    returns.
  - Final numeric defaults (HOT window/GB, pack size, capacity-floor knock thresholds)
    until Sheet 2 census pastes.
  - Merge until gate v2 passes on mainline.
  - The additive-only firewall in full: `cli.py` / `config.py` / `ladder.py` /
    `pyproject.toml` registration points only; **zero edits to `daemon.py`,
    `transcribe.py`, `live_client.py`, `HANDOFF.md`.**
  - The owner's real wavs and content never enter this sandbox.

### Cadence for construction activations

DONE / DEFECTS FOUND / NEXT GATE / OPEN QUESTIONS per activation; ambiguities as
multiple-choice via owner relay; **evidence tags on every claim**; suite + ruff clean per
commit at the recorded branch baseline; **no reports about nothing**.

**First report owed:** build plan (machinery increment order, synthetic fixture inventory,
interim-defaults table with labels) **plus the first landed increment.** No hardware scene
requests until design schedules them.

### What this amendment does NOT change

The frozen branch, the three wake triggers, the §2 canonical journal contract and its §2.1
dispatch rule, the privacy fence, and the two-clause consumption-time check. The lane is no
longer *idle*, but it is still **STOPPED AT GATE 1** for live traffic and merge — only the
build blocker has been lifted.

---

## 2026-10-31 — Q26 RULED (b) THEN (a); "DECADES" FORMALLY RETRACTED; CENSUS WINDOW SUPPLIED; TABLE SPLIT

Report 015 is the record. **This entry is appended at the true end of the file** — see the
ordering defect recorded first, because two earlier entries are physically in the wrong
place and a reader needs to know that before anything else.

### DEFECT IN MY OWN APPEND DISCIPLINE — recorded, not hidden

`docs/storage-handoff.md` is append-only with newest at bottom. Reports **013 and 014 are
physically mid-file**, not at the bottom: report 013 sits at ~line 929 (immediately after
report 011's "Standing commitment re-armed" block) and report 014 at ~line 1017. The true
chronological order of the last six entries is:

```
011 (report 011, base b3db316)
  -> DOCTRINE RE-TIMED (record-only activation)
  -> RECORD-ONLY ACTIVATION APPROVED (safety addendum, idle cadence)
  -> GATE 1 AMENDED / RULING 33 (owner order: build now)
  -> 012 (build plan + increment 1 landed)
  -> 013 (measured compression band)
  -> 014 (census, defaults FINAL, capacity recomputed)
  -> THIS ENTRY
```

**Root cause, recorded so it cannot recur:** I appended with a text anchor rather than at
the file's end, and `edit_file` replaces the **first** match. The anchor
"Standing commitment re-armed (two clauses, now doctrine)" appears twice — once ending
report 011 mid-file and once later — so the first match won and the entry landed mid-file.
Report 014 then anchored on report 013's tail and inherited the same position.

**Nothing was deleted, moved or rewritten** — the append-only rule is intact, and the two
entries are complete and correct in content. Only their physical position is wrong.
**Corrective habit from this activation forward: append with a shell append (`cat >>`),
never with a text anchor.** A text anchor can match mid-file; a shell append cannot.

### RULING 38 — Q26 = (b) then (a); the lane's lean adopted

**The honest statement is YEARS, and it is now the lane's canonical number:**

| Scenario | 10 GB knock | 20 GB full tier |
|---|---|---|
| Daily audio only | **3.45–5.00 yr** | **6.91–10.00 yr** |
| Daily audio **+ ruled monthly events** | **1.07–1.38 yr** | **2.14–2.76 yr** |

**The design chat's "decades" wording is FORMALLY RETRACTED.** It was a months-versus-years
conflation — **60 months read as 60 years**. Recorded here beside the ruling so no future
activation inherits the word. Any later figure quoting "decades" for this lane is wrong by
construction and should be treated as a **corrupted relay, not a datum**.

**The GO ruling stands unchanged:** the knock is a **designed pressure gauge**, and its
levers are enumerated for the owner:
1. **event frequency** — the owner's number, under Q24 doctrine;
2. **`trim_grace_days`** — the last unmeasured `[backup]` value, interim until an owner
   word or the WP5 event shape lands;
3. **cold retention policy** — lever (c) from the original four-lever menu.

### RULING 39 — the census window, discharging "the period wasn't given"

Kept-wav filenames span **2026-10-25 → 2026-10-31, six days** — oldest
`20261025-181730-4d90bf`, newest `20261031-145603-94129e`.

| Quantity | Computed | Ruling's figure |
|---|---|---|
| Observed total rate | 76.96 MiB / 6 d = **12.83 MiB/day** | 11–13 MiB/day |
| Outlier (9,637,484 B) | 9.19 MiB / 6 d = **1.53 MiB/day** | ≈1.6 MiB/day |
| **Steady state** | **11.29 MiB/day** | ≈9.5–11.5 MiB/day |
| Outlier share of volume | **11.9%** | — |

**CAVEAT, carried verbatim in force:** the span is observed from filenames in this census
only. Wavs older than 10-25 may have existed and been trimmed before the census, so the
window is a **lower bound on the observation period**, not a claim about history.

### THE CAPACITY TABLE, SPLIT BY COLUMN — and what the split settles

| Scenario | Column A: total, outlier **included** (11–13 MiB/d) | Column B: **steady-state** (9.5–11.5 MiB/d) |
|---|---|---|
| Cold growth | 5.48–7.93 MB/day | 4.73–7.02 MB/day |
| 10 GB knock, daily only | 3.45–5.00 yr | **3.90–5.79 yr** |
| 20 GB full, daily only | 6.91–10.00 yr | **7.81–11.58 yr** |
| 10 GB knock, + monthly events | 1.07–1.38 yr | **1.11–1.43 yr** |
| 20 GB full, + monthly events | 2.14–2.76 yr | **2.22–2.87 yr** |

**What the split settles, and it is the real answer to Q26:** separating the outlier moves
the projections by **+13%** and changes nothing. The outlier is 11.9% of volume — it was
**never** the explanation for a decades/years gap. The gap was the conflation, and the
conflation is retracted. Q26 option (b) was the right instinct and the right order, but its
effect is a 13% improvement, not an order of magnitude.

**Column A is the conservative planning column** and stays canonical; Column B is recorded
because the ruling asked for the separation and because it is the honest steady-state
figure.

### RULING 40 — structural findings recorded as ruling-grade

1. **Monthly events dominate daily audio 2–3×** — the event calendar is the capacity driver.
2. **Actual usage is 16–25% of the WP5 daily allowance** — event headroom is real and large.

### RULING 41 — Ruling 36 defaults ratified, including the evolved label test

The FINAL/INTERIM split enforcement stands as built.

### Cadence constraints carried forward

No re-proposal of frequency absent an owner word. No promotion of `trim_grace_days` absent
measurement or owner ruling.

---

## 2026-10-31 — INCREMENT 2 LANDED: reconcile-on-start + crash-point tests

Report 015 is the record. Appended with a shell append, per the corrective habit recorded
in the previous entry.

### What landed

`src/assistant/backup.py` (new) + 20 tests. All three spec crash points pinned:

1. **Killed between upload and flip** → reconcile re-verifies (local file must exist and
   hash to the recorded sha256; the remote must confirm) **then** flips. A verification
   failure defers and records a problem; it never guesses.
2. **Killed between flip and trim** → trim is planned and **idempotency is structural** —
   the state machine has no `trashed -> trashed` edge, so once trashed no further trim is
   ever planned. A test runs reconcile twice and asserts the mover fired exactly once.
3. **Flip fsync'd before any trim** → `append()` fsyncs before returning, and `reconcile()`
   appends the flip *before* calling the trim mover. A test has the mover record what the
   manifest says at the moment it runs; it must see `flipped`, not `uploaded`.

**The refusals are the important half.** Five tests assert reconcile *declines*: local hash
drifted, remote does not confirm, **no verifier configured**, local artifact vanished, trim
mover absent. The no-verifier case is the posture increment 2 must hold before increment 4
supplies a real remote — without one, an `uploaded` artifact is left exactly where the crash
left it rather than flipped on trust.

### Design decision recorded: ONE STATE PER PASS

A single reconcile pass advances each artifact by **at most one state**, so
`uploaded -> trashed` takes two passes, driven by `reconcile_all()` looping to quiescence.

**This is deliberate and it is the safer semantics.** Advancing several states in one pass
would mean a single crash could skip a verification step. With one step per pass, a crash
mid-reconcile leaves every artifact at most one step further on, each step separately
verified before the next is attempted. A test pins this explicitly
(`test_one_pass_advances_at_most_one_state`).

If the owner prefers a single advancing pass, that is a design-chat entry, not a lane change
(Q27).

### Privacy fence held

`ReconcilePlan.summary()` is path-blind; a test asserts no path fragment appears in it.

### Verification

Full suite **1948 passed / 6 skipped / 0 errors** (branch baseline 1928 + 20 new), ruff
clean. Firewall clean — no edits to `daemon.py`, `transcribe.py`, `live_client.py`,
`HANDOFF.md`, `tests/conftest.py`.

### Increment 3 is now unblocked in a specific way

Increment 2 supplied the `trim_mover` seam, so increment 3 implements the real mover (grace
clock, trash dir; idempotency already structural). It must honour the census's **permanent
exclusions**: voice-cache and test-assets are never tiered or trimmed, forever.
