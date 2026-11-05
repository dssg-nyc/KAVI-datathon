// Reference layers on the finder's map: libraries, health facilities and cooling sites (PRD 7.1), drawn
// from the files pipeline/6_build/reference_layers.ts downloads into data/public/layers/. The index lists
// them; a layer's features are fetched the first time someone switches it on. No UI here.
import { escapeHtml } from '../components/cards.js';

export const LAYER_INDEX_PATH = 'data/public/layers/index.json';

/**
 * One entry of data/public/layers/index.json.
 * @typedef {object} LayerInfo
 * @property {string} key
 * @property {string} label the toggle's text
 * @property {string} note what the layer is
 * @property {string} color
 * @property {string} file path of its GeoJSON, relative to the site root
 * @property {number} count
 * @property {string} source
 * @property {string} fetched YYYY-MM-DD
 */

// The layer index, or [] when it cannot be read: the finder then shows no layer toggles.
export async function fetchLayerIndex(path = LAYER_INDEX_PATH) {
  try {
    const response = await fetch(path, { cache: 'no-store' });
    const data = response.ok ? await response.json() : null;
    return Array.isArray(data) ? data.filter((l) => l.key && l.label && l.file) : [];
  } catch {
    return [];
  }
}

// The popup for one feature of a reference layer. `props` is its properties; `layer` its index entry.
export function layerPopupHtml(layer, props) {
  const kind = [props.kind, props.status && props.status !== 'Activated' ? props.status.toLowerCase() : ''].filter(Boolean).join(', ');
  return `<div class="card-head"><strong>${escapeHtml(props.name)}</strong></div>
    ${props.address ? `<div class="meta">${escapeHtml(props.address)}</div>` : ''}
    ${kind ? `<div class="meta">${escapeHtml(kind)}</div>` : ''}
    <div class="meta">${escapeHtml(layer.label)} layer, not from the Connections guide</div>`;
}
