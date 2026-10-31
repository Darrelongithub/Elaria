"""Daemon + IPC + CLI end-to-end, no key, no network (Phase 0 done-when)."""

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from assistant.ipc import call

REPO = Path(__file__).resolve().parents[1]


# running_daemon fixture lives in conftest.py (shared across phases).


def test_socket_is_owner_only(config, running_daemon):
    assert config.socket_path.stat().st_mode & 0o777 == 0o600  # §3.1


def test_status_cost_ack_over_ipc(config, running_daemon):
    status = call(config.socket_path, "status")
    assert status["running"] and status["name"] == "Elaria"
    assert status["gemini_mode"] == "mock"

    started = time.monotonic()
    ack = call(config.socket_path, "ack")
    assert (time.monotonic() - started) * 1000 < 300  # §18 budget, incl. IPC
    assert ack["network"] is False

    cost = call(config.socket_path, "cost")
    assert cost["month"]["calls"] == 0  # ack made ZERO model calls (99% code)


def test_ask_flows_governor_then_harness(config, running_daemon):
    result = call(config.socket_path, "ask", {"text": "status of my chaos?"})
    assert result["mode"] == "mock"
    assert result["register"] in ("plain", "expressive-allowed")
    assert result["fixture"]["synthetic"] is True  # unrecorded => flagged synth
    cost = call(config.socket_path, "cost")
    assert cost["month"]["calls"] == 1  # and it was ledgered


def test_halt_and_resume(config, running_daemon):
    assert call(config.socket_path, "halt")["halted"] is True
    assert call(config.socket_path, "status")["halted"] is True
    assert call(config.socket_path, "resume")["halted"] is False


def test_ptt_acks_immediately(config, running_daemon):
    reply = call(config.socket_path, "ptt.start")
    assert reply["listening"] and reply["ack"] and reply["network"] is False


def test_unknown_method_is_an_error_not_a_crash(config, running_daemon):
    with pytest.raises(RuntimeError):
        call(config.socket_path, "plan.apply")  # Phase 4 — must refuse cleanly


# -- CLI as a subprocess: the Phase 0 definition of done ----------------------
def _cli(args, env_extra=None):
    import os
    env = {**os.environ, "PYTHONPATH": str(REPO / "src"), **(env_extra or {})}
    return subprocess.run([sys.executable, "-m", "assistant.cli", *args],
                          check=False, capture_output=True, text=True, env=env, timeout=30)


def test_cli_doctor_reports_honest_facts():
    out = _cli(["doctor"])
    assert out.returncode == 0, out.stdout + out.stderr
    # Stage A / Step 0: the owner has VERIFIED the quota shape, so the doctor
    # reads the real numbers from [quota] and must not cry wolf any more.
    assert "VERIFIED 2026-10-20" in out.stdout
    assert "5 RPM" in out.stdout and "20 RPD" in out.stdout
    assert "UNVERIFIED: no verified numbers" not in out.stdout
    assert "aistudio.google.com/rate-limit" not in out.stdout
    assert "gemini-3.8-live" in out.stdout      # the validated Live voice route
    assert "mock" in out.stdout                # no key => no network
    assert "hypr" in out.stdout.lower()        # version/syntax verdict present


def test_cli_doctor_json_is_machine_readable():
    out = _cli(["doctor", "--json"])
    report = json.loads(out.stdout)
    names = {c["check"] for c in report["checks"]}
    assert {"api key", "quota shape", "hyprland", "daemon"} <= names


