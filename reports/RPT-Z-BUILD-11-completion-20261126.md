# BUILD-11 completion — Agent Z — 2026-11-26

Supersedes the draft disposition in RPT-Z-BUILD-11-20261126.md.
Owner follow-up: **“Finish then merge”**. All work remains on
`arena/33287bfa-elaria`; PR #139. Current main was merged into this branch
before integrated testing. No ownership map or ownership guard changes.

## Closed acceptance items

- Configured, read-only discovery roots, bounded metadata walks and ZIP/TAR
  manifests; no extraction, moves or writes to discovered files.
- Path/filename **index metadata hits now feed both CLI find and IPC fs.locate**,
  controlled by `[discovery].search_index`. Cached hits are revalidated against
  current roots, protected paths, ignore sentinels, hidden/vendor trees,
  symlinks, file existence/type and live stat metadata. Live/cache hits dedupe.
- Chunked, schema-inspected structured reads with continuation, explicit EOF,
  redaction and never-send preservation. JSON/JSONL, CSV/TSV, SQLite and office
  record readers are generic, not domain- or chat-shaped.
- Indexer now persists extractor, extracted character count, truncation and
  parse failures, including re-extracting pre-provenance cached rows. Its
  compatibility extraction API names caps/errors instead of silently presenting
  a prefix as complete. Index text remains intentionally bounded; full file
  consumption is provided by the resumable reader. Both organise and stream
  index character limits apply (the smaller wins).
- `stream-report` reports extraction errors even when metadata identity was
  indexed successfully. Undecodable text files retain valid hashed identity for
  reversible organiser moves, with a recorded decoder error and no invented
  decoded content. Structured parse failures retain error status.
- Errands record partial reads and named parse failures. Read observations are
  always untrusted; only authenticated owner confirmation can promote facts.

## Final adversarial fixes

Tests exposed SQLite advancing by fetched instead of emitted rows. It now
advances one emitted row at a time across **all tables**, with byte accounting
explicitly labelled as rendered bytes. Office readers likewise no longer skip
paragraphs at record limits, and iterate primary members (all slides/sheets),
using record cursors and bounded XML parsing. Both propagate never-send flags.
Malformed JSONL errors reach the errand rather than becoming success-shaped
text, and invalid lines are withheld under redaction. Journal provenance no
longer includes the CSV header-bearing cursor.

Existing tests caught two integration regressions: new CLI leaves lacked smoke
entries, and decoder failures incorrectly invalidated otherwise fresh file
identity for organiser apply/undo. Both are fixed without loosening protected
paths, consent checks or file hash verification.

## Procedure evidence and limitations

The initial draft correctly disclosed missing pre-build evidence. That history
is not rewritten. Before completion changes, the existing audit/stdlib blueprint
was re-read; during completion, licence and API sources were verified via GitHub:

- https://github.com/python/cpython/blob/main/LICENSE — PSF licence/history.
- https://github.com/ICRAR/ijson/blob/master/LICENSE.txt — BSD-style three-clause
  licence, checked before its README. Its iterator blueprint is applicable, but
  no source was copied and no runtime dependency added.
- https://github.com/ICRAR/ijson/blob/master/README.rst — streaming iterator
  alternative considered; external parser/backends rejected for this stdlib lane.
- https://github.com/python/cpython/blob/main/Lib/json/decoder.py — verified
  `raw_decode` returns a value/end-index, not validation of the remaining input;
  explicit delimiter and trailing-content checks are required and tested.

Procedure steps: (1) alternatives/licences above; (2) stdlib record-cursor
blueprint and API budget below; (3) bounded entries/depth/records and tail-fixture
stress; (4) decoder API fact-check; (5) cursor/privacy research via author/enemy
code reading; (6) protected/symlink/archive/injection/owner-authority bug tests;
(7) repeated multi-window tests after fixes; (8) final review found SQLite,
office, journal and metadata-policy issues, corrected before completion.
This records completion-time remediation, not a false claim that the original
pre-build sequence had already occurred.

[quota]
Discovery, inspection, streaming, indexing and extraction reporting call **no
model: zero calls/day, zero tokens, hard cap zero**. No stranger-triggered feed.
Errand analysis retains the existing dispatcher/workhorse and owner quota table:
max_api_calls=10 per errand, max_step_api_calls=2; no new flash escalation calls.
Tests use mocks; no live model requests, accounts or credentials were needed.

Limits remain explicit: finite step/file/record budgets can stop before EOF and
are reported; oversized line records require a larger byte budget; unsupported
PDF streaming refuses loudly. Rendered text may be capped with truncation/notes;
full structured values remain in read_batch. SQLite/office byte positions count
rendered bytes, not physical pages/ZIP offsets. Office resumption reparses prior
records (bounded memory, potentially higher CPU). Concurrent file mutation is
not snapshot-isolated; no claim of TOCTOU-proof path access or real-hardware
performance testing. No voice/Wayland capability is introduced by this lane.

## Ownership and merge authorization

The owner's follow-up explicitly directs completion and merge of the previously
disclosed cross-lane implementation. The static ownership guard still denies
`config.toml.example`, `discovery.py`, `streamread.py`, `errand.py`, and now
`indexer.py`; this is an **owner-directed exception**, not a green guard result.
OWNERS.yaml and scripts/check_ownership.py remain unchanged. Zero-owner map
entries predate this lane as well; no attempt was made to hide or bypass them.

## Validation

- Focused integration/authority/privacy/config/indexer/CLI/organiser tests:
  **171 passed**; final indexer-cap compatibility recheck: **39 passed**.
- Ruff passes for all changed Python implementation modules and test files.
- `git diff --check` passes.
- Full suite result recorded below after the final run completes. Initial full
  run found missing sandbox test dependencies and the two regressions above;
  test-only environment dependencies were installed, not added to the project.

Final full suite: **3362 passed, 32 skipped, 1 deselected in 199.92 seconds**.
Command: `PYTHONPATH=src /tmp/venv/bin/python -m pytest -q`.
The subsequent stream-index-limit compatibility adjustment was separately
validated by the 39-test indexer/organiser/discovery suite above.
