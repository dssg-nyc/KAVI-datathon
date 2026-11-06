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
| 5 | **load**: join the GeoJSON, `resources_extended.csv` and `resource_audiences.csv` into the rows of the Supabase `public.resources` table | `5_load/map_resources.mjs` | the three files above, `data/NYPLConnections_NoMatch.csv` | nothing; the rows, for the next script |
| | send those rows to Supabase | `5_load/load_supabase.mjs` | the rows | the database |
| 6 | **ids**: give every row an id that does not change between builds | `6_build/resource_ids.ts` | the rows from step 5 | `data/resource_ids.csv` |
| | **build** the files the site reads | `6_build/build_data.ts` | the rows from step 5, `data/resource_ids.csv` | `data/public/resources.public.json`, `data/public/resources.provenance.json`, `data/public/resources.meta.json`, `data/review/needs_address.csv` |
| | **layers**: copy the reference layers the map can show (`npm run layers`, needs the network, not in `run.py`) | `6_build/reference_layers.ts` | the three supplementary layers on ArcGIS Online | `data/public/layers/{libraries,health_facilities,cooling_sites}.geojson`, `data/public/layers/index.json` |

Step 3 reads the raw guide, not step 1's output, and step 5 joins everything by row order and `resource_id`. Every step is deterministic: running it again on the same inputs gives the same files, so the outputs are committed and can be diffed.

`run.py` runs steps 1 to 4, step 6 (`ids`, then `build`) and the check. A step whose input is missing is skipped with a note (the PDF is not in git), unless it was asked for by name. Step 5 is deliberately not part of the runner because it writes to the shared database:

```sh
npm run import -- --dry-run      # read and check the files, insert nothing
npm run import                   # needs SUPABASE_SECRET_KEY in .env
```

## Side branch: supplement

[`supplement/`](supplement/README.md) holds the scripts that compare OpenStreetMap and other public lists with the guide, queue
the places the guide lacks for human review, and read organizations' websites for details and events. It is not numbered
and not a stage of `run.py`: most of its steps need the network, its output changes from day to day, and it writes only to
`data/supplement/`, never to the resource table. Nothing it finds reaches the finder unless a person has reviewed it first.
Its tests are in `supplement/__tests__/` and run with the others.

## Stable IDs

The database `id` changes on every `npm run import -- --replace`, and `resource_id` is a row's position in the guide export, which repeats (the NEON clothing closets are six rows with one `resource_id`) and would shift if NYPL re-exported the guide. So step 6 gives each row an id of its own, taken from `resource_id` with `-2`, `-3`... where it repeats and `feature-N` for the one row without one, and keeps the result in `data/resource_ids.csv`, which is committed. On the next run a row is first looked up in that file by name and address, so it keeps its id even if its `resource_id` moved; only rows not seen before get a new id, and a row that has left the data stays in the file as `retired` so its id is never reused.

```sh
npm run ids              # check: fails if data/resource_ids.csv would change
npm run ids -- --write   # update the file after the data changed, then commit it
```

## The files the site reads

`build_data.ts` takes the same rows the loader sends to Supabase, keyed by the stable id, and writes them to `data/public/`, split in two: `resources.public.json` has the columns the finder shows and filters on, `resources.provenance.json` has everything else (the raw guide fields the finder does not show, the geocoder's match, the PDF listing, the service type and audience tagging and their review flags), joined to the public file by `id`. The public file also gets `review_flags`, derived from those review flags: which of `services`, `audiences`, `eligibility`, `location` and `details` nobody has confirmed yet, so the finder can say so on the card (see `reviewFlags()` in `build_data.ts` for the exact rules). `resources.meta.json` names the source and the day the row files last changed; the finder's resource page shows both. Every row goes into both files, cross-references and the one blank row included; the finder decides what to list, as it does today. The files are committed and served as they are, so the site needs no build step and a data change shows up as a diff, one row per line. `data/review/needs_address.csv` lists the rows that name a street but have no point on the map, for someone to check.

`reference_layers.ts` (`npm run layers`) copies the three supplementary ArcGIS Online layers from PRD section 8 into `data/public/layers/`: public libraries and health facilities (both from the NYC Facilities Database) and NYC Parks cooling sites (outdoor spray showers and misting stations, not indoor cooling centers). Each becomes a GeoJSON file of points with only `name`, `address` and `kind` (and `status` for cooling sites), one feature per line, and `index.json` lists the layers with their label, colour, count and the day they last changed. The finder draws them as toggleable layers under the resource pins and never calls ArcGIS Online itself. The script needs the network, so it is not a `run.py` stage; rerun it when a layer changes, and the diff shows what moved. Each file has a schema (`schemas/layer_*.json`) that `check_data.py` checks.

```sh
npm run build:data              # check: fails if a file in data/public/ would change
npm run build:data -- --write   # rewrite them after the data changed, then commit them
```

Until the finder switches to `resources.public.json` ([roadmap](../docs/technical-requirements.md#roadmap) commit 9) it reads `data/kavi_resources.csv`, an export of `public.resources` made by hand from the Supabase dashboard.

## Schemas: what each data file must contain

The steps are in different languages, so they share nothing but the files. [`schemas/`](schemas) says what each file must look like, one JSON file per data file, and `check_data.py` checks the files against them:

```sh
npm run check:data                            # every file that exists; also part of npm run check and CI
uv run pipeline/check_data.py kavi_resources # one file, by schema name
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

- **Python** (`.py`): [uv](https://docs.astral.sh/uv/), and nothing else to install. `pyproject.toml` at the repo root names the project, the Python version (`.python-version`, 3.12, which uv downloads if the machine lacks it) and ruff; `uv.lock` pins them. Each script's header also declares what it needs (`pandas` or `pymupdf`), and `uv run pipeline/<stage>/<script>.py` installs that into a cache on first run. `uv run` is how every Python command in `package.json` and `run.py` starts, so they all use the same interpreter. No `__pycache__` folders are written: the tests and `run.py` turn bytecode off, so `pipeline/` shows only source.
- **TypeScript** (`.ts`) and **JavaScript** (`.mjs`): Node 22.18 or later, no npm dependencies. The geocoder is TypeScript, which Node runs directly. The loader is `.mjs` so Node treats it as an ES module; `map_resources.mjs` turns the files into rows and `load_supabase.mjs` sends them to Supabase over plain HTTP, so the mapping can be reused without a database. `link_env.mjs` is a small helper for git worktrees that makes `.env` a symlink to the main checkout's, so the secret key is not copied.

Each step's tests sit in its own `__tests__/` folder, and `check_data.py`'s in `pipeline/__tests__/`: `npm run test:py` runs the Python ones, `npm test` the geocoder's, the mapping's and the build's. `npm run lint:py` runs [ruff](https://docs.astral.sh/ruff/) over the Python (settings under `[tool.ruff]` in `pyproject.toml`); `npm run lint` runs eslint over the TypeScript tooling. `npm run check` runs all of it, and CI runs `npm run check`. Database schema changes go in [`supabase/migrations/`](../supabase/migrations).
