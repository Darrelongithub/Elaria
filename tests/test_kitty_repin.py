"""Lane Q re-pin acceptance — upstream kitty v0.47.1 -> v0.49.2, CODE ONLY.

No release, deploy, install, live kitty or owner machine is touched here. Every number
below was measured against the v0.49.2 source tree (`kovidgoyal/kitty` @ b2cb8712) with
`tools/kitty/build_inventory.py`; nothing is inherited from the v0.47.1 catalogue.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from test_kitty_adapters import marker

from assistant.hands.kitty import pin, policy
from assistant.hands.kitty.adapters.marker import CreateMarkerAdapter
from assistant.hands.kitty.checker import NativeChecker, validate_payload
from assistant.hands.kitty.policy import Act, canonical, inventory

ROOT = Path(__file__).resolve().parents[1]
PIN_MODULE = ROOT / 'src/assistant/hands/kitty/pin.py'


def builder():
    path = ROOT / 'tools/kitty/build_inventory.py'
    spec = importlib.util.spec_from_file_location('kitty_build_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- inventory scale

def test_re_derived_inventory_scale_is_measured_not_carried_forward():
    data = inventory()
    verbs = len(data['verbs'])
    verb_options = sum(len(v['options']) for v in data['verbs'].values())
    kitten_options = sum(len(k['options']) for k in data['kittens'].values())
    hazards = set()
    for entry in data['verbs'].values():
        hazards.update(entry['hazards'])
        for option in entry['options']:
            hazards.update(option['hazards'])
    for option in data['global_options']:
        hazards.update(option['hazards'])
    for entry in data['kittens'].values():
        hazards.update(entry['hazards'])
        for option in entry['options']:
            hazards.update(option['hazards'])
    # v0.47.1 shipped 39 verbs / 190 options (167 verb + 23 kitten) / 26 hazard flags.
    # v0.49.2: +2 verbs, +3 verb options; 25 of the 26 flags re-derive unchanged, 1 is
    # renamed with the new version suffix, and 5 are newly derived for the three changes.
    assert (verbs, verb_options, kitten_options) == (41, 170, 23)
    assert verb_options + kitten_options == 193
    assert len(hazards) == 31
    carried = {'acts-inherit-K-tier', 'arbitrary-effects', 'arbitrary-input', 'arbitrary-process',
               'bracketed-paste-not-a-guarantee', 'broadcast', 'credential-access-K3',
               'destructive-K3', 'effects-require-verification', 'external-effects-may-require-K3',
               'focus-steal', 'his-window-K3', 'irreversible-effects-K3', 'never-grant-rc',
               'newline-execution', 'python-escape-cli', 'response-is-not-effect-proof',
               'screen-or-environment-may-contain-secrets', 'sensitive-input-or-code', 'silent',
               'silent-success', 'stamp-required', 'target-blind', 'target-default-may-be-active',
               'target-expansion'}
    assert carried <= hazards
    assert hazards - carried == {
        'K3-send-key-exclude-active-unenforced-0.49.2', 'arbitrary-path-write',
        'get-text-extent-unassessed-0.49.2', 'os-window-reach', 'screen-content-return',
        'window-identity-spoofing'}
    assert data['upstream_version'] == '0.49.2'
    assert data['upstream_commit'] == 'b2cb871254fbdac19a085188813c8dfb258b95cd'
    assert data['owner_rpm_ruling'] == '0.49.2-1.fc44'
    assert data['owner_version_verbatim'] == 'kitten 0.49.2 created by Kovid Goyal'
    assert data['owner_drift_reconciled'] is True
    assert data['researched_on'] == pin.RESEARCHED_ON


def test_verb_delta_against_the_previous_pin_is_exactly_the_two_new_verbs():
    data = inventory()
    assert {'screenshot', 'set-os-window-title'} <= set(data['verbs'])
    assert data['verbs']['screenshot']['tier'] == 'K3'
    assert data['verbs']['set-os-window-title']['tier'] == 'K3'
    for verb in ('screenshot', 'set-os-window-title'):
        assert 'never-grant-rc' in data['verbs'][verb]['hazards']
    assert 'arbitrary-path-write' in data['verbs']['screenshot']['hazards']
    assert 'screen-content-return' in data['verbs']['screenshot']['hazards']
    assert 'window-identity-spoofing' in data['verbs']['set-os-window-title']['hazards']


def test_schema_still_validates_the_regenerated_inventory():
    jsonschema = pytest.importorskip('jsonschema')
    jsonschema.validate(inventory(), json.loads((policy.DATA / 'inventory.schema.json').read_text()))


# ---------------------------------------------------------------- ASK 52 (f-strings)

def test_ask_52_fstring_protocol_spec_extracts_fields_instead_of_emptiness():
    entry = inventory()['verbs']['set-background-image']
    assert entry['protocol_spec'].strip()
    layout = next(f for f in entry['payload'] if f['name'] == 'layout')
    expected = ['tiled', 'scaled', 'mirror-tiled', 'clamped', 'centered', 'cscaled',
                'configured']
    assert layout['type'] == 'choices.' + '.'.join(expected)
    assert '{' not in layout['type']
    option = next(o for o in entry['options'] if '--layout' in o['flags'])
    assert option['choices'] == expected


def test_ask_52_no_declared_spec_anywhere_silently_extracts_to_nothing():
    data = inventory()
    builder().assert_extraction_nonempty(data['verbs'], data['kittens'])
    for name, entry in data['verbs'].items():
        assert not entry['protocol_spec'].strip() or entry['payload'], name
        assert not entry['option_spec'].strip() or entry['options'], name


# ---------------------------------------------------------------- ASK 49 (one pin)

def test_ask_49_version_literals_live_in_exactly_one_module():
    # Runtime code must not carry the version at all; pin.py's docstring only names the
    # from-version of the re-pin.
    runtime = [p for p in (ROOT / 'src/assistant/hands/kitty').rglob('*.py') if p.name != 'pin.py']
    assert [str(p.relative_to(ROOT)) for p in runtime if '0.47.1' in p.read_text()] == []
    # Build tools may name the old version ONLY inside dated annotations — never as a live
    # pin (no old version constant, url, rpm ruling or CLI prefix).
    live = ("VERSION = '0.47.1'", 'upstream kitty 0.47.1', "'0.47.1-1.fc44'",
            'tree/v0.47.1', 'kitty 0.47.1 ')
    for path in (ROOT / 'tools/kitty').glob('*.py'):
        assert [form for form in live if form in path.read_text()] == [], path.name
    assert pin.UPSTREAM_VERSION == '0.49.2'
    assert pin.CLI_VERSION_PREFIX == 'kitty 0.49.2 '


# ---------------------------------------------------------------- the gate (strict)

def test_gate_passes_on_the_measured_string_and_fails_closed_on_everything_else():
    assert pin.cli_version_matches(b'kitty 0.49.2 created by Kovid Goyal')
    for bad in (b'kitty 0.47.1 created by Kovid Goyal', b'kitty 0.49.20 created by Kovid Goyal',
                b'kitty 0.49.2', b'', b'kitten 0.49.2 created by Kovid Goyal',
                'kitty 0.49.2 created by Kovid Goyal', None, b'\xff'):
        assert pin.cli_version_matches(bad) is False, bad
    pin.check_cli_version(b'kitty 0.49.2 created by Kovid Goyal')
    with pytest.raises(ValueError, match='installed-kitty-version-not-inventory-version'):
        pin.check_cli_version(b'kitty 0.47.1 created by Kovid Goyal')


def test_marker_gate_denies_independently_on_a_wrong_or_stale_pin():
    catalogue = inventory()
    assert CreateMarkerAdapter()(marker(), 'plan', (), catalogue).denied is False
    for key, value in (('upstream_version', '0.47.1'), ('upstream_commit', 'f' * 40)):
        stale = json.loads(json.dumps(catalogue))
        stale[key] = value
        result = CreateMarkerAdapter()(marker(), 'plan', (), stale)
        assert result.denied and result.legacy_tier is None
        assert result.reason == 'marker-source-evidence-missing-or-stale'
    assert (inventory()['verbs']['create-marker']['source_sha256']
            == pin.MARKER_SOURCES['kitty/rc/create_marker.py'])


# ---------------------------------------------------------------- classification

@pytest.mark.parametrize('verb,payload', [
    ('screenshot', {'output_path': '/tmp/elaria-q-should-never-write.png'}),
    ('set-os-window-title', {'title': 'spoofed'}),
])
def test_new_verbs_are_refused_at_the_payload_boundary_and_denied_by_the_checker(verb, payload):
    act = Act(verb, canonical(payload))
    with pytest.raises(PermissionError, match='never-grant-rc'):
        validate_payload(act, inventory())
    result = NativeChecker()(act, 'plan', ())
    assert result.denied and result.legacy_tier is None


@pytest.mark.parametrize('extent', sorted(pin.UNASSESSED_GET_TEXT_EXTENTS))
def test_get_text_invisible_screen_extents_are_refused_fail_closed(extent):
    act = Act('get-text', canonical({'match': 'id:1', 'extent': extent}), (1,))
    with pytest.raises(PermissionError, match='assessed subset'):
        validate_payload(act, inventory())
    assert NativeChecker()(act, 'plan', ()).denied


def test_assessed_get_text_extents_still_pass_and_are_marked_in_the_inventory():
    entry = inventory()['verbs']['get-text']
    option = next(o for o in entry['options'] if '--extent' in o['flags'])
    # CLI help text keeps the leading space after each comma; the wire type does not.
    assert {c.strip() for c in option['choices']} == (
        pin.ASSESSED_GET_TEXT_EXTENTS | pin.UNASSESSED_GET_TEXT_EXTENTS)
    assert pin.GET_TEXT_EXTENT_UNASSESSED in entry['hazards']
    assert pin.GET_TEXT_EXTENT_UNASSESSED in option['hazards']
    for extent in sorted(pin.ASSESSED_GET_TEXT_EXTENTS):
        validate_payload(Act('get-text', canonical({'match': 'id:1', 'extent': extent}), (1,)),
                         inventory())


def test_checker_marks_never_grant_coverage_for_the_new_verbs():
    coverage = NativeChecker().coverage()
    assert set(coverage) == set(inventory()['verbs'])
    assert coverage['screenshot'] == coverage['set-os-window-title'] == 'never-grant-rc'
    # The never-grant label must not quietly displace the opaque-family accounting.
    assert sum(v == 'needs-trusted-effect-adapter' for v in coverage.values()) == 10


@pytest.mark.parametrize('verb,payload', [
    ('screenshot', {'match': 'id:1'}),
    ('set-os-window-title', {'title': 'spoofed', 'match': 'id:1'}),
])
def test_surface_refuses_never_grant_verbs_before_any_target_binding(verb, payload):
    from assistant.hands.kitty.surface import resolve
    act = Act(verb, canonical(payload), (1,))
    with pytest.raises(PermissionError, match='never-grant-rc'):
        resolve(act, [])


# ---------------------------------------------------------------- history discipline

def test_history_records_are_annotated_not_rewritten():
    history = (ROOT / 'docs/phase-reports/kitty-2026-11-02-foundation.md').read_text()
    assert '`fb5255b1ae4f0249ba832d6a773348fd103449ce`' in history
    assert 'DATED SUPERSESSION — 2026-11-19' in history
    assert 'DATED SUPERSESSION 2026-11-19' in (ROOT / 'docs/kitty-inventory.md').read_text()
    assert 'v0.49.2' in (ROOT / 'docs/kitty-inventory.md').read_text()
