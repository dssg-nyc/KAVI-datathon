// Runs Lighthouse (mobile, simulated 4G) on the landing page, the finder and a resource page, served by
// app/dev-server.mjs with gzip, and checks them against docs/technical-requirements.md: accessibility
// (A1) must score 100, best practices at least 90, and the largest contentful paint (P1) is reported
// against the 2 s target. Needs Chrome; set CHROME_PATH if Lighthouse cannot find it.
//
//   npm run audit              check the three pages, exit 1 on a failed check
//   npm run audit -- --save    also write the JSON reports to .lighthouse/ (ignored by git)
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const PORT = 5177;
const PAGES = [
  ['landing page', '/'],
  ['finder', '/finder.html'],
  ['resource page (with a map)', '/resource.html?id=4'],
];
const LCP_TARGET_MS = 2000;
const save = process.argv.includes('--save');
const root = resolve(import.meta.dirname, '..');

const server = spawn(process.execPath, [resolve(import.meta.dirname, 'dev-server.mjs')], { env: { ...process.env, PORT: String(PORT) }, stdio: 'ignore' });
// Wait until the server answers, rather than a fixed delay: CI runners can take longer than a laptop to start it.
for (let tries = 0; ; tries++) {
  try {
    if ((await fetch(`http://127.0.0.1:${PORT}/`)).ok) break;
  } catch { /* not listening yet */ }
  if (tries === 100) { server.kill(); throw new Error(`dev-server.mjs did not start on port ${PORT} within 10 s`); }
  await new Promise((r) => setTimeout(r, 100));
}

let failed = false;
try {
  const { default: lighthouse } = await import('lighthouse');
  const { launch } = await import('chrome-launcher');
  const chrome = await launch({ chromeFlags: ['--headless=new', '--no-sandbox'] });
  try {
    if (save) await mkdir(resolve(root, '.lighthouse'), { recursive: true });
    for (const [name, path] of PAGES) {
      const { lhr } = await lighthouse(`http://127.0.0.1:${PORT}${path}`, {
        port: chrome.port, logLevel: 'error', output: 'json',
        onlyCategories: ['performance', 'accessibility', 'best-practices'], formFactor: 'mobile', screenEmulation: { mobile: true, width: 360, height: 780, deviceScaleFactor: 2 },
      });
      if (save) await writeFile(resolve(root, '.lighthouse', `${name.replace(/ /g, '-')}.json`), JSON.stringify(lhr, null, 2));
      const score = (c) => Math.round(lhr.categories[c].score * 100);
      const lcp = lhr.audits['largest-contentful-paint'].numericValue;
      const a11y = score('accessibility');
      const bp = score('best-practices');
      const checks = [
        [`accessibility ${a11y}`, a11y === 100],
        [`best practices ${bp}`, bp >= 90],
      ];
      const lcpOk = lcp <= LCP_TARGET_MS;
      console.log(`${name}: performance ${score('performance')}, LCP ${(lcp / 1000).toFixed(1)} s (${lcpOk ? 'within' : 'over'} the ${LCP_TARGET_MS / 1000} s target), ${checks.map(([label, ok]) => `${label} ${ok ? 'ok' : 'FAIL'}`).join(', ')}`);
      for (const [id, audit] of Object.entries(lhr.audits)) {
        if (lhr.categories.accessibility.auditRefs.some((ref) => ref.id === id) && audit.score !== null && audit.score < 1) {
          console.log(`  ${id}: ${audit.title}`);
          for (const item of audit.details?.items ?? []) console.log(`    ${item.node?.snippet ?? item.node?.selector ?? ''}`);
        }
      }
      if (checks.some(([, ok]) => !ok)) failed = true;
    }
  } finally {
    await chrome.kill();
  }
} finally {
  server.kill();
}
process.exit(failed ? 1 : 0);
