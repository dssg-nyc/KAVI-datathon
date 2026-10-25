// Serves the repo as static files on http://localhost:5173 (PORT overrides it), to this computer only.
// Usage: npm run dev
// index.html reads its Supabase connection from the committed config.js, so no .env or build step is needed.
// Any static server works too, e.g. python3 -m http.server 5173 --bind 127.0.0.1 from the repo root.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize, resolve, sep } from 'node:path';

const root = resolve(import.meta.dirname, '..', '..');

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
  const file = normalize(join(root, path === '/' ? 'index.html' : path));
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
