# BUILD-11 reader consolidation — Agent Z — 2026-11-26

Owner follow-up: **"BUILD-11 landed twice (PRs #138/#139).
`src/assistant/structured_reader.py` is orphaned — nothing imports it;
`discovery.py`/`streamread.py` are the wired path. Remove the orphan (or merge
any unique capability into `streamread.py` with tests proving it), run the
full streaming/discovery/errand slices, and merge the cleanup PR. One reader,
one truth."**

## Claim vs. verified reality (disclosed, not silently corrected)

The "nothing imports it" premise is **not accurate for this tree**. After the
#138/#139 reconciliation, `structured_reader` was lazily imported by:

- `src/assistant/errand.py` — the read-only `file.read_batch` skill (SQLite
  pagination) and the fully-read structured-input inspection/validation seams;
- `src/assistant/indexer.py` — pre-validation of JSON/JSONL/CSV/TSV before
  indexing;
- `tests/test_build11_streaming.py` — 13 tests.

What *was* true: no module-level imports, no CLI/IPC entry points, and the
richer wired path (`discovery.py` + `streamread.py`, `read_window`/`inspect`,
redaction, projection) carried every interactive surface. The owner direction
was executed as written — one reader, one truth — by merging the orphan's
unique capabilities into `streamread.py` first, then deleting it. No
capability was silently dropped.

## What was merged into `streamread.py` (each with a proving test)

1. **Cursor↔source digest binding.** Every `read_batch` cursor now carries
   `sha256` + `digest_scope`; resuming against a changed source raises
   `StreamError("cursor", "source changed since previous batch")`, and a
   source that changes mid-read raises `StreamError("read", "source changed
   during read")`. `Batch` exposes `trusted: False` (IF-6 pin, `__post_init__`
   guarded), `sha256`, `digest_scope`; `Batch.as_dict()` carries all three.
   Scope is `full` up to 1 MiB, else `head:1048576+size` — honestly labelled,
   and a note is attached to the batch when scoped. (Weaker than the
   orphan's full-hash-per-batch on huge files; stronger than no binding at
   all. Full-stream certainty is available via `validate()`.)
