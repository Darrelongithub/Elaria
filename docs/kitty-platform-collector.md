# Fedora/OpenSSH metadata collector — BUILT, NOT AUTHORISED FOR OWNER RUN

`tools/kitty/collect_platform.py` is a separate, standalone instrument. It does not
modify or import the approved drift script or its inventory, the daemon, or adapters.
Build permission is not owner-run permission. **Scene remains NOT READY.** No owner
run packet for this collector is issued here.

## Meaning of the result

- Exit **0**: the bounded collection completed without its defined findings. **Not**
  compatible, reconciled, semantic proof, package integrity proof or hardware proof.
- Exit **1**: evidence was saved, but one or more query/document checks have findings.
  Missing packages are recorded; nothing is installed or repaired.
- Exit **2**: setup/persistence/OS failure. Partial evidence may remain. Nothing is
  deleted, moved, overwritten or automatically retried into the same directory.

`report.json` always marks `compatibility_verified=false`, `hardware_proven=false`,
and `requires_manual_reconciliation=true`. A 0.47.1 version reading establishes
neither Fedora release `-1.fc44` nor downstream-patch equivalence. An unowned executable,
unexpected build/package or changed documentation requires reconciliation, not a safe
verdict. The source pin remains upstream 0.47.1; the owner-design package pin remains
0.47.1-1.fc44. Neither is promoted to an owner observation by this instrument.

## Exact subprocess surface (12 queries)

| Record | Fixed argv |
| --- | --- |
| `kitty-version` | `/usr/bin/kitty --version` |
| `binary-owners` | `/usr/bin/rpm -qf /usr/bin/kitty /usr/bin/kitten /usr/bin/ssh` |
| `package-versions` | `/usr/bin/rpm -q kitty kitty-kitten kitty-shell-integration kitty-terminfo openssh openssh-clients` |
| `files-PACKAGE` (six calls) | `/usr/bin/rpm -ql PACKAGE`, separately for those six literal package names |
| `ssh-version` | `/usr/bin/ssh -V` |
| `ssh-usage` | `/usr/bin/ssh` (no destination) |
| `ssh-query-categories` | `/usr/bin/ssh -Q help` |

Bare SSH usage with return code 255 and `usage: ssh ` in stderr is expected, retained
and not treated as failure. Other unexpected/nonzero results, missing binaries, empty
results, truncation or timeout become findings. `ssh -Q help` supplies query categories,
**not configured defaults**. There is no ssh connection, `ssh -G`, kitty RC command,
config application, package install, updater, shell or request-selected executable.

The approved drift packet already collects `kitten --version`; this collector's distinct
`kitty --version` reading does not replace it. Both instrument outputs are needed for
manual reconciliation. This collector needs no checkout or inventory file to run after
separate approval/deployment; it consists of one Python file.

## Packaged manuals, not personal configuration

Successful `rpm -ql openssh` and `rpm -ql openssh-clients` results are the only sources
of eligible manual paths. Accept only exact unlocalized paths beneath `/usr/share/man`:

- `man1/ssh.1`
- `man5/ssh_config.5`
- Either may have exactly one supported suffix: `.gz`, `.bz2`, `.xz`, `.zst`.

Zero candidates or multiple representations for a page produce a finding; no guessing.
The reader refuses symlinks in the path, nonregular files, hardlinks, foreign ownership,
group/world-writable files/directories, oversized files and changes observed during the
read. Production manual files/directories must be root-owned. Synthetic test seams do
not appear in the CLI.

Compressed bytes are opened/read through that gate, then sent on stdin to one fixed
helper; the helper never gets a filename from RPM output:

| Suffix | Fixed decompressor argv |
| --- | --- |
| `.gz` | `/usr/bin/gzip -cd` |
| `.bz2` | `/usr/bin/bzip2 -dc` |
| `.xz` | `/usr/bin/xz -dc --memlimit-decompress=64MiB` |
| `.zst` | `/usr/bin/zstd -dc --memory=64MB` |

