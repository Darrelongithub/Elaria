# Platform collector owner packet — committed-file delivery, LOW PRIORITY

**TESTED-ONLY. Owner/design schedules this; no hardware time is requested now.**
**Kitty scene NOT READY.** The voice-chain work has priority. This packet implements the
conditional collector-delivery ruling; it does not declare compatibility or release the
scene. No adapter work or cross-lane changes are included.

## Standing rule and exact deliverable

Owner-run packets must be committed files, never executable shell reconstructed from
chat. The deliverable is `tools/kitty/owner_run_platform.py`. Its delivery commit is
reported with the checkpoint; its SHA256 is:

`8c9c1d62fa3d917344e9f5903f68cb3a6666c4434d2b975847bd82d92e025b14`

Size: **10846 bytes**. Python imports are stdlib-only. Invocation forms are recorded
inside the committed packet, not supplied as chat shell. The executable shebang uses
isolated Python with bytecode writing disabled; explicit invocation must likewise use
`-I -B`, as recorded in that file.

**Bootstrap is a separate trust step:** owner/design retrieves this exact packet from
its reported commit using their local Git-object mechanism, and independently compares
its SHA256 with the report **before Python executes**. The packet cannot authenticate
its own first execution. No certification of an unseen extraction script is implied.
If the file, commit or checksum cannot be verified, stop and report; do not reconstruct,
edit or repair the script from relay text. The previously issued drift packet remains
its specifically approved exception; future owner packets follow this committed-file rule.

## What it does

From any working directory, the packet reads a local source checkout (default
`HOME/Elaria`; `--repo` changes only that local path). It never changes branch, checks
out files, creates a worktree, fetches, installs, pushes, edits configuration or invokes
a shell. The owner's mainline tree stays on its voice-chain branch.

It creates a fresh private `HOME/kitty-platform-kit-*` directory and extracts the exact
five-file collector checkpoint from **a0e1aa8bba11e15ae6de9150b5a158a966acc2d6**, not from
HEAD, a moving branch or an API response. Each file must pass its exact byte count and
SHA256 **before its bytes are written**. All five on-disk files are rechecked before a
delivery receipt is written. An explicit run choice triggers another complete on-disk
verification immediately before handoff to the collector. There is no fallback pin,
source, executable, checksum override or repair path.

Only `collect_platform.py` executes. Tests and documents are provenance material, not
programs the packet runs. All five source files are intentionally unchanged from the
accepted checkpoint, including its historical build-only labels. The later conditional
owner-run ruling controls scheduling; those historical labels are not silently rewritten.

Default behavior is **prepare/verify only**. It does not run the collector or create its
evidence directory. An explicit `--run`, selected by the owner under the scheduling
ruling, hands off using the fixed system Python, isolated mode and no bytecode writes.
The collector is one standalone file: it has **no checkout or inventory dependency**
and runs from the temporary private kit. No branch switch or `.venv` is required.

## No silent Git network fallback

The fixed Git command uses `--no-lazy-fetch`, `--no-replace-objects`,
`--no-optional-locks`, `protocol.allow=never` and disabled fsmonitor before `cat-file blob`
with the exact source commit/path. Git's explicit **--no-lazy-fetch** option prevents
on-demand promisor-remote fetches in partial clones. The corresponding environment
variable is also set, but is not used as the only guard: older Git could ignore an
unknown environment variable. An unsupported command-line option instead **stops**.

The option's behavior was checked against Git v2.48.0 documentation and `git.c`; this
is source evidence, not the owner's installed Git measurement. The sandbox Git is
2.39.5; no supported-Git live packet run is claimed. Tests use fake Git processes.

Only a positive environment is passed to Git. HOME/XDG_CONFIG_HOME point to a fresh
`git-empty-home` inside the kit; global/system Git config is disabled. No inherited
Git injection variables, credentials, SSH agent socket or loader environment. Local
repository configuration/object storage is still read; this is **not an OS sandbox**
or protection against a compromised system Git binary. No hooks, textconv or filters
are requested. Existing source objects are required; absence/unsupported flags mean
stop and report, never retry without the no-fetch guard. There is no fetch command in
the packet and no request to the owner to fetch or change Git urgently.

Five Git calls have 20-second deadlines, exact expected stdout-size limits and a
4096-byte stderr cap per call. Failure kills the private process group and permits at
most two more seconds for reaping, including when descendants hold pipes after the
leader exits. Normal completed/reaped groups are not signalled. Nominal extraction
budget: up to **110 seconds**, excluding filesystem/OS stalls. Stderr is not dumped
into the delivery receipt or terminal; fixed diagnostic codes tell the owner to stop.

## Collector controls and precision about HOME

The packet does not modify the accepted collector. Its fixed argv, positive child
environment, private evidence, query/decompression output caps and deadlines remain
those documented in `docs/kitty-platform-collector.md`. It replaces itself with the
collector instead of supervising it with a second timeout that could orphan the
collector's independently grouped query children. The collector owns those deadlines;
no new hard overall wall-clock deadline is claimed.

**An empty HOME is not by itself proof that OpenSSH cannot reach account-home files.**
OpenSSH can derive the home directory from account information. The collector's controls
are the combination of fixed version/no-destination-usage/query-only arguments, no
connection/configuration-evaluation mode, no inherited agent environment, and closed
application descriptors. Empty HOME additionally isolates programs that consult it,
including user-level RPM configuration. Do not call this an SSH filesystem sandbox.
This precision correction does not alter the already accepted collector or expand its
command surface, and no owner hardware verification is claimed.

## Writes, outcomes and return scope

Packet writes are confined to the fresh kit: directories at 0700; the five files and
`delivery.json` at 0600 with exclusive creation/fsync. Git receives umask 077, DEVNULL
stdin, closed inherited descriptors and a private process group. Unexpected files in
its empty HOME are a finding. Partial kits remain after failures; nothing is overwritten,
moved or deleted. A private kit and final checks are delivery controls, not a security
boundary against a malicious same-UID process modifying files between check and use.

`delivery.json` records the immutable source commit, five byte counts/hashes and whether
execution was requested. It explicitly does **not** claim collection or hardware proof.
With `--run`, the collector creates a separate fresh `HOME/kitty-platform-evidence-*`
directory and the previously disclosed 15 JSON records/empty child home. Its existing
read-only probes and private-output writes are unchanged. Neither kit touches files in
`/home/darrel/Elaria`; Git reads source objects/configuration without optional writes.

The packet prints its kit path before extraction so failures remain locatable. Default
exit 0 means **delivery verified only**. Packet failure exits 2: stop and report the
fixed reason; do not change a failed gate. On real collector handoff, the process becomes
the collector and its exit code applies: 0 = collection complete, 1 = findings, 2 =
setup/persistence failure. None means compatibility, reconciliation, semantic or
hardware proof.

No owner action is requested by this document now. At the owner's/design's chosen time,
the committed packet is the delivery/run artifact. Owner return scope stays as documented
for the collector; no owner configuration, keys, agents, terminal contents or incidental
empty-home files are requested into the sandbox. Fedora release/downstream equivalence
remain unverified until actual evidence is returned and reconciled. No sandbox Python
3.14 run occurred; the designated 3.14 mounted-daemon instrument remains the supervised
owner scene, which is NOT READY.
