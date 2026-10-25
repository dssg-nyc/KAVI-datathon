-- Recreate public.resources with one column per column of "NYPL Connections Resources.csv".
-- The table held 0 rows when this was written, so dropping it loses no data.
-- CSV header -> column:
--   Organization Name -> organization_name      Phone Number -> phone_number
--   Street Number -> street_number              Website -> website
--   Address Line 2 -> address_line_2            Description -> description
--   Street -> street                            Category -> category
--   City -> city                                Subcategory -> subcategory
--   State -> state                              Notes -> notes
--   Zip Code -> zip_code
--   Spanish-speaking (Y/N) -> spanish_speaking
--   Works w/ Currently Incarcerated/Pre-release (Y/N) -> works_with_currently_incarcerated
--   ATI Program (Y/N) -> ati_program
--   Know Your Rights Content (Y/N) -> know_your_rights_content
-- Y/N columns are booleans; a blank cell is null (unknown), not false.

drop table if exists public.resources;

create table public.resources (
  id bigint generated always as identity primary key,
  -- Nullable: 2 CSV rows have no organization name (extra addresses for the row above).
  organization_name text,
  street_number text,
  address_line_2 text,
  street text,
  city text,
  state text,
  -- Text, not integer, so leading zeros survive.
  zip_code text,
  -- Free text in the CSV, e.g. "Child Support Helpline: 888.208.4485 (Mon–Fri 8am–7pm)".
  phone_number text,
  website text,
  description text,
  category text,
  subcategory text,
  spanish_speaking boolean,
  works_with_currently_incarcerated boolean,
  ati_program boolean,
  know_your_rights_content boolean,
  notes text
);

create index resources_category_idx on public.resources (category);

-- The publishable key ships in the browser, so RLS decides what it can do.
-- Anyone can read; nobody can insert, update or delete through the Data API.
-- Imports use the secret key (scripts only), which bypasses RLS.
alter table public.resources enable row level security;

create policy "Resources are publicly readable"
  on public.resources
  for select
  to anon, authenticated
  using (true);

grant select on public.resources to anon, authenticated;
