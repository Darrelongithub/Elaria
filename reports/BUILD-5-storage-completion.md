# BUILD-5 — storage completion

Evidence: **sandbox fixtures only**; no Google Drive, real capture, rclone service,
or real restic repository was contacted. Model/API budget for this lane: zero model
calls; zero live storage API calls in sandbox. Synthetic subprocess stubs and
`LocalPathBackend` are fixtures, not backups of owner data.

A `flipped` transition now requires a recorded SHA-256, a matching local file, and a
confirmed **hash** verdict; presence-only and opaque boolean verdicts cannot flip.
The configured owner path writes a restic snapshot through rclone and verifies by
restoring that exact pinned snapshot and hashing its bytes, not by listing Drive files.
Old manifests can contain legacy flips authorized under the earlier presence-only rule;
status does not retroactively certify them. Verify or drill them before relying on them.

## Owner interface and operation

- `assist backup status`: manifest, backend, and path-free health history. `uploaded`
  is not a verified flip; status does not assert that previously flipped data is still
  healthy. Past failures remain visible even if a later test passes; inspect the private
  health journal for chronology.
- `assist backup run --artifact /absolute/path/to/audio/file.wav`: explicit single cold
  artifact, capacity-gated, verified before flip and local grace-trash move. An unknown
  quota fails closed. `--dry-run` classifies without network or changes.
- `assist backup run --all-cold`: explicitly run the same guarded path for cold WAVs.
  `assist backup watch --run-cold` performs that tier scan on each invocation, even if
  no file was just written; arrange a periodic owner-controlled invocation if automatic
  age/size transitions are desired. This does not install or start a background service.
  There is no newly invented warm threshold: the existing frozen hot/cold policy applies.
- `assist backup verify <artifact>` restores the pinned copy to temporary scratch and
  compares SHA-256, without changing the manifest state.
- `assist backup drill [artifact]` restores to temporary scratch, hashes and journals the
  result; it reports the restic check separately. `assist backup restore <artifact>
  --out <new-path>` restores and hashes into a new destination without overwriting.
  Existing `fetch`, `check`, and observational `watch` remain available.
- A run retries failures up to three attempts and records failures in the private health
  journal alongside drill records; a failed or unjournalable operation is reported.
  This is bounded immediate retry, not an installed scheduler or a promise of retries
  while the process is stopped. A later invocation is needed after a prolonged outage.

## Owner laptop eye-check (not performed in sandbox)

1. Install the project's restic and pinned-compatible rclone; configure the owner's own
   Google Drive remote with rclone on the laptop, and initialize a restic repository
   there. Keep credentials and the restic password outside the repository and escrow the
   password; configure `[backup] rclone_remote` and `rclone_path` in the laptop config.
   Make the restic password available to restic through its normal secure mechanism.
2. Confirm quota can actually be read and passes the existing remote floor/headroom and
   local scratch gates. Do not bypass a refusal. Inspect `assist backup status` and
   `assist backup run --dry-run` first.
3. With a disposable, explicitly selected cold recording and an independent original,
   run `assist backup run --artifact <absolute-path>`; confirm backend provenance and
   the verified flip. It moves the local copy to grace trash, not permanent deletion.
4. Run `assist backup verify <artifact>`, then `assist backup drill <artifact>`;
   check the journaled result and `assist backup status`. Restore with `assist backup
   restore <artifact> --out <new-path>` and compare the restored bytes independently.
5. Only after that owner eye-check, optionally schedule `assist backup watch --run-cold`.
   Confirm failure/health warnings are visible during a disconnected-remote test. Network,
   Google Drive credentials, real quota behavior, and owner hardware remain unverified.
