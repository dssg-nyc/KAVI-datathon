# Handoff: running EMPOWER after the datathon

For the KAVI Brooklyn and DSSG NYC team taking the site over. It says what is deployed, how to change it, what to check before the next deployment, and what still needs a decision. The longer story is in [technical-requirements.md](technical-requirements.md); what the product is for is in [PRD.md](PRD.md).

## What is deployed

A static site on Vercel, built from the `main` branch of this repo with no build step. Four public pages:

| URL | What it is | Source |
|---|---|---|
| `/` | Landing page | `app/pages/index.html` |
| `/finder.html` | The resource finder: three questions, then a list and a map | `app/pages/finder.html`, `finder.js` |
| `/resource.html?id=<id>` | One resource, with a link to copy | `app/pages/resource.html`, `resource.js` |
| `/privacy.html` | What the pages send, and to whom | `app/pages/privacy.html` |

`/reach-prototype.html` is also reachable. It is a throwaway prototype; see the open decisions.

The finder downloads one file, `data/public/resources.public.json`, and does all filtering in the browser. Nothing a visitor types or chooses is sent to this site. The only other hosts a page talks to are NYC GeoSearch (address suggestions), OpenFreeMap (map tiles) and, only if the data file fails to load, the Supabase project. The pages cannot load anything from any other host: `vercel.json` sets a content security policy that names exactly these.

Everything a page needs is in the repo: the map library, the Supabase client and the fonts are in `app/vendor/` with their licences. There are no accounts, cookies or analytics.

## Where the data comes from

The listings are the NYPL Connections guide, cleaned and extended by the scripts in `pipeline/`, one numbered folder per stage. The final step writes two committed files: `data/public/resources.public.json` (what the site downloads) and `data/public/resources.provenance.json` (where each field came from, for review). Every resource has a stable id from `data/resource_ids.csv`, so links to resource pages keep working across rebuilds.

The map's reference layers (libraries, health facilities, cooling sites) are committed copies of the ArcGIS Online layers in `data/public/layers/`.

## How to update the data

You need git, Node 22 or later, and [uv](https://docs.astral.sh/uv/). Nothing else: `npm ci` installs the Node tools and uv installs Python on first use.

1. Make the change at its source. A fix to a listing goes in `data/review/` (see its README), not in the generated files.
2. Run the pipeline and the checks:

   ```sh
   npm ci
   npm run pipeline      # cleans, extends, geocodes, tags audiences, assigns ids, builds the public files
   npm run check         # type check, linters, tests and the data schemas
   ```

3. Look at the diff of `data/public/resources.public.json`. It is one resource per line, so a small change shows as a small diff.
4. Open a pull request. CI runs the same checks plus a Lighthouse audit, and Vercel builds a preview to click through.
5. Merge. Vercel deploys `main`.

`npm run pipeline -- --list` shows the stages, and [../pipeline/README.md](../pipeline/README.md) says how to run one on its own. The Supabase import (`npm run import`) is separate and needs the secret key; the site does not need it to be run, because it reads the committed file first.

## What to check on a preview deployment

These were tested locally against a server that imitates Vercel, but not on Vercel itself:

- **The four pages load**, the finder shows counts after each question, and the map draws on the results and on a resource page. If the map area is blank or the browser console shows a "Content Security Policy" error, a host is missing from the policy in `vercel.json`.
- **The response headers are there.** Open the browser's network panel on `/finder.html` and look for `Content-Security-Policy`, `X-Content-Type-Options` and `Referrer-Policy` on the document response.
- **`/privacy.html` is right.** It was written from the code by the refactor, not reviewed by KAVI, and it names `info@kavibrooklyn.org` as the contact. Edit the wording in `app/pages/privacy.html` as needed; keep the list of hosts in step with `vercel.json`.
- **Nothing internal is published.** Try `/pipeline/README.md` and `/docs/handoff.md`: both should be 404, because `.vercelignore` keeps them off the site.

## Checks you can run

| Command | What it does |
|---|---|
| `npm run dev` | Serves the site locally at http://127.0.0.1:5173 with the same URL rewrites and headers as Vercel |
| `npm run check` | Everything CI runs except Lighthouse: type check, lint, tests in JS, TS and Python, and the data schemas |
| `npm run audit` | Lighthouse on the landing page, the finder and a resource page, as a phone on 4G. Needs Chrome. Fails if accessibility drops below 100 |
| `npm test` | The JS and TS tests only, in about a second |

## Known gaps

- **Speed on phones (P1).** The target is first results within 2 s on 4G. The landing page meets it (1.8 s). The finder and resource page measure 3.2 s, because the first question is built from the 158 KB data file. The next step would be to show the first question from a small committed list before the data arrives.
- **Neighborhood search (F3)** does not work: GeoSearch only knows addresses, so "Bushwick" returns streets. Borough and ZIP search work. Supporting neighborhoods needs a list of names with a centre point, such as the NTA centroids on NYC Open Data.
- **Keyboard and touch pass.** Automated accessibility checks pass at 100, but nobody has yet gone through the three questions with a keyboard only, or on a real phone.
- **Hours, eligibility and referral details** are not in the source data. The schema has room for them.
- **Audience tags** are labelled as unreviewed in the UI; see [audience_matching.md](audience_matching.md) before relying on them with clients.

## Decisions for the team

The full table is in [technical-requirements.md](technical-requirements.md#open-decisions-for-the-team). The ones that affect the next deployment:

- **Who owns data updates.** Without a named person the listings go stale. The steps above take under an hour once set up.
- **The privacy page wording and contact address.**
- **The licence.** `LICENSE` in the repo root is MIT, added in the refactor so partners can reuse the code; the team can change it.
- **Supabase.** The site reads the committed file; Supabase is only a fallback. Keeping it means keeping the import working and the project paid for. Retiring it means removing the fallback from `finder.js` and the `supabase/` folder.
- **The reach prototype.** It still loads scripts from CDNs and depends on a volunteer-run routing server. Unlink it (one footer link in `index.html`) or integrate it; the acceptance criteria are in the decisions table.

## Who to ask

The base authors of each part are listed under "Who built what" in [technical-requirements.md](technical-requirements.md#who-built-what). The refactor commits on the `ramsey-refactor` branch each describe what they changed and why.
