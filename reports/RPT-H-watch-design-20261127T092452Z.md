# RPT-H — WATCH-DESIGN: continuous local screen awareness (blueprint, no code)

**Agent H · DISPATCH-WATCH · WATCH-DESIGN · 2026-11-27**
Spec: `reports/DISPATCH-WATCH.md` (owner ruling + rails 1–5, read first).
Base: `42afd7f` on branch `arena/9974d83f-elaria`.
Deliverable type: **blueprint only.** No product code, no tests, no config, no
`OWNERS.yaml` edits. Hardware claims are the owner's eyes only.

**Evidence labels**

| Label | Meaning |
|---|---|
| `[OBS]` | I read this in the repo at the cited path and line. |
| `[DOC]` | Documented platform behaviour (AT-SPI, Hyprland IPC, logind). Not run in this sandbox. |
| `[INF]` | My inference. Attack it. |
| `[GAP]` | Not verified and not decidable from the sandbox. Listed in §12. |

**Sandbox limits.** This sandbox has no Hyprland session, no AT-SPI bus,
no portal, and no owner laptop. Every runtime claim below is `[DOC]`,
`[INF]`, or `[GAP]`. None is a hardware result.

---

## 0. Verdict and decisions for the owner

**Verdict.** Continuous AT-SPI watching is buildable on the existing
helper pattern. It needs (a) an event-driven watcher child process,
(b) a multi-window RAM tree that is never trusted past a 2 s draw-time
age without a single-window revalidation, and (c) a sensitive filter that
drops names and values **before** they reach memory. The design needs
**zero cloud API calls** (§9). Continuous screenshots stay out of scope
(ruling: NO).

**One finding to fix even if watching is never built** (`[OBS]`):
`_observation_linux.py:157-158` calls `node.get_name()` on **every** node,
including `PASSWORD_TEXT` nodes, and sends the name to the daemon in the
frame. The `sensitive` flag is computed from the role but the name is
still read and carried. Rail 1 says the tree must be incapable of holding
a secret, so this is a rail-1 defect in today's one-shot path. Fix it
first (§6.3, WATCH-BUILD-1).

**Decisions I need from the owner** (defaults are what I built the design on):

