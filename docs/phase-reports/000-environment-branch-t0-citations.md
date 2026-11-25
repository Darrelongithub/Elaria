# Phase report 000 — environment discovery, branch reconciliation, T0 citations

**Date:** 2026-10-27
**Phase:** WP7 pre-flight (no WP7 code written this turn)
**Builder:** storage builder, branch `arena/e7a1cca5-elaria` @ `ed20344`
**Scope check:** WP7 only. WP8 (corpus package) remains DEFERRED by owner order —
not started, not designed, not stubbed.

---

## DONE

### 1. Environment discovery — every claim [HW-PROVEN], measured not assumed

| Fact | Value |
|---|---|
| Python | 3.11.2 (`/usr/bin/python3`) |
| `uv` | not installed |
| `pytest` / `ruff` | not installed system-wide; installed into `./.venv` (gitignored) |
| `restic` | not installed in sandbox — expected, it is a `dnf` binary on the laptop |
| `rclone` | not installed in sandbox — same |
| Suite baseline | **1780 passed, 6 skipped**, ~97 s |
| `ruff check .` | **All checks passed** |
| Remote refs | `origin/HEAD -> origin/main`, `origin/main` — nothing else |

Baseline discipline: the WP7 brief quoted 1,887 passed / 6 skipped for the
mainline suite. This checkout measures 1780 / 6. The skip count matches exactly;
the delta is consistent with mainline work that has not landed here. Nothing in
this repo was modified to reach that number, and the suite is re-run before
every commit from here on.

### 2. Branch reconciliation

- `origin/arena/c2a7085d-elaria` does not exist. Commit `0c08cb5` is not a valid
  object here.
- `arena/e7a1cca5-elaria` == `origin/main` == `ed20344`.
- Work proceeds on `arena/e7a1cca5-elaria` and the separate WP7 PR is opened
  from it. No branch created, switched to, or force-pushed.

### 3. T0 citations — collected before any code

#### 3.1 restic's `rclone:` backend mechanics

> "Internally, restic runs `rclone serve restic --stdio`, and it will serve HTTP
> requests via HTTP2 on stdin/stdout. This is great because it does not need any
> network connections, all data is only available to the user running the restic
> and rclone processes (except for the super user root). There's also no need to
> coordinate local TCP ports with other users on the system, and restic can
> easily start and stop the rclone process. It is even possible to run multiple
> instances of restic/rclone in parallel without having to configure any TCP
> ports."
> — restic.net, "Using rclone as a restic Backend", 2018-04-01
> <https://restic.net/blog/2018-04-01/rclone-backend/>

The backend spec format is `rclone:<remote>:<path>`, and the `<remote>:<path>`
part is passed straight through to rclone. restic builds the argv by joining
`rclone.program`, `rclone.args`, then the part after the `rclone:` prefix.
Default `rclone.args` is `serve restic --stdio --b2-hard-delete`; default
`rclone.program` is `rclone`; default `rclone.timeout` is **1m**.

> "In order to start rclone, restic will build a list of arguments by joining
> the following lists (in this order): rclone.program, rclone.args and as the
> last parameter the value that follows the rclone: prefix of the repository
> specification."
> — restic, "Preparing a new repository"
> <https://restic.readthedocs.io/en/latest/030_preparing_a_new_repo.html>

**Consequence for WP7:** there is no server to run, no port to open, no unit to
supervise, and nothing for the systemd timer to start except `restic` itself.
Provider swap = one config line (`rclone:<remote>:<path>`), zero code change.

**MEGA-specific timeout trap.** `rclone.timeout` defaults to 1m, and MEGA is
slow to open a repository because rclone must download and decrypt account
metadata on connect. restic issue #3511 is exactly this failure
(`unable to open repo at rclone:mega:... context deadline exceeded`) and PR
#3514 raised the default to 240 s. The WP7 wrapper must set
`-o rclone.timeout` explicitly rather than rely on the default.
<https://github.com/restic/restic/issues/3511>,
<https://github.com/restic/restic/pull/3514>

#### 3.2 Known rclone MEGA-backend limitations under many-small-object workloads

From <https://rclone.org/mega/> (backend added v1.41, classified **Tier 2**):

> "Mega does not support modification times or hashes yet."
> "Mega can have two files with exactly the same name and path (unlike a normal
> file system). Duplicated files cause problems with the syncing and you will
> see messages in the log about duplicates. Use `rclone dedupe` to fix
> duplicated files."
> "Mega remotes seem to get blocked (reject logins) under 'heavy use'. We
> haven't worked out the exact blocking rules but it seems to be related to fast
> paced, successive rclone commands. For example, executing this command 90
> times in a row `rclone link remote:file` will cause the remote to become
> 'blocked'. … After more or less a week, the remote will remote accept rclone
> logins normally again."

