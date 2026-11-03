# Console readiness contract correction — 2026-11-03

Parent: `42a717d27519808c100824ebb90985a1e38dc5b0`.
Branch: `arena/b65d5161-elaria`. Resulting commit supplied in delivery.
**TESTED-ONLY locally; owner live-model/browser verification remains pending.**
No PR, force-push, protected-file change, engine change or kitty unpark.

## Owner evidence and defect

The owner relayed a successful launcher checksum check and status IPC round-trip followed
by the bridge's readiness refusal. The reported daemon status was running, Gemini mode
`live`, and connectivity `ONLINE`, with nested `effective_mode: ONLINE`, display alias
`mode: online`, `online: true`, `offline: false`, `forced_offline: false`.
This is owner-relayed evidence, not a new builder-side hardware observation. It establishes
that the reported attempt reached readiness evaluation; it does not prove a model turn.

The bridge compared top-level `connectivity_mode` against lowercase `online`. Its fixture
encoded that same incorrect assumption. The producer uses uppercase effective-mode enums.

## Contract chosen from the producer, not a casing workaround

Source authority is the accepted parent's `src/assistant/modes.py`:

- `ModeManager.status()` resolves preference and observed health into **ONLINE**, **OFFLINE**,
  or **FORCED_OFFLINE**. Owner-forced offline wins; explicit online may remain ONLINE even
  when the last network check was unhealthy.
- `ModeStatus.is_online` is exactly `effective_mode == ONLINE`.
- `ModeStatus.as_dict()` emits `effective_mode` unchanged, `mode` as its lowercase display
  alias, and booleans derived from that effective mode.
- `Daemon._status()` emits the same snapshot under `connectivity`, and copies its uppercase
  effective mode into top-level `connectivity_mode`.

The bridge now chooses **`connectivity.effective_mode == "ONLINE"`** as its authoritative
eligibility field, matching the daemon's preference-resolved `is_online` policy. It also
requires consistent producer booleans: `online is True`, `offline is False`,
`forced_offline is False`. Missing, malformed or contradictory data refuses.

There is no case-folding, lowercase-alias fallback, or network-health override. The tests
exercise the real ModeManager with synthetic probes, including explicit online/unhealthy,
auto/offline, and forced-offline/healthy postures. This deliberately distinguishes policy
eligibility from a guarantee that the next provider call will succeed.

## Audit of remaining daemon-field comparisons

| Consumer check | Producer / conclusion |
| --- | --- |
| `running is True` | `_status()` emits the literal boolean True; unchanged. |
| status `gemini_mode == live` | `config.py` defines VALID_MODES as live/record/mock. Environment input is stripped/lowercased; configured values must belong to that lowercase set; automatic defaults are lowercase live/mock. Normal construction cannot produce LIVE. `_status()` returns `self.config.gemini_mode` unchanged. |
| reply `mode == live` | `_ask`, `_guest_turn` and `_guest_turn_normal` return the same `self.config.gemini_mode`. It is not the daemon activity mode idle, nor the connectivity enum. The lowercase comparison is correct and remains strict. |
| reply `fixture is not None` | `_ask` copies `HarnessResult.fixture`; that defaults to None and is populated from response fixture metadata. SDK text transports return text/usage, not fixture metadata. Mock/record postures remain refused independently by mode. No live reply casing mismatch found here. |
| model tags | Actual `_ask` tags gemini/gemini-unparsed-command and show-off's showoff match the existing allowlist. Unknown tags still refuse. |
| local tags | `_run_intent` uses local-intent/local-memory. `_ask` additionally emits **local-awareness** and **local-hotword-checkin**, not company-awareness. Corrected that nonexistent name and admitted the real check-in tag, only with the explicit non-model prefix. |
| refusal/fallback tags | local-queue, local-timeout-fallback, withheld, guest-deflection and showoff-refusal match their producers. Show-off's offline-only **local** tag now produces an explicit OFFLINE error rather than an unspecified provenance error; it is never presented as model output. |
| queued/withheld indicators | `_ask` returns queued_job_id and withheld as None absent those conditions; existing checks unchanged. |
| Unix envelope | Existing server echoes request id and uses boolean ok plus result/error. Client still sends only status/console.say; those registered method names match exactly. |