| # | Decision | Default in this design |
|---|---|---|
| D1 | Accept **best-effort** name filtering for displayed text (labels), with the residual in §6.4? | Yes. Password/sensitive *roles* are guaranteed by construction. Displayed label text is best-effort. |
| D2 | Freshness bound X (draw-time age ceiling without revalidation) | **2.0 s** (§5.2). |
| D3 | Swap exposure of RAM-only tree (§8.4) | Attempt `mlock`; if refused, journal a warning and keep watching. Owner may choose fail-closed instead. |
| D4 | "company mode" | **Not in the repo** (`[OBS]`: only `showoff` and class-mode posture exist). Treated as "any privacy posture". Owner to name it. |
| D5 | Cross-output windows (not on the screenshot's output) | Identity spoken only, no ring (§7.4). |

---

## 1. Procedure note: branch

The dispatch says "new `arena/*` branch". The session rules fix work to
the current branch, `arena/9974d83f-elaria`, and forbid creating others.
This report is committed to the current branch. The PR is opened from it.

---

## 2. Current code paths: replace, extend, or keep

| Path | What it does today `[OBS]` | Disposition in WATCH |
|---|---|---|
| `src/assistant/_observation_linux.py` `atspi()` (L75–169) | One-shot per ask. Reads the focused window's PID only. Requires `ACTIVE` on the window (L93–94). Walks ≤1000 nodes, ≤150 children per node (L125, L160). Calls `get_name()` on every node (L157). | **Extend.** Add a `watch` mode (long-running, NDJSON deltas). Keep `atspi` as the dark-watcher fallback and as a test oracle. Fix L157 for password roles (§6.3). Replace the `ACTIVE` gate with the Hyprland visible-output gate (§7.2). |
| `src/assistant/_observation_linux.py` `portal()` (L12–74) | Screenshot via portal, 12 s wait (L53). | **Keep.** Pixels remain snapshot-per-ask. |
| `src/assistant/observation.py` `Element`, `Frame` (L36, L45) | One focused-window element tuple per ask. | **Extend.** Add a `window` key to `Element`. Ids become `<window_key>:<n>`. The `Frame` stays the per-ask, immutable materialised view. |
| `observation.py` `_elements()` (L199) | `hyprctl activewindow` only. Logs rejection counts. | **Replace** with a read of the live store (`hyprctl clients -j` + watcher RAM). Keep the rejection-count journalling pattern. |
| `observation.py` `ground()` (L118) | Pure validator. Binds `frame_id` + `snapshot_id`. Refuses sensitive, or sensitive-overlapping, rects. Caps area at 25 %. | **Keep unchanged in contract.** Add a cross-window occlusion check (§7.3). |
| `observation.py` `semantic_target()` (L158) | Exact name. Same-name duplicates collapse only to a unique actionable element that contains all matches (HW2B). Otherwise `None`. | **Extend.** Return a `clarify` result when matches span >1 window (§7.1). Same-window HW2B rules stay as they are. |
| `observation.py` `capture()` (L228) | Tree read, then screenshot, then focus/output unchanged check (L238). | **Keep the focus/output check** for pixels. Remove the implicit requirement that the tree is captured at the same instant (§5.2). |
| `observation.py` `SECRET` (L24), `_sensitive()` (L114) | Regex: `SECRET_PATTERNS` plus `card/otp/ssn/seed/recovery`. | **Keep, reuse** at ingestion (§6). |
| `src/assistant/disclosure.py` `SECRET_PATTERNS` (L31) | Shared secret patterns. | **Keep.** Single source. |
| `src/assistant/nus_pointer.py` `_resolve_atspi()` (L590) | AT-SPI-first. Sensitive match refuses. Never falls back to VLM for a sensitive hit. | **Keep.** Extend the match to the multi-window store. |
| `nus_pointer.py` `draw()` (L637), `Pointer.point_instruction()` (L766) | Capture, ground, draw. VLM fallback budgeted. | **Keep.** Add the draw-time staleness check before `draw()` (§5.3). |
| `nus_pointer.py` `GroundingRequest` (L1195) | Sends the query text and PNG only. Element names are **not** sent `[OBS]`. | **Keep, and enforce** with a test (§9). |
| `src/assistant/daemon.py` `permitted()` (~L1308) | `enabled` + not halted + explicit flag. | **Extend** so watching is gated on the same predicate. |
| `daemon.py` `_halt()` (L1625) | `set_halt()`, interrupts speech, sets `mode=halted`. | **Extend** to stop the watcher synchronously (§4.3). |
| `daemon.py` `_emit_capture_state()` (L563) | Broadcasts `capture.state` on transitions only. | **Pattern to copy** for `watch.state`. |
| `src/assistant/safety.py` `set_halt`, `clear_halt`, `is_halted` (L294–306) | Flag file in the runtime dir. | **Keep.** The watcher also reacts to the flag file (§4.3). |
| `src/assistant/hypr_binds.py` (L48) | `SUPER + SHIFT + F12` → `assist halt`. | **Keep.** This is the owner's instant-off. |
| `src/assistant/showoff.py` `enter()` (L384), `exit_hotkey()` (L460) | Demo mode, zero standing permissions. | **Extend.** Showoff entry stops the watcher. |
| `src/assistant/nus_surface.py` `CAPTURE_STATE_VIEW` (L42) | Dumb renderer. **Unknown states hide.** | **Extend** with a `watching` state, rendered as a distinct indicator (§4.4). |
| `src/assistant/capture.py` `RollingAudioBuffer` (L418) | RAM-only rolling buffer, memory only. | **Pattern to copy** for the RAM tree's lifetime rules. |
| `src/assistant/journal_log.py` `log_event()` (L85) | Metadata-only event lines. | **Keep.** Watch transitions journal state and reason codes, never names. |
| `src/assistant/intents.py` (IF-6 at L15, L44) | Observation is non-dispatchable; screen text is untrusted. | **Keep.** Element and window names are IF-6 data. |
| `src/assistant/_observation_linux.py` (no logind code) | `[OBS]` no `login1`/`LockedHint` anywhere in `src/`, `ui/`, `systemd/`. | **New** (§4.5). |

---

## 3. The five rails → mechanisms → tests

| Rail | Mechanism | Test that must exist before the build is accepted |
|---|---|---|
| **1. Password nodes never enter the tree** | Role check *before* any property read. `PASSWORD_TEXT` → tombstone (§6.2). Name-pattern hits → tombstone. Watcher never subscribes to text events. | Canary test: a fake node whose `get_name/get_description/get_text/get_value` raise. Assert the output and the serialised journal lines contain no canary. |
| **2. Visible when watching** | `watch.state=watching` drives an indicator that is shown **only** while watching (§4.4). Overlay disconnect → PAUSED. | Simulate overlay EOF. Assert the watcher stops within 500 ms and the state journals `paused/overlay-gone`. |
| **3. Instant off** | Halt flag, SUPER+SHIFT+F12, showoff, lock, and mode gates all force OFF (§4.3, §4.5). RAM tree cleared on every exit. | Per-trigger test: each trigger → OFF, tree empty, no further deltas accepted. |
| **4. No authority change** | Watcher output is data only. It has no path into `intents`, `executor`, or any dispatch. Pointing still needs an ask. | AST import test: the watcher module does not import `executor`, `hands`, `intents`, or the pointer's draw path. |
| **5. Resource honesty** | Event-driven; no timers except the bounded debounce. Budget declared (§9, §10). | Owner measurement run (§10). Sandbox cannot satisfy this. |

---

## 4. Architecture

### 4.1 Processes

```
daemon (assistd)
  ├─ WatchSupervisor  (new, in daemon)
  │     spawns ──► watcher child:  /usr/bin/python3 _observation_linux.py watch
  │                  • AT-SPI event listener (structural events only)
  │                  • Hyprland socket2 listener (window lifecycle)
  │                  • logind listener (lock / sleep)
  │                  emits NDJSON deltas on stdout (one line = one delta)
  │     reads deltas ─► WatchStore (RAM, daemon side)
  └─ ask path: observation.capture() ─► WatchStore.view() ─► Frame ─► ground()/draw()
```

- **Why a child process, not a thread.** `[INF]` A crash or a GI
  segfault in the AT-SPI bridge then takes down only the watcher. It also
  matches the existing `/usr/bin/python3` helper pattern (`observation.py`
  `_helper()`, L195), which is why the GI bridge stays on system Python.
- **Why supervised by the daemon, not a separate systemd unit.** Halt and
  showoff must stop the watcher synchronously. A daemon restart must also
  end the tree. A separate unit would survive both.
- **IPC.** stdout NDJSON, each line ≤ 64 KiB, each delta carrying a
  per-window `seq`. A gap in `seq` forces that window into `stale` (§5.1).
  A malformed line journals `watch.ipc/malformed` and drops the window.
- **Stderr.** Metadata only. Tracebacks are sanitised so they never contain
  a node `repr` (§8.7).

### 4.2 Watched sources (structural only)

| Source | Events | `[DOC]` notes |
|---|---|---|
| AT-SPI registry | `window:create`, `window:destroy`, `window:activate`, `object:children-changed:*`, `object:state-changed:showing`, `object:property-change:accessible-name`, `object:bounds-changed` | **Never** `object:text-changed:*` (the payload can carry inserted text) or `object:text-selection-changed`. |
| Hyprland IPC `socket2` | `openwindow`, `closewindow`, `movewindowv2`, `windowtitle`, `workspace`, `monitoradded`, `monitorremoved` | Event names are `[DOC]` for Hyprland 0.57 (the owner's version per `hypr_binds.py` docstring). Verify on the owner's build (`[GAP]`). |
| logind (system bus) | Session `Lock`/`Unlock`, `PrepareForSleep`, `LockedHint` | `[DOC]`. Nothing in the repo uses it today (`[OBS]`). |
| Halt flag | `Gio.FileMonitor` on the runtime dir | Event-driven. No polling. |

### 4.3 Instant-off (rail 3)

Every stop trigger goes through one function, `WatchSupervisor.stop(reason)`:

1. Set state OFF and journal `watch.state` with the reason code.
2. Send the child `SIGTERM`. After 200 ms, `SIGKILL`.
3. Clear `WatchStore` (drop all dicts/lists, then `gc`).
4. Broadcast `watch.state=off` to the overlay (§4.4).

Triggers:

- **Halt.** `daemon._halt()` (L1625) calls `stop("halt")` before it returns.
  The flag-file monitor is the second path, covering the `cli.py` L2791/L2796
  flag-file-only path (`[OBS]`, daemon down).
- **SUPER+SHIFT+F12** → `assist halt` → the same path.
- **Showoff.** `ShowoffService.enter()` (L384) → `stop("showoff")`.
- **Class / privacy posture.** `[OBS]` presence.py class-mode posture and
  modes.py `FORCED_OFFLINE` → `stop("posture")`.
- **Lock/sleep.** logind `Lock` or `PrepareForSleep` → `stop("lock")`.
- **Overlay gone** (§4.4).

Resume is never automatic. Watching restarts only through an explicit
resume, after a successful full resync (§4.6).

**Latency target** (proposal, measured in §10): trigger → RAM cleared
≤ 500 ms.

### 4.4 Visible when watching (rail 2)

- `[OBS]` The overlay is a dumb renderer of daemon state (`nus_surface.py`
  L40–44). Unknown states hide.
- Add state `watching` to `CAPTURE_STATE_VIEW`, or to a parallel
  `WATCH_STATE_VIEW` so capture and watch do not share a label. The
  indicator is a **separate, persistent dot** labelled "watching". It
  appears only on `watch.state=watching`, and it is absent in every other
  state.
- **The indicator is the precondition, not decoration.** The supervisor
  starts the watcher only after the overlay has acknowledged a
  `watch.state=arming` message. If the overlay's socket closes, the
  supervisor stops with `overlay-gone`. A watcher that is running with no
  overlay connected is therefore not reachable. This is what "a watcher that
  hides itself is a fail" requires in event-driven form.

### 4.5 State machine

```
OFF ──arm (resume + overlay ack)──► ARMING ──full resync ok──► WATCHING
 ▲                                    │                          │
 │                                    └─fail──► DARK ◄──────────┤ bus death / child crash
 │                                                               │
 └──────── stop(reason) ◄── PAUSED(halt|showoff|posture|lock|overlay-gone)
```

- **DARK** = the child is gone or the bus is gone. The tree is cleared. The
  indicator is off. Reconnect runs with backoff (1 s, 2 s, 4 s … capped at
  60 s), and each attempt is journalled as a count, not a per-attempt line.
  On success, the supervisor returns to ARMING and requires a full resync
  before WATCHING.
- Every transition is journalled as `watch.state <from>→<to> reason=<code>`
  (state and reason only).

### 4.6 Resync

A full resync walks every visible window on the focused output plus the
N most recently focused windows, up to the caps in §8.3. It runs inside
ARMING. The indicator stays off until it completes or times out.

---

## 5. Data model and staleness

### 5.1 Records (RAM only, never serialised to disk)

```
Window {
  key:        str        # hypr address + pid, not an AT-SPI path
  pid:        int
  app:        str        # AT-SPI app name, ≤ 64 chars, sensitive-filtered
  title:      str        # ≤ 64 chars, sensitive-filtered; else "" (§6.5)
  rect:       (x,y,w,h)  # screen coords, from Hyprland, revalidated (§5.3)
  output:     str        # Hyprland monitor name
  workspace:  int
  visible:    bool       # on a visible workspace of its output
  focus_rank: int        # Hyprland focusHistoryID (a hint, §7.1)
  seq:        int        # last applied delta sequence number
  synced_at:  float      # monotonic seconds, last successful sync OR revalidation
  state:      live | stale | dark
}
Node {
  window: key ; parent: int|None ; role: str ; rect: (x,y,w,h)
  name: str | None     # None for tombstones and for non-allowlisted content (§6.4)
  kind: element | tombstone
  sensitive: bool      # True for tombstones and any SECRET-name hit
}
```

Caps (proposals, measured in §10): ≤ 128 windows, ≤ 256 nodes per
window, ≤ 20 000 nodes total, names ≤ 64 characters. The current helper
allows 256 characters (`L157`). The 64 cap is a tightening.

### 5.2 Staleness bound X — proposal: **2.0 s, measured at draw time**

**Rule.** A ring is drawn from a window's nodes only if
`now − synced_at ≤ X`, where `now` is read **immediately before** `draw()`.
Otherwise the watcher must first perform a single-window revalidation (§5.3).
If that fails, the answer is "I can't confirm it's still there" with no ring.

**Why draw time, not capture time.** `[OBS]` The screenshot path can wait up
to 12 s (`_screenshot` → portal helper's 12 s wait, plus the 20 s subprocess timeout
in `observation.py` L215). The tree read in `capture()` can therefore
be far older than the pixels by the time a ring is placed. A check at
capture time would miss this.

**Why silence is not currency.** `[INF]` AT-SPI does not guarantee an event
for every compositor-driven move or resize. An event-quiet window is not
therefore an unchanged window. The age bound, not the event stream, is what
limits a misplaced ring.

**Why 2.0 s.**

- Event-driven updates land in well under a second in the common case
  `[INF]`, so a 2 s bound is almost never hit in normal use.
- When it is hit, one revalidation is one bounded call (≤ 150 ms, one
  window). The bound is therefore cheap to keep tight.
- **Sensitivity.** X = 1 s causes more revalidations, which are cheap. X = 5 s
  lets a ring sit on a moved window for up to five seconds. A misplaced
  ring over a control the user might click is the harm, so 2 s is the upper
  limit I would accept.

### 5.3 Revalidation (single window, bounded)

1. Re-read the window's extents (Component interface, WINDOW and SCREEN
   coords, using the existing dual-path acceptance from `atspi()` L100–110).
2. Compare with the Hyprland `rect` (tolerance 8 px, as in `atspi()`).
3. If equal, set `synced_at = now` and proceed. If not, mark the window
   `stale` and re-walk only that window's subtree.
4. Hard timeout 150 ms. Timeout → `stale`, journal `watch.reval/timeout`.

---

## 6. Sensitive filter at ingestion (rail 1)

### 6.1 Principle

The **role** is decided before any **property** is read. A property the
design never reads cannot be stored. Three categories:

| Category | Examples `[DOC]` | What is read | What is stored |
|---|---|---|---|
| **Sensitive role** | `PASSWORD_TEXT` | role, extents, state only | tombstone: role, rect, window key |
| **Sensitive-name hit** | any role whose name matches `SECRET` | role, extents, name (to test it) | tombstone. The name is dropped right after the test. |
| **Content / control** | button, label, text, entry, menu item … | role, extents, name (≤ 64 chars) | element with name, unless the name is a SECRET hit |

Never read, in any category: `Text`/`EditableText` contents, `Value`,
`get_description`, selection, or any event payload carrying text.

### 6.2 Proof that a password field's **existence** can be known while its **identity and value** can never be stored

Claim: the stored record for a password field has no field that can hold its
name or its value, and the code path never requests them.

1. **Type.** The password record is `Tombstone(window: str, rect: Rect,
   role: Literal['password text'])`. It has no `name` or `value`
   attribute. A type checker and a unit test both enforce this.
2. **Code path.** The ingest function (sketch, not code) is
   ```python
   def ingest(node, window):
       role = node.get_role()                 # first
       if role == PASSWORD_TEXT:
           return Tombstone(window, extents(node), 'password text')  # return
       name = node.get_name()[:64]            # reached only for non-password roles
       ...
   ```
   `get_name()` is unreachable for `PASSWORD_TEXT`, and no other property
   of that node is called.
3. **Existence is still known.** The tombstone holds the rect and role, so
   `ground()`'s existing overlap rule (`observation.py` L153, the
   sensitive-intersect check) still refuses any ring over that field.
   Queries such as "where is the password field" can return the sensitive
   refusal from the tombstone alone.
