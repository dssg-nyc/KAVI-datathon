// Address lookup (NYC GeoSearch) and map geometry helpers.

const GEOSEARCH = 'https://geosearch.planninglabs.nyc/v2/autocomplete';

// GeoSearch has no ZIP layer, so a bare 5-digit ZIP becomes the average position of the in-person
// resources whose zip_code is that ZIP. Returns null when no resource has that ZIP.
export function zipPlace(resources, zip) {
  const pts = resources.filter((r) => r.inPerson && r.zip === zip);
  if (!pts.length) return null;
  const lat = pts.reduce((s, r) => s + r.lat, 0) / pts.length;
  const lon = pts.reduce((s, r) => s + r.lon, 0) / pts.length;
  return { label: `ZIP ${zip}`, lat, lon };
}

// Returns { places: [{ label, lat, lon }], failed } for typed text. `failed` is true when GeoSearch
// could not be reached; a ZIP match from zipPlace() is still returned in that case.
export async function searchPlaces(text, resources, { signal } = {}) {
  const trimmed = text.trim();
  const zip = /^\d{5}$/.test(trimmed) ? zipPlace(resources, trimmed) : null;
  try {
    const res = await fetch(`${GEOSEARCH}?text=${encodeURIComponent(trimmed)}`, { signal });
    if (!res.ok) throw new Error(`GeoSearch HTTP ${res.status}`);
    const body = await res.json();
    const places = (body.features ?? []).slice(0, 6).map((f) => ({
      label: String(f.properties?.label ?? '').replace(/, USA$/, ''),
      lon: f.geometry.coordinates[0],
      lat: f.geometry.coordinates[1],
    }));
    return { places: zip ? [zip, ...places.slice(0, 4)] : places, failed: false };
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    console.warn('Address search failed:', error);
    return { places: zip ? [zip] : [], failed: true };
  }
}

// A GeoJSON polygon approximating a circle of `mi` miles around `place`.
export function circle(place, mi) {
  const R = 3958.8;
  const deg = 180 / Math.PI;
  const pts = [];
  for (let i = 0; i <= 64; i++) {
    const a = (i / 64) * 2 * Math.PI;
    const dLat = (mi / R) * Math.cos(a) * deg;
    const dLon = ((mi / R) * Math.sin(a) * deg) / Math.cos(place.lat / deg);
    pts.push([place.lon + dLon, place.lat + dLat]);
  }
  return { type: 'Feature', geometry: { type: 'Polygon', coordinates: [pts] }, properties: {} };
}
