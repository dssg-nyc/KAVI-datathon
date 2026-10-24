// Imports "NYPL Connections Resources.csv" into public.resources using SUPABASE_SECRET_KEY.
// The secret key bypasses RLS, so this script must only ever run locally, never in the browser.
//
// Usage:
//   node scripts/database/import-csv.mjs [path-to-csv] [--dry-run] [--replace]
//     path-to-csv  defaults to data/NYPL Connections Resources.csv
//     --dry-run    parse and map the CSV, print a summary, insert nothing
//     --replace    delete every existing row in public.resources before inserting
// Without --replace the script refuses to run when the table already has rows, so a second
// run cannot duplicate the data.
import { readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..', '..');

// CSV header -> public.resources column (see supabase/migrations/*_reshape_resources_to_match_csv.sql).
const TEXT_COLUMNS = {
  'Organization Name': 'organization_name',
  'Street Number': 'street_number',
  'Address Line 2': 'address_line_2',
  'Street': 'street',
  'City': 'city',
  'State': 'state',
  'Zip Code': 'zip_code',
  'Phone Number': 'phone_number',
  'Website': 'website',
  'Description': 'description',
  'Category': 'category',
  'Subcategory': 'subcategory',
  'Notes': 'notes',
};
const YES_NO_COLUMNS = {
  'Spanish-speaking (Y/N)': 'spanish_speaking',
  'Works w/ Currently Incarcerated/Pre-release (Y/N)': 'works_with_currently_incarcerated',
  'ATI Program (Y/N)': 'ati_program',
  'Know Your Rights Content (Y/N)': 'know_your_rights_content',
};
const BATCH_SIZE = 500;

const args = process.argv.slice(2);
const csvPath = args.find((a) => !a.startsWith('--')) ?? join(root, 'data', 'NYPL Connections Resources.csv');
const dryRun = args.includes('--dry-run');
const replace = args.includes('--replace');

// RFC 4180 parser: quoted fields may contain commas, newlines and "" escapes.
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field); rows.push(row); row = []; field = '';
    } else field += c;
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row); }
  return rows.filter((r) => r.some((v) => v.trim() !== ''));
}

function toText(value) {
  const v = value.trim();
  return v === '' ? null : v;
}

// Blank means unknown, so it stays null rather than becoming false.
function toBoolean(value, header, line) {
  const v = value.trim().toUpperCase();
  if (v === '') return null;
  if (v === 'Y') return true;
  if (v === 'N') return false;
  throw new Error(`Line ${line}: "${header}" must be Y, N or blank, got "${value}"`);
}

const text = (await readFile(csvPath, 'utf8')).replace(/^﻿/, '');
const [headers, ...dataRows] = parseCsv(text);

const expected = [...Object.keys(TEXT_COLUMNS), ...Object.keys(YES_NO_COLUMNS)];
const missing = expected.filter((h) => !headers.includes(h));
const unknown = headers.filter((h) => !expected.includes(h));
if (missing.length || unknown.length) {
  console.error(`CSV headers do not match the table.\n  Missing: ${missing.join(', ') || 'none'}\n  Unknown: ${unknown.join(', ') || 'none'}`);
  process.exit(1);
}

const records = dataRows.map((cells, i) => {
  const line = i + 2;
  if (cells.length !== headers.length) {
    throw new Error(`Line ${line}: expected ${headers.length} fields, got ${cells.length}`);
  }
  const record = {};
  headers.forEach((header, j) => {
    if (header in TEXT_COLUMNS) record[TEXT_COLUMNS[header]] = toText(cells[j]);
    else record[YES_NO_COLUMNS[header]] = toBoolean(cells[j], header, line);
  });
  return record;
});

console.log(`Parsed ${records.length} rows from ${csvPath}`);
for (const column of Object.values(YES_NO_COLUMNS)) {
  const yes = records.filter((r) => r[column] === true).length;
  const no = records.filter((r) => r[column] === false).length;
  console.log(`  ${column}: ${yes} Y, ${no} N, ${records.length - yes - no} blank`);
}
if (dryRun) {
  console.log('Dry run: nothing inserted.');
  process.exit(0);
}

try {
  process.loadEnvFile(join(root, '.env'));
} catch {
  console.error('Missing .env. Run: cp .env.example .env  and paste in SUPABASE_SECRET_KEY.');
  process.exit(1);
}
const { SUPABASE_SECRET_KEY } = process.env;
if (!SUPABASE_SECRET_KEY || /^sb_secret_x+$/.test(SUPABASE_SECRET_KEY)) {
  console.error('.env must set a real SUPABASE_SECRET_KEY (Supabase dashboard -> Project Settings -> API Keys).');
  process.exit(1);
}

// The project URL lives in config.js, the same file the browser uses, so it is written down once.
// SUPABASE_URL in .env overrides it, e.g. to import into a different project.
const browserConfig = JSON.parse((await readFile(join(root, 'config.js'), 'utf8')).match(/\{[\s\S]*\}/)[0]);
const SUPABASE_URL = process.env.SUPABASE_URL || browserConfig.SUPABASE_URL;
console.log(`Importing into ${SUPABASE_URL}`);

const endpoint = `${SUPABASE_URL}/rest/v1/resources`;
const headersFor = (extra = {}) => ({ apikey: SUPABASE_SECRET_KEY, 'Content-Type': 'application/json', ...extra });

async function request(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`${options.method ?? 'GET'} ${url} -> ${res.status}: ${await res.text()}`);
  return res;
}

const countRes = await request(`${endpoint}?select=id&limit=1`, { headers: headersFor({ Prefer: 'count=exact' }) });
const existing = Number(countRes.headers.get('content-range')?.split('/')[1] ?? 0);
if (existing > 0 && !replace) {
  console.error(`public.resources already has ${existing} rows. Re-run with --replace to delete them and import again.`);
  process.exit(1);
}
if (existing > 0) {
  // PostgREST refuses a DELETE without a filter; id >= 0 matches every row.
  await request(`${endpoint}?id=gte.0`, { method: 'DELETE', headers: headersFor() });
  console.log(`Deleted ${existing} existing rows.`);
}

for (let i = 0; i < records.length; i += BATCH_SIZE) {
  const batch = records.slice(i, i + BATCH_SIZE);
  await request(endpoint, { method: 'POST', headers: headersFor({ Prefer: 'return=minimal' }), body: JSON.stringify(batch) });
  console.log(`Inserted rows ${i + 1}-${i + batch.length}`);
}
console.log(`Done: ${records.length} rows in public.resources.`);
