# Phase report 009 — GATE 1e re-dated to 462fa98; drift check clean; A.1 FIXED, baseline corrected

**Date:** 2026-10-27
**Branch:** `arena/storage` @ `751c68c`
**Trigger:** cross-lane notice + design-chat rulings, both naming `462fa98` as the true
mainline tip and both invoking my own 007 §2 protocol: *"do not trust the relay."*

---

## DONE

### 1. THE `eae1d01..462fa98` DRIFT CHECK — RUN, NOT RELAYED

The tip note ordered a re-run of `diff eae1d01..462fa98` before fixtures and a re-dating
of the GATE 1e window. Done, in full, against the real commit:

| Check | Result |
|---|---|
| `git diff eae1d01..462fa98 -- src/assistant/journal_log.py` | **EMPTY — byte-identical** |
| `"audio kept at"` sites | **4 sites, character-identical.** Only line numbers shifted (`daemon.py` 2404→2405; `transcribe.py` 418 / 1438 / 1451 unchanged) |
| `session.close` emitted | **YES** (`daemon.py`) |
| `transcription.landed` emitted | **YES** (`transcribe.py`) |
| `transcription.deferred` emitted | **YES** (`transcribe.py`) |
| Full §2 verification table against 462fa98's actual module | **ALL 12 CHECKS PASS** |
| Verdict collision (`fallback.outcome` vs `transcription.landed`) | **STILL PRESENT** → dispatch rule still required |

The verification was run by extracting `462fa98`'s real `journal_log.py` and executing
the six canonical reference shapes against it — not by reading a diff and inferring.
`split(" ", 6)` → 6 parts (no detail) or 7 (detail present), `parts[6]` byte-intact on
the real long detail string, dash placeholders on `session_id`/`peak`/`verdict` only,
32-hex `session_id` accepted.

**What `462fa98` actually changed** (three files, `+27/-9`): `scripts/live_repro.py`
(default `--wav` now resolves the daemon's XDG audio dir first, then a repo-local
`audio/` copy, and the error names both candidates), `HANDOFF.md` §4 (a manifest entry
named the wav `…-77cc4efb.wav`; corrected to the session-id-prefix name
`…-77cc4e.wav`, UNVERIFIED marker dropped), and `daemon._mic_release_probe` (capture
target read at spawn time and passed in). **None of it touches the journal.**

**No schema drift. No phrasing drift. The canonical contract in 007 §2 stands unchanged
at `462fa98`.**

### 2. GATE 1e WINDOW RE-DATED

| | |
|---|---|
| Canonical baseline (contract designated) | `f915d8e396d3fed0b3c77af7b21b2031c09ede5b` |
| Re-verified at (report 008) | `eae1d01b402dc2cef9d788956c0851ea1d38c14e` |
| **Re-verified at (this report) — current mainline tip** | **`462fa98fba34e3939ad0ba896df95bf69b7977cf`** |

The contract is unchanged across all three. The window's closing event (fixture
authorship) is dated against **the tip at closing**, per the ruling — and this report
establishes that the tip as of now is `462fa98`, drift-free.

### 3. A.1 IS FIXED — MY RECORDED BASELINE WAS STALE, CORRECTED HERE

`462fa98` carries the defensive fix I offered in report 005. At `tests/conftest.py`:

```python
and getattr(task.get_coro(), "__qualname__", "")
== "serve.<locals>._client"]
```

Exactly the one-liner offered, adopted by Stream H. (`git diff eae1d01..462fa98 --
tests/` is empty, so it landed earlier, in `8a72939` — after my report 008 measurement
and before this one.)

**I did not trust Stream H's commit-message claim of "1,925 passed / 6 skipped". I
measured it myself**, in a throwaway worktree at `462fa98`, on this sandbox's CPython
3.11:

```
1925 passed, 6 skipped in 167.84s
ruff: All checks passed!
```

**CORRECTED BASELINE TO HOLD: `1925 passed / 6 skipped / 0 errors`, ruff clean.**
The previous record — "1913 passed / 6 skipped / 1 error (pre-existing, CPython 3.11
only)" — is **superseded**. There is no open pre-existing defect any more. Every report
and handoff entry that quoted the 1913/1-error figure is historical, not current.

### 4. CROSS-LANE FACT WORTH RECORDING FOR THE MANIFEST

`462fa98` established, in code, where kept wavs live and how they are named:

```
~/.local/share/assistant/audio/{when}-{session_id[:6]}.wav
e.g. 20261027-064450-77cc4e.wav   (session 77cc4efb1886…)
```

This is directly load-bearing for the WP7 manifest, which addresses artifacts by path:
the kept-audio path that rides in the journal's `detail` field will follow this shape.
Recorded so the manifest's path handling is designed against the real convention rather
than an assumption. It also confirms the privacy fence's importance — that path is a
real filesystem location on the owner's laptop and must never leave it.

---

## RULINGS RECORDED

1. **Dispatch rule ADOPTED as canonical amendment (007 §2.1).** Consumers key on
   `parts[2]` (event), never on verdict; verdict is corroborating state after a match
   only. Baseline, not window-contingent. Recorded as the contract mechanic's second
   pre-code save.
2. **Rename option DECLINED on the merits.** Mainline code is correct, verdict values
   are event-local semantics, the fence is consumer-side and costs nothing. Recorded
   as declined-with-reasons. **It must not drift into a mainline work queue** — noted
   explicitly so a future turn does not "helpfully" re-raise it.
3. **Report 008 self-correction endorsed** (canonical-document propagation awareness).
4. **Tip note:** re-verification dates against `eae1d01`; the true tip is `462fa98`;
   do not trust the relay — re-run the diff at next activation before fixtures, and
   date the window against the tip at closing. **Discharged by §1 and §2 above.**
5. **Posture confirmed: STOPPED AT GATE 1.** Sheets 1+2 numbers gate everything.

---

## DEFECTS FOUND

**None in the journal contract.** `journal_log.py` byte-identical; phrasing
character-identical; full verification table passes against the real module.

**One stale record, corrected:** my "baseline to hold" said 1 pre-existing error. It is
now 0 — A.1 was fixed by Stream H and I verified the fix on CPython 3.11 myself.

---

## NEXT GATE

**GATE 1 — owner scenes. UNCHANGED. Still the real gate.** Scene Sheets 1 and 2 stand
as issued. Nothing is built until the numbers arrive and the design chat rules go/no-go
on the MEGA target and the compression multiplier.

**GATE 1e — window OPEN, re-dated to `462fa98`, drift-free.** The next base movement
triggers another full re-run of the §1 table plus a fresh baseline measurement. Both
are now cheap and mechanical, which is the point.

**Standing commitment re-armed**, extended with one clause: on every base movement,
re-run the drift check **and** re-measure the suite, because A.1 proved that a
mainline fix can silently change my recorded baseline.

---

## OPEN QUESTIONS

**Q19 — none blocking.** The tip move was verified end-to-end, produced no contract
drift, and corrected one stale baseline number.
