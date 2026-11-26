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
| BUG-C1 | `reach/egress.py` | robots.txt 3xx treated as "no rules" → fetch proceeds against a redirected `Disallow:` (fail-open) | OPEN |
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
S-C1 unprovisioned WhatsApp verify-token sentinel · S-C2 phone
`device=` override vs configured-device binding · S-C3 REACH DNS
rebinding window (validation vs connect-time resolve) · S-C4
alive receipt bookkeeping gap · S-C5 backup purge target when
`trashed_as` missing. Rule on S-C1/S-C2 when fixing the C lane.

## Hardware-found (owner laptop, 2026-11-26 — first real-hardware entries)

| ID | Where | Failure | Status |
|---|---|---|---|
| BUG-HW1 | `capture.py` (`PipeWireCapture` / `pw_record_pcm_stream_command`) | Daemon-captured audio is explosive static on owner hardware while manual `pw-record` from the SAME node (`--rate 16000 --channels 1`, WAV) is clean. Daemon path: `pw-record --target=<node.name> --rate 16000 --channels 1 --format s16 -` raw PCM via stdout. Evidence (owner's machine, files kept): `~/.local/share/assistant/audio/20261126-165648-0f964a.wav` (raw_peak 1.0, 4.6% limited, ASR empty on all backends) and `20261126-171509-974193.wav` (owner: "mad explosion, static"); clean control: owner's `/tmp/same-node.wav`. Secondary symptom: repeated 0-byte captures (first-frame latency ~1.5s). Suspects: stream format/rate actually delivered vs assumed s16le-16k-mono, stdout pipe framing, target resolution, processing before WavSink. Thresholds are NOT suspects and stay frozen. **Differential closed 2026-11-26 (owner A/B):** probe shows capture resolves to the same default Mic1 node at 84% (target resolution acquitted); `pw-record --rate 16000 --channels 1 --format s16 file.wav` CLEAN; the daemon's exact raw-stdout form (`--format s16 -`) EXPLODES on playback as s16/16k. The raw stdout stream's format/rate does not match its label on this hardware (byte-count of owner `/tmp/raw.pcm` pending: ~160KB/5s = samples corrupt; ~480KB = 48k s16; ~320KB = 16k s32; ~960KB = 48k float). **ROOT CAUSE 2026-11-26 (Agent J, FIX-HW1 — `RPT-J-BUGFIX-HW1-20261126.md`):** `-` without `--raw` is NOT raw PCM — pw-cat opens it via libsndfile (`sf_open("-", …)` → stdio) and `format_from_filename()` maps `-` to the **AU container**: 24-byte `.snd` header + **big-endian** PCM16 (upstream `pw-cat.c` 1.4.6 & master, `sndfile.c`). The daemon read it as s16le: byte-swap static (×256 gain with wraparound), and the header is the 2026-11-15 "start pop" (rate field reads as sample −32706 = peak 0.9981, survives node mute). Pending byte count predicts 160024/5s + `.snd` magic (the "samples corrupt" row). Fix: argv gains `--raw` (true raw s16le; old builds fail closed), container-header tripwire refuses mislabelled streams (`capture.format_mismatch`), `capture.stream_open` journals argv + `pw-dump` negotiated facts, 0-byte captures journal `capture.starved`; sandbox harness proves the AU form reproduces every evidence fact (`test_bug_hw1_*`). Owner paste-backs (byte count, evidence-WAV header words, `--raw` A/B) in the report §7. | FIXED (PR #TBD, `test_bug_hw1_*`) |

## Hunt scoreboard

30 reproduced bugs (5 P0 · 19 P1 · 6 P2… see tables) + 13
suspects, zero found in: WhatsApp 24h-window gate, atomic template
cap, phone verb allowlist, rclone command surface. Hunters: A core,
B embodied, C edges — all read-only, no fixes in-hunt.
