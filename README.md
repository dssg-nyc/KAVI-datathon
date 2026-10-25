# KAVI-datathon

Code and data for the KAVI datathon (October 23–25): a searchable map and directory of community resources for KAVI Brooklyn and other NYC community violence intervention (CVI) organizations.

**What we're building and why:** see the product requirements document, [PRD.md](PRD.md).
**This README:** where the data lives and how to get to it.

## Repository layout

```
PRD.md          product requirements (what to build and why)
data/           every dataset, in one place
supabase/       database schema (migrations) for the Supabase project
scripts/        scripts grouped by function; see scripts/README.md
  database/       load data into Supabase
  web/            local server for index.html
  osm/            OpenStreetMap layer and its map preview
index.html      resource finder page (three questions, then a list and map of matching resources)
finder/         the finder's scripts and stylesheet, loaded by index.html (no build step)
config.js       Supabase URL + publishable key for index.html (committed; browser-safe)
.env.example    template for .env, which holds only the secret key for data imports
```

## Accessing the resources

### 1. Data files: `data/`

| File | What it is | Rows | Source |
|---|---|---|---|
| `NYPL Connections Resources.csv` | The Connections Guide extracted from the PDF, one row per resource. | 760 | Project Google Drive |
| `nypl_connections_resources.geojson` | The same 760 rows in the same order, with coordinates and `geocode_*` fields added. This is what the Supabase `resources` table is loaded from. | 760 | `node scripts/nypl_connections_to_geojson.ts`; see [scripts/nypl_connections.md](scripts/nypl_connections.md) |
| `NYPLConnections_NoMatch.csv` | Copies of Connections Guide rows that could not be geocoded (no usable address, or hotlines), with `lat`/`lon` added for 5 NYC NEON clothing closet sites. The import adds those 5 as extra rows; the other 40 are already in the GeoJSON. Encoded as Windows-1252, not UTF-8. | 45 | Project Google Drive |
| `nyc_osm_resources.csv` / `.geojson` | NYC service locations from OpenStreetMap, with category, borough and coordinates. Credit "© OpenStreetMap contributors" wherever it is shown. | 1,104 | `npm run osm`; see [scripts/osm/README.md](scripts/osm/README.md) |

