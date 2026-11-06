# /// script
# requires-python = ">=3.10"
# ///
"""Broad OpenStreetMap extract of named service-like places in New York City.

Data: (c) OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright).
Anything derived from data/supplement/osm.csv must keep this credit.

One Overpass request. Named features inside the City of New York (relation 175905) with
office=*, healthcare=*, government=*, or an amenity from AMENITIES. It keeps libraries and
general clinics/hospitals, and every tag (tags_json), so later stages can mine them.

Borough: the query walks the five borough boundaries (admin_level=7), printing each borough's area before its members, so the borough of a feature is the
last area seen. A final pass over the whole city catches features that sit in no borough
polygon (e.g. offshore or on a boundary); those get the borough of the nearest feature that
has one, and the script lists them on stderr.

Writes data/supplement/osm.csv in the common source schema shared with other sources
(source, source_id, name, lat, lon, borough, primary_type, address, house_number, street, zip, phone, website,
opening_hours, operator, last_edit, url, bin, raw_json), sorted by source_id so diffs are stable. raw_json holds
every OSM tag (alt_name, brand, short_name, ... are read from it by match_nypl.py) plus osm_version.
`bin` is nycdoitt:bin (the NYC building id imported with building outlines).

    python3 core/supplement/extract_all.py [--from-json raw.json]   (--from-json skips the network)
    python3 core/supplement/extract_all.py --from-legacy-csv old_osm_extract.csv   (convert the first-stage csv)
"""

import argparse
import csv
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "supplement" / "osm.csv"

ENDPOINT = "https://overpass-api.de/api/interpreter"
USER_AGENT = "KAVI-datathon resource map (github.com/dssg-nyc/KAVI-datathon)"
NYC_AREA_ID = 3_600_000_000 + 175905
TIMEOUT_S = 300
RETRY_STATUS = {429, 502, 503, 504}
MAX_ATTEMPTS = 5
FIRST_WAIT_S = 15

AMENITIES = (
    "social_facility community_centre social_centre clinic doctors hospital library college "
    "university courthouse townhall food_bank childcare kindergarten public_building training "
    "arts_centre shelter prep_school language_school"
).split()
# Added after probing 333 NYPL points with an unfiltered name query (probe_overpass.py around, probe_analyze.py): the only
# excluded tags that held a same-site match and stayed small. place_of_worship (2,728 named features for 2 hits),
# amenity=cafe (2,622), landuse=residential (493), building (11,733) and shop=charity (34) were left out.
EXTRA_AMENITIES = ["prison"]
EXTRA_TOURISM = ["museum"]
# key to inspect, in priority order, for primary_tag
PRIMARY_KEYS = ("amenity", "office", "healthcare", "government", "tourism")

COLUMNS = ["source", "source_id", "name", "lat", "lon", "borough", "primary_type", "address", "house_number",
           "street", "zip", "phone", "website", "opening_hours", "operator", "last_edit", "url", "bin", "raw_json"]


def selectors(area):
    amen = "|".join(AMENITIES + EXTRA_AMENITIES)
    tour = "|".join(EXTRA_TOURISM)
    return (f'    nwr["name"]["office"](area.{area});\n'
            f'    nwr["name"]["healthcare"](area.{area});\n'
            f'    nwr["name"]["amenity"~"^({amen})$"](area.{area});\n'
            f'    nwr["name"]["government"](area.{area});\n'
            f'    nwr["name"]["tourism"~"^({tour})$"](area.{area});\n')


QUERY = f"""[out:json][timeout:{TIMEOUT_S}];
area(id:{NYC_AREA_ID})->.nyc;
rel(area.nyc)["boundary"="administrative"]["admin_level"="7"];
map_to_area;
foreach->.b(
  .b out tags;
  (
{selectors("b")}  );
  out center meta;
);
(
{selectors("nyc")});
out center meta;
"""


