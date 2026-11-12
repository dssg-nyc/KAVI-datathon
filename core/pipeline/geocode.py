"""Transforms data/NYPL Connections Resources.csv into a GeoJSON that uses OSM's address-tagging
convention (addr:housenumber, addr:street, addr:city, addr:state, addr:postcode, addr:country; see
https://wiki.openstreetmap.org/wiki/Key:addr). Every original column is kept on each feature's
properties; only the location fields are added.

Coordinates try NYC's own GeoSearch geocoder first (building-level, no API key), falling back
to the Census Bureau's free batch geocoder for whatever GeoSearch can't confidently place.
GeoSearch has no real concept of "outside NYC": for an address it can't find, it silently
returns the nearest same-named NYC street instead of nothing, so a GeoSearch result is only
trusted when the zip code it returns matches the input's. Anything that fails that check
(including every address genuinely outside NYC) falls through to Census. Rows with no usable
address, or that neither geocoder can match, are kept with geometry: null rather than dropped,
since the PRD wants hotlines and address-less resources surfaced too.

  uv run core/pipeline/geocode.py [out.geojson]    needs the network: queries GeoSearch and Census

Ported from geocode.ts (Rita's), which it replaces; the logic and the output are the same.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from map_resources import ROOT, read_text, to_json, to_number

GEOCODE_ENDPOINT = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
BENCHMARK = "Public_AR_Current"
INPUT_CSV = ROOT / "data" / "NYPL Connections Resources.csv"
OUTPUT = ROOT / "data" / "nypl_connections_resources.geojson"
RETRY_STATUSES = (429, 502, 503, 504)

GEOSEARCH_ENDPOINT = "https://geosearch.planninglabs.nyc/v2/search"
GEOSEARCH_CONCURRENCY = 5


def parse_csv(text: str) -> list[list[str]]:
    """RFC 4180 with \\r dropped outside quotes, so CRLF files and the Census response both read."""
    rows: list[list[str]] = []
    row: list[str] = []
    field: list[str] = []
    in_quotes = False
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if in_quotes:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 1
                else:
                    in_quotes = False
            else:
                field.append(c)
        elif c == '"':
            in_quotes = True
        elif c == ",":
            row.append("".join(field))
            field = []
        elif c == "\r":
            pass
        elif c == "\n":
            row.append("".join(field))
            rows.append(row)
            row, field = [], []
        else:
            field.append(c)
        i += 1
    if field or row:
        row.append("".join(field))
        rows.append(row)
    return [r for r in rows if any(f.strip() for f in r)]


def csv_cell(v: str) -> str:
    return '"' + v.replace('"', '""') + '"' if re.search(r'[",\n]', v) else v


def is_geocodable(r: dict) -> bool:
    return bool(r["Street"].strip()) and bool(r["City"].strip() or r["Zip Code"].strip())


# Two zip-code typos in the source CSV, confirmed against the published ArcGIS layer
# (NYPL_Connections_merge) during PR review. Keyed by Organization Name (stable and unique for
# both rows) rather than rewriting the raw CSV, so the delivered file stays byte-for-byte as
# received and this fix stays visible and testable in code.
ZIP_FIXES = {
    "THE BEDFORD-STUYVESANT FAMILY HEALTH CENTER - 4 (Wellness Center Program)": "11216",  # was 12116
    "CENTER FOR JUSTICE INNOVATION (CJI)—THE STATEN ISLAND JUSTICE CENTER": "10301",  # was 10304
}


def clean_zip(r: dict) -> dict:
    fix = ZIP_FIXES.get(r["Organization Name"])
    return {**r, "Zip Code": fix} if fix else r


# Rows whose point is kept but couldn't be confirmed during PR review. 45 Suffolk Street has no
# tax lot in PLUTO and GeoSearch can't find it either; Census places it on the street, but
# nothing confirms the building. Keyed by Organization Name, like ZIP_FIXES.
REVIEW_NOTES = {
    "Chinese-American Planning Council": (
        "45 Suffolk Street is not in PLUTO or NYC GeoSearch; location is a street-level estimate. "
        "Confirm the address with the organization."
    ),
}

# A match result is a dict: matched (bool), and when placed lon, lat, source ('geosearch' or
# 'census'), matched_address (the address the geocoder actually placed: GeoSearch's label, Census's
# matched address) and review (set when the point is kept but not confirmed at building level).


def build_batch_csv(ids: list[int], rows: list[dict]) -> str:
    return "\n".join(
        ",".join(csv_cell(str(v)) for v in (id_, r["street"], r["city"], r["state"], r["zip"]))
        for id_, r in zip(ids, rows)
    )


def parse_geocode_response(csv_text: str) -> dict[int, dict]:
    results: dict[int, dict] = {}
    for cols in parse_csv(csv_text):
        id_ = int(cols[0])
        if len(cols) < 3 or cols[2] != "Match":
            results[id_] = {"matched": False}
            continue
        lon, lat = (to_number(v) for v in cols[5].split(",")[:2])
        results[id_] = {"matched": True, "lon": lon, "lat": lat, "matched_address": cols[4]}
    return results


def to_feature(r: dict, result: dict | None) -> dict:
    addr = {}
    for column, tag in (("Street Number", "addr:housenumber"), ("Street", "addr:street"), ("City", "addr:city"),
                        ("State", "addr:state"), ("Zip Code", "addr:postcode")):
        if r.get(column):
            addr[tag] = r[column]
    if addr:
        addr["addr:country"] = "US"
    matched = bool(result and result["matched"])
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [result["lon"], result["lat"]]} if matched else None,
        "properties": {
            **r,
            **addr,
            "geocode_match": "not_attempted" if not result else "matched" if matched else "unmatched",
            "geocode_source": result.get("source", "") if matched else "",
            "geocode_matched_address": result.get("matched_address", "") if matched else "",
            "geocode_review": result.get("review", "") if matched else "",
        },
    }


def _post_census(body: bytes, content_type: str) -> tuple[int, str]:
    request = urllib.request.Request(GEOCODE_ENDPOINT, data=body, method="POST", headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def census_form(ids: list[int], rows: list[dict]) -> tuple[bytes, str]:
    """The multipart body the batch endpoint takes: the addresses as a file, and the benchmark."""
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="addressFile"; filename="addresses.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n{build_batch_csv(ids, rows)}\r\n",
        f'--{boundary}\r\nContent-Disposition: form-data; name="benchmark"\r\n\r\n{BENCHMARK}\r\n',
        f"--{boundary}--\r\n",
    ]
    return "".join(parts).encode("utf-8"), f"multipart/form-data; boundary={boundary}"


def geocode(ids: list[int], rows: list[dict], post: Callable[[bytes, str], tuple[int, str]] = _post_census,
            sleep: Callable[[float], None] = time.sleep) -> dict[int, dict]:
    """The Census batch geocoder, retried with backoff while it says it is busy."""
    body, content_type = census_form(ids, rows)
    wait = 10
    for attempt in range(4):
        status, text = post(body, content_type)
        if status not in RETRY_STATUSES or attempt == 3:
            break
        print(f"Census geocoder busy (HTTP {status}), retrying in {wait}s", file=sys.stderr)
        sleep(wait)
        wait *= 2
    if status != 200:
        raise RuntimeError(f"Census geocoder HTTP {status}: {text[:500]}")
    return parse_geocode_response(text)


def _normalize_house_number(n: str) -> str:
    n = re.sub(r"[–—]", "-", n.upper())
    n = re.sub(r"\s+", "", n)
    return re.sub(r"-?[A-Z]+\Z", "", n)


def house_numbers_match(given: str, returned: str) -> bool:
    """"76-A" matches 76, "150D" matches 150, and a range like "400-430" matches either end. A
    Queens-style number like "29-76" only matches itself, because GeoSearch returns those whole."""
    a, b = _normalize_house_number(given), _normalize_house_number(returned)
    if not a or not b:
        return False
    if a == b:
        return True
    m = re.fullmatch(r"([0-9]+)-([0-9]+)", a)
    return bool(m) and "-" not in b and b in (m[1], m[2])


def pick_geosearch_match(features: list[dict], zip_code: str, house_number: str = "") -> dict | None:
    """GeoSearch always returns something for a plausible-looking query, even for addresses nowhere
    near NYC: it falls back to the nearest same-named NYC street rather than no match (e.g.
    "Kingston, NY 12401" comes back as a Brooklyn street with zip 11213). The only reliable signal
    that a result is real is that the zip it returns matches the zip we asked for.

    Inside NYC the same fallback returns a different building on the right street and zip (e.g.
    "581 Rogers Avenue" comes back as 1038 Rogers Avenue, 1.4 km away), so the house number has to
    match too. A zip-only match is still returned, flagged with house_number_matches False."""
    zip5 = zip_code.strip()[:5]
    if not zip5:
        return None
    hit = next((f for f in features if (f["properties"].get("postalcode") or "").strip()[:5] == zip5), None)
    if hit is None:
        return None
    lon, lat = hit["geometry"]["coordinates"][:2]
    return {
        "lon": lon,
        "lat": lat,
        "house_number_matches": house_numbers_match(house_number, hit["properties"].get("housenumber") or ""),
        "label": hit["properties"].get("label") or "",
    }


def _get_geosearch(text: str) -> dict | None:
    url = f"{GEOSEARCH_ENDPOINT}?text={urllib.parse.quote(text, safe='')}&size=1"
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def geocode_with_geosearch(rows: list[dict], get: Callable[[str], dict | None] = _get_geosearch) -> dict[int, dict]:
    """A row whose GeoSearch result has the wrong house number comes back with matched False (so it
    still goes to Census) but keeps the GeoSearch point, which main() uses only if Census also fails.
    A failed request leaves the row unresolved, so it goes to Census like any other."""

    def one(row: dict) -> tuple[int, dict | None]:
        text = ", ".join(v for v in (row["street"], row["city"], row["state"], row["zip"]) if v)
        try:
            data = get(text)
        except Exception as e:  # noqa: BLE001 - any failure falls through to Census
            print(f"GeoSearch request failed for row {row['id']}: {e}", file=sys.stderr)
            return row["id"], None
        features = (data or {}).get("features")
        match = pick_geosearch_match(features, row["zip"], row.get("house_number", "")) if features else None
        if not match:
            return row["id"], None
        return row["id"], {"matched": match["house_number_matches"], "lon": match["lon"], "lat": match["lat"],
                           "source": "geosearch", "matched_address": match["label"]}

    with ThreadPoolExecutor(GEOSEARCH_CONCURRENCY) as pool:
        return {id_: result for id_, result in pool.map(one, rows) if result}


def read_records(path: Path = INPUT_CSV) -> list[dict]:
    header, *rows = parse_csv(read_text(path))
    return [clean_zip({h: cols[i] if i < len(cols) else "" for i, h in enumerate(header)}) for cols in rows]


def address_rows(records: list[dict]) -> list[dict]:
    return [
        {
            "id": i,
            "house_number": r["Street Number"],
            "street": " ".join(v for v in (r["Street Number"], r["Street"]) if v),
            "city": r["City"],
            "state": r["State"],
            "zip": r["Zip Code"],
        }
        for i, r in enumerate(records)
        if is_geocodable(r)
    ]


def merge_results(records: list[dict], geosearch: dict[int, dict], census: dict[int, dict]) -> dict[int, dict]:
    """One result per row: GeoSearch where it matched, then Census, then GeoSearch's same-street point."""
    results = {id_: r for id_, r in geosearch.items() if r["matched"]}
    for id_, r in census.items():
        fallback = geosearch.get(id_)
        if r["matched"] or not fallback:
            results[id_] = {**r, "source": "census"}
        else:
            # Neither geocoder placed the exact building. Keep GeoSearch's same-street point rather than
            # dropping the resource, and say why it needs review.
            results[id_] = {
                **fallback,
                "matched": True,
                "review": f"GeoSearch matched {fallback['matched_address']}, not house number "
                f"{records[id_]['Street Number']}, and Census found no match. Confirm the location.",
            }
    for id_, r in results.items():
        note = REVIEW_NOTES.get(records[id_]["Organization Name"])
        if note and r["matched"]:
            r["review"] = note
    return results


