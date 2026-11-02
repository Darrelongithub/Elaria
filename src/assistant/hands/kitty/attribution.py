"""Metadata-only assessment receipts; shared formatting, NEVER shared assessment.

A reference commits to the decision, source review and exact act/observations, not to
owner consent. Receipts contain digests, never terminal content, argv or passwords.
They prove attribution/binding, not that upstream matches an installed owner binary.
"""
from __future__ import annotations

import re
from dataclasses import replace

from .policy import Assessment, digest, fingerprint

TOKEN = re.compile(r'[a-z0-9][a-z0-9./-]{0,127}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
PHASES = frozenset({'plan', 'disclose', 'pre-exec', 'pre-send'})


def attribute(result, *, assessor, reason, act, phase, targets, basis):
    """Attach an immutable receipt to a decision ALREADY made by a specific assessor."""
    evidence = tuple(sorted(dict(basis, act_sha256=digest({
        'verb': act.verb, 'payload': act.payload, 'target_ids': act.target_ids,
        'nonce': act.nonce}), targets_sha256=fingerprint(targets)).items()))
    result = replace(result, assessor=assessor, reason=reason, evidence=evidence)
    receipt = receipt_body(result, phase)
    return replace(result, evidence_ref=digest(receipt))


def receipt_body(result, phase):
    return {'assessor': result.assessor, 'reason': result.reason, 'assessment_phase': phase,
            'legacy_tier': result.legacy_tier, 'nature': result.nature, 'denied': result.denied,
            'bracketed_paste': result.bracketed_paste, 'evidence': dict(result.evidence)}


def trace(result, phase):
    """Reject malformed receipts before persistence/dispatch. Legacy stub seams are marked."""
    if (not isinstance(result, Assessment) or phase not in PHASES
            or type(result.denied) is not bool or type(result.bracketed_paste) is not bool
            or result.nature not in {'observational', 'reversible', 'irreversible', 'credential-access', 'unknown'}
            or (result.legacy_tier is not None and
                (type(result.legacy_tier) is not int or result.legacy_tier not in range(4)))):
        raise ValueError('invalid assessment receipt')
    if result.assessor is None:
        if result.reason is not None or result.evidence_ref is not None or result.evidence:
            raise ValueError('partial assessment receipt')
        return {'assessor': 'unattributed-library-checker', 'reason': 'no-attribution-supplied',
                'assessment_phase': phase, 'evidence_ref': None, 'evidence': {},
                'legacy_tier': result.legacy_tier, 'nature': result.nature,
                'denied': result.denied, 'bracketed_paste': result.bracketed_paste}
    if (not TOKEN.fullmatch(result.assessor) or not isinstance(result.reason, str)
            or not TOKEN.fullmatch(result.reason) or type(result.evidence) is not tuple
            or any(type(pair) is not tuple or len(pair) != 2
                   or not isinstance(pair[0], str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', pair[0])
                   or not isinstance(pair[1], str) or not SHA.fullmatch(pair[1])
                   for pair in result.evidence)
            or len(dict(result.evidence)) != len(result.evidence)):
        raise ValueError('invalid assessment attribution')
    body = receipt_body(result, phase)
    if result.evidence_ref != digest(body):
        raise ValueError('assessment evidence reference mismatch')
    return body | {'evidence_ref': result.evidence_ref}


def validate_trace(receipt):
    """Verify metadata shape/reference when opening the durable ledger, without authorizing."""
    keys = {'assessor', 'reason', 'assessment_phase', 'legacy_tier', 'nature', 'denied',
            'bracketed_paste', 'evidence', 'evidence_ref'}
    if type(receipt) is not dict or set(receipt) != keys or type(receipt['evidence']) is not dict:
        raise ValueError('invalid persisted assessment')
    unattributed = receipt['assessor'] == 'unattributed-library-checker'
    result = Assessment(receipt['legacy_tier'], receipt['nature'], receipt['denied'],
                        receipt['bracketed_paste'],
                        None if unattributed else receipt['assessor'],
                        None if unattributed else receipt['reason'], receipt['evidence_ref'],
                        tuple(sorted(receipt['evidence'].items())))
    if trace(result, receipt['assessment_phase']) != receipt:
        raise ValueError('persisted assessment mismatch')
