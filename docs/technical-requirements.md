# Technical requirements and roadmap

**Status: proposed, for team review.** [PRD.md](../PRD.md) says what to build. This covers where the code stands, how it should change, and the order of work. All targets are proposals, and none has been agreed with KAVI.

## Where things stand

The site is static HTML, CSS and browser JS with no build step. The website is in `app/`, the data pipeline is in `pipeline/`, one folder per stage, and the notebooks, one-off analysis and the OSM layer are in `notebooks/`, and `vercel.json` maps the public URLs to the pages.

- **Finder:** `app/pages/finder.html`, `app/components/` and `app/lib/`. `app/config.js` sets `RESOURCES_CSV`, so the browser downloads `data/kavi_resources.csv`, with Supabase as the fallback data source.
- **Data pipeline:** Python and notebooks clean and enrich the Connections Guide, TS scripts geocode it, and `pipeline/5_load/load_supabase.mjs` loads it into Supabase.
- **Tests:** they exist in JS, TS and Python, but there is no CI and no `npm test`.
- **PRD coverage:** map, service, keyword, address, ZIP and borough search, and hotlines are built. The gaps are listed under [PRD features](#prd-features).

### Who built what

| Area | Files | Base authors |
|---|---|---|
| Finder app and map | `app/pages/finder.js`, `app/components/cards.js`, `map.js`, `place-input.js`, `app/lib/filter.js`, `geo.js`, `resources.js` | Akai, Franziska |
| CSV loader | `app/lib/csv.js`, `preview.js` | Cursor Agent (jyr-ai's PRs), Franziska |
| Landing page and brand | `app/pages/index.html`, `app/brand/` | Cursor Agent (jyr-ai's PRs), Akai |
| Reach prototype | `app/prototypes/reach/` | Akai |
| Cleaning and audiences | `pipeline/1_clean/clean_guide.py`, `pipeline/4_audiences/tag_audiences.py`, `notebooks/` | Franziska |
| PDF extension | `pipeline/2_pdf/extract_pdf.py`, `match_pdf.py`, `extend_with_pdf.py` | Akai, Rita |
| Geocoding | `pipeline/3_geocode/geocode.ts` | Rita, Akai |
| OSM layer | `notebooks/osm/` | Ramsey |
| Database import | `pipeline/5_load/load_supabase.mjs`, `supabase/` | Akai, Franziska |

## Design decisions

1. **Build on the existing code.** Move files with `git mv`, edit them in place, and add new files for new behaviour. Renames get their own commits so history follows the files.
2. **Keep the site static for now.** A Next.js port with Postgres would replace most of the finder and need a database and hosting changes. The cost is that updating a resource still means a data file change and a PR, until the team adds a database and admin area.
3. **Commit generated data.** `npm run build:data` joins and validates the source files, then writes `data/public/resources.public.json` for the finder and `resources.provenance.json` for review and source fields. Filtering stays in the browser, because 765 rows do not need a search API.
4. **Python, JS and TS all stay.** Python handles cleaning and analysis, JS handles the browser, and new Node tooling is TS. Scripts in different languages connect only through data files checked against a schema.
5. **Keep Vercel's behaviour unchanged.** To our understanding of Vercel's default for projects with no framework, that means no `build` script in `package.json` and no top-level `public/` or `api/` directory. The HTML pages moved to `app/`, so `vercel.json` rewrites keep the public URLs and `.vercelignore` keeps internal files off the site. The team should confirm this on a preview deployment before merging.
6. **Take stable IDs from the source data.** The database `id` changes on each `import --replace`, so IDs come from `resource_id`, with a suffix where it repeats, such as the NEON sites. The mapping is committed.
7. **Leave Supabase in place.** The refactor does not change `supabase/` or run the import against the database, and the finder's fallback stays. Retiring it is the team's decision.

## Open decisions for the team

| Decision | Why it matters | Assumption until decided |
|---|---|---|
| Public or partner-only? (PRD 13) | A static site cannot restrict access | Public, per PRD 7.6 |
| Who owns data updates at KAVI? (PRD 13) | Without an owner the data goes stale | Unassigned |
| Which geography model: catchment, precinct or neighborhood? (PRD 13) | Blocks the geography filter in PRD 7.5 | Not built |
| Is an organization type filter useful? (PRD 7.5) | The data has no organization type field | Not built |
| Future of Supabase | Two data paths remain until this is decided | Fallback stays |
| Is the reach prototype in scope? | It is not in the PRD and is marked throwaway | Stays in the repo, unlinked |
| When can audience tags be used with clients? | [audience_matching.md](audience_matching.md) calls them demo only | Labelled in the UI |
| Repo license | The repo has none, which limits reuse by partners | Team to choose |

## Roadmap

One PR, reviewed commit by commit. Each commit should leave the checks passing and the site working. The exception is commit 3, a pure rename so history follows the files: the site and tests work again at commit 4.

| # | Commit | Touches existing code? |
|---|---|---|
| 1 | `docs: add technical requirements and roadmap` | No |
| 2 | `chore: add type checks, lint and CI for new code` | `package.json` only |
| 3 | `chore: reorganize into app/, core/ and docs/` | Renames only |
| 4 | `chore: fix paths after the reorganization` | Paths only, plus new `vercel.json` and `.vercelignore` |
| 4a | `refactor(pipeline): rewrite the cleaning stage in Python and add a single pipeline command` | `package.json` and READMEs; `clean_guide.py` is new and reproduces the notebook's output |
| 5 | `feat(data): add schemas for resource data` | No |
| 6 | `refactor(data): export the import mapping` | `load_supabase.mjs`, in place, same output |
| 7 | `feat(data): add stable resource IDs` | No |
| 8 | `feat(data): generate public and provenance data files` | No |
| 9 | `feat(finder): load the generated public data file` | `preview.js`, `csv.js`, `app/config.js`, small edits |
| 10 | `chore(finder): vendor MapLibre instead of loading it from a CDN` | HTML script tags |
| 11 | `chore(landing): unlink the reach prototype` | One link in `index.html` |
| 12 | `feat(finder): add shareable resource pages` | New `app/pages/resource.html`, small edits to `cards.js` |
| 13 | `feat(finder): show data confidence labels` | Small edits to `cards.js`, `resources.js` |
| 14 | `feat(map): add ArcGIS reference layers` | Small edits to `map.js`, `finder.js` |
| 15 | `test: add performance and accessibility checks` | No |
| 16 | `docs: update README and add team handoff` | `README.md` |

**Not on this roadmap:** PRD Stage 2 and Section 9 (overlays, referral tracking, gap analysis, impact reporting, Apricot 360 integration). These need team decisions, new data or a backend.

## Requirements

"Commit" refers to the roadmap above. "Blocked" means it needs a team decision or data we do not have.

### Performance and devices

| ID | Requirement | Source | Today | How it is checked | Commit |
|---|---|---|---|---|---|
| P1 | First results within 2 s on a mid-range phone over 4G | PRD 10 | Not measured | Lighthouse in CI | 15 |
| P2 | Resource data the finder loads is under 200 KB gzipped | PRD 10 | 928 KB uncompressed, all 67 columns. The 22 columns the finder uses come to about 634 KB, or 143 KB gzipped. | Test on the generated file | 8 |
| P3 | Usable at 360 px wide and up, by touch | PRD 10 | Not measured | Browser pass before merge | 15 |

### Accessibility

| ID | Requirement | Source | Today | How it is checked | Commit |
|---|---|---|---|---|---|
| A1 | Meets WCAG 2.1 AA on the landing page, finder and resource page | PRD 10 | Not measured | Automated checks plus a manual keyboard pass | 15 |
| A2 | All results are reachable without using the map | PRD 7.7, 10 | List view exists | Manual keyboard pass | 15 |

### Privacy

| ID | Requirement | Source | Today | How it is checked | Commit |
|---|---|---|---|---|---|
| S1 | No participant-level data anywhere in the site or repo | PRD 7.6, 10 | None seen in the resource data | Review | All |
| S2 | No logging or analytics on searches, addresses or location | PRD 10 | No logging code seen in the finder | Review; test that no analytics scripts are added | 15 |
| S3 | Review and source fields are not loaded by the finder | PRD 10 | They are, in the CSV | Test on the generated file | 8 |
| S4 | Third parties are listed, with what each receives | PRD 10 | Not documented | See [Third-party services](#third-party-services) | 1 |

### Data quality

| ID | Requirement | Source | Today | How it is checked | Commit |
|---|---|---|---|---|---|
| D1 | Every row passes a schema before reaching the site | PRD 8 | Partial report in `csv.js` | `build:data` fails on invalid rows | 5, 8 |
| D2 | No resources are dropped between source and site | PRD 8 | Manual | Row-count test, with intentional exclusions listed | 8 |
| D3 | Resource IDs are unique and do not change between builds | PRD 8 | Database `id` changes on each replace | Test on the committed mapping | 7 |
| D4 | Unreviewed values are labelled for the user | PRD 10 | Review flags are not shown | Tests on each flag combination | 13 |
| D5 | "Open to everyone" only appears when the source says so; otherwise it reads "eligibility not stated" | PRD 7.4 | Assumed values look like stated ones | Tests on `everyone_basis` | 13 |
| D6 | Each resource shows its source and data date | PRD 7.4, 10 | Not shown | Test on the resource page | 12 |

### Reliability

| ID | Requirement | Source | Today | How it is checked | Commit |
|---|---|---|---|---|---|
| R1 | If map tiles fail, the list still works | PRD 10 | Not tested | Manual test with tiles blocked | 15 |
| R2 | If address search fails, ZIP search and a clear message remain | PRD 10 | Implemented in `geo.js` and `place-input.js` | Existing behaviour, manual test | 15 |
| R3 | Core pages load no third-party script from a CDN | PRD 10 | MapLibre and Supabase come from CDNs | Review of the HTML | 10 |
| R4 | A merge keeps Vercel's current static behaviour | Decision 5 | Static today | Team's preview deployment | 16 |

R3 is only partly met while the Supabase fallback stays, because that library still loads from a CDN (decision 7).

### Maintainability

| ID | Requirement | Source | Today | How it is checked | Commit |
|---|---|---|---|---|---|
| M1 | Moved files keep their history | Decision 1 | n/a | `git log --follow` | 3 |
| M2 | One command runs all tests and checks, and CI runs it | PRD 10 | No CI or `npm test` | GitHub Actions | 2 |
| M3 | A data update needs no code changes and shows a readable diff | PRD 5.5 | Regenerate and import by hand | Generated change summary | 8 |
| M4 | A resource can be updated without an engineer | PRD 10 | Not possible | **Blocked:** needs a database and admin area (decision 2) | Later |

### PRD features

| ID | Requirement | Source | Today | Commit |
|---|---|---|---|---|
| F1 | Toggleable library, health facility and cooling center layers | PRD 7.1 | Not in the finder | 14 |
| F2 | Shareable link for each resource | PRD 7.4, 7.6 | Not available | 12 |
| F3 | Neighborhood search | PRD 7.2 | Not tested | 15 (test), then decide |
| F4 | Hours, eligibility and referral details | PRD 7.4 | **Blocked:** not in the source data | Later |
| F5 | Catchment or precinct filter | PRD 7.2, 7.5 | **Blocked:** model undecided | Later |
| F6 | Organization type filter | PRD 7.5 | **Blocked:** no such field. `category` has 18 values but mixes services and audiences, such as "Formerly Incarcerated People" | Later |
| F7 | Report of rows that may need an address | PRD 8, 13 | All `mapped` rows have coordinates. Of the 325 rows without them, 34 are `mailing_address` or `outside_nyc` and may need checking; the rest are web-only, hotline, cross-reference or the one blank row | 8 |
| F8 | Schema leaves room for hours, eligibility and referral fields | PRD 7.4, 8 | Not in the current data | 5 |

## Third-party services

| Service | Used for | What it receives |
|---|---|---|
| NYC GeoSearch (`geosearch.planninglabs.nyc`) | Address lookup | Typed address text and the visitor's IP address |
| OpenFreeMap (`tiles.openfreemap.org`) | Map background | Requested map areas and the visitor's IP address |
| jsDelivr and unpkg | Library files, until commit 10 | The visitor's IP address |
| Supabase | Fallback data source only | The visitor's IP address, when the fallback runs |

Typed addresses go straight from the browser to GeoSearch. The team should decide whether that is acceptable for public use. The site has no privacy notice yet, so this should go in one.
