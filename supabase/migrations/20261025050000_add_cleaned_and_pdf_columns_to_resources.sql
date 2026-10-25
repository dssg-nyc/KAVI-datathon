-- Add the columns that data/cleaned/resources_extended.csv adds to the Connections Guide:
-- the cleaning notebook's features (scripts/cleaning/README.md) and the PDF extension
-- (scripts/pdf/README.md, "Columns extend_clean_resources.py adds"). Column names match the
-- CSV headers verbatim.
-- Additive only: existing rows keep their values and get nulls until the next
-- `npm run import -- --replace`.
-- Not added: the CSV's cleaned copies of columns public.resources already has (org_name,
-- street, zip, phone, website, guide_category, ...), latitude/longitude (blank in the CSV),
-- and status/source/in_nomatch_file (one value, or provenance only).
-- Multi-label CSV cells ("Education; Employment") are text[]; empty cells are null.

alter table public.resources
  -- resource_id in resources_extended.csv. Not unique: the 5 NEON rows from
  -- data/NYPLConnections_NoMatch.csv copy their parent row's value.
  add column resource_id integer,

  -- From scripts/cleaning/data_cleaning_added_features.ipynb.
  add column service_type text,
  add column service_type_suggested text[],
  add column borough text,
  add column row_type text,
  add column service_type_source text,
  add column service_type_confidence text,
  add column organization_service_types text[],
  add column service_type_conflict boolean,
  add column needs_review boolean,
  add column review_notes text,

  -- From scripts/pdf/extend_clean_resources.py.
  add column pdf_match_method text,
  add column pdf_listing_id integer,
  add column pdf_chapter text,
  add column pdf_section text,
  add column pdf_preceding_subheading text,
  add column pdf_guide_page integer,
  add column pdf_is_cross_reference boolean,
  add column pdf_section_service_type text,
  add column pdf_appearances text[],
  add column pdf_org_service_types text[],
  add column pdf_audiences text[],
  add column service_type_extended text,
  add column service_type_extended_source text,
  add column service_subtype_extended text,
  add column description_keyword_types text[],
  add column description_service_types text[],
  add column description_service_types_source text,
  -- Every service an organization offers; the map filters on this column.
  add column service_types_all text[],
  add column pdf_contradiction text,
  add column needs_review_extended boolean,
  add column review_notes_extended text,

  add constraint resources_row_type_values
    check (row_type in ('mapped', 'outside_nyc', 'mailing_address', 'hotline', 'web_only', 'cross_reference')),
  add constraint resources_borough_values
    check (borough in ('Manhattan', 'Brooklyn', 'Queens', 'Bronx', 'Staten Island'));

create index resources_row_type_idx on public.resources (row_type);
create index resources_borough_idx on public.resources (borough);
create index resources_service_type_extended_idx on public.resources (service_type_extended);
create index resources_service_types_all_idx on public.resources using gin (service_types_all);
