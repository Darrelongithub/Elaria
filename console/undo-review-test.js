'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const ROOT = path.resolve(__dirname, '..');
const IF6_SHA = '6961c7f8b72d223d053bd20a45d8401e0466d358565ecf19952aaf5ee0ca351f';

function read(rel) {
  return fs.readFileSync(path.join(ROOT, rel), 'utf8');
}

function json(rel) {
  return JSON.parse(read(rel));
}

function sha256(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex');
}

const inventory = json('fixtures/hands/inventory.json');

test('inventory declares 6 armed traps, 2 benign controls, and 5 scenes', () => {
  assert.equal(inventory.schema_version, 1);
  assert.equal(inventory.cluster, 'R');
  assert.equal(inventory.fixture_count, 8);
  assert.equal(inventory.trap_count, 6);
  assert.equal(inventory.benign_control_count, 2);
  assert.equal(inventory.pilot_scene_count, 5);
  assert.equal(inventory.criteria_count, 5);
  assert.equal(inventory.no_hardware_execution, true);
  assert.equal(inventory.never_execute_fixtures, true);
});

test('all six frozen contract pins are present and IF-6 is unchanged', () => {
  const pins = inventory.contract_pins;
  assert.equal(Object.keys(pins).length, 6);
  for (const value of Object.values(pins)) {
    assert.match(value, /^[a-f0-9]{64}$/);
  }
  assert.equal(pins['IF-6'], IF6_SHA);
  assert.equal(inventory.contract.id, 'IF-6');
  assert.equal(inventory.contract.sha256, IF6_SHA);
});

