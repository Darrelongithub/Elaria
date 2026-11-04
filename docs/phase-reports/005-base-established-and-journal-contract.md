# Phase report 005 — base established, journal contract verified, branch ruling executed

**Date:** 2026-10-27
**Branch:** `arena/storage` @ `aca38c1`, cut from `f915d8e396d3fed0b3c77af7b21b2031c09ede5b`
**Session branch:** `arena/e7a1cca5-elaria` @ `b181712` — **untouched from the moment the
ruling landed**, per the ruling's instruction.

---

## 1. THE BRANCH RULING IS EXECUTED

Ruling (design chat, 2026-10-27), substance quoted:

> "BRANCH MECHANICS — RULED: OPTION (b), THE HYBRID. Substance beats bookkeeping.
> Execute: 1. Cut `arena/storage` at f915d8e (the verified live tip — PR #23's open
> head, carrying all of Stream G + G.7). Push it as a NEW branch.
> 2. `arena/e7a1cca5-elaria` is untouched from this moment: no force-push, no
> rewrite, no new commits. Your pre-flight docs stay as its historical record; the
> harness keeps attribution of what lives there. The WP7 machinery's lost
> session-attribution is ACCEPTED — the PR description is the durable provenance
> record.
> 3. Open the PR with base = `arena/c2a7085d-elaria` (stacked; retarget to main
> after #23 merges). In the PR description record: base SHA f915d8e, the session
> branch name, the harness-attribution caveat, and the four verified seams.
> 4. Record the base SHA + this ruling as a dated entry in docs/storage-handoff.md
> §5 (append-only).
> 5. CONTINGENCY (pinned): if the push of `arena/storage` is TECHNICALLY blocked,
> STOP and report the exact error. No stale-base fallback, no force-push, no
> improvisation. The invariant stands: WP7 is built on the live mainline tip or it
> is not built today."

**Note on the ruling's option letter.** The ruling says "OPTION (b), THE HYBRID",
but the hybrid was option **(c)** in the three options I offered — option (b) was
"follow the harness, build on ed20344". The *substance* of the ruling is
unambiguous and matches (c) exactly (cut `arena/storage` at f915d8e, push as new
branch, session branch untouched, PR base = `arena/c2a7085d-elaria`). The letter
is a relay slip; the substance is what I executed, and I record the discrepancy
rather than silently pick one reading.

**Executed:**

| Step | Status |
|---|---|
| Cut `arena/storage` at `f915d8e` | DONE |
| Session branch untouched (no force-push, no rewrite, no new commits) | DONE — still at `b181712` |
| Pre-flight commits carried across | DONE — cherry-picked clean, no conflicts |
| Base SHA recorded | DONE — `f915d8e396d3fed0b3c77af7b21b2031c09ede5b` |
| Ruling recorded in `docs/storage-handoff.md` | DONE — dated append-only entry |
| PR with base `arena/c2a7085d-elaria` | PENDING this report |

### 1.1 The sandbox `.git` reset — handled, and it is now a known recurring hazard

Between turn 1 and turn 2 the sandbox reset `.git` to a single-commit state at
`ed20344`. My turn-1 commit survived only on origin. The turn-2 work had already
been committed locally on top of the stale `ed20344`, which would have pushed as a
**non-fast-forward** — i.e. a silent rewrite of shared history on the session
branch. Caught before push; reconciled by re-fetching `2320e1d` from origin and
rebasing onto it, so the session branch history stayed
`ed20344 → 2320e1d → b181712` and the push was a clean fast-forward.

**Standing rule adopted:** before every commit on this branch, verify
`git merge-base --is-ancestor <origin tip> HEAD` is true, or the push will rewrite
shared history. Never `--force`.

---

## 2. BASELINE ON THE REAL BASE — and one pre-existing defect that is NOT mine

The ruling cited a "1,901-test suite" on the mainline. Measured on `f915d8e`, in
this sandbox:

| Measurement | Value |
|---|---|
| `pytest -q` | **1913 passed, 6 skipped, 1 error** |
| `ruff check .` | **All checks passed** |

### 2.1 Two environment corrections I had to make before those numbers meant anything

**(a) `.venv` was wiped by the same reset.** Recreated with `pytest` + `ruff`.

**(b) 21 tests failed until the project's OWN declared dependencies were
installed.** Every one of them failed with:

```
assistant.live_client.LiveUnavailable: live transcription needs the Gemini SDK:
uv sync --extra live
```

`pyproject.toml` declares `google-genai>=2.0.0` and `httpx>=0.27` as core
dependencies. Installing them took `tests/test_stream_g_primary.py` from
6 failed / 8 passed to **14 passed**. This is a sandbox environment artefact, not
a base defect, and it is recorded because the same trap would silently produce a
"21 failing tests on the base" false alarm for anyone repeating this.

### 2.2 The 1 error — pre-existing, on the base, and deliberately NOT fixed

```
tests/test_gate_fix_round.py::test_hold_to_talk_ptt_start_stop_still_works
ERROR tests/conftest.py:108: AttributeError
  'async_generator_athrow' object has no attribute '__qualname__'
```

`tests/conftest.py` teardown does:

```python
clients = [task for task in asyncio.all_tasks()
           if task is not current and not task.done()
           and task.get_coro().__qualname__ == "serve.<locals>._client"]
```

On CPython **3.11** (this sandbox), `task.get_coro()` for an async-generator
`athrow` frame does not expose `__qualname__`. The repo targets "Fedora 44 owner:
CPython 3.14; keep code/tests 3.11-compatible too" — so this is a **latent
3.11 incompatibility in the mainline's own test harness**, present on the base
before WP7 touched anything.

**Deliberately not fixed here.** `tests/conftest.py` is the mainline's active
theatre and the mainline builder works it concurrently; a fix inside my stacked
PR would collide with theirs for zero WP7 benefit. Reported instead, as a defect
the mainline owns. It does not block WP7: it is a teardown error in one fixture,
1913 tests pass, and it is deterministic on 3.11.

**Baseline to hold:** **1913 passed / 6 skipped / 1 error (pre-existing, 3.11
only), ruff clean.** WP7 must not move any of those numbers.

---

## 3. JOURNAL CONTRACT — VERIFIED AGAINST REAL MACHINERY, NOT GUESSED

The ruling's bonus instruction: *"verify your watcher fixtures against the on-base
journal_log.py output shapes before writing the watcher, and report any drift from
the contract verbatim."*

### 3.1 The mechanism (already confirmed from code, restated for the record)

`src/assistant/journal_log.py` writes space-separated plain-text lines to
**stdout**; the unit's `StandardOutput=journal` captures them into journald.
There is **no append-only file** to `tail`. journald itself is the append-only
record and `journalctl` is a pure read — so the trigger ruling's "the backup hook
must NOT touch the daemon" holds literally: the watcher only ever reads.

### 3.2 Actual emitted shapes, captured verbatim from the running module

```
1) session.close         : '2026-10-27T06:15:34+00:00 info session.close ptt-abc123 0.42 closed'
2) transcription.landed  : '2026-10-27T06:15:34+00:00 info transcription.landed ptt-abc123 - landed'
3) transcription.deferred: '2026-10-27T06:15:34+00:00 warn transcription.deferred ptt-abc123 - deferred quota'
4) transcription.rejected: '2026-10-27T06:15:34+00:00 warn transcription.rejected ptt-abc123 - rejected /path/rec.wav'
5) quota.counter (all-empty optionals): '2026-10-27T06:15:34+00:00 info quota.counter - - -'
```

Field layout: `ts level event session_id peak verdict detail…`

### 3.3 DRIFT #1 — the field count is VARIABLE, and a naive `split(" ")` breaks

| Line | Parts | Why |
|---|---|---|
| `session.close` (peak present, no detail) | 6 | detail absent |
| `transcription.landed` (no peak, no detail) | 6 | both optional absent |
| `transcription.deferred` with detail | 8 | detail is two words |
| `quota.counter` (everything empty) | 7 | three `-` placeholders |

`detail` is documented as *"the rest of the line, plain words"* — free text that
can contain spaces, and on failure paths can contain a **filesystem path**.

**Binding consequence for the watcher:** parse with `line.split(" ", 6)` (maxsplit
6) so the first six fields are positional and everything after is `detail`. Never
`len(parts) == N`. Never assume `detail` exists.

### 3.4 DRIFT #2 — the WP7-relevant lines carry the kept-audio path in `detail`

Verified at the actual call sites, not inferred:

`transcribe.py:1390` (`transcription.landed`):
```
detail = f"model_version={model}; {len(shown)} chars committed"
         + (f"; audio kept at {audio_path}" if audio_path else "")
```

`transcribe.py:415` (`transcription.deferred`):
```
detail = f"low-confidence transcript queued for cloud redo (job #{job_id}); "
         f"audio kept at {result.audio_path}"
```

`daemon.py:2317` (`session.close`):
```
detail = f"model_version={model_of_record}; {mode} session closed — "
         f"text_chars={len(...)} ..."
```

So the WP7 brief's claim — *"session.close / transcription.landed /
transcription.deferred lines carry session ids, kept-audio paths and resolution
state"* — is **verified true**, with the exact field each fact lands in:

| Fact the brief needs | Field | Example |
|---|---|---|
| session id | field 4 | `ptt-abc123` |
| resolution state | field 6 (`verdict`) | `landed` / `deferred` / `rejected` / `closed` / `silence` |
| kept-audio path | inside `detail` | `audio kept at /path/to/rec.wav` |

**PRIVACY CONSEQUENCE, recorded because it is load-bearing.** The journal lines
carry **local filesystem paths** of real recordings. Therefore:

- The watcher extracts the path to address the artifact in the manifest, and must
  **never** write it to a log line, a sensor event, a PR, a chat message, or the
  manifest's human-readable fields. The manifest stores the path (it must — it is
  the record of intent) but the manifest lives only on the laptop, 0600, outside
  the repo.