4. **Evidence obligations.** The canary test in §3 (rail 1) must pass.
   Journal lines contain only `kind=tombstone role=password text`. A
   tombstone is never spoken with a name.

### 6.3 Fix the one-shot helper now (WATCH-BUILD-1, independent of watching)

`_observation_linux.py` L157–158 reads the name and carries it for
password nodes. The rule above applies to the one-shot path as well:
`PASSWORD_TEXT` must short-circuit before `get_name()`. This does not need
the watcher. It is a rail-1 defect in today's code.

### 6.4 What the filter cannot prove (residual risk, owner decision D1)

- **Displayed secrets in labels.** A label whose text is a secret (for
  example a password manager showing a password as a `label`) has no
  password role and may not match `SECRET`. The name is stored, within the
  64-character cap, and RAM-only. **The design cannot prove the tree is
  incapable of holding arbitrary displayed text**, and no AT-SPI-only design
  can. `[INF]`
- **Unlabelled password fields** exposed by a toolkit as a plain `entry`
  with a non-matching name. The `PASSWORD_TEXT` role will not fire. The
  design depends on toolkits exposing the role correctly. `[GAP]`
- **Mitigations available.** (a) Geometry-only for non-control text roles,
  which breaks HW2B's contained-label collapse (`semantic_target`, L158).
  (b) A keyed hash of names for matching. Rejected for v1: the key lives in
  the same RAM, so it defeats only accidental serialisation, not a memory
  read.