def feature_collection(records: list[dict], results: dict[int, dict]) -> str:
    """The GeoJSON the rest of the pipeline reads: compact, one line, no trailing newline."""
    features = [to_feature(r, results.get(i)) for i, r in enumerate(records)]
    return to_json({"type": "FeatureCollection", "features": features})


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT
    records = read_records()
    rows = address_rows(records)

    # Try NYC GeoSearch first (see pick_geosearch_match for why its result has to match on zip and
    # house number); whatever it can't confidently place, including every address genuinely
    # outside NYC, falls through to the Census batch geocoder.
    geosearch = geocode_with_geosearch(rows) if rows else {}
    remaining = [row for row in rows if not geosearch.get(row["id"], {}).get("matched")]
    census = geocode([r["id"] for r in remaining], remaining) if remaining else {}
    results = merge_results(records, geosearch, census)

    content = feature_collection(records, results)
    matched = [r for r in results.values() if r["matched"]]
    unmatched = sum(1 for r in results.values() if not r["matched"])
    via = {s: sum(1 for r in matched if r.get("source") == s) for s in ("geosearch", "census")}
    review = sum(1 for r in matched if r.get("review"))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    print(
        f"{len(records)} resources ({len(matched)} matched [{via['geosearch']} via GeoSearch, {via['census']} via Census, "
        f"{review} need review], {unmatched} unmatched, {len(records) - len(matched) - unmatched} not attempted) -> {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
