// MapLibre map with OpenFreeMap tiles: a location pin with its radius circle, and optionally resource pins.
// The tiles are the background only; every pin comes from public.resources.
import { circle } from '../lib/geo.js';

const STYLE = 'https://tiles.openfreemap.org/styles/liberty';
const NYC_BOUNDS = [-74.26, 40.49, -73.7, 40.92];
const EMPTY = { type: 'FeatureCollection', features: [] };

// Resources at identical coordinates (several organizations in one building) share one pin.
export const pointKey = (r) => `${r.lat.toFixed(6)},${r.lon.toFixed(6)}`;

// Returns null when MapLibre did not load (app/vendor/ missing or blocked); callers then work without a map.
// onPick(place) fires on a click on empty map. popupHtml(group) builds the popup for one pin.
// layerPopupHtml(layer, props) builds the popup for one feature of a reference layer (see setLayer).
export function createMap(container, { onPick, popupHtml, layerPopupHtml } = {}) {
  if (!window.maplibregl) {
    container.innerHTML = '<p class="map-missing">The map could not load. The list still works.</p>';
    return null;
  }
  const map = new maplibregl.Map({ container, style: STYLE, bounds: NYC_BOUNDS, attributionControl: { compact: true } });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
  map.on('error', (e) => console.warn('Map error:', e.error?.message ?? e));

  let loaded = false;
  let place = null;
  let radius = 0;
  let groups = new Map();
  let colorOf = (r) => r.color;
  let marker = null;
  let popup = null;
  let fitPending = false;
  const refLayers = new Map(); // key → { layer, data: Promise<GeoJSON> | null, on }

  // Reference layers (libraries, health facilities, cooling sites) sit under the resource pins, as
  // smaller circles in the layer's colour. Their GeoJSON is fetched the first time they are switched on.
  async function drawRefLayer(key) {
    const ref = refLayers.get(key);
    const id = `ref-${key}`;
    if (!ref.on) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'none');
      return;
    }
    if (!map.getSource(id)) {
      ref.data ??= fetch(ref.layer.file).then((r) => (r.ok ? r.json() : EMPTY)).catch(() => EMPTY);
      const data = await ref.data;
      if (map.getSource(id) || !ref.on) return;
      map.addSource(id, { type: 'geojson', data });
      map.addLayer({ id, type: 'circle', source: id, paint: {
        'circle-color': ref.layer.color,
        'circle-opacity': 0.85,
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 3, 14, 5, 17, 7],
        'circle-stroke-width': 1,
        'circle-stroke-color': '#ffffff',
      } }, 'res');
      map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
    }
    map.setLayoutProperty(id, 'visibility', 'visible');
  }

  function openRefFeature(key, feature) {
    const ref = refLayers.get(key);
    if (!ref || !layerPopupHtml) return;
    popup?.remove();
    popup = new maplibregl.Popup({ maxWidth: '320px', focusAfterOpen: false })
      .setLngLat(feature.geometry.coordinates)
      .setHTML(layerPopupHtml(ref.layer, feature.properties))
      .addTo(map);
  }

  function drawPlace() {
    map.getSource('radius').setData(place && radius ? circle(place, radius) : EMPTY);
    if (place) {
      marker ??= new maplibregl.Marker({ color: '#b91c1c' });
      marker.setLngLat([place.lon, place.lat]).addTo(map);
    } else {
      marker?.remove();
    }
    if (place && fitPending) {
      const r = radius || 3;
      map.fitBounds([[place.lon - r / 45, place.lat - r / 60], [place.lon + r / 45, place.lat + r / 60]], { padding: 30, duration: 500 });
    }
    fitPending = false;
  }

  function drawResources() {
    const features = [...groups].map(([key, group]) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [group[0].lon, group[0].lat] },
      properties: { key, count: group.length, color: group.length > 1 ? '#1c1917' : colorOf(group[0]) },
    }));
    map.getSource('res').setData({ type: 'FeatureCollection', features });
  }

  // Moves the pin to near the bottom of the map and opens its popup above it, so the popup has the
  // map's full height to fit in. `zoom` is optional.
  function openGroup(key, zoom) {
    const group = groups.get(key);
    if (!group) return;
    const center = [group[0].lon, group[0].lat];
    popup?.remove();
    map.easeTo({ center, zoom, offset: [0, map.getContainer().clientHeight / 2 - 40], duration: 500 });
    popup = new maplibregl.Popup({ maxWidth: '320px', anchor: 'bottom', focusAfterOpen: false })
      .setLngLat(center)
      .setHTML(popupHtml(group))
      .addTo(map);
  }

  map.on('load', () => {
    map.addSource('radius', { type: 'geojson', data: EMPTY });
    map.addLayer({ id: 'radius-fill', type: 'fill', source: 'radius', paint: { 'fill-color': '#b91c1c', 'fill-opacity': 0.06 } });
    map.addLayer({ id: 'radius-line', type: 'line', source: 'radius', paint: { 'line-color': '#b91c1c', 'line-width': 1.5, 'line-dasharray': [2, 2] } });
    map.addSource('res', { type: 'geojson', data: EMPTY });
    const shared = ['>', ['get', 'count'], 1];
    map.addLayer({ id: 'res', type: 'circle', source: 'res', paint: {
      'circle-color': ['get', 'color'],
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, ['case', shared, 9, 5], 14, ['case', shared, 11, 8], 17, ['case', shared, 14, 11]],
      'circle-stroke-width': 2,
      'circle-stroke-color': '#ffffff',
    } });
    map.addLayer({ id: 'res-count', type: 'symbol', source: 'res', filter: shared,
      layout: { 'text-field': ['to-string', ['get', 'count']], 'text-font': ['Noto Sans Bold'], 'text-size': 11, 'text-allow-overlap': true, 'text-ignore-placement': true },
      paint: { 'text-color': '#ffffff' } });
    map.on('click', (e) => {
      const hit = map.queryRenderedFeatures(e.point, { layers: ['res'] })[0];
      const refIds = [...refLayers.keys()].map((k) => `ref-${k}`).filter((id) => map.getLayer(id));
      const refHit = hit ? null : map.queryRenderedFeatures(e.point, { layers: refIds })[0];
      if (hit) openGroup(hit.properties.key);
      else if (refHit) openRefFeature(refHit.layer.id.slice(4), refHit);
      else onPick?.({ lat: e.lngLat.lat, lon: e.lngLat.lng, label: `pin at ${e.lngLat.lat.toFixed(4)}, ${e.lngLat.lng.toFixed(4)}` });
    });
    map.on('mouseenter', 'res', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'res', () => { map.getCanvas().style.cursor = ''; });
    loaded = true;
    drawPlace();
    drawResources();
    for (const key of refLayers.keys()) drawRefLayer(key);
  });

  return {
    // Moves the pin and circle. The map zooms to them only when the place or radius changed.
    setPlace(nextPlace, nextRadius) {
      if (nextPlace !== place || nextRadius !== radius) fitPending = Boolean(nextPlace);
      place = nextPlace;
      radius = nextRadius;
      if (loaded) drawPlace();
    },
    // Draws one pin per distinct coordinate among the in-person resources of `list`.
    // pinColor(r) picks a single pin's colour; shared pins are dark with a count.
    setResources(list, pinColor = (r) => r.color) {
      colorOf = pinColor;
      groups = new Map();
      for (const r of list) {
        if (!r.inPerson) continue;
        const key = pointKey(r);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(r);
      }
      popup?.remove();
      if (loaded) drawResources();
    },
    // Centers on r and opens the popup of the pin it shares.
    show(r) {
      if (!r.inPerson) return;
      const go = () => openGroup(pointKey(r), Math.max(map.getZoom(), 14));
      if (loaded) go();
      else map.once('load', go);
    },
    // Shows or hides a reference layer. `layer` is its entry in data/public/layers/index.json
    // ({ key, file, color, label, ... }); its features load on the first show.
    setLayer(layer, on) {
      const ref = refLayers.get(layer.key) ?? { layer, data: null, on: false };
      ref.on = on;
      refLayers.set(layer.key, ref);
      if (loaded) drawRefLayer(layer.key);
    },
    resize() { map.resize(); },
  };
}
