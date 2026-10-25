#!/usr/bin/env python3
"""Reproduces the numbers in scripts/analysis/nypl_connections_location_analysis.md.

Reads data/nypl_connections_resources.geojson (the output of
nypl_connections_to_geojson.ts) and prints: total entities, Census geocoder match counts,
a per-state table, a per-city table, and density stats (densest grid cell, nearest-neighbor
distances) computed from the matched points' coordinates.

    python3 scripts/analysis/analyze_nypl_connections_location.py
"""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

GEOJSON_PATH = Path(__file__).parent.parent.parent / 'data' / 'nypl_connections_resources.geojson'
GRID_CELL_DEG = 0.02  # ~2.2km lat x ~1.7km lon at NYC's latitude


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def section_totals(features: list) -> None:
    print(f"## Total entities\n{len(features)}\n")


def section_geocode_match(features: list) -> None:
    counts = Counter(f['properties']['geocode_match'] for f in features)
    sent = counts['matched'] + counts['unmatched']
    print("## Census geocoder match rate")
    print(f"{'geocode_match':<15} {'count':>6} {'% of all':>10} {'% of sent':>10}")
    for key in ('matched', 'unmatched', 'not_attempted'):
        n = counts[key]
        pct_all = f"{100 * n / len(features):.1f}%"
        pct_sent = f"{100 * n / sent:.1f}%" if key != 'not_attempted' else '—'
        print(f"{key:<15} {n:>6} {pct_all:>10} {pct_sent:>10}")
    print()


def section_per_field(features: list, field: str, label: str) -> None:
    counts = Counter(f['properties'][field].strip() or f'(no {label.lower()})' for f in features)
    print(f"## Entities per {label} ({len(counts)} distinct values)")
    for value, n in counts.most_common():
        print(f"{n:>4}  {value}")
    print()


def section_density(features: list) -> None:
    pts = [(f['geometry']['coordinates'][0], f['geometry']['coordinates'][1], f['properties'])
           for f in features if f['geometry']]
    print(f"## Density (from {len(pts)} matched points with coordinates)\n")

    grid = defaultdict(list)
    for lon, lat, p in pts:
        key = (round(lon / GRID_CELL_DEG), round(lat / GRID_CELL_DEG))
        grid[key].append(p)
    ranked = sorted(grid.items(), key=lambda kv: -len(kv[1]))

    print(f"Densest grid cells (cell ~{GRID_CELL_DEG} deg):")
    for key, plist in ranked[:8]:
        cities = Counter(p['City'] or '(no city)' for p in plist)
        top_cities = ', '.join(f'{c} x{n}' for c, n in cities.most_common(4))
        lon_c, lat_c = key[0] * GRID_CELL_DEG, key[1] * GRID_CELL_DEG
        print(f"  {len(plist):3d} resources around ({lat_c:.3f}, {lon_c:.3f}) -> {top_cities}")
    isolated_cells = sum(1 for v in grid.values() if len(v) == 1)
    print(f"\nOccupied grid cells: {len(grid)}  (of which {isolated_cells} hold exactly 1 resource)\n")

    nn = []
    for i, (lon, lat, p) in enumerate(pts):
        nearest = min(haversine_km(lon, lat, lon2, lat2) for j, (lon2, lat2, _) in enumerate(pts) if j != i)
        nn.append((nearest, p))
    nn.sort(key=lambda x: -x[0])

    print("Most isolated resources (largest distance to nearest other matched resource):")
    for dist, p in nn[:8]:
        print(f"  {dist:7.1f} km   {p['Organization Name'][:45]:45s} {p['City']}, {p['State']}")
    median_nn = sorted(d for d, _ in nn)[len(nn) // 2]
    print(f"\nMedian nearest-neighbor distance: {median_nn:.3f} km")


def main() -> None:
    features = json.loads(GEOJSON_PATH.read_text())['features']
    section_totals(features)
    section_geocode_match(features)
    section_per_field(features, 'State', 'State')
    section_per_field(features, 'City', 'City')
    section_density(features)


if __name__ == '__main__':
    main()
