// Tests for app/lib/share.js and the card link in app/components/cards.js. Run: node --test app/lib/__tests__/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { findRow, idFromSearch, pageTitle, resourcePath } from '../share.js';
import { rowsFromJson } from '../csv.js';
import { isListed, toResource } from '../resources.js';
import { cardHtml, popupHtml } from '../../components/cards.js';

const root = new URL('../../../', import.meta.url);
const rows = rowsFromJson(await readFile(new URL('data/public/resources.public.json', root), 'utf8'));

test('resourcePath makes a relative link that idFromSearch reads back, for every kind of id', () => {
  for (const id of ['176', '176-2', 'feature-695', 42, 'a b&c']) {
    const path = resourcePath(id);
    assert.ok(path.startsWith('resource.html?id='), path);
    assert.equal(idFromSearch(path.slice('resource.html'.length)), String(id));
  }
});

test('idFromSearch is blank without an id', () => {
  assert.equal(idFromSearch(''), '');
  assert.equal(idFromSearch('?preview=local'), '');
  assert.equal(idFromSearch('?id=%20'), '');
});

test('findRow matches string and numeric ids, and is null when nothing matches', () => {
  const sample = [{ id: '176' }, { id: '176-2' }, { id: 7 }];
  assert.equal(findRow(sample, '176-2'), sample[1]);
  assert.equal(findRow(sample, 176), sample[0]);
  assert.equal(findRow(sample, '7'), sample[2]);
  assert.equal(findRow(sample, '999'), null);
  assert.equal(findRow([], '1'), null);
});

test('every listed row of the committed data has a page link that finds it again', () => {
  const listed = rows.filter(isListed);
  assert.ok(listed.length > 700);
  for (const row of listed) {
    const id = idFromSearch(resourcePath(row.id).slice('resource.html'.length));
    assert.equal(findRow(rows, id), row, `id ${row.id}`);
  }
});

test('cards link to the resource page unless asked not to', () => {
  const r = toResource(rows.find((row) => row.id === '176-2'), 0);
  assert.match(cardHtml(r), /<a href="resource\.html\?id=176-2">Link to this resource<\/a>/);
  assert.match(popupHtml([r]), /resource\.html\?id=176-2/);
  assert.doesNotMatch(cardHtml(r, { link: false }), /resource\.html/);
  assert.doesNotMatch(cardHtml(toResource({ organization_name: 'No id' }, 0)), /resource\.html/);
});

test('the link is escaped and the page title names the resource', () => {
  const r = toResource({ id: 'x"<y', organization_name: 'A & B' }, 0);
  assert.match(cardHtml(r), /href="resource\.html\?id=x%22%3Cy"/);
  assert.equal(pageTitle(r), 'A & B — EMPOWER');
  assert.equal(pageTitle(null), 'Resource not found — EMPOWER');
});
