"""Rung-0 identity readback — is the RUNNING daemon this checkout? (Ask 43).

The bug this prevents is expensive and quiet: an evening spent debugging a
transcript produced by the binary you replaced an hour ago. Two facts are pinned
hard here:

1. **`version` cannot answer the question.** `__version__` is the literal
   `"0.0.1"` and has been for every commit in this tree, so two different
   checkouts report the same version. `version_alone_discriminates 0` is printed
   on every run and pinned, so the field can never imply a match it did not test.
2. **Freshness is the cheap, honest discriminator.** A source file newer than the
   daemon's start is code the daemon is not running. That comparison also has a
   third state: with no daemon to compare against it is `-1` (never compared),
   not `0` ("nothing stale"), which would be the same silence-as-absence mistake
   the rest of this cluster exists to prevent.

The pid proof (`/proc/net/unix` inode matched against `/proc/<pid>/fd`) is pinned
against real table text, including the row shape that broke the first
implementation: every data row's first column is a kernel pointer ending in `:`,
so a `parts[0].endswith(":")` header skip silently dropped the whole table.
"""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "daemon_identity.py"
MANIFEST = REPO / "scripts" / "daemon_identity.py.sha256"

_spec = importlib.util.spec_from_file_location("daemon_identity", SCRIPT)
identity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(identity)

UNIX_TABLE = """Num       RefCount Protocol Flags    Type St Inode Path
0000000000000000: 00000002 00000000 00010000 0001 01 24761 @/tmp/.X11-unix/X0
000000007164603c: 00000002 00000000 00010000 0001 01 10849 /tmp/rt/assistant.sock
0000000012345678: 00000002 00000000 00010000 0001 01 99999 /run/other.sock
"""


def _identify(**overrides) -> dict:
    """A reachable, matching baseline that each test perturbs one field on."""
    base = {
        "daemon": {"version": "0.0.1", "uptime_s": 100.0,
                   "started_at": "2026-11-17T09:00:00Z"},
        "daemon_error": "",
        "checkout": Path("/repo"),
        "checkout_commit": "abc123def456",
        "checkout_commit_error": "",
        "checkout_dirty": 0,
        "checkout_version_value": "0.0.1",
        "daemon_dir_commit": "abc123def456",
        "daemon_dir_error": "",
        "newest_source_mtime": 1_000.0,
        "newest_source_file": "/repo/src/assistant/daemon.py",
        "daemon_start_epoch": 2_000.0,
        "now": 2_100.0,
    }
    base.update(overrides)
    return identity.identify(**base)


# ---------------------------------------------------------------------------
# the verdict ladder
# ---------------------------------------------------------------------------
def test_a_matching_clean_tree_reads_match():
    result = _identify()
    assert result["verdict"] == "match"
    assert result["stale_source_files"] == 0
    assert result["daemon_reachable"] == 1
    assert "same commit" in result["why"]


def test_no_daemon_is_never_a_clean_verdict():
    result = _identify(daemon={}, daemon_error="DaemonUnavailable: no socket")
    assert result["verdict"] == "daemon_down"
    assert result["daemon_reachable"] == 0
    # The anti-vacuity pin: not compared is -1, never 0.
    assert result["stale_source_files"] == -1
    assert result["version_equal"] == 0


def test_a_source_file_newer_than_the_daemon_reads_stale():
    result = _identify(newest_source_mtime=2_500.0)   # edited after the start
    assert result["verdict"] == "stale_checkout"
    assert result["stale_source_files"] == 1
    assert "daemon.py" in result["why"]
    assert "not running the code on disk" in result["why"]


def test_a_source_file_older_than_the_daemon_does_not_read_stale():
    result = _identify(newest_source_mtime=1_500.0, daemon_start_epoch=2_000.0)
    assert result["stale_source_files"] == 0
    assert result["verdict"] == "match"


def test_two_different_checkouts_are_named_before_freshness_is_blamed():
    """The two-checkout confusion: -old dir running while you edit the new one."""
    result = _identify(daemon_dir_commit="999999999999", newest_source_mtime=2_500.0)
    assert result["verdict"] == "different_checkout"
    assert "999999999999" in result["why"] and "abc123def456" in result["why"]


def test_an_uncommitted_tree_is_its_own_verdict():
    result = _identify(checkout_dirty=1)
    assert result["verdict"] == "dirty_checkout"
    assert "not a single thing" in result["why"]


