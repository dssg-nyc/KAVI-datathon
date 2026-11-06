# /// script
# requires-python = ">=3.10"
# ///
"""Gentle Overpass probes for the "does our tag filter exclude NYPL sites?" question.

Data: (c) OpenStreetMap contributors, ODbL 1.0.

  around  every named feature (any tag except highways and transit) within RADIUS_M of each mapped
          NYPL point, in batches of BATCH points (one `around` statement per point; NOT one
          multi-coordinate `around`, which Overpass reads as a polyline).
  names   features whose name/operator/brand/alt_name matches a regex of distinctive NYPL parent org names.

One request at a time, exponential backoff, each response cached as JSON in --cache so reruns are free.
Analysis of the cached responses lives in probe_analyze.py.

    python3 notebooks/osm/probe_overpass.py around|names --cache DIR [--endpoint URL]
"""

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NYPL_CSV = ROOT / "data" / "kavi_resources.csv"
ENDPOINT = "https://overpass-api.de/api/interpreter"
USER_AGENT = "KAVI-datathon resource map (github.com/dssg-nyc/KAVI-datathon)"
RADIUS_M = 120
BATCH = 30
PAUSE_S = 20
RETRY_STATUS = {429, 502, 503, 504}


def post(endpoint, query, tries=6):
    wait = 30
    for attempt in range(tries):
        req = urllib.request.Request(endpoint, data=urllib.parse.urlencode({"data": query}).encode(),
                                     headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=200) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            msg = f"HTTP {e.code}"
            if e.code not in RETRY_STATUS:
                raise SystemExit(msg)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            msg = repr(e)
        print(f"  {msg}; retry in {wait}s ({attempt + 1}/{tries})", file=sys.stderr, flush=True)
        time.sleep(wait)
        wait = min(wait * 2, 300)
    return None


def points():
    pts = set()
    for r in csv.DictReader(NYPL_CSV.open(encoding="utf-8-sig")):
        if r["row_type"] == "mapped" and r["latitude"]:
            pts.add((round(float(r["latitude"]), 5), round(float(r["longitude"]), 5)))
    return sorted(pts)


def around_queries():
    pts = points()
    for i in range(0, len(pts), BATCH):
        body = "".join(f'  nwr["name"](around:{RADIUS_M},{la},{lo});\n' for la, lo in pts[i:i + BATCH])
        yield f"around_{i // BATCH:02d}", f"[out:json][timeout:120];\n(\n{body});\nout center meta;\n"


def name_queries(patterns):
    # one regex per query, a handful of names each; case-insensitive on name, operator, brand, alt_name
    for i in range(0, len(patterns), 12):
        rx = "|".join(patterns[i:i + 12])
        body = "".join(f'  nwr["{k}"~"{rx}",i];\n' for k in ("name", "operator", "brand", "alt_name"))
        yield f"names_{i // 12:02d}", "[out:json][timeout:180];\narea(id:3600175905)->.nyc;\n(\n" + body.replace(";\n", "(area.nyc);\n") + ");\nout center meta;\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["around", "names"])
    ap.add_argument("--cache", required=True)
    ap.add_argument("--endpoint", default=ENDPOINT)
    ap.add_argument("--patterns", help="text file, one regex per line (names mode)")
    a = ap.parse_args()
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    if a.mode == "around":
        qs = list(around_queries())
    else:
        pats = [p.strip() for p in Path(a.patterns).read_text().splitlines() if p.strip()]
        qs = list(name_queries(pats))
    done = failed = 0
    for key, q in qs:
        f = cache / f"{key}.json"
        if f.exists():
            done += 1
            continue
        print(f"{key}: {len(q)} chars", flush=True)
        data = post(a.endpoint, q)
        if data is None or "elements" not in data:
            failed += 1
            print(f"  {key} FAILED", file=sys.stderr, flush=True)
        else:
            f.write_text(json.dumps(data))
            print(f"  {len(data['elements'])} elements", flush=True)
            done += 1
        time.sleep(PAUSE_S)
    print(f"{done} ok, {failed} failed, of {len(qs)}")


if __name__ == "__main__":
    main()
