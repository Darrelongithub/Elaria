# KITTY HANDS v1.1 — foundation checkpoint, 2026-11-02

**NOT DONE. TESTED-ONLY foundation; no live adapter is registered.** This checkpoint
is not completion of the consolidated builder block and is not owner hardware proof.
Remaining engineering work is listed explicitly below; it is not waiting on PR23,
console cherry-pick or SC-H1.

Branch: `arena/b65d5161-elaria` (owner-authorized additive lane), based on preserved
`35adbbaf5ccf471e2075aaea432f9429e4d2d1e7`. Resulting foundation commit SHA is provided
in the delivery message; a commit cannot contain its own resulting SHA. NO PR.

Authority: owner sequencing-only addendum > block > clause. Clause v2 remains unchanged,
14322 bytes, SHA256 `8be8a4a94e958e1fd0323d8e687418f73e6cfd407a5a08bb6720b75769ffb6bc`.
No design-document revision, branch switch or sequencing re-litigation.

## DONE at this checkpoint

- Resolved the failed AST extractor without importing/executing upstream kitty.
  Resolved v0.47.1 annotated tag to commit `fb5255b1ae4f0249ba832d6a773348fd103449ce`.
- Offline source inventory: **39 RC verbs, 167 command-local option entries**, five
  global options, payload declarations, typed CLI defaults, source hashes and hazards.
  Unknown verbs default K3. **28 upstream kittens/companion tools** enumerated; complete
  extracted transfer/remote-file options and kitty-specific SSH config/copy options.
  Installed OpenSSH delegation and actual Fedora membership remain unverified.
- Human reference, machine JSON and JSON schema. GPL upstream prose attribution/license
  included. Pinned-source regeneration is byte-identical.
- Additive encrypted AF_UNIX transport: runtime environment binding; lstat, no-symlink
  fd-walk, owned 0700 parent, S_ISSOCK/UID, anchored connect, SO_PEERCRED and inode recheck
  on every request; no /tmp/discovery/plaintext fallback. Runtime-read 0600 password files.
- Additive policy foundation using existing immutable Plan/Step hashing and R3 adjudicate,
  with mandatory trusted independent-checker injection. No default hand-open, session
  approval never substitutes for K3 exact consent, and legacy T3 is never overridden.
- Launch stamp/keep-focus/no-child-RC guards; journal-confirmed HER identity tracking;
  mixed-tab close escalation; pre-send identity/program binding and post-send text-delta
  observation; no automatic retry. `run` is marked silent and exit success is not proof.
- Private fsynced `kitty.act` JSONL sink, strict separate settings loader, draft setup,
  owner-only scene card and one-shot help/version drift script.
- **59 new synthetic tests**, including end-to-end Bridge → encrypted AF_UNIX JSON peer →
  policy/consent/effect observation/journal. Both refusal and positive cases measured.
  No real kitty, terminal emulator, compositor, owner window or model endpoint used.

## Verbatim local gates

Pre-change baseline (restored local test environment):

```text
2103 passed, 6 skipped in 99.69s (0:01:39)
```

New tests:

```text
59 passed in 0.48s
```

Full suite:

```text
2162 passed, 6 skipped in 97.32s (0:01:37)
```

Ruff:

```text
All checks passed!
```

Regeneration:

```text
39 remote-control verbs extracted
Pinned-source inventory regeneration: byte-identical
Inventory SHA256: a8d9a11f03e80cdf07f860f0ac4e5b6e37c1f630d16fb9783b3e4e6bb581dc4d
```

These are **local-runner-only** gates. No automated CI was wired or claimed. Existing
six skips are retained; new tests were not skipped in this environment. Optional local
cryptography/jsonschema dependencies were installed only into ignored `.venv`; frozen
pyproject/configuration files were not edited.

## DEFECTS FOUND / corrected research assumptions

1. Hyprland v0.57.0's configuration manager is Lua-only. The clause's historical
   `windowrulev2` snippet is not a version-correct install instruction. The setup draft
   supplies source-checked `hl.window_rule`, `initial_title`, `no_initial_focus` and
   whole-string regex spelling. Actual compositor behavior remains UNVERIFIED.
