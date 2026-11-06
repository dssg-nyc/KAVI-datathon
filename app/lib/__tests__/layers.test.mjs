// Tests for app/lib/layers.js. Run: node --test app/lib/__tests__/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { LAYER_INDEX_PATH, fetchLayerIndex, layerPopupHtml } from '../layers.js';

const root = new URL('../../../', import.meta.url);
const index = JSON.parse(await readFile(new URL(LAYER_INDEX_PATH, root), 'utf8'));
const libraries = index.find((l) => l.key === 'libraries');

test('the committed index has the three PRD layers, each pointing at a file under data/public/', () => {
  assert.deepEqual(index.map((l) => l.key), ['libraries', 'health_facilities', 'cooling_sites']);
  for (const l of index) assert.ok(l.file.startsWith('data/public/layers/') && l.label && l.color, l.key);
});

test('fetchLayerIndex returns the entries, or [] when the file cannot be read', async () => {
  const realFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({ ok: true, json: async () => [...index, { key: 'broken' }] });
    assert.deepEqual(await fetchLayerIndex(), index);
    globalThis.fetch = async () => ({ ok: false });
    assert.deepEqual(await fetchLayerIndex(), []);
    globalThis.fetch = async () => { throw new Error('offline'); };
    assert.deepEqual(await fetchLayerIndex(), []);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test('layerPopupHtml shows the name, address, kind and which layer it came from, escaped', () => {
  const html = layerPopupHtml(libraries, { name: 'A <b>Branch</b>', address: '1 Main St, Brooklyn 11201', kind: 'BPL' });
  assert.match(html, /A &lt;b&gt;Branch&lt;\/b&gt;/);
  assert.match(html, /1 Main St, Brooklyn 11201/);
  assert.match(html, /BPL/);
  assert.match(html, /Libraries layer, not from the Connections guide/);
});

test('layerPopupHtml leaves out blank fields and mentions a status other than Activated', () => {
  const cooling = index.find((l) => l.key === 'cooling_sites');
  const on = layerPopupHtml(cooling, { name: 'Park', address: null, kind: 'Spray Shower', status: 'Activated' });
  assert.doesNotMatch(on, /activated/i);
  assert.equal((on.match(/class="meta"/g) ?? []).length, 2);
  const off = layerPopupHtml(cooling, { name: 'Park', address: 'Bronx', kind: 'Spray Shower', status: 'Broken' });
  assert.match(off, /Spray Shower, broken/);
});
