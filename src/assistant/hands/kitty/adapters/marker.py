"""create-marker assessment from reviewed 0.47.1 parser/dispatch/marker sources.

Literal text is escaped by upstream before regex compilation. Function markers run
Python files. Regex complexity is not proven by syntactic validity. Never execute,
import or read a requested marker file to assess it. This is NOT effect verification.
"""
from __future__ import annotations

from types import MappingProxyType

from ..attribution import PHASES, attribute
from ..policy import Assessment, digest

ASSESSOR = 'kitty.create-marker/v1'
COMMIT = 'fb5255b1ae4f0249ba832d6a773348fd103449ce'
# Reviewed dependency chain, not an assertion about the installed owner binary.
SOURCES = MappingProxyType({
    'kitty/rc/create_marker.py': 'ac844de07cd150c10ab76ca43685ef6bbe0ee7c6ea7baab67773205dd7989e90',
    'kitty/options/utils.py': '8a5a7ec2dca9f4d18fa68c5d9bfc9591281c66ed378ce227161df98472f0afa2',
    'kitty/window.py': '6e1b33931d3a3795bf082a886ed946b2f0a954a7e4171d4ba5e57bd1145ff846',
    'kitty/marks.py': 'e4c5e9bbc0f4e4cc412c0dd97becb86d8ceeaf9d4c91d4c533f1946b4b99f6e2',
})


class CreateMarkerAdapter:
    """No runtime injection seam: NativeChecker constructs this exact family assessor."""
    def __call__(self, act, phase, targets, catalogue):
        # Missing or changed source identity is a REFUSAL, not a lower-confidence Yes.
        entry = catalogue.get('verbs', {}).get('create-marker', {})
        basis = {'catalogue_sha256': digest(catalogue)}

        def verdict(tier, nature, reason, *, denied=False):
            return attribute(Assessment(tier, nature, denied=denied), assessor=ASSESSOR,
                             reason=reason, act=act, phase=phase, targets=targets, basis=basis)

        if (catalogue.get('upstream_version') != '0.47.1'
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