restic's own repository layout is exactly the many-small-object shape this
hurts: `data/` packs, `index/` index shards, `snapshots/`, `keys/`, `locks/`.
Corroborating field reports:

> "I suspect it's because restic uploads a lot of tiny files, which is a
> worst-case scenario for drive." … "Changing the pack size to 256 MB does
> appear to have solved the speed problems!"
> — restic forum, "Slow speeds of Restic with Google Drive rclone backend"
> <https://forum.restic.net/t/slow-speeds-of-restic-with-google-drive-rclone-backend/818>

> "Restic + Mega + Rclone serve epiphany … While Restic + Rclone works with
> Mega, starting any operation was extremely slow, it usually took more than a
> minute just to open the repo (I had to set --option=rclone.timeout to make it
> work!). This is probably due to the number of files I have there: 6 TB of
> Restic backups, that's a lot of files."
> — restic forum, 2025-02-05
> <https://forum.restic.net/t/restic-mega-rclone-serve-epiphany/9086>

Also from the same rclone page: the classic MEGA backend stores the password as
`pass = *** ENCRYPTED ***` in `rclone.conf`, and the `--mega-pass` doc says
*"Input to this must be obscured — see `rclone obscure`"*. **Obscured, not
encrypted** — this is the fact the privacy note in the WP7 brief rests on, and
it is why `rclone.conf` is accepted at 0600 outside the repo and never in git.

And, verbatim from the top of that page:

> "**Note** MEGA S4 Object Storage, an S3 compatible object store, also works
> with rclone and this is recommended for new projects."

S4 is a paid product, so the $0 doctrine keeps the classic backend. This is
recorded as an **accepted risk with a named mitigation path**, not a silent
workaround: if Scene Sheet 1's numbers fail the go/no-go, the design chat takes
options to the owner with the data.

#### 3.3 MEGA free-tier inactivity-deletion policy for dormant accounts

> "If you don't log in or use MEGA for an extended period, your account becomes
> inactive and we'll start sending you warning emails. If your account remains
> inactive, your data will eventually be deleted. **The whole process takes at
> least 10 months from your last activity.** Logging in or using MEGA apps and
> services at any point stops the process and keeps your data safe. **Only your
> data is deleted, not your account.** If you log back in after deletion, your
> account will be empty."
> — MEGA Help Centre, "Does my MEGA account ever expire?", updated 2026-06-19
> <https://help.mega.io/accounts/create-account/account-expiry>

MEGA's Terms of Service, clause "By us", names the trigger:

> "you are using a free account and that account has been inactive for over 3
> months and you have been given notice to act"
> — <https://mega.io/terms>

And what gets deleted:

> "If your account remains inactive, security-compromised, or over-quota after
> the warning period, the following items will be deleted: All files, All chat
> messages (including in-meeting chats), All your MEGA Pass information, All
> scheduled meetings. Folders themselves may remain, but they'll be empty."
> — MEGA Help Centre, "Why was my data deleted by MEGA?", updated 2026-07-24
> <https://help.mega.io/files-folders/data-deletion/data-deleted-by-mega>

**Consequence for WP7:** a nightly restic run is itself MEGA activity (uploads,
and any repo-open/list counts as use of the service), so an actively-backed-up
account is not dormant. The failure mode is the *opposite* one: the owner stops
using Elaria, the timer stops firing, and 3 months of silence starts a clock
that ends at 10 months with every cold copy gone. The ladder's
"last-backup age" rung is therefore also the anti-inactivity sensor, and a
stale last-backup must raise the knock — which it does anyway under the 2 GB /
integrity rules.

#### 3.4 MEGA transfer-quota semantics as they apply to restic's pattern

> "**Transfer** is the amount of data consumed by downloading or streaming files
> from MEGA. **Storage** is the amount of space taken up by your files on MEGA."
> "For free account holders or non-MEGA users, this limit is influenced by
> factors such as your geographical location and our current network usage. The
> limit is based on the amount of data downloaded from your IP address over the
> past six hours."
> "**Uploading files uses your storage quota, but not your transfer quota.**"
> "Transfer quota only begins to apply to a given file once that file has been
> transferred in full more than 10 times. Partial transfers count
> proportionally towards this threshold rather than as full transfers."
> — MEGA Help Centre, "What is transfer quota on MEGA?", updated 2026-05-23
> <https://help.mega.io/plans-storage/space-storage/transfer-quota>

