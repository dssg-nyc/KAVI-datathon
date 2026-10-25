# PROTOTYPE, throwaway. Builds the transit network used by reach-prototype.html.
#
# Downloads the MTA's static GTFS (subway plus the five borough bus feeds and MTA Bus Co) and the
# MTA Subway Stations dataset (data.ny.gov 39hk-dx4f, for the ADA flags), and writes
# data/prototype/reach_transit_PROTOTYPE.json:
#   stops:  [name, lat, lon, kind, accessible]   kind 0 = bus, 1 = subway
#   routes: [{"n": name, "k": kind, "c": colour, "p": [[stop index, ...], ...]}]
# Each route keeps up to three stop sequences ("patterns") per direction, the ones most trips use.
# No times are kept: the prototype estimates ride time from distance.
#
# Subway stops are the GTFS platform stops (e.g. R01N, R01S), so a station that is accessible in
# one direction only (ada = 2) is accessible on that platform only. Every MTA bus is accessible.
#
# Usage: python3 scripts/prototype/build_reach_transit.py   (stdlib only; downloads about 60 MB)
import csv
import io
import json
import os
import tempfile
import urllib.request
import zipfile
from collections import Counter, defaultdict

FEEDS = {
    'gtfs_subway': 1,
    'gtfs_bx': 0, 'gtfs_b': 0, 'gtfs_m': 0, 'gtfs_q': 0, 'gtfs_si': 0, 'gtfs_busco': 0,
}
GTFS_URL = 'https://rrgtfsfeeds.s3.amazonaws.com/{}.zip'
STATIONS_URL = 'https://data.ny.gov/resource/39hk-dx4f.json?$limit=1000'
PATTERNS_PER_DIRECTION = 3
MIN_PATTERN_SHARE = 0.1  # a pattern must carry this share of its route-direction's trips

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = os.path.join(ROOT, 'data', 'prototype', 'reach_transit_PROTOTYPE.json')


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'KAVI-datathon reach prototype'})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def rows(z, name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding='utf-8-sig'))


def station_ada():
    """GTFS platform stop id (e.g. 'R01N') -> 0/1 accessible, from the MTA Subway Stations dataset."""
    out = {}
    for s in json.loads(fetch(STATIONS_URL)):
        sid = s['gtfs_stop_id']
        out[sid + 'N'] = 1 if s.get('ada_northbound') == '1' else 0
        out[sid + 'S'] = 1 if s.get('ada_southbound') == '1' else 0
    return out


def main():
    ada = station_ada()
    stops, stop_index, routes = [], {}, []
    tmp = tempfile.mkdtemp(prefix='reach_gtfs_')
    for feed, kind in FEEDS.items():
        path = os.path.join(tmp, feed + '.zip')
        with open(path, 'wb') as f:
            f.write(fetch(GTFS_URL.format(feed)))
        z = zipfile.ZipFile(path)
        feed_stops = {r['stop_id']: r for r in rows(z, 'stops.txt')}
        route_info = {r['route_id']: r for r in rows(z, 'routes.txt')}
        trip_route = {r['trip_id']: (r['route_id'], r.get('direction_id', '')) for r in rows(z, 'trips.txt')}

        seqs = defaultdict(list)
        for r in rows(z, 'stop_times.txt'):
            seqs[r['trip_id']].append((int(r['stop_sequence']), r['stop_id']))
        patterns = defaultdict(Counter)  # (route, direction) -> Counter of stop tuples
        for trip, seq in seqs.items():
            if trip not in trip_route:
                continue
            seq.sort()
            patterns[trip_route[trip]][tuple(s for _, s in seq)] += 1
        del seqs

        by_route = defaultdict(list)
        for (route_id, _), counter in patterns.items():
            total = sum(counter.values())
            for pattern, n in counter.most_common(PATTERNS_PER_DIRECTION):
                if n / total >= MIN_PATTERN_SHARE and len(pattern) > 1:
                    by_route[route_id].append(pattern)

        for route_id, pats in sorted(by_route.items()):
            info = route_info.get(route_id, {})
            idx_pats = []
            for pattern in pats:
                idx = []
                for sid in pattern:
                    key = f'{feed}:{sid}'
                    if key not in stop_index:
                        s = feed_stops[sid]
                        accessible = ada.get(sid, 0) if kind == 1 else 1
                        stop_index[key] = len(stops)
                        stops.append([s['stop_name'].strip(), round(float(s['stop_lat']), 5),
                                      round(float(s['stop_lon']), 5), kind, accessible])
                    idx.append(stop_index[key])
                idx_pats.append(idx)
            routes.append({'n': info.get('route_short_name') or route_id, 'k': kind,
                           'c': '#' + (info.get('route_color') or '666666'), 'p': idx_pats})
        print(f'{feed}: {len(by_route)} routes, {len(stops)} stops so far')
        os.remove(path)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump({'stops': stops, 'routes': routes}, f, separators=(',', ':'))
    sub = [s for s in stops if s[3] == 1]
    print(f'wrote {OUT}: {len(stops)} stops ({len(sub)} subway platforms, '
          f'{sum(s[4] for s in sub)} accessible), {len(routes)} routes, {os.path.getsize(OUT) // 1024} KB')


if __name__ == '__main__':
    main()
