"""Only a fake runner ships. No subprocess, shell, execve, network or live adapter."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .gate import child_environment
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