MEGA publishes **no fixed number** for the free tier; the window is rolling and
per-IP, and third-party measurements cluster around roughly 1–5 GB per ~6
hours. Two consequences for restic's specific pattern:

- **`restic backup` (upload) does not consume transfer quota at all.** It
  consumes *storage* quota — which is the 20 GB cap the capacity model is about.
  So the nightly backup is not quota-shaped; it is *capacity*-shaped.
- **`restic check --read-data`, `--read-data-subset`, and `restic restore` /
  `fetch` DO consume it**, because they download. The monthly and quarterly
  drills therefore have a real, rolling, per-IP budget. This is precisely why
  the quarterly `--read-data-subset` is capped at ≤5% or ≤500 MB: a 5% subset of
  a small repo is a few hundred MB, comfortably inside one window; an uncapped
  `check --read-data` on a growing repo is not.
- The ">10 full transfers before a file counts" rule is why occasional restores
  are effectively free, and why the cold read path can be exercised freely for
  drills but should not be hammered.

#### 3.5 Restic pack-size knob and sane values for object-store-flaky backends

> "In certain instances, such as very large repositories (in the TiB range) or
> very fast upload connections, it is desirable to use larger pack sizes to
> reduce the number of files in the repository and improve upload performance.
> Notable examples are OpenStack Swift and some Google Drive Team accounts,
> where there are hard limits on the total number of files. … Restic currently
> defaults to a 16 MiB pack size. Note that this setting should be specified for
> each restic command that modifies the repository."
> "The side effect of increasing the pack size is requiring more disk space for
> temporary pack files created before uploading. … Restic requires temporary
> space according to the pack size, multiplied by the number of backend
> connections plus one. For example, if the backend uses 5 connections (the
> default for most backends), with a target pack size of 64 MiB, you'll need a
> minimum of 384 MiB of space in the temp directory."
> — restic, "Tuning parameters" (0.19.1)
> <https://restic.readthedocs.io/en/stable/047_tuning_parameters.html>

Hard limits, from `internal/repository/repository.go`: `MinPackSize` 4 MiB,
`DefaultPackSize` 16 MiB, `MaxPackSize` 128 MiB.

MEGA's own restic setup guide (for the paid S4 product, cited here only as the
vendor's stated tuning) recommends:

> "**Pack size: 64–128 MiB** – restic default is 16 MiB … Bigger packs mean
> fewer, larger objects: minimizing the number of nodes in the account optimizes
> performance and reduces the request rate. Requires repository format v2"
> — <https://help.mega.io/megas4/setup-guides/restic-setup-guide-for-mega-s4>

**Sane values for a flaky object store, reasoned from the above:** 16 MiB
default is the most conservative on temp space and the worst on object count;
128 MiB is the maximum and needs 768 MiB of temp at 5 connections. The brief's
~32 MiB is a defensible middle: 2× fewer objects than default, 192 MiB of temp
at 5 connections, and small enough that a failed multipart upload wastes little.
**The value is not chosen here — Scene Sheet 1 measures default vs 32 MiB and
the design chat rules.**

#### 3.6 systemd user timer `Persistent=true` catch-up semantics

> "`Persistent=` Takes a boolean argument. If true, the time when the service
> unit was last triggered is stored on disk. When the timer is activated, the
> service unit is triggered immediately if it would have been triggered at least
> once during the time when the timer was inactive. Such triggering is
> nonetheless subject to the delay imposed by `RandomizedDelaySec=`. This is
> useful to catch up on missed runs of the service when the system was powered
> down. Note that this setting only has an effect on timers configured with
> `OnCalendar=`. Defaults to `false`."
> — systemd.timer(5), systemd 262
> <https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html>

And the always-on suspend behaviour, which is a separate mechanism from
`Persistent=` and does not depend on it:

> "When a system is temporarily put to sleep (i.e. system suspend or
> hibernation) the realtime clock does not pause. When a calendar timer elapses
> while the system is sleeping it will not be acted on immediately, but once the
> system is later resumed it will catch up and process all timers that triggered
> while the system was sleeping. **Note that if a calendar timer elapsed more
> than once while the system was continuously sleeping the timer will only
> result in a single service activation.**"

**Consequence for WP7:** with `OnCalendar=daily` + `Persistent=true`, a laptop
that is off or asleep at 03:00 fires the backup on next activation of the timer
unit — i.e. on wake. But **a two-day sleep collapses to one activation, not
two.** So `Persistent=true` guarantees *at least one* catch-up, never *one per
missed night*. That is exactly why the brief's watcher-as-suspenders framing is
right, and why the ladder rung must read *last-backup age* (a fact about state)
rather than *runs last night* (a fact about the timer). `Persistent=true` is the
belt; the journal-tailing watcher is the suspenders; the ladder is the thing
that notices when both failed.

