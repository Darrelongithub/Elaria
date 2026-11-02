"""Private durable JSONL kitty.act sink for a trusted service, not an errand tool.

No auto-creation of parent dirs; owner provisions them. Console adapters can render
these events later; no frozen registry/console changes or claimed UI delivery.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from .transport import directory_fd


class EventJournal:
    def __init__(self, path: Path):
        self.path = path

    def __call__(self, event):
        if event.get('kind') != 'kitty.act':
            raise ValueError('unexpected journal kind')
        wire = (json.dumps(event, ensure_ascii=True, allow_nan=False, sort_keys=True) + '\n').encode()
        with directory_fd(self.path.parent) as parent:
            info = os.fstat(parent)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise PermissionError('journal directory must be owned 0700')
            fd = os.open(self.path.name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
                         | os.O_NONBLOCK, 0o600, dir_fd=parent)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                    raise PermissionError('journal must be an owned single-link regular 0600 file')
                remaining = memoryview(wire)
                while remaining:
                    written = os.write(fd, remaining)
                    if written <= 0:
                        raise OSError('incomplete journal write')
                    remaining = remaining[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
