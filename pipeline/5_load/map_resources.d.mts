// Types for map_resources.mjs, so TypeScript tooling can import it. Keep in step with that file.

/** One row of public.resources: text, numbers, booleans and "; "-split lists, null when blank. */
export type ResourceRow = Record<string, string | number | boolean | string[] | null>;

export const TEXT_COLUMNS: Record<string, string>;
export const YES_NO_COLUMNS: Record<string, string>;
export const GEOCODE_COLUMNS: Record<string, string>;
export const EXTENDED_COLUMNS: Record<string, 'text' | 'list' | 'integer' | 'boolean'>;
export const AUDIENCE_COLUMNS: Record<string, 'text' | 'list' | 'integer' | 'boolean'>;
export const MERGED_FEATURE_INDEX: number;

export function parseCsv(text: string): string[][];
export function toText(value: string): string | null;
export function toBoolean(value: string, header: string, where: string): boolean | null;
export function toExtendedValue(value: string, type: string, column: string, where: string): ResourceRow[string];

export function mapResources(root: string): Promise<{
  records: ResourceRow[];
  paths: { geojson: string; extended: string; audiences: string; nomatch: string };
  counts: { geojson: number; extras: number; extended: number; unmatchedFeatures: number; audiences: number };
}>;