Also relevant: `WakeSystem=` "requires privileges and is thus generally only
available in the system service manager" — so a **user** timer cannot wake a
sleeping laptop. The catch-up is on resume, not on wake.

### 4. Capacity model — the number that decides FLAC

16 kHz mono 16-bit: `16000 samples/s × 2 bytes = 32,000 B/s = 115.2 MB/hour`.

| Quantity | Value |
|---|---|
| 20 GB ÷ 115.2 MB/h | **173.6 h ≈ 7.2 days** of continuous audio |
| Continuous burn | **84.2 GB/month** — 4.2× the whole quota |
| 12-month runway needs | **≤ 54.8 MB/day ≈ 28.6 min/day** of kept audio |
| 6-month runway needs | ≤ 109.6 MB/day ≈ 57 min/day |
| 3-month runway needs | ≤ 219 MB/day ≈ 114 min/day |
| Usable before the 2 GB knock floor | 18 GB |

Model assumptions, stated so they can be attacked:

- **Dedup gain = 0** for audio (unique streams). Per the brief.
- **Compression gain = 0** until Scene Sheet 2 measures one real restic/zstd
  ratio on a real kept wav. The table is therefore the pessimistic floor; any
  measured saving multiplies every runway figure.
- MEGA's "20 GB" is treated as 20 × 10⁹ bytes. If MEGA means GiB the numbers
  improve by 7.4% — immaterial to the conclusion.
- "Kept audio" means resolved kept-audio wavs plus event-sized recordings after
  transcript resolution — i.e. the COLD class only. HOT material (SQLite
  memory/inbox, journals, voice cache, unresolved kept audio) never leaves the
  laptop and does not enter this model, except nightly DB snapshots which are
  tiny and live in both places.

**Reading:** the 12-month bar is reachable, but only if the owner's real
resolved-audio volume stays under roughly half an hour a day. Whether it does
is a question only the owner's `du` can answer. **Scene Sheet 2 exists to answer
it, and the FLAC / second-target / tighter-hot-window decision fires from that
answer, not from this model.** The model's job is to tell us to ask.

### 5. Scene sheets issued

- `docs/phase-reports/001-owner-scene-sheet-1-mega-and-benchmark.md` — MEGA
  account + `rclone config` + the builder-written benchmark. EARS steps and
  TERMINAL steps in strictly separate sections, no physical action inside any
  paste-able block.
- `docs/phase-reports/002-owner-scene-sheet-2-aggregates.md` — aggregates only.
- `scripts/storage-benchmark.sh` — the instrument. Reads every credential from
  the owner's own environment, prints numbers and nothing else.

---

## DEFECTS FOUND

**D1 — the specified base branch does not exist.** `origin/arena/c2a7085d-elaria`
and commit `0c08cb5` are both absent. `origin` carries only `main` @ `ed20344`.
*Handling:* work on the session-pinned `arena/e7a1cca5-elaria`, open the separate
PR from it. No force-push, no history rewrite, no silent substitution of a
different mainline. Escalated to the design chat as OPEN QUESTION 1.

**D2 — the WP7 spec references mainline foundations that are not in this
checkout.** No `ladder.py` (so no chain #5 to extend), no append-only
schema-event journal carrying `session.close` / `transcription.landed` /
`transcription.deferred`, no `backup.*` / `storage.gauge` sensor events, and no
grace-then-purge trash discipline (`executor.trash()` moves + manifests but
never purges). All [HW-PROVEN] by grep. *Handling:* not worked around. WP7 is
built self-contained against documented seams, and the seams are named in the
code and in the phase reports so the mainline can land its side without a
merge conflict. Escalated as OPEN QUESTION 2.

**D3 — suite baseline differs from the brief's quoted figure** (1780 vs 1887
passed). Skips match exactly. Consistent with un-landed mainline work; no
regression introduced here. *Handling:* record the real number, re-measure every
commit. Escalated as OPEN QUESTION 3.

**D4 — `restic` and `rclone` are absent from the sandbox.** Not a defect in the
repo; a fact about the environment. *Consequence:* every WP7 test must run
against a fake `restic`/`rclone` seam (a scripted stub on `PATH`), because the
real binaries only exist on the owner's laptop. This shapes the test design and
is recorded so nobody later mistakes a green sandbox suite for a proven backup.

