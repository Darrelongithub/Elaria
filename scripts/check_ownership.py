#!/usr/bin/env python3
"""Lint OWNERS.yaml and check a Git change set against its base revision's owners."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from fnmatch import fnmatchcase
from pathlib import Path
from typing import ClassVar

OWNERS = "OWNERS.yaml"
CLUSTERS = frozenset("ABCDEFGHIJKLMOPQRSTUVZ") | {"REL", "REACH"}


def git(*args, cwd=None):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    if result.returncode:
        raise ValueError(os.fsdecode(result.stderr).strip() or f"git {args[0]} failed")
    return result.stdout


def valid_path(path):
    return (
        isinstance(path, str)
        and all(part not in {"", ".", "..", ".git"} for part in path.split("/"))
        and not any(ord(char) < 32 for char in path)
    )


def read_map(data):
    # JSON is a YAML 1.2 subset; use a strict, dependency-free parser.
    def unique_keys(pairs):
        mapping = {}
        for key, value in pairs:
            if key in mapping:
                raise ValueError(f"duplicate cluster: {key}")
            mapping[key] = value
        return mapping

    mapping = json.loads(data, object_pairs_hook=unique_keys)
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("expected a nonempty object of cluster IDs to glob lists")
    rules, seen = [], set()
    for owner, globs in mapping.items():
        if owner not in CLUSTERS or not isinstance(globs, list) or not globs:
            raise ValueError(f"invalid cluster or empty glob list: {owner!r}")
        for glob in globs:
            if not valid_path(glob):
                raise ValueError(f"invalid repository glob: {glob!r}")
            parts = tuple(glob.split("/"))
            if any("**" in part for part in parts[:-1]) or (
                "**" in parts[-1] and (parts[-1] != "**" or len(parts) == 1)
            ):
                raise ValueError(f"'**' is only supported as a trailing subtree: {glob!r}")
            if glob in seen:
                raise ValueError(f"duplicate ownership rule: {glob!r}")
            seen.add(glob)
            rules.append((owner, glob, parts))
    return rules


def matches(parts, pattern):
    if pattern[-1] == "**":
        pattern = pattern[:-1]
        if len(parts) <= len(pattern):
            return False
    elif len(parts) != len(pattern):
        return False
    return all(fnmatchcase(part, glob) for part, glob in zip(parts, pattern))


def owners_for(path, rules):
    if not valid_path(path):
        raise ValueError(f"invalid repository path: {path!r}")
    parts = path.split("/")
    return [(owner, glob) for owner, glob, pattern in rules if matches(parts, pattern)]


def git_paths(data):
    if not data:
        return set()
    if not data.endswith(b"\0"):
        raise ValueError("expected NUL-delimited Git paths")
    return {os.fsdecode(path) for path in data[:-1].split(b"\0")}


def lint(paths, rules):
    orphan = duplicate = 0
    for path in sorted(paths):
        found = owners_for(path, rules)
        if not found:
            orphan += 1
            print(f"unowned: {path!r}", file=sys.stderr)
        elif len(found) != 1:
            duplicate += 1
            print(f"multiple ownership rules: {path!r}: {found!r}", file=sys.stderr)
    print(f"{len(paths)} paths; {orphan} zero-owner; {duplicate} multi-owner")
    return int(bool(orphan or duplicate))


def check(paths, rules, cluster):
    denied = 0
    for path in sorted(paths):
        found = owners_for(path, rules)
        if len(found) != 1 or found[0][0] != cluster:
            print(f"denied for {cluster}: {path!r}: {found!r}", file=sys.stderr)
            denied += 1
    print(f"{len(paths)} changed paths; {denied} denied for {cluster}")
    return int(bool(denied))


def commit(ref, cwd):
    if not ref:
        raise ValueError("a nonempty commit ref is required")
    return (
        git("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}", cwd=cwd)
        .decode()
        .strip()
    )


def check_changes(cwd, base_ref, head_ref, staged, cluster):
    base = commit(base_ref, cwd)
    if staged:
        if git("ls-files", "--unmerged", "-z", cwd=cwd):
            raise ValueError("resolve index conflicts before checking ownership")
        candidate = git("show", f":{OWNERS}", cwd=cwd)
        tracked = git_paths(git("ls-files", "--cached", "-z", cwd=cwd))
        head_args = ("--cached", base)
    else:
        head = commit(head_ref, cwd)
        candidate = git("show", f"{head}:{OWNERS}", cwd=cwd)
        tracked = git_paths(git("ls-tree", "-r", "--name-only", "-z", head, cwd=cwd))
        head_args = (base, head)
    # Disable rename detection to check both the old and new paths of any move.
    changed = git_paths(
        git(
            "diff",
            "--name-only",
            "--no-renames",
            "--ignore-submodules=none",
            "-z",
            *head_args,
            "--",
            cwd=cwd,
        )
    )
    trusted = read_map(git("show", f"{base}:{OWNERS}", cwd=cwd))
    return check(changed, trusted, cluster) | lint(tracked, read_map(candidate))


class GuardTests(unittest.TestCase):
    """Run the actual CLI in disposable Git repositories, not on the user's index."""

    MAP: ClassVar[dict[str, list[str]]] = {
        "Z": ["OWNERS.yaml", "src/daemon.py"],
        "A": ["src/voice*.py"],
        "B": ["src/memory.py"],
    }
    SCRIPT = Path(__file__).resolve()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        git("init", "-q", cwd=self.root)
        git("config", "user.email", "guard-test@example.invalid", cwd=self.root)
        git("config", "user.name", "Ownership guard test", cwd=self.root)
        self.write(OWNERS, json.dumps(self.MAP))
        for path in ("src/daemon.py", "src/voice.py", "src/memory.py"):
            self.write(path)
        git("add", ".", cwd=self.root)
        self.make_commit()
        self.base = commit("HEAD", self.root)

    def write(self, path, content="fixture\n"):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def make_commit(self):
        git(
            "-c",
            "commit.gpgSign=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "commit",
            "-qm",
            "fixture",
            cwd=self.root,
        )

    def run_guard(self, *args, code=0):
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def staged(self, cluster, code=0):
        return self.run_guard(
            "check", "--base", self.base, "--staged", "--cluster", cluster, code=code
        )

    def test_cross_edit_rejected(self):
        self.write("src/daemon.py", "changed\n")
        git("add", ".", cwd=self.root)
        self.assertIn("1 denied for A", self.staged("A", code=1))

    def test_in_owner_edit_accepted(self):
        self.write("src/voice.py", "changed\n")
        git("add", ".", cwd=self.root)
        self.assertIn("1 changed paths; 0 denied for A", self.staged("A"))

    def test_z_wire_commit_accepted(self):
        self.write("src/daemon.py", "delegates through shared wire\n")
        git("add", ".", cwd=self.root)
        self.make_commit()
        output = self.run_guard("check", "--base", self.base, "--head", "HEAD", "--cluster", "Z")
        self.assertIn("1 changed paths; 0 denied for Z", output)

    def test_orphan_and_duplicate_reported(self):
        self.write("src/orphan.txt")
        git("add", ".", cwd=self.root)
        self.write(OWNERS, json.dumps({**self.MAP, "C": ["src/voice.py"]}))
        output = self.run_guard("lint", code=1)
        self.assertIn("1 zero-owner; 1 multi-owner", output)
        self.assertIn("src/orphan.txt", output)
        self.assertIn("src/voice.py", output)

    def test_candidate_cannot_reassign_itself(self):
        self.write(
            OWNERS,
            json.dumps({**self.MAP, "Z": ["OWNERS.yaml"], "A": ["src/voice.py", "src/daemon.py"]}),
        )
        self.write("src/daemon.py", "changed\n")
        git("add", ".", cwd=self.root)
        self.assertIn("2 denied for A", self.staged("A", code=1))

    def test_z_cannot_claim_another_clusters_path(self):
        self.write("src/voice.py", "changed\n")
        git("add", ".", cwd=self.root)
        self.assertIn("1 denied for Z", self.staged("Z", code=1))

    def test_move_checks_both_endpoints(self):
        git("mv", "src/daemon.py", "src/voice-new.py", cwd=self.root)
        output = self.staged("A", code=1)
        self.assertIn("2 changed paths; 1 denied for A", output)
        self.assertIn("denied for A: 'src/daemon.py'", output)

    def commit_report_rules(self):
        # Use the shipped map so these tests catch a policy regression as well
        # as a matcher regression. Keep all report rules, even broad ones.
        repo_rules = read_map((self.SCRIPT.parents[1] / OWNERS).read_bytes())
        mapping = {owner: globs.copy() for owner, globs in self.MAP.items()}
        for owner, glob, _ in repo_rules:
            if glob.startswith("reports/"):
                mapping.setdefault(owner, []).append(glob)
        self.write(OWNERS, json.dumps(mapping))
        git("add", OWNERS, cwd=self.root)
        self.make_commit()
        self.base = commit("HEAD", self.root)
        return repo_rules

    def test_own_report_accepted(self):
        rules = self.commit_report_rules()
        for cluster in sorted(CLUSTERS):
            with self.subTest(cluster=cluster):
                path = f"reports/RPT-{cluster}-r1-x.md"
                self.assertEqual(owners_for(path, rules), [(cluster, f"reports/RPT-{cluster}-*")])
        self.assertEqual(owners_for("reports/unassigned.md", rules), [])
        self.write("reports/RPT-E-r1-x.md")
        git("add", "--", "reports/RPT-E-r1-x.md", cwd=self.root)
        self.assertIn("1 changed paths; 0 denied for E", self.staged("E"))

    def test_foreign_report_rewrite_denied(self):
        self.commit_report_rules()
        path = "reports/RPT-E-r1-x.md"
        self.write(path, "E's original report\n")
        git("add", "--", path, cwd=self.root)
        self.make_commit()
        self.base = commit("HEAD", self.root)
        self.write(path, "another cluster's rewrite\n")
        git("add", "--", path, cwd=self.root)
        for cluster in ("F", "Z"):
            with self.subTest(cluster=cluster):
                self.assertIn(f"denied for {cluster}: {path!r}", self.staged(cluster, code=1))

    def test_invalid_map_fails_closed(self):
        self.write(OWNERS, '{"Z":["OWNERS.yaml"],"Z":["src/daemon.py"]}')
        self.assertIn("duplicate cluster", self.run_guard("lint", code=2))

    def test_no_base_map_fails_closed(self):
        git("rm", OWNERS, cwd=self.root)
        self.make_commit()
        base = commit("HEAD", self.root)
        self.write(OWNERS, json.dumps(self.MAP))
        git("add", OWNERS, cwd=self.root)
        self.run_guard("check", "--base", base, "--staged", "--cluster", "Z", code=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("lint", help="lint the worktree map against all indexed paths")
    commands.add_parser("self-test", help="run the guard's tests in temporary repositories")
    change = commands.add_parser("check", help="check a staged or committed change set")
    change.add_argument("--cluster", required=True, choices=sorted(CLUSTERS))
    change.add_argument("--base", required=True, help="reviewed base commit containing OWNERS.yaml")
    target = change.add_mutually_exclusive_group(required=True)
    target.add_argument("--head", help="candidate commit")
    target.add_argument("--staged", action="store_true", help="check the Git index")
    args = parser.parse_args()
    if args.command == "self-test":
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(GuardTests)
        return int(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
    try:
        # Git knows the worktree root even if invoked from a nested directory.
        root = Path(os.fsdecode(git("rev-parse", "--show-toplevel").removesuffix(b"\n")))
        if args.command == "lint":
            paths = git_paths(git("ls-files", "--cached", "-z", cwd=root))
            return lint(paths, read_map((root / OWNERS).read_bytes()))
        return check_changes(root, args.base, args.head, args.staged, args.cluster)
    except (OSError, ValueError) as error:
        print(f"ownership guard: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
