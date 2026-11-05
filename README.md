# KAVI-datathon

Code and data for the KAVI datathon (October 23–25): a searchable map and directory of community resources for KAVI Brooklyn and other NYC community violence intervention (CVI) organizations.

**What we're building and why:** see the product requirements document, [PRD.md](PRD.md).
**This README:** where the data lives and how to get to it.

## Repository layout

```
PRD.md          product requirements (what to build and why)
vercel.json     maps the public URLs (/, /finder.html, /resource.html) to the pages in app/
.vercelignore   keeps everything the site does not load off the public site
app/            the website; see app/README.md
  pages/          landing page and finder pages
  components/     map, result cards, place input and finder styles
  lib/            filtering, data loading and geocoding, with tests in __tests__/
  brand/          DSSG design-system CSS and cobrand logos
  prototypes/     reach prototype (throwaway)
pipeline/       the data pipeline, one folder per stage; see pipeline/README.md
  cleaning/       clean the Connections Guide
  pdf/            extend it from the printed guide PDF
  geocode/        add coordinates
  audiences/      tag who each resource serves
  load/           load the result into Supabase
notebooks/      exploratory work the site does not use: the cleaning and audience notebooks,
                the location analysis, and the OpenStreetMap layer
data/           every dataset, in one place
  reference/      lookup tables the pipeline reads
  review/         human review decisions the pipeline reads back
  cleaned/, extracted/   pipeline output
supabase/       database schema (migrations) for the Supabase project
docs/           technical requirements and notes
.env.example    template for .env, which holds only the secret key for data imports
```

## Data pipeline

Raw Connections Guide export → cleaned, enriched CSV → Supabase → finder. Each step only adds columns; none of them edit a column an earlier step set. `npm run pipeline` runs steps 1 and 2, the geocoder and the audience tagging in order (`-- --list` shows the stages); loading is a separate command.

