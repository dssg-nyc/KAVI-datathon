// Tests for the review labels and eligibility tag in app/components/cards.js (requirements D4, D5).
// Run: node --test app/components/__tests__/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cardHtml } from '../cards.js';
import { REVIEW_LABELS, toResource } from '../../lib/resources.js';
import { sourceLine } from '../../lib/share.js';

const FLAGS = Object.keys(REVIEW_LABELS);
const base = { id: '1', organization_name: 'Org', audiences_all: ['Youth', 'Everyone'] };
const card = (row) => cardHtml(toResource({ ...base, ...row }, 0));

test('a row with no flags shows no review line and says it is open to everyone', () => {
  const html = card({ review_flags: [] });
  assert.doesNotMatch(html, /Not yet checked/);
  assert.match(html, /Open to everyone/);
  assert.doesNotMatch(html, /Eligibility not stated/);
});

test('each flag alone gives its label; eligibility changes the tag instead', () => {
  for (const flag of FLAGS) {
    const html = card({ review_flags: [flag] });
    if (flag === 'eligibility') {
      assert.doesNotMatch(html, /Not yet checked/);
      assert.match(html, /Eligibility not stated/);
      assert.doesNotMatch(html, /Open to everyone/);
    } else {
      assert.match(html, new RegExp(`Not yet checked: ${REVIEW_LABELS[flag]}<`));
    }
  }
});

test('every combination lists its labels in order, and eligibility is always the tag', () => {
  for (let bits = 1; bits < 1 << FLAGS.length; bits++) {
    const flags = FLAGS.filter((_, i) => bits & (1 << i));
    const html = card({ review_flags: flags });
    const labels = flags.filter((f) => f !== 'eligibility').map((f) => REVIEW_LABELS[f]);
    if (labels.length) assert.match(html, new RegExp(`Not yet checked: ${labels.join(', ')}<`), flags.join());
    else assert.doesNotMatch(html, /Not yet checked/);
    assert.match(html, flags.includes('eligibility') ? /Eligibility not stated/ : /Open to everyone/, flags.join());
  }
});

test('a row the filter sees as "for everyone" still matches any audience even when eligibility is assumed', () => {
  const r = toResource({ ...base, review_flags: ['eligibility'] }, 0);
  assert.equal(r.forEveryone, true);
  assert.equal(r.everyoneStated, false);
});

test('unknown flags and missing review_flags (CSV or Supabase rows) are ignored', () => {
  assert.deepEqual(toResource({ ...base, review_flags: ['something_new'] }, 0).review, []);
  assert.deepEqual(toResource(base, 0).review, []);
  assert.doesNotMatch(card({}), /Not yet checked/);
});

test('a restricted row has neither tag', () => {
  const html = card({ audiences_all: ['Youth'], restricted_audiences: ['Youth'], review_flags: [] });
  assert.doesNotMatch(html, /Open to everyone|Eligibility not stated/);
});

test('the source line names the source and the data date', () => {
  assert.equal(sourceLine({ source: 'The guide', data_updated: '2026-11-04' }), 'Source: The guide. Data updated 2026-11-04.');
  assert.equal(sourceLine({ source: 'The guide' }), 'Source: The guide.');
  assert.equal(sourceLine(null), 'Source: the NYPL Connections guide.');
});
