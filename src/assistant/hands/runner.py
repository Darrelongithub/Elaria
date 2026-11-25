"""Only fake runners ship. No subprocess, shell, execve, network or live adapter.

TypingRunner is the gated text-injection seam; its only shipped sinks are synthetic or refuse.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .gate import TYPE_TOOL, child_environment, typing_text_ok
from .plan import Step
from .sandbox import SyntheticSpace

log = logging.getLogger(__name__)

# Linux evdev key names for printable ASCII. Shift is only used for the upper
# form of a key; there are no control/meta chords and no Enter/Tab/Backspace.
# Anything outside this table (Unicode letters, control bytes) is refused: a
# guessed keysym would type something other than the consented text.
_ASCII_KEY_NAMES: dict[str, tuple[str, bool]] = {
    **{c: (f"KEY_{c.upper()}", False) for c in "abcdefghijklmnopqrstuvwxyz0123456789"},
    **{c: (f"KEY_{c}", True) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    " ": ("KEY_SPACE", False),
    "!": ("KEY_1", True), "@": ("KEY_2", True), "#": ("KEY_3", True),
    "$": ("KEY_4", True), "%": ("KEY_5", True), "^": ("KEY_6", True),
    "&": ("KEY_7", True), "*": ("KEY_8", True), "(": ("KEY_9", True),
    ")": ("KEY_0", True),
    "-": ("KEY_MINUS", False), "_": ("KEY_MINUS", True),
    "=": ("KEY_EQUAL", False), "+": ("KEY_EQUAL", True),
    "[": ("KEY_LEFTBRACE", False), "{": ("KEY_LEFTBRACE", True),
    "]": ("KEY_RIGHTBRACE", False), "}": ("KEY_RIGHTBRACE", True),
    "\\": ("KEY_BACKSLASH", False), "|": ("KEY_BACKSLASH", True),
    ";": ("KEY_SEMICOLON", False), ":": ("KEY_SEMICOLON", True),
    "'": ("KEY_APOSTROPHE", False), '"': ("KEY_APOSTROPHE", True),
    ",": ("KEY_COMMA", False), "<": ("KEY_COMMA", True),
    ".": ("KEY_DOT", False), ">": ("KEY_DOT", True),
    "/": ("KEY_SLASH", False), "?": ("KEY_SLASH", True),
    "`": ("KEY_GRAVE", False), "~": ("KEY_GRAVE", True),
}


@dataclass(frozen=True)
class Result:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    op_ids: tuple[int, ...] = ()


@dataclass
class FakeRunner:
    space: SyntheticSpace
    responses: dict[int, Result | Exception] = field(default_factory=dict)
    calls: list = field(default_factory=list)
    cleaned: list = field(default_factory=list)
    during: object = None  # trusted test hook, never populated from plans/data

    def run(self, step: Step) -> Result:
        env = child_environment(step.env_diff)
        self.calls.append((step.i, tuple(a.encode("utf-8") for a in step.argv),
                           step.cwd.encode("utf-8"), env))
        if self.during is not None:
            self.during(step)
        scripted = self.responses.get(step.i)
        if isinstance(scripted, Exception):
            raise scripted
        if scripted is not None:
            return scripted
        cwd = Path(step.cwd)
        if step.tool in {"move", "resolve_collision"}:
            src = cwd / step.argv[0]
            dst = cwd / step.argv[-1]
            # Never let the library's automatic conflict-name selection change
            # a hashed intended destination. A collision needs an explicit new plan.
            if dst.exists():
                raise PermissionError("destination changed; re-plan")
            report = self.space.move(src, dst)
            return Result(returncode=0 if report["applied"] == 1 else 1,
                          op_ids=report["op_ids"])
        if step.tool == "trash":
            src = cwd / step.argv[0]
            result = self.space.trash(src)
            ops = self.space.store.committed_operations()
            ids = tuple(o["id"] for o in ops if o["op"] == "trash" and o["src"] == str(src))
            return Result(returncode=0 if result["result"] == "applied" else 1, op_ids=ids)
        return Result()  # arbitrary exec stays a simulated response, never a host spawn

    def cleanup(self, step: Step):
        """Fake process-group lifecycle observation, not hardware cleanup proof."""
        self.cleaned.append(step.i)


# --- Text injection (O-HANDS). Behind the same gate: tier 2 owner decision,
# exact-digest consent, claim, then readback. Text only: no keys, chords, paths.

class TypeSink(Protocol):
    """A keyboard-like sink. ``has_readback`` says whether it can prove what it typed."""

    has_readback: bool

    def available(self) -> tuple[bool, str]: ...

    def type_text(self, text: str) -> None: ...

    def last_typed(self) -> str | None: ...


@dataclass
class SyntheticTypeSink:
    """Lab sink: records text in memory. Reaches no keyboard, no window, no process."""

    typed: list = field(default_factory=list)
    has_readback = True

    def available(self) -> tuple[bool, str]:
        return True, ""

    def type_text(self, text: str) -> None:
        self.typed.append(text)

    def last_typed(self) -> str | None:
        return self.typed[-1] if self.typed else None


class UinputTypeSink:
    """Real-keyboard seam. Off by default; refuses honestly unless every precondition holds.

    Key emission is implemented here, and nowhere else: ``evdev`` is imported
    lazily, and a trusted ``evdev_factory`` can return an evdev-like module for
    fake-device tests (the factory is never populated from config, plans or
    data). Without that injection the old preconditions apply unchanged.

    Keystrokes into a focused window have no independent readback. This sink
    therefore keeps ``has_readback = False`` and remembers no typed text:
    SandboxCore refuses it before ``type_text`` rather than claim an
    unverified step. Emission is reachable only by a trusted caller holding a
    genuinely open gate (e.g. ``TypingRunner.run`` in tests/hardware wiring).
    """

    has_readback = False

    def __init__(self, *, enabled: bool, evdev_factory: Callable[[], object] | None = None,
                 uinput_path: str = "/dev/uinput"):
        self._enabled = enabled is True
        self._evdev_factory = evdev_factory  # trusted test/hardware hook only
        self._uinput_path = uinput_path

    def _refuse(self, reason: str) -> tuple[bool, str]:
        log.warning("typing refused: %s", reason)
        return False, reason

    def _raise_refusal(self, reason: str) -> None:
        self._refuse(reason)
        raise PermissionError(f"typing refused: {reason}")

    def _evdev(self):
        """Return an evdev-like module lazily, or None if it cannot be had."""
        try:
            module = (self._evdev_factory() if self._evdev_factory is not None
                      else importlib.import_module("evdev"))
        except Exception:
            return None
        if not callable(getattr(module, "UInput", None)) or getattr(module, "ecodes", None) is None:
            return None
        return module

    @staticmethod
    def _emit_calls(text: str, ecodes) -> list[tuple] | None:
        """Exact write/syn call sequence for ASCII text; None if unsupported."""
        ev_key = getattr(ecodes, "EV_KEY", None)
        shift = getattr(ecodes, "KEY_LEFTSHIFT", None)
        if not isinstance(ev_key, int) or not isinstance(shift, int):
            return None
        calls: list[tuple] = []
        for char in text:
            name, needs_shift = _ASCII_KEY_NAMES.get(char, (None, False))
            if name is None:
                return None
            code = getattr(ecodes, name, None)
            if not isinstance(code, int):
                return None
            # Shift must be held across the key press. One SYN after each state
            # change makes the events independently observable on real uinput.
            if needs_shift:
                calls.extend((("write", ev_key, shift, 1), ("syn",)))
            calls.extend((("write", ev_key, code, 1), ("syn",),
                          ("write", ev_key, code, 0), ("syn",)))
            if needs_shift:
                calls.extend((("write", ev_key, shift, 0), ("syn",)))
        return calls

    def available(self) -> tuple[bool, str]:
        if not self._enabled:
            return self._refuse("disabled-by-config")
        if self._evdev_factory is None:
            if importlib.util.find_spec("evdev") is None:
                return self._refuse("evdev-absent")
            if not os.access(self._uinput_path, os.W_OK):
                return self._refuse("uinput-absent")
        elif not callable(self._evdev_factory):
            return self._refuse("evdev-absent")
        return True, ""

    def type_text(self, text: str) -> None:
        ok, reason = self.available()
        if not ok:
            self._raise_refusal(reason)
        if not typing_text_ok((text,)):
            self._raise_refusal("invalid-text")
        if any(char not in _ASCII_KEY_NAMES for char in text):
            self._raise_refusal("unsupported-character")
        module = self._evdev()
        if module is None:
            self._raise_refusal("evdev-absent")
        calls = self._emit_calls(text, module.ecodes)
        if calls is None:
            self._raise_refusal("unsupported-character")
        codes = sorted({call[2] for call in calls if call[0] == "write"})
        try:
            device = module.UInput({module.ecodes.EV_KEY: codes}, name="elaria-hands")
        except Exception as exc:
            self._raise_refusal(f"uinput-absent: {type(exc).__name__}: {exc}")
        try:
            for call in calls:
                if call[0] == "write":
                    device.write(*call[1:])
                else:
                    device.syn()
        except Exception as exc:
            self._raise_refusal(f"uinput-write-failed: {type(exc).__name__}: {exc}")
        finally:
            close = getattr(device, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    log.warning("typing device close failed after emission")

    def last_typed(self) -> str | None:
        return None


def typing_enabled(config) -> bool:
    """Default OFF. Only a literal boolean True at [hands.typing] enabled turns it on."""
    try:
        return config["hands"]["typing"]["enabled"] is True
    except (KeyError, TypeError):
        return False


@dataclass
class TypingRunner:
    """The only runner that may carry a type step. Bound to one synthetic workspace."""

    space: SyntheticSpace
    sink: object
    injections: list = field(default_factory=list)  # every text that reached sink.type_text
    cleaned: list = field(default_factory=list)

    def __post_init__(self):
        if type(self.space) is not SyntheticSpace:
            raise TypeError("typing runner requires a minted synthetic workspace")

    def available(self, step: Step) -> tuple[bool, str]:
        if step.tool != TYPE_TOOL or not typing_text_ok(step.argv):
            return False, "invalid-text"
        return self.sink.available()

    def readback_available(self) -> bool:
        return bool(getattr(self.sink, "has_readback", False))

    def readback(self) -> str | None:
        return self.sink.last_typed()

    def run(self, step: Step) -> Result:
        ok, reason = self.available(step)
        if not ok:
            raise PermissionError(f"typing refused: {reason}")
        self.injections.append(step.argv[0])
        self.sink.type_text(step.argv[0])
        return Result()

    def cleanup(self, step: Step):
        self.cleaned.append(step.i)
