"""P · HANDS-HEADLESS — instance resolution + fail-closed version gate tests."""

from __future__ import annotations

import os
import stat

import pytest

from assistant.hands.headless.instance import (
    DEFAULT_VERSION_PIN,
    InstanceError,
    KittyInstance,
    PinMismatchError,
    PinNotConfiguredError,
    VersionGateError,
    sha256_of,
)

PINNED_OUTPUT = "kitty 0.49.2 created by Kovid Goyal\n"
WRONG_OUTPUT = "kitty 0.48.0 created by Kovid Goyal\n"


def _fake_kitty(tmp_path, output: str):
    """An executable fake kitty that prints ``output`` on --version."""
    path = tmp_path / "kitty"
    # echo re-adds exactly one trailing newline; the version text itself has
    # no quotes or backslashes, so this reproduces ``output`` byte-exactly.
    path.write_text(f'#!/bin/sh\necho "{output.rstrip()}"\n', encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _pinned_instance(tmp_path, output: str = PINNED_OUTPUT) -> KittyInstance:
    kitty = _fake_kitty(tmp_path, output)
    python = "/usr/bin/python3"
    return KittyInstance(
        kitty_path=str(kitty),
        python_path=python,
        kitty_sha256=sha256_of(kitty),
        python_sha256=sha256_of(python),
    )


def test_gate_passes_on_pinned_version(tmp_path):
    instance = _pinned_instance(tmp_path)
    check = instance.check()
    assert check.version_output == PINNED_OUTPUT
    assert check.version_output.startswith(DEFAULT_VERSION_PIN)
    assert check.kitty_sha256 == sha256_of(instance.kitty_path)


def test_gate_raises_before_mkdir_on_wrong_version(tmp_path):
    instance = _pinned_instance(tmp_path, output=WRONG_OUTPUT)
    with pytest.raises(VersionGateError) as excinfo:
        instance.check()
    message = str(excinfo.value)
    assert DEFAULT_VERSION_PIN in message
    assert "0.48.0" in message
    assert "before any directory" in message


def test_check_creates_no_directories(tmp_path):
    instance = _pinned_instance(tmp_path, output=WRONG_OUTPUT)
    # NB: the repo conftest pre-creates tmp_path/"runtime" as XDG_RUNTIME_DIR,
    # so the sentinel uses a distinct name.
    sentinel = tmp_path / "headless-runtime"
    with pytest.raises(VersionGateError):
        instance.check()
    assert not sentinel.exists()


def test_prepare_creates_runtime_tree_only_after_check(tmp_path):
    instance = _pinned_instance(tmp_path)
    instance.check()
    runtime = instance.prepare(tmp_path / "headless-runtime")
    assert runtime.is_dir()
    assert (runtime / "logs").is_dir()


def test_sha_mismatch_raises_legibly(tmp_path):
    instance = _pinned_instance(tmp_path)
    bad = KittyInstance(
        kitty_path=instance.kitty_path,
        python_path=instance.python_path,
        kitty_sha256="0" * 64,
        python_sha256=instance.python_sha256,
    )
    with pytest.raises(PinMismatchError) as excinfo:
        bad.check()
    message = str(excinfo.value)
    assert "0" * 64 in message
    assert sha256_of(instance.kitty_path) in message


def test_missing_pins_fail_closed(tmp_path):
    kitty = _fake_kitty(tmp_path, PINNED_OUTPUT)
    instance = KittyInstance(kitty_path=str(kitty), python_path="/usr/bin/python3")
    with pytest.raises(PinNotConfiguredError) as excinfo:
        instance.check()
    assert "fails CLOSED" in str(excinfo.value)


def test_missing_binary_raises_legibly(tmp_path):
    instance = KittyInstance(
        kitty_path=str(tmp_path / "nope"),
        python_path="/usr/bin/python3",
        kitty_sha256="0" * 64,
        python_sha256="0" * 64,
    )
    with pytest.raises(InstanceError) as excinfo:
        instance.check()
    assert "binary not found" in str(excinfo.value)


def test_non_executable_binary_raises_legibly(tmp_path):
    not_exec = tmp_path / "kitty-not-exec"
    not_exec.write_text("#!/bin/sh\n", encoding="utf-8")
    not_exec.chmod(0o644)
    instance = KittyInstance(
        kitty_path=str(not_exec),
        python_path="/usr/bin/python3",
        kitty_sha256="0" * 64,
        python_sha256="0" * 64,
    )
    with pytest.raises(InstanceError) as excinfo:
        instance.check()
    assert "not executable" in str(excinfo.value)
    assert not os.access(not_exec, os.X_OK)
