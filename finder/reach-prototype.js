// PROTOTYPE, throwaway. Page script for reach-prototype.html: pick a place, a time limit and the
// client's transport, then list which in-person resources from Supabase public.resources they can reach.
// The trip search is in reach-prototype-engine.js. The on-foot area comes from the public Valhalla
// server (valhalla1.openstreetmap.de), which follows real streets and, for wheelchairs, avoids steps.
import { fetchRows, isListed, toResource } from './resources.js';
import { escapeHtml } from './cards.js';
import { createPlaceInput } from './place-input.js';
import { DEFAULTS, buildNetwork, bestTrip, describeLegs, insideGeometry, metres, searchFrom, stopsNear, tripMode } from './reach-prototype-engine.js';

const VALHALLA = 'https://valhalla1.openstreetmap.de/isochrone';
const STYLE = 'https://tiles.openfreemap.org/styles/liberty';
const MINUTES = [15, 30, 45, 60, 90];
const MODE_COLOR = { foot: '#0f766e', bus: '#2563eb', subway: '#c2410c', 'bus + subway': '#7c3aed' };
const EMPTY = { type: 'FeatureCollection', features: [] };
const ASSUMPTIONS = [
  ['walkKmh', 'Walking speed (km/h)'],
  ['wheelchairKmh', 'Wheelchair speed (km/h)'],
  ['detour', 'Street detour factor'],
  ['busKmh', 'Bus speed incl. stops (km/h)'],
  ['subwayKmh', 'Subway speed incl. stops (km/h)'],
  ['busWaitMin', 'Wait per bus boarding (min)'],
  ['subwayWaitMin', 'Wait per train boarding (min)'],
  ['transferMaxM', 'Max transfer distance (m)'],
  ['maxFootToStopMin', 'Max time to/from a stop (min)'],
];

const state = {
  place: null,
  minutes: 45,
  wheelchair: false, bus: true, subway: true, express: false,
  ...DEFAULTS,
  footArea: null, // Valhalla isochrone geometry for the current place, minutes and wheelchair setting
  footAreaKey: '',
  selected: null,
};
let net;
let resources = [];
let map;
let mapReady = false;
let lastResults = [];

const $ = (id) => document.getElementById(id);

// ---------- Controls ----------
function renderControls() {
  $('minutes').innerHTML = MINUTES.map((m) => `<button type="button" class="pill" data-min="${m}" aria-pressed="${m === state.minutes}">${m} min</button>`).join('');
  $('transfers').innerHTML = [0, 1, 2].map((n) => `<button type="button" data-tr="${n}" aria-pressed="${n === state.maxTransfers}">${n === 0 ? 'None' : n}</button>`).join('');
  $('assume').innerHTML = ASSUMPTIONS.map(([k, label]) => `<label for="a-${k}">${label}</label><input id="a-${k}" data-assume="${k}" type="number" step="any" value="${state[k]}">`).join('');
}

document.addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (b?.dataset.min) { state.minutes = Number(b.dataset.min); renderControls(); update(); }
  else if (b?.dataset.tr) { state.maxTransfers = Number(b.dataset.tr); renderControls(); update(); }
  const card = e.target.closest('.card[data-id]');
  if (card && !e.target.closest('a')) select(Number(card.dataset.id));
});
document.addEventListener('change', (e) => {
  if (['wheelchair', 'bus', 'subway', 'express'].includes(e.target.id)) { state[e.target.id] = e.target.checked; update(); }
  if (e.target.dataset.assume) { state[e.target.dataset.assume] = Number(e.target.value); update(); }
});

// ---------- On-foot area (Valhalla) ----------
async function loadFootArea() {
  const key = state.place && `${state.place.lat},${state.place.lon},${state.minutes},${state.wheelchair},${state.walkKmh},${state.wheelchairKmh}`;
  if (!key || key === state.footAreaKey) return;
  state.footAreaKey = key;
  state.footArea = null;
  const pedestrian = state.wheelchair ? { type: 'wheelchair', walking_speed: state.wheelchairKmh } : { walking_speed: state.walkKmh };
  const body = { locations: [{ lat: state.place.lat, lon: state.place.lon }], costing: 'pedestrian', costing_options: { pedestrian }, contours: [{ time: state.minutes }], polygons: true };
  try {
    const res = await fetch(`${VALHALLA}?json=${encodeURIComponent(JSON.stringify(body))}`);
    if (!res.ok) throw new Error(`Valhalla HTTP ${res.status}`);
    const geo = await res.json();
    if (state.footAreaKey === key) { state.footArea = geo.features?.[0]?.geometry ?? null; update(false); }
  } catch (error) {
    console.warn('On-foot area failed; using straight-line estimates only:', error);
  }
}

