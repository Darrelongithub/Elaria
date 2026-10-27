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
