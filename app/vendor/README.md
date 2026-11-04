# Third-party libraries the site loads

The finder loads these from the repo instead of a CDN, so a visitor's browser talks only to this site, the map
tiles and, as a fallback, Supabase. There is no build step, so the built files are committed as published on
npm, unchanged, each with its licence. The folder name carries the version.

| Folder | What | Licence | From |
|---|---|---|---|
| `maplibre-gl@5.6.0/` | [MapLibre GL JS](https://maplibre.org/maplibre-gl-js/docs/), the map | BSD-3-Clause, `LICENSE.txt` | `https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.{js,css}` and `/LICENSE.txt` |
| `supabase-js@2.117.3/` | [supabase-js](https://supabase.com/docs/reference/javascript) UMD build, the data fallback | MIT, `LICENSE` | `https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.117.3/dist/umd/supabase.js` and `/LICENSE` |

To update one: download the new version's files into a new folder named after it, change the `<link>` and
`<script>` tags in `app/pages/finder.html`, delete the old folder, and update this table.
