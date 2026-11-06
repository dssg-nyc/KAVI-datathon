# Supplement: other sources beside the guide

This is a side branch of the pipeline. It collects OpenStreetMap (OSM) and other public lists of service locations, matches
them to the NYPL Connections Guide, scores the places the guide lacks for human review, and reads organizations' own websites
for details and events. The guide is human-verified, so it stays the source of truth.

Nothing here writes to the resource table: not `data/kavi_resources.csv`, `data/public/` or Supabase. It is not a stage of
`run.py`, because most steps need the network and their output changes from day to day. Its output is in `data/supplement/`.
The findings are in [`notebooks/osm/osm_eda.ipynb`](../../notebooks/osm/osm_eda.ipynb), and the review map is
[`notebooks/osm/map.html`](../../notebooks/osm/map.html).

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
