// Guided resource finder: three questions (what help, who for, where), then results as a list or a map.
// Data: Supabase public.resources only, read with the publishable key in config.js.
import { BOROUGHS, distinctValues, fetchRows, isListed, serviceColor, toResource } from './resources.js';
import { RADII, countBy, matchingResources, newFilters } from './filter.js';
import { cardHtml, escapeHtml, popupHtml } from './cards.js';
import { createPlaceInput } from './place-input.js';
import { createMap } from './map.js';
import { applyLocalPreview, isLocalPreview } from './preview.js';

const app = document.getElementById('app');
const statusEl = document.getElementById('status');
const LIST_PAGE = 100; // cards rendered per group before a "Show all" button

function showSetupHelp(reason, detail = '') {
  document.getElementById('setup-reason').textContent = reason;
  document.getElementById('setup-detail').textContent = detail ? `Technical detail: ${detail}` : '';
  document.getElementById('setup-help').hidden = false;
  statusEl.hidden = true;
  app.innerHTML = '';
}

// Turns a Supabase error into a sentence a teammate can act on.
function explainError(error) {
  const message = error?.message ?? String(error);
  if (/failed to fetch|networkerror|load failed/i.test(message)) {
    return 'The page could not reach the Supabase project. SUPABASE_URL in config.js may be wrong, or you may be offline.';
  }
  if (/invalid api key|no api key|jwt|unauthorized/i.test(message)) {
    return 'Supabase rejected the key. SUPABASE_PUBLISHABLE_KEY in config.js is missing, mistyped or from a different project.';
  }
  if (/could not find the table|does not exist/i.test(message)) {
    return 'The Supabase project has no resources table yet. Someone with database access needs to run supabase db push.';
  }
  return null;
}

// Returns a Supabase client, or null after showing why the page cannot connect.
function connect() {
  const config = window.APP_CONFIG;
  if (!config?.SUPABASE_URL || !config?.SUPABASE_PUBLISHABLE_KEY) {
    showSetupHelp('This page has no Supabase connection details: config.js is missing or does not set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY.');
    return null;
  }
  if (config.SUPABASE_PUBLISHABLE_KEY.startsWith('sb_secret_')) {
    showSetupHelp('config.js holds a secret key. Replace it with the publishable key (sb_publishable_…) and rotate the secret key in the Supabase dashboard, because it has been exposed.');
    return null;
  }
  if (!window.supabase?.createClient) {
    showSetupHelp('The Supabase library did not load from cdn.jsdelivr.net. Check your connection or any content blocker, then reload.');
    return null;
  }
  return window.supabase.createClient(config.SUPABASE_URL, config.SUPABASE_PUBLISHABLE_KEY);
}

// ---------- State ----------
const filters = newFilters();
let resources = [];
let serviceValues = [];
let audienceValues = [];
let step = 0; // 0-2: questions, 3: results
let tab = 'list';
let view = {}; // DOM helpers of the current screen: placeInput, map, list

const radiusLabel = (r) => (r ? `${r} mi` : 'any distance');
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const toggle = (set, value) => (set.has(value) ? set.delete(value) : set.add(value));

// ---------- Question steps ----------
function tilesHtml(facet, values) {
  return `<div class="tiles">${values.map((v) => `<button type="button" class="tile" data-facet="${facet}" data-value="${escapeHtml(v)}" aria-pressed="false">
      ${facet === 'services' ? `<span class="dot" style="background:${serviceColor(v)}"></span>` : ''}
      <span class="tile-label">${escapeHtml(v === 'true' ? 'Spanish-speaking staff' : v)}${facet === 'audiences' ? '<small class="count-open"></small>' : ''}</span><span class="count"></span>
    </button>`).join('')}</div>`;
}

const navHtml = `<div class="nav"><button type="button" data-nav="back">← Back</button><button type="button" class="go" data-nav="next"></button></div>`;

