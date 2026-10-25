# NYPL Connections → GeoJSON: data analysis

Analysis of `data/nypl_connections_resources.geojson`, the output of
[`nypl_connections_to_geojson.ts`](../nypl_connections_to_geojson.ts) run against
`data/NYPL Connections Resources.csv` on 2026-10-25.

Every number below is reproducible by running
[`analyze_nypl_connections_location.py`](analyze_nypl_connections_location.py) (stdlib-only, no dependencies):

```sh
python3 scripts/analysis/analyze_nypl_connections_location.py
```

## 1. Entities in the source file

**760** resources (rows) are present in `NYPL Connections Resources.csv`, and all 760 carry
through to the output GeoJSON as features — the script never drops a row (see
[`nypl_connections.md`](../nypl_connections.md)).

## 2. Census Bureau geocoding match rate

Of the 760 resources, **469** had enough of an address (a street plus a city or zip) to be sent to
the Census Bureau's batch geocoder at all; the other 291 are hotlines or online-only resources with
no physical address.

| `geocode_match` | Count | % of all 760 | % of the 469 sent to the geocoder |
|---|---|---|---|
| `matched` | 424 | 55.8% | 90.4% |
| `unmatched` | 45 | 5.9% | 9.6% |
| `not_attempted` | 291 | 38.3% | — |

So **424 of 760 entities (55.8%)** ended up with real coordinates. The 45 `unmatched` rows had an
address but the geocoder couldn't place it — mostly PO boxes (e.g. `Box 188`) or addresses outside
what the Census TIGER road network resolves well, a known weak spot for the Census geocoder inside
NYC specifically.

## 3. Entities per state

| State | Count |
|---|---|
| NY | 445 |
| *(no state given)* | 289 |
| CA | 7 |
| DC | 5 |
| IL | 3 |
| MA | 3 |
| MO | 1 |
| FL | 1 |
| WA | 1 |
| CO | 1 |
| VA | 1 |
| MN | 1 |
| TX | 1 |
| WV | 1 |

The dataset is overwhelmingly NY-focused (445 of the 471 rows that give a state at all, 94.5%),
consistent with it being a NYC resource guide. The 289 rows with no state are the same address-less
hotline/online resources counted in section 2.

## 4. Entities per city

53 distinct city values appear (including the 289 blanks). Full breakdown, descending:

| City | Count |
|---|---|
| *(no city given)* | 289 |
| New York | 212 |
| Brooklyn | 87 |
| Bronx | 57 |
| Jamaica | 16 |
| Staten Island | 16 |
| Albany | 14 |
| Long Island City | 7 |
| Washington | 5 |
| Kew Gardens | 4 |
| Kingston | 2 |
| Champaign | 2 |
| Northampton | 2 |
| Ithaca | 2 |
| Ossining | 2 |
| Buffalo | 2 |
| Corona | 2 |
| Forest Hills | 2 |
| Woodside | 2 |
| San Francisco | 2 |
| Yaphank | 1 |
| Yonkers | 1 |
| Kansas City | 1 |
| Lake Worth | 1 |
| Seattle | 1 |
| Denver | 1 |
| Annandale-on-Hudson | 1 |
| Saranac Lake | 1 |
| Holtsville | 1 |
| Arlington | 1 |
| Jackson Heights | 1 |
| Los Angeles | 1 |
| St. Paul | 1 |
| Chicago | 1 |
| Briarwood | 1 |
| Massapequa Park | 1 |
| Huntington Station | 1 |
| Newburgh | 1 |
| Quincy | 1 |
| East Elmhurst | 1 |
| Delmar | 1 |
| Covina | 1 |
| Ridgewood | 1 |
| Rensselaer | 1 |
| Jamaica Estates | 1 |
| Sacramento | 1 |
| Oakland | 1 |
| Austin | 1 |
| West Hollywood | 1 |
| New Paltz | 1 |
| Astoria | 1 |
| Queens | 1 |
| Clarksburg | 1 |

33 of the 53 cities have exactly one resource — a long tail of one-off out-of-state orgs (national
hotlines, advocacy groups) alongside the NYC core.

## 5. Densest and sparsest areas (by coordinates)

Based on the 424 matched points' actual lat/lon, not the `City` text field.

**Densest.** Binning the matched points into a ~0.02°×0.02° grid (roughly 2km×1.7km at this
latitude) and ranking by point count per cell:

| Resources in cell | Approx. center (lat, lon) | Area |
|---|---|---|
| 35 | 40.720, -74.000 | Lower Manhattan (Chinatown / Civic Center) |
| 26 | 40.740, -74.000 | Greenwich Village / West Village |
| 21 | 40.820, -73.920 | The Bronx (Morrisania area) |
| 20 | 40.800, -73.940 | Manhattan (Upper West Side/Morningside) |
| 20 | 40.680, -73.980 | Brooklyn (Downtown/Fort Greene) |
| 19 | 40.760, -73.980 | Manhattan (Midtown) |

**Lower Manhattan is the single densest cluster** — 35 resources packed into about 2 square
kilometers, roughly 8x the median cell's density. Overall, 100 grid cells contain at least one
matched resource, and the top 6 cells above alone account for ~34% of all matched resources — the
dataset is heavily clustered around Manhattan, the Bronx, and Brooklyn.

**Sparsest.** 49 of the 100 occupied grid cells contain exactly one isolated resource. Ranking
every matched point by its distance to its *nearest* other matched resource (haversine distance)
surfaces the most geographically isolated entries:

| Distance to nearest other resource | Organization | Location |
|---|---|---|
| 1,128.7 km | AMERICAN INDIAN COLLEGE FUND | Denver, CO |
| 1,014.1 km | PRISON SCHOLAR FUND | Seattle, WA |
| 669.4 km | 1IN6 | St. Paul, MN |
| 200.7 km | PRISONERS' LEGAL SERVICES OF NEW YORK (PLSNY) | Ithaca, NY |
| 181.5 km | NORTH COUNTY COMMUNITY COLLEGE (NCCC) | Saranac Lake, NY |
| 133.7 km | PRISON BOOK PROGRAM | Quincy, MA |
| 118.4 km | National Center for LGBTQ Rights (NCLR) | Sacramento, CA |
| 95.2 km | STOP IT NOW! | Northampton, MA |

The **sparsest points are the handful of national/out-of-state organizations** (Denver, Seattle,
St. Paul, Sacramento) that sit 600–1,100km from any other resource in the dataset. Even restricted
to New York State, the sparsest entries are upstate orgs in Ithaca and Saranac Lake, 180–200km from
the next-nearest resource — a sharp contrast to the median matched resource, which has another
resource just **~155 meters** away.

## Takeaways

- The dataset is a NYC resource guide with a long out-of-state tail: 94.5% of addressed rows are in
  NY, but a few dozen national hotlines/orgs are scattered coast to coast.
- Geocoding recovers coordinates for 90% of rows that had an address at all, but only addresses 56%
  of the full dataset — the other 44% are either hotline-only entries or failed to match.
- Geographically, resources are extremely concentrated in a handful of NYC neighborhoods (Lower
  Manhattan above all), while the sparsest entries are isolated national organizations far outside
  the city.
