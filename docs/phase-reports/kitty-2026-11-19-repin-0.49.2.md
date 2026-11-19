# Kitty re-pin 0.47.1 → 0.49.2 — rebuild record (lane Q, code only)

**Date:** 2026-11-19 · **Cluster:** Q (KITTY) · **Status:** re-pin CODE complete; release/deploy/live run
are NOT part of this lane and were not performed. Nothing was installed, released, deployed or run on
the owner's machine.

**Scope:** rebuild the pinned inventory against upstream `kovidgoyal/kitty` v0.49.2
(`b2cb871254fbdac19a085188813c8dfb258b95cd`), move the fail-closed version gates, classify the three
real semantic changes, and centralise the pin. Authority: `KITTY-REPIN-DECISION.md` (asks 46/49/50/52)
and `KITTY-SEMANTIC-DIFF.md` (2026-11-17), re-verified here against the v0.49.2 source tree.

## 1 · Method (measured, not estimated)

Both upstream tarballs were fetched from `codeload.github.com/kovidgoyal/kitty` at tags `v0.47.1` and
`v0.49.2` and parsed with `tools/kitty/build_inventory.py` (AST + literal option declarations; kitty is
never imported or executed). The two generated catalogues were then diffed by **semantic surface**
(option names/defaults/choices, protocol fields, `short_desc`, tier flags) rather than by file bytes,
because a repo-wide formatting pass touched every `kitty/rc/*.py` file at both tags.

```
v0.47.1 : 39 verbs · 167 verb options · 23 kitten options · 26 hazard flags
v0.49.2 : 41 verbs · 170 verb options · 23 kitten options · 31 hazard flags
```

- **Verbs 39 → 41**, zero removed: `screenshot` and `set-os-window-title` are new.
- **Options 190 → 193** (verb + kitten): `screenshot` adds `--match`, `--match-tab`; `set-os-window-title`
  adds `--match`. Global CLI options: identical set (5), no choice/semantics drift.
- **Hazard flags 26 → 31**: 25 of the 26 re-derive unchanged; `K3-send-key-exclude-active-unenforced-0.47.1`
  is re-derived and **renamed** `…-0.49.2` (owner ruling 2: nothing carries over); five are newly derived for
  the three real changes (`arbitrary-path-write`, `screen-content-return`, `os-window-reach`,
  `window-identity-spoofing`, `get-text-extent-unassessed-0.49.2`).
- **Kittens:** 25 → 25, same set, same option counts. `kitty/launch.py` and
  `kitty/simple_cli_definitions.py` changed at byte level but produced identical global-option surfaces.
- **Only one pre-existing verb changed behaviourally:** `get-text`.

## 2 · The three real changes, handled

1. **`get-text --extent` gained `alternate` and `alternate_scrollback`.** The grant is verb-granular and
   neither the verb nor the option name changed, so the widening is invisible in the
   `remote_control_password` verb list. The new extents read the not-currently-visible screen and its
   scrollback. **Handled by narrowing, which needs no approval:** `checker.validate_payload` refuses the
   two unassessed values (`get-text extent outside the assessed subset refused`) and the catalogue carries
   `get-text-extent-unassessed-0.49.2` at verb and `--extent` option level. Widening remains an owner
   ruling (ASK 50 / Approval 2c).
2. **`screenshot` (new).** An arbitrary-path PNG write *and* a screen-content return-to-caller. Classified
   `never-grant-rc` + `arbitrary-path-write` + `screen-content-return` + `os-window-reach`; refused again at
   the payload boundary so a mis-granted password cannot reach it.
