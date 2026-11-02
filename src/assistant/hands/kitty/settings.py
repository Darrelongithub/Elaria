"""Strict separate kitty-bridge.toml settings; no changes to assistant config.toml."""
from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .transport import directory_fd


@dataclass(frozen=True)
class Settings:
    socket: Path
    passwords: tuple[tuple[str, Path], ...]
    journal: Path
    timeout_seconds: float = 5.0
    max_response_bytes: int = 8388608


def load_settings(path: Path) -> Settings:
    with directory_fd(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 16384):
                raise PermissionError('settings must be an owned regular 0600 file')
            raw = tomllib.load(source)
    required = {'socket', 'password_files', 'journal'}
    if not required <= raw.keys() or raw.keys() - required - {'timeout_seconds', 'max_response_bytes'}:
        raise ValueError('unknown/missing settings; hand-open and inline passwords are forbidden')
    if not isinstance(raw['password_files'], dict) or set(raw['password_files']) != {'K1', 'K2', 'K3'}:
        raise ValueError('three password file paths required')
    paths = [raw['socket'], raw['journal'], *raw['password_files'].values()]
    if any(not isinstance(p, str) or not Path(p).is_absolute() or '..' in Path(p).parts for p in paths):
        raise ValueError('absolute literal paths required; no environment or tilde expansion')
    timeout = raw.get('timeout_seconds', 5.0)
    size = raw.get('max_response_bytes', 8388608)
    if (type(timeout) not in {int, float} or not 0 < timeout <= 60
            or type(size) is not int or not 1024 <= size <= 67108864):
        raise ValueError('invalid transport bounds')
    return Settings(Path(raw['socket']), tuple((k, Path(v)) for k, v in raw['password_files'].items()),
                    Path(raw['journal']), timeout, size)