function stepHtml() {
  const head = (n, title, sub) => `<p class="progress">Question ${n} of 3</p><h1>${title}</h1><p class="sub">${sub}</p>`;
  if (step === 0) {
    return head(1, 'What kind of help are you looking for?', 'Pick any that apply, or skip to see everything.')
      + tilesHtml('services', serviceValues) + navHtml;
  }
  if (step === 1) {
    return head(2, 'Who is the help for?', 'Some organizations serve a specific group. Pick any that describe the person, or skip.')
      + tilesHtml('audiences', audienceValues)
      + '<h2>Language (optional)</h2>' + tilesHtml('spanish', ['true']) + navHtml;
  }
  return head(3, 'Where should it be?', 'Enter an address or ZIP, use your location, or click the map to drop a pin. You can also pick a borough.')
    + `<div id="step-place"></div>
      <div id="step-map" class="pick-map"></div>
      <h2>How far can you travel?</h2>
      <div class="pills">${RADII.map((r) => `<button type="button" class="pill" data-radius="${r}">${radiusLabel(r)}</button>`).join('')}</div>
      <h2>Or limit to a borough</h2>
      <div class="pills">${BOROUGHS.map((b) => `<button type="button" class="pill" data-borough="${b}">${b} <span class="count"></span></button>`).join('')}</div>
      <h2>Phone and online help</h2>
      <label class="chk"><input type="checkbox" id="include-remote"> Also show hotlines and online resources (they serve all of NYC)</label>
      ${navHtml}`;
}

function renderStep() {
  app.innerHTML = `<div class="wrap">${stepHtml()}</div>`;
  view = {};
  if (step === 2) {
    const map = createMap(document.getElementById('step-map'), {
      // No resource pins here: places show only after "Show N resources".
      onPick: (place) => { filters.place = place; view.placeInput.sync(); updateStep(); },
      popupHtml,
    });
    view.map = map;
    view.placeInput = createPlaceInput(document.getElementById('step-place'), {
      resources,
      getPlace: () => filters.place,
      onChange: (place) => { filters.place = place; updateStep(); },
    });
  }
  updateStep();
  window.scrollTo(0, 0);
}

// Refreshes counts, pressed states and the Next button without rebuilding the screen (so the map stays).
function updateStep() {
  const n = matchingResources(resources, filters).length;
  const counts = { services: countBy(resources, filters, 'services'), audiences: countBy(resources, filters, 'audiences'), spanish: countBy(resources, filters, 'spanish') };
  // Audience tiles show the resources for that group, and below the label how many open-to-everyone
  // resources picking it adds after them.
  const openCounts = countBy(resources, filters, 'audiences_open');
  for (const tile of app.querySelectorAll('.tile')) {
    const { facet, value } = tile.dataset;
    const selected = facet === 'spanish' ? filters.spanish : filters[facet].has(value);
    const count = counts[facet].get(facet === 'spanish' ? true : value) ?? 0;
    const open = facet === 'audiences' ? openCounts.get(value) ?? 0 : 0;
    tile.setAttribute('aria-pressed', String(selected));
    tile.querySelector('.count').textContent = count;
    const openEl = tile.querySelector('.count-open');
    if (openEl) openEl.textContent = open ? `+${open} open to all` : '';
    tile.disabled = !count && !open && !selected;
  }
  const back = app.querySelector('[data-nav=back]');
  back.style.visibility = step === 0 ? 'hidden' : '';
  const chosen = step === 0 ? filters.services.size : step === 1 ? filters.audiences.size || filters.spanish : 1;
  app.querySelector('[data-nav=next]').textContent = step === 2
    ? `Show ${plural(n, 'resource', 'resources')}`
    : `${chosen ? 'Next' : 'Skip'} · ${n} match so far`;
  if (step === 2) {
    const boroughCounts = countBy(resources, filters, 'boroughs');
    for (const b of app.querySelectorAll('[data-radius]')) b.setAttribute('aria-pressed', String(Number(b.dataset.radius) === filters.radius));
    for (const b of app.querySelectorAll('[data-borough]')) {
      const count = boroughCounts.get(b.dataset.borough) ?? 0;
      const selected = filters.boroughs.has(b.dataset.borough);
      b.setAttribute('aria-pressed', String(selected));
      b.querySelector('.count').textContent = count;
      b.disabled = !count && !selected;
    }
    document.getElementById('include-remote').checked = filters.how !== 'in_person';
    view.map?.setPlace(filters.place, filters.radius);
  }
}

