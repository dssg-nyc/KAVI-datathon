// Tests for pipeline/6_build/build_data.ts. Run with: node --test pipeline/6_build/__tests__/build_data.test.ts
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { PUBLIC_COLUMNS, PUBLIC_PATH, PROVENANCE_PATH, NEEDS_ADDRESS_PATH, buildData, needsAddress, splitRows, toJson } from '../build_data.ts';

const root = join(import.meta.dirname, '..', '..', '..');
const kaviSchema = JSON.parse(await readFile(join(root, 'pipeline', 'schemas', 'kavi_resources.json'), 'utf8'));
const tableColumns = Object.entries(kaviSchema.columns as Record<string, { planned?: boolean }>)
  .filter(([, spec]) => !spec.planned)
  .map(([name]) => name);

describe('splitRows', () => {
  const record = { organization_name: 'A', street: null, latitude: 40.7, service_types_all: ['Food'], needs_review: true, geocode_match: 'match' };
  const { publicRows, provenanceRows } = splitRows([record], ['7']);

  test('public rows have exactly the public columns, blank where the record has none', () => {
    assert.deepEqual(Object.keys(publicRows[0]), [...PUBLIC_COLUMNS]);
    assert.equal(publicRows[0].id, '7');
    assert.equal(publicRows[0].organization_name, 'A');
    assert.equal(publicRows[0].row_type, null);
  });
  test('provenance rows carry the id and every other column', () => {
    assert.deepEqual(provenanceRows[0], { id: '7', needs_review: true, geocode_match: 'match' });
  });
  test('JSON is one row per line', () => {
    assert.equal(toJson([{ a: 1 }, { b: [2] }]), '[\n  {"a":1},\n  {"b":[2]}\n]\n');
  });
});

describe('needsAddress', () => {
  test('is a placeable row with a street but no coordinates', () => {
    assert.equal(needsAddress({ row_type: 'mapped', street: 'Main St', latitude: null }), true);
    assert.equal(needsAddress({ row_type: 'mailing_address', street_number: '1', street: null, latitude: null }), true);
    assert.equal(needsAddress({ row_type: 'mapped', street: 'Main St', latitude: 40.7 }), false);
    assert.equal(needsAddress({ row_type: 'hotline', street: 'Main St', latitude: null }), false);
    assert.equal(needsAddress({ row_type: 'mapped', street: null, street_number: null, latitude: null }), false);
  });
});

describe('the committed files', async () => {
  const { records, files } = await buildData();
  const publicRows = JSON.parse(await readFile(PUBLIC_PATH, 'utf8'));
  const provenanceRows = JSON.parse(await readFile(PROVENANCE_PATH, 'utf8'));

  test('are what the committed data produces', async () => {
    for (const [path, content] of Object.entries(files)) assert.equal(await readFile(path, 'utf8'), content, path);
  });
  test('keep every row the loader produces (D2: nothing is dropped between source and site)', () => {
    assert.equal(publicRows.length, records.length);
    assert.equal(provenanceRows.length, records.length);
    assert.equal(records.length, 765);
  });
  test('use ids that are unique and the same in both files', () => {
    const ids = publicRows.map((r: { id: string }) => r.id);
    assert.equal(new Set(ids).size, ids.length);
    assert.deepEqual(provenanceRows.map((r: { id: string }) => r.id), ids);
  });
  test('together hold every column of the resources table, each exactly once', () => {
    const columns = [...Object.keys(publicRows[0]), ...Object.keys(provenanceRows[0]).filter((c) => c !== 'id')];
    assert.deepEqual([...columns].sort(), [...tableColumns].sort());
  });
  test('list the rows with an address but no map point', async () => {
    const lines = (await readFile(NEEDS_ADDRESS_PATH, 'utf8')).trim().split('\n');
    assert.equal(lines.length - 1, records.filter(needsAddress).length);
  });
});
