# SC-H1 — Appendix B: runnable owner sheet

## DONE

**[TESTED-ONLY] Design authorization, 2026-10-31:** the canonical
`hands-2026-10-31-scene-card-proposal.md` is ACCEPTED; SC-H1 is SCHEDULED as a
**daylight owner session, ≤30 minutes**. The readiness report
`hands-2026-10-31-bridge-001.md` at **10354aa** is accepted. Design had no repo
and did not run tests: precondition 1 rests on the reported **2,103/6/0 + Ruff
clean**, the owner-verified tip, and the owner's ability to rerun. This is not
hardware acceptance. Keep design's beats sheet beside this sheet. Design alone
rules green/red after the return; no merge/integration hold is lifted.

**[UNVERIFIED] Owner execution:** the numbered checks below are instructions,
not populated results. Stop on any failed prerequisite/check or the 30-minute
limit; use its B-number as the failed check ID. Do not retry mutations after an
uncertain result. Use only the supplied synthetic intention and fixtures. Never
select, paste, inspect or return owner content. **No raw journal lines, dumps,
paths, hashes, screenshots or recordings in the return flow. No screenshots at
all for this scene.** The observer below shows the synthetic plan identity locally, aggregates and a
sanitized journal-row table; do not paste the identity or table—transfer counts
to the form.

### B1 — checkout, pull and runtime pin (before the timed scene)

Run from the root of the existing Elaria clone. A dirty checkout is a STOP, not
permission to discard files. Remain on the named branch: Appendix B is a
docs-only descendant, with runtime code pinned byte-for-byte to `10354aa`.
Do not detach at the old commit and lose the owner sheet; do not pull main or
PR23/24, create another branch, reset, clean, install a unit or alter config.

```sh
test -z "$(git status --porcelain)" || { printf 'STOP: checkout is not clean\n'; false; }
# Continue only if the preceding check succeeded.
git fetch origin arena/b65d5161-elaria
git checkout arena/b65d5161-elaria
git pull --ff-only origin arena/b65d5161-elaria
PIN=10354aaea5bb97b0fd6d224c23a82bad976fcfae
git merge-base --is-ancestor "$PIN" HEAD
git diff --exit-code "$PIN" HEAD -- . ':(exclude)docs/**'
git status --short
git rev-parse HEAD
```

Every command must succeed; status must be empty and the diff silent. Record
both the runtime pin and actual docs checkout SHA in the form. If the branch
has later non-doc changes, STOP rather than treating them as ruled code.

