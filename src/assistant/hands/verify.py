"""Independent re-read verification, never return-code-only success."""
from dataclasses import dataclass
from pathlib import Path

from assistant.safety import assert_within_sandbox, try_sha256_file


@dataclass(frozen=True)
class Expected:
    path: Path
    digest: str | None
    exists: bool = True


def verify(space, expected: tuple[Expected, ...]) -> bool:
    if not expected:
        return False
    for item in expected:
        path = assert_within_sandbox(item.path, space.work)
        if path.exists() != item.exists:
            return False
        if item.exists and (item.digest is None or try_sha256_file(path) != item.digest):
            return False
    return True


def operation_expectations(space, step) -> tuple[Expected, ...]:
    if step.tool not in {"move", "resolve_collision", "trash"}:
        return ()
    cwd = Path(step.cwd)
    src = assert_within_sandbox(cwd / step.argv[0], space.work)
    doc = space.store.document_by_path(str(src))
    if doc is None or doc["sha256"] != try_sha256_file(src):
        raise PermissionError("unindexed or changed source")
    if step.tool == "trash":
        return (Expected(src, None, False),)
    dest = assert_within_sandbox(cwd / step.argv[-1], space.work)
    expected = [Expected(src, None, False), Expected(dest, doc["sha256"])]
    if step.tool == "resolve_collision":
        old = assert_within_sandbox(cwd / step.argv[1], space.work)
        expected.append(Expected(old, try_sha256_file(old)))
    return tuple(expected)