- `journalctl` output must never be pasted anywhere. Scene Sheet 1 and Scene
  Sheet 2 both already say "numbers only, never content"; this is the concrete
  reason why, and it is now written down as a rule rather than left as good
  intentions.
- The `detail` field can also carry `text_chars=N` and `model_version=…` — counts
  and identifiers, not content. Those are safe to surface as aggregates.

### 3.5 Event names — full verified inventory relevant to WP7

Present on the base and usable by the watcher:

| Event | Emitted from | WP7 use |
|---|---|---|
| `session.close` | `daemon.py:2317` | session finished; peak + verdict |
| `transcription.landed` | `transcribe.py:1390` | transcript committed, audio kept → **cold candidate** |
| `transcription.deferred` | `transcribe.py:415`, `:425`, `:1378` | transcript queued; audio kept → **HOT, do not trim** |
| `transcription.rejected` | — | audio kept, no transcript → **HOT, do not trim** |
| `watchdog.close` | — | abnormal close; a safety signal for the ladder |
| `quota.counter` | — | Gemini spend; not WP7's concern |
| `ws.histogram`, `audio.sent`, `audio.first_byte`, `latency.table`, `final.*` | `transcribe.py`, `daemon.py` | stream-F/G sensors; not WP7's concern |

The design chat's contract list (`stop.requested`, `ack.played`, `final.*`,
`ws.histogram`, `audio.sent`, `latency.table`) is **fully present** — no drift.