def test_cli_doctor_names_registry_role_drift(tmp_path):
    """M-3 (mini order M): a registered id in the wrong role is its own
    doctor defect — named by key with the pinned value. This is the check
    that would have named the W1 files-route drift before the stump."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[gemini]\nmodel_transcribe_batch = "gemini-3.5-flash-lite"\n')
    out = _cli(["doctor", "--json"], {"ASSIST_CONFIG": str(cfg)})
    report = json.loads(out.stdout)
    by_name = {c["check"]: c for c in report["checks"]}
    pin_check = by_name["registry role pins"]
    assert pin_check["status"] == "fail"
    assert "model_transcribe_batch" in pin_check["detail"]
    assert "gemini-3.5-transcribe" in pin_check["detail"]
    # the clean config passes the same check
    out2 = _cli(["doctor", "--json"])
    by_name2 = {c["check"]: c for c in json.loads(out2.stdout)["checks"]}
    assert by_name2["registry role pins"]["status"] == "ok"


def test_cli_cost_works_with_daemon_down():
    out = _cli(["cost"])
    assert out.returncode == 0
    assert "billed this month: $0.00" in out.stdout  # free tier, honestly


def test_cli_status_waybar_shape():
    out = _cli(["status", "--waybar"])
    payload = json.loads(out.stdout)
    assert {"text", "class", "tooltip"} <= payload.keys()


# -- BH-G4 (fixed): argparse help strings must survive %-formatting ----------
#
# `help="…>tripwire% of the tree…"` is not a cosmetic typo. argparse
# %-formats every help string, and since Python 3.14 it does so eagerly
# inside add_argument() — so one unescaped `%` made `build_parser()` raise
# `ValueError: badly formed help string` (caused by `TypeError: %o format:
# an integer is required, not dict`) and took EVERY `assist` command down.
# On 3.11-3.13 the same string only crashed when that one subcommand's
# `--help` was formatted, which is how it shipped.

def _walk_parsers(parser, path=()):
    import argparse

    yield list(path), parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                yield from _walk_parsers(subparser, (*path, name))


def test_cli_every_help_string_renders():
    """Construct the parser and format every subcommand's help in-process.

    Fails on 3.11+ (format time) and on 3.14+ (construction time), so this
    catches the bug on every supported Python, not just the one that
    validates eagerly.
    """
    from assistant.cli import build_parser

    rendered = [tuple(path) for path, parser in _walk_parsers(build_parser())
                if parser.format_help() or True]
    # The walk really reached the parser that used to explode.
    assert ("plan", "apply") in rendered
    assert ("queue", "add-external") in rendered
    assert len(rendered) > 30            # whole command tree, not a smoke test


def test_cli_plan_apply_help_renders_a_single_percent():
    out = _cli(["plan", "apply", "--help"])
    assert out.returncode == 0, out.stdout + out.stderr
    assert ">tripwire% of the tree" in out.stdout   # `%%` renders as one `%`
    assert "%%" not in out.stdout


@pytest.mark.parametrize("args", [
    [], ["plan"], ["plan", "apply"], ["queue"], ["queue", "add-external"],
    ["voice"], ["review"], ["meeting"], ["taxonomy"],
])
def test_cli_help_exits_zero_for_every_command_group(args):
    out = _cli([*args, "--help"])
    assert out.returncode == 0, out.stdout + out.stderr
    assert "usage: assist" in out.stdout


def test_no_unescaped_percent_in_any_argparse_help_string():
    """Static audit over the whole tree, so `assist-voice-test` (whose parser
    is built inside its own main()) is covered too, and so a future bare `%`
    is caught at lint time rather than on someone's Fedora.

    Run in a fresh interpreter: CPython's parser keeps its own recursion
    bookkeeping, and auditing after ~1000 tests have perturbed it can raise
    `SystemError: AST constructor recursion depth mismatch` on a deep file.
    """
    script = textwrap.dedent("""
        import ast, sys
        from pathlib import Path

        HELP_KWARGS = {"help", "description", "epilog", "usage", "metavar", "prog"}
        offenders = []
        for path in sorted(Path(sys.argv[1]).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call):
                    continue
                callee = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if callee not in {"add_argument", "add_parser", "ArgumentParser"}:
                    continue
                for kw in node.keywords:
                    if kw.arg not in HELP_KWARGS:
                        continue
                    try:
                        value = ast.literal_eval(kw.value)
                    except ValueError:
                        continue
                    for text in (value if isinstance(value, (list, tuple)) else [value]):
                        if not isinstance(text, str) or "%" not in text:
                            continue
                        try:
                            text % {"prog": "assist", "default": 0, "const": 0,
                                    "type": "str", "choices": "a, b"}
                        except (TypeError, ValueError, KeyError) as exc:
                            offenders.append(f"{path.name}:{node.lineno} {kw.arg} "
                                             f"{text!r} -> {exc}")
        print("\\n".join(offenders))
        """)
    audit = subprocess.run([sys.executable, "-c", script, str(REPO / "src")],
                           check=False, capture_output=True, text=True, timeout=60)
    assert audit.returncode == 0, audit.stderr
    assert audit.stdout.strip() == "", audit.stdout
