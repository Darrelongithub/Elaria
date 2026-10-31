# Hands core — sandbox-only interfaces

[TESTED-ONLY] `SyntheticSpace()` creates a fresh temporary workspace and private
control directory. It cannot be initialized with an owner path. Explicit fixture
seeding/indexing is test setup, not a callable model tool. Close queue handles
before closing the workspace. No service/unit/socket or live transport starts
on import.

[TESTED-ONLY] `Plan` is immutable and strictly parsed. `MockPlanner.advance`
consumes at most one synthetic request reservation and candidate; the caller
must respect a parked result's reason/next eligible time. No sleep/retry loop,
API key, provider SDK, network request or narration call exists.

[TESTED-ONLY] `SandboxCore` accepts only this workspace's `FakeRunner`. Pass
independent synthetic `Expected` re-read oracles for generic exec simulations;
file-operation oracles come from the indexed library state and tool semantics.
No oracle means no execution. `run` posts the privately rendered plan only
after its initial gates; current facts are rechecked at dispatch/resume.

[TESTED-ONLY] A returned `parked` result has a durable `ParkedQueue.pending()`
card. A decision must carry its ask ID and whole-plan digest. Repeated calls
with the same errand ID do not replay finished or uncertain steps; No persists,
stale decisions cannot authorize a revision, and cancellation/mismatch halt
cannot be cleared by changing plan bytes. Re-plan consent cannot execute a task.
Interrupted-to-unknown recovery is an explicit restart operation, not opening
a second connection and deciding another worker must have died.

[TESTED-ONLY] The simulated exec boundary records argv UTF-8 bytes, cwd and a
positively constructed environment; it never calls the OS process launcher.
T1 moves/trash and exact collision repair delegate to the existing
Executor/Store/Journal inside the temporary tree. The synthetic Executor subclass
only disables implicit conflict path rewriting, so approval cannot silently
refer to a different destination after a race. The existing mutation algorithms,
locks, caps, manifests, verification and undo remain in use.

[UNVERIFIED] This is not production confinement or a universal command analyser.
The fixture `SyntheticFacts` carries independent observed effects/dirty roots/
immutables/service choices; real measurement belongs to the ruled broker
integration. Generic task effects are fake. Process-group cleanup is an observed
fake lifecycle, not a demonstrated process-tree kill. No production T0 or T2
execution proof follows from these tests.

[TESTED-ONLY] Data-origin text has no plan-update route. The conservative
injection detector reports the known imperative/structured-plan fixtures; the
structural rule holds even if detection misses another wording. The exact
fixture oracle and immutable subsequent-plan trace are asserted in tests.

[TESTED-ONLY] `Reporter` is a private in-memory console view, not notification or
journal output. The R4 sink accepts only metadata and fixed diagnostics, emits
six/seven fields, and records failures without changing authority. File-operation
write-ahead logging is still the existing safety Journal, not this telemetry.

[UNVERIFIED] Standalone QML-to-core IPC remains unshipped. R7 DTOs are tested
against the queue in the sandbox; QML itself still captures local preview input.
There is no approval by screenshot, no actual desktop notification, and no
hardware gate result. See the current core report and proposed scene card.