// ---------- Results ----------
function renderResults() {
  app.innerHTML = `<div class="res">
    <header class="res-head">
      <div class="res-top"><p class="sentence" id="sentence"></p><button type="button" class="plain" id="restart">Start over</button></div>
      <div class="res-tools">
        <div class="res-where"><div id="res-place"></div>
          <select id="radius-select" aria-label="Distance">${RADII.map((r) => `<option value="${r}">${radiusLabel(r)}</option>`).join('')}</select></div>
        <input id="text-search" type="search" placeholder="Search within these results" aria-label="Search within these results">
        <button type="button" class="pill" id="spanish-toggle">Spanish-speaking</button>
      </div>
      <div class="res-tools">
        <div class="seg"><button type="button" data-tab="list">List</button><button type="button" data-tab="map">Map</button></div>
        <div class="seg" id="how"></div>
      </div>
    </header>
    <div class="res-body"><div class="res-list" id="res-list"></div><div class="res-map" id="res-map" hidden></div></div>
  </div>`;
  document.getElementById('radius-select').value = String(filters.radius);
  document.getElementById('text-search').value = filters.text;
  view = {
    placeInput: createPlaceInput(document.getElementById('res-place'), {
      resources,
      getPlace: () => filters.place,
      onChange: (place) => { filters.place = place; refreshResults(); },
    }),
    map: null,
    list: [],
  };
  setTab(tab);
  refreshResults();
  window.scrollTo(0, 0);
}

function sentenceHtml(n) {
  const link = (s, text) => `<button type="button" class="link" data-goto-step="${s}">${escapeHtml(text)}</button>`;
  const services = filters.services.size ? [...filters.services].join(' or ') : 'any kind of help';
  let who = filters.audiences.size ? [...filters.audiences].join(' or ') : 'anyone';
  if (filters.spanish) who += ', Spanish-speaking';
  const where = [
    filters.place ? (filters.radius ? `within ${filters.radius} mi of ${filters.place.label}` : `near ${filters.place.label}`) : '',
    filters.boroughs.size ? `in ${[...filters.boroughs].join(' or ')}` : '',
  ].filter(Boolean).join(' ') || 'anywhere';
  const noun = filters.how === 'in_person' ? ['place', 'places'] : ['resource', 'resources'];
  return `<strong>${plural(n, ...noun)}</strong> for ${link(0, services)} for ${link(1, who)}, ${link(2, where)}`;
}

function groupHtml(title, list, id) {
  if (!list.length) return '';
  const shown = list.slice(0, LIST_PAGE);
  return `<h3>${escapeHtml(title)} · ${list.length}</h3>
    <ul class="cards">${shown.map(cardItemHtml).join('')}</ul>
    ${list.length > LIST_PAGE ? `<button type="button" class="plain more" data-show-all="${id}">Show all ${list.length}</button>` : ''}`;
}

const cardItemHtml = (r) => `<li class="card${r.inPerson ? ' clickable' : ''}" data-index="${r.index}">${cardHtml(r)}</li>`;

// The list groups in-person resources (nearest first when a place is set) apart from phone/online ones.
function renderList(list) {
  const near = list.filter((r) => r.inPerson);
  const remote = list.filter((r) => !r.inPerson);
  document.getElementById('res-list').innerHTML = `<section>
    ${list.length ? '' : '<p class="empty">Nothing matches. Click a highlighted part of the sentence above to loosen it, or widen the distance.</p>'}
    ${groupHtml(filters.place ? 'Nearest first' : 'In person', near, 'near')}
    ${groupHtml('By phone or online', remote, 'remote')}
  </section>`;
}

function refreshResults() {
  const list = matchingResources(resources, filters);
  view.list = list;
  document.getElementById('sentence').innerHTML = sentenceHtml(list.length);
  const how = countBy(resources, filters, 'how');
  const inPerson = how.get('in_person') ?? 0;
  const remote = how.get('remote') ?? 0;
  document.getElementById('how').innerHTML = [['all', 'All', inPerson + remote], ['in_person', 'In person', inPerson], ['remote', 'Phone / online', remote]]
    .map(([k, label, n]) => `<button type="button" data-how="${k}" aria-pressed="${filters.how === k}">${label} · ${n}</button>`).join('');
  document.getElementById('spanish-toggle').setAttribute('aria-pressed', String(filters.spanish));
  renderList(list);
  view.map?.setResources(list, pinColor);
  view.map?.setPlace(filters.place, filters.radius);
}

// A single pin takes the colour of the first service type that matched Q1, else the row's first one.
const pinColor = (r) => serviceColor(r.services.find((s) => filters.services.has(s)) ?? r.services[0]);

