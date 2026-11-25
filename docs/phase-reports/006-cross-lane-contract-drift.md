# Phase report 006 — CROSS-LANE CONTRACT DRIFT: the addendum's journal shape is wrong

**Date:** 2026-10-27
**Branch:** `arena/storage` @ `7fc190a` (base `f915d8e396d3fed0b3c77af7b21b2031c09ede5b`)
**In response to:** Stream H addendum, 2026-10-27, §A.2 (cross-lane contract notice)
**Why this exists:** the ruling that ordered the contract check also ordered me to
*"report any drift from the contract verbatim."* There is drift, it is in the
addendum's own statement of the contract, and Stream H / WP1 may be coding against
it right now. This report is the correction.

---

## 1. WHAT THE ADDENDUM STATES (verbatim, quoted so the drift is unambiguous)

> "A.2 (cross-lane contract notice — awareness, no action): the WP7 storage watcher
> (PR #24) now CONSUMES the journal line shape as a contract: **RFC3339 ts · level ·
> event · 12-hex session or '-' · detail**, bound as `split(" ", 6)` (field count is
> variable — 6, 7 or 8 parts). If Stream H or WP1 changes the journal line shape or
> the "audio kept at {path}" detail phrasing, flag it in your phase report so the
> storage lane can re-verify before its integration reconciliation round. Also
> note: the kept-audio path riding in free-text detail is now a fenced privacy
> surface in the storage lane — never re-emitted to logs, sensors, PRs, or chats
> beyond its current journal form."

## 2. WHAT THE CODE ACTUALLY DOES (verified, not inferred)

`src/assistant/journal_log.py`, `format_line()`:

```python
def format_line(event, *, level="info", session_id="", peak=None, verdict="", detail=""):
    level = str(level).lower()
    if level not in _LEVELS:
        level = "info"
    peak_s = _EMPTY if peak is None or peak == "" else _flat(peak)
    return (f"{_ts()} {level} {_flat(event, dash=False) or 'event'} "
            f"{_flat(session_id)} {peak_s} {_flat(verdict)} "
            f"{_flat(detail, dash=False)}").rstrip()
```

Real shape, measured by running the module:

```
6 parts | '2026-10-27T07:04:44+00:00 info session.close ptt-abc123 0.42 closed'
6 parts | '2026-10-27T07:04:44+00:00 info transcription.landed ptt-abc123 - landed'
6 parts | '2026-10-27T07:04:44+00:00 info quota.counter - - -'
7 parts | '2026-10-27T07:04:44+00:00 warn transcription.rejected ptt-3 - rejected /home/u/audio/rec.wav'
8 parts | '2026-10-27T07:04:44+00:00 warn transcription.deferred ptt-2 - deferred quota paused'
```

**The real schema is SEVEN fields, not five:**

```
ts · level · event · session_id · peak · verdict · detail(optional)
```

---

## 3. DRIFT FOUND

### DRIFT 1 — the addendum's prose omits `peak` and `verdict` entirely

The addendum lists `ts · level · event · session · detail`. Reality inserts **two
more mandatory fields** between `session_id` and `detail`:

| # | Field | Placeholder when absent |
|---|---|---|
| 1 | `ts` | always present (RFC3339 with offset) |
| 2 | `level` | always present (`info`/`warn`/`error`) |
| 3 | `event` | always present (falls back to the literal `event`) |
| 4 | `session_id` | `-` |
| 5 | **`peak`** | **`-`** ← omitted from the addendum |
| 6 | **`verdict`** | **`-`** ← omitted from the addendum |
| 7 | `detail` | **absent entirely** (see DRIFT 3) |

**Consequence if Stream H or WP1 codes to the addendum's prose:** they would treat
`detail` as the 5th field. It is the 7th. Index `parts[4]` is `peak`, not `detail`;
index `parts[5]` is `verdict`, not `detail`. A watcher built that way would read
`0.42` or `closed` as the detail and silently find no `audio kept at …` phrase —
i.e. it would look correct and quietly never fire.

**What is CORRECT in the addendum:** the `split(" ", 6)` binding. Maxsplit 6 yields
7 parts, which maps exactly onto the real 7-field shape with the detail tail
intact. The binding is right; the prose that describes it is missing two fields.

### DRIFT 2 — my own report 005 §3.3 contains an error, corrected here

Report 005 claimed `quota.counter` with everything empty produces **7** parts with
"three `-` placeholders". Measured: it produces **6** parts
(`ts info quota.counter - - -`). Three dashes plus three leading fields is six,
not seven. The error is mine, it is in a document Stream H may be reading, and it
is corrected here rather than silently patched.

### DRIFT 3 — the field count is `6..N`, not "6, 7 or 8"

The addendum says "field count is variable — 6, 7 or 8 parts". That is true of the
samples I happened to pick and wrong as a rule. `detail` is **free text** — the
real `transcription.landed` detail is
`model_version=…; N chars committed; audio kept at /path/rec.wav`, and the real
`transcription.deferred` detail is
`low-confidence transcript queued for cloud redo (job #12); audio kept at /path/rec.wav`.
Both are far longer than two words. **The part count is unbounded above.**

Correct statement: **minimum 6 parts, unbounded maximum.** Any code that switches
on `len(parts)` is wrong, including mine in report 005's table.

### DRIFT 4 — `detail` is OPTIONAL and ABSENT, not `-`

`_flat(detail, dash=False)` returns `""` when detail is empty, and the line is
`.rstrip()`ed. So a line with no detail **ends at `verdict`** — there is no
trailing dash and no trailing space. The `-` placeholder convention applies to
`session_id`, `peak` and `verdict`; it does **not** apply to `detail`.

Consequence: a parser must not require a 7th field, and must not treat a missing
detail as an error.

### DRIFT 5 — `session_id` is 12-hex on the PTT/dictation path only

The addendum states "12-hex session or '-'". Measured minting sites:

| Site | Expression | Width |
|---|---|---|
| `daemon.py:1764` (PTT/dictation) | `uuid.uuid4().hex[:12]` | **12-hex** |
| `transcribe.py:1406` | `uuid.uuid4().hex[:12]` | **12-hex** |
| `daemon.py:2646` | `uuid.uuid4().hex` | **32-hex** |
| `daemon.py:2694` | `str(meeting.get("session_id") or uuid.uuid4().hex)` | 32-hex or meeting-supplied |

So 12-hex is correct for the three WP7-relevant events (`session.close`,
`transcription.landed`, `transcription.deferred` all flow from the PTT/dictation
path), but it is **not a schema invariant**. A watcher that hard-validates
`^[0-9a-f]{12}$` would silently drop every stream-F/G sensor line
(`ws.histogram`, `audio.sent`, `latency.table`, `final.*`). Recommendation: accept
`[0-9a-f]{12}` or `[0-9a-f]{32}` or `-`, and do not validate at all beyond
"non-empty and whitespace-free" unless a ruling says otherwise.

### DRIFT 6 — `_flat()` normalises whitespace in EVERY field, including `detail`

```python
def _flat(value, *, dash=True):
    text = " ".join(str(value if value is not None else "").split())
    return text if text else (_EMPTY if dash else "")
```

Every field is collapsed to single spaces. Consequence for the fenced privacy
surface: **the `audio kept at {path}` detail is not byte-faithful to the path** if
the path contains a newline, a tab, or repeated spaces. A watcher that extracts
the path from the journal and uses it to address the artifact on disk can miss.

Mitigation, and it is already the design: the journal tail is the *suspenders*;
the directory poll is the *belt*. The manifest should resolve the artifact from
the filesystem scan and use the journal only as corroboration, never as the sole
source of a path. Recorded here so the integration round does not "optimise" the
poll away on the assumption that the journal is authoritative.

---

## 4. WHAT IS CORRECT AND SHOULD NOT BE "FIXED"

So the correction is not a rewrite:

| Addendum claim | Verdict |
|---|---|
| `split(" ", 6)` binding | **CORRECT** — keep exactly as written |
| RFC3339 `ts` | **CORRECT** (`2026-10-27T07:04:44+00:00`, local time with offset) |
| `"audio kept at {path}"` detail phrasing | **CORRECT** — verified at `transcribe.py:1390` and `:415` |
| kept-audio path is a fenced privacy surface | **CORRECT**, and the storage lane agrees and restates it below |
| field list `ts · level · event · session · detail` | **WRONG** — missing `peak` and `verdict` |
| "6, 7 or 8 parts" | **WRONG** — it is 6..N, unbounded |
| "12-hex session" | **PARTLY WRONG** — true for PTT/dictation, 32-hex elsewhere |

## 5. ONE ACCURACY CORRECTION TO THE ADDENDUM'S FRAMING

> "the WP7 storage watcher (PR #24) now CONSUMES the journal line shape as a contract"

The watcher does not exist yet. PR #24 contains **documents and one paste-safe
shell script, no WP7 code** — no module, no config section, no CLI subcommand, no
systemd unit. What is true, and is the load-bearing statement: the contract is
**recorded as the binding constraint for the watcher when it is written**, and it
was verified against the real `journal_log.py` on `f915d8e` before any of it was
written down. No fixture has been authored yet, so nothing in PR #24 can currently
drift from the contract — but nothing consumes it either.

This matters for the notice's purpose: the ask ("flag it in your phase report so
the storage lane can re-verify before its integration reconciliation round") is
correct and remains open, but there is no running consumer to break yet. The
window to change the journal shape without a storage-lane migration is **now**,
while the watcher is unbuilt.

## 6. PRIVACY FENCE — RESTATED AND ACCEPTED

The addendum's fencing note is accepted verbatim and made operational:

> "the kept-audio path riding in free-text detail is now a fenced privacy surface
> in the storage lane — never re-emitted to logs, sensors, PRs, or chats beyond its
> current journal form."

Storage lane's binding rules that follow from it:

1. The watcher extracts the path **only** to address the artifact in the manifest.
2. The path is never written to a log line, a sensor event (`backup.*`,
   `storage.gauge`), a phase report, a PR, or a chat message.
3. `journalctl` output is never pasted anywhere. Scene Sheets 1 and 2 already say
   "numbers only, never content"; this is the concrete reason, now written as a rule.
4. The manifest stores the path (it must — it is the record of intent and state per
   artifact), lives only on the laptop at 0600 outside the repo, and is never
   committed.
5. `detail` may also carry `text_chars=N` and `model_version=…`. Those are counts
   and identifiers, not content, and are safe to surface as aggregates.

## 7. A.1 — CONFTEST DEFECT: STANDING DOWN, CONFIRMED STREAM H'S

The addendum hands `tests/conftest.py:108` to Stream H. **Acknowledged and stood
down.** For the record, so nobody re-opens it in my lane:

- Defect: teardown raises `AttributeError: 'async_generator_athrow' object has no
  attribute '__qualname__'` under CPython 3.11.
- Present on `f915d8e` before any WP7 work; deterministic; teardown-only; the 1
  error in an otherwise **1913 passed / 6 skipped / 1 error**, ruff-clean suite.
- The storage lane will not touch `tests/conftest.py`. It is the mainline's active
  theatre and a stacked-PR fix would collide.
- One-line defensive fix, offered to Stream H, not applied here:
  `getattr(task.get_coro(), "__qualname__", "")`.
- **Baseline WP7 must hold, unchanged:** 1913 passed / 6 skipped / 1 error
  (pre-existing, 3.11 only), ruff clean.

---

## NEXT GATE

**GATE 1 — owner scenes, unchanged and still the real gate.** Scene Sheets 1 and 2
stand as issued; the numbers come back before any machinery is built.

**New, and time-sensitive: GATE 1e — the journal-shape window is open NOW.** Because
no watcher exists yet, Stream H / WP1 can still change the journal line shape or
the `"audio kept at {path}"` phrasing at zero migration cost. After the watcher's
fixtures are authored, any shape change becomes a storage-lane migration. **Ask:
if Stream H or WP1 intends any change to the journal schema, say so before the
watcher is built.**

**GATE 1d — build the WP7 machinery**, still unblocked and still not started,
pending the owner's numbers.

---

## OPEN QUESTIONS

**Q14 — is the addendum's field list a relay truncation or a genuine
misunderstanding?** It reads like `peak` and `verdict` were dropped in the relay
rather than never known. If the former, the correction above is all that is needed.
If the latter, Stream H's mental model of the schema may have other gaps worth
checking before WP1 builds on it.

**Q15 — should `session_id` width be pinned in the schema doc?** Options: (a) leave
it unvalidated (recommended — it is an identifier, not a protocol field); (b) pin
"12-hex for PTT/dictation, 32-hex otherwise" as documented behaviour; (c) normalise
all session ids to one width. (c) is a breaking change to every consumer and is not
recommended while WP1 is in flight.

**Q16 — should `detail` whitespace normalisation be removed?** `_flat()` collapsing
whitespace in `detail` is what makes the kept-audio path non-byte-faithful.
Options: (a) leave it and rely on the filesystem poll as the belt (recommended,
zero risk to mainline); (b) exempt `detail` from normalisation — but that lets a
newline in a value forge a second journal line, which is worse. Recorded as a
decision, not built.