- **Recommendation.** Accept (a) as the default for `label`/`static`/
  `paragraph`/`terminal`/`document` roles, keeping names only for
  control roles and the HW2B contained-label case. This narrows the risk
  without breaking pointing. Owner decides (D1).

### 6.5 Window titles

Titles are needed for spoken disambiguation (§7.1). They are filtered with
the same `SECRET` pattern and capped at 64 characters. On a hit, the title
is dropped and the window is spoken as "the second Files window" (app name
plus ordinal).

---

## 7. Grounding when the tree is live

### 7.1 Window identity and cross-window search

- `semantic_target(frame, name)` keeps its signature. It searches every
  **visible-on-focused-output** window's nodes.
- **One match** across all windows → resolved, as today.
- **Matches in >1 window** → return `{'kind': 'clarify', 'candidates': [...]}`
  with window identities only (app, filtered title, ordinal). **No ring, no
  click.** The reply is then spoken: "Cancel in Files, or Cancel in
  Settings?"
- The user's answer selects a window key. That key then drives a
  window-scoped `semantic_target(frame, name, window=key)`, which runs the
  existing HW2B same-window rules.
- **Focus is a hint, not a gate.** Focus only orders the candidate list
  (`focus_rank`, §5.1). It never auto-resolves a cross-window ambiguity.
  A single match is found whether or not its window has focus, which
  satisfies "no focus-first requirement".
