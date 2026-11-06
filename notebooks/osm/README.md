# Supplementing the NYPL guide

The NYPL Connections Guide PDF is human-verified, so it's our source of truth. This folder tests whether OpenStreetMap (OSM)
and similar public lists add anything to it: places it lacks, especially outside Manhattan, and details missing from the
places it has.

This is exploratory. Nothing here feeds the finder, `data/kavi_resources.csv`, `data/public/` or Supabase. The scripts that
build the data are in [`pipeline/supplement/`](../../pipeline/supplement/README.md), with how to run them, review the list and
what is committed. This folder has the notebook, the review map and two one-off probes.

For the results, read [`osm_eda.ipynb`](osm_eda.ipynb). In short:

- **Matching:** the other sources find 201 of the guide's 400 mapped rows at the same site, and OSM adds 23 more.
- **Gaps:** of 2,596 map cells where a service has no guide site nearby, other sources reach 1,559 and OSM adds 68. Most of the
  places they propose are health and mental health. Brooklyn's widest gaps (disability, reentry, food) barely move.
- **Ranking:** the relevance score does little better than a baseline against the guide (AUC 0.794 vs 0.783), and worse
  than one against other service lists (0.487 vs 0.788). Treat it as a filter for human review, not as a measure of relevance.
- **Website crawl:** site text doesn't help judge relevance, because nearly every site mentions a service type. It's more useful
  for selective details and upcoming events, which still need checking.

## See it on a map

```sh
python3 pipeline/supplement/build_map_data.py    # writes the ignored data/supplement/map_data.geojson
python3 -m http.server 8000 --bind 127.0.0.1     # from the repo root
# open http://localhost:8000/notebooks/osm/map.html
```

The map shows mapped guide sites and places awaiting review, with the list below it. Filter by status, source, area of support,
borough or what a source adds. Click a point or a row to split the view into a zoomed map and the organization's card: its
description and labels, contact details, upcoming events, then what each source would add or why it is up for review.

The switch above the list changes both the list and the map from organizations to events: upcoming events found on those places'
websites, soonest first, then events that recur. Events that match no service are hidden until you tick the box above the list,
because most are concerts and fairs, though that check also misses some real programs.

| Status | Meaning |
|---|---|
| Matched | A source lists this guide site, or the guide's own website had something to add. |
| Needs review | Not in the guide, and above the relevance threshold. A person decides whether it belongs. |
| In the guide, nothing matched | No source lists this site. Off by default. |

Survivor services and shelters awaiting review are left off the map. ENDGBV listings with confidential addresses never link to a
site. Crawled hours, languages and events are unverified, so check the link before relying on one. Events that have passed
drop off when the page opens, and the list shrinks until the crawl runs again. `build_map_data.py` only reads the saved
crawl output. `crawl_sites.py` sends real requests to the organizations' websites, so only run it on purpose.

## Probes

`probe_overpass.py` and `probe_analyze.py` are one-off checks of whether our OSM tag filter misses guide sites. Their inputs are in
`data/osm/`, along with `nypl_aliases.csv`, the name aliases used for matching.