function setTab(next) {
  tab = next;
  for (const b of app.querySelectorAll('[data-tab]')) b.setAttribute('aria-pressed', String(b.dataset.tab === tab));
  const mapEl = document.getElementById('res-map');
  document.getElementById('res-list').hidden = tab === 'map';
  mapEl.hidden = tab !== 'map';
  if (tab !== 'map') return;
  if (!view.map) {
    // Created on first use, so the tiles load only when someone opens the map.
    view.map = createMap(mapEl, {
      onPick: (place) => { filters.place = place; view.placeInput.sync(); refreshResults(); },
      popupHtml,
    });
    view.map?.setResources(view.list, pinColor);
    view.map?.setPlace(filters.place, filters.radius);
  }
  view.map?.resize();
  // On a phone the page scrolls and the map sits under the header; bring all of it on screen.
  if (mapEl.getBoundingClientRect().bottom > window.innerHeight) mapEl.scrollIntoView({ block: 'end' });
}

// ---------- Events (one listener per event type on #app) ----------
function render() {
  if (step < 3) renderStep();
  else renderResults();
}

app.addEventListener('click', async (e) => {
  const target = e.target.closest('button, .card.clickable');
  if (!target || e.target.closest('a')) return;
  const d = target.dataset;
  if (d.facet) {
    if (d.facet === 'spanish') filters.spanish = !filters.spanish;
    else toggle(filters[d.facet], d.value);
    updateStep();
  } else if (d.nav === 'back') {
    step -= 1;
    render();
  } else if (d.nav === 'next') {
    if (view.placeInput?.isPending()) {
      target.disabled = true;
      const ok = await view.placeInput.resolve();
      target.disabled = false;
      if (!ok) return;
    }
    step += 1;
    render();
  } else if (d.radius != null) {
    filters.radius = Number(d.radius);
    updateStep();
  } else if (d.borough) {
    toggle(filters.boroughs, d.borough);
    updateStep();
  } else if (d.gotoStep != null) {
    step = Number(d.gotoStep);
    render();
  } else if (d.tab) {
    setTab(d.tab);
  } else if (d.how) {
    filters.how = d.how;
    refreshResults();
  } else if (d.showAll) {
    target.previousElementSibling.insertAdjacentHTML('beforeend', view.list
      .filter((r) => (d.showAll === 'near') === r.inPerson).slice(LIST_PAGE)
      .map(cardItemHtml).join(''));
    target.remove();
  } else if (target.id === 'spanish-toggle') {
    filters.spanish = !filters.spanish;
    refreshResults();
  } else if (target.id === 'restart') {
    Object.assign(filters, newFilters());
    step = 0;
    tab = 'list';
    render();
  } else if (target.classList.contains('card')) {
    const r = view.list.find((x) => x.index === Number(d.index));
    if (!r) return;
    setTab('map');
    view.map?.show(r);
  }
});

app.addEventListener('change', (e) => {
  if (e.target.id === 'include-remote') {
    filters.how = e.target.checked ? 'all' : 'in_person';
    updateStep();
  } else if (e.target.id === 'radius-select') {
    filters.radius = Number(e.target.value);
    refreshResults();
  }
});

app.addEventListener('input', (e) => {
  if (e.target.id === 'text-search') {
    filters.text = e.target.value.trim();
    refreshResults();
  }
});

// ---------- Start ----------
async function main() {
  const db = connect();
  if (!db) return;
  let rows;
  try {
    rows = await fetchRows(db);
  } catch (error) {
    const reason = explainError(error);
    if (reason) showSetupHelp(reason, error.message);
    else {
      statusEl.textContent = `Supabase error: ${error.message ?? error}`;
      statusEl.classList.add('error');
    }
    return;
  }
  if (isLocalPreview()) {
    try {
      const preview = await applyLocalPreview(rows);
      app.insertAdjacentHTML('beforebegin', `<p class="preview-note">${escapeHtml(preview.summary)}</p>`);
    } catch (error) {
      statusEl.textContent = error.message;
      statusEl.classList.add('error');
      return;
    }
  }
  resources = rows.filter(isListed).map((row, i) => toResource(row, i));
  serviceValues = distinctValues(resources, 'services');
  audienceValues = distinctValues(resources, 'audiences');
  statusEl.hidden = true;
  render();
}

main();