- Within one window, the HW2B duplicate rules are unchanged.

### 7.2 Replace the ACTIVE gate

`atspi()` rejects every window that is not `ACTIVE` (L93–94). That gate
is the focus gate the owner ruling removes. In the live design a window is
eligible when:

- its Hyprland `visible` is true (a visible workspace on the focused
  output, which is where the screenshot is taken), **and**
- AT-SPI reports the window `SHOWING` (not `ACTIVE`).

Windows on other outputs are **identity-only** (D5). The answer is "it's in
Files on the other monitor. I can only point on this screen."

### 7.3 Occlusion (a gap the current code does not handle)

AT-SPI reports nodes under a window that is covered by another window as
still `SHOWING`. A ring could therefore point at a button hidden behind
another window. `[INF]` The one-shot path has the same gap today, but it
is limited to one window.

Proposal: refuse a ring whose rect intersects a **more recently focused**
window's rect (`focus_rank` lower than the target's) on the same output. The
ring is then suppressed with "it might be behind another window". This is a
conservative approximation of z-order. Hyprland's focus history is the only
ordering available to us `[DOC]`. Tiled windows rarely overlap, so the cost
is small. The approximation is an open question (§12).

### 7.4 `ground()` and `draw()`

- `ground()` keeps its contract: it binds `frame_id`/`snapshot_id`, refuses
  sensitive or sensitive-overlapping rects, caps area at 25 %, and checks
  the output bounds. The occlusion check (§7.3) and the draw-time age check
  (§5.2) are added in the caller or as one extra guard before `draw()`.
