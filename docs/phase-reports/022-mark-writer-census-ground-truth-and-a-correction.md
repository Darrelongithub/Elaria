# Report 022 - the mark writer, the census ground truth, and a correction I owe

**Date:** 2026-11-03 (Africa/Nairobi)
**Branch:** `arena/storage` @ `04ad75a`
**PR:** #24 (base `arena/c2a7085d-elaria` @ `a6cc150`)
**Frozen branch (condition 3):** `origin arena/e7a1cca5-elaria = b181712563c1577f5faea4e59fe5f7e104a89ed1` - verified before and after this activation. Untouched.

---

## DONE

Both open questions answered, one of them from evidence I did not have and could not have
checked. One of my own statements from last activation was **wrong** and is corrected
below - the correction is mine, and it is recorded rather than buried.

### 1. THE MARK WRITER - answered, one line, with the byte count

**`assistant.capture.WavSink` writes the never-retry marks: a sink opened and closed with
zero frames written emits exactly 44 bytes - canonical PCM header, `fmt` at offset 12,
`data` at offset 36, a zero-frame `data` chunk, and no LIST/INFO/fact chunk.**

Proven by running the class, not by reading it:

```
52494646 24000000 57415645 666d7420 10000000 0100 0100 803e0000 007d0000 0200 1000 64617461 00000000
RIFF      size=36    WAVE      fmt     16       1ch   16-bit 16 kHz  32 kB/s  2     16-bit data     0 frames
```

`WavSink.__init__` creates the file at 0600 and calls `wave.open(path, "wb")` then
`setnchannels(1)`, `setsampwidth(BYTES_PER_SAMPLE)`, `setframerate(sample_rate)`; Python's
`wave` module patches the header on `close()`. Zero frames written means a zero-length
`data` chunk, and the file is exactly 44 bytes. The same writer with one second of audio
produces 32,044 bytes.

`capture.py` is a **mainline file this lane does not own and has not edited** - I read it
only.

**The fmt chunk is byte-identical to the census captures** the design chat tabled:

```
census wav A fmt (bytes 12-35): 666d74201000000001000100803e0000007d000002001000
WavSink mark fmt (bytes 12-35): 666d74201000000001000100803e0000007d000002001000
IDENTICAL
```

So the writer emits canonical 44, matching the design chat's three byte-level headers and
matching the census mark.

### 2. WAS ANY REAL MARK MIS-TIERED? - No. Checked against ground truth, not the record.

This is the D10 class, so I checked the disk record rather than the manifest. The census
arithmetic is the ground truth available to me:

```
  35 session wavs      :   80,698,682 B
  event-spike.wav      :   57,600,044 B  (synthetic tone, relocated to test-assets)
  1 never-retry mark   :           44 B  (header-only)
  computed total       :  138,298,770 B
  du -sb audio/        :  138,298,770 B
  RECONCILES EXACTLY   : True
```

A chunked zero-frame mark could only be:
- **(a) a 38th file** - the arithmetic would then fail to reconcile. It reconciles exactly,
  so there is no 38th file; or
- **(b) hidden inside the 35** - at most ~62 bytes inside 80,698,682 bytes of tierable
  volume, i.e. **0.000077%**, and the average session wav (2,305,677 B) matches the
  report's 2.306 MB with no discontinuity.

The census found exactly one header-only artifact and named it. **No mark was ever
mis-tiered. The defect was latent everywhere, exactly as the design chat's own header
evidence implied.**

### 3. DID THE CAPACITY CENSUS MOVE? - No. Q26 stands unchanged.

| Quantity | Value | Status |
|---|---|---|
| Steady-state growth | 11.29 MiB/day | **unchanged** |
| Cold growth | 5.48-7.93 MB/day | **unchanged** |
| Q26 knock, daily audio only | 3.45-5.00 yr | **unchanged** |
| Q26 knock, + monthly events | 1.07-1.38 yr | **unchanged** |

Worst case if *every* mark were mis-counted as audio: +62 B per mark against cold growth,
and the census found one mark. That is ~36 B/day compressed against 5.48-7.93 MB/day -
**0.00063%**. It cannot move a published answer.

**Conclusion: the fix is purely defensive, which is still worth having.** It removes a
dependency on *which tool happened to write the file* - a restore from cold storage, an
artifact round-tripped through ffmpeg or sox, or a mark written by anything other than
`WavSink` could all carry a chunk, and none would have been caught by a size comparison.
The defect was latent, not live, and the lane's fixtures now cannot accidentally look like
something they are not.

### 4. OPEN QUESTION 1 (D7) - closed, nothing further from me

The design chat ruled D7 is mainline's and has relayed the fix, my measurement, and the
constraint that no fixture changes come without a grant. `tests/conftest.py` remains
forbidden to this lane. My measurement (1/20 with my changes, 3/20 at `60f0060` with them
stashed) was offered to prove the defect is not mine rather than to assign it; it has
served that purpose and I have nothing to add.

---

## A CORRECTION I OWE - `ladder.py` is MAINLINE's, not my lane's creation

Last activation I confirmed, in one line, that `src/assistant/ladder.py` was my lane's own
creation. **That was wrong, and the design chat's inference - which my wrong line appeared
to corroborate - is also wrong.** I am correcting it because the collision question it was
asked to inform is now inverted, and an uncorrected line here would be worse than the
original error.

**The facts, verified with full SHAs this time:**

