# Technical requirements and roadmap

**Status: proposed, for team review.** [PRD.md](PRD.md) says what to build. This covers where the code stands, how it should change, and the order of work. All targets are proposals, and none has been agreed with KAVI.

## Where things stand

The site is static HTML, CSS and browser JS with no build step. The website is in `app/`, the data pipeline is in `core/pipeline/`, one script per stage, and the notebooks, one-off analysis and the OSM layer are in `notebooks/`, and `vercel.json` maps the public URLs to the pages.

- **Finder:** `app/pages/finder.html`, `app/components/` and `app/lib/`. `app/config.js` sets `RESOURCES_FILE`, so the browser downloads `data/public/resources.public.json`, with Supabase as the fallback data source.
- **Data pipeline:** Python scripts and notebooks clean, enrich and geocode the Connections Guide, and `supabase/load_supabase.mjs` loads it into Supabase.
- **Tests:** `npm run check` runs the type check, linters and the JS, TS and Python tests; `npm run audit` runs Lighthouse. CI runs both on every push. (At the start there was no CI and no `npm test`.)
- **Handoff:** [handoff.md](handoff.md) says what is deployed, how to update the data and what the team still has to decide.
- **PRD coverage:** map, service, keyword, address, ZIP and borough search, and hotlines are built. The gaps are listed under [PRD features](#prd-features).

### Who built what

| Area | Files | Base authors |
|---|---|---|
| Finder app and map | `app/pages/finder.js`, `app/components/cards.js`, `map.js`, `place-input.js`, `app/lib/filter.js`, `geo.js`, `resources.js` | Akai, Franziska |
| CSV loader | `app/lib/csv.js`, `preview.js` | Cursor Agent (jyr-ai's PRs), Franziska |
| Landing page and brand | `app/pages/index.html`, `app/brand/` | Cursor Agent (jyr-ai's PRs), Akai |
| Reach prototype | `app/prototypes/reach/` | Akai |
| Cleaning and audiences | `core/pipeline/clean_guide.py`, `core/pipeline/tag_audiences.py`, `notebooks/` | Franziska |
| PDF extension | `core/pipeline/extract_pdf.py`, `match_pdf.py`, `extend_with_pdf.py` | Akai, Rita |
| Geocoding | `core/pipeline/geocode.py` (ported from Rita's `geocode.ts`) | Rita, Akai |
| OSM layer | `core/supplement/`, `notebooks/osm/` | Ramsey |
| Database import | `supabase/` (`load_supabase.mjs`, migrations) | Akai, Franziska |

## Design decisions

1. **Build on the existing code.** Move files with `git mv`, edit them in place, and add new files for new behaviour. Renames get their own commits so history follows the files.
2. **Keep the site static for now.** A Next.js port with Postgres would replace most of the finder and need a database and hosting changes. The cost is that updating a resource still means a data file change and a PR, until the team adds a database and admin area.
3. **Commit generated data.** `npm run build:data` joins and validates the source files, then writes `data/public/resources.public.json` for the finder and `resources.provenance.json` for review and source fields. Filtering stays in the browser, because 765 rows do not need a search API.
4. **Python, JS and TS all stay.** Python handles cleaning and analysis, JS handles the browser, and new Node tooling is TS. Scripts in different languages connect only through data files checked against a schema.
5. **Keep Vercel's behaviour unchanged.** To our understanding of Vercel's default for projects with no framework, that means no `build` script in `package.json` and no top-level `public/` or `api/` directory. The HTML pages moved to `app/`, so `vercel.json` rewrites keep the public URLs and `.vercelignore` keeps internal files off the site. The team should confirm this on a preview deployment before merging.
6. **Take stable IDs from the source data.** The database `id` changes on each `import --replace`, so IDs come from `resource_id`, with a suffix where it repeats, such as the NEON sites. The mapping is committed.
7. **Leave Supabase in place.** The refactor does not change `supabase/` or run the import against the database, and the finder's fallback stays. Retiring it is the team's decision.
8. **Serve nothing from other companies, and say so.** Fonts and libraries are in `app/vendor/`, so a core page makes requests only to this site, the map tiles, GeoSearch and, as a fallback, Supabase. `vercel.json` sets a content security policy that allows exactly those hosts, plus `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and `Permissions-Policy`; the dev server sends the same headers so a mistake shows up locally. `/privacy.html` lists the same hosts for visitors. The reach prototype is excluded from the policy because it still uses CDNs.
9. **One tool per language.** Python runs through [uv](https://docs.astral.sh/uv/) (`pyproject.toml`, `.python-version`, `uv.lock`), Node through npm. No `__pycache__` folders are written by the tests or the pipeline, so `core/pipeline/` stays readable.

## Open decisions for the team

| Decision | Why it matters | Assumption until decided |
|---|---|---|
| Public or partner-only? (PRD 13) | A static site cannot restrict access | Public, per PRD 7.6 |
| Who owns data updates at KAVI? (PRD 13) | Without an owner the data goes stale | Unassigned |
| Which geography model: catchment, precinct or neighborhood? (PRD 13) | Blocks the geography filter in PRD 7.5 | Not built |
| Is an organization type filter useful? (PRD 7.5) | The data has no organization type field | Not built |
| Future of Supabase | Two data paths remain until this is decided | Fallback stays |
| Unlink or integrate the reach prototype? | It is not in the PRD and its author marked it throwaway, but it works (about 540 lines plus a transit data builder). Unlinking is one footer link in `index.html`; the page and its URL stay. Integrating is a few commits with these acceptance criteria: it reads `data/public/resources.public.json`, not Supabase; its scripts come from `app/vendor/`, not a CDN; someone owns rebuilding `data/prototype/reach_transit_PROTOTYPE.json` (910 KB, from MTA GTFS) when routes change; the team accepts a volunteer-run Valhalla routing server with no uptime guarantee, or the isochrone is dropped; the "times are estimates from distance, not schedules" caveat is part of the UI, not a banner; it gets tests and the same accessibility pass as the finder | Stays linked and unchanged until decided |
| When can audience tags be used with clients? | [audience_matching.md](audience_matching.md) calls them demo only | Labelled in the UI |
| Repo license | Without one, partners cannot legally reuse the code. The vendored libraries and fonts keep their own licences in `app/vendor/` whatever is chosen | MIT, in `LICENSE` at the repo root, chosen in the refactor; the team can change it |
| Privacy page wording | `/privacy.html` was written from the code and names KAVI's public address as the contact | As written, until KAVI reviews it |

## Roadmap

One PR, reviewed commit by commit. Each commit should leave the checks passing and the site working. The exception is commit 3, a pure rename so history follows the files: the site and tests work again at commit 4.

| # | Commit | Touches existing code? |
|---|---|---|
| 1 | `docs: add technical requirements and roadmap` | No |
| 2 | `chore: add type checks, lint and CI for new code` | `package.json` only |
| 3 | `chore: reorganize into app/, core/ and docs/` | Renames only |
| 4 | `chore: fix paths after the reorganization` | Paths only, plus new `vercel.json` and `.vercelignore` |
| 4a | `refactor(pipeline): rewrite the cleaning stage in Python and add a single pipeline command` | `package.json` and READMEs; `clean_guide.py` is new and reproduces the notebook's output |
| 5 | `feat(data): add schemas for resource data` | `package.json` and `core/run.py` (a `check` stage); schemas in `core/schemas/`, validator `core/pipeline/check_data.py` |
| 6 | `refactor(data): export the import mapping` | `load_supabase.mjs`: the file-to-row mapping moved to `map_resources.mjs`, same output; `package.json`, `tsconfig.json` |
| 7 | `feat(data): add stable resource IDs` | `package.json` (an `ids` script), `tsconfig.json`, `eslint.config.js` and `core/run.py` (an `ids` stage); the mapping is `data/resource_ids.csv`, made by `core/pipeline/resource_ids.ts` |
| 8 | `feat(data): generate public and provenance data files` | `package.json` (a `build:data` script), `core/run.py` (a `build` stage), `core/pipeline/check_data.py` (reads JSON files too); the files are `data/public/resources.public.json` and `resources.provenance.json`, made by `core/pipeline/build_data.ts` |
| 9 | `feat(finder): load the generated public data file` | `csv.js` reads the JSON file as well as a CSV, `preview.js` and `app/config.js` point at it (`RESOURCES_FILE`; `RESOURCES_CSV` still works), one comment line in `finder.js`; `app/lib/types.js` is new |
| 10 | `chore(finder): vendor MapLibre instead of loading it from a CDN` | Three tags in `finder.html` point at `app/vendor/` (MapLibre and supabase-js, same versions, with licences); one message in `finder.js` and one comment in `map.js` |
| 12 | `feat(finder): add shareable resource pages` | New `app/pages/resource.html`, `resource.js`, `app/components/resource.css` and `app/lib/share.js`; `cards.js` gained a "Link to this resource" line, `finder.css` one rule, `vercel.json` one rewrite |
| 13 | `feat(finder): show data confidence labels` | `build_data.ts` derives `review_flags` into the public file (schema and data regenerated) and writes `resources.meta.json`; small edits to `cards.js`, `resources.js`, `csv.js`, `types.js`, `finder.css`; the resource page shows the source and data date |
| 14 | `feat(map): add ArcGIS reference layers` | New `core/pipeline/reference_layers.ts` (`npm run layers`) downloads the library, health facility and cooling site layers into committed `data/public/layers/*.geojson` plus an `index.json`; new `app/lib/layers.js`; small edits to `map.js` (`setLayer`), `finder.js` (toggle buttons on the map tab) |
| 15 | `test: add performance and accessibility checks` | New `app/audit.mjs` (`npm run audit`, Lighthouse on the three pages, also a CI job) and tests under `app/pages/__tests__/`, `app/lib/__tests__/fallbacks.test.mjs`, `app/components/__tests__/contrast.test.mjs`; small edits for the findings: `cards.js` ("Show on map" is a button), `finder.js`, `resource.js`, three colour rules in `finder.css`, and `dev-server.mjs` gzips text like Vercel |
| 16 | `chore: prepare for production and add team handoff` | Production readiness and the docs in one commit. Performance (P1): fonts self-hosted in `app/vendor/fonts/` (one line of `brand.css`), MapLibre and supabase-js loaded on demand by new `app/lib/vendor.js` (tags removed from `finder.html` and `resource.html`, `map.js` and `finder.js` call it), the partner logos in `app/brand/` resized from 1024 px to 176 px, `modulepreload` and font preloads in the pages, `finder.js` fetches the layer index alongside the data. Security headers and a content security policy in `vercel.json`, mirrored by `dev-server.mjs`. New `app/pages/privacy.html` and `app/components/page.css`, linked from the footers (one line in `index.html`). `LICENSE`. Python through uv: `pyproject.toml`, `.python-version`, `uv.lock` replace `ruff.toml`; `package.json` and `run.py` call `uv run`; no `__pycache__`. `.gitattributes` marks vendored and generated files. Tests for all of it; `README.md`, `app/README.md`, `app/vendor/README.md`, `core/README.md`, this file, and new `docs/handoff.md` |

**Not on this roadmap:** PRD Stage 2 and Section 9 (overlays, referral tracking, gap analysis, impact reporting, Apricot 360 integration). These need team decisions, new data or a backend.

## Requirements

"Commit" refers to the roadmap above. "Blocked" means it needs a team decision or data we do not have.

### Performance and devices

| ID | Requirement | Source | Today | How it is checked | Commit |
|---|---|---|---|---|---|
| P1 | First results within 2 s on a mid-range phone over 4G | PRD 10 | **Landing page within target, finder and resource page over it.** Lighthouse (mobile, simulated 4G, gzip) measures the largest contentful paint at 1.8 s on the landing page (was 3.8 s), 3.2 s on the finder (was 6.3 s) and 3.2 s on a resource page with a map (was 6.9 s); performance scores 100, 88 and 88. Commit 16 removed the Google Fonts request (fonts are now in `app/vendor/fonts/`, preloaded), loads MapLibre and supabase-js only when a map or the fallback is needed (`app/lib/vendor.js`), shrank the two partner logos from 470 KB to 36 KB, and preloads the finder's modules and data file. The finder now downloads 327 KB before its first screen, of which the data file is 158 KB. What remains is the data download plus the first render on a throttled phone CPU: the first question's tiles are built from the data, so the heading waits for it. The next steps would be to show the first question from a small, committed list of service types before the data arrives, or to split the file. A size budget on the app's own code, the fonts, the data and the on-demand libraries is tested | `npm run audit` reports it; size budget in `app/pages/__tests__/` | 15, 16; a follow-up for the finder |
| P2 | Resource data the finder loads is under 200 KB gzipped | PRD 10 | 928 KB uncompressed, all 67 columns. The 22 columns the finder uses come to about 634 KB, or 143 KB gzipped. | Test on the generated file | 8 |
| P3 | Usable at 360 px wide and up, by touch | PRD 10 | All three pages fit 360 px with no horizontal overflow (Lighthouse's 360 px screenshots and its viewport and tap-target audits pass). Touch is not yet tried on a phone | `npm run audit` at 360 px; a phone pass before merge | Done, 15 |

### Accessibility

| ID | Requirement | Source | Today | How it is checked | Commit |
|---|---|---|---|---|---|
| A1 | Meets WCAG 2.1 AA on the landing page, finder and resource page | PRD 10 | Lighthouse accessibility 100 and best practices 100 on all three pages. The first run found the orange "Phone / online" badge at 2.9:1, now 5.2:1; the contrast test also found muted counts on pressed tiles and the "Eligibility not stated" tag under 4.5:1, both fixed in `finder.css`. Automated checks cover the loaded screen only; a keyboard pass through the three questions and the results is still to do | `npm run audit` (CI), static checks in `app/pages/__tests__/`, colour pairs in `app/components/__tests__/contrast.test.mjs`; a manual keyboard pass | Done, 15 |
| A2 | All results are reachable without using the map | PRD 7.7, 10 | With the default filters the list holds every listed resource, in person or not, and every card links to its page; "Show on map" is now a button, so it is reachable by keyboard | `fallbacks.test.mjs` | Done, 15 |

### Privacy

| ID | Requirement | Source | Today | How it is checked | Commit |
|---|---|---|---|---|---|
| S1 | No participant-level data anywhere in the site or repo | PRD 7.6, 10 | None seen in the resource data | Review | All |
| S2 | No logging or analytics on searches, addresses or location | PRD 10 | No logging code in the finder, and the content security policy in `vercel.json` stops the pages from loading a script from, or sending data to, any host it does not name | Page test: no CDN tags and the policy names only the known hosts | 15, 16 |
| S3 | Review and source fields are not loaded by the finder | PRD 10 | They are, in the CSV | Test on the generated file | 8 |
| S4 | Third parties are listed, with what each receives | PRD 10 | [Third-party services](#third-party-services) below, and for visitors `/privacy.html`, which the team should check before launch | Page test: the privacy page names every host | 1, 16 |

### Data quality

| ID | Requirement | Source | Today | How it is checked | Commit |
|---|---|---|---|---|---|
| D1 | Every row passes a schema before reaching the site | PRD 8 | `core/pipeline/check_data.py` checks each pipeline output, `kavi_resources.csv` and the two files in `data/public/` against `core/schemas/`; runs in `npm run check` and as the pipeline's last stage | Done | 5, 8 |
| D2 | No resources are dropped between source and site | PRD 8 | `data/public/resources.public.json` holds every row the loader produces, and a test checks the count; the finder leaves out cross-references and blank rows at load time, as before | Done | 8 |
| D3 | Resource IDs are unique and do not change between builds | PRD 8 | `data/resource_ids.csv` is committed; `npm run ids` fails if it would change, and a test checks it is unique and reproduced from the data | Done | 7 |
| D4 | Unreviewed values are labelled for the user | PRD 10 | `review_flags` in the public file (services, audiences, eligibility, location, details, derived from the pipeline's own flags); cards say "Not yet checked: …" | Tests on each flag combination, in the build and on the card | Done, 13 |
| D5 | "Open to everyone" only appears when the source says so; otherwise it reads "eligibility not stated" | PRD 7.4 | The tag reads "Eligibility not stated" when `everyone_basis` is assumed (666 of 765 rows); filtering is unchanged | Tests on `everyone_basis` | Done, 13 |
| D6 | Each resource shows its source and data date | PRD 7.4, 10 | The resource page shows a source line from `data/public/resources.meta.json`, whose date moves only when the row files change | Tests on the source line and the meta file | Done, 13 |

### Reliability

| ID | Requirement | Source | Today | How it is checked | Commit |
|---|---|---|---|---|---|
| R1 | If map tiles fail, the list still works | PRD 10 | When MapLibre is missing, `createMap` returns null and the map tab says "The map could not load. The list still works." The list never depends on the map. Failed tiles leave a blank map with the pins still drawn, which is MapLibre's own behaviour | `fallbacks.test.mjs`; tiles blocked by hand before merge | Done, 15 |
| R2 | If address search fails, ZIP search and a clear message remain | PRD 10 | When GeoSearch is down, a ZIP still resolves from the data and `searchPlaces` reports the failure so the input can say so; an abort is not treated as a failure | `fallbacks.test.mjs` | Done, 15 |
| R3 | Core pages load no third-party script from a CDN | PRD 10 | MapLibre, supabase-js and the fonts come from `app/vendor/`, and the content security policy would block anything else. The reach prototype still uses CDNs, see the open decision on it | Page test: no CDN tags; `npm run audit` shows no console errors under the policy | 10, 16 |
| R4 | A merge keeps Vercel's current static behaviour | Decision 5 | Static today, with no `build` script. New in `vercel.json`: a `/privacy.html` rewrite and the security headers (decision 8). The dev server applies both, and the audit runs against it, but Vercel itself has not been tried | Team's preview deployment: open the four pages, the map, and check the response headers; see [handoff.md](handoff.md) | 16 |

### Maintainability

| ID | Requirement | Source | Today | How it is checked | Commit |
|---|---|---|---|---|---|
| M1 | Moved files keep their history | Decision 1 | n/a | `git log --follow` | 3 |
| M2 | One command runs all tests and checks, and CI runs it | PRD 10 | `npm run check`; CI runs it and the Lighthouse audit | GitHub Actions | 2, 15 |
| M3 | A data update needs no code changes and shows a readable diff | PRD 5.5 | Regenerate and import by hand | Generated change summary | 8 |
| M4 | A resource can be updated without an engineer | PRD 10 | Not possible | **Blocked:** needs a database and admin area (decision 2) | Later |

### PRD features

| ID | Requirement | Source | Today | Commit |
|---|---|---|---|---|
| F1 | Toggleable library, health facility and cooling center layers | PRD 7.1 | Libraries, Health facilities and Cooling sites buttons on the map tab; the files are committed copies of the ArcGIS layers, so the finder makes no run-time call to ArcGIS Online. The cooling layer is NYC Parks outdoor cooling sites, not indoor cooling centers, and is labelled so | Done | 14 |
| F2 | Shareable link for each resource | PRD 7.4, 7.6 | `/resource.html?id=<stable id>` shows one resource with its map and a copyable link; every card links to it | Done | 12 |
| F3 | Neighborhood search | PRD 7.2 | **Not working, needs a decision.** GeoSearch's autocomplete returns addresses and venues only: "Bushwick", "Crown Heights", "East New York" and "Jackson Heights" each come back as street addresses with those words in them, never as a neighborhood. To support it the finder would need its own list of neighborhood names with a centre point, such as the NTA centroids from NYC Open Data, matched before GeoSearch is called. Borough search already works | Tested in 15; team to decide |
| F4 | Hours, eligibility and referral details | PRD 7.4 | **Blocked:** not in the source data | Later |
| F5 | Catchment or precinct filter | PRD 7.2, 7.5 | **Blocked:** model undecided | Later |
| F6 | Organization type filter | PRD 7.5 | **Blocked:** no such field. `category` has 18 values but mixes services and audiences, such as "Formerly Incarcerated People" | Later |
| F7 | Report of rows that may need an address | PRD 8, 13 | All `mapped` rows have coordinates. Of the 325 rows without them, 34 are `mailing_address` or `outside_nyc` and may need checking; the rest are web-only, hotline, cross-reference or the one blank row. `build:data` writes those 34 to `data/review/needs_address.csv` | Done, 8 |
| F8 | Schema leaves room for hours, eligibility and referral fields | PRD 7.4, 8 | `hours`, `eligibility` and `referral_process` are planned columns in `core/schemas/kavi_resources.json`: checked when present, not required | 5 |

## Third-party services

| Service | Used for | What it receives |
|---|---|---|
| NYC GeoSearch (`geosearch.planninglabs.nyc`) | Address lookup | Typed address text and the visitor's IP address |
| OpenFreeMap (`tiles.openfreemap.org`) | Map background | Requested map areas and the visitor's IP address |
| Vercel | Hosting | The usual request logs, including the visitor's IP address |
| Supabase (`xwpuphhocwstfgbjreeg.supabase.co`) | Fallback data source only | The visitor's IP address, when the fallback runs |

Until commit 16 the pages also loaded fonts from Google Fonts and, until commit 10, libraries from jsDelivr and unpkg; both now come from `app/vendor/`. The content security policy in `vercel.json` allows only the hosts in this table, so adding a service means adding it there, to this table and to `/privacy.html`.

Typed addresses go straight from the browser to GeoSearch. The team should decide whether that is acceptable for public use. `/privacy.html` says so to visitors; it was written from the code, not reviewed by KAVI, and names `info@kavibrooklyn.org` as the contact.