---

## 4. CAPACITY RULING RECORDED (levers (d) and the sizing target)

Both are now recorded verbatim in `docs/storage-handoff.md` as dated entries, and
report 004 carries the sizing-target amendment. Headlines:

**Lever (d), corrected verbatim.** The fragment "(d) event/flight recordin…" was
lever **(c)'s guard clause**, mis-fused onto (d) in the relay. The corrected menu
is four levers: (a) FLAC cold-only, (b) second target, (c) retention-class prune
*with the guard "event/flight recordings never pruned without explicit owner
order"*, (d) **do nothing** — the 2 GB gauge knock is the designed pressure gauge
and the owner picks among (a)/(b)/(c) when it fires. My three reconstruction
candidates were rejected as substitutes, and my candidate (a) — excluding
event/flight recordings from the cold class — was named a **new, never-ruled
lever** that contradicts audio-never-lost. Recorded as such.

**Sizing target: MONTHLY 8-hour events** (11.06 GB/yr raw), because monthly is the
highest frequency that survives the zero-compression floor (21.7 months) — nothing
unverified is load-bearing. Combined-profile allowance, per the ruling:
`18 GB usable − 11.06 GB events ≈ 6.9 GB/yr ≈ ~10 kept-min/day at the floor,
~20 at 2×`. I verified the ruling's arithmetic against my own constants: 6.9 GB/yr
÷ 365 = 18.9 MB/day; ÷ 1.92 MB/kept-min = **9.8 ≈ 10 kept-min/day** at the floor,
and **19.6 ≈ 20** at 2×. **No drift.** Relief path if Scene Sheet 2 measures above
the allowance: lever (c) only.

