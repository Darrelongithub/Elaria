# Observability readers — the rung ladder

Elaria's diagnostics answer questions in **one direction, cheapest first**. Each
rung is only worth climbing when the rung above it came back empty *and* you can
say what that emptiness failed to discriminate.

```
doctor  →  reader  →  journal
```

| Rung | What it is | Cost | Answers | Fails to answer |
|---|---|---|---|---|
| **doctor** | `assist doctor` — the existing checks in `cli.py` | seconds, no daemon needed | is the tool there, is the node listed, is there a live level | *why* a past take looked wrong |
| **reader** | the scripts below, against the durable store | one read, `mode=ro` | what the limiter saw, which node capture would open, what the player actually did | anything about a session that never reached the store |
| **journal** | `journalctl --user -u assistant` | free | ordering and stderr around a moment | **nothing on its own** — see the warning below |

## The scripts

| Script | Question | Positive control | Negative control |
|---|---|---|---|
| `scripts/limiter_readings.py` | did the capture limiter actually touch the input? | a row with `processed < raw` **and** `limited_samples > 0` reads `limiter_effective 1` | a row with counters present but nothing limited reads `0`; a row with **no** counters reads **`-1` (not measured)** |
| `scripts/capture_source_check.py` | which node would capture open, and at what volume? | a named Mic1 node reads `node <name>`, `node_is_monitor 0`, a real `volume_percent` | an unset `mic_target` reads `fallback_to_default 1` (`--policy as-built`) or `refusal f17_no_node` (`--policy f17`) |
| `scripts/player_probe.py` | did that wav produce sound, and if not, why? | a player that runs for the audio's own duration reads `played` | exit 0 returning instantly reads `exit_zero_no_output`; a non-zero exit carries the first stderr line verbatim |
| `scripts/daemon_identity.py` | is the **running** daemon the code in this checkout? (ask 43) | matching commit + no source file newer than the daemon's start reads `match` | a source file newer than the daemon's start reads `stale_checkout`; no daemon reads `daemon_down` with `stale_source_files -1` |

Every script prints `key value` lines, ends with `note read_only`, and states
`fails_to_discriminate` when it has nothing: a reader that returns silence
without saying what that silence cannot rule out is a guess in a lab coat.

## `limiter_effective` is three-valued on purpose

| Value | Meaning | What you may claim |
|---|---|---|
| `1` | processed peak below raw peak, and samples were limited | the limiter is wired **and** it fired on this audio |
| `0` | both peaks measured, nothing was limited | the limiter was measured and had nothing to do — the input was under the knee |
| `-1` | the row carries no limiter counters | **nothing.** The instrument is missing |

`-1` is the common case on a tree whose `transcribe.py` does not emit
`raw_peak` / `processed_peak` / `limited_samples`. Folding it into `0` would
report "the limiter did not fire" about audio nobody measured, which is exactly
the silence-as-proof-of-absence mistake this ladder exists to prevent.

## Why the journal is the last rung, not the first

An empty `journalctl | grep capture.levels` **discriminates nothing**. A stale
daemon binary, a second unit, log rotation and "no session ran on this unit" all
produce the same empty output. The store cannot be stale in that way: a dictation
writes its `capture.stats` row on the way out, so the *reader* is the honest rung
and the journal is context around it.

## `player_probe.py` — exit 0 is not evidence of sound

`paplay` exits 0 after handing samples to a sink nobody is listening to (wrong
sink, suspended, muted, null sink). The probe therefore separates the process's
own verdict (`exit_code`, `stderr_first`) from the observable fact (`first_byte_ms`,
`first_byte_hex`, `wav_peak`), and `--telemetry` reads the daemon's own ack rows
to report the played / none-played split as numbers.

**This is a diagnostic, not a fix.** The none-played cause is parked with the
owner (ask 45 / decision 29); nothing here changes playback.

## `daemon_identity.py` — `version` cannot answer ask 43

`status` reports `"version": __version__`, and `__version__` is the hand-edited
literal `"0.0.1"` in `src/assistant/__init__.py`. It has been that string for
every commit in this tree, so **two different checkouts report the same version**.
The probe prints `version_alone_discriminates 0` on every run so the field can
never imply a match it did not test.

What does discriminate, cheapest first:

| Rung | Evidence | Cost |
|---|---|---|
| 1 | any `src/assistant/*.py` newer than the daemon's start (`uptime_s` vs `stat`) | no git, no network, no write |
| 2 | `/proc/<pid>/cwd` and `cmdline` — which directory the process really runs from | read-only |
| 3 | `git -C <dir> rev-parse HEAD` — the only real revision evidence | needs git + a real checkout |

The pid is **proved, not guessed**: the socket's kernel inode comes from
`/proc/net/unix`, then `/proc/*/fd` is searched for `socket:[<inode>]`. Matching a
process by name breaks the moment two daemons run under different
`XDG_RUNTIME_DIR`s. (`os.stat().st_ino` is *not* used — that is the filesystem
node's inode, a different number from the socket inode, and it can never match.)

Verdicts: `match` · `stale_checkout` · `different_checkout` · `dirty_checkout` ·
`revision_unknown` · `daemon_down`. With no daemon, `stale_source_files` is **-1
(never compared)**, not `0` — the same anti-vacuity rule as the limiter reader.
The reader never signals or restarts a process; it prints
`note restart_is_the_owners_call`.

## Pinning

Each reader has a `.sha256` sibling recording its digest under its
repository-relative path:

```sh
sha256sum -c scripts/limiter_readings.py.sha256
sha256sum -c scripts/capture_source_check.py.sha256
sha256sum -c scripts/player_probe.py.sha256
sha256sum -c scripts/daemon_identity.py.sha256
```

Regenerate after any edit with `python3 scripts/<name> --checksum`. A test fails
if a script and its manifest disagree, so a pinned script cannot drift silently.
