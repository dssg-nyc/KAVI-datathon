// Local preview: open the finder with ?preview=local to see local data changes before they are imported.
// The rows still come from Supabase (read-only), then these local files overwrite some of their columns,
// matched by resource_id:
//   data/cleaned/resources_extended.csv  service_types_all
//   data/cleaned/resource_audiences.csv  audiences_all, restricted_audiences, focus_audiences
// Nothing is written anywhere, and other people see the live data. Needs the repo served as static files
// (npm run dev, or python3 -m http.server 5173 --bind 127.0.0.1).

const FILES = [
  { path: 'data/cleaned/resources_extended.csv', columns: ['service_types_all'] },
  { path: 'data/cleaned/resource_audiences.csv', columns: ['audiences_all', 'restricted_audiences', 'focus_audiences'] },
];

export const isLocalPreview = () => new URLSearchParams(location.search).get('preview') === 'local';

// RFC 4180: quoted fields may contain commas, newlines and "" escapes.
function parseCsv(text) {
  const rows = [];
  let row = [], field = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\n') { row.push(field.replace(/\r$/, '')); rows.push(row); row = []; field = ''; }
    else field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  const [header, ...body] = rows;
  return body.filter((r) => r.length > 1).map((r) => Object.fromEntries(header.map((h, j) => [h, r[j] ?? ''])));
}

const toList = (cell) => {
  const items = cell.split(';').map((s) => s.trim()).filter(Boolean);
  return items.length ? items : null;
};

// Returns the rows with the local columns applied, and a short summary for the page.
export async function applyLocalPreview(rows) {
  const notes = [];
  for (const { path, columns } of FILES) {
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Local preview: could not load ${path} (${response.status})`);
    const byId = new Map(parseCsv(await response.text()).map((r) => [Number(r.resource_id), r]));
    let applied = 0;
    for (const row of rows) {
      const local = byId.get(row.resource_id);
      if (!local) continue;
      for (const column of columns) row[column] = toList(local[column]);
      applied += 1;
    }
    notes.push(`${path.split('/').pop()}: ${applied} rows`);
  }
  return { rows, summary: `Local preview · ${notes.join(' · ')}` };
}
