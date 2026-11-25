"""Point-only orchestration. No pointer injection and no provider egress."""
from __future__ import annotations

import asyncio
import time
from subprocess import SubprocessError

from . import observation


def draw(surface, frame, target, *, reduced_motion=False):
    resolution = observation.ground(frame, target)
    if resolution is None:
        return None
    x, y, w, h = resolution.bbox
    ox, oy, _, _ = frame.output.bounds
    surface.send('pointAt', frame.output.name, x-ox, y-oy, w, h,
                 resolution.label or 'sure', 12000, int(reduced_motion))
    return resolution


class Pointer:
    def __init__(self, surface, *, capture=observation.capture, desktop=observation._desktop):
        self.surface = surface
        self.capture = capture
        self.desktop = desktop
        self.lock = asyncio.Lock()
        self.watcher = None

    async def _watch(self, frame, permitted):
        try:
            while time.monotonic() - frame.captured_at < 12:
                await asyncio.sleep(.25)
                focus, output, _ = await asyncio.to_thread(self.desktop)
                if not permitted() or (focus, output) != (frame.focus, frame.output):
                    break
        except (ValueError, KeyError, StopIteration, RuntimeError, OSError, SubprocessError):
            # Lost compositor evidence: clear the marker.
            pass
        async with self.lock:
            if self.watcher is not asyncio.current_task():
                return
            try:
                await asyncio.to_thread(self.surface.send, 'clearPoint')
            except (OSError, SubprocessError):
                # The surface-side TTL still expires independently.
                pass


    async def point(self, name, *, reduced_motion=False, permitted=lambda: True):
        async with self.lock:
            if self.watcher is not None:
                self.watcher.cancel()
                await asyncio.gather(self.watcher, return_exceptions=True)
                self.watcher = None
            await asyncio.to_thread(self.surface.send, 'clearPoint')
            if not permitted() or observation.SECRET.search(name):
                return None
            await asyncio.to_thread(self.surface.send, 'suspendPill', 1)
            try:
                await asyncio.sleep(.12)
                frame, pixels = await asyncio.to_thread(self.capture)
                del pixels  # No pinned vision role: zero calls, zero image egress.
            finally:
                await asyncio.to_thread(self.surface.send, 'suspendPill', 0)
            target = observation.semantic_target(frame, name)
            if target is None or not permitted():
                return None
            resolution = await asyncio.to_thread(draw, self.surface, frame, target,
                                                 reduced_motion=reduced_motion)
            if resolution is not None:
                self.watcher = asyncio.create_task(self._watch(frame, permitted))
            return resolution
