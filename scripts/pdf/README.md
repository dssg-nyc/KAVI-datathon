# Connections Guide PDF

These scripts read the printed guide, `data/NYPL_JPS_Connections_2026.pdf`, and use it to extend the team's cleaned
data without replacing any of it. The PDF is not in git; put a copy at that path first.

```sh
uv run scripts/pdf/extract_listings.py         # PDF -> data/extracted/connections_pdf_listings.csv
uv run scripts/pdf/compare_to_csv.py           # team CSV vs PDF -> data/extracted/connections_pdf_vs_csv.csv
uv run scripts/pdf/extend_clean_resources.py   # resources_clean.csv + PDF -> data/cleaned/resources_extended.csv
```

`extend_clean_resources.py` reads `data/cleaned/resources_clean.csv`, which `scripts/cleaning/` writes. Each script
gives the same output on every run.

## What the PDF can and cannot tell us

- **Chapter and section are reliable.** The PDF sets each level in one fixed font size, and every section the
  extractor assigns matches one of the PDF's own bookmarks.
- **There is no third level.** Every 11.5pt subheading in the guide is followed by 5 to 63 lines of explanation
  before the next listing, e.g. "Discovery Law" above the public defenders. `preceding_subheading` records it
  but nothing uses it.
- **Audience chapters don't name a service.** Youth, Immigrants, LGBTQI+, Women, Veterans, Older People, and
  People with Disabilities list their resources under "Organizations" or "Organizations & Resources". The PDF can
  only give these rows a service type when the same organization is also listed in a service chapter.

## `section_service_types.csv`

One row per PDF section: the `service_type` and `service_subtype` its listings get, and the `audience` for
audience chapters. This table is the only place where a person decides anything; the script stops if the PDF has a
section the table lacks. `basis` says where each row came from:

| `basis` | Meaning |
|---|---|
| `pr_subcategory` | The section is in `by_sub` in `scripts/cleaning/data_cleaning_added_features.ipynb`. |
| `pr_chapter` | The section's chapter is in `by_cat` in the notebook. |
| `new` | Not decided by the notebook. Added here; review these rows. |
| blank | The section gets no service type. |

The `new` rows map Formerly Incarcerated People to Reentry Support, most of Parents & Caregivers to Family &
Childcare, and the few topical sections inside audience chapters (e.g. Older People > Housing).

## Columns `extend_clean_resources.py` adds

All columns of `resources_clean.csv` come first, unchanged.

| Column | Meaning |
|---|---|
| `pdf_match_method` | How the row was matched to a PDF listing; see the header of `compare_to_csv.py`. `no_match` means the PDF does not print that name. |
| `pdf_listing_id` | `listing_id` in `connections_pdf_listings.csv`. |
| `pdf_chapter`, `pdf_section`, `pdf_guide_page` | Where the PDF prints this listing. |
| `pdf_preceding_subheading` | The explanation heading above the listing, if any. Not a category. |
| `pdf_is_cross_reference` | The PDF listing only says "See the full listing for X on page N". |
| `pdf_section_service_type` | The service type `section_service_types.csv` gives `pdf_section`. Differs from `service_type` in 19 rows, all where the notebook guessed from the description or from other rows. |
| `pdf_appearances` | Every place the PDF lists this organization, as `Chapter > Section (p. N)`. |
| `pdf_org_service_types` | The service types of all those places. |
| `pdf_audiences` | The audience chapters the organization is listed in. |
| `service_type_extended` | `service_type` if the notebook set it, otherwise filled from the PDF. Never overrides. |
| `service_type_extended_source` | `pr:<service_type_source>`, `pdf_section`, `pdf_other_listings` (every other listing agrees), `pdf_candidates` (they disagree; left blank), or `unassigned`. |
| `service_subtype_extended` | `service_subtype` of the row's own PDF section, when that section's type is `service_type_extended`. |
| `description_keyword_types` | Every service type whose pattern in `SERVICE_PATTERNS` matches the row's description (plus the PDF's listing text), or, for a row whose description only says "See X listing for full description", X's description. Multi-label, and computed for every row, including rows that already have a `service_type_extended` from the guide or PDF — a resource's primary type never changes, but its secondary services (e.g. a housing org that also runs a food pantry) now surface in `description_service_types` and `service_types_all`. |
| `description_service_types` | The row's types from the human review in `data/review/` when it has one, else from `reviewed_service_types.csv`, otherwise `description_keyword_types`. Multi-label. |
| `description_service_types_source` | `human_agreed` (a person agreed with `reviewed_service_types.csv`), `human_changed` (a person replaced those types), `human_new_types` (from `new_service_types_review.csv`), `cross_reference:<resource_id>` (a cross-reference row the review left blank, which takes its full listing's `service_types_all`), `reviewed`, `description_keywords`, or `pointer:<resource_id>` (types taken from X's description). |
| `service_types_all` | `service_type_extended`, `pdf_org_service_types`, and `description_service_types` together, for map filters that show an organization under every service it offers. |
| `pdf_contradiction` | Set only where the PDF clearly disagrees: the notebook's own rules applied to the PDF section give another type, the PDF chapter differs from `guide_category`, or "Not found in PDF". |
| `needs_review_extended`, `review_notes_extended` | `review_notes` without "service_type to assign" where the PDF filled it, plus `pdf_contradiction`. |