Missing helpers/unsupported formats/decompression errors are findings, never installation
requests or fallback to a different document. These helper invocations are tested with
stubs, not claimed to have run on Fedora. There are at most two decompressor calls.
The text is raw package documentation, not rendered by `man`, a pager or troff.
Recognized `.so`/`.mso` include directives refuse collection; no include is followed.
Collection is not a roff semantic interpreter. Source-byte and collected-text SHA256
references are retained, not claims of package pristine state or source equivalence.

## Process isolation and limits

Python imports are stdlib-only. Existing system query binaries and the applicable
compression helper are external prerequisites; missing ones are reported. No venv,
Python package installation, model dependency or `compression.zstd` module is required.
The collector records its Python version; this is not a mounted-daemon interpreter test.

Children receive only PATH=/usr/bin:/bin, LC_ALL=C.UTF-8, TERM=dumb, NO_COLOR=1, and
HOME/XDG_CONFIG_HOME pointing to a fresh private `empty-home` inside the evidence directory.
This avoids per-user RPM macros/configuration. No inherited KITTY_*, SSH_AUTH_SOCK,
loader variables, API keys, proxy settings or owner HOME/XDG paths. System RPM settings,
the RPM database and system loader/runtime files may still be read by the query programs.
**This is not an OS filesystem/network sandbox.** It does not claim to constrain a
compromised system executable.

No shell, inherited terminal input or inherited application descriptors; subprocesses
have `close_fds=true`, their own session/process group and umask 077. Query stdin is
DEVNULL; decompressor stdin contains only the validated package-document bytes.

- **20 seconds** per subprocess; **2 MiB combined stdout/stderr** per subprocess.
- **2 MiB** per compressed/plain input manual; decompressed output has the same process cap.
- Timeout/output overflow kills the private process group, even if its leader already
  exited with descendants holding pipes. Reaping is bounded to another **2 seconds**.
- Twelve queries plus at most two decompressions: about **5 minutes 8 seconds** of
  nominal subprocess timeout/reap budget in an all-stalled run. Normal duration is
  expected to be seconds to about a minute, **not owner-measured**. Filesystem/OS stalls
  are not covered by a claimed hard overall deadline.

## Explicit reads, writes and return scope

The CLI accepts only `--output`: a **new direct child of the invoking HOME**, with an
existing owned, non-group/world-writable HOME and no symlink components. No parent tree
creation, checkout discovery or Git command. Symlinked home layouts are currently refused,
not automatically resolved. This is a documented instrument limitation requiring review.

The collector explicitly creates:

- One fresh evidence directory, **0700**.
- Its `empty-home` directory, **0700**.
- **15 JSON files**, created exclusively at **0600**: 12 query records, two manual
  records and `report.json`. Records carry argv/return code/stdout/stderr/error/truncation;
  manual records additionally carry path, hashes and raw package documentation.

Files and the evidence directory are fsynced. Existing outputs/symlinks refuse; nothing
is moved, deleted, repaired or overwritten. Partial files remain after failures.
Unexpected query-program writes inside `empty-home` are detected as a finding and left
in place; the collector does not read or return their contents. Nothing intentionally
writes to the checkout, system packages, owner configuration or running applications.

After a separate owner-run ruling, the proposed initial return is `report.json`,
`kitty-version.json`, `binary-owners.json`, `package-versions.json`, `ssh-version.json`,
`ssh-usage.json`, and `ssh-query-categories.json`. Package-membership/manual records can
be requested as needed for reconciliation; they contain package metadata/vendor docs,
not owner configuration. No contents from `empty-home` are requested.

NOT inspected: owner kitty.conf/includes/effective settings, RC socket state, SSH
configuration, keys, agents, terminal contents, RPM file integrity, binary-content
identity or downstream-patch equivalence. Owner configuration/effective settings remain
for the separately supervised owner-local setup/scene review. Neither metadata instrument
silently closes that gate.
