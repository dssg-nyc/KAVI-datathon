# Supplement: other sources beside the guide

This is a side branch of the pipeline. It collects OpenStreetMap (OSM) and other public lists of service locations, matches
them to the NYPL Connections Guide, scores the places the guide lacks for human review, and reads organizations' own websites
for details and events. The guide is human-verified, so it stays the source of truth.

Nothing here writes to the resource table: not `data/kavi_resources.csv`, `data/public/` or Supabase. It is not a stage of
`run.py`, because most steps need the network and their output changes from day to day. Its output is in `data/supplement/`.
The findings are in [`notebooks/osm/osm_eda.ipynb`](../../notebooks/osm/osm_eda.ipynb), and the review map is
[`notebooks/osm/map.html`](../../notebooks/osm/map.html).

## Sources

Each source is fetched, cut to NYC and normalized to `data/supplement/<source>.csv`. "Site-level" counts the guide's 400 mapped rows
that the matcher placed at the same site (the organization itself, or the building hosting its program). These are accepted matches
with no gold labels, so they are not accuracy. Counts are from the 2026-11-05 fetch.

| Source | Publisher and dataset | What it adds | NYC rows | Guide rows matched at site level | Terms |
|---|---|---|---|---|---|
| `osm` | OpenStreetMap, pulled broadly (no type filter) | Any mapped place; sometimes hours, email, wheelchair access | 9,166 | 74 | ODbL: attribution, maybe share-alike |
| `facdb` | NYC DCP Facilities Database | Every city-listed facility; partly copies OMH, DYCD, DOHMH and Workforce1 | 34,305 | 190 | NYC Open Data (not read) |
| `irs_eo` | IRS Exempt Organizations Business Master File, NY | Registered nonprofits, usually at a mailing address, so organization matches only | 51,791 | 0 (285 by organization) | None stated |
| `omh` | NYS Office of Mental Health, local programs | Mental health programs | 1,931 | 52 | OPEN-NY: reuse allowed |
| `doh_childcare` | NYC DOHMH active child care programs | Licensed childcare | 2,755 | 5 | NYC Open Data (not read) |
| `dycd` | NYC DYCD program sites | Youth and community programs | 2,660 | 47 | NYC Open Data (not read) |
| `endgbv` | NYC ENDGBV resource directory | Domestic and gender-based violence services; some locations confidential | 286 | 9 | NYC Open Data (not read) |
| `workforce1` | NYC SBS Workforce1 centers | Job centers | 41 | 0 | NYC Open Data (not read) |
| `hrsa` | HRSA health center service delivery sites | Community health centers | 491 | 14 | "Usage limitations: None" |
| `cms_otp` | CMS opioid treatment program providers | Methadone and other OTPs | 51 | 6 | US government work |

