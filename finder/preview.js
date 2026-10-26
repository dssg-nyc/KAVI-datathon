// Local data: the finder reads data/kavi_resources.csv (a public.resources export)
// for map pins and filters. Set RESOURCES_CSV in config.js, or open ?preview=local.
// The file is not written anywhere. Needs the repo served as static files
// (npm run dev, or python3 -m http.server 5173 --bind 127.0.0.1).

import { fetchKaviRows, KAVI_CSV_PATH } from './csv.js';

export const isLocalPreview = () => new URLSearchParams(location.search).get('preview') === 'local';

export function localCsvPath() {
  return window.APP_CONFIG?.RESOURCES_CSV || (isLocalPreview() ? KAVI_CSV_PATH : '');
}

export async function loadLocalCsv() {
  const path = localCsvPath();
  if (!path) return null;
  const { rows, report } = await fetchKaviRows(path);
  if (report.stats.missingColumns.length) {
    throw new Error(`Local CSV is missing columns the map needs: ${report.stats.missingColumns.join(', ')}`);
  }
  const pins = report.stats.listedWithCoords;
  const listed = report.stats.listed;
  const problems = report.issues.length ? ` · ${report.issues.length} schema issue${report.issues.length === 1 ? '' : 's'}` : '';
  return {
    rows,
    report,
    summary: `Map pins from ${path} · ${pins} geocoded of ${listed} listed resources${problems}`,
  };
}
