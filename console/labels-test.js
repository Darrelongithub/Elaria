/* Provenance/label regression; local DOM only, no daemon or model. */
'use strict';
const assert = require('node:assert/strict');
const { load } = require('./harness.js');
(async () => {
  const c = await load();
  const shell = c.window.ElariaShell;
  const badge = name => c.$('badge-' + name).textContent;
  try {
    for (const name of ['transcript', 'audio', 'memory']) shell[name]([]);
    assert.equal(badge('transcript'), 'pending');
    assert.equal(badge('audio'), 'pending');
    assert.equal(badge('memory'), 'shell copy');
    shell.transcript([{ts:'test',id:'synthetic',who:'test',text:'Synthetic transcript row',peak:0,verdict:'test'}]);
    assert.equal(badge('transcript'), 'live');
    assert.equal(badge('audio'), 'pending');
    assert.equal(badge('memory'), 'shell copy');
    shell.audio([{name:'synthetic.wav',size:'0 B',age:'test',tier:'test'}]);
    shell.transcript([]);
    assert.equal(badge('transcript'), 'pending');
    assert.equal(badge('audio'), 'live');
    shell.memory([{t:'Synthetic card',v:'Test feed, not model proof',w:'test'}]);
    assert.equal(badge('memory'), 'live');
    await c.click(c.q('[data-pane="memory"]'));
    assert(!c.$('body-memory').textContent.includes('shell copy'));
    shell.memory([]);
    assert.equal(badge('memory'), 'shell copy');
    await c.type('/demo');
    assert.equal(badge('transcript'), 'sample');
    assert.equal(badge('audio'), 'live'); // a sample toggle cannot relabel real feed rows
    await c.type('/audio');
    assert.equal(c.$('fbadge').textContent, 'live');
    assert(!c.$('fbody').textContent.includes('[SAMPLE]'));
    shell.audio([]);
    assert.equal(badge('audio'), 'pending');
    assert.equal(badge('transcript'), 'pending');
    assert.equal(c.$('fbadge').textContent, 'pending');
    assert(c.$('fbody').textContent.includes('No storage manifest feed rows'));
    const footer = c.$('orbnote').textContent;
    assert.equal(footer, 'synthesised text cadence, not measured audio · text-only, no speech');
    assert.equal(c.qa('.console-footer .lamps li').length, 4);
    shell.connect({send:async () => 'Synthetic reply',name:'synthetic test'});
    assert.equal(c.$('orbnote').textContent, footer);
    assert(!c.doc.body.textContent.includes('driven by real levels'));
    assert(!c.doc.body.textContent.includes('bridge does not exist yet'));
    assert(!c.doc.body.textContent.includes('never leaves this machine'));
    assert(c.q('[data-lamp="wire"]').title.includes('connected; not proof'));
    c.window.innerWidth = 390;
    c.window.dispatchEvent(new c.window.Event('resize'));
    assert.equal(c.$('tgSb').getAttribute('aria-expanded'), 'false');
    await c.click(c.$('tgSb'));
    assert.equal(c.$('tgSb').getAttribute('aria-expanded'), 'true');
    await c.click(c.$('tgSb'));
    assert.equal(c.$('tgSb').getAttribute('aria-expanded'), 'false');
    assert.deepEqual(c.errors, []);
    console.log('PASS: independent feed badges, empty reset, sample/live precedence, footer, status copy, narrow sidebar');
  } finally { c.close(); }
})().then(() => process.exit(0), error => { console.error(error); process.exit(1); });