Not used: OASAS and SAMHSA (search tools only, no bulk list; CMS's list stands in for opioid treatment), Findhelp and 211.
The full terms notes are at the top of [`fetch_sources.py`](fetch_sources.py).

## What we found

From [`notebooks/osm/osm_eda.ipynb`](../../notebooks/osm/osm_eda.ipynb), run on 2026-11-05 and 2026-11-06. Every place outside the
guide is unreviewed, so the numbers about gaps are upper limits.

- **The guide is thin outside Manhattan.** Per 100,000 residents it has 9.4 locations in Manhattan, 3.7 in the Bronx, 3.0 in Staten
  Island, 2.5 in Brooklyn and 1.5 in Queens. 71% of neighbourhood cells citywide are over 800 m from any guide site. Brooklyn's widest
  service gaps are Disability Services (99% of cells out of range), Reentry Support (92%) and Food (89%).
- **OSM matches part of the guide.** 74 of 400 mapped rows match at site level (61 before matching used phone, website, address,
  aliases and building IDs). For 142 rows OSM has nothing named nearby, so no matcher can help.
- **OSM must be pulled broadly.** The old type filter would have kept 19 of those 74 matches. Libraries, associations, government
  offices, colleges and clinics host many guide programs.
- **OSM adds a few fields to guide rows, not contact details.** Across 42 same-site rows it adds opening hours (16), email (7),
  operator (6), who it serves (6) and wheelchair access (4). It fills no missing phone or website.
- **The government lists add more than OSM.** Without OSM they find 201 of 400 guide rows at site level, and OSM adds 23. Their
  places reach 1,559 of 2,596 gap cells; OSM alone adds 68.
- **They don't close the widest gaps.** Most candidate places are health providers (1,138 of 1,769 proposed service types), so
  Brooklyn's Disability Services, Reentry Support and Food gaps barely move. That needs a different source, such as a food pantry list.
- **The relevance score sorts the list but does not show relevance.** AUC 0.794 against the guide, barely above a baseline of
  0.783 from source and type alone.
- **The website crawl is useful for checking the guide, not for finding services.** Nearly every live site matches some service
  type, so it cannot judge relevance. It does find hours and referral wording, and the guide rows whose site has moved, shows another
  address or mentions closure (`guide_checks.csv`). Event extraction was fully right for about 9 of 16 events checked.

## Using it

Nothing here is ready to go on the site without a person checking it. In order of how ready it is:

1. **Check the guide with `guide_checks.csv`.** 306 rows, each a guide entry, a flag and a link: 41 show a different address on the
   organization's own site, 4 closure wording, 4 an unreachable or moved website, and 257 list details the guide has no column for
   (hours, email, languages, eligibility, referral). Corrections go to the guide itself, so they reach the site through the normal
   pipeline.
2. **Review the first batch of new places.** `review_queue.csv` holds 706 places from OSM, OMH, HRSA and CMS, all `pending`. The 214 in
   Queens and Brooklyn with priority 1 (no guide site nearby) are the suggested first batch. A reviewer sets `hitl_review` and `review_note`; the team
   still has to agree what the verdict values are. Those verdicts are the first real relevance labels, and would show whether the
   score and the sources are worth keeping.
3. **Decide how a confirmed place reaches the site.** Today the only route is adding it to the guide. A reviewed-additions file read
   by `core/pipeline/` is possible, but it would need its own provenance and review flag, and a licence check first (below).
4. **Add OSM fields to matched guide rows.** Opening hours and wheelchair access on same-site matches are the most useful. They need
   ODbL attribution wherever shown, and the guide has no hours column yet.

## Run it

Run from the repo root with Python 3.10 or later. The scripts use only the standard library. Steps 1–3 and 7 send requests
over the network; the rest only read files in `data/`.

```sh
python3 core/supplement/extract_all.py                      # 1. OSM snapshot: data/supplement/osm.csv
python3 core/supplement/fetch_sources.py                    # 2. the other sources; name some to fetch only those
python3 core/supplement/fetch_bins.py                       # 3. building IDs for the guide's addresses (cached)
python3 core/supplement/match_nypl.py --source osm          # 4. match to the guide; repeat for each source
python3 core/supplement/coverage_report.py --source osm     # 5. coverage by source; repeat for each source
python3 core/supplement/build_supplement.py                 # 6. one table of every place, with score and review column
python3 core/supplement/crawl_sites.py --cache <dir>        # 7. optional website crawl; --list makes no requests
python3 core/supplement/review_recommendations.py           # 8. the review list; --eval also writes the ranker results
python3 core/supplement/build_map_data.py                   # 9. data for the review map in notebooks/osm/
```

Step 7 sends real requests to the organizations' own websites (robots.txt obeyed, one request per 2 seconds per site), so
run it only on purpose. Its cache directory must be new, or a cache from an earlier run, which it reads instead of fetching
again. Step 9 and everything after step 7 only read its saved output.

Then re-run `notebooks/osm/osm_eda.ipynb`. Tests, each runnable on its own:

```sh
for f in core/supplement/__tests__/*.test.py; do uv run "$f"; done
```

A clean clone skips the tests that need local data files.

## Review the list

Reviewers fill in `hitl_review` and `review_note` in `data/supplement/review_queue.csv`. Re-running the scripts keeps those entries,
and a verdict on a row applies to every listing of that place (`member_keys`). Rows are sorted with the sparsest areas first:

1. `1_no_guide_site_nearby`: no guide site within 800 m.
2. `2_service_missing_nearby`: guide sites are nearby, but none offers a service proposed here.
3. `3_already_covered`: nearby guide sites already offer it, or no service is proposed.
4. `4_no_location`: the source gives no coordinates, so someone has to locate the place first.

`guide_checks.csv` is the freshness check the crawl feeds. It lists guide rows whose own website is unreachable or has moved,
shows another address or closure wording, or lists details the guide has no column for (phone if blank, email, hours,
languages, eligibility, referral). Each row is a flag, the field names, a link and the crawl date, never page text. These are
prompts to check the guide, not corrections; the values sit in the ignored `crawl_pilot.csv` and on the review map.

## What's committed

Only these files in `data/supplement/` are committed. Everything else there is ignored, and the pipeline regenerates it.

| File | What it is |
|---|---|
| `osm.csv`, `matches_osm.csv`, `parent_orgs_osm.csv` | The OSM snapshot and match results the notebook reads. |
| `review_queue.csv` | The review list: OSM, OMH, HRSA and CMS places, none sensitive. |
| `guide_checks.csv` | Guide rows to re-check. |

`review_queue_local.csv` stays local, and its `local_reason` column says why:

- `sensitive`: survivor services and shelters, even with a public address.
- `private_practice`: places only OSM lists under a practice tag, which may name a person.
- `nyc_open_data_terms`: NYC Open Data rows. We haven't been able to read the full Terms of Use.

## Limits and licences

- **Unverified data.** OSM and the other lists record what a place is and where it is, rarely who it serves or how to get referred.
  A match confirms a location, not that a service still runs.
- **Uneven coverage.** OSM depends on where volunteers have mapped, so a thin area may reflect the mapping rather than a lack of services.
- **Sources overlap.** The NYC Facilities Database partly copies OMH, DYCD, DOH and Workforce1, so it isn't independent confirmation.
- **Confidential addresses.** ENDGBV programs with `display_physical_address=No` must stay blank everywhere, with no location-revealing link.
- **OSM licence.** OSM data is under [ODbL](https://opendatacommons.org/licenses/odbl/). Credit "© OpenStreetMap contributors" wherever
  it's shown. Check whether share-alike applies before publishing a table that combines OSM with other sources.
- **Other licences.** See the notes at the top of `fetch_sources.py`.
