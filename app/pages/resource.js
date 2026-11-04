// One resource's page: resource.html?id=<stable id>. Reads the same data file as the finder
// (RESOURCES_FILE in app/config.js, else data/public/resources.public.json), finds the row by id,
// and shows the finder's card for it with a map when it has a point. The id comes from
// data/resource_ids.csv, so a link keeps working when the data is rebuilt.
import { fetchKaviRows, PUBLIC_JSON_PATH } from '../lib/csv.js';
import { localCsvPath } from '../lib/preview.js';
import { isListed, toResource } from '../lib/resources.js';
import { findRow, idFromSearch, pageTitle } from '../lib/share.js';
import { cardHtml, escapeHtml, popupHtml } from '../components/cards.js';
import { createMap } from '../components/map.js';

const app = document.getElementById('app');
const statusEl = document.getElementById('status');

function fail(message) {
  statusEl.textContent = message;
  statusEl.classList.add('error');
}

function notFound(id) {
  document.title = pageTitle(null);
  statusEl.hidden = true;
  app.innerHTML = `<p class="crumbs"><a href="/finder.html">← Find resources</a></p>
    <p class="empty">${id ? `There is no resource with the id <strong>${escapeHtml(id)}</strong>.` : 'This page needs a resource id in its address, like <code>resource.html?id=176</code>.'}
    It may have been removed from the guide, or the link may be incomplete. <a href="/finder.html">Search the finder</a> instead.</p>`;
}

function render(resource) {
  document.title = pageTitle(resource);
  statusEl.hidden = true;
  const url = location.href;
  app.innerHTML = `<p class="crumbs"><a href="/finder.html">← Find resources</a></p>
    <article class="card">${cardHtml(resource, { link: false })}</article>
    ${resource.inPerson ? '<div class="detail-map" id="detail-map" role="region" aria-label="Map"></div>' : ''}
    <div class="share">
      <label for="share-url">Link to this resource</label>
      <input id="share-url" type="text" readonly value="${escapeHtml(url)}">
      <button type="button" class="plain" id="copy">Copy</button>
      <span class="note" id="copy-note" aria-live="polite"></span>
    </div>`;
  document.getElementById('copy').addEventListener('click', async () => {
    const note = document.getElementById('copy-note');
    const input = document.getElementById('share-url');
    try {
      await navigator.clipboard.writeText(url);
      note.textContent = 'Copied';
    } catch {
      input.select();
      note.textContent = 'Select the link and copy it';
    }
  });
  if (resource.inPerson) {
    const map = createMap(document.getElementById('detail-map'), { popupHtml });
    map?.setResources([resource]);
    map?.show(resource);
  }
}

async function main() {
  const id = idFromSearch(location.search);
  if (!id) return notFound('');
  let rows;
  try {
    ({ rows } = await fetchKaviRows(localCsvPath() || PUBLIC_JSON_PATH));
  } catch (error) {
    return fail(error.message);
  }
  const row = findRow(rows, id);
  if (!row || !isListed(row)) return notFound(id);
  render(toResource(row, rows.indexOf(row)));
}

main();
