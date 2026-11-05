// Static checks on the three public pages (landing, finder, resource page) for the accessibility and
// performance requirements in docs/technical-requirements.md (A1, P1, R3). They read the HTML and the
// files it references; nothing is rendered. The browser audit (Lighthouse) is `npm run audit`.
// Run: node --test app/pages/__tests__/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { gzipSync } from 'node:zlib';

const root = new URL('../../../', import.meta.url);
const PAGES = ['index.html', 'finder.html', 'resource.html', 'privacy.html'];
const html = Object.fromEntries(await Promise.all(PAGES.map(async (p) => [p, await readFile(new URL(`app/pages/${p}`, root), 'utf8')])));

// Every /app/... or data/... file a page loads up front: stylesheets, scripts and the data file the
// finder fetches first. Module imports are followed one level deep from the entry script's static imports.
async function loadedFiles(page) {
  const files = new Set();
  for (const m of html[page].matchAll(/(?:href|src)="(\/app\/[^"]+\.(?:css|js))"/g)) files.add(m[1].slice(1));
  const entry = [...files].find((f) => f.startsWith('app/pages/') && f.endsWith('.js'));
  const queue = entry ? [entry] : [];
  while (queue.length) {
    const file = queue.shift();
    const text = await readFile(new URL(file, root), 'utf8');
    for (const m of text.matchAll(/^import .* from '(\.[^']+)';/gm)) {
      const dep = new URL(m[1], new URL(file, root)).pathname.replace(root.pathname, '');
      if (!files.has(dep)) { files.add(dep); queue.push(dep); }
    }
  }
  return [...files];
}

const gzipped = async (file) => gzipSync(await readFile(new URL(file, root))).length;

