// Writes the data files the site reads, from the pipeline's output.
//
// The rows are the same ones the loader sends to Supabase (5_load/map_resources.mjs), keyed by the
// stable id from data/resource_ids.csv instead of the database id. They are split in two files:
//
//   data/public/resources.public.json      the columns the finder shows and filters on
//   data/public/resources.provenance.json  everything else: source fields, review flags, how each
//                                          value was derived; joined to the public file by id
//
// Every row goes into both files, including the cross-reference and blank rows; the finder decides
// what to list, as it does today. The files are committed, so the site needs no build step on
// deploy and a change to the data shows up as a diff. A third file, data/review/needs_address.csv,
// lists the rows that have an address but no point on the map, for someone to check.
//
//   node pipeline/6_build/build_data.ts            check: fail if any file would change
//   node pipeline/6_build/build_data.ts --write    write the files
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { mapResources, type ResourceRow } from '../5_load/map_resources.mjs';
import { assignIds, readMapping, toCsv as mappingToCsv } from './resource_ids.ts';

const root = join(import.meta.dirname, '..', '..');
export const PUBLIC_PATH = join(root, 'data', 'public', 'resources.public.json');
export const PROVENANCE_PATH = join(root, 'data', 'public', 'resources.provenance.json');
export const NEEDS_ADDRESS_PATH = join(root, 'data', 'review', 'needs_address.csv');

// What the finder reads (app/lib/csv.js FINDER_COLUMNS), with the stable id in place of the database one.
export const PUBLIC_COLUMNS = [
  'id', 'resource_id', 'organization_name', 'street_number', 'street', 'address_line_2', 'city', 'state', 'zip_code',
  'phone_number', 'website', 'description', 'spanish_speaking', 'latitude', 'longitude', 'borough', 'row_type',
  'service_types_all', 'audiences_all', 'restricted_audiences', 'focus_audiences', 'pdf_audiences',
] as const;

export type PublicRow = Record<(typeof PUBLIC_COLUMNS)[number], ResourceRow[string]>;
export type ProvenanceRow = Record<string, ResourceRow[string]>;

// A row that someone could place on the map but the geocoder did not: it names a street but has no
// coordinates, and is not a hotline, web-only or cross-reference listing.
export function needsAddress(record: ResourceRow): boolean {
  const placeable = ['mapped', 'mailing_address', 'outside_nyc'].includes(String(record.row_type));
  return placeable && record.latitude == null && Boolean(record.street || record.street_number);
}

export function splitRows(records: ResourceRow[], ids: string[]): { publicRows: PublicRow[]; provenanceRows: ProvenanceRow[] } {
  const publicRows: PublicRow[] = [];
  const provenanceRows: ProvenanceRow[] = [];
  records.forEach((record, i) => {
    const pub = { id: ids[i] } as PublicRow;
    const prov: ProvenanceRow = { id: ids[i] };
    for (const column of PUBLIC_COLUMNS) if (column !== 'id') pub[column] = record[column] ?? null;
    for (const [column, value] of Object.entries(record)) {
      if (!(PUBLIC_COLUMNS as readonly string[]).includes(column)) prov[column] = value;
    }
    publicRows.push(pub);
    provenanceRows.push(prov);
  });
  return { publicRows, provenanceRows };
}

// One row per line, so a data change is a readable diff.
export function toJson(rows: object[]): string {
  return `[\n${rows.map((r) => `  ${JSON.stringify(r)}`).join(',\n')}\n]\n`;
}

function csvCell(v: ResourceRow[string]): string {
  const s = v == null ? '' : String(v);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function needsAddressCsv(records: ResourceRow[], ids: string[]): string {
  const columns = ['id', 'organization_name', 'row_type', 'street_number', 'street', 'address_line_2', 'city', 'state', 'zip_code', 'geocode_match', 'geocode_review'];
  const lines = [columns.join(',')];
  records.forEach((record, i) => {
    if (!needsAddress(record)) return;
    lines.push(columns.map((c) => csvCell(c === 'id' ? ids[i] : record[c])).join(','));
  });
  return lines.join('\n') + '\n';
}

export async function buildData(): Promise<{ records: ResourceRow[]; files: Record<string, string> }> {
  const { records } = await mapResources(root);
  const existing = await readMapping();
  const { rows: mapping } = assignIds(records, existing);
  if (mappingToCsv(mapping) !== mappingToCsv(existing)) {
    throw new Error('data/resource_ids.csv is out of date: run `npm run ids -- --write` first and commit it');
  }
  const ids = mapping.slice(0, records.length).map((r) => r.id);
  const { publicRows, provenanceRows } = splitRows(records, ids);
  return {
    records,
    files: {
      [PUBLIC_PATH]: toJson(publicRows),
      [PROVENANCE_PATH]: toJson(provenanceRows),
      [NEEDS_ADDRESS_PATH]: needsAddressCsv(records, ids),
    },
  };
}

async function main(): Promise<void> {
  const write = process.argv.includes('--write');
  const { records, files } = await buildData();
  console.log(`${records.length} rows, ${records.filter(needsAddress).length} with an address but no point on the map`);
  let stale = 0;
  for (const [path, content] of Object.entries(files)) {
    const current = await readFile(path, 'utf8').catch(() => '');
    if (current === content) {
      console.log(`${path} is up to date`);
      continue;
    }
    stale++;
    if (write) {
      await mkdir(join(path, '..'), { recursive: true });
      await writeFile(path, content);
      console.log(`Wrote ${path}`);
    } else {
      console.error(`${path} would change`);
    }
  }
  if (stale && !write) {
    console.error('Run with --write to update the files, then commit them.');
    process.exit(1);
  }
}

if (process.argv[1] === import.meta.filename) await main();