// ---------- Search and results ----------
function update(refetch = true) {
  if (!state.place) {
    $('results').innerHTML = '<p class="summary">Enter an address, or click the map, to see what the client can reach.</p>';
    drawMap([], null);
    return;
  }
  if (refetch) loadFootArea();
  const t0 = performance.now();
  const search = searchFrom(net, state.place, state);
  const inPerson = resources.filter((r) => r.inPerson);
  const results = inPerson.map((r) => {
    const inside = state.footArea ? insideGeometry(state.footArea, r) : undefined;
    const trip = bestTrip(net, search, r, inside);
    return { r, trip, mode: trip ? tripMode(net, trip) : null };
  });
  const ms = Math.round(performance.now() - t0);
  const reachable = results.filter((x) => x.trip).sort((a, b) => a.trip.t - b.trip.t);
  lastResults = reachable;
  const byMode = {};
  for (const x of reachable) byMode[x.mode] = (byMode[x.mode] ?? 0) + 1;
  const remote = resources.length - inPerson.length;

  const nearbySubway = stopsNear(net, state.place, 1200).filter(({ stop }) => stop.kind === 1);
  // "Fordham Rd (4)" and "Fordham Rd (B D)" are different stations, so each name carries its lines.
  const lines = (stop) => [...new Set(stop.patterns.map(([pid]) => net.patterns[pid].route.name))].sort().join(' ');
  const stationNames = (ok) => [...new Set(nearbySubway.filter(({ stop }) => stop.accessible === ok).map(({ stop }) => `${stop.name} (${lines(stop)})`))];
  const stateLines = [
    `search ${ms} ms · on-foot area: ${state.footArea ? 'Valhalla streets' : 'straight-line estimate (Valhalla not loaded yet)'}`,
    `stops reachable on foot as a first leg: ${search.stats.stopsOnFoot}`,
    ...search.stats.rounds.map((r, i) => `ride ${i + 1}: boarded at ${r.boardedFrom} stops, reached ${r.stopsReached}`),
    `subway platforms within 1.2 km: ${nearbySubway.length} (accessible: ${stationNames(true).join(', ') || 'none'}${state.wheelchair ? `; not usable in a wheelchair: ${stationNames(false).join(', ') || 'none'}` : ''})`,
  ];

  $('results').innerHTML = `
    <p class="summary"><strong>${reachable.length} of ${inPerson.length}</strong> in-person resources reachable within ${state.minutes} min${state.wheelchair ? ' by wheelchair' : ''}.</p>
    <div class="modes">${Object.entries(byMode).map(([m, n]) => `<span class="mode" style="background:${MODE_COLOR[m]}">${m}: ${n}</span>`).join('')}</div>
    <p class="meta">${remote} more are by phone, mail or online and need no travel.</p>
    <div class="state">${escapeHtml(stateLines.join('\n'))}</div>
    <ul class="cards" style="margin-top:12px">${reachable.map(cardHtml).join('')}</ul>`;
  drawMap(results, search);
  if (state.selected != null && !reachable.some((x) => x.r.id === state.selected)) state.selected = null;
  if (state.selected != null) select(state.selected, false);
}

function cardHtml({ r, trip, mode }) {
  return `<li class="card clickable${r.id === state.selected ? ' sel' : ''}" data-id="${r.id}">
    <div class="card-head"><strong>${escapeHtml(r.name)}</strong><span class="dist" style="color:${MODE_COLOR[mode]}">${Math.round(trip.t)} min · ${mode}</span></div>
    ${r.address ? `<div class="meta">${escapeHtml(r.address)}</div>` : ''}
    ${r.services.length ? `<div class="meta">${escapeHtml(r.services.join(', '))}</div>` : ''}
    <ol class="legs">${describeLegs(net, trip.legs, state.wheelchair).map((l) => `<li>${escapeHtml(l)}</li>`).join('')}</ol>
  </li>`;
}

