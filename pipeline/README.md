# Pipeline

Turns the Connections Guide into the data the site shows. One folder per stage, in the order they run. Run the commands from the repo root; every stage reads from and writes to the top-level [`data/`](../data) folder.

```
data/NYPL Connections Resources.csv              the raw guide, 760 rows
  ├─ cleaning/   → data/cleaned/resources_clean.csv
  ├─ pdf/        → data/extracted/*.csv, data/cleaned/resources_extended.csv
  ├─ geocode/    → data/nypl_connections_resources.geojson   (reads the raw CSV, not cleaning/)
  ├─ audiences/  → data/cleaned/resource_audiences.csv
  └─ load/       joins pdf + geocode + audiences → Supabase public.resources
```

The site does not read the pipeline's output directly. It reads `data/kavi_resources.csv`, an export of `public.resources` made by hand from the Supabase dashboard. Closing that gap, so the pipeline writes the site's data file itself, is the next step on the [roadmap](../docs/technical-requirements.md#roadmap).

## Stages

| Stage | Files | What it does | Run with |
|---|---|---|---|
| [`cleaning/`](cleaning/README.md) | [`notebooks/data_cleaning_added_features.ipynb`](../notebooks/data_cleaning_added_features.ipynb) | Normalizes names, addresses, ZIPs and websites; derives `borough`, `row_type` and a first `service_type`. Notebook only today; a Python version is planned. | Run all cells |
| [`pdf/`](pdf/README.md) | `extract_listings.py` | Reads `data/NYPL_JPS_Connections_2026.pdf` (not in git) into `data/extracted/connections_pdf_listings.csv`. | `uv run pipeline/pdf/extract_listings.py` |
| | `compare_to_csv.py` | Matches each guide row to a PDF listing, in `data/extracted/connections_pdf_vs_csv.csv`. | `uv run pipeline/pdf/compare_to_csv.py` |
| | `extend_clean_resources.py` | Adds PDF and description columns, applies the reviews in `data/review/` and the mapping in `data/reference/`, fills blank service types, in `data/cleaned/resources_extended.csv`. | `uv run pipeline/pdf/extend_clean_resources.py` |
| [`geocode/`](geocode/nypl_connections.md) | `nypl_connections_to_geojson.ts` | Geocodes the raw guide (NYC GeoSearch, then Census) into `data/nypl_connections_resources.geojson`. | `node pipeline/geocode/nypl_connections_to_geojson.ts` |
| [`audiences/`](audiences/README.md) | [`notebooks/audience_enrichment.ipynb`](../notebooks/audience_enrichment.ipynb) | Tags who each resource serves, in `data/cleaned/resource_audiences.csv`. Notebook only today. | Run all cells |
| | `check_audiences.py` | Checks that output before a load. Writes nothing. | `python3 pipeline/audiences/check_audiences.py` |
| `load/` | `import-resources.mjs` | Joins the GeoJSON, the located `NYPLConnections_NoMatch.csv` rows, `resources_extended.csv` and `resource_audiences.csv` into Supabase. Needs `SUPABASE_SECRET_KEY` in `.env`; `--dry-run` needs nothing. | `npm run import -- --dry-run` |
| | `link-main-env.mjs` | In a git worktree, makes `.env` a symlink to the main checkout's. Refuses to replace an existing `.env`. | `node pipeline/load/link-main-env.mjs` |

The Node scripts need Node 22.18 or later and have no npm dependencies. The Python scripts in `pdf/` need [uv](https://docs.astral.sh/uv/), which installs `pymupdf` from the header of each script. Database schema changes go in [`supabase/migrations/`](../supabase/migrations).

Tests sit in each stage's `__tests__/` folder: `npm test` runs the geocoder's, `npm run test:py` the PDF stage's.
