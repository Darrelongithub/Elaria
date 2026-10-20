"""BUG 7 + the dead-command class: every `assist` subcommand entry point must
be alive.

Owner repro 2026-10-20: `uv run assist meeting setup` crashed with
`ImportError: cannot import name 'list_pw_nodes' from 'assistant.capture'`
(cli.py:380) while 1,280 tests stayed green — nothing ever invoked the CLI
entry points. This file closes that class:

1. `assist meeting setup` works (the exact repro) and prints the Step-3C plan.
2. EVERY leaf subcommand of `build_parser()` is invoked through `main()`.
   A dead entry point — ImportError, AttributeError, TypeError, any
   traceback-shaped failure — fails CI. Exit codes 0/1/2 are all legitimate
   answers (daemon down, refused, nothing to do); a crash is not.
3. Coverage is enforced: a NEW subcommand with no smoke argv fails this file,
   so the table cannot rot silently.
"""

from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import pytest

from assistant.cli import build_parser, main


# ---------------------------------------------------------------------------
# Every leaf entry point with safe args (isolated tmp HOME via conftest;
# the daemon is DOWN, so daemon-owned commands answer 1 — which is an answer).
# ---------------------------------------------------------------------------
def _tiny_wav(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)
    return path


def _smoke_table(tmp_path: Path) -> list[list[str]]:
    mic = _tiny_wav(tmp_path / "mic.wav")
    system = _tiny_wav(tmp_path / "sys.wav")
    root = tmp_path / "files"
    root.mkdir(exist_ok=True)
    return [
        ["doctor", "--json"],
        ["status"],
        ["cost"],
        ["talk", "hello"],
        ["console", "--json"],
        ["class", "status"],
        ["knock", "list"],
        ["knock", "status"],
        ["knock", "due"],
        ["knock", "raise", "--topic", "t", "--reason", "r", "--json"],
        ["knock", "accept", "1", "--json"],
        ["knock", "decline", "1"],
        ["knock", "later", "1", "--json"],
        ["knock", "ignore", "1", "--json"],
        ["privacy", "status"],
        ["showoff", "status"],
        ["showoff", "exit"],
        ["showoff", "demo", "--action", "list"],
        ["commitment", "add", "call the dentist"],
        ["commitment", "list"],
        ["mode"],
        ["ask", "hello"],
        ["voice", "status"],
        ["voice", "say", "hi", "--no-play"],
        ["voice", "models"],
        ["voice", "warm"],
        ["voice", "cleanup"],
        ["voice", "audition", "--text", "hi"],
        ["voice", "select", "voice-00"],
        ["queue", "list"],
        ["queue", "drain"],
        ["queue", "approve", "1"],
        ["queue", "add-external", "action", "description"],
        ["halt"],
        ["resume"],
        ["ptt", "stop"],
        ["transcribe", str(mic)],
        ["index"],
        ["plan", "build"],
        ["plan", "apply", "1"],
        ["plan", "show", "1"],
        ["plan", "list"],
        ["review", "list"],
        ["review", "approve", "1"],
        ["review", "reject", "1"],
        ["undo", "1"],
        ["verify"],
        ["taxonomy", "suggest", str(root)],
        ["search", "hello"],
        ["remember", "I like tea"],
        ["memory"],
        ["forget", "tea"],
        ["embed"],
        ["meeting", "start"],
        ["meeting", "stop"],
        ["meeting", "transcribe", str(mic), str(system)],
        ["meeting", "setup"],
        ["hotword", "status"],
        ["hotword", "start"],
        ["hotword", "start", "--unsafe-energy-test"],
        ["hotword", "stop"],
        ["hotword", "purge"],
        ["dictate"],
        ["events"],
    ]


def _leaf_paths(parser: argparse.ArgumentParser, prefix: tuple = ()):
    """Every leaf subcommand path of the parser tree."""
    subactions = [a for a in parser._actions
                  if isinstance(a, argparse._SubParsersAction)]
    if not subactions:
        yield prefix
        return
    for action in subactions:
        for name, sub in action.choices.items():
            yield from _leaf_paths(sub, prefix + (name,))


# ---------------------------------------------------------------------------
# 1. The exact Bug 7 repro
# ---------------------------------------------------------------------------
def test_meeting_setup_is_alive_and_prints_the_plan(tmp_path, capsys,
                                                   monkeypatch):
    monkeypatch.setattr(sys, "argv", ["assist"])
    code = main(["meeting", "setup"])
    out = capsys.readouterr().out
    assert code == 0
    assert "MEETING CAPTURE SETUP" in out
    assert "Discovered nodes" in out
    assert "mic_target" in out


def test_list_pw_nodes_is_importable_from_capture():
    # The exact ImportError of the owner repro — fail loudly at import time.
    from assistant.capture import list_pw_nodes

    assert callable(list_pw_nodes)


# ---------------------------------------------------------------------------
# 2+3. Every entry point answers, and every leaf is covered
# ---------------------------------------------------------------------------
def test_every_cli_subcommand_entry_point_is_alive(tmp_path, capsys,
                                                   monkeypatch):
    monkeypatch.setattr(sys, "argv", ["assist"])
    # `dictate` blocks on Enter only after the daemon acks; with the daemon
    # down it answers 1 before input(). The stub covers the daemon-up case.
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")

    table = _smoke_table(tmp_path)
    for argv in table:
        capsys.readouterr()          # drain output between entry points
        try:
            code = main(list(argv))
        except SystemExit as exc:    # argparse rejection = dead for users
            pytest.fail(f"{argv} exited via SystemExit({exc.code}) — "
                        "argparse rejected these args")
        except BaseException as exc:
            pytest.fail(f"{argv} crashed with {type(exc).__name__}: {exc}")
        assert isinstance(code, int) and 0 <= code <= 2, (
            f"{argv} returned nonsense exit code {code!r}")


def test_every_parser_leaf_has_a_smoke_invocation(tmp_path):
    """A new subcommand without a smoke argv fails here — the table rots
    loudly, which is the whole point of the Bug 7 exercise."""
    table = [tuple(argv) for argv in _smoke_table(tmp_path)]
    leaves = [leaf for leaf in _leaf_paths(build_parser()) if leaf]
    missing = []
    for leaf in leaves:
        if not any(argv[: len(leaf)] == leaf for argv in table):
            missing.append(" ".join(leaf))
    assert not missing, (
        "subcommand(s) with no smoke entry in "
        "tests/test_bug7_cli_smoke.py::_smoke_table: " + ", ".join(missing))
