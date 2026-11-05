# App

The website: static HTML, CSS and browser JS with no build step. Run the commands from the repo root.

| Folder | What is in it |
|---|---|
| `pages/` | `index.html` (landing page), `finder.html` and `finder.js` (the finder's entry script), `resource.html` and `resource.js` (one resource's shareable page) |
| `components/` | Parts of the finder UI: `map.js`, `cards.js`, `place-input.js`, `finder.css`, `resource.css`. Tests are in `components/__tests__/` |
| `lib/` | Logic with no UI: `filter.js`, `resources.js`, `csv.js`, `geo.js`, `preview.js`, `share.js` (resource page links), `layers.js` (the map's reference layers); `types.js` has the JSDoc types of a data row and a finder resource. Tests are in `lib/__tests__/` |
| `brand/` | DSSG design-system CSS and cobrand logos |
| `vendor/` | MapLibre and supabase-js, committed at pinned versions so the finder loads no script from a CDN. See [`vendor/README.md`](vendor/README.md) |
| `prototypes/reach/` | PROTOTYPE, throwaway. The reach prototype's page, scripts and transit data builder |

`config.js` sets the data file (`data/public/resources.public.json`) and the Supabase connection, and `dev-server.mjs` is the local server.

## URLs

The public URLs did not change. [`vercel.json`](../vercel.json) maps them to the files here, and the dev server reads the same file, so local URLs match production:

| URL | File |
|---|---|
| `/`, `/index.html` | `app/pages/index.html` |
| `/finder.html` | `app/pages/finder.html` |
| `/resource.html?id=<id>` | `app/pages/resource.html`, one resource by its stable id |
| `/reach-prototype.html` | `app/prototypes/reach/reach-prototype.html` |

The browser stays on the public URL, so the pages load their assets with absolute paths (`/app/...`). [`.vercelignore`](../.vercelignore) keeps files the site does not load off the public site.

## Commands

| Command | What it does |
|---|---|
| `npm run dev` | Serves the site on http://127.0.0.1:5173, reachable from this computer only. Never serves dotfiles such as `.env`. |
| `npm test` | Runs the JS and TS tests. No network calls. |
| `python3 app/prototypes/reach/build_reach_transit.py` | PROTOTYPE. Downloads MTA GTFS and ADA data into `data/prototype/reach_transit_PROTOTYPE.json`. |

The data the site reads is built by [`pipeline/`](../pipeline/README.md) and stored in [`data/`](../data): the resources in `data/public/resources.public.json`, and the map's reference layers (libraries, health facilities, cooling sites) in `data/public/layers/`, read by `lib/layers.js` and drawn by `components/map.js` when their buttons on the map tab are pressed.
