// Tests for pipeline/6_build/resource_ids.ts. Run with: node --test pipeline/6_build/__tests__/resource_ids.test.ts
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { mapResources, type ResourceRow } from '../../5_load/map_resources.mjs';
import { assignIds, fingerprint, fromCsv, readMapping, toCsv, type MappingRow } from '../resource_ids.ts';

const root = join(import.meta.dirname, '..', '..', '..');

function row(resource_id: number | null, organization_name: string, street: string | null = null): ResourceRow {
  return { resource_id, organization_name, street_number: null, street, city: null, zip_code: null };
}

describe('assignIds', () => {
  test('ids come from resource_id, with a suffix where it repeats', () => {
    const { rows, added } = assignIds([row(1, 'A'), row(2, 'NEON'), row(2, 'NEON', 'Adams St'), row(2, 'NEON', 'Bay St')], []);
    assert.deepEqual(rows.map((r) => r.id), ['1', '2', '2-2', '2-3']);
    assert.equal(added, 4);
  });
  test('a row without a resource_id is named by its position', () => {
    const { rows } = assignIds([row(1, 'A'), row(null, '')], []);
    assert.equal(rows[1].id, 'feature-1');
  });
  test('a row keeps its id when its resource_id moves', () => {
    const first = assignIds([row(1, 'A'), row(2, 'B')], []).rows;
    const { rows, kept, added } = assignIds([row(1, 'New'), row(2, 'A'), row(3, 'B')], first);
    assert.deepEqual(rows.map((r) => [r.id, r.organization_name]), [['1-2', 'New'], ['1', 'A'], ['2', 'B']]);
    assert.equal(kept, 2);
    assert.equal(added, 1);
  });
  test('a row that disappears is retired and its id is not reused', () => {
    const first = assignIds([row(1, 'A'), row(2, 'B')], []).rows;
    const second = assignIds([row(1, 'A')], first).rows;
    assert.deepEqual(second.map((r) => [r.id, r.status]), [['1', 'active'], ['2', 'retired']]);
    const third = assignIds([row(1, 'A'), row(2, 'C')], second).rows;
    assert.deepEqual(third.map((r) => [r.id, r.organization_name, r.status]), [['1', 'A', 'active'], ['2-2', 'C', 'active'], ['2', 'B', 'retired']]);
  });
  test('fingerprints ignore case and spacing', () => {
    const a = { organization_name: 'The  Fortune Society', street_number: '29-76', street: 'Northern Blvd', city: 'Queens', zip_code: '11101' };
    assert.equal(fingerprint(a), fingerprint({ ...a, organization_name: 'the fortune society ', street: 'northern  blvd' }));
  });
  test('the CSV round-trips', () => {
    const rows: MappingRow[] = [{ id: '1', status: 'active', resource_id: '1', organization_name: 'A, "B"', street_number: '', street: '', city: '', zip_code: '' }];
    assert.deepEqual(fromCsv(toCsv(rows)), rows);
  });
});

describe('the committed mapping', async () => {
  const existing = await readMapping();
  const { records } = await mapResources(root);
  const { rows, added, retired } = assignIds(records, existing);

  test('is what the committed data produces, so ids do not change between builds', () => {
    assert.equal(toCsv(rows), toCsv(existing));
    assert.equal(added, 0);
    assert.equal(retired, 0);
  });
  test('has one active id per row and no duplicates', () => {
    const active = existing.filter((r) => r.status === 'active');
    assert.equal(active.length, records.length);
    assert.equal(new Set(existing.map((r) => r.id)).size, existing.length);
  });
});