- `Frame` is still an immutable per-ask materialisation. The live store is
  a **source**, not an authority. A target's `frame_id`/`snapshot_id` binds
  it to that materialisation, so a stale target cannot be replayed against a
  newer frame.

### 7.5 IF-6

Window titles and element names are untrusted data (`intents.py` L15, L44).
They are spoken only through fixed templates with length caps. A title
never becomes an instruction and never reaches a prompt.

---

## 8. Failure modes

| # | Failure | Detection | Behaviour (fail silent and dark) |
|---|---|---|---|
| 8.1 | **a11y bus death** (AT-SPI registry gone) | child reports bus error, or the child exits | DARK. Clear RAM. Indicator off. Backoff reconnect; full resync required before WATCHING. Journal the count, not per-attempt lines. |
| 8.2 | **App crashes mid-tree** (dead node refs) | GLib/AT-SPI error on a node call | Drop that app's whole subtree (never a partial tree, the same rule as `atspi()`'s `escaped` path L154–162). Journal `watch.app/dropped` with the count. |
| 8.3 | **500-window stress** | window count over cap | Track up to 128 windows: visible-on-focused-output first, then most recently focused. Others are identity-only or untracked. Journal `watch.overflow` count. Node cap 20 000 total. |
| 8.4 | **Event floods** (terminal output, progress bars, video) | per-window token bucket: 50 events/s; global 300/s | Coalesce per window, 200 ms debounce, one re-walk per window per debounce. Sustained >5 s → window `stale` (frozen). Journal `watch.flood` count. Never spin. |
| 8.5 | **Hyprland IPC death** | socket2 EOF | DARK (window identity lost, so grounding cannot be trusted). Reconnect with backoff. |
| 8.6 | **Overlay gone** | overlay socket EOF | PAUSED (`overlay-gone`) (§4.4). |
| 8.7 | **Child crash / GI segfault** | child exit | DARK. The child is dumpable only if core dumps are off. Set `RLIMIT_CORE=0` and `PR_SET_DUMPABLE=0` in the child, so a core dump cannot write names to disk. |
| 8.8 | **Daemon crash** | child loses its stdout reader | Child exits on broken pipe. RAM dies with the process. |
| 8.9 | **Stale tree at ask time** | `synced_at` age check (§5.2) | Revalidate once. Failure → "I can't confirm it's still there". |
| 8.10 | **Swap / hibernate** | RAM can be paged out `[INF]` | D3: attempt `mlock` on the store arena; if refused, journal a warning and surface it in `assist doctor`. Hibernation writes RAM to disk, so the owner should be told this in the eye-check (§11). |

