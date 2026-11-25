"""Only fake runners ship. No subprocess, shell, execve, network or live adapter.

TypingRunner is the gated text-injection seam; its only shipped sinks are synthetic or refuse.
"""
from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .gate import TYPE_TOOL, child_environment, typing_text_ok
from .plan import Step
from .sandbox import SyntheticSpace


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

    No key emission is implemented here. Keystrokes into a focused window have no
    independent readback, so SandboxCore never calls ``type_text`` on this sink
    (``has_readback`` is False and the core refuses before claiming the step).
    """

    has_readback = False

    def __init__(self, *, enabled: bool):
        self._enabled = enabled is True

    def available(self) -> tuple[bool, str]:
        if not self._enabled:
            return False, "disabled-by-config"
        if importlib.util.find_spec("evdev") is None:
            return False, "evdev-absent"
        if not os.access("/dev/uinput", os.W_OK):
            return False, "uinput-absent"
        return True, ""

    def type_text(self, text: str) -> None:
        ok, reason = self.available()
        raise PermissionError(f"typing refused: {reason if not ok else 'no key-emission backend'}")

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
