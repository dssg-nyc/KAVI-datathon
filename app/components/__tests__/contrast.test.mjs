// WCAG 2.1 AA contrast (requirement A1) of the text and background pairs the finder draws, computed
// from the colours in app/brand/brand.css and app/components/finder.css. Lighthouse only sees the
// screen it loads; cards, tiles and pills appear after a click, so they are checked here.
// Run: node --test app/components/__tests__/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const root = new URL('../../../', import.meta.url);
const brand = await readFile(new URL('app/brand/brand.css', root), 'utf8');
const finder = await readFile(new URL('app/components/finder.css', root), 'utf8');

// The custom properties of brand.css, resolved through var() references.
const vars = {};
for (const m of brand.matchAll(/--([\w-]+):\s*([^;]+);/g)) vars[m[1]] = m[2].trim();
const resolve = (value) => value.replace(/var\(--([\w-]+)\)/g, (_, name) => resolve(vars[name]));

function luminance(hex) {
  const [r, g, b] = hex.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i).slice(1).map((h) => {
    const c = parseInt(h, 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(text, background) {
  const [a, b] = [luminance(resolve(text)), luminance(resolve(background))];
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

// The colour a finder.css rule gives a property, e.g. rule('.dist.remote', 'color').
function rule(selector, property) {
  const line = finder.split('\n').find((l) => l.startsWith(`${selector} {`));
  assert.ok(line, `no rule for ${selector}`);
  return line.match(new RegExp(`[\\s;{]${property}:\\s*([^;]+);`))[1].trim();
}

const AA = 4.5; // all of this text is under 18 pt

test('colours are parsed from the stylesheets', () => {
  assert.equal(resolve('var(--muted)'), '#64748b');
  assert.equal(contrast('#000000', '#ffffff').toFixed(0), '21');
});

// [what, text colour, background]
const pairs = [
  ['body text on the page', 'var(--text)', 'var(--bg)'],
  ['muted text (meta lines, counts, review notes) on a card', 'var(--muted)', 'var(--panel)'],
  ['muted text on the page background', 'var(--muted)', 'var(--bg)'],
  ['headings and links in brand blue', 'var(--primary-blue)', 'var(--white)'],
  ['the error message', 'var(--error)', 'var(--bg)'],
  ['a pressed tab (white on blue)', '#ffffff', 'var(--primary-blue)'],
  ['a pressed pill or tile (blue on the tint)', 'var(--primary-blue)', 'var(--accent-soft)'],
  ['a "Phone / online" badge on a card', rule('.dist.remote', 'color'), 'var(--panel)'],
  ['an "Eligibility not stated" tag', rule('.tag.who.unstated', 'color'), rule('.tag.who.unstated', 'background')],
  ['a "Made for" tag', 'var(--text)', 'var(--who)'],
  ['a Spanish-speaking tag', 'var(--text)', 'var(--lang)'],
  ['the preview note', '#5c4300', '#fff4d6'],
];

for (const [what, text, background] of pairs) {
  test(`${what} is at least ${AA}:1`, () => {
    const ratio = contrast(text, background);
    assert.ok(ratio >= AA, `${text} on ${background} is ${ratio.toFixed(2)}:1`);
  });
}

test('muted text is not drawn on the blue tint: a pressed tile or pill inherits its text colour', () => {
  assert.ok(contrast('var(--muted)', 'var(--accent-soft)') < AA, 'if this now passes, the inherit rule can go');
  assert.match(finder, /\.pill\[aria-pressed=true\] \.count, \.tile\[aria-pressed=true\] \.count-open \{ color: inherit; \}/);
});