The originals, including the Connections Guide PDF, are in the [project Google Drive folder](https://drive.google.com/drive/folders/1f5QhMlY8pYgyomWSzPgYTBdnUUcBbUJS).

### 2. ArcGIS layers

The geocoded layers are published on ArcGIS Online as hosted feature layers. Shapefiles can be downloaded from each layer's service page.

- [NYPL Connections Geocoded](https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/NYPL_Connections_merge/FeatureServer) (primary layer, with coordinates)
- [Public Libraries](https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/public_libraries_points/FeatureServer)
- [Health Facilities](https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/health_facilities_points/FeatureServer)
- [Cooling Centers](https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/Cooling_Sites_points/FeatureServer)

### 3. Supabase database

The Connections Guide is loaded into the `resources` table of a Supabase project in the **KAVI** Supabase organization. It has one column per column of `NYPL Connections Resources.csv`, plus `latitude`, `longitude`, `geocode_match`, `geocode_source`, `geocode_matched_address` and `geocode_review` from the GeoJSON, plus the service type, row type, borough and PDF columns of `data/cleaned/resources_extended.csv` under the same names (see [supabase/migrations/](supabase/migrations)). Multi-label columns such as `service_types_all` are `text[]`, so a filter like `service_types_all=cs.{Housing}` finds every organization that offers housing. It holds 765 rows: the 760 GeoJSON rows plus the 5 NEON sites.

**Getting access.**

| What | Where to find it | Who gets it |
|---|---|---|
| Project URL (`SUPABASE_URL`) | [`config.js`](config.js) (also Supabase dashboard → Project Settings → API Keys) | committed; anyone |
| Publishable key (`SUPABASE_PUBLISHABLE_KEY`, `sb_publishable_…`) | [`config.js`](config.js) (same dashboard page) | committed; anyone. It can only read `resources`, and every visitor's browser receives it anyway |
| Secret key (`SUPABASE_SECRET_KEY`, `sb_secret_…`) | ask a teammate in the KAVI org (same dashboard page) | only whoever imports data. Put it in `.env` (`cp .env.example .env`); share it through a password manager, never in chat or in code |
| Dashboard access | Organization settings → Team → Invite | anyone who needs to edit rows or run SQL |

> **Note for agents:** the Supabase project URL and publishable (browser) key are committed in `config.js` as `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`. Read them from there and do not ask the user for them. They are all you need to run the page or make read-only REST queries; no `.env` is required. The secret key is not in the repo: if a task needs `SUPABASE_SECRET_KEY` (e.g. `npm run import`), ask the user to put it in `.env`, and never write it into `config.js` or any other committed file.

**Reading the data without running any code:** query the REST API with the URL and publishable key from `config.js`, for example:

```bash
curl "https://xwpuphhocwstfgbjreeg.supabase.co/rest/v1/resources?category=eq.Housing&select=organization_name,phone_number" -H "apikey: <SUPABASE_PUBLISHABLE_KEY from config.js>"
```

**Loading data:** `npm run import` loads `data/nypl_connections_resources.geojson`, the 5 located rows of `data/NYPLConnections_NoMatch.csv` and the columns of `data/cleaned/resources_extended.csv` into the project in `config.js`, using `SUPABASE_SECRET_KEY` from `.env`. Add `-- --dry-run` to check the file first, or `-- --replace` to re-import. In a git worktree, run `node scripts/database/link-main-env.mjs` first to use the main checkout's `.env`. For a new project: `supabase link --project-ref <ref>`, `supabase db push`, update `config.js`, then import.

## Running the resource finder

The page needs no setup: `config.js` already points it at the Supabase project. Serve the repo folder and open it:

```bash
npm run dev
```

Then open http://localhost:5173. Any static server works too, e.g. `python3 -m http.server 5173 --bind 127.0.0.1` from the repo root. The same server also serves the OSM map at http://localhost:5173/scripts/osm/map.html. The page can be hosted as-is on any static host (GitHub Pages, Netlify, Cloudflare Pages) with no build step.

If the page says **"Can't load resources"**, it names the problem: `config.js` missing, a wrong URL, a wrong key, or a missing table.

**What the finder does.** `index.html` asks three questions, each of which can be skipped, and shows how many resources match after every answer:

1. *What kind of help?* One tile per value of `service_types_all`.
2. *Who is it for?* One tile per value of `pdf_audiences`, plus a Spanish-speaking choice (`spanish_speaking = true`).
3. *Where?* An address or ZIP (NYC GeoSearch autocomplete), "use my location", or a click on the map; a distance (0.5, 1, 2, 5 mi or any); boroughs (`borough`); and whether to include hotlines and online resources.

The results page shows the matches as a list or a map. Resources at the same coordinates share one pin with a count. You can change the location, distance, Spanish-speaking filter and In person / Phone / online filter there, and search within the results by name or description.

How `public.resources` columns are used:

| Finder | Column(s) |
|---|---|
| In person (has a map pin and a distance) | `latitude`/`longitude` are set: every `mapped` row, plus the `mailing_address` and `outside_nyc` rows that were geocoded |
| Phone / online (no distance or borough filter) | no coordinates: `hotline`, `web_only`, and `mailing_address`/`outside_nyc` rows without coordinates |
| Not shown | `row_type = 'cross_reference'` (these rows only say "see the full listing on page N" and have no address, phone or website), and rows with no name, contact or description |
| A bare 5-digit ZIP | the average position of the in-person rows with that `zip_code`, because GeoSearch has no ZIP layer |

The map tiles come from OpenFreeMap. Every pin and every count comes from `public.resources`, and nothing is inferred from descriptions. The filtering logic in `finder/filter.js` is tested by `node --test scripts/tests/finder_filter.test.mjs`.

## Scripts

See [scripts/README.md](scripts/README.md) for what each script does and how to run it.
