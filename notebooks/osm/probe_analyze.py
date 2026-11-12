# /// script
# requires-python = ">=3.10"
# ///
"""Which OSM tags outside the current extract filter hold NYPL matches?

Reads the cached Overpass answers of `probe_overpass.py around|names` (a directory of JSON files), keeps named
features that are not already in data/supplement/osm.csv (no highways, transit or railway), runs the real matcher
over osm.csv + those extras, and reports, per primary tag:
  - extras: features near the NYPL points (the "flood" cost of adding the tag)
  - gain:   NYPL rows whose best match is an extra feature and which osm.csv alone did not site-match
            (same_site / program_at_host); with examples.
Counts of accepted pairs, not accuracy: there are no gold labels.

    python3 notebooks/osm/probe_analyze.py --cache DIR [--cache DIR2 ...]
"""

import argparse
import json
import re
from collections import Counter, defaultdict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline" / "supplement"))
import extract_all as ex  # noqa: E402
import match_nypl as m  # noqa: E402

SKIP_KEYS = ("highway", "public_transport", "railway")
TAG_KEYS = ("amenity", "office", "healthcare", "social_facility", "government", "shop", "leisure", "tourism", "club",
            "craft", "building", "landuse", "man_made", "historic", "place", "emergency", "military", "sport")
SITE = ("same_site", "program_at_host")


def tag_of(t):
    for k in TAG_KEYS:
        if k in t:
            return f"{k}={t[k]}" if k != "building" else "building=*"
    return "other"


def load(caches):
    feats = {}
    for c in caches:
        for f in sorted(Path(c).glob("*.json")):
            for e in json.loads(f.read_text()).get("elements", []):
                t = e.get("tags") or {}
                if "name" not in t or any(k in t for k in SKIP_KEYS):
                    continue
                c_ = e.get("center") or e
                if "lat" not in c_:
                    continue
                feats[f"{e['type']}/{e['id']}"] = (e, c_["lat"], c_["lon"], t)
    return feats


def names_report(cache, patterns_file):
    """Per distinctive NYPL org name: OSM features (any tag) whose name/operator/brand/alt_name match, and where."""
    have = {r["source_id"] for r in m.read(m.SUPP_DIR / "osm.csv")}
    feats = {}
    for f in sorted(Path(cache).glob("*.json")):
        for e in json.loads(f.read_text()).get("elements", []):
            feats[f"{e['type']}/{e['id']}"] = e
    print(f"{len(feats)} features returned by the name search ({len(list(Path(cache).glob('*.json')))} batches cached)")
    pats = [p.strip() for p in Path(patterns_file).read_text().splitlines() if p.strip()]
    absent = []
    for p in pats:
        rx = re.compile(p, re.I)
        hits = [(oid, e) for oid, e in feats.items()
                if any(rx.search((e.get("tags") or {}).get(k, "")) for k in ("name", "operator", "brand", "alt_name"))]
        if not hits:
            absent.append(p)
            continue
        inside = sum(oid in have for oid, _ in hits)
        print(f"{p:42} {len(hits):3} features, {inside} already in osm.csv")
        for oid, e in hits[:3]:
            t = e["tags"]
            print(f"      {oid:22} {tag_of(t):26} {t.get('name', t.get('operator', ''))[:50]}")
    print(f"\nno OSM feature at all for {len(absent)} of {len(pats)} names (only a returned batch can say so):")
    print("  " + "; ".join(absent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", help="patterns file: report the name-search cache (--cache) instead")
    ap.add_argument("--cache", action="append", required=True)
    ap.add_argument("--examples", type=int, default=4)
    a = ap.parse_args()
    if a.names:
        return names_report(a.cache[0], a.names)
    base = m.read(m.SUPP_DIR / "osm.csv")
    have = {r["source_id"] for r in base}
    feats = load(a.cache)
    extra_rows = []
    for oid, (e, la, lo, t) in feats.items():
        if oid in have:
            continue
        r = ex.to_row(oid, la, lo, "", t, e.get("timestamp", ""), e.get("version", ""))
        r["primary_type"] = tag_of(t)
        extra_rows.append(r)
    print(f"{len(feats)} named non-transit features in cache; {len(feats) - len(extra_rows)} already in osm.csv; "
          f"{len(extra_rows)} extra")
    nypl = m.read(m.NYPL_CSV)
    kw = dict(bins=m.load_bins(), aliases=m.load_aliases())
    before = {r["nypl_id"]: r["match_class"] for r in m.match_all(m.Ctx(nypl, base, **kw)) if r["is_best"]}
    rows = m.match_all(m.Ctx(nypl, base + extra_rows, **kw))
    extra_ids = {r["source_id"] for r in extra_rows}
    flood = Counter(r["primary_type"] for r in extra_rows)
    gain = defaultdict(list)
    for r in rows:
        if not r["is_best"] or r["source_id"] not in extra_ids:
            continue
        if r["match_class"] in SITE and before.get(r["nypl_id"]) not in SITE:
            gain[r["match_primary_type"]].append(r)
    print(f"\n{'tag':32} {'extras':>6} {'new site-level rows':>20}")
    for tag in sorted(set(flood) | set(gain), key=lambda k: (-len(gain[k]), -flood[k])):
        print(f"{tag:32} {flood[tag]:6} {len(gain[tag]):20}")
        for r in gain[tag][: a.examples]:
            print(f"    {r['match_class']:15} {r['nypl_name'][:44]:44} <- {r['match_name'][:36]:36} {r['distance_m']}m "
                  f"sim={r['name_sim']} {r['source_id']}")
    print("\ntotal new site-level rows:", sum(len(v) for v in gain.values()))
    other = Counter(r["match_class"] for r in rows if r["is_best"] and r["source_id"] in extra_ids)
    print("best-match class counts for rows won by an extra feature:", dict(other))


if __name__ == "__main__":
    main()
