// Tests for pipeline/6_build/reference_layers.ts. Run with: node --test pipeline/6_build/__tests__/reference_layers.test.ts
// Nothing here touches the network: the conversion is tested on sample ArcGIS rows, and the committed files
// in data/public/layers/ are checked against each other.
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { INDEX_PATH, LAYERS, indexJson, layerPath, titleCase, toGeoJson } from '../reference_layers.ts';

const layer = (key: string) => LAYERS.find((l) => l.key === key)!;
const nyc: [number, number] = [-73.95, 40.75];

describe('titleCase', () => {
  test('lowercases the Facilities Database shouting and capitalizes each word', () => {
    assert.equal(titleCase('GREENPOINT LIBRARY'), 'Greenpoint Library');
    assert.equal(titleCase('ST. JOHN-RIVERSIDE (ANNEX)'), 'St. John-Riverside (Annex)');
    assert.equal(titleCase('163-18 JAMAICA AVENUE'), '163-18 Jamaica Avenue');
  });
  test('is blank for null', () => {
    assert.equal(titleCase(null), '');
    assert.equal(titleCase(undefined), '');
  });
});

describe('toFeature', () => {
  test('a library keeps its name, address and system', () => {
    const f = layer('libraries').toFeature({ FACNAME: 'GREENPOINT LIBRARY', ADDRESS: '107 NORMAN AVENUE', CITY: 'BROOKLYN', ZIPCODE: '11222', OPNAME: 'BPL' }, nyc);
    assert.deepEqual(f, { type: 'Feature', geometry: { type: 'Point', coordinates: nyc }, properties: { name: 'Greenpoint Library', address: '107 Norman Avenue, Brooklyn 11222', kind: 'BPL' } });
  });
  test('a library without an address has address null', () => {
    const f = layer('libraries').toFeature({ FACNAME: 'A', ADDRESS: null, CITY: null, ZIPCODE: null, OPNAME: null }, nyc);
    assert.deepEqual(f.properties, { name: 'A', address: null, kind: null });
  });
  test('a health facility uses its facility type as kind', () => {
    const f = layer('health_facilities').toFeature({ FACNAME: 'JOBNET', ADDRESS: '163-18 JAMAICA AVENUE', CITY: 'JAMAICA', ZIPCODE: '11432', FACTYPE: 'SUPPORT MENTAL HEALTH' }, nyc);
    assert.deepEqual(f.properties, { name: 'Jobnet', address: '163-18 Jamaica Avenue, Jamaica 11432', kind: 'Support Mental Health' });
  });
  test('a cooling site names the park and feature, with the borough and status', () => {
    const f = layer('cooling_sites').toFeature({ PropertyName: 'Prospect Park', SubPropertyName: 'Vanderbilt Playground', Borough: 'Brooklyn', FeatureType: 'Spray Shower', Status: 'Activated' }, nyc);
    assert.deepEqual(f.properties, { name: 'Prospect Park: Vanderbilt Playground', address: 'Brooklyn', kind: 'Spray Shower', status: 'Activated' });
    const bare = layer('cooling_sites').toFeature({ PropertyName: 'Prospect Park', SubPropertyName: null, Borough: null, FeatureType: null, Status: null }, nyc);
    assert.deepEqual(bare.properties, { name: 'Prospect Park', address: null, kind: null, status: null });
  });
});

describe('toGeoJson', () => {
  test('writes a FeatureCollection with one feature per line', () => {
    const f = layer('libraries').toFeature({ FACNAME: 'A' }, nyc);
    const text = toGeoJson([f, f]);
    assert.deepEqual(JSON.parse(text), { type: 'FeatureCollection', features: [f, f] });
    assert.equal(text.split('\n').length, 5);
  });
});

describe('indexJson', () => {
  test('lists every layer with its file, count and the date it changed', async () => {
    const counts = Object.fromEntries(LAYERS.map((l) => [l.key, 1]));
    const changed = Object.fromEntries(LAYERS.map((l) => [l.key, true]));
    const entries = JSON.parse(await indexJson(counts, changed, new Date('2026-01-02T12:00:00Z')));
    assert.deepEqual(entries.map((e: { key: string }) => e.key), LAYERS.map((l) => l.key));
    for (const e of entries) {
      assert.equal(e.file, `data/public/layers/${e.key}.geojson`);
      assert.equal(e.count, 1);
      assert.equal(e.fetched, '2026-01-02');
      assert.ok(e.label && e.note && e.color && e.source, e.key);
    }
  });
  test('keeps the committed date for a layer that did not change', async () => {
    const committed = JSON.parse(await readFile(INDEX_PATH, 'utf8'));
    const counts = Object.fromEntries(LAYERS.map((l) => [l.key, 1]));
    const changed = Object.fromEntries(LAYERS.map((l) => [l.key, false]));
    const entries = JSON.parse(await indexJson(counts, changed, new Date('2030-01-01T12:00:00Z')));
    for (const e of entries) assert.equal(e.fetched, committed.find((c: { key: string }) => c.key === e.key).fetched);
  });
});

describe('the committed files', () => {
  test('the index matches the GeoJSON files, which hold named points in New York City', async () => {
    const entries = JSON.parse(await readFile(INDEX_PATH, 'utf8'));
    assert.deepEqual(entries.map((e: { key: string }) => e.key), LAYERS.map((l) => l.key));
    for (const l of LAYERS) {
      const data = JSON.parse(await readFile(layerPath(l), 'utf8'));
      const entry = entries.find((e: { key: string }) => e.key === l.key);
      assert.equal(data.features.length, entry.count, l.key);
      assert.ok(data.features.length > 100, l.key);
      for (const f of data.features) {
        assert.equal(f.geometry.type, 'Point');
        const [lon, lat] = f.geometry.coordinates;
        assert.ok(lon > -74.3 && lon < -73.6 && lat > 40.4 && lat < 41, `${l.key}: ${f.properties.name} at ${lon}, ${lat}`);
        assert.ok(f.properties.name, l.key);
      }
    }
  });
});
