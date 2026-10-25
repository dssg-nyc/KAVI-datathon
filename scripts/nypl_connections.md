# GeoJSON creation

How `data/nypl_connections_resources.geojson` is built from
`data/NYPL Connections Resources.csv`.

```sh
node scripts/nypl_connections_to_geojson.ts              # writes data/nypl_connections_resources.geojson
node --test scripts/tests/nypl_connections_to_geojson.test.ts   # runs the tests (no network calls)
```

`data/NYPL Connections Resources.csv` is the raw Connections Guide export: one row per
resource, with location split across `Street Number`, `Address Line 2`, `Street`, `City`, `State`,
`Zip Code`, and no coordinates. This script (issue
[#4](https://github.com/dssg-nyc/KAVI-datathon/issues/4)) turns those columns into the location
format OSM itself uses, so the output can sit next to `nyc_osm_resources.geojson` or be loaded into
OSM-based tooling.

- **Address tags.** OSM addresses are a flat set of `addr:*` tags (see the
  [OSM wiki](https://wiki.openstreetmap.org/wiki/Key:addr)), not a single string. The script maps
  `Street Number → addr:housenumber`, `Street → addr:street`, `City → addr:city`,
  `State → addr:state`, `Zip Code → addr:postcode`, and sets `addr:country = US` whenever any of
  those are present. Every original CSV column is kept as-is on the feature's properties alongside
  the new tags — nothing is renamed or dropped.
- **Two known zip typos are fixed in code, not in the CSV.** `cleanZip()` corrects two rows'
  `Zip Code` (confirmed against the published ArcGIS `NYPL_Connections_merge` layer during
  review) before geocoding — the delivered CSV stays byte-for-byte as received.
- **Coordinates try NYC GeoSearch first, then fall back to the Census Bureau.**
  [NYC GeoSearch](https://geosearch.planninglabs.nyc) (no API key) is building-level accurate for
  NYC addresses, but it has no real concept of "outside NYC": for an address it can't place, it
  silently returns the nearest same-named NYC street instead of nothing (e.g. querying it with a
  Kingston, NY address returns a Brooklyn street of the same name). The only reliable signal that
  a GeoSearch result is real is that the zip code it returns matches the zip we asked for —
  `pickGeoSearchMatch()` enforces that. Inside NYC the same fallback returns a different building
  on the right street and zip (e.g. `581 Rogers Avenue` came back as 1038 Rogers Avenue, 1.4 km
  away), so `houseNumbersMatch()` also requires the returned house number to match, allowing for
  letter suffixes (`76-A`) and ranges (`400-430`, `3807–3809`). Whatever GeoSearch can't confidently place — including
  every address genuinely outside NYC — falls through to the
  [Census Bureau's free batch geocoder](https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html)
  (one request for the whole remainder, benchmark `Public_AR_Current`), same as before. GeoSearch
  has no batch endpoint, so it's called once per address, concurrency-limited to 5 at a time.
  Only rows with a street plus a city or zip are sent to either geocoder; the rest are hotlines or
  resources with no physical address. On the 2026-10-25 run: 760 total, 435 matched (386 via
  GeoSearch, 49 via Census, 3 of them flagged for review), 34 unmatched, 291 not attempted.
- **`geocode_source` and `geocode_matched_address`.** `geocode_source` is `'geosearch'` or
  `'census'` on matched features, and `geocode_matched_address` is the address that geocoder
  actually placed (GeoSearch's label or Census's matched address), so coordinate provenance is
  auditable. Both are empty strings on unmatched/not-attempted features.
- **`geocode_review`.** Non-empty when a point is kept but not confirmed at building level.
  Two cases: neither geocoder matched the house number, so the feature keeps GeoSearch's
  same-street point (16-16 Hazen St, 126-01 Queens Blvd); or the address was checked by hand
  during PR review and couldn't be confirmed (`REVIEW_NOTES`: 45 Suffolk St, which isn't in
  PLUTO). These rows need someone to confirm the location before they're relied on.
- **Nothing is dropped.** Every row from the CSV becomes a feature. `geocode_match` on each
  feature's properties is `matched`, `unmatched` (had an address, neither geocoder could place
  it — e.g. a PO box), or `not_attempted` (no usable address). Unmatched/not-attempted features
  get `geometry: null` instead of being removed, since hotlines and address-less resources still
  belong in the directory.
- **Not wired into map.html.** This is the data-transformation step only; no category mapping to
  the OSM layer's taxonomy and no map UI changes.
