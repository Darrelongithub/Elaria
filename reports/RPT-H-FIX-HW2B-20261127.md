# Agent H — FIX-HW2B: descendant extents and contained-label duplicates

## Status

Synced with `origin/main` before work; the fetch confirmed the assigned base
`24e9ac7a3be1782897bf208fd93470926ea4fd0a` was current. Implemented FIX-HW2B
on the assigned branch. **Owner hardware retest is still pending**; this report
records sandbox evidence only.

## Fix

- The top-level window continues to use `Atspi.CoordType.SCREEN`, including
  both existing HW2 acceptance paths (screen-origin match, or near-zero
  window-relative origin with size match). Size/origin disagreements still
  reject the window.
- Every descendant now uses `Atspi.CoordType.WINDOW`; its true in-window
  offsets are translated from the accepted window rectangle. Each descendant
  rectangle must be fully inside that window. If any valid descendant escapes,
  all elements from that frame are discarded and `_elements()` journals the
  metadata-only `descendant_outside_window` reason count.
- `semantic_target()` may collapse same-name duplicates only to a unique
  actionable element whose rectangle fully contains every match (including a
  contained label). Separate same-name controls remain ambiguous and resolve
  to `None`. Existing downstream sensitive-role checks are unchanged.
- Confidence gates, point-only behavior, and `OWNERS.yaml` were not changed.

## Regression coverage

`test_bug_hw2b_*` fixtures cover:

- The owner's `(811,475)` origin-based dump shape: dialog → nested panels →
  Cancel push button + contained Cancel label. `Cancel` resolves to the button
  at its true bounds `(1011,575,80,36)`.
- Two separate Cancel buttons still resolve to `None`.
- An out-of-window descendant rejects the whole frame and journals the reason
  without logging its accessible name.
- A collapsed sensitive control is still refused by `ground()`.

## Validation

- `.venv/bin/pytest -q tests/test_bug_hw2_atspi.py tests/test_nus*.py tests/test_bug_hw1*.py` — **117 passed**.
- `.venv/bin/pytest -q` — **3599 passed, 32 skipped, 1 deselected**.
- `.venv/bin/ruff check tests/test_bug_hw2_atspi.py src/assistant/_observation_linux.py src/assistant/observation.py` — passed.
- `git diff --check` — clean.

## Owner's zenity retest script

Prerequisites: install the merged checkout in the normal environment; set
`[nus_pointer] enabled = true` and `[quota.grounding] enabled = false` in
`~/.config/assistant/config.toml`. Run `assist doctor`, then
`systemctl --user restart assistant.service elaria-nus.service`.
Use the terminal only to schedule each ask, then focus the zenity window before
the four-second delay expires. Keep it away from desktop origin `(0,0)`.

1. **Visible Cancel:** open a test dialog in one terminal:
   ```sh
   zenity --question --title='Elaria HW2B check' --text='Point only; do not click.' --ok-label=OK --cancel-label=Cancel
   ```
   In another terminal:
   ```sh
   sleep 4; assist ask 'where is the Cancel button'
   ```
   Focus zenity during the delay. Expected: orb/ring centered on the **Cancel
   button** (not the dialog corner), no click, no focus theft, and the dialog
   remains open. Ring clears on focus change or within its normal 12-second
   lifetime.

2. **Nonexistent label:** while that same dialog is open:
   ```sh
   sleep 4; assist ask 'where is the nonexistent widget button'
   ```
   Focus zenity during the delay. Expected: no ring; honest
   **"I couldn't find it"**; no VLM/API calls.

3. **Password field:** close the question dialog manually, then open an empty
   throwaway prompt (do not type any real credential):
   ```sh
   zenity --password --title='Elaria HW2B sensitive check'
   ```
   In the other terminal:
   ```sh
   sleep 4; assist ask 'where is the password field'
   ```
   Focus the password prompt during the delay. Expected: sensitive-field
   refusal, no ring, no click, and no field contents or pixels in logs.

If Cancel still fails, collect metadata-only diagnostics:
```sh
journalctl --user -u assistant.service --since '10 minutes ago' --no-pager | grep -E 'observation\.atspi\.(windows|snapshot)'
```
Report the actual ring placement and rejection counts. Only the owner's eyes
close the hardware retest; fixtures and a merged PR do not establish hardware
success.
