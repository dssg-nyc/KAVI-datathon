// PROTOTYPE, throwaway. Which resources can a client reach from one place within a time limit, by
// walking (or wheelchair), bus and subway, with no schedules. Pure functions, no DOM.
//
// Network: data/prototype/reach_transit_PROTOTYPE.json (scripts/prototype/build_reach_transit.py).
// Every time is an estimate from distance:
//   on foot      straight-line metres x detour / speed
//   ride         metres along the route's stops / average route speed, plus a fixed wait per boarding
//   transfer     on foot to any stop within transferMaxM of where the client got off
// A wheelchair user can only board and get off at accessible stops (every bus stop; subway platforms
// with ADA access in that direction).

export const DEFAULTS = {
  walkKmh: 4.8,
  wheelchairKmh: 3.6,
  detour: 1.3, // street distance / straight-line distance
  busKmh: 12, // MTA average bus speed including stops is about 8 mph
  subwayKmh: 27, // about 17 mph including stops
  busWaitMin: 8,
  subwayWaitMin: 5,
  transferMaxM: 250,
  maxTransfers: 1,
  maxFootToStopMin: 20, // longest trip on foot to the first stop, and from the last stop
};

const BUS = 0;
const SUBWAY = 1;
// Express buses charge a higher fare than local buses and the subway.
const EXPRESS = /^(BM|BxM|QM|SIM|X)\d/;

export function metres(a, b) {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(h));
}

// Turns the JSON file into stop objects, route patterns with cumulative distances, and a grid index.
export function buildNetwork(json) {
  const stops = json.stops.map(([name, lat, lon, kind, accessible], i) => ({ i, name, lat, lon, kind, accessible: accessible === 1, patterns: [] }));
  const patterns = [];
  for (const route of json.routes) {
    const r = { name: route.n, kind: route.k, color: route.c, express: route.k === BUS && EXPRESS.test(route.n) };
    for (const seq of route.p) {
      const cum = [0];
      for (let j = 1; j < seq.length; j++) cum.push(cum[j - 1] + metres(stops[seq[j - 1]], stops[seq[j]]));
      const pid = patterns.length;
      patterns.push({ route: r, stops: seq, cum });
      seq.forEach((s, pos) => stops[s].patterns.push([pid, pos]));
    }
  }
  const grid = new Map();
  for (const s of stops) {
    const k = cellKey(s.lat, s.lon);
    if (!grid.has(k)) grid.set(k, []);
    grid.get(k).push(s);
  }
  return { stops, patterns, grid };
}

const CELL = 0.005; // degrees; about 550 m north-south
const cellKey = (lat, lon) => `${Math.floor(lat / CELL)},${Math.floor(lon / CELL)}`;

// Stops within `radiusM` of p, each with its straight-line distance `d`.
export function stopsNear(net, p, radiusM) {
  const out = [];
  const dLat = radiusM / 111000 / CELL;
  const dLon = radiusM / (111000 * Math.cos((p.lat * Math.PI) / 180)) / CELL;
  const cy = Math.floor(p.lat / CELL);
  const cx = Math.floor(p.lon / CELL);
  for (let y = Math.floor(cy - dLat); y <= Math.ceil(cy + dLat); y++) {
    for (let x = Math.floor(cx - dLon); x <= Math.ceil(cx + dLon); x++) {
      for (const s of net.grid.get(`${y},${x}`) ?? []) {
        const d = metres(p, s);
        if (d <= radiusM) out.push({ stop: s, d });
      }
    }
  }
  return out;
}

