// Named OSM service locations in New York City, one row per feature with its borough and
// PRD service category. A supplementary layer next to the ArcGIS ones (Connections, libraries,
// health facilities, cooling centers), so it leaves out libraries and general clinics/hospitals.
//
// Each borough is an admin_level=7 boundary inside the City of New York (relation 175905); the
// query prints the borough's area before its members, so the borough of a row is the last area seen.
//
// Writes data/nyc_osm_resources.{csv,geojson} (same rows); scripts/osm/map.html reads the GeoJSON.
//
//   node scripts/osm/osm_resources_nyc.ts [out.csv]      (Node >= 22.18, no dependencies)

import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

const ENDPOINT = 'https://overpass-api.de/api/interpreter'
const NYC_AREA_ID = 3600000000 + 175905
const TIMEOUT_S = 300

type Tags = Record<string, string>

// [category, Overpass filter, predicate on tags]. The first match wins, so specific rows go first.
const CATEGORIES: [string, string, (t: Tags) => boolean][] = [
  ['food', '["amenity"="social_facility"]["social_facility"~"^(food_bank|soup_kitchen)$"]', (t) => /^(food_bank|soup_kitchen)$/.test(t.social_facility ?? '')],
  ['food', '["amenity"="food_bank"]', (t) => t.amenity === 'food_bank'],
  ['housing', '["amenity"="social_facility"]["social_facility"~"^(shelter|group_home|transitional_housing)$"]', (t) => /^(shelter|group_home|transitional_housing)$/.test(t.social_facility ?? '')],
  ['mental_health', '["healthcare"~"^(counselling|psychotherapist)$"]', (t) => /^(counselling|psychotherapist)$/.test(t.healthcare ?? '')],
  ['social_services', '["amenity"="social_facility"]', (t) => t.amenity === 'social_facility'],
  ['childcare', '["amenity"~"^(childcare|kindergarten)$"]', (t) => /^(childcare|kindergarten)$/.test(t.amenity ?? '')],
  ['employment', '["office"="employment_agency"]', (t) => t.office === 'employment_agency'],
  ['community_centre', '["amenity"~"^(community_centre|social_centre)$"]', (t) => /^(community_centre|social_centre)$/.test(t.amenity ?? '')],
]

const QUERY = `[out:json][timeout:${TIMEOUT_S}];
area(id:${NYC_AREA_ID})->.nyc;
rel(area.nyc)["boundary"="administrative"]["admin_level"="7"];
map_to_area;
foreach->.b(
  .b out tags;
  (
${[...new Set(CATEGORIES.map(([, f]) => f))].map((f) => `    nwr${f}["name"](area.b);`).join('\n')}
  );
  out center tags;
);`

const COLUMNS = ['category', 'subtype', 'borough', 'name', 'lat', 'lon', 'address', 'phone', 'website', 'opening_hours', 'operator', 'osm_url']

function csvCell(v: string | number | null | undefined): string {
  const s = v == null ? '' : String(v)
  return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s
}

function address(t: Tags): string {
  const street = [t['addr:housenumber'], t['addr:street']].filter(Boolean).join(' ')
  return [street, t['addr:city'], t['addr:postcode']].filter(Boolean).join(', ')
}

function subtype(t: Tags): string {
  const detail = t.social_facility ?? t['healthcare:counselling'] ?? t.community_centre ?? ''
  const forWhom = t['social_facility:for'] ? ` (for ${t['social_facility:for']})` : ''
  return `${t.amenity ?? t.healthcare ?? t.office ?? ''}${detail ? `:${detail}` : ''}${forWhom}`
}

interface Element {
  type: string
  id: number
  lat?: number
  lon?: number
  center?: { lat: number; lon: number }
  tags?: Tags
}

async function main(): Promise<void> {
  const out = process.argv[2] ?? join(import.meta.dirname, '..', '..', 'data', 'nyc_osm_resources.csv')
  // The public server answers 429/502/504 when busy; back off and retry.
  let resp: Response | undefined
  for (let attempt = 0, waitS = 15; attempt < 5; attempt++, waitS *= 2) {
    resp = await fetch(ENDPOINT, {
      method: 'POST',
      body: new URLSearchParams({ data: QUERY }),
      headers: { 'User-Agent': 'KAVI-datathon resource map (github.com/dssg-nyc/KAVI-datathon)' },
    })
    if (![429, 502, 503, 504].includes(resp.status)) break
    await resp.body?.cancel()
    console.error(`Overpass busy (HTTP ${resp.status}), retrying in ${waitS}s`)
    await new Promise((r) => setTimeout(r, waitS * 1000))
  }
  if (resp!.status !== 200) throw new Error(`Overpass HTTP ${resp!.status}: ${(await resp!.text()).slice(0, 500)}`)
  const payload = (await resp!.json()) as { remark?: string; elements?: Element[] }
  if (payload.remark?.toLowerCase().includes('error')) throw new Error(`Overpass aborted the query: ${payload.remark}`)

  const rows: string[][] = []
  const features: object[] = []
  const seen = new Set<string>()
  const counts = new Map<string, number>()
  let borough = ''
  for (const el of payload.elements ?? []) {
    const t = el.tags ?? {}
    if (el.type === 'area') {
      borough = t.name ?? ''
      continue
    }
    const lat = el.lat ?? el.center?.lat
    const lon = el.lon ?? el.center?.lon
    const ref = `${el.type}/${el.id}`
    const category = CATEGORIES.find(([, , match]) => match(t))?.[0]
    if (lat == null || lon == null || !category || seen.has(ref)) continue
    seen.add(ref)
    counts.set(`${category}\t${borough}`, (counts.get(`${category}\t${borough}`) ?? 0) + 1)
    const values = [
      category, subtype(t), borough, t.name, lat, lon, address(t),
      t.phone ?? t['contact:phone'], t.website ?? t['contact:website'], t.opening_hours, t.operator,
      `https://www.openstreetmap.org/${ref}`,
    ]
    rows.push(values.map(csvCell))
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [lon, lat] },
      properties: Object.fromEntries(COLUMNS.map((c, i) => [c, values[i] ?? ''])),
    })
  }

  const geojson = out.replace(/\.csv$/, '') + '.geojson'
  mkdirSync(dirname(out), { recursive: true })
  writeFileSync(out, [COLUMNS.join(','), ...rows.map((r) => r.join(','))].join('\n') + '\n')
  writeFileSync(geojson, JSON.stringify({ type: 'FeatureCollection', features }))
  for (const [key, n] of [...counts].sort()) console.log(`${key.replace('\t', '  ')}  ${n}`)
  console.log(`${rows.length} resources -> ${out}, ${geojson}`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
