// What the finder does when something outside it fails (requirements R1, R2, A2 in
// docs/technical-requirements.md): no map library, no address search, and the list on its own.
// Run: node --test app/lib/__tests__/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { searchPlaces, zipPlace } from '../geo.js';
import { countBy, matchingResources, newFilters } from '../filter.js';
import { isListed, toResource } from '../resources.js';
import { rowsFromJson } from '../csv.js';
import { cardHtml } from '../../components/cards.js';

const root = new URL('../../../', import.meta.url);
const rows = rowsFromJson(await readFile(new URL('data/public/resources.public.json', root), 'utf8'));
const resources = rows.filter(isListed).map((row, i) => toResource(row, i));

async function withFetch(fake, run) {
  const real = globalThis.fetch;
  globalThis.fetch = fake;
  try { return await run(); } finally { globalThis.fetch = real; }
}

// R1: the map is optional. createMap() returns null without MapLibre and says so in the container.
test('createMap returns null and explains when MapLibre did not load, so the list is all there is', async () => {
  globalThis.window = {};
  try {
    const { createMap } = await import('../../components/map.js');
    const container = { innerHTML: '' };
    assert.equal(createMap(container, {}), null);
    assert.match(container.innerHTML, /The map could not load\. The list still works\./);
  } finally {
    delete globalThis.window;
  }
});

// R2: when GeoSearch is down, a ZIP still resolves and the caller is told the search failed.
test('searchPlaces falls back to the ZIP average when GeoSearch fails, and reports the failure', async () => {
  const offline = async () => { throw new TypeError('Failed to fetch'); };
  const warn = console.warn;
  console.warn = () => {};
  try {
    const zip = await withFetch(offline, () => searchPlaces('11201', resources));
    assert.equal(zip.failed, true);
    assert.deepEqual(zip.places, [zipPlace(resources, '11201')]);
    assert.equal(zip.places[0].label, 'ZIP 11201');
    const street = await withFetch(offline, () => searchPlaces('147 Prince St', resources));
    assert.deepEqual(street, { places: [], failed: true });
    const http = await withFetch(async () => ({ ok: false, status: 503 }), () => searchPlaces('99999', resources));
    assert.deepEqual(http, { places: [], failed: true });
  } finally {
    console.warn = warn;
  }
});

test('searchPlaces puts the ZIP first and keeps four GeoSearch matches when both work', async () => {
  const body = { features: Array.from({ length: 6 }, (_, i) => ({ properties: { label: `${i} Main St, Brooklyn, NY, USA` }, geometry: { coordinates: [-73.9, 40.7] } })) };
  const result = await withFetch(async () => ({ ok: true, json: async () => body }), () => searchPlaces('11201', resources));
  assert.equal(result.failed, false);
  assert.equal(result.places.length, 5);
  assert.equal(result.places[0].label, 'ZIP 11201');
  assert.equal(result.places[1].label, '0 Main St, Brooklyn, NY');
});

test('an abort is passed through, not swallowed as a failure', async () => {
  const abort = async () => { throw Object.assign(new Error('aborted'), { name: 'AbortError' }); };
  await assert.rejects(withFetch(abort, () => searchPlaces('x', resources)), { name: 'AbortError' });
});

// A2: every listed resource appears in the list with the default filters, and the list alone covers
// both in-person and phone/online rows; no result exists only on the map.
test('with the default filters the list shows every listed resource, in person or not', () => {
  const list = matchingResources(resources, newFilters());
  assert.equal(list.length, resources.length);
  const how = countBy(resources, newFilters(), 'how');
  assert.equal((how.get('in_person') ?? 0) + (how.get('remote') ?? 0), resources.length);
  assert.ok(how.get('in_person') > 400 && how.get('remote') > 200, [...how]);
});

test('every card has the resource name, a link to its page, and a map button only when it has a pin', () => {
  for (const r of resources) {
    const card = cardHtml(r);
    assert.ok(card.includes(`resource.html?id=${encodeURIComponent(r.id)}`), r.id);
    assert.equal(/<button[^>]*data-show-map/.test(card), r.inPerson, r.id);
  }
});
