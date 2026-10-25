-- Add the audience columns of data/cleaned/resource_audiences.csv
-- (scripts/audiences/audience_enrichment.ipynb; see scripts/audiences/README.md). Column names match
-- the CSV headers verbatim.
-- Additive only: existing rows keep their values and get nulls until the next
-- `npm run import -- --replace`.
-- Not added: name_audiences, description_audiences and pdf_text_audiences, which only show where a
-- match came from; they stay in the CSV.
-- Multi-label CSV cells ("Youth; Everyone") are text[]; empty cells are null.

alter table public.resources
  -- What the finder's "Who is it for?" question filters on: pdf_audiences, the audiences found in
  -- the name, description and PDF text, and 'Everyone' for every resource that isn't restricted.
  add column audiences_all text[],
  -- Audiences the text explicitly limits the resource to ("only", "must be", an age range).
  add column restricted_audiences text[],
  -- Audiences the resource focuses on without being limited to them; ranked first for that audience.
  add column focus_audiences text[],
  add column confirmed_pdf_audiences text[],
  add column unconfirmed_pdf_audiences text[],
  add column pdf_audience_check text,
  add column audience_restriction text,
  add column restriction_evidence text,
  -- 'stated' (the text says it serves anyone), 'assumed' (no restriction found), null (restricted).
  add column everyone_basis text,
  add column audience_needs_review boolean,
  -- True when scripts/audiences/reviewed_audiences.csv overrides the rules for this row.
  add column audience_reviewed boolean,

  add constraint resources_audience_restriction_values
    check (audience_restriction in ('restricted', 'open', 'mixed', 'not_stated')),
  add constraint resources_everyone_basis_values
    check (everyone_basis in ('stated', 'assumed')),
  add constraint resources_pdf_audience_check_values
    check (pdf_audience_check in ('confirmed', 'partly confirmed', 'not confirmed'));

-- audiences_all is filtered with "contains" (audiences_all=cs.{Youth}), which a GIN index serves.
create index resources_audiences_all_idx on public.resources using gin (audiences_all);