for (const page of PAGES) {
  test(`${page}: has a language, a viewport, a title, and at most one h1`, () => {
    const h = html[page];
    assert.match(h, /<html lang="en">/);
    assert.match(h, /<meta name="viewport" content="width=device-width, initial-scale=1">/);
    assert.match(h, /<title>[^<]+<\/title>/);
    assert.ok((h.match(/<h1\b/g) ?? []).length <= 1, 'at most one h1');
  });

  test(`${page}: every image has alt text (empty for decorative ones) and every control a name`, () => {
    const h = html[page];
    for (const img of h.matchAll(/<img\b[^>]*>/g)) assert.match(img[0], /\balt="/, img[0]);
    for (const input of h.matchAll(/<input\b[^>]*>/g)) assert.match(input[0], /aria-label=|\bid="/, input[0]);
    for (const button of h.matchAll(/<button\b[^>]*>([^<]*)</g)) assert.ok(button[1].trim() || /aria-label=/.test(button[0]), button[0]);
    for (const nav of h.matchAll(/<nav\b[^>]*>/g)) assert.match(nav[0], /aria-label=/, nav[0]);
  });

  test(`${page}: loads scripts and stylesheets from this site only, never a CDN (R3)`, () => {
    for (const m of html[page].matchAll(/<(?:script|link)\b[^>]*(?:src|href)="(https?:)?\/\/[^"]+"/g)) assert.fail(m[0]);
  });
}

test('finder.html: what it loads before the first results stays within budget (P1)', async () => {
  const files = await loadedFiles('finder.html');
  assert.ok(files.includes('app/pages/finder.js') && files.includes('app/lib/filter.js'), files.join(', '));
  assert.ok(!files.some((f) => f.startsWith('app/vendor/') && !f.includes('/fonts/')), `libraries load on demand, not up front: ${files.join(', ')}`);
  const sizes = Object.fromEntries(await Promise.all([...files, 'data/public/resources.public.json'].map(async (f) => [f, await gzipped(f)])));
  const own = Object.entries(sizes).filter(([f]) => f.startsWith('app/')).reduce((s, [, n]) => s + n, 0);
  const data = sizes['data/public/resources.public.json'];
  const fonts = (await Promise.all(['inter-latin', 'playfair-display-latin'].map((f) => readFile(new URL(`app/vendor/fonts/${f}.woff2`, root))))).reduce((s, b) => s + b.length, 0);
  // The budget: on Lighthouse's simulated 4G (1.6 Mbit/s) 2 s is about 400 KB, less the requests' round
  // trips. The app's own code, the two Latin fonts and the data file must fit; the map library is
  // loaded only when a map is drawn (app/lib/vendor.js).
  assert.ok(own < 40_000, `app code and styles: ${own} bytes gzipped`);
  assert.ok(fonts < 100_000, `latin fonts: ${fonts} bytes`);
  assert.ok(data < 200_000, `resources.public.json: ${data} bytes gzipped (P2)`);
  assert.ok(own + fonts + data < 320_000, `before the first results: ${own + fonts + data} bytes`);
});

for (const page of ['finder.html', 'resource.html']) {
  test(`${page}: preloads exactly the modules its script imports, so they load in one round trip`, async () => {
    const preloaded = [...html[page].matchAll(/<link rel="modulepreload" href="(\/app\/[^"]+)">/g)].map((m) => m[1].slice(1)).sort();
    const entry = html[page].match(/<script type="module" src="(\/app\/[^"]+)">/)[1].slice(1);
    const imported = (await loadedFiles(page)).filter((f) => f.endsWith('.js') && f !== entry && !f.endsWith('config.js')).sort();
    assert.deepEqual(preloaded, imported);
  });
}

test('the libraries vendor.js loads on demand are in the repo and within budget', async () => {
  const { LIBRARIES } = await import('../../lib/vendor.js');
  let total = 0;
  for (const lib of Object.values(LIBRARIES)) {
    for (const file of [lib.script, lib.style].filter(Boolean)) {
      assert.match(file, /^\/app\/vendor\//, file);
      total += await gzipped(file.slice(1));
    }
  }
  assert.ok(total < 320_000, `vendored libraries: ${total} bytes gzipped`);
});

test('privacy.html: is linked from every page and names each third party the pages talk to', () => {
  for (const page of PAGES.filter((p) => p !== 'privacy.html')) assert.match(html[page], /href="\/?privacy\.html"/, page);
  const privacy = html['privacy.html'];
  for (const party of ['GeoSearch', 'OpenFreeMap', 'Supabase', 'Vercel']) assert.ok(privacy.includes(party), party);
});

test('finder.html, resource.html and privacy.html: the content is in a main landmark', () => {
  for (const page of ['finder.html', 'resource.html', 'privacy.html']) assert.match(html[page], /<main\b/, page);
});

test('every page is served with the security headers in vercel.json', async () => {
  const { headers, rewrites } = JSON.parse(await readFile(new URL('vercel.json', root), 'utf8'));
  const urls = ['/', '/index.html', '/finder.html', '/resource.html', '/privacy.html'];
  for (const url of urls) assert.ok(rewrites.some((r) => r.source === url), `${url} is rewritten to a page`);
  const headersFor = (url) => Object.assign({}, ...headers.filter((h) => new RegExp(`^${h.source}$`).test(url)).map((h) => Object.fromEntries(h.headers.map(({ key, value }) => [key, value]))));
  for (const url of urls) {
    const h = headersFor(url);
    assert.equal(h['X-Content-Type-Options'], 'nosniff', url);
    assert.match(h['Content-Security-Policy'] ?? '', /default-src 'self'/, `${url} has a content security policy`);
    // Every host the pages talk to is allowed, and nothing else.
    for (const host of ['https://geosearch.planninglabs.nyc', 'https://tiles.openfreemap.org']) assert.ok(h['Content-Security-Policy'].includes(host), host);
    assert.ok(!/https?:\/\/(?!geosearch\.planninglabs\.nyc|tiles\.openfreemap\.org|[a-z]+\.supabase\.co)/.test(h['Content-Security-Policy']), 'no other hosts');
  }
  assert.ok(!headersFor('/reach-prototype.html')['Content-Security-Policy'], 'the reach prototype still uses CDNs, so it gets no policy');
});

test('resource.html: loads the same resource module and data as the finder, no Supabase client', async () => {
  const files = await loadedFiles('resource.html');
  assert.ok(files.includes('app/lib/resources.js'));
  assert.ok(!files.some((f) => f.includes('supabase')), files.join(', '));
});
