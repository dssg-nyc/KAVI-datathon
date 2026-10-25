// Imports the Connections Guide into public.resources using SUPABASE_SECRET_KEY.
// The secret key bypasses RLS, so this script must only ever run locally, never in the browser.
//
// Rows come from two files in data/:
//   nypl_connections_resources.geojson  one feature per row of "NYPL Connections Resources.csv",
//                                       in the same order, with coordinates and geocode_* fields
//                                       (built by scripts/nypl_connections_to_geojson.ts).
//   NYPLConnections_NoMatch.csv         copies of CSV rows the geocoders could not place. Only its
//                                       rows with lat/lon are used: each becomes an extra row,
//                                       inserted after the GeoJSON row with the same organization
//                                       name and copying that row's fields except the address.
//                                       Today that is the 5 NYC NEON clothing closet sites.
//   cleaned/resources_extended.csv      the cleaned rows with service types, row types and PDF
//                                       fields (scripts/cleaning/, scripts/pdf/). Its columns in
//                                       EXTENDED_COLUMNS are added to the GeoJSON row it was
//                                       cleaned from; NoMatch extra rows copy their parent's.
//
// Usage:
//   node scripts/database/import-resources.mjs [--dry-run] [--replace]
//     --dry-run    read and map both files, print a summary, insert nothing
//     --replace    delete every existing row in public.resources before inserting
// Without --replace the script refuses to run when the table already has rows, so a second
// run cannot duplicate the data.
import { readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..', '..');
const GEOJSON_PATH = join(root, 'data', 'nypl_connections_resources.geojson');
const NOMATCH_PATH = join(root, 'data', 'NYPLConnections_NoMatch.csv');
const EXTENDED_PATH = join(root, 'data', 'cleaned', 'resources_extended.csv');

// CSV header (a GeoJSON property name) -> public.resources column
// (see supabase/migrations/*_reshape_resources_to_match_csv.sql).
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
// GeoJSON property -> column (see supabase/migrations/*_add_geocode_columns_to_resources.sql).
// The addr:* properties repeat the address columns and are not imported.
const GEOCODE_COLUMNS = {
  'geocode_match': 'geocode_match',
  'geocode_source': 'geocode_source',
  'geocode_matched_address': 'geocode_matched_address',
  'geocode_review': 'geocode_review',
};
// resources_extended.csv column -> type of the public.resources column with the same name
// (see supabase/migrations/*_add_cleaned_and_pdf_columns_to_resources.sql).
// 'list' cells are "; "-separated and become text[].
const EXTENDED_COLUMNS = {
  resource_id: 'integer',
  service_type: 'text',
  service_type_suggested: 'list',
  borough: 'text',
  row_type: 'text',
  service_type_source: 'text',
  service_type_confidence: 'text',
  organization_service_types: 'list',
  service_type_conflict: 'boolean',
  needs_review: 'boolean',
  review_notes: 'text',
  pdf_match_method: 'text',
  pdf_listing_id: 'integer',
  pdf_chapter: 'text',
  pdf_section: 'text',
  pdf_preceding_subheading: 'text',
  pdf_guide_page: 'integer',
  pdf_is_cross_reference: 'boolean',
  pdf_section_service_type: 'text',
  pdf_appearances: 'list',
  pdf_org_service_types: 'list',
  pdf_audiences: 'list',
  service_type_extended: 'text',
  service_type_extended_source: 'text',
  service_subtype_extended: 'text',
  description_keyword_types: 'list',
  description_service_types: 'list',
  description_service_types_source: 'text',
  service_types_all: 'list',
  pdf_contradiction: 'text',
  needs_review_extended: 'boolean',
  review_notes_extended: 'text',
};
// The cleaning notebook merged GeoJSON feature 690 (no organization name; extra text for the row
// above) into resource_id 690, so resource_id N is feature N-1 up to 690 and feature N after it.
const MERGED_FEATURE_INDEX = 690;
const BATCH_SIZE = 500;

const args = process.argv.slice(2);
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
function toBoolean(value, header, where) {
  const v = value.trim().toUpperCase();
  if (v === '') return null;
  if (v === 'Y') return true;
  if (v === 'N') return false;
  throw new Error(`${where}: "${header}" must be Y, N or blank, got "${value}"`);
}

// --- GeoJSON: one record per feature, in file order ---

const geojson = JSON.parse(await readFile(GEOJSON_PATH, 'utf8'));
const expected = [...Object.keys(TEXT_COLUMNS), ...Object.keys(YES_NO_COLUMNS), ...Object.keys(GEOCODE_COLUMNS)];

const geojsonRecords = geojson.features.map((feature, i) => {
  const where = `Feature ${i}`;
  const props = feature.properties;
  const missing = expected.filter((key) => !(key in props));
  if (missing.length) throw new Error(`${where}: missing properties ${missing.join(', ')}`);

  const record = {};
  for (const [key, column] of Object.entries(TEXT_COLUMNS)) record[column] = toText(props[key]);
  for (const [key, column] of Object.entries(YES_NO_COLUMNS)) record[column] = toBoolean(props[key], key, where);
  for (const [key, column] of Object.entries(GEOCODE_COLUMNS)) record[column] = toText(props[key]);

  if (feature.geometry) {
    if (feature.geometry.type !== 'Point') throw new Error(`${where}: expected a Point, got ${feature.geometry.type}`);
    const [longitude, latitude] = feature.geometry.coordinates;
    Object.assign(record, { latitude, longitude });
  } else {
    Object.assign(record, { latitude: null, longitude: null });
  }
  return record;
});

// --- Extended CSV: new columns for the GeoJSON row each cleaned row came from ---

function toExtendedValue(value, type, column, where) {
  const v = value.trim();
  if (v === '') return null;
  if (type === 'text') return v;
  if (type === 'list') return v.split(';').map((s) => s.trim()).filter(Boolean);
  if (type === 'integer') {
    if (!/^\d+$/.test(v)) throw new Error(`${where}: ${column} must be an integer, got "${value}"`);
    return Number(v);
  }
  if (v === 'True') return true;
  if (v === 'False') return false;
  throw new Error(`${where}: ${column} must be True, False or blank, got "${value}"`);
}

const [extendedHeaders, ...extendedRows] = parseCsv(await readFile(EXTENDED_PATH, 'utf8'));
const missingExtended = Object.keys(EXTENDED_COLUMNS).filter((c) => !extendedHeaders.includes(c));
if (missingExtended.length) throw new Error(`${EXTENDED_PATH}: missing columns ${missingExtended.join(', ')}`);

const emptyExtended = Object.fromEntries(Object.keys(EXTENDED_COLUMNS).map((c) => [c, null]));
for (const record of geojsonRecords) Object.assign(record, emptyExtended);

const normalizeName = (name) => (name ?? '').trim().toLowerCase();
extendedRows.forEach((cells, i) => {
  const where = `${EXTENDED_PATH} line ${i + 2}`;
  const row = Object.fromEntries(extendedHeaders.map((h, j) => [h, cells[j] ?? '']));
  const resourceId = Number(row.resource_id);
  const featureIndex = resourceId <= MERGED_FEATURE_INDEX ? resourceId - 1 : resourceId;
  const record = geojsonRecords[featureIndex];
  if (!record) throw new Error(`${where}: resource_id ${resourceId} has no GeoJSON feature`);
  // The notebook fills in some blank names, so only a name that is set on both sides must agree.
  if (record.organization_name && normalizeName(record.organization_name) !== normalizeName(row.org_name)) {
    throw new Error(`${where}: org_name "${row.org_name}" does not match feature ${featureIndex} "${record.organization_name}"`);
  }
  for (const [column, type] of Object.entries(EXTENDED_COLUMNS)) record[column] = toExtendedValue(row[column], type, column, where);
});
const unmatchedFeatures = geojsonRecords.filter((r) => r.resource_id === null).length;

// --- Audience CSV: "Who is it for?" columns, joined by resource_id like the extended CSV ---
// (see scripts/audiences/README.md and supabase/migrations/*_add_audience_columns_to_resources.sql).

const AUDIENCES_PATH = join(root, 'data', 'cleaned', 'resource_audiences.csv');
const AUDIENCE_COLUMNS = {
  audiences_all: 'list',
  restricted_audiences: 'list',
  focus_audiences: 'list',
  confirmed_pdf_audiences: 'list',
  unconfirmed_pdf_audiences: 'list',
  pdf_audience_check: 'text',
  audience_restriction: 'text',
  restriction_evidence: 'text',
  everyone_basis: 'text',
  audience_needs_review: 'boolean',
  audience_reviewed: 'boolean',
};

const [audienceHeaders, ...audienceRows] = parseCsv(await readFile(AUDIENCES_PATH, 'utf8'));
const missingAudience = Object.keys(AUDIENCE_COLUMNS).filter((c) => !audienceHeaders.includes(c));
if (missingAudience.length) throw new Error(`${AUDIENCES_PATH}: missing columns ${missingAudience.join(', ')}`);

const emptyAudience = Object.fromEntries(Object.keys(AUDIENCE_COLUMNS).map((c) => [c, null]));
for (const record of geojsonRecords) Object.assign(record, emptyAudience);

audienceRows.forEach((cells, i) => {
  const where = `${AUDIENCES_PATH} line ${i + 2}`;
  const row = Object.fromEntries(audienceHeaders.map((h, j) => [h, cells[j] ?? '']));
  const record = geojsonRecords.find((r) => r.resource_id === Number(row.resource_id));
  if (!record) throw new Error(`${where}: resource_id ${row.resource_id} is not in ${EXTENDED_PATH}`);
  for (const [column, type] of Object.entries(AUDIENCE_COLUMNS)) record[column] = toExtendedValue(row[column], type, column, where);
});

// --- NoMatch CSV: extra rows for the entries that have coordinates ---

// The file is Windows-1252, not UTF-8 (its dashes are byte 0x97). Its header repeats City and
// State, so columns are read by position. Positions 0-9 are the address the coordinates belong to;
// positions 10-26 are the same columns as the main CSV.
const NOMATCH = { place: 0, address2: 1, city: 4, state: 6, zip: 7, organizationName: 10, lat: 28, lon: 29 };
const NOMATCH_HEADER_COUNT = 30;
const BOROUGH_BY_CITY = { 'New York': 'Manhattan', Brooklyn: 'Brooklyn', Bronx: 'Bronx', Queens: 'Queens', 'Staten Island': 'Staten Island' };

const [nomatchHeaders, ...nomatchRows] = parseCsv(new TextDecoder('windows-1252').decode(await readFile(NOMATCH_PATH)));
if (nomatchHeaders.length !== NOMATCH_HEADER_COUNT || nomatchHeaders[NOMATCH.lat] !== 'lat' || nomatchHeaders[NOMATCH.lon] !== 'lon') {
  throw new Error(`${NOMATCH_PATH}: header changed; update NOMATCH positions in this script.`);
}

const extras = [];
nomatchRows.forEach((cells, i) => {
  const where = `${NOMATCH_PATH} line ${i + 2}`;
  if (!cells[NOMATCH.lat].trim() && !cells[NOMATCH.lon].trim()) return;
  const latitude = Number(cells[NOMATCH.lat]);
  const longitude = Number(cells[NOMATCH.lon]);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) throw new Error(`${where}: lat/lon must both be numbers`);

  const name = cells[NOMATCH.organizationName].trim();
  const parentIndex = geojsonRecords.findLastIndex((r) => r.organization_name === name);
  if (parentIndex === -1) throw new Error(`${where}: no GeoJSON row has Organization Name "${name}"`);

  // "162-24 Jamaica Avenue" -> street_number "162-24", street "Jamaica Avenue".
  const place = cells[NOMATCH.place].trim();
  const [, streetNumber = null, street = place] = place.match(/^(\S*\d\S*)\s+(.+)$/) ?? [];
  // The parent row is the phone listing, so its row_type and borough do not describe this address.
  // Every extra row so far is a street address in NYC: the notebook's rules make that 'mapped'.
  const city = toText(cells[NOMATCH.city]);
  const borough = BOROUGH_BY_CITY[city];
  if (!borough) throw new Error(`${where}: city "${city}" is not in BOROUGH_BY_CITY`);
  const record = {
    ...geojsonRecords[parentIndex],
    street_number: streetNumber,
    address_line_2: toText(cells[NOMATCH.address2]),
    street,
    city,
    borough,
    row_type: 'mapped',
    state: toText(cells[NOMATCH.state]),
    zip_code: toText(cells[NOMATCH.zip]),
    latitude,
    longitude,
    geocode_match: 'matched',
    geocode_source: 'nomatch_csv',
    // No geocoder placed these points, and the NoMatch file does not say where they came from.
    geocode_matched_address: null,
    geocode_review: null,
  };
  extras.push({ parentIndex, record });
});

// Each extra row goes right after its parent row; extras for one parent keep file order.
const records = geojsonRecords.flatMap((record, i) => [record, ...extras.filter((e) => e.parentIndex === i).map((e) => e.record)]);

console.log(`Read ${geojsonRecords.length} rows from ${GEOJSON_PATH}`);
console.log(`Read ${extras.length} extra rows with coordinates from ${NOMATCH_PATH}`);
console.log(`Read ${extendedRows.length} rows from ${EXTENDED_PATH}; ${unmatchedFeatures} GeoJSON rows have no extended row`);
console.log(`Read ${audienceRows.length} rows from ${AUDIENCES_PATH}`);
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
