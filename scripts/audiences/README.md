# Audience enrichment

> **Demo only:** the audience tags come from keyword rules and haven't been reviewed by a person. See
> [md/audience_matching.md](../../md/audience_matching.md) for how matching works and its limitations.

`audience_enrichment.ipynb` answers the finder's question *"Who is it for?"* for every resource. It reads
`data/cleaned/resources_extended.csv` and the PDF listing text in `data/extracted/connections_pdf_listings.csv`, and
writes `data/cleaned/resource_audiences.csv`, one row per `resource_id`, to be joined onto the resource table. It
doesn't change any existing file.

Run it from `scripts/audiences/`, top to bottom. It needs Python 3 and pandas.

## Why

`pdf_audiences` (from `scripts/pdf/extend_clean_resources.py`) only knows the PDF's audience chapters, so it is
blank for every organization listed only in a service chapter (Health, Legal, Housing, …). A blank can mean
"open to everyone" or "not stated", and the data can't tell these apart.

## Rules

1. `pdf_audiences` is kept unchanged.
2. A PDF audience is **confirmed** when the organization's name, description or PDF listing text also mentions it.
3. Audiences found in those texts are added, including *Survivors of violence* and *People without homes*.
4. **`Everyone` is the default.** A resource is restricted only on explicit wording: *only*, *exclusively*, *limited
   to*, *must be* right before or after the audience, or an age range of 12–25 (Youth) or 55+ (Older People) in the
   first sentence. A resource that merely focuses on a group (in its name, or "for youth" in the first sentence)
   keeps `Everyone` and ranks higher for that group.

## Columns

| Column | Meaning |
|---|---|
| `pdf_audiences` | Unchanged from `resources_extended.csv`. |
| `confirmed_pdf_audiences`, `unconfirmed_pdf_audiences` | The PDF audiences that the texts do or don't mention. |
| `pdf_audience_check` | `confirmed`, `partly confirmed`, `not confirmed`, or blank (no PDF audience). |
| `name_audiences`, `description_audiences`, `pdf_text_audiences` | Audiences found in each text, so a match can be traced to its source. |
| `restricted_audiences` | The audiences the text explicitly limits the resource to. |
| `focus_audiences` | Audiences the resource focuses on without being limited to them. |
| `audience_restriction` | `restricted`, `open` (says it serves anyone), `mixed` (both; needs review) or `not_stated`. |
| `restriction_evidence` | The words that triggered a restriction or the "open" wording. |
| `everyone_basis` | `stated` (the text says it serves anyone), `assumed` (no restriction found) or blank (restricted). |
| `audiences_all` | All of the above together, plus `Everyone` for every resource that isn't restricted. |
| `audience_needs_review` | `True` for restricted or mixed rows and for PDF audiences that aren't (fully) confirmed. |

## Ranking in the finder

When a user picks an audience, e.g. *Youth*: first resources made for youth (restricted to or focused on them),
then other resources tagged *Youth*, then resources tagged *Everyone*. Resources restricted to other groups are left
out. `rank_for()` in the notebook is the reference for the finder's filter.

## Manual decisions

`reviewed_audiences.csv` (in this folder) holds decisions for single rows that no pattern can capture. The
notebook reads it on every run, applies it over the rules, and never overwrites it. Columns: `resource_id`,
`org_name` (must match the id), `human_audiences` (`; `-separated, without `Everyone`), `human_restriction`
(`restricted`, `open` or `not_stated`), `human_notes`. Blank cells keep the rule-based value.

## Data quality check

```sh
python3 scripts/audiences/check_audiences.py
```

Run it from the repo root after the notebook and before every import. It needs only the standard library and
checks the output in three groups: structure (ids, columns, formats, the values the migration allows), logic (the
columns agree with each other, e.g. `Everyone` exactly when not restricted, PDF audiences always kept) and content
(audiences from PDF extraction notes, ambiguous words like "survivors" or "reentry permits", pointer rows, and the
import's `resource_id` → GeoJSON join). It exits with status 1 when a check fails.

## Loading into Supabase

1. `supabase db push` applies `supabase/migrations/*_add_audience_columns_to_resources.sql`, which adds the columns
   above (lists as `text[]`, plus a GIN index on `audiences_all`).
2. `npm run import -- --replace` reads `data/cleaned/resource_audiences.csv` next to `resources_extended.csv` and
   joins it by `resource_id` (see `AUDIENCE_COLUMNS` in `scripts/database/import-resources.mjs`).

For the finder, `finder/resources.js` would read `audiences_all` in place of `pdf_audiences`, and `finder/filter.js`
would apply the ranking above: a resource matches a chosen audience when `audiences_all` contains it or `Everyone`.

## Status

Third version of the rules, not reviewed yet. Two files in `data/review/` support the manual check:
`audience_review.csv` (a random sample of 50 rows) and `audience_no_match.csv` (PDF audiences the texts don't
confirm, and rows with no audience anywhere). Sharpen the patterns from what they show, then run again.