3. **`set_os_window_title` (new).** Falsified the shipped errata line ("set-os-window-title is not a v0.47.1
   RC verb"): true of 0.47.1, false of 0.49.2. The errata entry is **annotated and corrected**, not carried
   forward silently; the verb is classified `never-grant-rc` + `window-identity-spoofing`.

## 3 · ASK 52 — f-string protocol specs

`set-background-image.protocol_spec` is an f-string at **v0.49.2** (it was a plain string with literal
braces at v0.47.1, which is why the shipped 0.47.1 catalogue recorded the bogus field type
`choices.{layout_choices.replace(",", ".")}`). The builder's AST walker already evaluates
`ast.JoinedStr`/`FormattedValue`, so the v0.49.2 run resolves it correctly to
`choices.tiled.scaled.mirror-tiled.clamped.centered.cscaled.configured` with all five payload fields.

The defect class is real even though this implementation does not have it, so it is now **locked**:
`assert_extraction_nonempty()` fails the build if any declared `protocol_spec`/`options_spec` extracts to
nothing, or if an unresolved `{…}` leaks into a field type. `tests/test_kitty_repin.py` asserts the same
against the committed catalogue, so a future regression is a build failure rather than a silent
"capability removed" reading.

> Correction on record (section G of the Q report): `KITTY-SEMANTIC-DIFF.md` states the f-string appeared
> at 0.49.2 *and* that the 0.47.1 literal was plain. Measured against both tags, the direction is:
> **0.47.1 = plain string containing literal braces; 0.49.2 = f-string that interpolates.** The doc's
> conclusion (the builder must parse f-strings) stands; its version direction is annotated here and was
> not copied forward.

## 4 · ASK 49 — one pin, not 63 literals

The pin now lives in **one module**: `src/assistant/hands/kitty/pin.py`
(`UPSTREAM_VERSION`, `UPSTREAM_COMMIT`, `OWNER_RPM_RULING`, `OWNER_VERSION_VERBATIM`,
`OWNER_DRIFT_RECONCILED`, `SOURCE_URL`, `CLI_VERSION_PREFIX`, the version-suffixed hazard names, the
assessed `--extent` subset, `NEVER_GRANT_VERBS`, and the reviewed create-marker source hashes).

Consumers changed to read it: `adapters/marker.py`, `checker.py`, `tools/kitty/build_inventory.py`,
`tools/kitty/render_inventory.py`, `tools/kitty/collect_platform.py`, and the kitty tests. The regenerated
`data/inventory.json` (539,589 bytes, sha256 `be06b3d2…`) records the measured owner strings:
`owner_rpm_ruling = 0.49.2-1.fc44`, `owner_version_verbatim = kitten 0.49.2 created by Kovid Goyal`,
`owner_drift_reconciled = true`, and `packaging_status` upgraded from ruling-supplied to MEASURED.

**Not** changed (other lanes own them — see §6): `src/assistant/hands/headless/instance.py` and
`src/assistant/hands/headless/contract.py`.

## 5 · The gate stays exactly as strict

`pin.cli_version_matches()` / `pin.check_cli_version()` keep the exact-prefix, fail-closed test:
`kitty --version` must start with `kitty 0.49.2 ` (trailing space, so `0.49.20` cannot pass). Asserts:
passes on `kitty 0.49.2 created by Kovid Goyal`; fails closed on `0.47.1`, on `0.49.20`, on
`kitty 0.49.2` without the trailing space, on `kitten …`, on `str`, on `None`. Marker evidence still gates
independently on catalogue version + commit + the four reviewed source hashes, and denies
`marker-source-evidence-missing-or-stale` on any stale pin.

## 6 · Owed outside this lane (named, not silently edited)

1. **P (hands-headless)** — `instance.py:49` still reads `b'kitty 0.47.1 '`, and `contract.py:17` still pins
   `INVENTORY_SHA = '7e0f01ff…'`. Consequence today: `hands open` refuses (`installed-kitty-version-not-inventory-version`)
   and consent checks raise `inventory-consent-drift`. That is **fail-closed and correct for a re-pin** —
   hands stay inert — but it must be updated before hands can start. Exact patch:
   ```python
   from ..kitty import pin                     # instance.py
   pin.check_cli_version(version.stdout)       # replaces the b'kitty 0.47.1 ' startswith test
   from ..kitty import policy                  # contract.py
   INVENTORY_SHA = policy.INVENTORY_SHA256     # single source, no second literal
   ```
   plus `tests/test_hands_dedicated_start.py:33` (mock string) and any standing-consent fixtures.
2. **Owner** — re-approval of the new catalogue hash `be06b3d2…` (F31 rule: a re-pin requires explicit
   re-approval; every old consent binding now fails closed and must be re-granted deliberately).
3. **Z** — `HR-Q-1` (`config.py`: owner version/rpm values + rc-password generation) and `OWNERS.yaml` +
   `scripts/check_ownership.py`, neither of which exists on the console branch yet.
4. **REL** — release cut consumes this inventory/pin later. Not this lane. No release, deploy or install
   was performed.

## 7 · Verification

- `pytest` on the kitty lane: see the Q report for the exact counts (`tests/test_kitty_*.py`).
- Full suite: see the Q report — the 16 remaining failures are **all** `tests/test_hands_headless.py` and
  all trace to §6.1 (`inventory-consent-drift`), i.e. the re-pin binding working as designed across a
  cluster boundary.
- `ruff check .` — 0 findings (the one pre-existing `SIM102` in `kitty/bridge.py`, a Q-owned file, was fixed).
- `jsonschema` validation of the regenerated inventory: passes.
- History: 10 kitty documents carry an appended **DATED SUPERSESSION — 2026-11-19** block and the
  regenerated reference carries its own dated line (11 total); no historical text was rewritten. Two
  R-owned documents that also say 0.47.1 were deliberately left untouched (HR-Q-3).

---

## 8 · Round 2 (same day) — hardening, reproducibility proof, verified hand-off patch

**Extra refusals (Q-owned files only).** `surface.resolve()` now refuses `pin.NEVER_GRANT_VERBS` *before*
any target binding, and `checker.coverage()` labels the two new verbs `never-grant-rc` instead of the
misleading `native-state`. The opaque-family accounting assertion (10) is unchanged and still asserted, so
the legibility fix does not move any existing count. Two new tests cover both.

**Reproducibility (measured, not asserted).** Two independent rebuilds of the v0.49.2 tarball produced
byte-identical catalogues — sha256 `be06b3d206acca5ea906a471b174d594cfccf7118936ba27212a15af947b15f0`
in both runs and in the committed file (`cmp` clean) — and the renderer run twice reproduces
`docs/kitty-inventory.md` exactly. The committed artefact is therefore provably the output of the builder,
not a hand-edited file.

**HR-Q-2 is a patch, not a request.** `reports/HR-Q-2-hands-headless-repin.patch` (4 files, 70 diff lines)
is included **unapplied** because `hands/headless/**` is P's. It was applied to a scratch checkout of this
branch, the full suite ran **2563 passed / 17 skipped / 0 failed / 0 errors**, and it was reverted.

> **Correction to the round-1 wording:** `headless/contract.py` must keep a *literal* hash — the module is
> copied into the per-instance directory and imported standalone by the fixed Kitty worker, which cannot
> import the package. `INVENTORY_SHA = policy.INVENTORY_SHA256` would have broken the worker. The patch
> updates the literal and adds
> `test_headless_inventory_pin_matches_the_kitty_catalogue`, so the two pins can never drift silently again.