// opts: { minutes, wheelchair, bus, subway, express } plus any DEFAULTS key.
// Returns { boardAt, alightAt, footMin, opts, stats }:
//   boardAt / alightAt: Map stop index -> { t, legs } for the best way found to stand at that stop
//   ready to board / just after getting off. legs: [{ type: 'foot'|'ride', ... , min }].
export function searchFrom(net, origin, options) {
  const o = { ...DEFAULTS, ...options };
  const kmh = o.wheelchair ? o.wheelchairKmh : o.walkKmh;
  const footMin = (straightM) => (straightM * o.detour) / ((kmh * 1000) / 60);
  const usable = (s) => (s.kind === BUS ? o.bus : o.subway) && (!o.wheelchair || s.accessible);
  const routeAllowed = (r) => (r.kind === BUS ? o.bus && (o.express || !r.express) : o.subway);

  const boardAt = new Map();
  const alightAt = new Map();
  const stats = { stopsOnFoot: 0, rounds: [] };

  // Round 0: on foot from the origin to every usable stop that can be reached in time.
  const maxFootM = (Math.min(o.minutes, o.maxFootToStopMin) * ((kmh * 1000) / 60)) / o.detour;
  let marked = [];
  for (const { stop, d } of stopsNear(net, origin, maxFootM)) {
    if (!usable(stop)) continue;
    const t = footMin(d);
    boardAt.set(stop.i, { t, legs: [{ type: 'foot', from: null, to: stop.i, min: t }] });
    marked.push(stop.i);
  }
  stats.stopsOnFoot = marked.length;

  for (let round = 0; round <= o.maxTransfers && marked.length; round++) {
    // Ride: from every stop improved last round, along every allowed pattern through it.
    const improved = new Map();
    for (const si of marked) {
      const label = boardAt.get(si);
      for (const [pid, pos] of net.stops[si].patterns) {
        const pat = net.patterns[pid];
        if (!routeAllowed(pat.route)) continue;
        const speed = ((pat.route.kind === BUS ? o.busKmh : o.subwayKmh) * 1000) / 60;
        const boardT = label.t + (pat.route.kind === BUS ? o.busWaitMin : o.subwayWaitMin);
        for (let j = pos + 1; j < pat.stops.length; j++) {
          const qi = pat.stops[j];
          const t = boardT + (pat.cum[j] - pat.cum[pos]) / speed;
          if (t > o.minutes) break;
          if (!usable(net.stops[qi])) continue;
          const best = improved.get(qi) ?? alightAt.get(qi);
          if (best && best.t <= t) continue;
          improved.set(qi, { t, legs: [...label.legs, { type: 'ride', pid, fromPos: pos, toPos: j, from: si, to: qi, min: t - label.t }] });
        }
      }
    }
    for (const [qi, label] of improved) alightAt.set(qi, label);
    stats.rounds.push({ boardedFrom: marked.length, stopsReached: improved.size });

    // Transfer: on foot from each stop just reached to stops nearby, ready for the next ride.
    const next = new Set();
    for (const [qi, label] of improved) {
      for (const { stop, d } of stopsNear(net, net.stops[qi], o.transferMaxM)) {
        if (!usable(stop)) continue;
        const walk = footMin(d);
        const t = label.t + walk;
        const best = boardAt.get(stop.i);
        if (t > o.minutes || (best && best.t <= t)) continue;
        boardAt.set(stop.i, { t, legs: walk > 0 ? [...label.legs, { type: 'foot', from: qi, to: stop.i, min: walk }] : label.legs });
        next.add(stop.i);
      }
    }
    marked = [...next];
  }
  return { origin, boardAt, alightAt, footMin, opts: o, stats };
}

// The fastest way to `place` from the search: on foot only, or a ride and then on foot.
// `insideFootArea` (optional) says whether `place` is inside the on-foot isochrone; when given, the
// on-foot-only option is kept only for places inside it. Returns { t, legs } or null when too far.
export function bestTrip(net, search, place, insideFootArea) {
  const { footMin, opts, alightAt } = search;
  let best = null;
  const direct = footMin(metres(search.origin, place));
  if (direct <= opts.minutes && (insideFootArea == null || insideFootArea)) {
    best = { t: direct, legs: [{ type: 'foot', from: null, to: null, min: direct }] };
  }
  const kmh = opts.wheelchair ? opts.wheelchairKmh : opts.walkKmh;
  const maxFootM = (Math.min(opts.minutes, opts.maxFootToStopMin) * ((kmh * 1000) / 60)) / opts.detour;
  for (const { stop, d } of stopsNear(net, place, maxFootM)) {
    const label = alightAt.get(stop.i);
    if (!label) continue;
    const walk = footMin(d);
    const t = label.t + walk;
    if (t <= opts.minutes && (!best || t < best.t)) best = { t, legs: [...label.legs, { type: 'foot', from: stop.i, to: null, min: walk }] };
  }
  return best;
}

// One line per leg, e.g. "Walk 6 min to Flatbush Av/Church Av", "B41 to Fulton St, 14 min".
export function describeLegs(net, legs, wheelchair) {
  const move = wheelchair ? 'Wheelchair' : 'Walk';
  return legs.map((leg) => {
    const min = `${Math.max(1, Math.round(leg.min))} min`;
    if (leg.type === 'foot') {
      const to = leg.to == null ? 'the resource' : net.stops[leg.to].name;
      return `${move} ${min} to ${to}`;
    }
    const pat = net.patterns[leg.pid];
    const kind = pat.route.kind === SUBWAY ? 'train' : pat.route.express ? 'express bus' : 'bus';
    return `${pat.route.name} ${kind} from ${net.stops[leg.from].name} to ${net.stops[leg.to].name}, ${min} incl. wait`;
  });
}

// "foot" | "bus" | "subway" | "bus + subway": what a trip uses.
export function tripMode(net, trip) {
  const kinds = new Set(trip.legs.filter((l) => l.type === 'ride').map((l) => net.patterns[l.pid].route.kind));
  if (!kinds.size) return 'foot';
  if (kinds.size === 2) return 'bus + subway';
  return kinds.has(SUBWAY) ? 'subway' : 'bus';
}

// Ray casting over a GeoJSON Polygon or MultiPolygon geometry.
export function insideGeometry(geometry, p) {
  const polys = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.type === 'MultiPolygon' ? geometry.coordinates : [];
  const inRing = (ring) => {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i];
      const [xj, yj] = ring[j];
      if ((yi > p.lat) !== (yj > p.lat) && p.lon < ((xj - xi) * (p.lat - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  };
  return polys.some(([outer, ...holes]) => inRing(outer) && !holes.some(inRing));
}
