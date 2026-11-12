# /// script
# requires-python = ">=3.10"
# ///
"""Fetch the NYC Building Identification Number (BIN) for each mapped NYPL address, once, cached.

Uses NYC GeoSearch (https://geosearch.planninglabs.nyc/v2/search), the same service as
core/pipeline/geocode.py; its result carries properties.addendum.pad.bin. One request at a time,
a pause between requests. Rows already in the cache are never fetched again. A BIN is kept only when
the returned zip and house number match the NYPL row (same rule as geocode.py), else bin is blank.

Writes data/supplement/nypl_bin_cache.csv (key = the query text).

    python3 core/supplement/fetch_bins.py
"""

import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NYPL_CSV = ROOT / "data" / "kavi_resources.csv"
CACHE = ROOT / "data" / "supplement" / "nypl_bin_cache.csv"
ENDPOINT = "https://geosearch.planninglabs.nyc/v2/search"
USER_AGENT = "KAVI-datathon resource map (github.com/dssg-nyc/KAVI-datathon)"
PAUSE_S = 0.4
COLUMNS = ["query", "house_number", "zip", "returned_label", "returned_housenumber", "returned_zip", "bin", "bbl",
           "house_match", "status"]


def norm_hn(n):
    return re.sub(r"-?[A-Z]+$", "", re.sub(r"\s+", "", n.upper().replace("–", "-").replace("—", "-")))


def house_match(a, b):
    a, b = norm_hn(a), norm_hn(b)
    if not a or not b:
        return False
    if a == b:
        return True
    m = re.fullmatch(r"(\d+)-(\d+)", a)
    return bool(m) and "-" not in b and b in m.groups()


def get(query):
    url = f"{ENDPOINT}?text={urllib.parse.quote(query)}&size=1"
    wait = 5
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  retry after {wait}s: {e}", file=sys.stderr)
            time.sleep(wait)
            wait *= 2
    return None


def address_query(r):
    """GeoSearch query text for an NYPL row (also the cache key)."""
    if not r.get("street") or not r.get("zip_code"):
        return ""
    return ", ".join(x for x in (f"{r['street_number']} {r['street']}".strip(), r["city"], r["state"], r["zip_code"][:5]) if x)


def main():
    cache = {}
    if CACHE.exists():
        cache = {r["query"]: r for r in csv.DictReader(CACHE.open(encoding="utf-8"))}
    todo = {}
    for r in csv.DictReader(NYPL_CSV.open(encoding="utf-8-sig")):
        if r["row_type"] != "mapped" or not address_query(r):
            continue
        q = address_query(r)
        if q not in cache:
            todo[q] = (r["street_number"], r["zip_code"][:5])
    print(f"{len(cache)} cached, {len(todo)} to fetch")
    for i, (q, (hn, z)) in enumerate(todo.items()):
        data = get(q)
        row = {"query": q, "house_number": hn, "zip": z, "returned_label": "", "returned_housenumber": "",
               "returned_zip": "", "bin": "", "bbl": "", "house_match": "", "status": "error"}
        if data is not None:
            feats = data.get("features") or []
            row["status"] = "no_result" if not feats else "ok"
            if feats:
                p = feats[0]["properties"]
                pad = (p.get("addendum") or {}).get("pad") or {}
                hm = house_match(hn, p.get("housenumber", "")) and p.get("postalcode", "")[:5] == z
                row.update(returned_label=p.get("label", ""), returned_housenumber=p.get("housenumber", ""),
                           returned_zip=p.get("postalcode", ""), house_match=hm,
                           bin=pad.get("bin", "") if hm else "", bbl=pad.get("bbl", "") if hm else "")
        if row["status"] != "error":  # errors are retried on the next run
            cache[q] = row
        time.sleep(PAUSE_S)
        if i % 50 == 0:
            print(f"  {i}/{len(todo)}")
    with CACHE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        w.writerows(cache.values())
    ok = sum(1 for r in cache.values() if r["bin"])
    print(f"{len(cache)} cached addresses, {ok} with a BIN -> {CACHE}")


if __name__ == "__main__":
    main()
