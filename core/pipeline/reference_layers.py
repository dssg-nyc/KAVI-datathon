"""Downloads the supplementary ArcGIS layers (PRD section 8) into data/public/layers/.

The finder draws them without talking to ArcGIS Online at run time (requirement R3), and a change
in them shows up as a diff. Each layer becomes a GeoJSON file of Point features with three or four
small properties, one feature per line, plus data/public/layers/index.json that lists the layers
for the finder.

  uv run core/pipeline/reference_layers.py    download all three and write the files

Needs the network. The files are committed; rerun this when the layers change on ArcGIS Online.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from map_resources import ROOT, read_text, to_json

LAYERS_DIR = ROOT / "data" / "public" / "layers"
INDEX_PATH = LAYERS_DIR / "index.json"

ARCGIS = "https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services"
PAGE = 2000  # the services' maxRecordCount


def _str(v) -> str:
    return "" if v is None else str(v)


def title_case(s) -> str:
    """"GREENPOINT LIBRARY" -> "Greenpoint Library"; the Facilities Database shouts."""
    return re.sub(r"(^|[\s\-/(])([a-z])", lambda m: m[1] + m[2].upper(), _str(s).lower()).strip()


def point(coordinates: list, properties: dict) -> dict:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": coordinates}, "properties": properties}


def facility(props: dict, coordinates: list, kind: str | None) -> dict:
    """The NYC Facilities Database rows (libraries, health facilities) share one layout."""
    city_zip = " ".join(_str(v) for v in (title_case(props.get("CITY")), props.get("ZIPCODE")) if v)
    address = ", ".join(v for v in (title_case(props.get("ADDRESS")), city_zip) if v)
    return point(coordinates, {"name": title_case(props.get("FACNAME")), "address": address or None, "kind": kind})


def cooling_site(p: dict, c: list) -> dict:
    return point(c, {
        "name": ": ".join(_str(v) for v in (p.get("PropertyName"), p.get("SubPropertyName")) if v),
        "address": _str(p["Borough"]) if p.get("Borough") else None,
        "kind": _str(p["FeatureType"]) if p.get("FeatureType") else None,
        "status": _str(p["Status"]) if p.get("Status") else None,
    })


@dataclass(frozen=True)
class Layer:
    key: str
    label: str  # the toggle's text in the finder
    note: str  # what the layer is, shown as the toggle's title
    color: str
    service: str  # the FeatureServer name on ArcGIS Online
    source: str  # where ArcGIS Online got it, for the attribution line
    to_feature: Callable[[dict, list], dict]


LAYERS = [
    Layer(
        key="libraries",
        label="Libraries",
        note="Public library branches (NYC Facilities Database)",
        color="#7c3aed",
        service="public_libraries_points",
        source="NYC Department of City Planning Facilities Database, via the DSSG NYC ArcGIS Online layer public_libraries_points",
        to_feature=lambda p, c: facility(p, c, _str(p["OPNAME"]) if p.get("OPNAME") else None),
    ),
    Layer(
        key="health_facilities",
        label="Health facilities",
        note="Hospitals, clinics, mental health and substance use programs (NYC Facilities Database)",
        color="#0891b2",
        service="health_facilities_points",
        source="NYC Department of City Planning Facilities Database, via the DSSG NYC ArcGIS Online layer health_facilities_points",
        to_feature=lambda p, c: facility(p, c, title_case(p["FACTYPE"]) if p.get("FACTYPE") else None),
    ),
    Layer(
        key="cooling_sites",
        label="Cooling sites",
        note="NYC Parks spray showers, misting stations and other outdoor cooling sites; not indoor cooling centers",
        color="#2563eb",
        service="Cooling_Sites_points",
        source="NYC Parks cooling sites, via the DSSG NYC ArcGIS Online layer Cooling_Sites_points",
        to_feature=cooling_site,
    ),
]


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.load(response)


def fetch_layer(layer: Layer, get_json: Callable[[str], dict] = _get_json) -> list[dict]:
    features: list[dict] = []
    offset = 0
    while True:
        url = (
            f"{ARCGIS}/{layer.service}/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=geojson"
            f"&resultOffset={offset}&resultRecordCount={PAGE}"
        )
        data = get_json(url)
        if data.get("error"):
            raise RuntimeError(f"{layer.service}: {data['error'].get('message')}")
        page = data.get("features") or []
        for f in page:
            geometry = f.get("geometry") or {}
            if geometry.get("type") != "Point":
                continue
            feature = layer.to_feature(f.get("properties") or {}, geometry["coordinates"])
            if feature["properties"]["name"]:
                features.append(feature)
        # A service may cap a page below PAGE (its maxRecordCount); it then says so, and the next page is fetched.
        if not page or (len(page) < PAGE and not data.get("exceededTransferLimit")):
            return features
        offset += len(page)  # step by what was actually returned


def to_geojson(features: list[dict]) -> str:
    """One feature per line, so a refresh is a readable diff."""
    return '{"type":"FeatureCollection","features":[\n' + ",\n".join(to_json(f) for f in features) + "\n]}\n"


def layer_path(layer: Layer) -> Path:
    return LAYERS_DIR / f"{layer.key}.geojson"


def _read_or_blank(path: Path) -> str:
    try:
        return read_text(path)
    except FileNotFoundError:
        return ""


def index_json(counts: dict[str, int], changed: dict[str, bool], today: date | None = None) -> str:
    """The index the finder reads: one entry per layer. `fetched` is the day the features last changed."""
    try:
        current = json.loads(_read_or_blank(INDEX_PATH) or "[]")
    except json.JSONDecodeError:
        current = []
    day = (today or datetime.now(timezone.utc).date()).isoformat()
    entries = []
    for layer in LAYERS:
        previous = next((e.get("fetched") for e in current if e.get("key") == layer.key), None)
        entries.append({
            "key": layer.key, "label": layer.label, "note": layer.note, "color": layer.color,
            "file": f"data/public/layers/{layer.key}.geojson", "count": counts[layer.key], "source": layer.source,
            "fetched": day if changed[layer.key] else (previous or day),
        })
    return json.dumps(entries, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    LAYERS_DIR.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    changed: dict[str, bool] = {}
    for layer in LAYERS:
        features = fetch_layer(layer)
        content = to_geojson(features)
        path = layer_path(layer)
        changed[layer.key] = _read_or_blank(path) != content
        counts[layer.key] = len(features)
        if changed[layer.key]:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        print(f"{layer.key}: {len(features)} features{', written' if changed[layer.key] else ', unchanged'}")
    with open(INDEX_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(index_json(counts, changed))
    print(f"Wrote {INDEX_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
