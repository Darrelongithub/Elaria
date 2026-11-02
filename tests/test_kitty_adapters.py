"""Family assessment doctrine: missing evidence is the primary refusal test, not a fallback.

All targets, contents and RC peers are synthetic. No upstream marker code is run.
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest
from test_kitty_hands import FakeKitty
from test_kitty_hands import private as private  # noqa: PLC0414 - pytest fixture registration
from test_kitty_host import build_session, prepare

from assistant.hands.kitty.adapters.marker import ASSESSOR, SOURCES, CreateMarkerAdapter
from assistant.hands.kitty.attribution import trace, validate_trace
from assistant.hands.kitty.bridge import Bridge, windows_from_ls
from assistant.hands.kitty.checker import OPAQUE, NativeChecker
from assistant.hands.kitty.policy import (
    Act,
    Assessment,
    Consent,
    canonical,
    digest,
    fingerprint,
    inventory,
)
from assistant.hands.kitty.recovery import RecoveryLedger


def marker(spec=None, ids=(1,), **extra):
    return Act('create-marker', canonical({'marker_spec': spec if spec is not None else ['text', '1', 'synthetic'],
                                         'match': 'id:1', **extra}), ids, 'a' * 32)


def targets():
    return windows_from_ls(FakeKitty().request('ls', {}, 'K1'))


@pytest.mark.parametrize('missing', ['version', 'commit', 'entry', 'source', 'hash'])
def test_marker_refuses_when_its_source_evidence_is_missing(missing):
    catalogue = inventory()
    if missing in {'version', 'commit'}:
        catalogue.pop('upstream_' + missing)
    elif missing == 'entry':
        catalogue['verbs'].pop('create-marker')
    else:
        catalogue['verbs']['create-marker'].pop('source' if missing == 'source' else 'source_sha256')
    result = CreateMarkerAdapter()(marker(), 'plan', (), catalogue)
    assert result.denied and result.legacy_tier is None
    assert result.assessor == ASSESSOR
    assert result.reason == 'marker-source-evidence-missing-or-stale'
    assert result.evidence_ref and 'source_review_sha256' not in dict(result.evidence)
    validate_trace(trace(result, 'plan'))


@pytest.mark.parametrize('key,value', [('upstream_version', 'future'), ('upstream_commit', '0' * 40)])
def test_marker_changed_pin_is_not_assumed_compatible(key, value):
    catalogue = inventory()
    catalogue[key] = value
    assert CreateMarkerAdapter()(marker(), 'plan', (), catalogue).denied


@pytest.mark.parametrize('phase', ['disclose', 'pre-exec', 'pre-send'])
def test_marker_refuses_when_target_observation_is_missing(phase):
    result = NativeChecker()(marker(), phase, ())
    assert result.denied and result.reason == 'marker-target-evidence-missing'
    assert result.assessor == ASSESSOR and result.evidence_ref


def test_marker_refuses_missing_spec_evidence():
    result = NativeChecker()(marker([]), 'plan', ())
    assert result.denied and result.reason == 'marker-spec-evidence-missing'


@pytest.mark.parametrize('spec,reason', [
    (['function', '/synthetic/marker.py'], 'marker-python-evaluation-forbidden'),
    (['regex', '1', '(a+)+$'], 'marker-regex-cost-evidence-missing'),
    (['iregex', '1', 'simple'], 'marker-regex-cost-evidence-missing'),
    (['new-mode', '1', 'simple'], 'marker-semantics-evidence-missing'),
    (['text'], 'marker-pairs-invalid'),
    (['text', '1'], 'marker-pairs-invalid'),
    (['text', '0', 'simple'], 'marker-literal-form-unproven'),
    (['text', '1', ''], 'marker-literal-form-unproven'),
    (['text', '1', '\x00'], 'marker-literal-form-unproven'),
    (['text', '1', 'x' * 4097], 'marker-parser-bound-exceeded'),
])
def test_marker_uncertain_or_executable_forms_refuse_with_specific_reason(spec, reason):
    result = NativeChecker()(marker(spec), 'plan', ())
    assert result.denied and result.reason == reason and result.assessor == ASSESSOR
    if spec[0] == 'function':
        assert result.legacy_tier == 3


@pytest.mark.parametrize('kind', ['text', 'itext'])
@pytest.mark.parametrize('literal', ['ordinary words', '$(touch /synthetic/never)', '(a+)+$', '../not-a-file'])
def test_literal_grammar_not_a_content_or_task_whitelist(kind, literal):
    result = NativeChecker()(marker([kind, '1', literal, '3', 'another']), 'pre-exec', targets())
    assert not result.denied and result.legacy_tier == 1 and result.nature == 'reversible'
    assert result.reason == 'marker-escaped-literal-highlight'
    assert literal not in canonical(trace(result, 'pre-exec'))


def test_marker_cannot_be_reused_as_generic_adapter():
    act = Act('action', canonical({'action': 'synthetic'}), (1,))
    result = CreateMarkerAdapter()(act, 'plan', (), inventory())
    assert result.denied and result.reason == 'marker-context-invalid'


def test_exact_plan_target_and_phase_bind_receipt():
    checker = NativeChecker()
    act = marker()
    a = checker(act, 'pre-exec', targets())
    values = [checker(marker(['text', '1', 'different']), 'pre-exec', targets()),
              checker(replace(act, nonce='b' * 32), 'pre-exec', targets()),
              checker(act, 'disclose', targets()),
              checker(act, 'pre-exec', [targets()[0] | {'pid': 999}])]
    assert all(x.evidence_ref != a.evidence_ref for x in values)
    assert a.evidence_ref == checker(act, 'pre-exec', targets()).evidence_ref
    assert dict(a.evidence)['source_review_sha256']
    assert inventory()['verbs']['create-marker']['source_sha256'] == SOURCES['kitty/rc/create_marker.py']


@pytest.mark.parametrize('change', [{'reason': 'invented'}, {'evidence_ref': '0' * 64},
                                  {'denied': True}, {'legacy_tier': 0}, {'evidence': ()}])
def test_modified_receipt_rejected(change):
    result = NativeChecker()(marker(), 'plan', ())
    with pytest.raises(ValueError):
        trace(replace(result, **change), 'plan')


def test_mounted_marker_attribution_before_dispatch_and_never_effect_proof(private):
    fake = FakeKitty()
    session = build_session(private, fake)
    try:
        description = session.prepare(prepare('create-marker', marker().payload, [1], 1))
        assert description['tier'] == 'K2'
        session.bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference='synthetic-hand')
        result = session.run(description['plan_hash'])
        assert result['verification'] == 'unverified'
        records = session.ledger.records
        assessments = [r for r in records if r['phase'] == 'assessment']
        assert [r['assessment']['assessment_phase'] for r in assessments] == [
            'plan', 'disclose', 'plan', 'pre-exec']
        assert all(r['assessment']['assessor'] == ASSESSOR and r['assessment']['evidence_ref']
                   and r['consent_ref'] is None for r in assessments)
        intent = next(i for i, r in enumerate(records) if r['verb'] == 'create-marker' and r['phase'] == 'intent')
        assert records[intent - 2]['phase'] == 'assessment'  # R3 gate record follows assessment
        assert any(c[0] == 'create-marker' for c in fake.calls)
    finally:
        session.close()


def test_k2_hand_still_required_despite_positive_marker_assessment(private):
    session = build_session(private)
    try:
        description = session.prepare(prepare('create-marker', marker().payload, [1], 1))
        with pytest.raises(RuntimeError):
            session.run(description['plan_hash'])
        assert all(c[0] != 'create-marker' for c in session.bridge.transport.calls)
    finally:
        session.close()


@pytest.mark.parametrize('missing', ['source', 'target'])
def test_owner_yes_never_overrides_missing_marker_evidence(missing):
    fake, events, checker = FakeKitty(), [], NativeChecker()
    act = marker()
    plan = act.plan(1)
    if missing == 'source':
        checker.catalogue['verbs']['create-marker'].pop('source_sha256')
    else:
        fake.windows.clear()
    bridge = Bridge(fake, checker, events.append)
    bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference='synthetic-hand')
    bridge.authorizer.decide(Consent('synthetic-consent', plan.digest, fingerprint(targets()), digest(act.payload)),
                             owner_answer='yes')
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert all(c[0] != 'create-marker' for c in fake.calls)
    assert events[-1]['verification'] == 'refused'


def test_function_marker_t3_not_overridden_by_yes_or_hand():
    fake, events = FakeKitty(), []
    bridge = Bridge(fake, NativeChecker(), events.append)
    act = marker(['function', '/synthetic/no-read.py'])
    plan = act.plan(2)
    bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference='synthetic-hand')
    bridge.authorizer.decide(Consent('synthetic-consent', plan.digest, fingerprint(targets()), digest(act.payload)),
                             owner_answer='yes')
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert fake.calls == []
    receipt = events[0]['assessment']
    assert receipt['legacy_tier'] == 3 and receipt['denied']
    assert receipt['reason'] == 'marker-python-evaluation-forbidden'


def test_assessment_write_failure_blocks_dispatch():
    fake = FakeKitty()
    def failed(event):
        if event['phase'] == 'assessment':
            raise OSError('synthetic unavailable journal')
    bridge = Bridge(fake, NativeChecker(), failed)
    act = marker()
    bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference='synthetic-hand')
    with pytest.raises(RuntimeError):
        bridge.execute(act, act.plan(1))
    assert fake.calls == []


def test_assessment_records_survive_restart_without_becoming_consent(private):
    session = build_session(private)
    path = private / 'kitty.jsonl'
    try:
        description = session.prepare(prepare('create-marker', marker().payload, [1], 1))
        original = [r for r in session.ledger.records if r['phase'] == 'assessment']
    finally:
        session.close()
    reopened = build_session(private)
    try:
        assert [r for r in reopened.ledger.records if r['phase'] == 'assessment'] == original
        assert not reopened.bridge.authorizer.consent and not reopened.bridge.authorizer.hand_ref
        assert description['plan_hash'] not in reopened.bridge.authorizer.consumed
    finally:
        reopened.close()
    lines = path.read_text().splitlines()
    record = json.loads(lines[0])
    record['assessment']['reason'] = 'tampered'
    lines[0] = json.dumps(record)
    path.write_text('\n'.join(lines) + '\n')
    with pytest.raises(ValueError):
        RecoveryLedger(path)


def test_literal_and_program_content_absent_from_durable_assessment(private):
    fake = FakeKitty()
    fake.windows[0]['cmdline'] = ['/synthetic/program', 'synthetic-private-argument']
    session = build_session(private, fake)
    try:
        session.prepare(prepare('create-marker', marker(['text', '1', 'synthetic-private-literal']).payload, [1], 1))
        raw = (private / 'kitty.jsonl').read_text()
        assert 'synthetic-private-literal' not in raw and 'synthetic-private-argument' not in raw
        assert 'kitty.create-marker/v1' in raw and 'evidence_ref' in raw
    finally:
        session.close()


UNIMPLEMENTED = {
    'action': {'action': 'synthetic'}, 'kitten': {'kitten': 'synthetic', 'args': []},
    'launch': {'args': ['/synthetic/program']}, 'new-window': {'args': ['/synthetic/program']},
    'run': {'cmdline': ['/synthetic/program'], 'data': ''}, 'load-config': {},
    'env': {'env': {}}, 'send-text': {'data': 'text:synthetic'},
    'send-key': {'keys': ['a']}, 'signal-child': {'signals': ['SIGTERM']},
}


@pytest.mark.parametrize('verb,payload', UNIMPLEMENTED.items())
def test_unimplemented_families_report_missing_adapter_not_completed_assessment(verb, payload):
    fake, events = FakeKitty(), []
    bridge = Bridge(fake, NativeChecker(), events.append)
    act = Act(verb, canonical(payload), (1,))
    with pytest.raises(PermissionError):
        bridge.inspect(act, act.plan(1))
    assert not fake.calls
    receipt = events[0]['assessment']
    assert receipt['denied'] and receipt['assessor'] == 'kitty.native/v1'
    assert receipt['reason'] == verb + '-adapter-not-implemented'
    assert receipt['evidence_ref']


def test_no_generic_adapter_or_hidden_completion_claim():
    assert set(UNIMPLEMENTED) == OPAQUE - {'create-marker'}
    coverage = NativeChecker().coverage()
    assert coverage['create-marker'] == 'partial-create-marker-adapter'
    assert sum(v == 'needs-trusted-effect-adapter' for v in coverage.values()) == 10


def test_legacy_injected_stub_is_explicitly_unattributed_not_native_evidence():
    receipt = trace(Assessment(1, 'reversible'), 'plan')
    assert receipt['assessor'] == 'unattributed-library-checker' and receipt['evidence_ref'] is None
    validate_trace(receipt)


@pytest.mark.parametrize('mode', ['raise', 'wrong-type', 'bad-receipt'])
def test_assessor_failure_records_refusal_without_exception_content(mode):
    fake, events = FakeKitty(), []
    def broken(act, phase, targets):
        if mode == 'raise':
            raise RuntimeError('synthetic-private-exception-content')
        if mode == 'wrong-type':
            return True
        return replace(NativeChecker()(act, phase, targets), evidence_ref='0' * 64)
    bridge = Bridge(fake, broken, events.append)
    act = marker()
    with pytest.raises(PermissionError):
        bridge.inspect(act, act.plan(1))
    assert not fake.calls
    receipt = events[0]['assessment']
    assert receipt['denied'] and receipt['assessor'] == 'kitty.assessment-boundary/v1'
    assert receipt['reason'] == 'checker-failed-or-invalid-evidence'
    assert 'synthetic-private-exception-content' not in canonical(events)


def test_marker_missing_declared_target_refuses_even_at_plan():
    result = NativeChecker()(marker(ids=()), 'plan', ())
    assert result.denied and result.reason == 'marker-target-evidence-missing'


def test_marker_direct_adapter_validates_wire_without_native_wrapper():
    result = CreateMarkerAdapter()(marker(unsafe='synthetic'), 'plan', (), inventory())
    assert result.denied and result.reason == 'marker-wire-invalid'
