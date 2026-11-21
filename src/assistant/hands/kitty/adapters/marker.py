"""create-marker assessment from reviewed v0.49.2 parser/dispatch/marker sources.

Literal text is escaped by upstream before regex compilation. Function markers run
Python files. Regex complexity is not proven by syntactic validity. Never execute,
import or read a requested marker file to assess it. This is NOT effect verification.
"""
from __future__ import annotations

from types import MappingProxyType

from .. import pin
from ..attribution import PHASES, attribute
from ..policy import Assessment, digest

ASSESSOR = 'kitty.create-marker/v1'
COMMIT = pin.UPSTREAM_COMMIT
# Reviewed dependency chain, not an assertion about the installed owner binary.
SOURCES = MappingProxyType(dict(pin.MARKER_SOURCES))


class CreateMarkerAdapter:
    """No runtime injection seam: NativeChecker constructs this exact family assessor."""
    def __call__(self, act, phase, targets, catalogue):
        # Missing or changed source identity is a REFUSAL, not a lower-confidence Yes.
        entry = catalogue.get('verbs', {}).get('create-marker', {})
        basis = {'catalogue_sha256': digest(catalogue)}

        def verdict(tier, nature, reason, *, denied=False):
            return attribute(Assessment(tier, nature, denied=denied), assessor=ASSESSOR,
                             reason=reason, act=act, phase=phase, targets=targets, basis=basis)

        if (catalogue.get('upstream_version') != pin.UPSTREAM_VERSION
                or catalogue.get('upstream_commit') != COMMIT
                or entry.get('source') != 'kitty/rc/create_marker.py'
                or entry.get('source_sha256') != SOURCES['kitty/rc/create_marker.py']):
            return verdict(None, 'unknown', 'marker-source-evidence-missing-or-stale', denied=True)
        basis['source_review_sha256'] = digest({'commit': COMMIT, 'sources': dict(SOURCES)})
        if act.verb != 'create-marker' or phase not in PHASES:
            return verdict(None, 'unknown', 'marker-context-invalid', denied=True)
        # Defensive independent input validation, even when invoked outside NativeChecker.
        from ..checker import validate_payload
        try:
            validate_payload(act, catalogue)
        except (TypeError, ValueError, PermissionError):
            return verdict(None, 'unknown', 'marker-wire-invalid', denied=True)
        spec = act.payload.get('marker_spec')
        if not spec:
            return verdict(None, 'unknown', 'marker-spec-evidence-missing', denied=True)
        kind, *parts = spec
        if kind == 'function':
            # runpy.run_path is legacy evaluation T3 even if owner approves the exact file.
            return verdict(3, 'unknown', 'marker-python-evaluation-forbidden', denied=True)
        if kind in {'regex', 'iregex'}:
            return verdict(None, 'unknown', 'marker-regex-cost-evidence-missing', denied=True)
        if kind not in {'text', 'itext'}:
            return verdict(None, 'unknown', 'marker-semantics-evidence-missing', denied=True)
        if not parts or len(parts) % 2:
            return verdict(None, 'unknown', 'marker-pairs-invalid', denied=True)
        # These are conservative parser bounds, not a task/content whitelist. Nothing
        # evaluates the literal, including shell syntax, regex operators or path strings.
        if len(parts) > 64 or sum(map(len, parts)) > 4096:
            return verdict(None, 'unknown', 'marker-parser-bound-exceeded', denied=True)
        for color, text in zip(parts[::2], parts[1::2], strict=True):
            if color not in {'1', '2', '3'} or not text or '\x00' in text:
                return verdict(None, 'unknown', 'marker-literal-form-unproven', denied=True)
        if not act.target_ids:
            return verdict(None, 'unknown', 'marker-target-evidence-missing', denied=True)
        # Plan phase precedes the observational ls probe. It classifies ONLY the effect
        # grammar; disclosure/pre-exec must additionally bind the resolved observations.
        if phase != 'plan' and (not targets or {w['id'] for w in targets} != set(act.target_ids)):
            return verdict(None, 'unknown', 'marker-target-evidence-missing', denied=True)
        return verdict(1, 'reversible', 'marker-escaped-literal-highlight')
