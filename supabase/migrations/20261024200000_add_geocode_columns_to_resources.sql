-- Add the coordinates and geocoding fields from data/nypl_connections_resources.geojson
-- (built by scripts/nypl_connections_to_geojson.ts; see md/nypl_connections.md).
-- Additive only: existing rows keep their values and get nulls until the next
-- `npm run import -- --replace`.
-- GeoJSON -> column:
--   geometry.coordinates[1] -> latitude        geocode_match -> geocode_match
--   geometry.coordinates[0] -> longitude       geocode_source -> geocode_source
--   geocode_matched_address -> geocode_matched_address
--   geocode_review -> geocode_review
-- Empty strings in the GeoJSON are stored as null.

alter table public.resources
  add column latitude double precision,
  add column longitude double precision,
  -- 'matched', 'unmatched' (had an address, no geocoder placed it) or
  -- 'not_attempted' (no usable address, e.g. hotlines).
  add column geocode_match text,
  -- 'geosearch' or 'census' for geocoded rows; 'nomatch_csv' for the rows whose
  -- coordinates come from data/NYPLConnections_NoMatch.csv.
  add column geocode_source text,
  -- The address the geocoder actually placed, for auditing the point. Null on
  -- 'nomatch_csv' rows, since no geocoder placed them.
  add column geocode_matched_address text,
  -- Non-null when the point is kept but not confirmed at building level.
  add column geocode_review text,
  add constraint resources_coordinates_paired
    check ((latitude is null) = (longitude is null)),
  add constraint resources_geocode_match_values
    check (geocode_match in ('matched', 'unmatched', 'not_attempted')),
  add constraint resources_geocode_source_values
    check (geocode_source in ('geosearch', 'census', 'nomatch_csv'));
