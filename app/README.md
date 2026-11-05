# App

The website: static HTML, CSS and browser JS with no build step. Run the commands from the repo root.

| Folder | What is in it |
|---|---|
| `pages/` | `index.html` (landing page), `finder.html` and `finder.js` (the finder's entry script), `resource.html` and `resource.js` (one resource's shareable page), `privacy.html` (what the pages send and to whom; keep it in step with the hosts in `vercel.json`) |
| `components/` | Parts of the finder UI: `map.js`, `cards.js`, `place-input.js`, `finder.css`, `resource.css`; `page.css` styles plain text pages and the footer. Tests are in `components/__tests__/` |
| `lib/` | Logic with no UI: `filter.js`, `resources.js`, `csv.js`, `geo.js`, `preview.js`, `share.js` (resource page links), `layers.js` (the map's reference layers), `vendor.js` (loads MapLibre and supabase-js from `vendor/` when first needed); `types.js` has the JSDoc types of a data row and a finder resource. Tests are in `lib/__tests__/` |
| `brand/` | DSSG design-system CSS and cobrand logos (the logos are 176 px, the largest size they are shown at) |
| `vendor/` | MapLibre, supabase-js and the Inter and Playfair Display fonts, committed at pinned versions so no page loads anything from a CDN. See [`vendor/README.md`](vendor/README.md) |
| `prototypes/reach/` | PROTOTYPE, throwaway. The reach prototype's page, scripts and transit data builder |

`config.js` sets the data file (`data/public/resources.public.json`) and the Supabase connection, and `dev-server.mjs` is the local server.

## URLs

The public URLs did not change. [`vercel.json`](../vercel.json) maps them to the files here, and the dev server reads the same file, so local URLs match production:

| URL | File |
|---|---|
| `/`, `/index.html` | `app/pages/index.html` |
| `/finder.html` | `app/pages/finder.html` |
| `/resource.html?id=<id>` | `app/pages/resource.html`, one resource by its stable id |
| `/privacy.html` | `app/pages/privacy.html` |
| `/reach-prototype.html` | `app/prototypes/reach/reach-prototype.html` |

The browser stays on the public URL, so the pages load their assets with absolute paths (`/app/...`). [`.vercelignore`](../.vercelignore) keeps files the site does not load off the public site.

`vercel.json` also sets the response headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and `Permissions-Policy` on everything, and a `Content-Security-Policy` on the four pages above that allows scripts, styles and fonts from this site only and connections to this site, GeoSearch, the OpenFreeMap tiles and Supabase. The dev server sends the same headers, so a page that needs another host fails locally, in the browser console, before it is deployed. To add a host: add it to the policy, to the table in [`docs/technical-requirements.md`](../docs/technical-requirements.md) and to `privacy.html`. The reach prototype is not covered by the policy because it still uses CDNs.

## How a page loads

Each page's HTML links its stylesheets and preloads the two Latin font files and, on the finder and resource page, the data file and every module its script imports (`modulepreload`, so they arrive in one round trip; a test checks the list against the imports). The page's module then runs. MapLibre and supabase-js are not in the HTML: `lib/vendor.js` adds their script (and MapLibre's stylesheet) to the page the first time a map is drawn or the Supabase fallback is needed, so the first screen does not wait for them.

## Commands

| Command | What it does |
|---|---|
| `npm run dev` | Serves the site on http://127.0.0.1:5173, reachable from this computer only. Never serves dotfiles such as `.env`. Gzips text when the browser accepts it and sends the headers from `vercel.json`, as Vercel does. |
| `npm test` | Runs the JS and TS tests. No network calls. The page tests in `pages/__tests__/` check the four pages' HTML, the size budget, the `modulepreload` lists and the headers in `vercel.json`; `components/__tests__/contrast.test.mjs` checks the finder's text colours against WCAG AA; `lib/__tests__/fallbacks.test.mjs` checks what happens without the map library or address search; `lib/__tests__/vendor.test.mjs` checks the on-demand loading. |
| `npm run audit` | Runs Lighthouse on `/`, `/finder.html` and a resource page with a map as a phone on 4G, served by `dev-server.mjs` with gzip and the headers, and prints the scores. Fails if accessibility is under 100 or best practices under 90. `-- --save` keeps the JSON reports in `.lighthouse/`. Needs Chrome. |
| `python3 app/prototypes/reach/build_reach_transit.py` | PROTOTYPE. Downloads MTA GTFS and ADA data into `data/prototype/reach_transit_PROTOTYPE.json`. |

The data the site reads is built by [`pipeline/`](../pipeline/README.md) and stored in [`data/`](../data): the resources in `data/public/resources.public.json`, and the map's reference layers (libraries, health facilities, cooling sites) in `data/public/layers/`, read by `lib/layers.js` and drawn by `components/map.js` when their buttons on the map tab are pressed.
