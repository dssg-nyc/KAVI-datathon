# Connections Guide data cleaning

`data_cleaning_added_features.ipynb` cleans and normalizes the NYPL Connections Guide export and adds
two features for the resource map: `service_type` (what a resource helps with) and `row_type` (what
kind of contact point it is). The notebook's markdown cells document every rule in detail. This file
is a short overview.

## Inputs and outputs

| File | What it is |
|---|---|
| `data/NYPL Connections Resources.csv` | Input. Raw Connections Guide export (760 rows). |
| `data/NYPLConnections_NoMatch.csv` | Input. Used only to record provenance in `in_nomatch_file`. No coordinates are taken from it. |
| `data/cleaned/resources_clean.csv` | **Main output.** All 759 cleaned resources, one row each. |
| `data/cleaned/review_list.csv` | Secondary output. The 287 rows flagged with `needs_review`. Not needed for the MVP. |

The raw file has 760 rows. One row without an organization name held only extra text for the row
above, so it was merged into that row's `review_notes`.

## Run it

Open the notebook from `scripts/cleaning/` and run all cells from top to bottom. It needs Python 3
and pandas, and it overwrites both files in `data/cleaned/`.

## What it does

1. **Cleaning:** trims whitespace, resolves rows without an organization name, converts all-uppercase
   organization names to title case (keeping acronyms such as NYC and HIV), combines street number
   and street, zero-pads ZIP codes and fixes one known wrong Brooklyn ZIP, and adds `https://` to
   websites without a scheme.
2. **Normalization:** renames columns to `snake_case` and derives `borough` from the ZIP code.
3. **`row_type`:** classifies each contact point. The first matching rule wins:

   | `row_type` | Meaning | Rows |
   |---|---|---|
   | `mapped` | Physical address inside NYC | 395 |
   | `outside_nyc` | Physical address outside NYC | 43 |
   | `mailing_address` | PO box or mailing address only | 31 |
   | `hotline` | Hotline, helpline or phone-only contact, no physical address | 71 |
   | `web_only` | Website only, no physical address or hotline | 169 |
   | `cross_reference` | Points to a full listing elsewhere in the guide | 50 |

4. **`service_type`:** assigns one of ten standard categories, for example Housing, Food or
   Legal & Rights. The guide's Category/Subcategory mapping is tried first, then the description
   keywords, and the category is set only when exactly one category matches. Ambiguous rows stay
   blank, with candidates in `service_type_suggested` (244 rows are blank). Audit columns
   (`service_type_source`, `service_type_confidence`, `service_type_conflict`) record how each
   value was decided.

## Not included

- **Coordinates:** `latitude` and `longitude` are intentionally left blank for later geocoding and
  mapping.
- **Manual review:** `review_list.csv` is a work list for a later manual check. To fix a row, change
  the rules in the notebook and run it again. Edits made only in `review_list.csv` are overwritten
  on the next run.
