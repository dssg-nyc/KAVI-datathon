# Third-party libraries and fonts the site loads

The pages load these from the repo instead of a CDN, so a visitor's browser talks only to this site, the map
tiles, GeoSearch and, as a fallback, Supabase. There is no build step, so the files are committed as
published, unchanged, each with its licence. The folder name carries the version.

| Folder | What | Licence | From |
|---|---|---|---|
| `maplibre-gl@5.6.0/` | [MapLibre GL JS](https://maplibre.org/maplibre-gl-js/docs/), the map | BSD-3-Clause, `LICENSE.txt` | `https://unpkg.com/maplibre-gl@5.6.0/dist/maplibre-gl.{js,css}` and `/LICENSE.txt` |
| `supabase-js@2.117.3/` | [supabase-js](https://supabase.com/docs/reference/javascript) UMD build, the data fallback | MIT, `LICENSE` | `https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.117.3/dist/umd/supabase.js` and `/LICENSE` |
| `fonts/` | [Inter](https://rsms.me/inter/) and [Playfair Display](https://github.com/clauseggers/Playfair), the site's fonts, as variable fonts (weights 400 to 700) in two subsets each (latin, latin-ext); `fonts.css` declares them | SIL Open Font License 1.1, `LICENSE-inter.txt` and `LICENSE-playfair-display.txt` | The `.woff2` files and unicode ranges Google Fonts serves for `css2?family=Inter:wght@400..700&family=Playfair+Display:wght@400..700` (November 2026); the licences from each font's repository |

The two libraries are not referenced by the HTML: `app/lib/vendor.js` lists them and adds the script (and
MapLibre's stylesheet) to the page the first time one is needed. The fonts are imported by
`app/brand/brand.css`, and each page preloads the two latin files.

To update a library: download the new version's files into a new folder named after it, change the paths in
`app/lib/vendor.js`, delete the old folder, and update this table. The page tests check that the files exist
and stay within the size budget. To change a font: replace the files, `fonts.css` and the licence, and update
this table; keep `font-display: swap` so text shows before the font arrives.
