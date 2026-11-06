# Architecture

How the KAVI resource finder is put together: the tech stack, the website, the data pipeline, and how data gets from the NYPL Connections Guide to a visitor's screen. [PRD.md](PRD.md) says what the product should do, [technical-requirements.md](technical-requirements.md) says why it is built this way and what comes next, and [handoff.md](handoff.md) says how to run and update it.

## The system in one picture

```
                           ┌──────────────────────── git repo ─────────────────────────┐
  NYPL Connections Guide   │                                                           │
  ─ CSV export ───────────►│  data/  (raw inputs, committed)                           │
  ─ NoMatch CSV ──────────►│     │                                                     │
  ─ printed PDF (local) ──►│     ▼                                                     │
                           │  core/run.py  ── Python pipeline, one script per stage ── │
  NYC GeoSearch, Census ◄──┼──  clean → pdf → geocode → audiences → ids → build → check│
                           │     │                                                     │
                           │     ▼                                                     │
                           │  data/public/resources.public.json  (+ meta, provenance)  │
  DCP Facilities, Parks ◄──┼──  data/public/layers/*.geojson  (npm run layers)         │
  (ArcGIS)                 │     │                                                     │
                           │     │  committed; Vercel serves it as a static file       │
                           └─────┼─────────────────────────────────────────┬───────────┘
                                 ▼                                         │ npm run import
                       ┌─────────────────────┐                             │ (by hand, secret key)
   visitor's browser ◄─┤ Vercel (static site)│                             ▼
   app/ pages + JS     └─────────────────────┘                   ┌───────────────────┐
     │  fetch JSON, filter in the browser                        │ Supabase Postgres │
     ├─► OpenFreeMap tiles (map)                                 │ public.resources  │
     ├─► NYC GeoSearch (address search)                          └─────────┬─────────┘
     └─► Supabase, only if the JSON file fails to load ◄───────────────────┘

  Side branch, not part of the above:  core/supplement/ (OSM and other public lists, website crawl)
  → data/supplement/ → human review in notebooks/osm/. Never writes to the resource data.
```