test('every trap exists, is armed, is inert data, and matches its pinned hash', () => {
  assert.equal(inventory.trap_arm_manifest.length, 6);
  const names = new Set();
  for (const entry of inventory.trap_arm_manifest) {
    assert.equal(entry.armed, true);
    assert.equal(entry.classification, 'untrusted-input');
    assert.match(entry.path, /^traps\//);
    assert.ok(!names.has(entry.path), `duplicate trap ${entry.path}`);
    names.add(entry.path);
    const text = read(path.join('fixtures/hands', entry.path));
    assert.match(text, /ARMED/);
    assert.match(text, /UNTRUSTED INPUT/);
    assert.match(text, /NEVER EXECUTE/);
    assert.equal(sha256(text), entry.sha256);
    assert.match(entry.expected, /recorded refusal/);
  }
  assert.equal(names.size, 6);
  assert.ok(names.has('traps/delete everything now.txt'));
  assert.ok(names.has('traps/stdout.txt'));
  assert.ok(names.has('traps/stderr.txt'));
  assert.ok(names.has('traps/tool-output.txt'));
});

test('benign negative controls hash-match and are not armed', () => {
  assert.equal(inventory.benign_controls.length, 2);
  for (const entry of inventory.benign_controls) {
    assert.equal(entry.armed, false);
    assert.equal(entry.classification, 'benign');
    const text = read(path.join('fixtures/hands', entry.path));
    assert.equal(sha256(text), entry.sha256);
    assert.doesNotMatch(text, /ARMED/);
    assert.doesNotMatch(text, /NEVER EXECUTE/);
  }
});

test('five criteria map 1:1 to five owner-only, spec-only scenes', () => {
  const scenes = read('fixtures/hands/pilot-scenes.md');
  const criterionRows = [...scenes.matchAll(/^\| (C\d+) \|/gm)].map((m) => m[1]);
  const sceneRows = [...scenes.matchAll(/^\| C\d+ \|[^|]+\| (R-S\d+) \|/gm)].map((m) => m[1]);
  assert.equal(criterionRows.length, 5);
  assert.equal(sceneRows.length, 5);
  assert.equal(new Set(criterionRows).size, 5);
  assert.equal(new Set(sceneRows).size, 5);
  assert.deepEqual(criterionRows, ['C1', 'C2', 'C3', 'C4', 'C5']);
  assert.deepEqual(sceneRows, ['R-S1', 'R-S2', 'R-S3', 'R-S4', 'R-S5']);
  assert.equal((scenes.match(/^- \[x\]/gm) || []).length, 5);
  assert.match(scenes, /SPEC ONLY — NOT EXECUTED/);
  assert.match(scenes, /OWNER-ONLY/);
});

test('pilot checklist states what an empty hardware result cannot prove', () => {
  const scenes = read('fixtures/hands/pilot-scenes.md');
  assert.match(scenes, /would fail to discriminate/);
  assert.match(scenes, /zero hardware runs explicitly/);
  assert.equal((scenes.match(/NOT EXECUTED/g) || []).length >= 6, true);
});

test('historical record is append-only annotated, never rewritten', () => {
  const recordPath = 'docs/phase-reports/hands-2026-11-19-pilot-record.md';
  const record = read(recordPath);
  const body = record.match(
    /<!-- BEGIN ORIGINAL RECORD -->\n([\s\S]*?)\n<!-- END ORIGINAL RECORD -->/
  );
  assert.ok(body, 'original record markers missing');
  const digest = record.match(/^RECORD-BODY-SHA256: ([a-f0-9]{64})$/m);
  assert.ok(digest, 'record body digest missing');
  assert.equal(sha256(body[1]), digest[1]);
  assert.equal(inventory.record_body_sha256, digest[1]);
  assert.equal((record.match(/<!-- BEGIN ORIGINAL RECORD -->/g) || []).length, 1);
  const annotations = [...record.matchAll(
    /<!-- BEGIN ANNOTATION (\d{4}-\d{2}-\d{2}T[^ ]+) -->[\s\S]*?<!-- END ANNOTATION -->/g
  )];
  assert.equal(annotations.length, 3);
  assert.ok(record.indexOf('<!-- END ORIGINAL RECORD -->') < record.indexOf('<!-- BEGIN ANNOTATION'));
  assert.match(annotations[0][0], /hypothesis/i);
  assert.match(annotations[0][0], /annotat/i);
  assert.match(annotations[1][0], /OWNERS\.yaml|ownership guard/i);
  assert.match(annotations[1][0], /append-only/i);
  assert.match(annotations[2][0], /a2eec68|5cf7c77|reports\/RPT-R/);
  assert.match(annotations[2][0], /append-only/i);
});

test('live ownership guard maps R test to console/ and R reports to R', () => {
  const owners = json('OWNERS.yaml');
  assert.ok(owners.R.includes('console/undo-review-test.js'));
  assert.ok(owners.R.includes('reports/RPT-R-*'));
  assert.ok(owners.R.includes('undo-review-test.js'), 'legacy root alias remains mapped');
  assert.ok(fs.existsSync(path.join(ROOT, 'console/undo-review-test.js')));
  assert.ok(!fs.existsSync(path.join(ROOT, 'undo-review-test.js')));
  assert.ok(fs.existsSync(path.join(ROOT, 'scripts/check_ownership.py')));
});

test('declared R paths stay inside R ownership roots', () => {
  assert.equal(inventory.owned_paths.length, inventory.owned_path_count);
  for (const rel of inventory.owned_paths) {
    assert.ok(
      inventory.allowed_prefixes.some((prefix) => rel.startsWith(prefix)),
      `out-of-ownership path: ${rel}`
    );
    assert.ok(fs.existsSync(path.join(ROOT, rel)), `missing owned path: ${rel}`);
  }
});

test('handoff records keep the hardware and no-code boundaries explicit', () => {
  const handoff = read('docs/hands-handoff.md');
  const headless = read('docs/hands-headless.md');
  assert.match(handoff, /no hook request is required from R/);
  assert.match(handoff, /R performs no hardware action/);
  assert.match(headless, /TESTED-ONLY \/ OWNER-HARDWARE-PENDING/);
  assert.match(headless, /No daemon restart/);
});
