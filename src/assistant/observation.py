"""Read-only observation contract shared by pointer and future mouse consumers.

Frames confer no authority. Coordinates in resolutions are desktop logical
pixels; vision coordinates are fractions of the captured output, never IDs.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import journal_log
from .disclosure import SECRET_PATTERNS

NOT_FOUND = "I couldn't find it"
SECRET = re.compile('|'.join((*SECRET_PATTERNS, r'\b(?:card|otp|ssn|seed|recovery)\b')), re.IGNORECASE)
Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class Output:
    name: str
    bounds: Rect
    scale: float


@dataclass(frozen=True)
class Element:
    id: str
    name: str
    role: str
    bounds: Rect
    sensitive: bool = False


@dataclass(frozen=True)
class Frame:
    frame_id: str
    snapshot_id: str
    png_sha256: str
    width: int
    height: int
    output: Output
    captured_at: float
    elements: tuple[Element, ...]
    focus: str

    def capture_pixel(self, x: float, y: float) -> tuple[float, float]:
        ox, oy, ow, oh = self.output.bounds
        return ((x - ox) * self.width / ow, (y - oy) * self.height / oh)


@dataclass(frozen=True)
class Resolution:
    frame_id: str
    snapshot_id: str
    bbox: Rect
    confidence: float
    source: str

    @property
    def point(self) -> tuple[float, float]:
        x, y, w, h = self.bbox
        return x + w / 2, y + h / 2

    @property
    def label(self) -> str:
        parts = []
        if self.source == 'vision':
            parts.append('unidentified')
        if self.confidence < .6:
            parts.append('best guess')
        return ' · '.join(parts)


def _intersects(a: Rect, b: Rect) -> bool:
    x, y, w, h = a
    X, Y, W, H = b
    return x < X + W and X < x + w and y < Y + H and Y < y + h


def _contains(outer: Rect, inner: Rect) -> bool:
    """Whether the full inner rectangle lies within the outer rectangle."""
    if not all(math.isfinite(value) for value in (*outer, *inner)):
        return False
    x, y, w, h = outer
    X, Y, W, H = inner
    return (w > 0 and h > 0 and W > 0 and H > 0
            and x <= X and y <= Y and X + W <= x + w and Y + H <= y + h)


_ACTIONABLE_ROLES = frozenset({
    'button', 'push button', 'toggle button', 'menu button',
    'menu item', 'check menu item', 'radio menu item', 'tearoff menu item',
    'check box', 'checkbox', 'radio button', 'link', 'page tab', 'tab',
    'combo box', 'list box', 'list item', 'tree item', 'option',
    'entry', 'text', 'password text', 'spin button', 'slider', 'scroll bar', 'switch',
})


def _is_actionable(element: Element) -> bool:
    role = ' '.join(element.role.casefold().replace('_', ' ').replace('-', ' ').split())
    return role in _ACTIONABLE_ROLES


def _sensitive(element: Element) -> bool:
    return element.sensitive or bool(SECRET.search(f'{element.name} {element.role}'))


def ground(frame: Frame, target: dict) -> Resolution | None:
    """Pure validator. Do not promote image guesses to verified controls."""
    if (target.get('frame_id'), target.get('snapshot_id')) != (frame.frame_id, frame.snapshot_id):
        return None
    c = target.get('confidence')
    if type(c) not in (int, float) or not 0 <= c <= 1 or target.get('sensitive', False) is not False:
        return None
    ox, oy, ow, oh = frame.output.bounds
    if target.get('kind') == 'element':
        element = next((e for e in frame.elements if e.id == target.get('id')), None)
        if element is None or c < .3 or _sensitive(element):
            return None
        rect, source = element.bounds, 'atspi'
    elif target.get('kind') == 'bbox':
        # No independent vision verifier in this lane: always enforce .5 (and .4).
        if c < .4 or c < .5 or SECRET.search(str(target.get('label', ''))):
            return None
        coords = [target.get(key) for key in ('x', 'y', 'w', 'h')]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in coords):
            return None
        x, y, w, h = coords
        if not (.00002 <= w * h <= .25 and w > 0 and h > 0
                and x >= -.05 and y >= -.05 and x+w <= 1.05 and y+h <= 1.05):
            return None
        l, t = max(0, x), max(0, y)
        w, h = min(1, x+w)-l, min(1, y+h)-t
        if w <= 0 or h <= 0 or w*h < .00002:
            return None
        rect, source = (ox+l*ow, oy+t*oh, w*ow, h*oh), 'vision'
    else:
        return None
    x, y, w, h = rect
    if not (0 < w*h <= ow*oh*.25 and w > 0 and h > 0
            and ox <= x <= ox+ow-w and oy <= y <= oy+oh-h):
        return None
    if any(_sensitive(e) and _intersects(rect, e.bounds) for e in frame.elements):
        return None
    return Resolution(frame.frame_id, frame.snapshot_id, rect, c, source)


def semantic_target(frame: Frame, name: str) -> dict | None:
    """Resolve exact names, collapsing contained label duplicates into controls."""
    matches = [e for e in frame.elements if e.name.casefold().strip() == name.casefold().strip()]
    if not matches:
        return None
    if len(matches) == 1:
        selected = matches[0]
    else:
        actionable = [
            element for element in matches
            if _is_actionable(element)
            and all(_contains(element.bounds, match.bounds) for match in matches)
        ]
        if len(actionable) != 1:
            return None
        selected = actionable[0]
    return {'kind': 'element', 'id': selected.id, 'confidence': 1,
            'frame_id': frame.frame_id, 'snapshot_id': frame.snapshot_id}


def _run(args, timeout=3):
    return subprocess.run(args, check=True, capture_output=True, timeout=timeout).stdout


def _desktop():
    window = json.loads(_run(['hyprctl', 'activewindow', '-j']))
    monitors = json.loads(_run(['hyprctl', 'monitors', '-j']))
    m = next((m for m in monitors if m['id'] == window.get('monitor')), None)
    if m is None or not window.get('address'):
        raise ValueError('no focused output')
    w, h = m['width'], m['height']
    if m['transform'] % 2:
        w, h = h, w
    scale = m['scale']
    return window['address'], Output(m['name'], (m['x'], m['y'], w/scale, h/scale), scale), len(monitors)


def _helper(mode):
    return ['/usr/bin/python3', str(Path(__file__).with_name('_observation_linux.py')), mode]


def _elements():
    window = json.loads(_run(['hyprctl', 'activewindow', '-j']))
    result = json.loads(_run([*_helper('atspi'), str(window['pid']),
                           *map(str, window['at'] + window['size'])]))
    if result['rejections']:
        journal_log.log_event("observation.atspi.windows", level="warn", verdict="rejected",
                              detail=json.dumps(result['rejections'], sort_keys=True))
    return tuple(Element(str(i), name, role, tuple(rect), sensitive)
                 for i, (name, role, rect, sensitive) in enumerate(result['rows']))


def _screenshot(output: Output, monitor_count: int):
    if monitor_count == 1:
        # Exit 3 means portal unavailable; cancellation/denial/timeouts MUST NOT
        # be bypassed with grim. The helper owns and unlinks the portal file.
        try:
            return _run(_helper('portal'), timeout=20)
        except subprocess.CalledProcessError as exc:
            if exc.returncode != 3:
                raise
    # Portal Screenshot has no output selector. Never map a desktop mosaic
    # onto one monitor. grim targets exactly the authorized focused output.
    with tempfile.TemporaryDirectory(prefix='elaria-frame-') as tmp:
        path = Path(tmp) / 'frame.png'
        _run(['grim', '-o', output.name, str(path)])
        with path.open('rb') as stream:
            return stream.read(32 * 1024 * 1024 + 1)


def capture(*, desktop=_desktop, screenshot=_screenshot, elements=_elements):
    """Capture once after caller authorization. Bytes are ephemeral, not in Frame."""
    focus, output, count = desktop()
    try:
        snapshot = elements()
    except (OSError, subprocess.SubprocessError) as exc:
        journal_log.log_event("observation.atspi.snapshot", level="warn", verdict="unavailable",
                              detail=type(exc).__name__)
        snapshot = ()
    pixels = screenshot(output, count)
    if desktop() != (focus, output, count):
        raise ValueError('focus or output changed during observation')
    if not 24 <= len(pixels) <= 32 * 1024 * 1024 or pixels[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('invalid screenshot')
    if pixels[12:16] != b'IHDR':
        raise ValueError('missing PNG header')
    width, height = struct.unpack('>II', pixels[16:24])
    if (width, height) != tuple(round(v * output.scale) for v in output.bounds[2:]):
        raise ValueError('capture does not match output geometry')
    return Frame(uuid.uuid4().hex, uuid.uuid4().hex, hashlib.sha256(pixels).hexdigest(),
                 width, height, output, time.monotonic(), snapshot, focus), pixels