---

## DEFECTS FOUND

**D7 — pre-existing, on the base, owned by the mainline.** `tests/conftest.py:108`
teardown raises `AttributeError: 'async_generator_athrow' object has no attribute
'__qualname__'` on CPython 3.11. Present on `f915d8e` before any WP7 work.
Deterministic, teardown-only, does not block WP7. **Not fixed here** — mainline's
active theatre, and a fix in a stacked PR would collide. Reported for the
mainline to own.

**D8 — process, now mitigated.** The sandbox `.git` reset dropped a commit locally
while origin retained it, which nearly produced a non-fast-forward push over the
session branch. Caught before push. Standing rule adopted: verify ancestry before
every push; never `--force`.

**D9 — journal contract drift (design-relevant, not a bug).** The schema line has a
variable field count and a free-text `detail` tail that can contain filesystem
paths. Any parser assuming fixed columns, or any log line that echoes `detail`,
would leak a recording path. Written into the watcher's binding contract in §3.3
and §3.4.

---

## NEXT GATE

**GATE 1c — push `arena/storage` and open the stacked PR.** Base
`arena/c2a7085d-elaria`, PR description recording: base SHA `f915d8e`, session
branch `arena/e7a1cca5-elaria`, the harness-attribution caveat, and the four
verified seams. The ruling's pinned contingency applies: if the push is
technically blocked, STOP and report the exact error — no stale-base fallback, no
force-push, no improvisation.

**GATE 1d — build the WP7 machinery.** Now unblocked: the base carries
`ladder.py`, `journal_log.py`, the schema events and the trash manifest, so chain
#5, the watcher and the grace-then-purge policy all have real seams to attach to.

**GATE 1 — owner scenes (unchanged, still the real gate).** Scene Sheet 1 and
Scene Sheet 2 stand as issued. The numbers still come back before the machinery is
trusted.

---

## OPEN QUESTIONS

**Q12 — does the mainline want D7 fixed by me, or by them?** It is a one-line
defensive fix (`getattr(coro, "__qualname__", "")`) in `tests/conftest.py`.
Options: (a) mainline fixes it, WP7 stays out of `conftest.py` entirely
(recommended — least collision); (b) I fix it in the stacked PR and flag the
expected conflict; (c) leave it, since it is 3.11-only and the owner runs 3.14.

**Q13 — `transcribe.py:1378` is a third `transcription.deferred` site I have not
read.** Sites at `:415`, `:425` and `:1378`. I read the first two. The third may
put a different shape in `detail`. Before the watcher's fixtures are finalised I
will read it and report any drift; flagging now so the record shows it was known
rather than missed.
