// Serves the repo as static files on http://localhost:5173 (PORT overrides it), to this computer only.
// Usage: npm run dev
// Pages read their Supabase connection from the committed app/config.js, so no .env or build step is needed.
// Page URLs come from the rewrites in vercel.json, so local URLs match production.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize, resolve, sep } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const { rewrites } = JSON.parse(await readFile(join(root, 'vercel.json'), 'utf8'));
const pageFor = new Map(rewrites.map(({ source, destination }) => [source, destination]));

const types = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.geojson': 'application/geo+json',
  '.csv': 'text/csv; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
};
// Never serve dotfiles or dot-folders: .env (and .env.local etc.) hold the secret key, .git holds history.
const isDotPath = (file) => file.slice(root.length).split(sep).some((part) => part.startsWith('.'));

const port = Number(process.env.PORT) || 5173;
// Listen on the loopback address only, so other machines on the same network (e.g. shared wifi) cannot reach it.
const host = '127.0.0.1';
createServer(async (req, res) => {
  const path = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  const file = normalize(join(root, pageFor.get(path) ?? path));
  if (!file.startsWith(root + sep) || isDotPath(file)) {
    res.writeHead(404).end('Not found');
    return;
  }
  try {
    const body = await readFile(file);
    res.writeHead(200, { 'Content-Type': types[extname(file)] ?? 'application/octet-stream' }).end(body);
  } catch {
    res.writeHead(404).end('Not found');
  }
}).listen(port, host, () => console.log(`Serving on http://localhost:${port} (this computer only)`));
