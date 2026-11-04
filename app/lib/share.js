// Shareable resource pages: one URL per resource, keyed by the stable id from data/resource_ids.csv.
// The finder links every card to resource.html?id=<id>, and app/pages/resource.js reads the id back.
// No UI here, so it can be tested in Node.

export const RESOURCE_PAGE = 'resource.html';

// The link to one resource's page, relative to the page root: "resource.html?id=176-2".
export function resourcePath(id) {
  return `${RESOURCE_PAGE}?id=${encodeURIComponent(String(id))}`;
}

// The id in a page URL's query string, or '' when there is none. Blank and whitespace count as none.
export function idFromSearch(search) {
  return (new URLSearchParams(search).get('id') ?? '').trim();
}

// The row with that id. Ids are strings in resources.public.json ("176", "176-2", "feature-695") and
// numbers in a Supabase or CSV export, so both sides are compared as strings.
export function findRow(rows, id) {
  const wanted = String(id);
  return rows.find((row) => String(row.id) === wanted) ?? null;
}

// The browser tab title of a resource page.
export function pageTitle(resource) {
  return resource ? `${resource.name} — EMPOWER` : 'Resource not found — EMPOWER';
}