def test_no_revision_evidence_is_reported_as_weak_not_as_match():
    result = _identify(checkout_commit="", checkout_commit_error="git missing",
                       daemon_dir_commit="")
    assert result["verdict"] == "revision_unknown"
    assert result["checkout_commit"] == "-1"
    assert "equal version is not an equal tree" in result["why"]


def test_every_verdict_is_in_the_documented_enum():
    for result in (_identify(), _identify(daemon={}, daemon_error="x"),
                   _identify(newest_source_mtime=2_500.0),
                   _identify(daemon_dir_commit="999"),
                   _identify(checkout_dirty=1),
                   _identify(checkout_commit="", daemon_dir_commit="")):
        assert result["verdict"] in identity.VERDICTS


# ---------------------------------------------------------------------------
# the ask-43 finding itself
# ---------------------------------------------------------------------------
def test_an_equal_version_is_printed_as_non_discriminating():
    result = _identify()
    assert result["version_equal"] == 1
    assert result["version_alone_discriminates"] == 0


def test_the_version_really_is_a_static_literal_in_this_tree():
    """If __version__ ever becomes per-commit, this pin goes red on purpose."""
    init = (REPO / "src" / "assistant" / "__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "0.0.1"' in init
    assert identity.VERSION_IS_STATIC_NOTE


def test_daemon_start_time_falls_back_to_self_reported_uptime():
    result = _identify(daemon_start_epoch=None,
                       daemon={"version": "0.0.1", "uptime_s": 600.0}, now=10_000.0)
    assert result["daemon_start_epoch"] == 9_400.0
    assert result["daemon_age_s"] == 600.0


def test_without_a_start_time_freshness_is_unknown_not_clean():
    result = _identify(daemon_start_epoch=None,
                       daemon={"version": "0.0.1"})   # no uptime either
    assert result["stale_source_files"] == -1
    # Verdict may still be match on commit evidence, but staleness is unproven.
    assert result["daemon_age_s"] == "-1"


# ---------------------------------------------------------------------------
# /proc/net/unix parsing (the bug that shipped in the first draft)
# ---------------------------------------------------------------------------
def test_unix_table_finds_the_bound_socket_inode():
    assert identity.parse_unix_table(UNIX_TABLE, "/tmp/rt/assistant.sock") == 10849
    assert identity.parse_unix_table(UNIX_TABLE, "/run/other.sock") == 99999


def test_data_rows_start_with_a_colon_and_must_not_be_skipped_as_headers():
    """Regression: skipping `parts[0].endswith(':')` dropped every real row."""
    rows = [line for line in UNIX_TABLE.splitlines()[1:] if line.strip()]
    assert all(row.split()[0].endswith(":") for row in rows)
    assert identity.parse_unix_table(UNIX_TABLE, "/tmp/rt/assistant.sock") is not None


def test_unix_table_absent_or_unnamed_sockets_parse_to_none():
    assert identity.parse_unix_table(UNIX_TABLE, "/not/here.sock") is None
    assert identity.parse_unix_table("Num RefCount\n", "/x") is None
    assert identity.parse_unix_table("", "/x") is None
    # An unnamed socket row (7 columns, no path) must not match anything.
    assert identity.parse_unix_table("aa: 02 00 00 0001 01 42\n", "/x") is None


def test_a_filesystem_inode_is_not_a_socket_inode(tmp_path):
    """The reason os.stat() is not used: the numbers are from different tables."""
    plain = tmp_path / "assistant.sock"
    plain.write_text("", encoding="utf-8")
    stat_inode = plain.stat().st_ino
    assert identity.parse_unix_table(UNIX_TABLE, str(plain)) is None
    # ...and the parsed socket inode is unrelated to any file's inode.
    assert identity.parse_unix_table(UNIX_TABLE, "/tmp/rt/assistant.sock") != stat_inode


def test_proc_facts_degrades_instead_of_raising():
    facts = identity.proc_facts(None)
    assert facts["pid"] == "-1"
    assert facts["exe"] == "-1" and facts["cwd"] == "-1"
    gone = identity.proc_facts(999_999_999)
    assert gone["pid"] == 999_999_999
    assert gone["exe"] == "-1"
    assert gone["start_epoch"] is None


def test_proc_facts_reads_a_real_process():
    import os

    facts = identity.proc_facts(os.getpid())
    assert facts["pid"] == os.getpid()
    assert facts["exe"] != "-1"
    assert facts["start_epoch"] is not None and facts["start_epoch"] > 0


def test_find_daemon_pid_says_why_when_it_cannot_answer(tmp_path):
    pid, reason = identity.find_daemon_pid(None)
    assert pid is None and reason == "no socket path"
    pid, reason = identity.find_daemon_pid(tmp_path / "not-bound.sock")
    assert pid is None and "not bound" in reason


# ---------------------------------------------------------------------------
# reading the checkout (text, never import)
# ---------------------------------------------------------------------------
def test_checkout_version_is_read_as_text_not_imported(tmp_path):
    pkg = tmp_path / "src" / "assistant"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        "# a comment\n__version__ = '9.8.7'\n", encoding="utf-8")
    assert identity.checkout_version(tmp_path) == "9.8.7"
    assert identity.checkout_version(tmp_path / "absent") == "-1"