1. **Clean** — [`pipeline/1_clean/clean_guide.py`](docs/cleaning.md): `data/NYPL Connections Resources.csv` → `data/cleaned/resources_clean.csv`. Normalizes names, addresses, ZIPs and websites; derives `borough` and `row_type`; and makes a first, conservative pass at `service_type` (the guide's `Category`/`Subcategory` mapped to a standard type, then an unambiguous description keyword as a fallback). Ambiguous or unsupported rows are left blank rather than guessed.
2. **Extend with the PDF** — [`pipeline/2_pdf/extract_pdf.py`](docs/pdf_extension.md) → `match_pdf.py` → `extend_with_pdf.py`: matches each row to its listing in the printed guide PDF, fills still-blank `service_type`s from the PDF section it's printed under, and runs a multi-label keyword search (`SERVICE_PATTERNS`) over every row's description — including rows that already have a type — to catch the secondary services a resource's description mentions beyond its primary one (e.g. a reentry org whose description also offers housing and legal help). Everything is combined into `service_types_all`, the column the finder actually filters on. Writes `data/cleaned/resources_extended.csv`.
3. **Human review** — [`data/review/`](data/review/README.md): a person's proposed fixes (new service types, corrections to keyword- or PDF-based guesses) live here as CSVs. Step 2 (`extend_with_pdf.py`) reads both CSVs back in, so rerun it after editing them. The secondary tags step 2 adds to rows that already have a primary type are not reviewed yet (`description_service_types_source == "description_keywords"`).
4. **Load into Supabase** — [`pipeline/5_load/load_supabase.mjs`](pipeline/README.md): joins the geocoded GeoJSON, the NoMatch extras, and `resources_extended.csv` into `public.resources`. `"; "`-joined CSV columns such as `service_types_all` and `pdf_audiences` become Postgres `text[]`.
5. **Finder** — `app/lib/resources.js`, `finder.html`: reads `data/public/resources.public.json` (written by `npm run build:data`, see [pipeline/README.md](pipeline/README.md)) when `RESOURCES_FILE` is set in `app/config.js` (map pins use that file's `latitude`/`longitude`); otherwise reads `public.resources` from Supabase. `service_types_all` drives the "What kind of help?" filter and the map pin color.

## Accessing the resources

### 1. Data files: `data/`

| File | What it is | Rows | Source |
|---|---|---|---|
| `NYPL Connections Resources.csv` | The Connections Guide extracted from the PDF, one row per resource. | 760 | Project Google Drive |
| `nypl_connections_resources.geojson` | The same 760 rows in the same order, with coordinates and `geocode_*` fields added. This is what the Supabase `resources` table is loaded from. | 760 | `node pipeline/3_geocode/geocode.ts`; see [docs/geocoding.md](docs/geocoding.md) |
| `NYPLConnections_NoMatch.csv` | Copies of Connections Guide rows that could not be geocoded (no usable address, or hotlines), with `lat`/`lon` added for 5 NYC NEON clothing closet sites. The import adds those 5 as extra rows; the other 40 are already in the GeoJSON. Encoded as Windows-1252, not UTF-8. | 45 | Project Google Drive |
| `nyc_osm_resources.csv` / `.geojson` | NYC service locations from OpenStreetMap, with category, borough and coordinates. Credit "© OpenStreetMap contributors" wherever it is shown. | 1,104 | `npm run osm`; see [notebooks/osm/README.md](notebooks/osm/README.md) |
| `public/resources.public.json` | The file the finder reads: the columns it shows and filters on, keyed by a stable id. `public/resources.provenance.json` holds the other columns, joined by id. | 765 | `npm run build:data` |
| `public/layers/*.geojson` | The reference layers the finder's map can show: libraries (221), health facilities (2,744) and NYC Parks cooling sites (269), copied from ArcGIS Online and trimmed to name, address and kind. `index.json` lists them. | 3,234 | `npm run layers` |
| `kavi_resources.csv` | Full `public.resources` export (guide columns, geocode, service types, audiences). The finder read it before the public file existed; kept for comparison. | 765 | Supabase export, 2026-10-25 |

The originals, including the Connections Guide PDF, are in the [project Google Drive folder](https://drive.google.com/drive/folders/1f5QhMlY8pYgyomWSzPgYTBdnUUcBbUJS).

### 2. ArcGIS layers

The geocoded layers are published on ArcGIS Online as hosted feature layers. Shapefiles can be downloaded from each layer's service page.

- [NYPL Connections Geocoded](https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/NYPL_Connections_merge/FeatureServer) (primary layer, with coordinates)
- [Public Libraries](https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/public_libraries_points/FeatureServer)
- [Health Facilities](https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/health_facilities_points/FeatureServer)
- [Cooling Sites](https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services/Cooling_Sites_points/FeatureServer) (NYC Parks outdoor cooling sites, not indoor cooling centers)

The last three are also copied into the repo as `data/public/layers/*.geojson` by `npm run layers`, trimmed to a name, address and kind per point, and the finder's map can switch each on as a reference layer. Rerun the script when a layer changes on ArcGIS Online.

### 3. Supabase database

The Connections Guide is loaded into the `resources` table of a Supabase project in the **KAVI** Supabase organization. It has one column per column of `NYPL Connections Resources.csv`, plus `latitude`, `longitude`, `geocode_match`, `geocode_source`, `geocode_matched_address` and `geocode_review` from the GeoJSON, plus the service type, row type, borough and PDF columns of `data/cleaned/resources_extended.csv` under the same names (see [supabase/migrations/](supabase/migrations)). Multi-label columns such as `service_types_all` are `text[]`, so a filter like `service_types_all=cs.{Housing}` finds every organization that offers housing. It holds 765 rows: the 760 GeoJSON rows plus the 5 NEON sites.

**Getting access.**

| What | Where to find it | Who gets it |
|---|---|---|
| Project URL (`SUPABASE_URL`) | [`app/config.js`](app/config.js) (also Supabase dashboard → Project Settings → API Keys) | committed; anyone |
| Publishable key (`SUPABASE_PUBLISHABLE_KEY`, `sb_publishable_…`) | [`app/config.js`](app/config.js) (same dashboard page) | committed; anyone. It can only read `resources`, and every visitor's browser receives it anyway |
| Secret key (`SUPABASE_SECRET_KEY`, `sb_secret_…`) | ask a teammate in the KAVI org (same dashboard page) | only whoever imports data. Put it in `.env` (`cp .env.example .env`); share it through a password manager, never in chat or in code |
| Dashboard access | Organization settings → Team → Invite | anyone who needs to edit rows or run SQL |

> **Note for agents:** the Supabase project URL and publishable (browser) key are committed in `app/config.js` as `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`. Read them from there and do not ask the user for them. They are all you need to run the page or make read-only REST queries; no `.env` is required. The secret key is not in the repo: if a task needs `SUPABASE_SECRET_KEY` (e.g. `npm run import`), ask the user to put it in `.env`, and never write it into `app/config.js` or any other committed file.

**Reading the data without running any code:** query the REST API with the URL and publishable key from `app/config.js`, for example:

```bash
curl "https://xwpuphhocwstfgbjreeg.supabase.co/rest/v1/resources?category=eq.Housing&select=organization_name,phone_number" -H "apikey: <SUPABASE_PUBLISHABLE_KEY from app/config.js>"
```

**Loading data:** `npm run import` loads `data/nypl_connections_resources.geojson`, the 5 located rows of `data/NYPLConnections_NoMatch.csv` and the columns of `data/cleaned/resources_extended.csv` into the project in `app/config.js`, using `SUPABASE_SECRET_KEY` from `.env`. Add `-- --dry-run` to check the file first, or `-- --replace` to re-import. In a git worktree, run `node pipeline/5_load/link_env.mjs` first to use the main checkout's `.env`. For a new project: `supabase link --project-ref <ref>`, `supabase db push`, update `app/config.js`, then import.

## Running the resource finder

The page needs no setup: `app/config.js` already points it at `data/public/resources.public.json` (and at the Supabase project as a fallback). Serve the repo folder and open it:

```bash
npm run dev
```

Then open http://localhost:5173 for the EMPOWER landing page, and http://localhost:5173/finder.html for the resource map. If another dev server already uses that port, `localhost` may reach it instead: open http://127.0.0.1:5173 or set `PORT`. The same server also serves the OSM map at http://localhost:5173/notebooks/osm/map.html. There is no build step, but the pages live in `app/`, so another static host would need the same URL rewrites as `vercel.json`.

If the page says **"Can't load resources"**, it names the problem: `app/config.js` missing, a wrong URL, a wrong key, or a missing table.

**What the finder does.** `finder.html` asks three questions, each of which can be skipped, and shows how many resources match after every answer:

1. *What kind of help?* One tile per value of `service_types_all`.
2. *Who is it for?* One tile per value of `pdf_audiences`, plus a Spanish-speaking choice (`spanish_speaking = true`).
3. *Where?* An address or ZIP (NYC GeoSearch autocomplete), "use my location", or a click on the map; a distance (0.5, 1, 2, 5 mi or any); boroughs (`borough`); and whether to include hotlines and online resources.

The results page shows the matches as a list or a map. Resources at the same coordinates share one pin with a count. You can change the location, distance, Spanish-speaking filter and In person / Phone / online filter there, and search within the results by name or description. Every card has a "Link to this resource" line: `resource.html?id=<id>` shows that one resource with its map and a link to copy, keyed by the stable id in `data/resource_ids.csv`, so it can be shared or opened during intake. Cards label what nobody has checked yet ("Not yet checked: service types, map location") from `review_flags`, and say "Eligibility not stated" rather than "Open to everyone" when the listing names no restriction; the resource page shows the data's source and date.

How `public.resources` columns are used:

| Finder | Column(s) |
|---|---|
| In person (has a map pin and a distance) | `latitude`/`longitude` are set: every `mapped` row, plus the `mailing_address` and `outside_nyc` rows that were geocoded |
| Phone / online (no distance or borough filter) | no coordinates: `hotline`, `web_only`, and `mailing_address`/`outside_nyc` rows without coordinates |
| Not shown | `row_type = 'cross_reference'` (these rows only say "see the full listing on page N" and have no address, phone or website), and rows with no name, contact or description |
| A bare 5-digit ZIP | the average position of the in-person rows with that `zip_code`, because GeoSearch has no ZIP layer |

The map tiles come from OpenFreeMap. Every pin and every count comes from `latitude`/`longitude` on the loaded rows (`data/public/resources.public.json` by default), and nothing is inferred from descriptions. The map tab also has Libraries, Health facilities and Cooling sites buttons that draw the reference layers in `data/public/layers/` as smaller dots under the pins; clicking a dot names the place and says which layer it came from, since those places are not in the Connections guide. The data file parser and filtering logic are tested by `node --test app/lib/__tests__/filter.test.mjs app/lib/__tests__/csv.test.mjs`.

## Reachability prototype (throwaway)

`reach-prototype.html` answers one question: can a client reach each resource within a time limit, given the transport they have? It is a prototype to test whether the idea works, not part of the finder.

**Launch it.** Same server as the finder, no extra setup:

```bash
npm run dev
```

Then open http://localhost:5173/reach-prototype.html. Enter the client's address (or click the map), pick a time limit (15–90 min), tick what they can use (wheelchair, local bus, subway, express bus) and the number of transfers. The list shows every reachable in-person resource with its estimated minutes and directions; click one to draw the trip on the map. The "Assumptions" panel lets you change speeds and waits and see the results update.

**How it estimates.** No schedules. Ride time is distance along the route's stops divided by an average speed (bus 12 km/h, subway 27 km/h) plus a fixed wait per boarding (bus 8 min, subway 5 min). On-foot legs are straight-line distance × 1.3. A wheelchair user can only board or get off at accessible stops: every bus stop, and subway platforms with ADA access in that direction (MTA Subway Stations dataset). The shaded walking area comes from the public Valhalla server. The stops and routes are in `data/prototype/reach_transit_PROTOTYPE.json`, rebuilt with `python3 app/prototypes/reach/build_reach_transit.py` from MTA GTFS.

**Not done yet:**
- **Accuracy is unchecked.** Eight test trips and their prototype times are in [`docs/reach_prototype_spot_check.md`](docs/reach_prototype_spot_check.md); the MTA trip planner times to compare against are not filled in.
- **Elevator outages are ignored.** A station counts as accessible even when its elevator is out.
- **Time of day is ignored.** Rush hour, nights and weekends get the same speeds and waits.
- **Transfers between subway lines are approximate.** Any two platforms within 250 m count as a transfer; a wheelchair transfer only requires both platforms to be accessible.
- **No fares.** Express buses can be excluded, but cost is not otherwise considered.
- **Nothing is stored.** Every search runs in the browser; no columns or tables were added to Supabase.
- **It depends on a public server.** The walking area uses valhalla1.openstreetmap.de, which has a fair-use policy. Without it the page falls back to straight-line estimates.

## Scripts

`npm run pipeline` runs the data pipeline; see [pipeline/README.md](pipeline/README.md) for what each stage does and how to run one on its own.
