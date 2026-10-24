# OpenStreetMap resources layer

A supplementary layer for the resource map: service locations in NYC that volunteers have mapped in
[OpenStreetMap](https://www.openstreetmap.org) (OSM). It complements the published ArcGIS layers
(NYPL Connections, public libraries, health facilities, cooling centers), so libraries and general
clinics and hospitals are left out on purpose.

```sh
npm run osm      # node scripts/osm/osm_resources_nyc.ts; writes data/nyc_osm_resources.{csv,geojson}
python3 -m http.server 8000 --bind 127.0.0.1   # from the repo root; then open http://localhost:8000/scripts/osm/map.html
```

The script needs Node 22.18 or later and has no dependencies. It runs one query against the free public
[Overpass API](https://overpass-api.de) and retries with backoff when the server is busy. The map (`scripts/osm/map.html`) is a
single HTML file (MapLibre GL + OpenFreeMap tiles). It has to be served over HTTP, not opened as
a file, because it fetches the GeoJSON.

## What OSM offers

The query covers every named feature with one of these tags inside each of the five boroughs. Each row gets
one of the PRD's service categories (first match wins) and its borough. Counts are from a run on 2026-10-24.

| Category | OSM tags | Count | Notes |
|---|---|---|---|
| Childcare | `amenity=childcare`, `amenity=kindergarten` | 442 | Daycares and pre-K. Best-covered category. |
| Community centres | `amenity=community_centre` (incl. youth/cultural centres), `amenity=social_centre` | 175 | Local places to hand off to. |
| Mental health | `healthcare=counselling`, `healthcare=psychotherapist` | 76 | `healthcare:counselling=*` sometimes says addiction, family, etc. |
| Housing | `social_facility=shelter`, `group_home`, `transitional_housing` | 48 | `social_facility:for=homeless` / `migrant` marks shelters. Group homes are mostly for seniors. |
| Food | `social_facility=food_bank`, `soup_kitchen`, `amenity=food_bank` | 29 | Far below the real number of NYC pantries. |
| Employment | `office=employment_agency` | 26 | Staffing agencies and job-support programmes are mixed together. |
| Other social services | the rest of `amenity=social_facility` | 308 | Outreach (54) is the useful part. Nursing homes, assisted living and senior day care are mostly noise for CVI referrals. |

Total: 1,104 places.

### Fields

`category, subtype, borough, name, lat, lon, address, phone, website, opening_hours, operator, osm_url`

`subtype` is the raw OSM tag, e.g. `social_facility:shelter (for homeless)`. About half the rows have
a phone number or website, and about 10% have opening hours.

## Limits

- **No eligibility or referral information.** OSM records what a place is and where it is. It doesn't
  record who a place serves or how to get referred. Use this as a "what's nearby" layer next to the Connections
  Guide, not as resource cards.
- **Uneven coverage.** Results depend on where volunteers have mapped. The Bronx has very few
  rows in every category, which shows a gap in the mapping, not a lack of services. Don't use this
  layer for service-gap analysis.
- **No reentry category.** OSM has no tag that is used for reentry support.
- **Better sources exist for some categories.** NYC Open Data has fuller lists for childcare (DOHMH
  licensed child care centers) and food (city food pantry and community food program locations).
  They are worth using in place of OSM for those two categories.
- **Licence.** OSM data is under [ODbL](https://opendatacommons.org/licenses/odbl/): credit
  "© OpenStreetMap contributors" wherever the data is shown. Fixes made on openstreetmap.org
  (every row links to its OSM page) show up the next time the script runs.