The other bridge string comparisons concern its own §5 protocol, HTTP paths, Host/Origin
and asset identities, not additional daemon-produced enums. No new daemon handler is needed.

## Fixture-first RED → GREEN evidence

Before modifying bridge.py, changed the synthetic LIVE fixture to the real reported casing
and consumed connectivity shape, and added an assertion against `ModeStatus.as_dict()`.
Offline fixtures now use the corresponding uppercase enum and consistent nested fields.
Each FakeRPC gets a deep copy, preventing nested-state contamination between tests.
No unrelated owner timestamps, conversation IDs or content were copied into fixtures.

Against the **unchanged old gate**, the serializer assertion passed, while both direct
readiness and the existing real-WebSocket-to-Unix test failed:

```text
2 failed, 1 passed in 0.14s
```

The direct failure was the exact readiness refusal; the wire failure was close code 1013
instead of hello-ok. After correcting the gate, the same three tests passed:

```text
3 passed in 0.12s
```

Additional regressions bind the contract to actual producer code, not just a new literal:

- Real preference resolver and serializer; missing/malformed/contradictory fields.
- Config input LIVE / mixed case normalizes to lowercase; mock/record remain ineligible.
- Real `console.say` returns the local awareness/check-in tags and lowercase mode.
- WebSocket → actual daemon status and `_ask` producers, with only generation and network
  probes replaced by keyless stubs. This exercises real response envelopes and fixture=None.
- Existing launcher preflight/process, checksum refusal, HTTP/DOM, unknown-outcome and
  reconnect tests all run using the corrected status fixture.

Shared fixtures are unchanged. No live provider, microphone or owner hardware call occurred.

## Final local gates

Bridge suite, **35 additional cases** over the parent's 64:

```text
99 passed in 8.00s
```

Full suite:

```text
2498 passed, 6 skipped in 110.75s (0:01:50)
```

Arithmetic: **2463 + 35 = 2498**. Python **3.11.2**, no Python 3.14 run.
Ruff: **All checks passed!** `git diff --check` clean.
`gate_verbatim` passed; engine remains
`5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447`.
No browser asset was changed or rebuilt in this correction.
Local ignored logs: `.venv/console-readiness-red.log`, `.venv/console-readiness-full.log`.
No automated CI or successful owner live-model turn is claimed.

## Release integrity and structural audit

Regenerated the bridge payload pin inside `console/run_bridge.py` and all launcher hash
references/one-line invocations in `console/BRIDGE.md`. No integrity bypass or owner edit.

- bridge.py SHA256: `5c996c849e00d3487bddd4a2dda81a1d3fe0d26008dfad8d72247b2ed46260a5`
- **console/run_bridge.py SHA256:**
  **`54f93a9ce35a1eea4847aa35c96bf7d484f45fec7954142d80f122ca5f524d05`**

Scope is six console-only paths: bridge.py, run_bridge.py, BRIDGE.md, INTEGRATION.md,
test_console_wire_bridge.py and this new report. All other accepted files, including the
protected daemon/core, engine, shared fixtures and kitty files, remain byte-identical.
Historical 42a717d report and its original hashes remain historical, not rewritten.

The refreshed sandbox again supplied original-base Git metadata with accepted files.
Before edits, all **296** files were compared byte-for-byte against fetched 42a717d, with no
extra files, then HEAD/index metadata alone was restored on the fixed branch. The old local
kitty stash object `78bc7cc24f584f063b41caec20b24aabc3f41ff2` was **not materialized in this
refresh**; its historical reference remains recorded, but its availability is not claimed.
No stash was applied, dropped, recreated or unparked, and no kitty file changed. Any recovery
of that earlier local-only work is separate from this urgent correction. Scene NOT READY.

## NEXT

Owner may re-point the existing worktree to the delivered commit and use the regenerated
checksum-first launcher line in BRIDGE.md. No local patch or checksum exception is needed.
The remaining owner gate is a live typed reply and actual browser presentation. The honest
standalone shell remains available if that gate cannot be completed in time.
