// Imports the Connections Guide into public.resources using SUPABASE_SECRET_KEY.
// The secret key bypasses RLS, so this script must only ever run locally, never in the browser.
//
// The rows come from map_resources.mjs, which reads data/nypl_connections_resources.geojson,
// data/cleaned/resources_extended.csv, data/cleaned/resource_audiences.csv and
// data/NYPLConnections_NoMatch.csv and says how each becomes a column. This script prints a
// summary of those rows and sends them to Supabase.
//
// Usage:
//   node supabase/load_supabase.mjs [--dry-run] [--replace]
//     --dry-run    read and map the files, print a summary, insert nothing
//     --replace    delete every existing row in public.resources before inserting
// Without --replace the script refuses to run when the table already has rows, so a second
// run cannot duplicate the data.
import { readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { YES_NO_COLUMNS, mapResources } from './map_resources.mjs';

const root = resolve(import.meta.dirname, '..');
const BATCH_SIZE = 500;

const args = process.argv.slice(2);
const dryRun = args.includes('--dry-run');
const replace = args.includes('--replace');

const { records, paths, counts } = await mapResources(root);

console.log(`Read ${counts.geojson} rows from ${paths.geojson}`);
console.log(`Read ${counts.extras} extra rows with coordinates from ${paths.nomatch}`);
console.log(`Read ${counts.extended} rows from ${paths.extended}; ${counts.unmatchedFeatures} GeoJSON rows have no extended row`);
console.log(`Read ${counts.audiences} rows from ${paths.audiences}`);
console.log(`Total: ${records.length} rows, ${records.filter((r) => r.latitude !== null).length} with coordinates`);
for (const column of Object.values(YES_NO_COLUMNS)) {
  const yes = records.filter((r) => r[column] === true).length;
  const no = records.filter((r) => r[column] === false).length;
  console.log(`  ${column}: ${yes} Y, ${no} N, ${records.length - yes - no} blank`);
}
for (const column of ['geocode_match', 'geocode_source', 'row_type', 'borough']) {
  const counts = Object.groupBy(records, (r) => r[column] ?? 'null');
  console.log(`  ${column}: ${Object.entries(counts).map(([k, v]) => `${v.length} ${k}`).join(', ')}`);
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

// The project URL lives in app/config.js, the same file the browser uses, so it is written down once.
// SUPABASE_URL in .env overrides it, e.g. to import into a different project.
const browserConfig = JSON.parse((await readFile(join(root, 'app/config.js'), 'utf8')).match(/\{[\s\S]*\}/)[0]);
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
