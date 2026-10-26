// Tests for finder/csv.js against data/kavi_resources.csv.
// Run with: node --test scripts/tests/kavi_csv.test.mjs
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  checkMapSchema,
  mapLayerCollection,
  parseBool,
  parseList,
  pointCoordinates,
  rowsFromCsv,
} from '../../finder/csv.js';
import { isListed, toResource } from '../../finder/resources.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const csvPath = join(root, 'data', 'kavi_resources.csv');
const text = await readFile(csvPath, 'utf8');

test('parseList reads Postgres arrays and semicolon lists', () => {
  assert.deepEqual(parseList('{Housing,"Reentry Support"}'), ['Housing', 'Reentry Support']);
  assert.deepEqual(parseList('{"Formerly Incarcerated People",Everyone}'), ['Formerly Incarcerated People', 'Everyone']);
  assert.deepEqual(parseList('{"Reentry Support"}'), ['Reentry Support']);
  assert.deepEqual(parseList('{}'), []);
  assert.equal(parseList(''), null);
  assert.deepEqual(parseList('Housing; Reentry Support'), ['Housing', 'Reentry Support']);
});

test('parseBool reads Postgres t/f and Y/N', () => {
  assert.equal(parseBool('t'), true);
  assert.equal(parseBool('f'), false);
  assert.equal(parseBool('Y'), true);
  assert.equal(parseBool('N'), false);
  assert.equal(parseBool(''), null);
});

test('pointCoordinates rejects swapped or one-sided lat/lon', () => {
  assert.deepEqual(pointCoordinates({ latitude: 40.7, longitude: -73.9 }), { lat: 40.7, lon: -73.9 });
  assert.equal(pointCoordinates({ latitude: null, longitude: null }), null);
  assert.equal(pointCoordinates({ latitude: 40.7, longitude: null }).error, 'one coordinate missing');
  assert.equal(pointCoordinates({ latitude: -73.9, longitude: 40.7 }).error, 'latitude/longitude look swapped');
});

test('data/kavi_resources.csv fits the finder map schema', () => {
  const report = checkMapSchema(text);
  assert.deepEqual(report.stats.missingColumns, []);
  assert.equal(report.issues.length, 0, report.issues.slice(0, 8).join('\n'));
  assert.equal(report.ok, true);
  assert.equal(report.stats.rows, 765);
  assert.equal(report.stats.withCoords, 440);
  assert.equal(report.stats.listed, 714);
  assert.equal(report.stats.listedWithCoords, 440);
});

test('CSV coordinates become map-layer Point features [lon, lat]', () => {
  const rows = rowsFromCsv(text);
  const resources = rows.filter(isListed).map((row, i) => toResource(row, i));
  const inPerson = resources.filter((r) => r.inPerson);
  assert.equal(inPerson.length, 440);
  assert.ok(inPerson.every((r) => typeof r.lat === 'number' && typeof r.lon === 'number'));
  assert.ok(inPerson.every((r) => r.lat >= -90 && r.lat <= 90 && r.lon >= -180 && r.lon <= 180));

  const layer = mapLayerCollection(resources);
  assert.equal(layer.type, 'FeatureCollection');
  assert.ok(layer.features.length > 0);
  assert.ok(layer.features.length <= inPerson.length);
  for (const feature of layer.features) {
    assert.equal(feature.geometry.type, 'Point');
    const [lon, lat] = feature.geometry.coordinates;
    assert.equal(typeof lon, 'number');
    assert.equal(typeof lat, 'number');
    assert.ok(Math.abs(lat) <= 90 && Math.abs(lon) <= 180);
  }

  const bpl = resources.find((r) => r.name.includes('BROOKLYN PUBLIC LIBRARY') && r.name.includes('WELCOME HOME'));
  assert.ok(bpl);
  assert.equal(bpl.inPerson, true);
  assert.equal(bpl.lat, 40.706926);
  assert.equal(bpl.lon, -73.957522);
  assert.ok(bpl.services.includes('Housing'));
  assert.equal(bpl.spanish, false);
});

test('empty and cross-reference rows are not listed; t/f spanish_speaking is typed', () => {
  const rows = rowsFromCsv(text);
  const empty = rows.find((row) => row.id === 4517);
  assert.ok(empty);
  assert.equal(isListed(empty), false);
  assert.equal(empty.latitude, null);
  assert.equal(empty.longitude, null);

  const listed = rows.filter(isListed);
  assert.ok(listed.some((row) => row.spanish_speaking === true));
  assert.ok(listed.some((row) => row.spanish_speaking === false));
  assert.ok(listed.every((row) => Array.isArray(row.service_types_all) || row.service_types_all == null));
});
