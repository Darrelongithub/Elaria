"""Only fake runners ship. No subprocess, shell, execve, network or live adapter.

TypingRunner is the gated text-injection seam; its only shipped sinks are synthetic or refuse.
"""
from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import re
import secrets
import time
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from assistant.observation import Frame, ground
from assistant.safety import is_halted

from .gate import TYPE_TOOL, _MOUSE_FIXTURE_KEY, adjudicate, child_environment, typing_text_ok
from .plan import Plan, Step
from .queue import ParkedQueue
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


@dataclass(frozen=True)
class MouseSeat:
    """Independent fixture compositor facts, not accessibility or model text."""
    frame: Frame
    window: str
    unlocked: bool
    owner_present: bool
    safe_surface: bool  # independent positive allowlist: excludes auth/payment


@dataclass
class FakeMouseInput:
    calls: list = field(default_factory=list)
    during: Callable | None = None

    def click(self, point):
        self.calls.append(point)
        if self.during is not None:
            self.during()


def mouse_screen(seat: MouseSeat) -> str:
    """Bind pixels, geometry, focus and accessibility data, not capture IDs."""
    f = seat.frame
    payload = (seat.window, f.focus, f.png_sha256, f.width, f.height,
               asdict(f.output), [asdict(e) for e in f.elements])
    return hashlib.sha256(json.dumps(payload, allow_nan=False).encode()).hexdigest()


def run_mouse_fixture(queue, errand, plan, *, capture, sink, owner_prompt,
                      principal, clock=time.monotonic):
    """Click-only tier-3 batch. No live adapter or remote approval path ships.

    Each canonical click has argv (window, role, name, before, after), with
    exact screen fingerprints as expected states. ``owner_prompt`` represents
    the trusted local seat in tests; it is not a daemon/model callback. The
    batch runs only while the errand still holds this exact digest and the
    burnt digest claim still binds that errand inside its expiry.
    """
    if type(queue) is not ParkedQueue or type(plan) is not Plan:
        raise TypeError("mouse fixture requires canonical plan and synthetic queue")
    digest = plan.digest

    def record(outcome):
        queue.record_observation(errand, 'mouse-fixture', digest, outcome)
        return outcome

    def check_stop():
        if clock() >= deadline or is_halted(queue.path.parent) or queue.cancelled(errand):
            raise PermissionError('kill')

    seen: set = set()
    newest = [float('-inf')]
    click_at = [None]

    def observe(window, expected, *, verifying_click=False):
        check_stop()
        seat = capture()
        check_stop()
        if (type(seat) is not MouseSeat or seat.unlocked is not True
                or seat.owner_present is not True or seat.safe_surface is not True
                or seat.window != window or not seat.frame.focus):
            raise PermissionError('unsafe-seat')
        frame = seat.frame
        at = frame.captured_at
        # Verification needs a fresh capture, taken after the click it verifies:
        # a cached or regressed buffer can never prove the click landed.
        if (type(frame.frame_id) is not str or not frame.frame_id or frame.frame_id in seen
                or type(at) not in (int, float) or not math.isfinite(at) or at <= newest[0]
                or (verifying_click and not at > click_at[0])):
            raise PermissionError('stale-frame')
        if mouse_screen(seat) != expected:
            raise PermissionError('unexpected-screen')
        seen.add(frame.frame_id)
        newest[0] = at
        return frame

    try:
        if principal != 'owner' or type(sink) is not FakeMouseInput:
            return record('refused/no-authority')
        if not queue.current(errand, digest):
            return record('refused/stale-plan')
        steps = plan.steps
        if not 1 <= len(steps) <= 12:
            return record('refused/click-budget')
        for step in steps:
            if (step.tool != 'click' or step.tier != 3 or step.env_diff or len(step.argv) != 5):
                return record('refused/invalid-click')
            window, role, name, before, after = step.argv
            if (not window or not re.fullmatch(r'button|push button|toggle button', role)
                    or not name.isprintable() or not re.search(r'[^\W\d_]', name)
                    or before == after or any(not re.fullmatch('[0-9a-f]{64}', h)
                                              for h in (before, after))):
                return record('refused/invalid-click')
        if any(a.argv[4] != b.argv[3] or a.argv[0] != b.argv[0]
               for a, b in zip(steps, steps[1:])):
            return record('refused/discontinuous-plan')
        deadline = clock() + 90
        observe(steps[0].argv[0], steps[0].argv[3])
        nonce = secrets.token_hex(16)
        # Exact canonical batch, not a summary or a reusable yes.
        if owner_prompt(plan.canonical.decode(), f'{digest} {nonce}') != f'{digest} {nonce}':
            return record('refused/unapproved')
        check_stop()
        if not queue.current(errand, digest):
            # superseded in errands while owner_prompt was waiting
            return record('refused/stale-plan')
        if not queue.claim_mouse_digest(errand, digest, len(steps)):
            return record('refused/replay-or-budget')
        record(f'approved/{nonce}')
        recent = []
        for step in steps:
            window, role, name, before, after = step.argv
            if not queue.claim_binds(errand, digest):
                raise PermissionError('stale-claim')
            # A plan superseded in `errands` while the batch was running (the
            # owner may revise an errand at any moment) must not click again:
            # re-checked per step, not only around the approval prompt.
            if not queue.current(errand, digest):
                raise PermissionError('stale-plan')
            frame = observe(window, before)
            matches = [e for e in frame.elements if (e.role, e.name) == (role, name)]
            if len(matches) != 1 or sum(e.id == matches[0].id for e in frame.elements) != 1:
                raise PermissionError('ungrounded')
            element = matches[0]
            triple = (window, element.id, before)
            if triple in recent:
                raise PermissionError('click-loop')
            recent.append(triple)
            record(f'click/{step.i}/before')
            # Recheck after the durable pre-action record; the click is grounded
            # on this fresh capture, never on the discarded first one.
            frame = observe(window, before)
            matches = [e for e in frame.elements if (e.role, e.name) == (role, name)]
            if (len(matches) != 1 or matches[0].id != element.id
                    or sum(e.id == element.id for e in frame.elements) != 1):
                raise PermissionError('ungrounded')
            resolution = ground(frame, dict(kind='element', id=element.id, confidence=1,
                                           frame_id=frame.frame_id, snapshot_id=frame.snapshot_id))
            if resolution is None:
                raise PermissionError('ungrounded')
            if adjudicate(step.tier, 3, _mouse_key=_MOUSE_FIXTURE_KEY).verdict != "ok":
                raise PermissionError("tier-3-refused")
            click_at[0] = clock()
            sink.click(resolution.point)
            observe(window, after, verifying_click=True)
            record(f'click/{step.i}/verified')
        return record('complete')
    except Exception as exc:
        # Unknown adapter/observation failures never retry or resume the batch.
        reason = str(exc) if type(exc) is PermissionError and str(exc) in {
            'kill', 'unsafe-seat', 'unexpected-screen', 'ungrounded', 'click-loop',
            'stale-frame', 'stale-claim', 'stale-plan'} else 'fixture-error'
        return record(f'halted/{reason}')
