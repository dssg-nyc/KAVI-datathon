// Static checks on the three public pages (landing, finder, resource page) for the accessibility and
// performance requirements in docs/technical-requirements.md (A1, P1, R3). They read the HTML and the
// files it references; nothing is rendered. The browser audit (Lighthouse) is `npm run audit`.
// Run: node --test app/pages/__tests__/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { gzipSync } from 'node:zlib';

const root = new URL('../../../', import.meta.url);
const PAGES = ['index.html', 'finder.html', 'resource.html'];
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

test('finder.html: the sitemap of what it loads up front stays within budget (P1)', async () => {
  const files = await loadedFiles('finder.html');
  assert.ok(files.includes('app/pages/finder.js') && files.includes('app/lib/filter.js'), files.join(', '));
  const sizes = Object.fromEntries(await Promise.all([...files, 'data/public/resources.public.json'].map(async (f) => [f, await gzipped(f)])));
  const vendor = Object.entries(sizes).filter(([f]) => f.startsWith('app/vendor/')).reduce((s, [, n]) => s + n, 0);
  const own = Object.entries(sizes).filter(([f]) => f.startsWith('app/') && !f.startsWith('app/vendor/')).reduce((s, [, n]) => s + n, 0);
  const data = sizes['data/public/resources.public.json'];
  // The budget: on Lighthouse's simulated 4G (1.6 Mbit/s) 2 s is about 400 KB, less the tiles and
  // requests' round trips. The app's own code and the data file must fit in that; the vendored libraries
  // are the known overrun, tracked under P1 in docs/technical-requirements.md.
  assert.ok(own < 40_000, `app code and styles: ${own} bytes gzipped`);
  assert.ok(data < 200_000, `resources.public.json: ${data} bytes gzipped (P2)`);
  assert.ok(vendor < 320_000, `vendored libraries: ${vendor} bytes gzipped`);
});

test('finder.html and resource.html: the content is in a main landmark', () => {
  assert.match(html['finder.html'], /<main\b/);
  assert.match(html['resource.html'], /<main\b/);
});

test('resource.html: loads the same resource module and data as the finder, no Supabase client', async () => {
  const files = await loadedFiles('resource.html');
  assert.ok(files.includes('app/lib/resources.js'));
  assert.ok(!files.some((f) => f.includes('supabase')), files.join(', '));
});
