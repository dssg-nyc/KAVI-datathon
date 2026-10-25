// Pure filtering over the records built by toResource() in resources.js. No DOM access, so it runs under node --test.

export const RADII = [0.5, 1, 2, 5, 0]; // miles; 0 means any distance

// how: 'all' | 'in_person' | 'remote'. place: { label, lat, lon } or null.
export const newFilters = () => ({
  services: new Set(),
  audiences: new Set(),
  spanish: false,
  place: null,
  radius: 2,
  boroughs: new Set(),
  how: 'all',
  text: '',
});

export function miles(a, b) {
  const R = 3958.8;
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

const matchesText = (r, text) => text.toLowerCase().split(/\s+/).filter(Boolean).every((word) => r.searchText.includes(word));

// Values inside services or audiences are OR'd; the filters are AND'd. `skip` names one filter to ignore,
// which is how a tile's count shows what picking it would give. Phone/online resources ignore the
// borough and distance filters, because they serve all of NYC.
export function passes(r, f, skip = null) {
  if (skip !== 'services' && f.services.size && !r.services.some((s) => f.services.has(s))) return false;
  if (skip !== 'audiences' && f.audiences.size && !r.audiences.some((a) => f.audiences.has(a))) return false;
  if (skip !== 'spanish' && f.spanish && !r.spanish) return false;
  if (skip !== 'how' && f.how === 'in_person' && !r.inPerson) return false;
  if (skip !== 'how' && f.how === 'remote' && r.inPerson) return false;
  if (f.text && !matchesText(r, f.text)) return false;
  if (r.inPerson) {
    if (skip !== 'boroughs' && f.boroughs.size && !f.boroughs.has(r.borough)) return false;
    if (skip !== 'place' && f.place && f.radius && miles(f.place, r) > f.radius) return false;
  }
  return true;
}

// Matching resources with `distance` (miles from f.place, or null), nearest first, then by name.
export function matchingResources(resources, f) {
  const out = resources.filter((r) => passes(r, f)).map((r) => ({ ...r, distance: f.place && r.inPerson ? miles(f.place, r) : null }));
  out.sort((a, b) => (a.distance ?? Infinity) - (b.distance ?? Infinity)
    || b.hasName - a.hasName
    || a.name.localeCompare(b.name));
  return out;
}

// Count of resources per value of one filter, with that filter itself ignored.
// facet: 'services' | 'audiences' | 'spanish' | 'boroughs' | 'how'. Returns a Map of value -> count.
export function countBy(resources, f, facet) {
  const counts = new Map();
  const add = (k) => counts.set(k, (counts.get(k) ?? 0) + 1);
  for (const r of resources) {
    if (!passes(r, f, facet)) continue;
    if (facet === 'services') r.services.forEach(add);
    else if (facet === 'audiences') r.audiences.forEach(add);
    else if (facet === 'spanish') { if (r.spanish) add(true); }
    else if (facet === 'boroughs') { if (r.inPerson && r.borough) add(r.borough); }
    else if (facet === 'how') add(r.inPerson ? 'in_person' : 'remote');
  }
  return counts;
}
