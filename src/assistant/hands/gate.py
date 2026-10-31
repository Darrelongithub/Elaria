"""R2/R3 sandbox adjudication. Facts are independent test observations, not model claims.

This is NOT a production command/effect analyser. Unknown flag semantics leave
read-only status unproven (T2); unknown effects refuse dispatch. Live integration
must supply executable identity, dirty-repo/immutable and outward-effect facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from assistant.safety import assert_within_sandbox, check_operation, is_protected

from .plan import Step

READ_BINARIES = frozenset(["cat", "ls", "stat", "du", "df", "grep", "find", "head", "tail", "wc", "file", "sha256sum", "systemctl", "rpm", "hyprctl", "pactl", "pw-dump", "journalctl"])
SHELLS = frozenset({"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh"})
EVAL_BINARIES = frozenset({"eval", "exec", "env", "xargs", "sudo", "su", "doas", "busybox"})
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


def adjudicate(model, checker, mismatches: int = 0) -> Verdict:
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
        for arg in args:
            value = arg.split("=", 1)[1] if arg.startswith("-") and "=" in arg else arg
            if not value or value.startswith("-") or "://" in value:
                continue
            values.append(Path(value) if value.startswith("/") else cwd / value)
        return (cwd, *values)

    def derive(self, step: Step, facts: SyntheticFacts) -> int | str:
        if facts.bulk_delete or facts.payments_or_identity:
            return 3
        try:
            child_environment(step.env_diff)
        except PermissionError:
            return 3
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
        binary = Path(step.argv[0]).name
        # Read identity only, never launch for introspection.
        resolved = Path(step.argv[0]).resolve().name if "/" in step.argv[0] else binary
        for name in (binary, resolved):
            if name in SHELLS | EVAL_BINARIES or name.startswith(INTERPRETERS):
                return 3
        candidate = Path(step.argv[0])
        if candidate.is_absolute() and self.space.work in candidate.parents and candidate.is_file():
            with candidate.open("rb") as handle:
                if handle.read(2) == b"#!":
                    return 3  # kernel shebang dispatch is an interpreter entry point too
        if binary == "find" and any(a in {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint",
                                          "-fprint0", "-fprintf"} for a in step.argv[1:]):
            return 3
        if binary == "rm" and any(a == "--recursive" or (a.startswith("-") and not a.startswith("--")
                                                         and ("r" in a or "R" in a))
                                  for a in step.argv[1:]):
            return 3  # independently recognized bulk-delete shape; other rm is simulated T2
        urls = [urlsplit(a) for a in step.argv[1:] if "://" in a]
        if any(u.username or u.password for u in urls):
            return 3
        upload = facts.sends_owner_content or any(a in {"-d", "--data", "-T", "--upload-file",
                                                        "-F", "--form"} for a in step.argv[1:])
        if upload and (not urls or any(u.hostname not in facts.owner_services for u in urls)):
            return 3
        if binary not in READ_BINARIES:
            return 2
        if "/" in step.argv[0] and step.argv[0] not in {f"/usr/bin/{binary}", f"/bin/{binary}"}:
            return 2  # a lookalike under the fixture tree is not a trusted T0 binary
        options = [a for a in step.argv[1:] if a.startswith("-") and a != "--"]
        if any(a not in READ_FLAGS[binary] for a in options):
            return 2
        if binary in READ_VERBS:
            words = [a for a in step.argv[1:] if not a.startswith("-")]
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
