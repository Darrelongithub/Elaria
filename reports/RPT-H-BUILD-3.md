# BUILD-3 — Ask → Point (Agent H)

BUILD-3 makes the BUILD-1 NUS pointer askable both inside the bounded errand
runner and outside an errand on the console/voice/`assist` ask path, and assigns
optional VLM fallback its own diverted-material budget role under
`reports/SPEC-PROVIDER-ROUTING.md`.

**Point-only guarantee:** NO clicking, NO key injection, NO desktop mutation.
`observation.py` and its frozen thresholds (`0.3` AT-SPI, `0.4` base, `0.5`
unverified VLM, `0.6` sure vs best guess, `0.00002–0.25` area, sensitive
exclusion) and `OWNERS.yaml` are untouched.

## What changed

1. **Read-only `point` skill in the errand runner (`src/assistant/errand.py`)**:
   - Registered `"point"` in `READ_ONLY_SKILLS` (clicking/acting verbs remain
     refused with `PermissionError`).
   - Explicit pointing instructions (`"where is the delete button"`, `"point at
     Settings"`, `"where do I delete this"`, `"show me the Settings menu"`,
     `"circle Save"`, etc.) plan `[PlannedStep("point", ...),
     PlannedStep("errand.report")]`, capture once, ground via AT-SPI first,
     optionally invoke budgeted diverted VLM fallback, draw via `Pointer`, and
     record per-step cost/receipts in `errand_steps` and `report["point_outcomes"]`.
   - File/memory `"where"` queries (`"where's that invoice from March?"`,
     `"where is the invoice"`) and negated/quoted phrases remain untouched.

2. **Diverted-material VLM fallback budget role (`src/assistant/nus_pointer.py`,
   `src/assistant/config.py`, `src/assistant/store.py`, `src/assistant/cost.py`,
   `config.toml.example`)**:
   - Declared `[quota.grounding]` directly beside `[quota]` (`enabled = false`,
     `provider = ""`, `model = ""`, `verified = false`, `rpd_cap = 30`,
     `timeout_s = 4.0`). `rpd_cap = 0` disables VLM calls (never unlimited).
     Account verification is strictly per-lane and never inherited from
     `[quota].verified`.
   - Enforced in code (`assert_grounding_role_allowed` + `validate_config`):
     grounding runs exclusively as `role="vision_grounding"` /
     `capability="diverted_material"` and REFUSES Gemini providers, the
     personality tier (`gemini-3.5-flash-lite`), the 20/day flash escalation
     (`gemini-3.8-flash`), `-latest` aliases, and `FORBIDDEN_IDS`.
   - Every grounding call is journaled in both `store.llm_calls`
     (`role="vision_grounding"`, `is_user_turn=0`) and `SafetyJournal`
     (write-ahead + observation, provenance/metadata only; pixels are dropped
     immediately and never persisted).
   - Untrusted VLM JSON output (IF-6) is injection-screened
     (`hands.injection.suspected`), sensitivity-checked (including overlap with
     sensitive AT-SPI controls), forced to `kind="bbox"`, and validated through
     frozen `observation.ground`. VLM coordinates always stay `source="vision"`
     with ring label `"unidentified"` (or `"unidentified · best guess"` below
     `0.6`, with `"Best guess"` spoken/replied).

3. **Shared `point` skill wired to console / voice / `assist` ask path
   (`src/assistant/intents.py`, `src/assistant/daemon.py`)**:
   - Registered read-only `"point"` intent in `READ_ONLY_KINDS` and
     `CAPABILITIES` (with IF-6 untrusted-source wrapping as `observation`).
   - Wired `Daemon._run_intent` (`via="local-intent"`, accepted by
     `console/bridge.py`), `Daemon._ask`, `Daemon._nus_point`, and
     `Daemon.errands` onto the same `Pointer.point_instruction` engine, with
     guest/show-off isolation and clean watcher cancellation in `Daemon.aclose()`.

## Declared API budget per lane

- **Default posture (AT-SPI-only, `[quota.grounding] enabled = false`):**
  0 VLM calls, 0 tokens, $0, 0 uploaded bytes.
- **Personality tier (`gemini-3.5-flash-lite`) and escalation (`gemini-3.8-flash`,
  20 RPD):** **0 calls, hard-refused in code** — grounding never touches Gemini.
