# Pipeline

Turns the Connections Guide, a spreadsheet the NYPL team exported, into the resource table the finder shows. One numbered folder per step, in the order they run; `run.py` runs them all. Each step reads files from [`data/`](../data), adds columns, and writes new files back to `data/`. Nothing in the app imports this code; the app only reads the data it produces.

```sh
npm run pipeline                 # every step whose inputs are present, in order
npm run pipeline -- clean pdf    # only these steps
npm run pipeline -- --list       # the steps with their inputs and outputs
```

## The steps, in order

| # | Step | Script | Reads | Writes |
|---|---|---|---|---|
| 1 | **clean** the guide: trim text, fix ZIPs and websites, merge address-only rows, derive `borough`, `row_type` and a first `service_type` | `1_clean/clean_guide.py` | `data/NYPL Connections Resources.csv` (the raw guide, 760 rows), `data/NYPLConnections_NoMatch.csv` | `data/cleaned/resources_clean.csv` (759 rows), `data/cleaned/review_list.csv` |
| 2 | **pdf**: pull every listing out of the printed guide | `2_pdf/extract_pdf.py` | `data/NYPL_JPS_Connections_2026.pdf` (not in git) | `data/extracted/connections_pdf_listings.csv` |
| | match each guide row to its PDF listing | `2_pdf/match_pdf.py` | the two files above | `data/extracted/connections_pdf_vs_csv.csv` |
| | extend the cleaned rows with what the PDF says (chapter, section, audiences), tag the services each description mentions, apply the human reviews in `data/review/` | `2_pdf/extend_with_pdf.py` | `resources_clean.csv`, the PDF listings, `data/reference/`, `data/review/` | `data/cleaned/resources_extended.csv` |
| 3 | **geocode** every address (NYC GeoSearch, then the Census geocoder; needs the network) | `3_geocode/geocode.ts` | `data/NYPL Connections Resources.csv` | `data/nypl_connections_resources.geojson` |
| 4 | **audiences**: tag who each resource serves ("Who is it for?") | `4_audiences/tag_audiences.py` | `resources_extended.csv`, the PDF listings, `data/review/reviewed_audiences.csv` | `data/cleaned/resource_audiences.csv`, two review lists in `data/review/` |
| | check that output before it is loaded | `4_audiences/check_audiences.py` | the files above and the GeoJSON | nothing; exits 1 on a failed check |
| | **check** every data file above against its schema | `check_data.py` | the files above and `data/kavi_resources.csv` | nothing; exits 1 on an invalid row |
| 5 | **load**: join the GeoJSON, `resources_extended.csv` and `resource_audiences.csv` into the Supabase `public.resources` table | `5_load/load_supabase.mjs` | the three files above, `data/NYPLConnections_NoMatch.csv` | the database |

Step 3 reads the raw guide, not step 1's output, and step 5 joins everything by row order and `resource_id`. Every step is deterministic: running it again on the same inputs gives the same files, so the outputs are committed and can be diffed.

`run.py` runs steps 1 to 4, then the check. A step whose input is missing is skipped with a note (the PDF is not in git), unless it was asked for by name. Step 5 is deliberately not part of the runner because it writes to the shared database:

```sh
npm run import -- --dry-run      # read and check the files, insert nothing
npm run import                   # needs SUPABASE_SECRET_KEY in .env
```

The site does not read the pipeline's output directly. It reads `data/kavi_resources.csv`, an export of `public.resources` made by hand from the Supabase dashboard. Closing that gap, so the pipeline writes the site's data file itself, is on the [roadmap](../docs/technical-requirements.md#roadmap).

## Schemas: what each data file must contain

The steps are in different languages, so they share nothing but the files. [`schemas/`](schemas) says what each file must look like, one JSON file per data file, and `check_data.py` checks the files against them:

```sh
npm run check:data                            # every file that exists; also part of npm run check and CI
python3 pipeline/check_data.py kavi_resources # one file, by schema name
```

| Schema | Checks |
|---|---|
| `resources_clean.json` | step 1's output |
| `resources_extended.json` | step 2's output; `extends` the clean schema, so it lists only the added columns |
| `connections_pdf_listings.json` | step 2's PDF listings |
| `nypl_connections_resources.json` | step 3's GeoJSON: the properties, and that each geometry is a Point in range or null |
| `resource_audiences.json` | step 4's output |
| `kavi_resources.json` | the Supabase export the site reads, with Postgres `t`/`f` booleans and `{a,"b c"}` arrays |

A schema lists every column with its `type` (`text`, `integer`, `number`, `boolean`, `yes_no` or `list`), whether it is `required`, `unique`, its allowed `values` or list `items`, a `pattern` or `min`/`max`. Allowed values that several files share, such as the service types, audiences, boroughs and row types, live once in `schemas/vocabularies.json` and are referred to as `"$service_types"`. A file must have exactly the schema's columns, so a step that adds or renames a column also changes the schema, in the same commit. Blank cells are allowed unless the column is `required`. The header of `check_data.py` spells out the keys.

`kavi_resources.json` also lists three `planned` columns, `hours`, `eligibility` and `referral_process`, which the PRD asks for and the data does not have yet. A planned column is checked when it is present and not missed when it is absent, so adding it later is a data change, not a schema change.

The check reports structure: types, allowed values, uniqueness, column sets. Whether the columns agree with each other (for example an `Everyone` audience on a row marked `restricted`) is what `4_audiences/check_audiences.py` tests, and the join between the files is what `npm run import -- --dry-run` tests.

## What each step decides, and why

The rules behind each step and the columns it adds are written up in `docs/`:

- [docs/cleaning.md](../docs/cleaning.md) for step 1
- [docs/pdf_extension.md](../docs/pdf_extension.md) for step 2
- [docs/geocoding.md](../docs/geocoding.md) for step 3
- [docs/audiences.md](../docs/audiences.md) and [docs/audience_matching.md](../docs/audience_matching.md) for step 4

Steps 1 and 4 were first written as notebooks, which are still in [`notebooks/`](../notebooks); the scripts here are the same rules with the same output. The notebooks stay as the place to look at intermediate results. Change a rule in both, or retire the notebook.

## Languages and tooling

The steps are in Python, TypeScript and JavaScript because different people wrote them, and the rule in this repo is to move code rather than rewrite it. Each language needs only one tool:

- **Python** (`.py`): [uv](https://docs.astral.sh/uv/). Each script's header declares what it needs (`pandas` or `pymupdf`), and `uv run` installs that into a cache on first run. There is no project environment to set up. `run.py`, `check_data.py` and `check_audiences.py` need only the standard library, so `python3` runs them.
- **TypeScript** (`.ts`) and **JavaScript** (`.mjs`): Node 22.18 or later, no npm dependencies. The geocoder is TypeScript, which Node runs directly. The loader is `.mjs` so Node treats it as an ES module; it talks to Supabase over plain HTTP. `link_env.mjs` is a small helper for git worktrees that makes `.env` a symlink to the main checkout's, so the secret key is not copied.

Each step's tests sit in its own `__tests__/` folder, and `check_data.py`'s in `pipeline/__tests__/`: `npm run test:py` runs the Python ones, `npm test` the geocoder's. `npm run lint:py` runs [ruff](https://docs.astral.sh/ruff/) over the Python (settings in `ruff.toml`); `npm run lint` runs eslint over the TypeScript tooling. `npm run check` runs all of it, and CI runs `npm run check`. Database schema changes go in [`supabase/migrations/`](../supabase/migrations).
