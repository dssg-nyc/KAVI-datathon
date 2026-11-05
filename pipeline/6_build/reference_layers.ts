// Downloads the supplementary ArcGIS layers (PRD section 8) into data/public/layers/, so the finder can
// draw them without talking to ArcGIS Online at run time (requirement R3) and a change in them shows up
// as a diff. Each layer becomes a GeoJSON file of Point features with three or four small properties,
// one feature per line, plus data/public/layers/index.json that lists the layers for the finder.
//
//   node pipeline/6_build/reference_layers.ts    download all three and write the files
//
// Needs the network. The files are committed; rerun this when the layers change on ArcGIS Online.
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const root = join(import.meta.dirname, '..', '..');
export const LAYERS_DIR = join(root, 'data', 'public', 'layers');
export const INDEX_PATH = join(LAYERS_DIR, 'index.json');

const ARCGIS = 'https://services6.arcgis.com/OO2s4OoyCZkYJ6oE/arcgis/rest/services';
const PAGE = 2000; // the services' maxRecordCount

type Props = Record<string, string | number | null>;
export type LayerFeature = {
  type: 'Feature';
  geometry: { type: 'Point'; coordinates: [number, number] };
  properties: { name: string; address: string | null; kind: string | null; status?: string | null };
};
export type LayerSpec = {
  key: string;
  label: string; // the toggle's text in the finder
  note: string; // what the layer is, shown as the toggle's title
  color: string;
  service: string; // the FeatureServer name on ArcGIS Online
  source: string; // where ArcGIS Online got it, for the attribution line
  toFeature: (props: Props, coordinates: [number, number]) => LayerFeature;
};

// "GREENPOINT LIBRARY" → "Greenpoint Library"; the Facilities Database shouts.
export function titleCase(s: string | number | null | undefined): string {
  return String(s ?? '').toLowerCase().replace(/(^|[\s\-/(])([a-z])/g, (m, before, c) => before + c.toUpperCase()).trim();
}

const point = (coordinates: [number, number], properties: LayerFeature['properties']): LayerFeature => ({
  type: 'Feature', geometry: { type: 'Point', coordinates }, properties,
});

// The NYC Facilities Database rows (libraries, health facilities) share one layout.
function facility(props: Props, coordinates: [number, number], kind: string | null): LayerFeature {
  const address = [titleCase(props.ADDRESS), [titleCase(props.CITY), props.ZIPCODE].filter(Boolean).join(' ')].filter(Boolean).join(', ');
  return point(coordinates, { name: titleCase(props.FACNAME), address: address || null, kind });
}

export const LAYERS: LayerSpec[] = [
  {
    key: 'libraries',
    label: 'Libraries',
    note: 'Public library branches (NYC Facilities Database)',
    color: '#7c3aed',
    service: 'public_libraries_points',
    source: 'NYC Department of City Planning Facilities Database, via the DSSG NYC ArcGIS Online layer public_libraries_points',
    toFeature: (p, c) => facility(p, c, p.OPNAME ? String(p.OPNAME) : null),
  },
  {
    key: 'health_facilities',
    label: 'Health facilities',
    note: 'Hospitals, clinics, mental health and substance use programs (NYC Facilities Database)',
    color: '#0891b2',
    service: 'health_facilities_points',
    source: 'NYC Department of City Planning Facilities Database, via the DSSG NYC ArcGIS Online layer health_facilities_points',
    toFeature: (p, c) => facility(p, c, p.FACTYPE ? titleCase(p.FACTYPE) : null),
  },
  {
    key: 'cooling_sites',
    label: 'Cooling sites',
    note: 'NYC Parks spray showers, misting stations and other outdoor cooling sites; not indoor cooling centers',
    color: '#2563eb',
    service: 'Cooling_Sites_points',
    source: 'NYC Parks cooling sites, via the DSSG NYC ArcGIS Online layer Cooling_Sites_points',
    toFeature: (p, c) => point(c, {
      name: [p.PropertyName, p.SubPropertyName].filter(Boolean).map(String).join(': '),
      address: p.Borough ? String(p.Borough) : null,
      kind: p.FeatureType ? String(p.FeatureType) : null,
      status: p.Status ? String(p.Status) : null,
    }),
  },
];

type EsriFeature = { geometry?: { type: string; coordinates: [number, number] } | null; properties: Props };

export async function fetchLayer(layer: LayerSpec): Promise<LayerFeature[]> {
  const features: LayerFeature[] = [];
  for (let offset = 0; ; offset += PAGE) {
    const url = `${ARCGIS}/${layer.service}/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&f=geojson&resultOffset=${offset}&resultRecordCount=${PAGE}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${layer.service}: HTTP ${response.status}`);
    const data = (await response.json()) as { features?: EsriFeature[]; error?: { message: string } };
    if (data.error) throw new Error(`${layer.service}: ${data.error.message}`);
    const page = data.features ?? [];
    for (const f of page) {
      if (f.geometry?.type !== 'Point') continue;
      const feature = layer.toFeature(f.properties, f.geometry.coordinates);
      if (feature.properties.name) features.push(feature);
    }
    if (page.length < PAGE) return features;
  }
}

// One feature per line, so a refresh is a readable diff.
export function toGeoJson(features: LayerFeature[]): string {
  return `{"type":"FeatureCollection","features":[\n${features.map((f) => JSON.stringify(f)).join(',\n')}\n]}\n`;
}

export const layerPath = (layer: LayerSpec) => join(LAYERS_DIR, `${layer.key}.geojson`);

// The index the finder reads: one entry per layer. `fetched` is the day the features last changed.
export async function indexJson(counts: Record<string, number>, changed: Record<string, boolean>, today = new Date()): Promise<string> {
  const current = await readFile(INDEX_PATH, 'utf8').then((t) => JSON.parse(t) as { key: string; fetched: string }[]).catch(() => []);
  const date = today.toISOString().slice(0, 10);
  const entries = LAYERS.map(({ key, label, note, color, source }) => ({
    key, label, note, color, file: `data/public/layers/${key}.geojson`, count: counts[key], source,
    fetched: changed[key] ? date : (current.find((e) => e.key === key)?.fetched ?? date),
  }));
  return `${JSON.stringify(entries, null, 2)}\n`;
}

async function main(): Promise<void> {
  await mkdir(LAYERS_DIR, { recursive: true });
  const counts: Record<string, number> = {};
  const changed: Record<string, boolean> = {};
  for (const layer of LAYERS) {
    const features = await fetchLayer(layer);
    const content = toGeoJson(features);
    const path = layerPath(layer);
    changed[layer.key] = (await readFile(path, 'utf8').catch(() => '')) !== content;
    counts[layer.key] = features.length;
    if (changed[layer.key]) await writeFile(path, content);
    console.log(`${layer.key}: ${features.length} features${changed[layer.key] ? ', written' : ', unchanged'}`);
  }
  await writeFile(INDEX_PATH, await indexJson(counts, changed));
  console.log(`Wrote ${INDEX_PATH}`);
}

if (process.argv[1] === import.meta.filename) await main();
