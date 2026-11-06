// Gives every resource an id that does not change between builds.
//
// The database id changes on every `import --replace`, and resource_id is the row's position in
// the guide export, which repeats (the NEON clothing closets are five rows for one resource_id)
// and would shift if NYPL re-exported the guide. So the id is taken from resource_id, with a
// suffix where it repeats, and the result is written to data/resource_ids.csv and committed.
// On the next run a row is looked up in that file by name and address first, so it keeps its id
// even if its resource_id moved; only rows not seen before get a new id. A row that is no longer
// in the data stays in the file as retired, so its id is never given to another resource.
//
//   node pipeline/6_build/resource_ids.ts            check: fail if the file would change
//   node pipeline/6_build/resource_ids.ts --write    update data/resource_ids.csv
import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { mapResources, parseCsv, type ResourceRow } from '../5_load/map_resources.mjs';

const root = join(import.meta.dirname, '..', '..');
export const MAPPING_PATH = join(root, 'data', 'resource_ids.csv');
export const MAPPING_COLUMNS = ['id', 'status', 'resource_id', 'organization_name', 'street_number', 'street', 'city', 'zip_code'] as const;

export type MappingRow = Record<(typeof MAPPING_COLUMNS)[number], string>;

const text = (v: ResourceRow[string]) => (v == null ? '' : String(v));

// How a row is recognised across builds: its name and address, case and spacing ignored.
export function fingerprint(row: Pick<MappingRow, 'resource_id' | 'organization_name' | 'street_number' | 'street' | 'city' | 'zip_code'>): string {
  const key = [row.organization_name, row.street_number, row.street, row.city, row.zip_code]
    .map((v) => v.toLowerCase().replace(/\s+/g, ' ').trim())
    .join('|');
  // A row with no name or address (one such row exists) is matched by its source id instead, so a reorder
  // of the source cannot swap its id with another blank row's.
  return key === '||||' ? `resource_id:${row.resource_id.trim()}` : key;
}

function describe(record: ResourceRow): Omit<MappingRow, 'id' | 'status'> {
  return {
    resource_id: text(record.resource_id),
    organization_name: text(record.organization_name),
    street_number: text(record.street_number),
    street: text(record.street),
    city: text(record.city),
    zip_code: text(record.zip_code),
  };
}

// The mapping for these records, given the committed one. Rows come out in record order, then
// the retired rows in their old order.
export function assignIds(records: ResourceRow[], existing: MappingRow[]): { rows: MappingRow[]; kept: number; added: number; retired: number } {
  const unclaimed = new Map<string, MappingRow[]>();
  for (const row of existing) {
    const key = fingerprint(row);
    unclaimed.set(key, [...(unclaimed.get(key) ?? []), row]);
  }
  const taken = new Set(existing.map((r) => r.id));
  const rows: MappingRow[] = [];
  let kept = 0;
  let added = 0;
  records.forEach((record, index) => {
    const fields = describe(record);
    const previous = unclaimed.get(fingerprint(fields))?.shift();
    if (previous) {
      kept++;
      rows.push({ id: previous.id, status: 'active', ...fields });
      return;
    }
    const base = fields.resource_id || `feature-${index}`;
    let id = base;
    for (let n = 2; taken.has(id); n++) id = `${base}-${n}`;
    taken.add(id);
    added++;
    rows.push({ id, status: 'active', ...fields });
  });
  const retired = [...unclaimed.values()].flat();
  for (const row of retired) rows.push({ ...row, status: 'retired' });
  return { rows, kept, added, retired: retired.length };
}

function csvCell(v: string): string {
  return /[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

export function toCsv(rows: MappingRow[]): string {
  const lines = [MAPPING_COLUMNS.join(',')];
  for (const row of rows) lines.push(MAPPING_COLUMNS.map((c) => csvCell(row[c])).join(','));
  return lines.join('\n') + '\n';
}

export function fromCsv(content: string): MappingRow[] {
  const [header, ...body] = parseCsv(content);
  const missing = MAPPING_COLUMNS.filter((c) => !header?.includes(c));
  if (missing.length) throw new Error(`${MAPPING_PATH}: missing columns ${missing.join(', ')}`);
  return body.map((cells) => Object.fromEntries(header.map((h, j) => [h, cells[j] ?? ''])) as MappingRow);
}

export async function readMapping(path = MAPPING_PATH): Promise<MappingRow[]> {
  try {
    return fromCsv(await readFile(path, 'utf8'));
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw e;
  }
}

async function main(): Promise<void> {
  const write = process.argv.includes('--write');
  const existing = await readMapping();
  const { records } = await mapResources(root);
  const { rows, kept, added, retired } = assignIds(records, existing);
  const ids = rows.map((r) => r.id);
  if (new Set(ids).size !== ids.length) throw new Error('ids are not unique');
  console.log(`${records.length} rows: ${kept} keep their id, ${added} new, ${retired} retired`);
  const next = toCsv(rows);
  const current = existing.length ? toCsv(existing) : '';
  if (next === current) {
    console.log(`${MAPPING_PATH} is up to date`);
    return;
  }
  if (!write) {
    console.error(`${MAPPING_PATH} would change. Run with --write to update it, then commit the file.`);
    process.exit(1);
  }
  await writeFile(MAPPING_PATH, next);
  console.log(`Wrote ${MAPPING_PATH}`);
}

if (process.argv[1] === import.meta.filename) await main();
