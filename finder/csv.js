// Parse a public.resources export (data/kavi_resources.csv) into the row shape
// toResource() already filters on. Postgres dumps arrays as {a,"b c"} and
// booleans as t/f; the map needs JS arrays, real booleans, and numeric lat/lon.

export const KAVI_CSV_PATH = 'data/kavi_resources.csv';

// Columns the finder reads. Extra CSV columns are ignored.
export const FINDER_COLUMNS = [
  'id', 'organization_name', 'street_number', 'street', 'address_line_2', 'city', 'state', 'zip_code',
  'phone_number', 'website', 'description', 'spanish_speaking', 'latitude', 'longitude', 'borough', 'row_type',
  'service_types_all', 'pdf_audiences', 'resource_id', 'audiences_all', 'restricted_audiences', 'focus_audiences',
];

export const ROW_TYPES = ['mapped', 'outside_nyc', 'mailing_address', 'hotline', 'web_only', 'cross_reference'];
export const BOROUGHS = ['Manhattan', 'Brooklyn', 'Queens', 'Bronx', 'Staten Island'];

const LIST_COLUMNS = ['service_types_all', 'pdf_audiences', 'audiences_all', 'restricted_audiences', 'focus_audiences'];
const BOOL_COLUMNS = ['spanish_speaking'];
const INT_COLUMNS = ['id', 'resource_id'];
const NUM_COLUMNS = ['latitude', 'longitude'];

// RFC 4180: quoted fields may contain commas, newlines and "" escapes.
export function parseCsv(text) {
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
  return rows.filter((r) => r.some((v) => String(v).trim() !== ''));
}

export function parsePgArray(cell) {
  const inner = cell.slice(1, -1);
  if (inner === '') return [];
  const items = [];
  let cur = '';
  let inQ = false;
  for (let i = 0; i < inner.length; i++) {
    const c = inner[i];
    if (inQ) {
      if (c === '"' && inner[i + 1] === '"') { cur += '"'; i++; }
      else if (c === '"') inQ = false;
      else cur += c;
    } else if (c === '"') inQ = true;
    else if (c === ',') { items.push(cur); cur = ''; }
    else cur += c;
  }
  items.push(cur);
  return items;
}

// Postgres {a,"b c"}, the pipeline's "a; b", a single value, or blank → null.
export function parseList(cell) {
  const v = (cell ?? '').trim();
  if (v === '') return null;
  if (v.startsWith('{') && v.endsWith('}')) return parsePgArray(v);
  if (v.includes(';')) return v.split(';').map((s) => s.trim()).filter(Boolean);
  return [v];
}

export function parseBool(cell) {
  const v = (cell ?? '').trim().toLowerCase();
  if (v === '') return null;
  if (['t', 'true', 'y', 'yes', '1'].includes(v)) return true;
  if (['f', 'false', 'n', 'no', '0'].includes(v)) return false;
  return undefined;
}

function emptyToNull(value) {
  const v = (value ?? '').trim();
  return v === '' ? null : v;
}

function parseIntCell(cell) {
  const v = emptyToNull(cell);
  if (v === null) return null;
  if (!/^-?\d+$/.test(v)) return undefined;
  return Number(v);
}

function parseNumCell(cell) {
  const v = emptyToNull(cell);
  if (v === null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

export function recordsFromCsv(text) {
  const [header, ...body] = parseCsv(text);
  if (!header) return [];
  return body.map((cells) => Object.fromEntries(header.map((h, j) => [h, cells[j] ?? ''])));
}

// One raw CSV record → the object toResource() expects (typed columns only).
export function toFinderRow(raw) {
  const row = {};
  for (const column of FINDER_COLUMNS) {
    const cell = raw[column];
    if (LIST_COLUMNS.includes(column)) row[column] = parseList(cell);
    else if (BOOL_COLUMNS.includes(column)) row[column] = parseBool(cell);
    else if (INT_COLUMNS.includes(column)) row[column] = parseIntCell(cell);
    else if (NUM_COLUMNS.includes(column)) row[column] = parseNumCell(cell);
    else row[column] = emptyToNull(cell);
  }
  return row;
}

export function rowsFromCsv(text) {
  return recordsFromCsv(text).map(toFinderRow);
}

// Whether a row can become a map pin: both coordinates finite, not swapped, in range.
export function pointCoordinates(row) {
  const lat = row.latitude;
  const lon = row.longitude;
  if (lat == null && lon == null) return null;
  if (lat == null || lon == null) return { error: 'one coordinate missing' };
  if (typeof lat !== 'number' || typeof lon !== 'number' || !Number.isFinite(lat) || !Number.isFinite(lon)) {
    return { error: 'non-numeric coordinates' };
  }
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return { error: 'coordinates out of range' };
  if (lat < -70 && lat > -80 && lon > 39 && lon < 42) return { error: 'latitude/longitude look swapped' };
  return { lat, lon };
}

// GeoJSON FeatureCollection the map layer draws: one Point per distinct coordinate.
export function mapLayerCollection(resources) {
  const groups = new Map();
  for (const r of resources) {
    if (!r.inPerson) continue;
    const key = `${r.lat.toFixed(6)},${r.lon.toFixed(6)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  return {
    type: 'FeatureCollection',
    features: [...groups].map(([key, group]) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [group[0].lon, group[0].lat] },
      properties: { key, count: group.length, name: group[0].name },
    })),
  };
}

export function checkMapSchema(textOrRows) {
  const raw = typeof textOrRows === 'string' ? recordsFromCsv(textOrRows) : null;
  const rows = raw ? raw.map(toFinderRow) : textOrRows;
  const header = raw ? Object.keys(raw[0] ?? {}) : FINDER_COLUMNS;
  const issues = [];
  const stats = {
    rows: rows.length,
    listed: 0,
    withCoords: 0,
    listedWithCoords: 0,
    pins: 0,
    missingColumns: FINDER_COLUMNS.filter((c) => !header.includes(c)),
  };

  rows.forEach((row, i) => {
    const where = `row ${i + 2} id=${row.id ?? ''}`;
    if (row.row_type && !ROW_TYPES.includes(row.row_type)) issues.push(`${where}: row_type "${row.row_type}" is not allowed`);
    if (row.borough && !BOROUGHS.includes(row.borough)) issues.push(`${where}: borough "${row.borough}" is not allowed`);
    if (row.spanish_speaking === undefined) issues.push(`${where}: spanish_speaking is not a boolean`);
    if (row.latitude === undefined || row.longitude === undefined) issues.push(`${where}: latitude/longitude are not numbers`);
    const point = pointCoordinates(row);
    if (point?.error) issues.push(`${where}: ${point.error}`);
    if (point && !point.error) stats.withCoords += 1;
    const listed = row.row_type !== 'cross_reference'
      && [row.organization_name, row.phone_number, row.website, row.street, row.description].some(Boolean);
    if (listed) {
      stats.listed += 1;
      if (point && !point.error) stats.listedWithCoords += 1;
    }
  });

  return { ok: stats.missingColumns.length === 0 && issues.length === 0, stats, issues };
}

export async function fetchKaviRows(path = KAVI_CSV_PATH) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`Could not load ${path} (${response.status})`);
  const text = await response.text();
  const rows = rowsFromCsv(text);
  return { rows, report: checkMapSchema(text), path };
}