2. **`validate()`** — one full streaming pass counting every record without
   collecting values; returns `{format, records, sha256, digest_scope,
   complete: True, trusted: False}`. Any parse failure, invalid record
   (e.g. invalid JSONL lines) or source change raises. `expected_sha256`
   accepts either this module's digest for the source or a full-file sha256
   hex digest (the form the errand's raw byte-window path produces); a
   full-file comparison runs as fallback when the scoped comparison does not
   match, so neither calling convention can false-fail.
3. **SQLite hardening on read *and* inspect.** All SQLite access now goes
   through `_sqlite_snapshot()`: a private temporary directory, 0o600 copy,
   1 GB budget, WAL-mode refused via the header version bytes, the live
   database is never opened. Connections run with `query_only=ON`,
   `trusted_schema=OFF`, `SQLITE_LIMIT_LENGTH`, and refuse `CREATE VIRTUAL
   TABLE` before any table is read. Blob values surface as `{"blob_hex": …}`.
   Archive-member `.sqlite` targets (previously read as raw bytes) now read
   from the snapshot too; `inspect()` reports WAL refusal as `parse_error`
   instead of reading a potentially stale immutable file.
4. **`cloud_bound=True` fence** on `inspect`, `read_batch`, `read_window`,
   `iter_batches`/`iter_rows`/`record_count` (via kwargs) and `validate`:
   a `never_send_to_cloud` source raises `PermissionError` before any byte is
   read (§10.7), matching the orphan's fence.
5. **Per-record size caps with explicit limits.** `max_record_chars`
   (default `MAX_RECORD_CHARS=4 MiB`, floored at 256) now bounds JSON values,
   JSONL lines and CSV records; violations raise `StreamError` with the word
   "limit". CSV/JSONL decode errors stay loud; JSONL also catches
   `RecursionError`.
6. **`tar://archive#member` accepted as an alias** for a tar member (the
   `skill_fs_locate` convention), alongside `zip://` — both report the
   detected container kind in labels; archive containers themselves are now
   refused as record sources exactly like `zip://`.
7. **`StreamError` now subclasses `ValueError`** (like the retired
   `StructuredReadError`), so the pre-existing
   `except (OSError, ValueError, PermissionError)` seams keep catching
   policy and parse failures. No site that catches only `RuntimeError` was
   relying on `StreamError` (all such sites catch `StreamError` explicitly
   or let it propagate).

`errand.py` was rewired to the consolidated reader: the `file.read_batch`
skill passes `record_limit`/`max_record_chars`/`byte_budget` to
`streamread.read_batch` and uses `batch.as_dict()`; structured inspection is a
`_structured_schema_summary()` helper (format/sample_type/complete/trusted);
the fully-read validation seam calls `streamread.validate` with
`expected_sha256=obs.sha256` (works for files > 1 MiB via the fallback).
`indexer.py` pre-validates with `streamread.validate`.

## Deliberately not merged (disclosed, with reasons)

- **PDF record streaming through `file.read_batch`.** The orphan could yield
  `pdftotext` output as records, but that path was dead code (the planner
  routes `.pdf` to `file.read`; the indexer streams PDF into indexes).
  `streamread` explicitly refuses PDF streaming; reversing that in a cleanup
  PR is a build, not a cleanup. `read_batch`/`read_window` still refuse PDF
  loudly, and the indexer is unchanged. Follow-up lane if the owner wants it.
- **The orphan's HTML reader.** It emitted raw text parts including
  `<script>`/`<style>` bodies (i.e. untrusted markup presented as data).
  `streamread` strips script/style and tags and renders one bounded record.
  The old test literal was updated to assert the stricter, safer behaviour.
- **The orphan's `sample_type`/`sample` repr fields** in its dict
  `inspect()` envelope; the `test_build11_streaming` summary maps
  `format/sample_type/complete/trusted/sha256_prefix` from a bounded
  one-record batch instead. No consumer asserted the old repr shape.

## Tests proving the merge (all in `tests/test_build11_streaming.py`)

Ported: large minified JSON coverage + change-on-resume detection;
multiline CSV + JSONL + ZIP member + unfinished/never-send fences; tar-member
streaming via `tar://`; malformed JSON / record caps (JSON, JSONL, CSV);
HTML untrusted data (stricter); corrupt-tail `validate`; SQLite snapshot
read-only/fenced/WAL/virtual-table; OOXML pagination tail; spreadsheet text;
SQLite errand end-to-end (230 records, trusted=False, schema counts).

Added: cursor round-trips through JSON and binds the source (tampered
`sha256` refused); `validate` honours `expected_sha256` (module digest **and**
full-file raw-path hash on a >1 MiB source), wrong digests refused, never-send
cloud fence; `validate` returns scope labels; `Batch.trusted` pinned False;
SQLite blob→`blob_hex`; `inspect()` reports WAL refusal without raising;
JSONL record cap.

## Validation

- Target slices: `pytest tests/test_build11_streaming.py
  tests/test_z_discovery_streaming.py tests/test_z_errand_runner.py` →
  **82 passed** (was 77; includes ported + new capability proofs).
- Full suite: `PYTHONPATH=src pytest -q` → **3444 passed, 32 skipped, 1
  deselected** (32 skipped = `slow` voice probes, unchanged). The 32 failures
  seen mid-work were missing sandbox deps (`httpx`, `numpy`, `websockets`,
  `google-genai`), pre-existing and unrelated; with those installed the suite
  is fully green, including at base commit.
- `ruff check` clean on all changed files; `git diff --check` clean.
- Ownership lint at HEAD: `scripts/check_ownership.py lint` → **39
  zero-owner / 0 multi-owner** (same as base, which also lists
  `structured_reader.py`). After this change lands, one unowned path
  disappears. Static ownership guard unchanged (`OWNERS.yaml` untouched); the
  wired modules remain unowned at HEAD — owner-directed exception, not a
  green guard result, same status as PRs #138/#139 disclosed.

## Limits / notes

- Cursor digests for files > 1 MiB bind `head:1048576+size`, not every byte;
  full-stream certainty goes through `validate()`. Both scopes are labelled
  on the batch/cursor; the label travels with the envelope.
- SQLite/office byte positions count rendered bytes/text, not pages/ZIP
  offsets (unchanged wired-path semantics). Office resume reparses earlier
  records (bounded memory, higher CPU) — the docx pagination fixture was
  rescaled from 60 000 to 6 000 paragraphs for the same reason.
- Windows/TOCTOU: snapshot copies protect against torn reads of SQLite;
  archive member streams are re-opened per digest; concurrent mutation of a
  plain file between the pre/post digests is still detected unless it is
  confined to bytes beyond the 1 MiB prefix at identical size (the
  `digest_scope` label says exactly this).
- No model calls of any kind in discovery/streaming/validation. Zero tokens.