The important point: **the site reads a file the pipeline commits, not the database.** `app/config.js` sets `RESOURCES_FILE` to `data/public/resources.public.json`; the finder downloads it and does all searching and filtering in the browser. Supabase holds the same rows and is a fallback the finder uses only when that file cannot be loaded.

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Pages | Static HTML, CSS and browser JavaScript (ES modules) | No framework, no bundler, no build step. JSDoc types in `app/lib/types.js`. |
| Map | [MapLibre GL JS](https://maplibre.org/) 5.6 with [OpenFreeMap](https://openfreemap.org/) tiles | Vendored in `app/vendor/`, loaded only when a map is drawn. |
| Address search | [NYC GeoSearch](https://geosearch.planninglabs.nyc/) (NYC Planning Labs) | Called from the browser as the visitor types; ZIP codes are matched locally. |
| Fonts | Self-hosted in `app/vendor/` | No font CDN. |
| Hosting | [Vercel](https://vercel.com/), no-framework static project | `vercel.json`: URL rewrites and security headers. `.vercelignore`: keeps the pipeline, docs and internal data off the site. |
| Database (fallback) | [Supabase](https://supabase.com/) Postgres, table `public.resources` | Read-only to browsers through row-level security and the publishable key; schema in `supabase/migrations/`. supabase-js 2 is vendored and loaded on demand. |
| Data pipeline | Python 3.12 run through [uv](https://docs.astral.sh/uv/) | pandas for cleaning, PyMuPDF for the printed guide; each script declares its own dependencies. Standard library elsewhere. |
| Database loader | Node 22.18+ (`supabase/load_supabase.mjs`) | No npm dependencies; plain HTTP to Supabase. Run by hand. |
| Notebooks | Jupyter (`notebooks/`) | Analysis and the OSM evaluation; not part of the site. |
| Lint | ruff (Python), eslint (the loader in `supabase/`) | |
| Tests | `node --test` (app and loader), `unittest` (pipeline and supplement), schema checks (`check_data.py`) | `npm run check` runs them all. |
| Performance and accessibility | Lighthouse (`npm run audit`) | Fails below 100 accessibility. |
| CI | GitHub Actions (`.github/workflows/ci.yml`) | `npm ci` + `npm run check` on Node 22 with uv; Lighthouse in a second job. |

## The website (`app/`)

### Pages and URLs

`vercel.json` rewrites the public URLs to files under `app/`, so the URLs stay short while the files are organized by role:

| URL | File | What it is |
|---|---|---|
| `/` | `app/pages/index.html` | Landing page |
| `/finder.html` | `app/pages/finder.html` + `finder.js` | The resource finder: three questions (what help, who for, where), then a list and a map |
| `/resource.html?id=176` | `app/pages/resource.html` + `resource.js` | One resource, linkable and shareable; the id is stable across data updates |
| `/privacy.html` | `app/pages/privacy.html` | What the site sends where |
| `/reach-prototype.html` | `app/prototypes/reach/` | Transit-reach prototype, outside the main design (still uses CDNs, so excluded from the strict security policy) |

### Code layout

The browser code is in three layers. Each depends only on the layers below it.

- **`app/pages/`**: one script per page. It wires the page together: loads data, keeps the state of the filters, and renders.
- **`app/components/`**: pieces of UI. `cards.js` renders resource cards and map popups (and owns `escapeHtml`, through which every data value passes), `map.js` wraps MapLibre, `place-input.js` is the address/ZIP box. CSS sits beside them.
- **`app/lib/`**: no DOM work beyond loading. `csv.js` and `preview.js` load the data file and check its columns; `resources.js` turns a row into the record the finder filters on (`toResource`) and holds the Supabase fallback query; `filter.js` is the filtering and counting logic; `geo.js` does distances and address search; `share.js` builds resource links and reads `resources.meta.json`; `layers.js` loads the reference layers; `vendor.js` loads MapLibre and supabase-js on demand.

`app/config.js` holds the only settings: the data file path and the Supabase URL and publishable key (safe to publish; see [Trust boundaries](#trust-boundaries)).

### How a page gets its data

1. `finder.js` starts loading `data/public/layers/index.json` and, through `preview.js`, the file named by `RESOURCES_FILE`.
2. `csv.js` parses it and checks that the columns the finder needs are there.
3. If that fails, and only then, `resources.js` loads supabase-js and pages through `public.resources`.
4. Rows that should not be listed are dropped (`isListed`), the rest become records (`toResource`), and the facet values are collected.
5. Every change to a question or a filter re-runs `filter.js` over the 765 records in memory and re-renders the list and, if open, the map. There is no server round trip.

`resource.js` does the same load, finds the row by its stable id (`share.js`), and shows the date from `resources.meta.json`.

### Design choices

- **No build step.** What is in `app/` is what is served. Anyone can change a page without a toolchain, and Vercel needs no build configuration.
- **Load little up front.** The finder's first paint needs the page, its CSS and modules, and the data file. MapLibre (about 300 KB) loads only when the map tab opens; supabase-js only on fallback. `modulepreload` lists in the HTML are tested.
- **Third parties are few and named.** A core page talks only to this site, OpenFreeMap, NYC GeoSearch and, as a fallback, Supabase. The content security policy in `vercel.json` allows exactly those hosts, the dev server (`npm run dev`) sends the same headers, and `/privacy.html` lists them for visitors.
- **Data is treated as untrusted text.** Values from the data files go through `escapeHtml`, and links through `safeUrl`, before reaching the page.
- **Review state is visible.** Each row carries `review_flags` (services, audiences, eligibility, location, details); the cards say when something has not been confirmed by a person.

## The data pipeline (`core/`)

### Stages

`npm run pipeline` (`core/run.py`) runs these in order. Each stage is a Python script in `core/pipeline/`; stages share nothing but files, so any one can be run, tested or replaced on its own. A stage whose input is missing is skipped (the printed-guide PDF is not in git).

| Stage | Script(s) | Reads | Writes |
|---|---|---|---|
| `clean` | `clean_guide.py` | Guide CSV export, NoMatch CSV | `data/cleaned/resources_clean.csv`, `review_list.csv` |
| `pdf` | `extract_pdf.py`, `match_pdf.py`, `extend_with_pdf.py` | Printed guide PDF, cleaned rows | `data/extracted/*.csv`, `data/cleaned/resources_extended.csv` |
| `geocode` | `geocode.py` (network: NYC GeoSearch, then US Census) | Guide CSV export | `data/nypl_connections_resources.geojson` |
| `audiences` | `tag_audiences.py`, `check_audiences.py` | Extended rows, PDF listings, GeoJSON | `data/cleaned/resource_audiences.csv`, `data/review/audience_*.csv` |
| `ids` | `resource_ids.py` | The mapped rows | `data/resource_ids.csv` (stable ids; old ids are retired, never reused) |
| `build` | `build_data.py` | The mapped rows and ids | `data/public/resources.public.json`, `resources.provenance.json`, `resources.meta.json`, `data/review/needs_address.csv` |
| `check` | `check_data.py` | Every data file | Nothing; fails if a file does not match its schema in `core/schemas/` |

`map_resources.py` is not a stage but a library used by `ids` and `build`: it joins the GeoJSON, extended rows, audiences and NoMatch extras into one row per resource, in the shape of `public.resources`.

`reference_layers.py` (`npm run layers`) runs on its own: it downloads libraries, health facilities and cooling sites from the DSSG NYC ArcGIS layers (NYC Department of City Planning Facilities Database, NYC Parks) into `data/public/layers/`.

### Storage

Everything the site reads is a committed file. The folders under `data/` are split by role:

| Folder | What | Committed | Served by Vercel |
|---|---|---|---|
| `data/` (top level) | Raw guide exports, the geocoded GeoJSON, `resource_ids.csv` | Yes | No |
| `data/cleaned/`, `data/extracted/` | Intermediate pipeline output | Yes | No |
| `data/review/` | Lists for people to check, and their verdicts, which the pipeline reads back | Yes | No |
| `data/reference/` | Lookup tables the pipeline uses | Yes | No |
| `data/public/` | What the site reads: resources, metadata, reference layers | Yes | **Yes** |
| `data/supplement/` | Supplement output (see below); mostly ignored by git | A few files | No |

The public file has only the columns the site shows, plus `review_flags`. Where each value came from (geocode match, sources, review notes) is in `resources.provenance.json`, joined by `id`. Committing generated data means every data change is a reviewable diff, and the site needs no database to run.

### Schemas and checks

Each data file has a JSON schema in `core/schemas/` (columns, types, allowed values, shared vocabularies in `vocabularies.json`). `check_data.py` validates every file against it, as the last pipeline stage and in CI. The tests in `core/pipeline/__tests__/` also rebuild the committed outputs from the committed inputs and fail if they differ, so a hand-edited output or a stale file is caught.

### Loading into Supabase

`npm run import` (`supabase/load_supabase.mjs`) sends the mapped rows to `public.resources`. It needs `SUPABASE_SECRET_KEY` in `.env`, so it is run by hand, never by CI or the pipeline. It keeps its own JavaScript copy of the mapping (`supabase/map_resources.mjs`) so it runs without Python; a test runs both on the committed data and fails if any row differs. Schema changes go in `supabase/migrations/`.

### The supplement (`core/supplement/`)

A side branch, deliberately outside `run.py`. It gathers OpenStreetMap and other public lists of service locations (DCP facilities, HRSA, OMH, DYCD, DOHMH childcare, Workforce1, ENDGBV, IRS exempt organizations, CMS opioid treatment programs), matches them to the guide, scores the places the guide lacks, and can read organizations' own websites (robots.txt obeyed, rate-limited, run only on purpose). Output goes only to `data/supplement/` and the review notebook and map in `notebooks/osm/`.

The guide is human-verified and stays the source of truth: nothing in the supplement writes to `data/public/`, the resource table or Supabase. A place found there reaches the site only by a person reviewing it and adding it to the guide. See [`core/supplement/README.md`](../core/supplement/README.md).

## Trust boundaries

- **The NYPL Connections Guide is the source of truth.** The pipeline cleans, extends and tags it; anything inferred rather than stated is flagged in `review_flags` and shown as unconfirmed.
- **Secrets live only in `.env`** (git-ignored), used only by the loader on a person's machine. The browser gets the publishable key, which row-level security limits to reading `public.resources`.
- **Hidden addresses stay hidden.** Where a source withholds a location, such as confidential sites in the ENDGBV directory the supplement reads, it stays blank: nothing geocodes or fills it in.
- **Outside content is untrusted.** Crawled text and third-party data are escaped wherever they are shown, and never reach the site's data without human review.

## Updating the data

1. Replace the guide export in `data/`, or edit a review file in `data/review/`.
2. `npm run pipeline` (the `geocode` stage calls NYC GeoSearch and the Census geocoder).
3. `npm run check`, then review the diff of `data/public/` and `data/resource_ids.csv` and open a PR. Merging deploys it on Vercel.
4. Optionally `npm run import -- --dry-run`, then `npm run import -- --replace`, to bring Supabase in line.

## Where to read more

- [core/README.md](../core/README.md): each pipeline step, its inputs and outputs, and how to run one.
- [app/README.md](../app/README.md): the website's files, tests and local development.
- [README.md](../README.md): the repo layout and a table of every data file.
- [data/review/README.md](../data/review/README.md): the review files and how verdicts flow back into the pipeline.
- [datathon/](datathon/): design notes from the datathon on cleaning, the PDF extension, geocoding and audiences.
