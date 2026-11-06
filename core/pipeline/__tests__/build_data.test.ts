// Tests for pipeline/6_build/build_data.ts. Run with: node --test pipeline/6_build/__tests__/build_data.test.ts
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { META_PATH, PUBLIC_COLUMNS, PUBLIC_PATH, PROVENANCE_PATH, NEEDS_ADDRESS_PATH, REVIEW_FLAGS, SOURCE, buildData, metaJson, needsAddress, reviewFlags, splitRows, toJson } from '../build_data.ts';

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
    assert.deepEqual(publicRows[0].review_flags, reviewFlags(record));
  });
  test('provenance rows carry the id and every other column', () => {
    assert.deepEqual(provenanceRows[0], { id: '7', needs_review: true, geocode_match: 'match' });
  });
  test('JSON is one row per line', () => {
    assert.equal(toJson([{ a: 1 }, { b: [2] }]), '[\n  {"a":1},\n  {"b":[2]}\n]\n');
  });
});

describe('reviewFlags', () => {
  // A row with everything confirmed: guide-mapped services, checked audiences, stated eligibility, a clean geocode, no notes.
  const clean = {
    service_type_extended_source: 'pr:guide_mapping', description_service_types_source: 'description_keywords',
    audience_needs_review: false, everyone_basis: 'stated', geocode_match: 'matched', geocode_review: null,
    needs_review_extended: false, review_notes_extended: null,
  };
  // What raises each flag on its own.
  const raise: Record<(typeof REVIEW_FLAGS)[number], object> = {
    services: { service_type_extended_source: 'pr:description_match' },
    audiences: { audience_needs_review: true },
    eligibility: { everyone_basis: 'assumed' },
    location: { geocode_match: 'unmatched' },
    details: { needs_review_extended: true, review_notes_extended: 'In NoMatch file' },
  };

  test('a confirmed row has no flags', () => {
    assert.deepEqual(reviewFlags(clean), []);
  });
  test('each flag is raised by its own column, alone', () => {
    for (const flag of REVIEW_FLAGS) assert.deepEqual(reviewFlags({ ...clean, ...raise[flag] }), [flag]);
  });
  test('every combination of flags comes out in REVIEW_FLAGS order', () => {
    for (let bits = 0; bits < 1 << REVIEW_FLAGS.length; bits++) {
      const expected = REVIEW_FLAGS.filter((_, i) => bits & (1 << i));
      const record = Object.assign({ ...clean }, ...expected.map((flag) => raise[flag]));
      assert.deepEqual(reviewFlags(record), expected, `bits ${bits.toString(2)}`);
    }
  });
  test('services are confirmed by the guide chapter, the organization or a person; a geocoder note flags the location', () => {
    assert.deepEqual(reviewFlags({ ...clean, service_type_extended_source: 'pdf_section' }), []);
    assert.deepEqual(reviewFlags({ ...clean, service_type_extended_source: 'pr:organization_consensus' }), []);
    assert.deepEqual(reviewFlags({ ...clean, service_type_extended_source: 'unassigned', description_service_types_source: 'human_agreed' }), []);
    assert.deepEqual(reviewFlags({ ...clean, service_type_extended_source: 'unassigned' }), ['services']);
    assert.deepEqual(reviewFlags({ ...clean, service_type_extended_source: null, description_service_types_source: null }), ['services']);
    assert.deepEqual(reviewFlags({ ...clean, geocode_review: 'Confirm the location.' }), ['location']);
  });
  test('"service_type to assign" alone is the services flag, not a details note', () => {
    assert.deepEqual(reviewFlags({ ...clean, needs_review_extended: true, review_notes_extended: 'service_type to assign' }), []);
    assert.deepEqual(reviewFlags({ ...clean, needs_review_extended: true, review_notes_extended: 'In NoMatch file | service_type to assign' }), ['details']);
  });
});

describe('metaJson', () => {
  test('names the source and dates the data', async () => {
    const meta = JSON.parse(await metaJson({ [PUBLIC_PATH]: 'changed' }, new Date('2026-01-02T15:00:00Z')));
    assert.deepEqual(meta, { source: SOURCE, data_updated: '2026-01-02' });
  });
  test('keeps the committed date while the row files are unchanged', async () => {
    const committed = JSON.parse(await readFile(META_PATH, 'utf8'));
    const same = { [PUBLIC_PATH]: await readFile(PUBLIC_PATH, 'utf8'), [PROVENANCE_PATH]: await readFile(PROVENANCE_PATH, 'utf8') };
    assert.deepEqual(JSON.parse(await metaJson(same, new Date('2099-01-01'))), committed);
    assert.match(committed.data_updated, /^\d{4}-\d{2}-\d{2}$/);
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
  test('together hold every column of the resources table, each exactly once, plus the derived review_flags', () => {
    const columns = [...Object.keys(publicRows[0]), ...Object.keys(provenanceRows[0]).filter((c) => c !== 'id')];
    assert.deepEqual([...columns].sort(), [...tableColumns, 'review_flags'].sort());
  });
  test('flag what the data says is unconfirmed', () => {
    const flagged = (flag: string) => publicRows.filter((r: { review_flags: string[] }) => r.review_flags.includes(flag)).length;
    assert.equal(flagged('audiences'), records.filter((r) => r.audience_needs_review === true).length);
    assert.equal(flagged('eligibility'), records.filter((r) => r.everyone_basis === 'assumed').length);
    assert.ok(flagged('services') > 0 && flagged('location') > 0 && flagged('details') > 0);
  });
  test('list the rows with an address but no map point', async () => {
    const lines = (await readFile(NEEDS_ADDRESS_PATH, 'utf8')).trim().split('\n');
    assert.equal(lines.length - 1, records.filter(needsAddress).length);
  });
});
