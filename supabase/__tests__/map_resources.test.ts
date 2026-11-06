// Tests for pipeline/5_load/map_resources.mjs, the mapping from the pipeline's files to the rows of
// public.resources. Run with: node --test pipeline/5_load/__tests__/map_resources.test.ts
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { AUDIENCE_COLUMNS, EXTENDED_COLUMNS, mapResources, toBoolean, toExtendedValue } from '../map_resources.mjs';

const root = resolve(import.meta.dirname, '..', '..', '..');

describe('toExtendedValue', () => {
  test('blank is null for every type', () => {
    for (const type of ['text', 'list', 'integer', 'boolean']) assert.equal(toExtendedValue('  ', type, 'c', 'w'), null);
  });
  test('lists split on ; and drop empty items', () => {
    assert.deepEqual(toExtendedValue('Housing; Food; ', 'list', 'c', 'w'), ['Housing', 'Food']);
  });
  test('integers and booleans are strict', () => {
    assert.equal(toExtendedValue('42', 'integer', 'c', 'w'), 42);
    assert.throws(() => toExtendedValue('4.2', 'integer', 'c', 'w'), /must be an integer/);
    assert.equal(toExtendedValue('True', 'boolean', 'c', 'w'), true);
    assert.throws(() => toExtendedValue('yes', 'boolean', 'c', 'w'), /must be True, False or blank/);
  });
  test('Y/N columns keep blank as unknown', () => {
    assert.equal(toBoolean('', 'h', 'w'), null);
    assert.equal(toBoolean('y', 'h', 'w'), true);
    assert.throws(() => toBoolean('maybe', 'h', 'w'), /must be Y, N or blank/);
  });
});

describe('mapResources on the committed data', async () => {
  const { records, counts } = await mapResources(root);

  test('one row per GeoJSON feature plus the located NoMatch rows', () => {
    assert.equal(records.length, counts.geojson + counts.extras);
    assert.equal(counts.geojson, 760);
    assert.equal(counts.extras, 5);
  });
  test('every row has every column the table expects', () => {
    const columns = ['organization_name', 'latitude', 'longitude', 'geocode_match', ...Object.keys(EXTENDED_COLUMNS), ...Object.keys(AUDIENCE_COLUMNS)];
    for (const record of records) for (const column of columns) assert.ok(column in record, `${column} missing`);
  });
  test('extended rows join onto the right feature', () => {
    const named = records.filter((r) => r.resource_id !== null && r.organization_name);
    assert.ok(named.length > 700);
    assert.equal(counts.unmatchedFeatures, 1);
  });
  test('NoMatch extras follow their parent and carry its fields', () => {
    const extras = records.map((r, i) => [r, i] as const).filter(([r]) => r.geocode_source === 'nomatch_csv');
    assert.equal(extras.length, counts.extras);
    for (const [extra, i] of extras) {
      const parent = records.slice(0, i).findLast((r) => r.geocode_source !== 'nomatch_csv');
      assert.ok(parent);
      assert.equal(extra.organization_name, parent.organization_name);
      assert.equal(extra.resource_id, parent.resource_id);
      assert.equal(extra.row_type, 'mapped');
      assert.ok(typeof extra.latitude === 'number' && typeof extra.longitude === 'number');
    }
  });
});