Every failure path journals **metadata only**: state, reason code, counts.
A test asserts that no journal line contains a node name from the canary set.

---

## 9. API budget declaration

**Declared: zero cloud API calls for watching and for element grounding.**

Proof by enumeration of the design's call graph:

| Component | Network | Provider |
|---|---|---|
| Child watcher (`_observation_linux.py watch`) | none. AT-SPI and Hyprland IPC are local sockets. | none |
| `WatchStore`, `WatchSupervisor` | none | none |
| `semantic_target`, `ground`, `draw` | none (pure) | none |
| `_resolve_atspi` | none | none |
| VLM grounding fallback | **unchanged, OFF by default** (`[quota.grounding] enabled = false`, as in HW2B). Ask-time only, budgeted diverted role. Receives **query text and PNG only**. | only if the owner enables it |

Enforcement (proposed, §3 rail 4 and §10):

- **Static.** An import test asserts the watcher modules do not import
  `gemini_client`, `live_client`, the router, or any HTTP client.
- **Static.** The `GroundingRequest` construction (`nus_pointer.py` L1195) is
  asserted to carry no `frame.elements` or `Element.name`.
- **Runtime.** Owner check: `llm_calls` (the store table named in
  `journal_log.py` header) shows a zero delta over 30 min of watching plus
  five element-grounded asks (§11).

---

## 10. Resource measurement plan (owner hardware)

The owner's laptop model, RAM, and CPU are not recorded in the repo `[GAP]`.
The first measurement run records them, with `/proc/cpuinfo`, `free -m`,
`uname -a`, and `hyprctl version`.

**Metrics** (all from `/proc`, no extra tools):

- CPU %: `utime+stime` delta from `/proc/<pid>/stat` over 60 s, for the
  child and the daemon separately.
- Memory: `VmRSS`, `VmHWM` from `/proc/<pid>/status`.
- Wakeups: `voluntary_ctxt_switches` delta per second. Idle wakeups should be
  near zero beyond events. This is the event-driven proof.
- Sockets: `ls -l /proc/<pid>/fd` and `/proc/<pid>/net/tcp`. The watcher
  must hold **no TCP** sockets.

**Scenarios**, each ≥ 10 min unless stated:

| ID | Scenario | Proposed budget |
|---|---|---|
| S1 | Idle, 30 min, one editor open | child CPU average ≤ 0.5 % of one core; RSS ≤ 64 MB |
| S2 | Typing in an editor | no extra CPU beyond S1 (text events are not subscribed) |
| S3 | Browser scrolling | ≤ 5 % sustained; coalescing engages (`watch.flood` count visible) |
| S4 | Terminal output flood (`yes` piped to `head -n 200000`) | flood cap engages; window goes `stale` after 5 s; no spin |
| S5 | 100 windows, then 500 windows (zenity loop) | caps engage; RSS ≤ 128 MB; node count ≤ 20 000 |
| S6 | Halt trigger → tree cleared | ≤ 500 ms |

These are **proposals to be measured**, not results. The budgets are
falsifiable: if they fail, the design changes.

---

## 11. Owner eye-check script

Record hardware first. Use only the empty throwaway prompts from HW2B.
**Never type a real credential.**

0. Record `uname -a`, `hyprctl version`, `free -m`, and CPU model.
1. Turn watching on through the existing resume path. Confirm the
   **watching** dot is visible. `assist watch status` (proposed) reports
   `watching`.
