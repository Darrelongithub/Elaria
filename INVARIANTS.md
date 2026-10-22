I1 No silent loss/substitution: captured audio/data yields the real
   result or an explicit error naming the failed stage. Never a
   canned line, empty string or default.
I2 Every wait terminates on every terminal state (success, error,
   cancel, timeout, peer death, superseded session, session_id
   mismatch, daemon restart) with an explicit payload.
I3 Deadlines are total, not per-call. No timeout that resets on
   trickle traffic. Hostile values (inf, NaN, negative) are rejected.
I4 Nothing plays into an open mic. Every playback entry point passes
   the duplex gate, including when synthesis outlasts the estimated
   gate.
I5 Every state-changing action has an authenticated principal.
   Authority is computed by the daemon, never accepted from the IPC
   caller. Guest/class-mode limits hold in every sibling path.
I6 Round trips are exact (undo byte-identical; journal written before
   the action it records).
I7 One source of truth per config key; documented precedence; keys
   promised vs read vs documented agree; quota purposes correct.
I8 Shipped == installed, with doctor drift checks, and settings that
   actually apply.
I9 Errors are honest: right class, right exit code, no tracebacks,
   nothing swallowed into "ok."
I10 Cleanup returns to baseline: subscribers, tasks, fds, subprocesses,
    temp files and parked state, measured over 1,000 cycles.