// ---------- Map ----------
function initMap() {
  if (!window.maplibregl) { $('map').innerHTML = '<p class="map-missing">The map could not load.</p>'; return; }
  map = new maplibregl.Map({ container: 'map', style: STYLE, bounds: [-74.26, 40.49, -73.7, 40.92], attributionControl: { compact: true } });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
  map.on('load', () => {
    for (const id of ['area', 'res', 'stations', 'trip']) map.addSource(id, { type: 'geojson', data: EMPTY });
    map.addLayer({ id: 'area-fill', type: 'fill', source: 'area', paint: { 'fill-color': '#0f766e', 'fill-opacity': 0.08 } });
    map.addLayer({ id: 'area-line', type: 'line', source: 'area', paint: { 'line-color': '#0f766e', 'line-width': 1.5 } });
    map.addLayer({ id: 'res', type: 'circle', source: 'res', paint: {
      'circle-color': ['get', 'color'], 'circle-radius': ['case', ['get', 'reach'], 6, 3.5],
      'circle-opacity': ['case', ['get', 'reach'], 1, 0.5], 'circle-stroke-width': ['case', ['get', 'reach'], 1.5, 0], 'circle-stroke-color': '#fff' } });
    map.addLayer({ id: 'stations', type: 'circle', source: 'stations', paint: {
      'circle-color': ['case', ['get', 'ok'], '#16a34a', '#dc2626'], 'circle-radius': 5, 'circle-stroke-width': 2, 'circle-stroke-color': '#fff' } });
    map.addLayer({ id: 'trip-ride', type: 'line', source: 'trip', filter: ['get', 'ride'], paint: { 'line-color': ['get', 'color'], 'line-width': 5 } });
    map.addLayer({ id: 'trip-foot', type: 'line', source: 'trip', filter: ['!', ['get', 'ride']], paint: { 'line-color': ['get', 'color'], 'line-width': 3, 'line-dasharray': [1.5, 1.5] } });
    map.on('click', (e) => {
      const hit = map.queryRenderedFeatures(e.point, { layers: ['res'] })[0];
      if (hit?.properties.reach) { select(hit.properties.id); return; }
      if (hit) { new maplibregl.Popup().setLngLat(e.lngLat).setHTML(`<strong>${escapeHtml(hit.properties.name)}</strong><br>Not reachable within ${state.minutes} min`).addTo(map); return; }
      setPlace({ lat: e.lngLat.lat, lon: e.lngLat.lng, label: `pin at ${e.lngLat.lat.toFixed(4)}, ${e.lngLat.lng.toFixed(4)}` });
      placeInput.sync();
    });
    mapReady = true;
    update(false);
  });
}

let marker;
function drawMap(results, search) {
  if (!mapReady) return;
  map.getSource('area').setData(state.footArea ? { type: 'Feature', geometry: state.footArea, properties: {} } : EMPTY);
  map.getSource('res').setData({ type: 'FeatureCollection', features: results.map(({ r, trip, mode }) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [r.lon, r.lat] },
    properties: { id: r.id, name: r.name, reach: Boolean(trip), color: trip ? MODE_COLOR[mode] : '#9ca3af' } })) });
  const near = search && state.subway ? stopsNear(net, state.place, 1200).filter(({ stop }) => stop.kind === 1) : [];
  map.getSource('stations').setData({ type: 'FeatureCollection', features: near.map(({ stop }) => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [stop.lon, stop.lat] }, properties: { ok: !state.wheelchair || stop.accessible } })) });
  if (!state.selected) map.getSource('trip').setData(EMPTY);
  if (state.place) {
    marker ??= new maplibregl.Marker({ color: '#b91c1c' });
    marker.setLngLat([state.place.lon, state.place.lat]).addTo(map);
  } else marker?.remove();
}

function select(id, fly = true) {
  state.selected = id;
  for (const c of document.querySelectorAll('.card[data-id]')) c.classList.toggle('sel', Number(c.dataset.id) === id);
  const x = lastResults.find((y) => y.r.id === id);
  if (!x || !mapReady) return;
  const features = [];
  let at = state.place;
  for (const leg of x.trip.legs) {
    if (leg.type === 'ride') {
      const pat = net.patterns[leg.pid];
      const coords = pat.stops.slice(leg.fromPos, leg.toPos + 1).map((s) => [net.stops[s].lon, net.stops[s].lat]);
      features.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: coords }, properties: { ride: true, color: pat.route.color } });
      at = net.stops[leg.to];
    } else {
      const to = leg.to == null ? x.r : net.stops[leg.to];
      features.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: [[at.lon, at.lat], [to.lon, to.lat]] }, properties: { ride: false, color: '#111827' } });
      at = to;
    }
  }
  map.getSource('trip').setData({ type: 'FeatureCollection', features });
  if (fly) {
    const pts = features.flatMap((f) => f.geometry.coordinates);
    const lons = pts.map((p) => p[0]);
    const lats = pts.map((p) => p[1]);
    map.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], { padding: 60, duration: 500, maxZoom: 15 });
  }
}

let placeInput;
function setPlace(place) {
  state.place = place;
  state.selected = null;
  update();
  if (place && mapReady) map.easeTo({ center: [place.lon, place.lat], zoom: 12.5, duration: 500 });
}

// ---------- Start ----------
async function main() {
  const db = window.supabase.createClient(window.APP_CONFIG.SUPABASE_URL, window.APP_CONFIG.SUPABASE_PUBLISHABLE_KEY);
  const [rows, transit] = await Promise.all([
    fetchRows(db),
    fetch('data/prototype/reach_transit_PROTOTYPE.json').then((r) => r.json()),
  ]);
  resources = rows.filter(isListed).map((row, i) => toResource(row, i));
  net = buildNetwork(transit);
  $('status').hidden = true;
  $('app').hidden = false;
  renderControls();
  placeInput = createPlaceInput($('place'), { resources, getPlace: () => state.place, onChange: setPlace });
  initMap();
  update();
}

main().catch((error) => {
  $('status').textContent = `Could not start: ${error.message ?? error}`;
  $('status').classList.add('error');
});

// For poking at the search from the console.
window.reach = { state, metres, get net() { return net; }, get map() { return map; } };