**D5 — the brief's WP7 text says "the existing append-only schema-event
journal"**, and also says the trigger ruling forbids touching the daemon. Both
cannot be satisfied until the mainline lands the journal. *Handling:* the
watcher is written to a **line contract**, not to a module: it tails a
configured path read-only, ignores every line that is not one of the three
event names, and tolerates the file not existing. That makes it a correct no-op
today and a working trigger the moment mainline starts writing lines.

---

## NEXT GATE

**GATE 0 (this turn, closed):** environment discovered, branch reconciled, T0
citations collected, scene sheets issued. No WP7 code.

**GATE 1 — owner scenes, before any WP7 machinery is built.** In order:

1. Owner completes Scene Sheet 1 (account + benchmark). Numbers come back.
2. Design chat rules **go / no-go on the MEGA backend and on the latency
   target**, from those numbers and from nothing else.
3. Owner completes Scene Sheet 2 (aggregates). Runway computed.
4. Design chat rules the **FLAC / second-target / tighter-hot-window** question
   if the runway is under ~12 months.

A failed benchmark sends **options with data** to the owner — different
provider, revised tier expectations — never a silent workaround.

Only after GATE 1 closes does WP7 machinery start: the manifest, the
reconcile-on-start, the crash-point tests, the tiering, the triggers, the cold
read path, the sensors, and ladder chain #5.

Then the WP7 gate itself (owner scenes, EARS/TERMINAL separated): benchmark
ruled go; a resolved kept-wav goes cold with manifest flip + grace-trash trim;
crash-point tests green; owner re-listens via `assist backup fetch` inside the
ruled latency budget; one live monthly drill (restore + check) passes; ladder
chain #5 including the integrity rung all REACHED; zero credentials in repo or
chat. After that gate: **STOP and report.**

---

## OPEN QUESTIONS

Rulings requested from the design chat. Each is multiple-choice; the owner
relays; the ruling binds and gets appended to `docs/storage-handoff.md`.

**Q1 — branch.** `origin/arena/c2a7085d-elaria` @ `0c08cb5` does not exist, and
the Arena harness pins this session to `arena/e7a1cca5-elaria`.
- (a) Work on `arena/e7a1cca5-elaria` and open the separate PR from it.
- (b) Create a local `arena/storage` branch anyway (untracked by the harness).
- (c) Stop and wait for the mainline branch to appear, then re-cut.

**Q2 — missing mainline foundations.** No `ladder.py`, no schema-event journal,
no `backup.*` sensors, no grace-then-purge trash.
- (a) Build WP7 self-contained against documented seams (own module, own
  journal-line reader, own config sections, own CLI subcommand, own ladder
  chain module that mainline can merge into `ladder.py` later). **Recommended.**
- (b) Build only the parts that need no mainline seam; defer the rest.
- (c) Stop until the mainline PR merges.

**Q3 — suite baseline.** 1780 passed here vs 1887 quoted for mainline.
- (a) Accept this checkout as the WP7 base; the brief's 1887 is mainline's
  number, not ours.
- (b) Treat the 107-test gap as a blocker and investigate before writing code.

**Q4 — runway.** 12 months needs ≤ ~29 min/day of kept audio (before any
measured compression gain).
- (a) Wait for Scene Sheet 2's real aggregates, then decide. **Recommended.**
- (b) Pre-build FLAC cold-only conversion now, gated behind config.
- (c) Pre-build second-target support now.

**Q5 — watcher wake mechanism.** The brief says "inotify wake on the data
dirs", but this repo's existing `watcher.py` is a stdlib polling snapshot-diff
by deliberate choice ("Phase 3 stays stdlib-only and fully testable headless"),
and inotify is not stdlib.
- (a) Poll the data dirs on the same seam as `watcher.py` (stdlib, headless-
  testable, no new dep). **Recommended — matches repo doctrine.**
- (b) Shell out to `inotifywait` (coreutils-adjacent, already on Fedora) for
  promptness, with the poll as fallback.
- (c) Poll only; drop the inotify requirement.

**Q6 — pack size.** Scene Sheet 1 measures default (16 MiB) vs 32 MiB.
- (a) Rule from the benchmark numbers.
- (b) Rule 64 MiB now on the strength of MEGA's own vendor guidance.
- (c) Rule 16 MiB (restic default, least temp space).

**Q7 — knock on the 2 GB floor.** The brief specifies one knock reading exactly
"Elaria wants to talk" with zero content. `initiative.raise_knock()` exists and
takes `topic`, `reason`, `kind`.
- (a) Reuse `raise_knock(kind=...)` with the exact literal reason string, so the
  knock lands in the existing pending queue and console surface.
- (b) Emit a storage-specific notification outside the knock system.

---

*Next phase report: `003-…`, only after GATE 1 returns numbers.*