def test_source_files_and_newest_mtime(tmp_path):
    pkg = tmp_path / "src" / "assistant"
    pkg.mkdir(parents=True)
    old = pkg / "old.py"
    new = pkg / "new.py"
    for path in (old, new):
        path.write_text("x = 1\n", encoding="utf-8")
    import os

    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    files = identity.source_files(tmp_path)
    assert [f.name for f in files] == ["new.py", "old.py"]
    newest, path = identity.newest_mtime(files)
    assert newest == 2000 and path.endswith("new.py")
    assert identity.newest_mtime([]) == (None, "")
    assert identity.source_files(tmp_path / "absent") == []


def test_git_revision_reports_a_real_sha_for_this_repo():
    sha, error = identity.git_revision(REPO)
    assert error == "" and len(sha) == 12
    assert all(character in "0123456789abcdef" for character in sha)


def test_git_revision_fails_readably_outside_a_repo(tmp_path):
    sha, error = identity.git_revision(tmp_path)
    assert sha == "" and error


def test_the_reader_never_imports_the_daemon_or_its_god_files():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("from assistant.daemon", "from assistant.store",
                      "from assistant.cli", "import assistant.daemon",
                      "import assistant.store", "import assistant.cli"):
        assert forbidden not in source, forbidden
    # `status` is read through the thin IPC client, and `config` only to resolve
    # a socket path when XDG_RUNTIME_DIR is unset.
    for module in ("daemon", "store", "cli"):
        assert identity.__dict__.get(module) is None


# ---------------------------------------------------------------------------
# rendering + cli
# ---------------------------------------------------------------------------
def test_render_states_the_static_version_and_read_only():
    lines = identity.render(_identify()).splitlines()
    assert lines[0] == "available 1"
    assert "verdict match" in lines
    assert "version_alone_discriminates 0" in lines
    assert any(line.startswith("note version_is_static") for line in lines)
    assert lines[-1] == "note read_only"
    for line in lines:
        assert " " in line


def test_render_says_what_a_missing_daemon_cannot_tell_you():
    result = _identify(daemon={}, daemon_error="no socket")
    lines = identity.render(result).splitlines()
    assert lines[0] == "available 0"
    assert any(line.startswith("note empty_fails_to_discriminate") for line in lines)


def test_render_never_offers_to_restart_anything():
    stale = identity.render(_identify(newest_source_mtime=2_500.0))
    assert "restart_is_the_owners_call" in stale
    assert "note read_only" in stale


def test_cli_no_ipc_still_reports_the_checkout(tmp_path, capsys):
    assert identity.main(["--no-ipc", "--checkout", str(REPO)]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "available 0"
    assert "checkout_commit " + identity.git_revision(REPO)[0] in out
    assert "daemon_reachable 0" in out


def test_cli_bad_arguments_and_help_are_refused():
    assert identity.main(["--help"]) == 2
    assert identity.main(["--nonsense"]) == 2
    assert identity.main(["--checkout"]) == 2


def test_manifest_is_repo_relative_and_verifies_from_the_root():
    digest, name = MANIFEST.read_text().split()
    assert name == "scripts/daemon_identity.py"
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == digest, (
        "daemon_identity.py changed without regenerating its manifest — run "
        "`python3 scripts/daemon_identity.py --checksum`")
    verified = subprocess.run(
        ["sha256sum", "-c", "scripts/daemon_identity.py.sha256"],
        cwd=REPO, capture_output=True, text=True, timeout=60, check=False)
    assert verified.returncode == 0, verified.stdout + verified.stderr
