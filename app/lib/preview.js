// Local data: the finder reads data/public/resources.public.json (written by the
// pipeline) for map pins and filters. Set RESOURCES_FILE in app/config.js, or open
// ?preview=local. A .csv path (a public.resources export) still works. Nothing is
// written anywhere. Needs the repo served with npm run dev.

import { fetchKaviRows, PUBLIC_JSON_PATH } from './csv.js';

export const isLocalPreview = () => new URLSearchParams(location.search).get('preview') === 'local';

export function localCsvPath() {
  const config = window.APP_CONFIG ?? {};
  return config.RESOURCES_FILE || config.RESOURCES_CSV || (isLocalPreview() ? PUBLIC_JSON_PATH : '');
}

export async function loadLocalCsv() {
  const path = localCsvPath();
  if (!path) return null;
  const { rows, report } = await fetchKaviRows(path);
  if (report.stats.missingColumns.length) {
    throw new Error(`${path} is missing columns the map needs: ${report.stats.missingColumns.join(', ')}`);
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