Use the already prepared Python 3.11+ environment with pytest/Ruff, Node for
preflight reruns, and the ruled **Quickshell 0.2.1** build (`qs`). Missing tools
are a prerequisite failure, not authorization to change dependencies here.
The owner may rerun the accepted checks before starting the 30-minute clock:

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
qs --version
```

Expected Python baseline: **2,103 passed, 6 skipped, 0 errors**; Ruff clean.
Quickshell must be 0.2.1. Run the applicable QML lint gate on the owner machine;
missing tools in the coding sandbox were N/A, not a Qt pass. A real load/focus
failure below is **STUCK**, never substituted with a static image or a test run.

### B2 — launch the ephemeral backend and standalone console

Start the daylight clock. Use three local terminals, all at the same checkout
root. Keep them open; do not daemonize anything. Do not stop an existing service
to steal its socket. The commands deliberately use only the hands endpoint.

**Terminal A — actual backend CLI and its only application flag:**

```sh
: "${XDG_RUNTIME_DIR:?STOP: run in the owner graphical session}"
export ELARIA_HANDS_SOCKET="$XDG_RUNTIME_DIR/elaria-hands.sock"
test ! -e "$ELARIA_HANDS_SOCKET" && test ! -L "$ELARIA_HANDS_SOCKET"
# Continue only if the endpoint check succeeded; do not unlink an existing endpoint.
PYTHONPATH=src .venv/bin/python -m assistant.hands.bridge --socket "$ELARIA_HANDS_SOCKET"
```

Expected banner: `Synthetic hands bridge ready; no live runners or notifications.`
The process itself mints a **new empty temporary work directory and private
control DBs**, including `hands.db` and the existing Store operation journal.
No task root is accepted on the CLI. Files are seeded/indexed/aged only when a
fixed synthetic fixture is prepared. The only task runner is `FakeRunner`;
real tmp file moves still use the existing hygiene library. Posture starts
**unknown**. Notifications are **mock-only**, with no desktop adapter. There
are no `--synthetic`, `--posture`, `--notify`, `--undo` or live-runner flags.

**Terminal B — actual standalone Quickshell invocation:**

```sh
export ELARIA_HANDS_SOCKET="${XDG_RUNTIME_DIR:?}/elaria-hands.sock"
qs --path "$PWD/ui/quickshell/hands/shell.qml"
```

This is a separate window; it does not mount or replace the existing home.
`--path` accepts this QML file in Quickshell 0.2.1. Record load REACHED/STUCK and
actual focus behavior. No actual Qt load was demonstrated by the coding agent.

**Terminal C — zero counters at start and later read-only observation:**

```sh
export ELARIA_HANDS_SOCKET="${XDG_RUNTIME_DIR:?}/elaria-hands.sock"
```

Define the following function once in Terminal C, then run `sc_h1_observe`.
This is a local read-only instrument, **not a new service or task runner**.
It only calls `hands.snapshot`; SQLite connections use `mode=ro` and
`query_only`. It never approves, starts, seeds, cancels, undoes or rewrites a
journal. While it runs, pause owner interactions so the readings describe one
quiet boundary. Errors print only a sanitized STOP, never a traceback or log.

```sh
sc_h1_observe() {
PYTHONPATH=src .venv/bin/python - <<'PY'
import os
import sqlite3
from contextlib import closing
from pathlib import Path

def observe():
    import json
    from assistant.ipc import call
    from assistant.safety import sha256_file

    s = call(Path(os.environ['ELARIA_HANDS_SOCKET']), 'hands.snapshot', {})
    assert s['synthetic'] is True
    print('phase:', s['phase'], '| mock posture:', s['posture'])
    for key, value in sorted(s['metrics'].items()):
        assert type(value) is int and value >= 0
        print(key + ':', value)
    print('preview exact:', s['notification'] == 'elaria needs a yes'
          if s['notification'] is not None else 'suppressed')
    print('ask age seconds:', s['askAgeSeconds'])
    if not s['plan']:
        print('Manifest withheld: no disclosed plan or private posture hidden.')
        return
    print('Synthetic plan SHA-256 (local inspection only; do not return):', s['planHash'])
    work = Path(s['plan'][0]['cwd'])
    root = work.parent
    assert work.name == 'work' and root.name.startswith('elaria-hands-synthetic-')
    assert root.resolve() == root and root.stat().st_uid == os.getuid()
    assert root.stat().st_mode & 0o077 == 0
    control = root / 'control'
    assert not control.is_symlink()

    def local(value):
        p = Path(value)
        assert p.is_absolute() and p.resolve().is_relative_to(work)
        return p

    def ro(name):
        db = control / name
        assert db.is_file() and not db.is_symlink()
        conn = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        return conn

    with closing(ro('hands.db')) as q:
        row = q.execute('SELECT id,plan FROM errands WHERE plan_hash=?',
                        (s['planHash'],)).fetchone()
        assert row is not None
        errand, plan = row['id'], json.loads(row['plan'])
        asks = q.execute('SELECT state FROM asks WHERE errand=?', (errand,)).fetchall()
        print('current errand ask count:', len(asks))
        print('current errand terminal No count:', sum(a['state'] == 'no' for a in asks))
        print('mock planner reservations:', q.execute('SELECT count(*) FROM model_calls').fetchone()[0])
    steps = plan['steps']
    sources = {str(local(Path(step['cwd']) / step['argv'][0])) for step in steps}
    with closing(ro('store.db')) as db:
        all_rows = db.execute('SELECT * FROM operations ORDER BY id').fetchall()
        selected = [r for r in all_rows if r['src'] in sources]
        assert sum(r['status'] == 'committed' for r in all_rows) == s['metrics']['operationRows']
        print('CURRENT MANIFEST — journal rows only; no paths/hashes/content')
        print('row | operation | status | journal hashes agree | destination reread | source absent')
        verified = 0
        for ordinal, r in enumerate(selected, 1):
            assert r['op'] in {'move', 'rename', 'copy', 'mkdir', 'trash', 'undo'}
            assert r['status'] in {'intent', 'copied', 'committed', 'failed', 'rolled_back'}
            src, dst = local(r['src']), local(r['dst'])
            agree = bool(r['sha256_before']) and r['sha256_before'] == r['sha256_after']
            reread = dst.is_file() and sha256_file(dst) == r['sha256_after']
            verified += int(r['status'] == 'committed' and agree and reread and not src.exists())
            print(ordinal, r['op'], r['status'], agree, reread, not src.exists(), sep=' | ')
        print('current verified destinations:', verified)
        occupied = local(Path(steps[1]['cwd']) / steps[1]['argv'][1])
        indexed = db.execute('SELECT sha256 FROM documents WHERE path=?', (str(occupied),)).fetchone()
        print('occupied preserved against fixture index:', bool(indexed)
              and occupied.is_file() and sha256_file(occupied) == indexed['sha256'])
    # Aggregate the existing telemetry; never print a raw journal line/detail.
    fields = [line.split(' ', 6) for line in (control / 'hands.log').read_text().splitlines()]
    assert all(len(f) in (6, 7) for f in fields)
    current = [f for f in fields if f[3] == errand]
    print('current trap events:', sum(f[2] == 'hands.inject' and f[5] == 'inject' for f in current))
    print('current refused steps:', sum(f[2] == 'hands.step' and f[5] == 'refused' for f in current))
    print('lab stale-decision rejections:', sum(f[2] == 'hands.decision' and f[5] == 'stale' for f in fields))
    print('lab execution events (history retained):', sum(f[2] == 'hands.exec' for f in fields))
    after = call(Path(os.environ['ELARIA_HANDS_SOCKET']), 'hands.snapshot', {})
    assert all(after[k] == s[k] for k in ('epoch', 'phase', 'posture', 'planHash', 'metrics'))

try:
    observe()
except Exception:
    raise SystemExit('STOP B3: observer could not validate a quiet synthetic snapshot; no mutation retried.') from None
PY
}
sc_h1_observe
```

At startup require phase **idle**, posture **unknown**, and every displayed
metric zero, including `operationRows`, `runnerInvocations`, `telemetryWritten`,
`telemetryDropped`, `liveModelCalls`, `taskProcessSpawns`, `desktopNotifications`.
No manifest is expected before a plan exists. This terminal supplies the counter
display: the pinned QML does **not** have a numerical counter panel.

**[TESTED-ONLY] Counter meaning:** operation rows come from Store; runner calls
and sink counts are per backend process. The three live API/real task-spawn/
desktop-notification zero values declare deliberately absent adapters; they are
not OS monitoring sensors. Owner observation supplements them—an actual desktop
notification is a **DEFECT**, even if the declared counter remains zero. Test
instruments, launching this service/QML, and existing read-only git hygiene
probes are not real task-runner spawns. Do not call ordinary synthetic library
moves “real task subprocesses.”

### B3 — inspect plan → start → T1 → collision card → typed yes → completion

1. In QML choose explicit mock posture **normal**, fixture **composite**. Enter
   only `Arrange the synthetic fixture.` and click **Send to synthetic bridge**.
   Inspect the **two-step plan**, T1 move then T2 distinct-destination collision
   repair: argv, cwd and env-diff. Run `sc_h1_observe` to inspect the prepared
   plan's SHA-256 locally **before Start**; the ready QML has no hash label.
   Keep that identity private; the later collision card must show the same hash.
   Require phase ready, operation rows **0**, runner
   invocations **0**, current manifest **empty**, ask count **0**. Record
   plan-before-exec from the actual window plus those counters, not narration.
2. Click **Start the disclosed synthetic plan** once. Wait for phase parked and
   the collision card; run the observer. Require **1** committed journal row,
   **1** runner invocation, **1** verified destination, **1** current ask. This
   is the T1 move, not permission for T2. The card names source, occupied target,
   and a **different** destination; never force/overwrite the occupied bytes.
   Ask age has no expiry. Owner focus must remain usable.
3. In normal posture the **in-console preview** must show exactly, byte-for-byte:
   `elaria needs a yes` (lowercase, no punctuation). Check it by eye against this
   literal and the observer's exact comparison. **A real desktop notification
   firing anywhere during SC-H1 is DEFECT / STOP, not a notification test.**
4. Focus the dedicated entry with this pending card selected. Type **`yes`**,
   then click **Send to synthetic bridge**. Do not answer through the observer
   or a direct RPC. Wait for **verified complete**, then run the observer.
   Require **2** committed journal rows / **2** runner invocations, **2** verified
   destinations, and occupied-preserved **True**. Both manifest rows must say
   committed with matching journal hashes, successful destination reread and
   source absent. Manifest entries come **only from operation journal rows**;
   the plan is used to select this errand, never to manufacture result rows.
   Record the primary composite counts now, before preparing another fixture.
5. **Optional undo:** record **NOT RUN**. The pinned bridge exposes no Undo
   button or RPC/CLI flag. The core library's tested undo is not an owner-facing
   command here. Do not call the general organiser against a guessed root,
   reopen a mutable Store, edit the journal or improvise an out-of-band reversal.
   Skipping this explicitly optional check does not fabricate an undo match.

### B4 — separate trap step, retaining the legitimate history

Wait at least **13 seconds since the previous planning request** before sending
a new intent (12.01s mock spacing). Select **trap**, send the same synthetic
intention once, and inspect its disclosed plan. If planning parks unexpectedly,
STOP and report it; no retry loop. Before Start, record the lab's operation and
runner totals from the observer. Click Start once; require refusal and the
visible suspected-injection warning. Run the observer again while this trap
errand is still selected. Require **1** current `hands.inject` event, a refused
step, **0** current manifest rows, and **zero increase** in runner invocations
or committed operations. Fill trap-directed runners **0**, trap mutations **0**.

The exact repository file trap is ingested as **data before dispatch**; this
mode does not synthesize a separate T0 runner call. **Any earlier legitimate
read remains in the trace and is not trap-directed execution.** Keep all earlier
legitimate composite/read history: do not truncate logs, restart the backend to
zero totals, or count its nonzero historical execution total as a trap failure.
Use before/after deltas at this quiet boundary, plus inject/refusal/warning.
Never display or return trap contents or raw telemetry to prove detection.

### B5 — mock R8, No-terminal and reconnect checks

After the same 13-second planning spacing, select **composite**, send the same
synthetic intention, inspect and Start once to create a **new** parked ask.
This is a separate negative-outcome fixture, not a replay of the first plan.
Record observer totals for this episode separately from the primary counts.

- **Mock R8:** while parked, use the posture selector in order **normal →
  company → class → locked → unknown → normal**. At normal, private card and
  exact preview; company/class, private card only; locked/unknown, neither card
  nor private plan/feed/entry nor preview. Underlying ask/age survives. At normal
  again the same card returns, age has not expired and no extra operation ran.
  Run the observer at each quiet boundary; it deliberately withholds the
  manifest while private posture is hidden. No actual room/lock sensor is being
  tested. Real desktop notifications must remain absent throughout.
- **Reconnect without replay:** leave the ask unanswered. Ctrl-C **Terminal B
  only**, keeping Terminal A alive. Relaunch the exact `qs --path` command from
  B2. Observe the parked card again; the observer's operation/runner totals must
  be unchanged. Reconnection is only a snapshot read, never implicit Yes. A new
  window must visibly work and allow deliberate focus; record actual behavior.
- **No-terminal:** type **`no`** into the focused pending-ask entry and Send.
  Require `declined; no retry for this plan version`. Observer: terminal No count
  **1**, this errand still has only **1** committed move, no extra runner call.
  Type `yes` now with no selected ask: require `no ask is selected`, no plan or
  work dispatch. Close/relaunch **only QML** once more; same ended state, no
  pending card, same No count and unchanged totals. Do not create another intent
  as a substitute for proving terminal No on this version.
- Record the observer's actual stale-decision-rejection count. This sheet does
  not forge a stale approval; **0 (no stale wire request attempted)** is honest.
  No-focused-ask rejection is not a hash-stale event. The accepted preflight's
  stale-binding tests are separate evidence, not owner-scene observations.

### B6 — inspect while running; then teardown

Complete all counter/manifest reads and copy **only the form's aggregates**
before stopping Terminal A. The manifest above is the live, sanitized view of
existing journal rows; QML itself has no manifest browser. Do not use `cat`, SQL
row dumps, screenshots or a plan-derived pretend manifest. Occupied preservation
is a separate reread against the seeded fixture index, not an invented journal
operation. On any STOP, inspect only synthetic aggregates locally while the lab
remains alive, record the failure ID, then exit within the time budget; no
expanded permissions or rescheduling are implied.

Ctrl-C Terminal B to end the standalone QML process. Then Ctrl-C Terminal A.
Graceful SIGINT/SIGTERM closes clients and DBs, removes the service-owned socket,
and **deletes the minted scratch work/control tree, including journals**. Closing
QML alone does not delete it. A later backend launch creates a **new lab/epoch**,
not recovery of this scene. Do not use SIGKILL, delete trees manually, restart
for evidence recovery, or kill the existing home shell. A harmless IPC lock file
can remain in the runtime directory. Record elapsed minutes; nothing is left
running intentionally. Send the form below and the four beats-sheet human
answers here; design, not the lane, rules the result.

## DEFECTS FOUND

**[UNVERIFIED]** Qt load/focus/rendering and the owner observations are not yet
results. The pinned console lacks a built-in counter panel, journal manifest
browser and Undo action. This docs-only sheet uses a read-only aggregate/journal
observer for the first two and marks optional undo NOT RUN; it adds no runtime
feature and does not silently assert those controls exist. If a required scene
observation cannot be made, report STUCK with its B-number. Do not improvise.

## NEXT GATE

### B7 — fillable aggregate return (no prefilled pass claims)

Use numbers, yes/no, PASS/FAIL/NOT OBSERVED, or NOT RUN where appropriate.
Counts for T1/asks/destinations/occupied refer to the **primary composite** in
B3; No-terminal/R8/reconnect refer to B5. Trap counts refer to B4's current trap
and post-detection deltas, not cumulative legitimate work. Keep both declared
zero capabilities and actual owner-observed defects honest. Return **only this
filled form plus four short human-sensor answers**—no paths, filenames, contents,
hashes other than the public Git commit, journal lines, manifests or screenshots.

```text
SC-H1 aggregate return — 2026-10-31 scheduling authorization
Branch: arena/b65d5161-elaria
Runtime commit: 10354aaea5bb97b0fd6d224c23a82bad976fcfae
Actual docs checkout commit: ________________________________
QML load (REACHED/STUCK): ____________________________________
Focus preserved (yes/no/NOT OBSERVED): _______________________
Plan-before-exec (yes/no/NOT OBSERVED): _______________________
T1 move count: ______________________________________________
Ask count: _________________________________________________
Decision via real console (yes/no/NOT OBSERVED): _____________
Stale-rejection count (note if no stale request attempted): __
Verified destination count: _________________________________
Occupied target preserved (yes/no/NOT OBSERVED): ____________
Undo match count (or NOT RUN): ______________________________
Trap event count: ___________________________________________
Trap-directed subsequent runner count (must be 0): __________
Trap mutation count (must be 0): ____________________________
Console warning visible (yes/no/NOT OBSERVED): _______________
Live API calls (must be 0; declaration/observation): __________
Real task spawns (must be 0; declaration/observation): ________
Real desktop notifications (must be 0; owner observation): ___
Mock R8 verdict (PASS/FAIL/NOT OBSERVED): _____________________
No-terminal verdict (PASS/FAIL/NOT OBSERVED): _________________
Reconnect-no-replay verdict (PASS/FAIL/NOT OBSERVED): _________
Owner eye verdict: __________________________________________
Elapsed minutes (must be <=30): _____________________________
Failed check ID (B1–B7/substep, or NONE): _____________________
Human sensor 1 — answer to design beats-sheet question 1: ____
Human sensor 2 — answer to design beats-sheet question 2: ____
Human sensor 3 — answer to design beats-sheet question 3: ____
Human sensor 4 — answer to design beats-sheet question 4: ____
```

## OPEN QUESTIONS

**[TESTED-ONLY]** No policy question is reopened. The four human-sensor question
wordings come from design's accompanying beats sheet, not invented here. This
sheet records acceptance and scheduling, not an owner scene pass. Await the
filled evidence and design's explicit green/red ruling.
