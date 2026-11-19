"""R5 canonical, immutable plans. No executable text interpolation."""
from __future__ import annotations

import json
import shlex
from dataclasses import dataclass

from assistant.indexer import sha256_bytes


def text(value: object) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("expected NUL-free UTF-8 text")
    value.encode("utf-8", errors="strict")
    return value


@dataclass(frozen=True)
class Step:
    i: int
    tier: int | None
    tool: str
    argv: tuple[str, ...]
    cwd: str
    env_diff: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if type(self.i) is not int or self.i < 0:
            raise ValueError("invalid step index")
        if self.tier is not None and (type(self.tier) is not int or self.tier not in range(4)):
            raise ValueError("malformed tier evidence")
        if not text(self.tool) or not text(self.cwd):
            raise ValueError("tool and cwd are required")
        if type(self.argv) is not tuple or not self.argv:
            raise ValueError("argv must be a nonempty immutable array")
        for arg in self.argv:
            text(arg)
        if type(self.env_diff) is not tuple:
            raise ValueError("env_diff must be immutable")
        for item in self.env_diff:
            if type(item) is not tuple or len(item) != 2:
                raise ValueError("invalid env pair")
            key, value = item
            if not text(key) or "=" in key:
                raise ValueError("invalid env name")
            text(value)
        if len(dict(self.env_diff)) != len(self.env_diff):
            raise ValueError("duplicate env names")

    def as_dict(self):
        return {"i": self.i, "tier": self.tier, "tool": self.tool,
                "argv": list(self.argv), "cwd": self.cwd, "env_diff": dict(self.env_diff)}

    def disclosure(self):
        # Display ONLY. Never pass this string to any runner.
        return {"argv": shlex.join(self.argv), "cwd": self.cwd,
                "env_diff": dict(self.env_diff)}


@dataclass(frozen=True)
class Plan:
    steps: tuple[Step, ...]

    def __post_init__(self):
        if type(self.steps) is not tuple or not self.steps:
            raise ValueError("plan requires immutable steps")
        if any(type(s) is not Step or s.i != i for i, s in enumerate(self.steps)):
            raise ValueError("steps must have unique consecutive indices")

    @property
    def canonical(self) -> bytes:
        return json.dumps({"steps": [s.as_dict() for s in self.steps]}, ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

    @property
    def digest(self) -> str:
        return sha256_bytes(self.canonical)

    @classmethod
    def parse(cls, data: bytes | str):
        def unique(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ValueError("duplicate JSON key")
                obj[key] = value
            return obj
        raw = json.loads(data, object_pairs_hook=unique)
        if type(raw) is not dict or set(raw) != {"steps"} or type(raw["steps"]) is not list:
            raise ValueError("invalid plan shape")
        steps = []
        for item in raw["steps"]:
            if type(item) is not dict or set(item) != {"i", "tier", "tool", "argv", "cwd", "env_diff"}:
                raise ValueError("invalid step shape")
            if type(item["argv"]) is not list or type(item["env_diff"]) is not dict:
                raise ValueError("argv/env_diff shape")
            steps.append(Step(item["i"], item["tier"], item["tool"], tuple(item["argv"]),
                              item["cwd"], tuple(sorted(item["env_diff"].items()))))
        return cls(tuple(steps))