def fetch():
    wait = FIRST_WAIT_S
    for attempt in range(MAX_ATTEMPTS):
        req = urllib.request.Request(ENDPOINT, data=urllib.parse.urlencode({"data": QUERY}).encode(),
                                     headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S + 60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUS or attempt == MAX_ATTEMPTS - 1:
                raise SystemExit(f"Overpass HTTP {e.code}: {e.read()[:500]!r}")
            print(f"Overpass busy (HTTP {e.code}), retrying in {wait}s", file=sys.stderr)
        time.sleep(wait)
        wait *= 2
    raise SystemExit("Overpass: out of retries")


def primary_tag(t):
    for k in PRIMARY_KEYS:
        v = t.get(k)
        if v and (k != "amenity" or v in AMENITIES + EXTRA_AMENITIES) and (k != "tourism" or v in EXTRA_TOURISM):
            return f"{k}={v}"
    return ""


def address(t):
    street = " ".join(x for x in (t.get("addr:housenumber"), t.get("addr:street")) if x)
    return ", ".join(x for x in (street, t.get("addr:city"), t.get("addr:postcode")) if x)


def dist2(a, b):
    return (a[0] - b[0]) ** 2 + ((a[1] - b[1]) * math.cos(math.radians(a[0]))) ** 2


def to_row(oid, lat, lon, borough, t, last_edit, version):
    """One OSM feature in the common source schema."""
    return {
        "source": "osm", "source_id": oid, "name": t["name"], "lat": lat, "lon": lon, "borough": borough,
        "primary_type": primary_tag(t), "address": address(t), "house_number": t.get("addr:housenumber", ""),
        "street": t.get("addr:street", ""), "zip": t.get("addr:postcode", ""),
        "phone": t.get("phone") or t.get("contact:phone") or "",
        "website": t.get("website") or t.get("contact:website") or "",
        "opening_hours": t.get("opening_hours", ""), "operator": t.get("operator", ""),
        "last_edit": last_edit, "url": f"https://www.openstreetmap.org/{oid}",
        "bin": t.get("nycdoitt:bin") or t.get("bin") or "",
        "raw_json": json.dumps({**t, "osm_version": version}, ensure_ascii=False, sort_keys=True),
    }


def from_legacy_csv(path):
    """Convert the first-stage data/osm/osm_extract.csv (tags_json column) without touching the network."""
    rows = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows[r["osm_id"]] = to_row(r["osm_id"], r["lat"], r["lon"], r["borough"], json.loads(r["tags_json"]),
                                       r["last_edit"], r["osm_version"])
    return rows


def build_rows(payload):
    rows, borough = {}, ""
    for el in payload.get("elements", []):
        t = el.get("tags", {})
        if el["type"] == "area":
            borough = t.get("name", "")
            continue
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        if lat is None or lon is None or not t.get("name"):
            continue
        oid = f"{el['type']}/{el['id']}"
        if oid in rows:
            continue  # seen in a borough pass already (or on a shared boundary)
        rows[oid] = to_row(oid, lat, lon, borough, t, el.get("timestamp", "")[:10], el.get("version", ""))
    return rows


def fill_missing_boroughs(rows):
    """Final-pass features have borough ''. Give them the nearest labelled feature's borough."""
    labelled = [r for r in rows.values() if r["borough"]]
    gaps = [r for r in rows.values() if not r["borough"]]
    for r in gaps:
        near = min(labelled, key=lambda o: dist2((r["lat"], r["lon"]), (o["lat"], o["lon"])))
        r["borough"] = near["borough"]
    return gaps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-json", help="parse a saved Overpass response instead of querying")
    ap.add_argument("--from-legacy-csv", help="convert the first-stage osm_extract.csv instead of querying")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    payload = {}
    if args.from_legacy_csv:
        rows = from_legacy_csv(args.from_legacy_csv)
    else:
        payload = json.load(open(args.from_json)) if args.from_json else fetch()
        if "error" in payload.get("remark", "").lower():
            raise SystemExit(f"Overpass aborted the query: {payload['remark']}")
        rows = build_rows(payload)
    gaps = fill_missing_boroughs(rows)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        for oid in sorted(rows):
            w.writerow(rows[oid])
    print(f"{len(rows)} features -> {out} (osm base {payload.get('osm3s', {}).get('timestamp_osm_base', '?')})")
    by_b = {}
    for r in rows.values():
        by_b[r["borough"]] = by_b.get(r["borough"], 0) + 1
    print("by borough:", dict(sorted(by_b.items())))
    print(f"{len(gaps)} features were in no borough polygon; borough filled from nearest feature")
    for r in gaps:
        print(f"  {r['source_id']} {r['name']} -> {r['borough']}", file=sys.stderr)


if __name__ == "__main__":
    main()
