# Scripts

Scripts are grouped by what they work on. Run them from the repo root. The Node scripts need Node 22.18 or later and have no npm dependencies. The Python scripts in `pdf/` need [uv](https://docs.astral.sh/uv/), which installs their one dependency (`pymupdf`) from the header of each script.

| Folder | Script | What it does | Run with |
|---|---|---|---|
| `database/` | `import-resources.mjs` | Loads `data/nypl_connections_resources.geojson` (every row of the Connections Guide CSV plus coordinates) and the rows of `data/NYPLConnections_NoMatch.csv` that have `lat`/`lon` into the Supabase `resources` table of the project in `config.js`. Needs `SUPABASE_SECRET_KEY` in `.env`. `--dry-run` checks the file without inserting; `--replace` deletes the existing rows first. | `npm run import -- --dry-run` |
| `database/` | `link-main-env.mjs` | In a git worktree, makes `.env` a symlink to the main checkout's `.env`, so the import can use its `SUPABASE_SECRET_KEY`. Refuses to replace an existing `.env`. | `node scripts/database/link-main-env.mjs` |
| `web/` | `dev.mjs` | Serves the repo as static files on http://localhost:5173 (`index.html`, `scripts/osm/map.html`), reachable from this computer only. Never serves dotfiles such as `.env`. | `npm run dev` |
| `osm/` | `osm_resources_nyc.ts` | Downloads NYC service locations from OpenStreetMap into `data/nyc_osm_resources.csv` and `.geojson`. | `npm run osm` |
| `osm/` | `map.html` | Map preview of the OSM layer. | see [`osm/README.md`](osm/README.md) |
| (top level) | `nypl_connections_to_geojson.ts` | Geocodes `data/NYPL Connections Resources.csv` (NYC GeoSearch, then Census) into `data/nypl_connections_resources.geojson`. See [`nypl_connections.md`](nypl_connections.md). | `node scripts/nypl_connections_to_geojson.ts` |
| `prototype/` | `build_reach_transit.py` | PROTOTYPE, throwaway. Downloads the MTA subway and bus GTFS and the MTA Subway Stations ADA flags into `data/prototype/reach_transit_PROTOTYPE.json`, the stops and routes `reach-prototype.html` searches. | `python3 scripts/prototype/build_reach_transit.py` |
| `tests/` | `nypl_connections_to_geojson.test.ts` | Unit tests for the script above; no network calls. | `node --test scripts/tests/nypl_connections_to_geojson.test.ts` |
| `tests/` | `finder_filter.test.mjs` | Unit tests for the finder's filtering (`finder/filter.js`, `finder/resources.js`); no network calls. | `node --test scripts/tests/finder_filter.test.mjs` |
| `analysis/` | `analyze_nypl_connections_location.py` | Reproduces the numbers in `analysis/nypl_connections_location_analysis.md` from the GeoJSON. | `python3 scripts/analysis/analyze_nypl_connections_location.py` |
| `pdf/` | `extract_listings.py` | Reads `data/NYPL_JPS_Connections_2026.pdf` (not in git) and writes every listing with its chapter, section, and subheading to `data/extracted/connections_pdf_listings.csv`. Headings are read from fixed font sizes and checked against the PDF's bookmarks. | `uv run scripts/pdf/extract_listings.py` |
| `pdf/` | `compare_to_csv.py` | Matches each row of `data/NYPL Connections Resources.csv` to a PDF listing and writes `data/extracted/connections_pdf_vs_csv.csv` with whether the chapter and section agree. Run `extract_listings.py` first. | `uv run scripts/pdf/compare_to_csv.py` |
| `pdf/` | `extend_clean_resources.py` | Adds PDF chapter, section, service subtype, audience, contradiction, and multi-label description service type columns (reviewed in `pdf/reviewed_service_types.csv`) to `data/cleaned/resources_clean.csv`, and fills blank service types, in `data/cleaned/resources_extended.csv`. See [`pdf/README.md`](pdf/README.md). | `uv run scripts/pdf/extend_clean_resources.py` |
| `tests/` | `extend_clean_resources.test.py` | Unit tests for the script above's description-keyword tagging; no file I/O. | `uv run scripts/tests/extend_clean_resources.test.py` |

Every script reads from and writes to the top-level [`data/`](../data) folder. Database schema changes go in [`supabase/migrations/`](../supabase/migrations), not here.

When you add a script, put it in the folder for what it works on (or a new folder if none fits) and add a row to this table.