- `src/assistant/ladder.py` **exists at `f915d8e` (my branch point) and at the base
  `a6cc150`.** It was created by mainline commit `b96fd23` (2026-10-25, "Phase 0 pin fix
  + WP0 EYES: model registry, log schema, ladder, watchdog, unit hardening").
- **Report 000's "No `ladder.py`" was true of the tree it inspected and false of the tree
  my lane branched from.** The harness checks out `ed20344` (the frozen-branch artifact);
  `ed20344` is an **ancestor** of `f915d8e`, and `b96fd23` created `ladder.py` *between*
  them. So report 000 was right about `ed20344` and wrong about the branch point. The
  design chat's "built between report 000 and increment 6" is right about the *creation*
  but wrong about the *author*: mainline built it, between report 000 and my branch point,
  not my lane.
- **The base's `ladder.py` has exactly four chains** - `console_chain` (582),
  `wake_chain` (620), `voice_chain` (655), `event_chain` (698), `run_chain` (748).
- **My HEAD has those four at byte-identical line numbers** plus `backup_chain` (764) and
  `run_chain` (851). My only removals from the file are the two argparse registration
  lines. 35,542 B on the base, 41,398 B on my HEAD.

**Why this matters for the collision question.** The risk the design chat named - "if
mainline ever writes its own ladder.py, PR #24 is where that collision surfaces" - has
already happened, in the benign direction: **mainline already owns `ladder.py`, and PR #24
is precisely where my extension of it merges.** There is no future collision to guard
against; there is a present merge to review. `backup_chain()` is appended after the
literal chains and the four pre-existing chains are untouched at identical offsets, so the
merge is additive by construction. Mainline's own "ladder" vocabulary - the §13.4 intent
ladder and the model escalation ladder, five and two prose references - lives in `cli.py`,
`hotword.py`, `daemon.py` and `intents.py`, and shares only the word, not the file.

**How the error happened, recorded so it is not repeated:** I ran
`git cat-file -e <sha>:src/assistant/ladder.py` when `<sha>` was **not yet a local object**
(the fresh clone's restricted refspec had not fetched it). `cat-file` failed on the
*commit*, and I read the failure as the *file* being absent. A later check in the same
session repeated the pattern with an unset shell variable, which made `git show :path`
read the index and appear to show `backup_chain` on the base. **Two checks, two false
negatives, both from shell/git plumbing rather than from the repository.** The rule that
would have caught both: never conclude a path is absent from a `cat-file`/`show` failure
without first confirming the revision resolved.

---

## THE SAFETY ADDENDUM HAS FIRED A SECOND TIME - push held

The re-provisioning recurred this activation, exactly as report 020 recorded and as the
ruling told me to assume it would:

```
ed20344 HEAD@{2}: clone: from https://github.com/Darrelongithub/Elaria.git
ed20344 HEAD@{1}: checkout: moving from main to arena/e7a1cca5-elaria
```

A fresh clone followed by a **forced checkout onto the frozen branch**, with the refspec
still restricted to `main` + `arena/e7a1cca5-elaria*`. **Per the safety addendum I stopped
and reported before pushing. Nothing was pushed this activation.**

The recovery was the report-020 method, in order:

1. Verified the frozen hash **before** touching anything: `b181712...` - unchanged.
2. Explicit-URL fetch of `refs/heads/arena/storage` (never the restricted refspec):
   `FETCH_HEAD = 04ad75a`, the commit I pushed last activation.
3. **Integrity check: `git hash-object` on disk vs `git rev-parse FETCH_HEAD:<path>` over
   all 21 tracked WP7 files - 0 mismatches.** The workspace file snapshot persisted my
   work exactly; only `.git` was reset.
4. `git checkout -f -B arena/storage FETCH_HEAD` - local only.
5. Verified the frozen hash **after**: `b181712...` - unchanged.

`.venv` was wiped again and recreated. **A trap worth recording:** the first suite run
after recreating it showed **21 failures** in `tests/test_stream_g_primary.py`. Those were
entirely `ModuleNotFoundError: No module named 'google'` from a venv built with
`pytest ruff` only, missing the `google-genai` the recorded baseline includes. With the
full recorded dep set (`pytest ruff google-genai httpx`) the suite is back to
**2104/6/0, ruff clean**. A re-provisioned venv is a measurement hazard, not a defect.

---

## Fifth base movement - bare, triggers nothing

`be9183c -> a6cc150`, four commits (voice-chain extraction and resilience work). Files
touched: `asr.py`, `gemini_client.py`, `scripts/file_leg_probe.py`, two phase reports, and
a new `tests/test_response_extraction.py`.

- **`journal_log.py` byte-identical** between `be9183c` and `a6cc150`.
- **`audio kept at` still 4** (daemon.py:1, transcribe.py:3). Drift 2 does not recur.
- Both §2 clauses re-verified directly against the local module: 6 parts with no detail, 7
  with; `parts[2]` is the event name and dispatch keys on it, never `parts[5]`.
- My branch's merge-base with the base is still `f915d8e`; `f915d8e` remains an ancestor
  of the base, so **no history rewrite** - my branch is simply behind by mainline progress.
- Suite re-measured unconditionally: **2104/6/0, ruff clean.**

**GATE 1e unchanged:** my lane still consumes no journal shape - there is no watcher code,
so the zero-migration-cost window is still open.

---

## Suite

**2104 passed / 6 skipped / 0 failed, ruff clean** - unchanged from last activation, and
the 21-failure scare was a venv dependency gap, not a defect.

---

## NEXT GATE

Report 022 closes both open questions and records a correction. The push is **held** under
the safety addendum pending the design chat's ruling on the second harness recurrence.
Increments 7 and 8 remain authorized and unstarted; nothing in them needs a ruling first.
