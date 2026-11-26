"""R2/R3 sandbox adjudication. Facts are independent test observations, not model claims.

This is NOT a production command/effect analyser. Unknown flag semantics leave
read-only status unproven (T2); unknown effects refuse dispatch. Live integration
must supply executable identity, dirty-repo/immutable and outward-effect facts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from assistant.safety import assert_within_sandbox, check_operation, is_protected

from .plan import Step

READ_BINARIES = frozenset(["cat", "ls", "stat", "du", "df", "grep", "find", "head", "tail", "wc", "file", "sha256sum", "systemctl", "rpm", "hyprctl", "pactl", "pw-dump", "journalctl"])
SHELLS = frozenset({"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh"})
EVAL_BINARIES = frozenset({"eval", "exec", "env", "xargs", "sudo", "su", "doas", "busybox"})
# Launchers whose own effect semantics are unrecognised (privilege/namespace
# escalation): forbidden outright, at any position of a launcher chain.
PRIVILEGE_LAUNCHERS = frozenset({"pkexec", "systemd-run", "unshare", "nsenter", "capsh"})
# Transparent wrappers that only schedule/attend their payload: unwrapped so
# every shell/recursive/upload check below applies to the payload, not the wrapper.
UNWRAP_LAUNCHERS = frozenset({"timeout", "nice", "nohup", "stdbuf", "setsid", "watch",
                              "time", "flock", "chrt", "ionice", "taskset", "strace",
                              "firejail", "bwrap", "bubblewrap"})
# Script interpreters and loaders can evaluate a file/stdin, not just -c/-e.
INTERPRETERS = ("python", "pypy", "perl", "ruby", "node", "lua", "php", "tclsh", "wish",
                "gawk", "awk", "sed", "ld-linux")
READ_FLAGS = {
    "cat": {"-n", "-b", "-s", "-E", "-T", "-v", "--number"},
    "ls": {"-l", "-a", "-h", "-la", "-al", "-lh", "--all", "--long"},
    "stat": {"-t", "--terse"}, "du": {"-s", "-h", "-sh"}, "df": {"-h", "-T"},
    "grep": {"-n", "-i", "-v", "-F", "-E", "-c", "-l"},
    "find": {"-type", "-name", "-iname", "-maxdepth", "-mindepth", "-print", "-print0"},
    "head": {"-n", "-c"}, "tail": {"-n", "-c"}, "wc": {"-l", "-c", "-w"},
    "file": {"-b", "--brief"}, "sha256sum": {"-b", "-t"},
    "systemctl": {"--user", "--no-pager", "--plain"},
    "rpm": {"-q", "-qa", "-qi", "-ql", "-qf"},
    "hyprctl": {"-j"}, "pactl": {"--format=json"}, "pw-dump": set(),
    "journalctl": {"--user", "--no-pager", "-b", "-n", "-u"},
}
READ_VERBS = {
    "systemctl": {"status", "show", "list-units", "list-unit-files", "is-active", "is-enabled"},
    "hyprctl": {"version", "monitors", "clients", "activewindow", "layers", "devices"},
    "pactl": {"info", "list", "get-default-sink", "get-default-source", "get-sink-volume"},
}

# curl/wget-style content transfer flags. Long names are matched after
# normalised flag parsing (``--name=value`` and abbreviated ``--name`` forms).
UPLOAD_FLAG_NAMES = ("data", "data-raw", "data-ascii", "data-binary", "data-urlencode",
                     "form", "form-string", "upload-file", "json", "proxy-upload-file")
UPLOAD_SHORTS = frozenset("dFT")
_UPLOAD_TOKENS = frozenset({"-d", "--data", "-T", "--upload-file", "-F", "--form"})
_DURATION_OPERAND = re.compile(r"[0-9]+(?:[.][0-9]+)?(?:ns|us|ms|s|m|h|d)?")
_TRUSTED_LAUNCHER = re.compile(r"/(?:usr/)?bin/[A-Za-z0-9._+-]+")


def _trusted_launcher(token: str) -> bool:
    """A canonicalised system binary path may name the executable without a
    sandbox path check; every other argv[0] path is an ordinary candidate."""
    try:
        resolved = str(Path(token).resolve())
    except (OSError, ValueError):
        return False
    return _TRUSTED_LAUNCHER.fullmatch(resolved) is not None


def _shell_like(name: str) -> bool:
    return (name in SHELLS | EVAL_BINARIES | PRIVILEGE_LAUNCHERS
            or name.startswith(INTERPRETERS))


def _arg_value(arg: str) -> str:
    """Path-like value carried by one argument after normalised flag parsing."""
    if "://" in arg:
        parts = urlsplit(arg)
        if parts.scheme != "file":
            return ""
        if parts.netloc in ("", "localhost"):
            return unquote(parts.path)
        return unquote("/" + parts.netloc + parts.path)
    if not arg.startswith("-"):
        return arg
    if "=" in arg:
        return arg.split("=", 1)[1]
    if arg.startswith("--"):
        return ""
    match = re.match(r"-\w*(.*)", arg)
    return match.group(1) if match else ""


def _unwrap_chain(argv: tuple[str, ...]) -> tuple[str | None, tuple[str, ...], bool]:
    """Split a launcher chain into (program, payload args, ok).

    Only bare names and trusted system paths are transparent wrappers; a
    lookalike under the fixture tree is a program of its own. A chain whose
    payload cannot be resolved is unrecognised (ok=False), never tier 2 by
    omission.
    """
    i = 0
    while i < len(argv):
        token = argv[i]
        name = Path(token).name
        if name not in UNWRAP_LAUNCHERS or ("/" in token and not _trusted_launcher(token)):
            return token, tuple(argv[i + 1:]), True
        i += 1
        while i < len(argv) and ((argv[i].startswith("-") and len(argv[i]) > 1)
                                 or _DURATION_OPERAND.fullmatch(argv[i])):
            i += 1
        if i >= len(argv):
            return None, (), False
    return None, (), False


def _recursive_shape(args: tuple[str, ...]) -> bool:
    """Normalised flag parsing: ``--recursive=always`` and ``--r`` are ``--recursive``."""
    for arg in args:
        if arg.startswith("--"):
            name = arg[2:].split("=", 1)[0]
            if name and "recursive".startswith(name):
                return True
        elif arg.startswith("-") and len(arg) > 1 and ("r" in arg or "R" in arg):
            return True
    return False


def _upload_shape(args: tuple[str, ...]) -> bool:
    """Normalised upload-flag detection: long names/prefixes and attached shorts."""
    for arg in args:
        if arg.startswith("--"):
            name = arg[2:].split("=", 1)[0]
            if name and any(flag.startswith(name) for flag in UPLOAD_FLAG_NAMES):
                return True
        elif arg.startswith("-") and len(arg) > 2 and arg[1] in UPLOAD_SHORTS:
            return True  # attached short-option value: -d@file, -Tfile, -F@file
    return False


TYPE_TOOL = "type"  # text injection: exactly one printable string, nothing else
TYPE_MAX_CHARS = 200


def typing_text_ok(argv) -> bool:
    """One nonempty printable string. No control bytes (no Enter/Tab/ESC chords)."""
    return (type(argv) is tuple and len(argv) == 1 and type(argv[0]) is str
            and 0 < len(argv[0]) <= TYPE_MAX_CHARS and argv[0].isprintable())


def child_environment(diff: tuple[tuple[str, str], ...]) -> dict[str, str]:
    """Positive baseline, never os.environ. Refuse rather than silently edit the hash."""
    result = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    for key, value in diff:
        upper = key.upper()
        if (any(part in upper for part in ("KEY", "TOKEN", "SECRET", "PASS", "CREDENTIAL", "AUTH", "COOKIE"))
                or upper.startswith(("LD_", "PYTHON", "PERL", "RUBY", "NODE", "BASH", "ZSH"))
                or upper in {"PATH", "HOME", "ENV", "SHELLOPTS", "IFS", "XDG_CONFIG_HOME"}):
            raise PermissionError("credential or evaluation environment refused")
        result[key] = value
    return result


@dataclass(frozen=True)
class Verdict:
    tier: int | None
    verdict: str
    reason: str = ""
    mismatches: int = 0
    halt: bool = False
    ask: bool = False


# Private in-process capability; only the fixture mouse runner may supply it,
# immediately after its batch, screen, journal and halt checks.
_MOUSE_FIXTURE_KEY = object()


def adjudicate(model, checker, mismatches: int = 0, *, _mouse_key=None) -> Verdict:
    if any(t is not None and (type(t) is not int or t not in range(4)) for t in (model, checker)):
        return Verdict(None, "refused", "unadjudicable", mismatches)
    if model is None and checker is None:
        return Verdict(None, "refused", "unadjudicable", mismatches)
    if mismatches >= 2:
        tier = max((t for t in (model, checker) if t is not None), default=None)
        return Verdict(tier, "refused", "two-mismatch-halt", mismatches, halt=True)
    if model is None or checker is None:
        present = checker if model is None else model
        tier = 3 if present == 3 else min(present + 1, 2)
        return Verdict(tier, "refused" if tier == 3 else "ok", "missing-evidence", mismatches,
                       ask=tier == 2)
    mismatch = model != checker
    count = mismatches + int(mismatch)
    tier = max(model, checker)
    if count >= 2:
        return Verdict(tier, "refused", "two-mismatch-halt", count, halt=True)
    if tier == 3:
        if model == checker == 3 and count == 0 and _mouse_key is _MOUSE_FIXTURE_KEY:
            return Verdict(3, "ok", "owner-present-mouse-fixture")
        return Verdict(3, "refused", "forbidden", count)
    return Verdict(tier, "mismatch-escalated" if mismatch else "ok", mismatches=count,
                   ask=tier == 2)


@dataclass(frozen=True)
class SyntheticFacts:
    dirty_roots: tuple[Path, ...] = ()
    immutable_paths: tuple[Path, ...] = ()
    owner_services: frozenset[str] = frozenset()
    bulk_delete: bool = False
    sends_owner_content: bool = False
    payments_or_identity: bool = False
    effects_complete: bool = True


class GateChecker:
    """Restrict all observed/target paths to a minted synthetic workspace."""

    def __init__(self, space):
        self.space = space

    def path_allowed(self, path: Path, facts: SyntheticFacts) -> bool:
        try:
            assert_within_sandbox(path, self.space.work)
            parts = path.parts
            if (any(p in {".ssh", ".gnupg", ".config", "keyrings", ".netrc", "gemini.env",
                          ".git-credentials"} for p in parts)
                    or (".git" in parts and "credentials" in parts)):
                return False
            if is_protected(path, [str(p) for p in (*facts.dirty_roots, *facts.immutable_paths)]):
                return False
            for parent in (path, *path.parents):
                if parent == self.space.work.parent:
                    break
                if (parent / ".assistant-ignore").exists():
                    return False
            if path.is_file():
                decision = check_operation("read", path, None, protected=[], recent_guard_minutes=15)
                if not decision.allowed:
                    return False
            return True
        except (OSError, ValueError, PermissionError):
            return False

    def paths(self, step: Step) -> tuple[Path, ...]:
        cwd = Path(step.cwd)
        # Conservative candidate extraction; no raw content or command output
        # influences this list. Service/tool parsers can narrow it at integration.
        args = step.argv if step.tool != "exec" else step.argv[1:]
        args = (*args, *(value for _, value in step.env_diff))
        values = []
        if step.tool == "exec" and step.argv:
            head = step.argv[0]
            # argv[0] is a path like any other once it is a path form; only
            # trusted system launchers are exempt from the sandbox path wall.
            if ("/" in head or "://" in head) and not _trusted_launcher(head):
                values.append(head)
        for arg in args:
            value = _arg_value(arg)
            if value.startswith("@"):  # --data=@file, -d@file, @file payloads
                value = value[1:]
            if not value or value.startswith("-") or "://" in value:
                continue
            values.append(value)
        return (cwd, *(Path(v) if v.startswith("/") else cwd / v for v in values))

    def _shebang_entry(self, token: str, cwd: Path) -> bool:
        """Kernel shebang dispatch on any canonicalised launcher path is tier 3."""
        if "/" not in token:
            return False
        try:
            candidate = Path(token)
            if not candidate.is_absolute():
                candidate = cwd / candidate
            candidate = candidate.resolve()
            if self.space.work.resolve() not in candidate.parents or not candidate.is_file():
                return False
            with candidate.open("rb") as handle:
                return handle.read(2) == b"#!"
        except (OSError, ValueError):
            return True  # an unreadable launcher path is unrecognised, never tier 2

    def derive(self, step: Step, facts: SyntheticFacts) -> int | str:
        if facts.bulk_delete or facts.payments_or_identity:
            return 3
        try:
            child_environment(step.env_diff)
        except PermissionError:
            return 3
        if step.tool == TYPE_TOOL:
            # Always an owner decision (tier 2) for valid text; never a path or argv.
            return 2 if typing_text_ok(step.argv) and not step.env_diff else 3
        if any(not self.path_allowed(p, facts) for p in self.paths(step)):
            return 3
        if step.tool == "resolve_collision":
            if len(step.argv) != 3:
                return "invalid"
            old, new = (Path(step.cwd) / a for a in step.argv[1:])
            return 2 if old.is_file() and not new.exists() else "invalid"
        if step.tool in {"move", "trash"}:
            if len(step.argv) != (2 if step.tool == "move" else 1):
                return "invalid"
            if step.tool == "move":
                dst = Path(step.cwd) / step.argv[1]
                return 2 if dst.exists() else 1
            return 1
        if step.tool != "exec" or not facts.effects_complete:
            return "invalid"
        # Classify the resolved launcher chain: transparent wrappers are
        # unwrapped so no wrapper can shadow the payload's semantics.
        program, args, chain_ok = _unwrap_chain(step.argv)
        if not chain_ok:
            return 3  # unrecognised launcher shape, never tier 2 by omission
        binary = Path(program).name
        # Read identity only, never launch for introspection.
        resolved = Path(program).resolve().name if "/" in program else binary
        for name in (binary, resolved):
            if _shell_like(name):
                return 3
        if self._shebang_entry(program, Path(step.cwd)):
            return 3  # kernel shebang dispatch is an interpreter entry point too
        if binary == "find" and any(a in {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint",
                                          "-fprint0", "-fprintf"} for a in args):
            return 3
        if binary == "rm" and _recursive_shape(args):
            return 3  # independently recognized bulk-delete shape; other rm is simulated T2
        urls = [urlsplit(a) for a in args if "://" in a]
        if any(u.username or u.password for u in urls):
            return 3
        upload = facts.sends_owner_content or any(a in _UPLOAD_TOKENS for a in args)
        if not upload and binary not in READ_BINARIES:
            upload = _upload_shape(args)  # normalised --data=/-d@file/T shapes
        if upload and (not urls or any(u.hostname not in facts.owner_services for u in urls)):
            return 3
        if binary not in READ_BINARIES:
            return 2
        if "/" in program and program not in {f"/usr/bin/{binary}", f"/bin/{binary}"}:
            return 2  # a lookalike under the fixture tree is not a trusted T0 binary
        options = [a for a in args if a.startswith("-") and a != "--"]
        if any(a not in READ_FLAGS[binary] for a in options):
            return 2
        if binary in READ_VERBS:
            words = [a for a in args if not a.startswith("-")]
            if not words or words[0] not in READ_VERBS[binary]:
                return 2
        if binary == "rpm" and not any(a.startswith("-q") for a in options):
            return 2
        # Directory-reading tools may otherwise traverse protected descendants.
        for path in self.paths(step):
            if path.is_dir():
                for entry in path.rglob("*"):
                    if not self.path_allowed(entry, facts):
                        return 3
        return 0
