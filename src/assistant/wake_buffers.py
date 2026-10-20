"""Always-on wake audio buffers — RAM only, crash-safe, never logged.

Two allocations live here, both anonymous `mmap` (no file backing anywhere,
`path` is always None and no code in this repo writes them to disk):

* **pre-wake ring** — a fixed-size circular buffer of at most 2.0 s of
  16 kHz mono PCM that is overwritten in place. It exists so the wake clip
  can include the fraction of a second BEFORE the keyword fired (people do
  not start words at frame zero). Pre-wake audio is never logged, never
  persisted, never shipped anywhere.
* **pending window** — 2–3 s captured AFTER a trigger, held until the
  voiceprint verdict decides its fate: inherited as the head of the command
  utterance (owner verified) or zeroed untranscribed (anything else).

Both request `MADV_DONTDUMP` on Linux so a core dump cannot resurrect the
audio. The flag is exposed (and reported by `assist hotword status` /
`assist doctor`) so "crash leaves nothing" is CHECKABLE, not believed.
"""

from __future__ import annotations

import mmap

SAMPLE_WIDTH = 2          # s16le
SAMPLE_RATE = 16000


def bytes_for(seconds: float, sample_rate: int = SAMPLE_RATE) -> int:
    return round(float(seconds) * sample_rate) * SAMPLE_WIDTH


class PcmRam:
    """Anonymous mmap'd PCM scratch. Supports write / read / zero only."""

    def __init__(self, size_bytes: int):
        self.size_bytes = max(0, int(size_bytes))
        self._buf = mmap.mmap(-1, self.size_bytes) if self.size_bytes else b""
        self.madv_dontdump = self._apply_dontdump()

    def _apply_dontdump(self) -> bool:
        try:
            advise = getattr(self._buf, "madvise", None)
            flag = getattr(mmap, "MADV_DONTDUMP", None)
            if advise is None or flag is None:
                return False
            advise(flag)
            return True
        except (OSError, ValueError, AttributeError, OverflowError):
            return False

    @property
    def path(self) -> None:
        """Always None. This buffer never has, and must never get, a path."""
        return None

    def write_at(self, offset: int, data: bytes) -> int:
        if not data:
            return 0
        data = bytes(data[: self.size_bytes - offset])
        self._buf[offset : offset + len(data)] = data
        return len(data)

    def read(self, size: int | None = None) -> bytes:
        if isinstance(self._buf, bytes):
            return b""
        n = self.size_bytes if size is None else min(size, self.size_bytes)
        return bytes(self._buf[:n])

    def zero(self) -> None:
        if isinstance(self._buf, bytes):
            return
        self._buf[:] = b"\x00" * self.size_bytes

    def close(self) -> None:
        try:
            if hasattr(self._buf, "close"):
                self._buf.close()
        except (OSError, ValueError, BufferError):
            pass


class PreWakeRing:
    """Fixed-capacity circular PCM overwrite buffer (<= 2.0 s by contract).

    The cap is enforced in the constructor regardless of config: a longer
    ring is pre-wake surveillance, not wake support.
    """

    MAX_SECONDS = 2.0

    def __init__(self, seconds: float, sample_rate: int = SAMPLE_RATE):
        seconds = min(float(seconds), self.MAX_SECONDS)
        self.seconds = max(0.0, seconds)
        self.sample_rate = sample_rate
        self.frame_bytes = SAMPLE_WIDTH
        self.capacity_bytes = bytes_for(self.seconds, sample_rate)
        self._ram = PcmRam(self.capacity_bytes)
        self._fill = 0          # bytes currently resident
        self._head = 0          # next write offset

    @property
    def path(self) -> None:
        return None

    @property
    def madv_dontdump(self) -> bool:
        return self._ram.madv_dontdump

    def append(self, frame: bytes) -> None:
        if self.capacity_bytes == 0 or not frame:
            return
        data = frame[: self.capacity_bytes]
        n = len(data)
        end = self._head + n
        if end <= self.capacity_bytes:
            self._ram.write_at(self._head, data)
        else:
            first = self.capacity_bytes - self._head
            self._ram.write_at(self._head, data[:first])
            self._ram.write_at(0, data[first:])
        self._head = (self._head + n) % self.capacity_bytes
        self._fill = min(self.capacity_bytes, self._fill + n)

    def snapshot(self) -> bytes:
        """Chronological copy of what is resident (oldest first)."""
        if self._fill < self.capacity_bytes:
            return self._ram.read(self._fill)
        raw = self._ram.read()
        return raw[self._head:] + raw[: self._head]

    def residence_s(self) -> float:
        return self._fill / (self.sample_rate * self.frame_bytes) \
            if self.sample_rate else 0.0

    def zero(self) -> None:
        self._ram.zero()
        self._fill = 0
        self._head = 0


class PendingWindow:
    """Post-trigger capture window (2–3 s by contract), append-only."""

    def __init__(self, seconds: float, sample_rate: int = SAMPLE_RATE):
        seconds = min(3.0, max(2.0, float(seconds)))
        self.seconds = seconds
        self.sample_rate = sample_rate
        self.capacity_bytes = bytes_for(self.seconds, sample_rate)
        self._ram = PcmRam(self.capacity_bytes)
        self._used = 0
        self._closed = False

    @property
    def path(self) -> None:
        return None

    @property
    def madv_dontdump(self) -> bool:
        return self._ram.madv_dontdump

    @property
    def full(self) -> bool:
        return self._used >= self.capacity_bytes or self._closed

    def append(self, frame: bytes) -> bool:
        """Returns True while there is room; the frame is dropped once full."""
        if self.full or not frame:
            return False
        room = self.capacity_bytes - self._used
        written = self._ram.write_at(self._used, frame[:room])
        self._used += written
        return True

    def data(self) -> bytes:
        return self._ram.read(self._used)

    def used_s(self) -> float:
        return self._used / (self.sample_rate * 2) if self.sample_rate else 0.0

    def close(self) -> None:
        """Stop accepting frames (window elapsed)."""
        self._closed = True

    def zero(self) -> None:
        self._ram.zero()
        self._used = 0
        self._closed = True
