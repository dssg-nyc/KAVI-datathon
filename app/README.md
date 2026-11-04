# App

The website: static HTML, CSS and browser JS with no build step. Run the commands from the repo root.

| Folder | What is in it |
|---|---|
| `pages/` | `index.html` (landing page), `finder.html` and `finder.js` (the finder's entry script) |
| `components/` | Parts of the finder UI: `map.js`, `cards.js`, `place-input.js`, `finder.css` |
| `lib/` | Logic with no UI: `filter.js`, `resources.js`, `csv.js`, `geo.js`, `preview.js`. Tests are in `lib/__tests__/` |
| `brand/` | DSSG design-system CSS and cobrand logos |
| `prototypes/reach/` | PROTOTYPE, throwaway. The reach prototype's page, scripts and transit data builder |

`config.js` sets the CSV path and the Supabase connection, and `dev-server.mjs` is the local server.

## URLs

The public URLs did not change. [`vercel.json`](../vercel.json) maps them to the files here, and the dev server reads the same file, so local URLs match production:

| URL | File |
|---|---|
| `/`, `/index.html` | `app/pages/index.html` |
| `/finder.html` | `app/pages/finder.html` |
| `/reach-prototype.html` | `app/prototypes/reach/reach-prototype.html` |

The browser stays on the public URL, so the pages load their assets with absolute paths (`/app/...`). [`.vercelignore`](../.vercelignore) keeps files the site does not load off the public site.

## Commands

| Command | What it does |
|---|---|
| `npm run dev` | Serves the site on http://127.0.0.1:5173, reachable from this computer only. Never serves dotfiles such as `.env`. |
| `npm test` | Runs the JS and TS tests. No network calls. |
| `python3 app/prototypes/reach/build_reach_transit.py` | PROTOTYPE. Downloads MTA GTFS and ADA data into `data/prototype/reach_transit_PROTOTYPE.json`. |

The data the site reads is built by [`core/`](../pipeline/README.md) and stored in [`data/`](../data).