2. `set-os-window-title` is not one of v0.47.1's 39 RC verbs. Initial OS titles are exposed
   by launch's `--os-window-title`; do not invent a command or option.
3. v0.47.1 `send-key` declares `exclude_active`, but its handler/helper does not apply it.
   A flag alone is not protection: bridge checks explicit target IDs/focus and refuses
   active IDs in a broadcast. Focus races are not claimed solved by a preflight snapshot.
4. `listen_on` option prose omits `password` in one sentence, while pinned boss.py
   explicitly permits it. The implementation confirms the required password posture.
5. Bracketed paste is not universal non-execution proof. Unknown/absent mode needs
   program acknowledgement; text-delta evidence is deliberately not exit/execution proof.
6. Exact raw command lines may contain credentials. The journal uses exact command-line
   hashes/counts and foreground-process hashes; private transient consent binds the full
   identity. No raw terminal text or password bytes are persisted in events.

## NEXT GATE — unfinished engineering, before owner activation

- **Trusted-host integration remains unwired.** No daemon/CLI/console integration was
  edited. The frozen synthetic GateChecker is not a live kitty effect assessor. Implement
  and review a real independent assessor and exact owner-input binding; do not replace
  them with fixed-safe test lambdas. Stop/ask if protected/frozen edits become necessary.
- **Complete target/effect coverage is not finished.** The focused guards cover launches,
  sends and close/tab attribution; all 39 verbs are inventoried, not all independently
  verified end-to-end. Generic selectors, global/OS-window effects, compound effects,
  unsafe option combinations, async cancellation, streaming/error boundaries and per-verb
  effect adapters need further implementation/tests. Generic successful responses remain
  `unverified` unless a trusted independent effect verifier observes a result.
- **Durable replay recovery is not finished.** In-process consumed-plan protection and
  closed-on-restart consent are present. Full trusted-service journal reconciliation for
  crash/unknown-outcome recovery and cancellation still needs implementation.
- Complete Fedora installed-file inventory and installed OpenSSH option/default reference.
  Upstream bundle enumeration is not proof of the owner's RPM split/version/content.
- Run and reconcile the owner drift report after every dnf upgrade. No owner version or
  drift output has been received. The drift script itself has parser tests, not a live
  owner execution result. Default/help match is not semantic or hardware proof.
- Only after integration/drift gates, owner runs `docs/kitty-owner-scene.md`. No extra
  hardware session is scheduled here. Return both outcomes with HW-PROVEN / TESTED-ONLY /
  UNVERIFIED / BROKEN labels, metadata only. No “done” before required bring-back.

## OPEN QUESTIONS / holds

No new branch/sequencing decision is required: the owner's prior authorizations remain
in force. No request to weaken legacy T3, protected-file or hardware holds is implied.
Any future wiring that touches protected/frozen integration needs a specific ruling at
that boundary, not a guessed exception now. Raw owner content and secrets stay owner-side.

## Deliverable paths

- `src/assistant/hands/kitty/{transport,policy,bridge,journal,settings}.py`
- `src/assistant/hands/kitty/data/inventory.json`
- `src/assistant/hands/kitty/data/inventory.schema.json`
- `src/assistant/hands/kitty/data/COPYING.kitty`
- `tools/kitty/{build_inventory,render_inventory,drift}.py`
- `tests/test_kitty_hands.py`
- `docs/kitty-inventory.md`
- `docs/kitty-setup.md`
- `docs/kitty-owner-scene.md`

Extra-diff audit: this checkpoint adds only the listed kitty order files and this report.
All files present at `35adbba` are preserved byte-for-byte. ZERO edits to daemon.py,
transcribe.py, live_client.py, cli.py, config.py, ladder.py, pyproject.toml, HANDOFF.md,
frozen hands/console/QML/storage integrations. No new daemon, paid/quota service,
automatic config application, live kitty execution, PR, merge or console-side work.
