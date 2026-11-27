# bugs.md — Elaria bug ledger

Consolidated by the manager from the 2026-11-26 three-hunter hunt
(`reports/BUGHUNT-A-20261126.md`, `BUGHUNT-B-20261126.md`,
`BUGHUNT-C-20261126.md`). Every entry was reproduced by its hunter
in sandbox; P0s were additionally spot-verified by the manager in
code. Fixes land as separate PRs, each with a regression test named
after the bug ID. Status: OPEN · FIX-IN-FLIGHT · FIXED (PR#).

## P0 — safety / authority / permanent-memory integrity

| ID | Where | Failure | Status |
|---|---|---|---|
| BUG-B1 | `hands/gate.py` | Forbidden tier-3 commands (`curl --data=@…`, wrapper shells, relative shebangs, `rm --recursive=always`) classified tier 2 (askable) | FIX-IN-FLIGHT (Agent O, FIX-B1) |
| BUG-B2 | `hands/queue.py`, `hands/runner.py` | Tier-3 mouse digest replays under a fresh errand ID; 12-click budget resets per errand; `bool` accepted as click count; no `queue.current` check | FIX-IN-FLIGHT (Agent O, FIX-B2) |
| BUG-B3 | `hands/headless/worker.py` | Workers tracked only after exit: daemon death signals 0 live processes; `terminate_all` can hit recycled PIDs; masking tests | **FIXED** (PR #149, `test_bug_b3_*`) |
| BUG-A1 | `errand.py`, `memory.py` | Unrelated/conflicting inferred facts promoted to `source='stated'` conf=1.0 by gap/conflict answers; `skill_memory_infer` bypasses tombstones — owner-rejected facts resurrect | **FIXED** (PR #159, `test_bug_a1_*`) |
| BUG-A2 | `daemon.py`, `errand.py` | `fs.locate`/`file.inspect`/`file.read` IPC bypass `[discovery]` roots, `_require_ipc_owner()`, and showoff lockdown (private files readable during show-off) | **FIXED** (PR #159, `test_bug_a2_*`) |

## P1 — wrong behaviour on a real path

| ID | Where | Failure | Status |
|---|---|---|---|
| BUG-A3 | `provider_router.py`, `daemon.py` | Router instances overwrite each other's quota state; `material()` skips 429 cooldowns; `personality()` leaks reservations; `assist cost` wrong at cap exhaustion | OPEN |
| BUG-A4 | `config.py`, `cost.py`, `provider_router.py` | TOML `inf`/`nan` crashes validation and grants unlimited provider quota (`rpd=inf`) | OPEN |
| BUG-A5 | `memory.py` | `recall()` suppresses unrelated inferred facts sharing one query word; `forget()` leaves namespace rows active | OPEN |
| BUG-A6 | `errand.py` | Structured/batch reads bypass `max_read_bytes`; `content.analyze` bypasses ProviderRouter + deadline; no in-flight step timeout | OPEN |
| BUG-A7 | `errand.py` | Pause/resume/cancel + restart lifecycle strands errands; failed errands can still promote facts | OPEN |
| BUG-A8 | `gemini_client.py`, `config.py` | SDK batch transcription/`generate_voice()` bypass daily cap (mock-masked); verification/runtime files created world-readable (I5) | OPEN |
| BUG-A9 | `intents.py` | `honest_claims()` passes false claims containing "no/can't"; "Remember …?" questions misrouted to permanent writes | OPEN |
| BUG-B4 | `hands/runner.py` | Post-click verification passes on stale frames; loop detection misses period ≥4 loops | FIX-IN-FLIGHT (with FIX-B2) |
| BUG-B5 | `_observation_linux.py`, `observation.py`, `hands/runner.py` | Sensitive-target refusal evaded by renamed labels ("CVC", "Verification code"…); prompt/click budget burned before sensitivity check | OPEN |
| BUG-B6 | `nus_pointer.py`, `hands/runner.py`, `daemon.py` | AT-SPI labels never injection-screened, echo into prompts/history; sensitive overlap falls to VLM with wiped pixels | OPEN |
| BUG-B7 | `hands/headless/*` | Consent journals AFTER acting (I6); danger verbs dropped unlogged; watcher skipped without daemon_pid; `~` unexpanded in runtime_dir | OPEN |
| BUG-B8 | `daemon.py`, `wake_guard.py` | Half-duplex/show-off/class-mode drops strand WakeGuard in ATTENDING (hotword deadlocked); 80 KB room audio retained unzeroed | OPEN |
| BUG-B9 | `disclosure.py`, `daemon.py` | `detect_company_command()` fails open on conditional/negated sentences; `leak_in()` misses 3-digit CVV/seed phrases; `nus.point` bypasses showoff+disclosure | OPEN |
| BUG-B10 | `voicetest.py`, `voiceprint.py`, `wake_guard.py` | Voice test FAILS OPEN when speaker score is None; external scorer bypasses missing enrollment; `.onnx` loaders lack SHA pins (I2), swallow corrupt models | OPEN |
| BUG-C1 | `reach/egress.py` | robots.txt 3xx treated as "no rules" → fetch proceeds against a redirected `Disallow:` (fail-open) | FIXED in [REACH-WIRE](reports/RPT-REACH-WIRE.md) (fixture-tested) |
| BUG-C2 | `alive_sync.py`, `alive/envelope.py` | Signed envelopes deduped by filename, not envelope ID — rename-copy replays an instruction into `awaiting_approval` | OPEN |
| BUG-C3 | `alive/webhook.py`, `heartbeat.py` | Monthly WhatsApp service-message cap counts only stranger turns; owner acks uncounted (runbook invariant unenforced) | OPEN |
| BUG-C4 | `backup.py` | `flipped→trashed` trim never re-verifies remote hash — vanished remote copy still trimmed (CLI shields; module contract doesn't) | OPEN |

## P2 — edge-case wrong

| ID | Where | Failure | Status |
|---|---|---|---|
| BUG-A10 | `config.py` vs `nus_pointer.py` | `[nus_pointer] ttl_ms` read but absent from DEFAULTS/example → `validate_config()` fails | OPEN |
| BUG-A11 | `planner_llm.py` | Greedy `\[.*\]` regex discards valid JSON batches with trailing `]` text | OPEN |
| BUG-A12 | `provider_router.py`, `cost.py` | Personality calls ledgered `is_user_turn=False`, `cost_usd=0.0`; provider rpm/tpm/tpd caps parsed, never enforced | OPEN |
| BUG-B11 | `safety_journal.py`, `safety.py` | `JournalLog.verify()` overwrites duplicate action IDs; overwrite of dangling symlinks allowed | OPEN |
| BUG-B12 | `hands/core.py`, test AST check | AST safety test misses `from subprocess import …`/subpackages; single-step mismatches double-counted to halt | OPEN |
| BUG-C5 | `alive_sync.py` | Future-dated heartbeat = "awake" forever (negative age) | OPEN |
| BUG-C6 | `alive/mirror.py`, `concierge.py` | Free/busy answers count past-due commitments (also leaks coarse past counts to strangers) | OPEN |

## SUSPECTS (static only — needs ruling or hardware repro; not asserted)

S-A1..S-A4 (`BUGHUNT-A` §SUSPECTS) · S-B1..S-B4 (`BUGHUNT-B`) ·
S-C1 unprovisioned WhatsApp verify-token sentinel · ~~S-C2 phone
`device=` override vs configured-device binding~~ (**FIXED** in
PHONE-WIRE-2: `PhoneLink.send_approved` and `_call_plugin` refuse and
journal `phone.refused` locally before any IPC packet when explicit
`device=` differs from configured `self.device_id` or is empty; redone
cleanly, regression tests in `tests/test_p_phone_wire.py`) · S-C3 REACH
DNS rebinding window (validation vs connect-time resolve) · S-C4
alive receipt bookkeeping gap · S-C5 backup purge target when
`trashed_as` missing. Rule on S-C1 when fixing the C lane.

## Hardware-found (owner laptop, 2026-11-26 — first real-hardware entries)

| ID | Where | Failure | Status |
|---|---|---|---|
| BUG-HW1 | `capture.py` (`PipeWireCapture` / `pw_record_pcm_stream_command`) | Daemon-captured audio is explosive static on owner hardware while manual `pw-record` from the SAME node (`--rate 16000 --channels 1`, WAV) is clean. Daemon path: `pw-record --target=<node.name> --rate 16000 --channels 1 --format s16 -` raw PCM via stdout. Evidence (owner's machine, files kept): `~/.local/share/assistant/audio/20261126-165648-0f964a.wav` (raw_peak 1.0, 4.6% limited, ASR empty on all backends) and `20261126-171509-974193.wav` (owner: "mad explosion, static"); clean control: owner's `/tmp/same-node.wav`. Secondary symptom: repeated 0-byte captures (first-frame latency ~1.5s). Suspects: stream format/rate actually delivered vs assumed s16le-16k-mono, stdout pipe framing, target resolution, processing before WavSink. Thresholds are NOT suspects and stay frozen. **Differential closed 2026-11-26 (owner A/B):** probe shows capture resolves to the same default Mic1 node at 84% (target resolution acquitted); `pw-record --rate 16000 --channels 1 --format s16 file.wav` CLEAN; the daemon's exact raw-stdout form (`--format s16 -`) EXPLODES on playback as s16/16k. **Owner byte analysis of `/tmp/raw.pcm` (270,988 B):** as s16le — RMS 0.576, clip 0.004, zero-crossing 0.457 (static fingerprint; speech < 0.25); as f32le — garbage (max ~2e38), so NOT float. **ROOT CAUSE (Agent J, FIX-HW1 — `RPT-J-BUGFIX-HW1-20261126.md`):** `-` without `--raw` is NOT raw PCM — pw-cat opens it through libsndfile (`sf_open("-", …)` binds stdio) and `format_from_filename()` maps `-` to the **AU container**: a 24-byte `.snd` header plus **big-endian** PCM16 (upstream `pw-cat.c` 1.4.6 & master, `sndfile.c`; the sndfile-WAV path builds the same stream but writes little-endian WAV — hence clean). Byte-swapped samples read as s16le = ×256 gain with wraparound → the static fingerprint above (ZCR 0.457 also refutes the rate-mislabel reading: slowed speech keeps a speech zero-crossing), raw_peak 1.0, ASR empty. The AU header is the 2026-11-15 mute-test "start pop": the rate field reads as sample −32706 = peak 0.9981, written at stream open, immune to node mute. Byte count = 24 + the labelled count (270,988 B fits a ~8.47 s take at 16k s16 + 24; the first four bytes of `/tmp/raw.pcm` reading `.snd` is the owner-side confirmation). Fix (capture fidelity only): argv gains `--raw` (true raw s16le; builds without the flag fail closed), container-header tripwire refuses mislabelled streams (`capture.format_mismatch`), `capture.stream_open` journals argv + `pw-dump` negotiated facts, delivery-rate/dropped-tail facts journal in `stream_facts`, 0-byte captures journal `capture.starved`; sandbox harnesses (`test_bug_hw1_*`) prove the AU form reproduces every evidence fact. | **FIXED** (PR #165, `test_bug_hw1_*`) |

| ID | Where | Failure | Status |
|---|---|---|---|
| BUG-HW2 | `_observation_linux.py` (`atspi()`) + `observation.py` (`_elements`) | AT-SPI grounding always empty on owner hardware (Hyprland/Wayland): GTK reports window extents WINDOW-RELATIVE (owner evidence: zenity window `active=True`, extents `(0,0,300,166)`), helper rejects any window whose SCREEN extents differ from `hyprctl` bounds by >8px ("reject disagreements instead of offsetting") → every window rejected → `elements: []` → honest "I couldn't find it" for on-screen buttons. Portal screenshot proven healthy (rc=0, valid PNG); AT-SPI bus/registry healthy; capture() itself succeeds. Fix direction: accept the window when SIZE matches Hyprland's within tolerance and extents are window-relative (origin ~0,0), translating all element bounds by the Hyprland window origin; keep rejecting true disagreements (size mismatch, ambiguous windows). Fail-closed spirit preserved: no guessed coordinates. | Patched by FIX-HW2; expanded fail-closed/tolerance fixtures verified (113 related tests passing); owner hardware retest pending — see `reports/RPT-H-FIX-HW2-20261127.md` |

| ID | Where | Failure | Status |
|---|---|---|---|
| GAP-HW3 | `phone_link.py` (module) vs `daemon.py`/`cli.py` (absent) | Phone lane is module-complete but UNWIRED (found at hardware pass, 2026-11-27): `PhoneLink` is instantiated only in tests; the daemon never imports/instantiates it, no `[phone]` config section, no `assist phone` surface — the owner's SMS approve-each ruling (2026-11-26) has no live path to execute on. Same species as the PR #89 nus unplugged seam. Needs a wiring build (daemon owner-gated IPC + CLI + on-demand sidecar lifecycle per `docs/contracts/IF-3-OWNER-AMENDMENT.md`). | **FIXED** (PHONE-WIRE-2: `phone_service.py`, `phone_link.py`, `daemon.py`, `cli.py`, `config.py`, `tests/test_p_phone_wire.py`; owner hardware pass script in `reports/RPT-P-phone-wire-2.md`) |

| ID | Where | Failure | Status |
|---|---|---|---|
| BUG-HW2B | `_observation_linux.py` (descendant extents) + `observation.py` (`semantic_target`) | Residuals of the HW2 fix, proven on owner hardware 2026-11-27 (elements dump in session): (1) descendant `get_extents(SCREEN)` on GTK/Wayland returns `(0,0,w,h)` for every node — after window-origin translation all elements sit at the window's top-left; ring would point at the dialog corner for any target. Must use WINDOW-relative extents for descendants. (2) `semantic_target` counts a button and its contained label child as two ambiguous matches (`Cancel` button + `Cancel` label → `None` → "couldn't find it"); contained same-name label duplicates of an actionable element must collapse to it, while genuinely distinct same-name elements must still refuse. | FIXED (PR #174; owner hardware retest pending) |

| ID | Where | Failure | Status |
|---|---|---|---|
| GAP-HW4 | `reach/**` (module) vs daemon/CLI/errand (absent) | Internet fetcher unwired (found at hardware pass, 2026-11-27): no daemon IPC, no `assist reach`, no errand `web.fetch` skill imports `assistant.reach` outside its own package/tests. `[reach] enabled` currently enables nothing reachable. Needs a wiring build like PHONE-WIRE: owner-gated fetch entry points under the existing egress contract (allowlist, journal-first, terminal outcomes, IF-6 untrusted landing). | WIRED in [REACH-WIRE](reports/RPT-REACH-WIRE.md); owner hardware test pending |
| BUG-HW5 | `errand.py` (`_read_step_for`, step-error handling) + `cli.py` (errand status) | Proven on owner hardware 2026-11-27 (errand #3, `--root ~/Downloads`, 11,719 files): one unreadable file kills the whole errand. A PDF whose own inspection skeleton says "streaming this target will fail loudly" (`streamread.py:1175`) was still queued for `file.read`; the read raised `UnicodeDecodeError` on binary bytes and the exception aborted the errand at step 5/12 — remaining queued files never read, no grouping produced, status `failed`. Per GAP-3's own rule a per-file parse failure must be loud, named, counted — and NON-fatal: record it, continue the queue, finish with a report listing parse failures. Known non-streamable formats (PDF at minimum) should route inspect-only, never to the UTF-8 byte reader. Secondary wart (errand #1, same day): plain `assist errand status` prints only the COUNT of `unanswered_or_unasked` notes; the reason text ("no discovery roots configured") is visible only in `--json`. Plain status must print the reasons. | FIXED (PR #184; OWNER VERIFIED 2026-11-27 errand #4: PDF inspect-only `queue_read:false`, `.torrent` read failure named in plain status and non-fatal, reasons printed in words) |
| BUG-HW6 | `errand.py` (adaptive planning, budget reserve, report, `memory.infer` gating) | Composition quality failure, owner errand #4 (2026-11-27): FIX-HW5 held, but the errand still didn't deliver. (1) Step starvation: 12-step budget burned on inspect/read pairs (incl. metadata-only PDF inspections and a zip member duplicating a loose PDF, same digest) — `budget_exhausted` before any grouping could be presented; only 2 of 32 selected files read. (2) No deliverable: the report summary counts steps/files but never states the grouping the owner asked for. (3) Inference noise auto-stored: `memory.infer` stored 13 "inferred" facts from a survey ask — mostly content snippets mislabelled `kind=preference` ("Initialize Git is git init") — with zero clarifying questions and no owner confirmation prompt. A "tell me what's there" survey must not silently seed long-term memory, and snippet extraction is not grouping. | OPEN → FIX-HW6 |

| ID | Where | Failure | Status |
|---|---|---|---|
| BUG-HW7 | `provider_router.py` adapters vs every production `ProviderRouter(...)` construction | Diverted-provider adapters exist but are never wired (found 2026-11-27 during owner Groq enablement): `HttpMaterialAdapter` (groq/openrouter) and `CloudflareMaterialAdapter` are instantiated only in tests; all production routers (daemon, organiser, planner, reach, CLI `assist cost` ladder) are built with `adapters=()`. An owner-verified `[quota.providers.groq]` row + `ELARIA_GROQ_API_KEY` therefore still yields "diverted material providers: none" and any `material()` call would refuse "no code-registered adapter". Same species as GAP-HW3/HW4 (module-complete, production-unwired). Needs one code-owned router factory that registers the three material adapters everywhere; enablement stays gated by the verified row + env key at dispatch, never by registration. | OPEN → PROVIDER-ENABLE-1 (scope extended) |

## Hunt scoreboard

30 reproduced bugs (5 P0 · 19 P1 · 6 P2… see tables) + 13
suspects, zero found in: WhatsApp 24h-window gate, atomic template
cap, phone verb allowlist, rclone command surface. Hunters: A core,
B embodied, C edges — all read-only, no fixes in-hunt.