2. Open two windows, each with a Cancel button:
   `zenity --question --title='Elaria WATCH A' --text='A' --ok-label=OK --cancel-label=Cancel`
   and the same with `WATCH B`. Then ask: `assist ask 'where is the Cancel button'`.
   **Expected:** a question naming both windows. No ring, no click.
3. Answer "the one in A". **Expected:** a ring on A's Cancel only. Neither
   window closes. No click.
4. Password check: `zenity --password --title='Elaria WATCH sensitive'`
   (leave empty). Ask: `assist ask 'where is the password field'`.
   **Expected:** the sensitive refusal, no ring.
   Then `journalctl --user -u assistant.service --since '5 minutes ago' | grep -i watch`.
   **Expected:** tombstone and count lines only. No field name. No value.
5. **Halt:** press SUPER+SHIFT+F12. **Expected:** the dot disappears within
   about 1 s. `assist watch status` → `off`.
6. **Resume** through the existing path. The dot returns only after resync.
7. **Lock:** `loginctl lock-session`. **Expected:** the dot is off while
   locked. Unlock, and the dot returns only after resync.
8. **Bus death:** restart the AT-SPI registry (`systemctl --user restart at-spi-dbus-bus.service`, name `[GAP]`; use whatever the owner's session
   uses). **Expected:** the dot goes off. It returns only after a full resync.
9. **Showoff:** enter showoff. **Expected:** the dot is off.
10. **Zero API:** note the `llm_calls` row count. Watch for 10 min and make
    five element-grounded asks. **Expected:** no change in the count.
11. **Stress:** open 100 zenity windows in a loop, then close them. Check the
    overflow count in the journal and the RSS.
12. Report the numbers from §10 and the journal lines. Only the owner's
    result closes this check.

---

## 12. Open questions and gaps `[GAP]`

1. **Hyprland 0.57 socket2 event names** and `hyprctl clients -j` fields
   (`focusHistoryID`, `visible`, `pid`). `[DOC]`, not run here.
2. **Which toolkits expose `PASSWORD_TEXT`** on the owner's apps.
3. **Occlusion approximation** (§7.3): is focus history good enough, or do we
   need a z-order source?
4. **"company mode"** (D4) does not exist in the repo.
5. **Swap/hibernation** policy (D3).
6. **logind lock reliability:** does the owner's locker call `Lock` on the
   session, or does it need an explicit `loginctl lock-session` hook?
7. **Build order.** WATCH-BUILD-1: rail-1 fix to the one-shot helper (§6.3).
   WATCH-BUILD-2: ingestion filter and tests. WATCH-BUILD-3: the child
   watcher with NDJSON. WATCH-BUILD-4: supervisor, states, and the overlay
   indicator. WATCH-BUILD-5: multi-window grounding and clarification.
   WATCH-BUILD-6: owner measurement and eye-check. Each build needs its own
   dispatch.
8. **Not verified in this sandbox:** every runtime behaviour in §4–§8. The
   sandbox has no compositor, bus, or hardware.

---

## 13. Files and paths

**This report only.** No source, test, config, or `OWNERS.yaml` file is
changed.

Read during this design (all `[OBS]`):
`reports/DISPATCH-WATCH.md`, `src/assistant/observation.py`,
`src/assistant/_observation_linux.py`, `src/assistant/nus_pointer.py`
(L590–660, L766–810, L1195–1203, L1390–1420), `src/assistant/disclosure.py`
(L31–60), `src/assistant/daemon.py` (L552–575, L1219–1221, L1300–1345,
L1625–1645), `src/assistant/safety.py` (L290–310), `src/assistant/hypr_binds.py`
(L1–60), `src/assistant/showoff.py` (L193, L384, L460),
`src/assistant/nus_surface.py` (L30–95), `src/assistant/capture.py`
(L418–440), `src/assistant/journal_log.py` (L1–40, L85), `src/assistant/intents.py`
(L15–80), `src/assistant/modes.py` (header), `src/assistant/presence.py`
(L1–60), `src/assistant/cli.py` (L2780–2800), `tests/test_bug_hw2_atspi.py`
(names only), `reports/RPT-H-FIX-HW2B-20261127.md`,
`reports/HARDWARE-PASS-20261126.md`, `reports/RPT-H-nus-pointer-blueprint-20261125T113441Z.md`.