## Description tagging

`SERVICE_PATTERNS` in `extend_clean_resources.py` starts from the notebook's `hints`. Unlike the notebook, it keeps
every type that matches instead of only rows with exactly one match: 102 of the 146 rows left blank above matched two
or more types, which is why the notebook left them blank. It also drops words that say who a resource serves or a
topic it mentions rather than what it offers ("formerly incarcerated", "parole", "unhoused", "shelter system",
"employment authorization", "medical records", "does not offer legal services", ...).

### `reviewed_service_types.csv`

Every row that got a description type, 123 in all, was checked against its description (and the PDF's listing text)
by Claude on 2026-10-24: 116 by four subagents with one shared rubric, 7 by hand. **No person has checked it yet.**
Each entry has the reviewed types, the keyword types at review time, and in `changes` each tag removed (`-Type: why`)
or added (`+Type: quote`). The script uses the reviewed types for those rows and stops if a `resource_id` no longer
belongs to the same `org_name`.

The review changed the keyword tags in 79 of the 116 subagent-reviewed rows. Against the keyword patterns before the
fixes below, 248 of 289 tags were right and 248 of the 326 reviewed tags were found. The most common mistakes:

- **Health & Mental Health from "counseling"** that is vocational, benefits, or discharge counseling (the seven
  ACCES-VR offices), and from "medical" in legal text ("medical records", "advance medical directives").
- **Housing from who is served**: "homeless youth", "unhoused", "living in the shelter system".
- **Employment and Education from topics** in legal or advocacy text ("denied jobs", "school suspensions").
- **Missed Financial Assistance** (24 of 78 missing tags): "benefits applications", stipends, bond, "reduced fare",
  "Social Security", "money management".

`SERVICE_PATTERNS` now has fixes for those patterns, and every run prints how the patterns compare with the review:
290 of 326 tags right, 290 of the 333 reviewed tags found. Those numbers are measured on the rows the fixes were
written for, so expect lower on rows that were not reviewed. Some mistakes can't be fixed with keywords: "medical
care" in a legal organization's description of the cases it takes still reads as health care.

## Remaining work

- **A person should check the newly added secondary tags.** `description_keyword_types` is now computed for
  every row, including ones that already have a `service_type_extended` from the guide or PDF, so a resource's
  secondary services (e.g. a housing org that also runs a food pantry) surface in `description_service_types`
  and `service_types_all` without changing its primary type. `reviewed_service_types.csv` only covers rows that
  had no primary type at review time, so these new secondary tags are still unreviewed keyword matches
  (`description_service_types_source == "description_keywords"`); the precision/recall numbers above, measured
  only against the reviewed set, are a rough guide for them, not an exact figure.
- **A violence-related service type** is proposed for rows 518, 562, 590, 651 and 656 in
  `data/review/new_service_types_review.csv`, but not decided yet. Until then those rows keep the existing types
  the review gave them.

A person has checked `reviewed_service_types.csv` (`data/review/reviewed_service_types_human_check.csv`) and
given types to the 25 rows that had none (`data/review/new_service_types_review.csv`), adding the type
`Disability Services`. The script applies both files; see `data/review/README.md`.