- **Diverted-material VLM lane (`[quota.grounding] enabled = true`):** bounded
  by `[quota.grounding] rpd_cap` (default 30 RPD, `0` = disabled) and
  `timeout_s` (default 4.0 s total wall-clock deadline), requiring per-lane
  `verified = true` for cloud providers and online connectivity.

## Sandbox verification (sandbox only — no hardware claims)

- `tests/test_nus_build_3.py`: **47 passed** (sandbox fixtures, fake Quickshell
  `NusDispatch`, fixture `Frame`/PNG, fixture diverted VLM):
  - Eye-check 1: fixture instruction → `pointAt` ring IPC fired with exact
    fixture bounds (`errand`, `ask`, `console.say`, and voice ask paths).
  - Eye-check 2: sensitive targets refused at pre-capture (`password`, `PIN`),
    AT-SPI (`Vault` with `sensitive=True`, zero VLM bypass), and VLM sensitive
    overlap — zero `pointAt` IPC, zero secret/pixel leaks in journal.
  - Eye-check 3: VLM-disabled mode (`enabled = false` and `rpd_cap = 0`) →
    AT-SPI-only, 0 VLM calls, honest `"I couldn't find it"`.
  - Policy isolation, daily cap enforcement, `unidentified` + `"best guess"`
    ring/spoken labels, IF-6 injection refusal, offline guard, timeout
    journaling, guest isolation, and read-only click refusal.
- `tests/test_nus_build_1.py` + 17 core regression suites: **402 passed**
  (sandbox); full runnable suite without optional `google-genai`/`numpy`/`websockets`
  extras: **3,174 passed**, 0 regressions.
- `ruff check` on all touched files: **0 errors**.

## Owner laptop eye check (not run in the sandbox — run in order)

1. Confirm prerequisites and overlay service are running from your graphical
   Hyprland session: `[nus_pointer] enabled = true` in
   `~/.config/assistant/config.toml`, `elaria-nus.service` active, and
   `assistant.service` restarted. Verify `[quota.grounding] enabled = false`
   first for the AT-SPI-only check, and run `assist doctor` to verify config
   schema passes cleanly.
2. Open a GTK or Qt app with a visible named button (e.g. **Cancel**, **Delete**,
   or **Settings**). Run `sleep 3; assist ask "where is the Cancel button"` (or
   ask via the console input or by voice: *"Elaria, where is the Cancel button?"*)
   and focus the target app before the delay expires. Confirm the violet orb and
   breathing ring land tightly on the button without clicking or stealing focus,
   the reply names the control, and the ring clears on focus change or within
   12 s.
3. Run the same check as an errand: `sleep 3; assist errand start "point at
   Cancel"`, switch to the target app, then inspect with `assist errand status
   <id>`. Confirm the errand ran `point` → `errand.report`, recorded `0` API
   calls, and drew the ring on the exact button without clicking.
4. Test sensitive refusal: ask `assist ask "where is the password field"` (or
   point at a real password/PIN box in a browser or password prompt). Confirm
   zero ring appears, Elaria refuses honestly (*"That's a sensitive field — I
   won't point at it."*), and `journal.jsonl` contains no secret text or image
   bytes.
5. Test VLM-disabled AT-SPI-only honesty: with `[quota.grounding] enabled =
   false`, ask for a control that does not exist (or an icon-only control absent
   from AT-SPI), e.g. `assist ask "where is the nonexistent widget button"`.
   Confirm no ring appears, Elaria answers `"I couldn't find it"`, and `assist
   cost` shows 0 vision-grounding calls and 0 Gemini calls.
6. *(Optional, only when you explicitly verify a non-Gemini diverted VLM
   provider account)* Configure `[quota.grounding]` with a non-Gemini provider +
   model, set `verified = true` and a small `rpd_cap`, and run `assist cost` to
   confirm the cap is shown cleanly as diverted material. Ask for an icon-only
   control absent from AT-SPI: confirm the ring carries `"unidentified"` (and
   dashed `"unidentified · best guess"` + spoken `"Best guess"` below 0.6), and
   confirm `assist cost` shows the call under `vision_grounding` with 0 Gemini
   personality or flash-escalation calls used.
