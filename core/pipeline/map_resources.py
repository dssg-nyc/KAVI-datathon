"""Maps the pipeline's data files to the rows of public.resources.

This is the same mapping supabase/load_supabase.mjs sends to Supabase (its copy is
supabase/map_resources.mjs; __tests__/map_resources.test.py fails if the two disagree), kept here
so the pipeline can build the site's data files without a database. No side effects: it reads the
files and returns the rows.

Rows come from four files in data/:
  nypl_connections_resources.geojson  one feature per row of "NYPL Connections Resources.csv",
                                      in the same order, with coordinates and geocode_* fields
                                      (built by geocode.py).
  cleaned/resources_extended.csv      the cleaned rows with service types, row types and PDF
                                      fields (clean_guide.py, extend_with_pdf.py). Its columns in
                                      EXTENDED_COLUMNS are added to the GeoJSON row it was
                                      cleaned from; NoMatch extra rows copy their parent's.
  cleaned/resource_audiences.csv      the "Who is it for?" columns (tag_audiences.py), joined by
                                      resource_id like the extended CSV.
  NYPLConnections_NoMatch.csv         copies of CSV rows the geocoders could not place. Only its
                                      rows with lat/lon are used: each becomes an extra row,
                                      inserted after the GeoJSON row with the same organization
                                      name and copying that row's fields except the address.
                                      Today that is the 5 NYC NEON clothing closet sites.

Usage:
  from map_resources import map_resources
  records = map_resources(ROOT)["records"]

  uv run core/pipeline/map_resources.py    print the rows as JSON, one per line
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# CSV header (a GeoJSON property name) -> public.resources column
# (see supabase/migrations/*_reshape_resources_to_match_csv.sql).
TEXT_COLUMNS = {
    "Organization Name": "organization_name",
    "Street Number": "street_number",
    "Address Line 2": "address_line_2",
    "Street": "street",
    "City": "city",
    "State": "state",
    "Zip Code": "zip_code",
    "Phone Number": "phone_number",
    "Website": "website",
    "Description": "description",
    "Category": "category",
    "Subcategory": "subcategory",
    "Notes": "notes",
}
YES_NO_COLUMNS = {
    "Spanish-speaking (Y/N)": "spanish_speaking",
    "Works w/ Currently Incarcerated/Pre-release (Y/N)": "works_with_currently_incarcerated",
    "ATI Program (Y/N)": "ati_program",
    "Know Your Rights Content (Y/N)": "know_your_rights_content",
}
# GeoJSON property -> column (see supabase/migrations/*_add_geocode_columns_to_resources.sql).
# The addr:* properties repeat the address columns and are not imported.
GEOCODE_COLUMNS = {
    "geocode_match": "geocode_match",
    "geocode_source": "geocode_source",
    "geocode_matched_address": "geocode_matched_address",
    "geocode_review": "geocode_review",
}
# resources_extended.csv column -> type of the public.resources column with the same name
# (see supabase/migrations/*_add_cleaned_and_pdf_columns_to_resources.sql).
# 'list' cells are "; "-separated and become text[].
EXTENDED_COLUMNS = {
    "resource_id": "integer",
    "service_type": "text",
    "service_type_suggested": "list",
    "borough": "text",
    "row_type": "text",
    "service_type_source": "text",
    "service_type_confidence": "text",
    "organization_service_types": "list",
    "service_type_conflict": "boolean",
    "needs_review": "boolean",
    "review_notes": "text",
    "pdf_match_method": "text",
    "pdf_listing_id": "integer",
    "pdf_chapter": "text",
    "pdf_section": "text",
    "pdf_preceding_subheading": "text",
    "pdf_guide_page": "integer",
    "pdf_is_cross_reference": "boolean",
    "pdf_section_service_type": "text",
    "pdf_appearances": "list",
    "pdf_org_service_types": "list",
    "pdf_audiences": "list",
    "service_type_extended": "text",
    "service_type_extended_source": "text",
    "service_subtype_extended": "text",
    "description_keyword_types": "list",
    "description_service_types": "list",
    "description_service_types_source": "text",
    "service_types_all": "list",
    "pdf_contradiction": "text",
    "needs_review_extended": "boolean",
    "review_notes_extended": "text",
}
# resource_audiences.csv column -> type (see docs/datathon/audiences.md and
# supabase/migrations/*_add_audience_columns_to_resources.sql).
AUDIENCE_COLUMNS = {
    "audiences_all": "list",
    "restricted_audiences": "list",
    "focus_audiences": "list",
    "confirmed_pdf_audiences": "list",
    "unconfirmed_pdf_audiences": "list",
    "pdf_audience_check": "text",
    "audience_restriction": "text",
    "restriction_evidence": "text",
    "everyone_basis": "text",
    "audience_needs_review": "boolean",
    "audience_reviewed": "boolean",
}
# The cleaning notebook merged GeoJSON feature 690 (no organization name; extra text for the row
# above) into resource_id 690, so resource_id N is feature N-1 up to 690 and feature N after it.
MERGED_FEATURE_INDEX = 690

# The NoMatch file is Windows-1252, not UTF-8 (its dashes are byte 0x97). Its header repeats City and
# State, so columns are read by position. Positions 0-9 are the address the coordinates belong to;
# positions 10-26 are the same columns as the main CSV.
NOMATCH = {"place": 0, "address2": 1, "city": 4, "state": 6, "zip": 7, "organization_name": 10, "lat": 28, "lon": 29}
NOMATCH_HEADER_COUNT = 30
BOROUGH_BY_CITY = {"New York": "Manhattan", "Brooklyn": "Brooklyn", "Bronx": "Bronx", "Queens": "Queens", "Staten Island": "Staten Island"}


def parse_csv(text: str) -> list[list[str]]:
    """RFC 4180: quoted fields may contain commas, newlines and "" escapes. Blank rows are dropped."""
    rows: list[list[str]] = []
    row: list[str] = []
    field: list[str] = []
    quoted = False
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if quoted:
            if c == '"' and i + 1 < n and text[i + 1] == '"':
                field.append('"')
                i += 1
            elif c == '"':
                quoted = False
            else:
                field.append(c)
        elif c == '"':
            quoted = True
        elif c == ",":
            row.append("".join(field))
            field = []
        elif c in "\r\n":
            if c == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append("".join(field))
            rows.append(row)
            row, field = [], []
        else:
            field.append(c)
        i += 1
    if field or row:
        row.append("".join(field))
        rows.append(row)
    return [r for r in rows if any(v.strip() for v in r)]


def read_text(path: Path, encoding: str = "utf-8") -> str:
    """The file as written: line endings are left for parse_csv."""
    with open(path, encoding=encoding, newline="") as f:
        return f.read()


def to_number(text: str) -> int | float:
    """A number read from text; a whole number stays an int, so it is written back as 40, not 40.0."""
    value = float(text)
    return int(value) if value.is_integer() and abs(value) < 2**53 else value


def to_json(value: object) -> str:
    """Compact JSON, the way the site's files are written."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def to_text(value: str) -> str | None:
    v = value.strip()
    return v or None


def to_boolean(value: str, header: str, where: str) -> bool | None:
    """Blank means unknown, so it stays None rather than becoming False."""
    v = value.strip().upper()
    if v == "":
        return None
    if v == "Y":
        return True
    if v == "N":
        return False
    raise ValueError(f'{where}: "{header}" must be Y, N or blank, got "{value}"')


def to_extended_value(value: str, type_: str, column: str, where: str):
    v = value.strip()
    if v == "":
        return None
    if type_ == "text":
        return v
    if type_ == "list":
        return [s.strip() for s in v.split(";") if s.strip()]
    if type_ == "integer":
        if not re.fullmatch(r"[0-9]+", v):
            raise ValueError(f'{where}: {column} must be an integer, got "{value}"')
        return int(v)
    if v == "True":
        return True
    if v == "False":
        return False
    raise ValueError(f'{where}: {column} must be True, False or blank, got "{value}"')


def _read_table(path: Path, columns: dict[str, str]) -> tuple[list[str], list[list[str]]]:
    headers, *rows = parse_csv(read_text(path))
    missing = [c for c in columns if c not in headers]
    if missing:
        raise ValueError(f"{path}: missing columns {', '.join(missing)}")
    return headers, rows


def map_resources(root: Path = ROOT) -> dict:
    """The rows of public.resources in insert order, with the paths read and what each file contributed."""
    root = Path(root)
    paths = {
        "geojson": root / "data" / "nypl_connections_resources.geojson",
        "extended": root / "data" / "cleaned" / "resources_extended.csv",
        "audiences": root / "data" / "cleaned" / "resource_audiences.csv",
        "nomatch": root / "data" / "NYPLConnections_NoMatch.csv",
    }

    # --- GeoJSON: one record per feature, in file order ---

    geojson = json.loads(read_text(paths["geojson"]))
    expected = [*TEXT_COLUMNS, *YES_NO_COLUMNS, *GEOCODE_COLUMNS]
    geojson_records: list[dict] = []
    for i, feature in enumerate(geojson["features"]):
        where = f"Feature {i}"
        props = feature["properties"]
        missing = [key for key in expected if key not in props]
        if missing:
            raise ValueError(f"{where}: missing properties {', '.join(missing)}")
        record: dict = {}
        for key, column in TEXT_COLUMNS.items():
            record[column] = to_text(props[key])
        for key, column in YES_NO_COLUMNS.items():
            record[column] = to_boolean(props[key], key, where)
        for key, column in GEOCODE_COLUMNS.items():
            record[column] = to_text(props[key])
        geometry = feature.get("geometry")
        if geometry:
            if geometry["type"] != "Point":
                raise ValueError(f"{where}: expected a Point, got {geometry['type']}")
            longitude, latitude = geometry["coordinates"][:2]
            record["latitude"], record["longitude"] = latitude, longitude
        else:
            record["latitude"], record["longitude"] = None, None
        geojson_records.append(record)

    # --- Extended CSV: new columns for the GeoJSON row each cleaned row came from ---

    extended_headers, extended_rows = _read_table(paths["extended"], EXTENDED_COLUMNS)
    for record in geojson_records:
        record.update(dict.fromkeys(EXTENDED_COLUMNS))

    def normalize_name(name: str | None) -> str:
        return (name or "").strip().lower()

    for i, cells in enumerate(extended_rows):
        where = f"{paths['extended']} line {i + 2}"
        row = {h: cells[j] if j < len(cells) else "" for j, h in enumerate(extended_headers)}
        resource_id = int(row["resource_id"]) if row["resource_id"].strip().isdigit() else -1
        feature_index = resource_id - 1 if resource_id <= MERGED_FEATURE_INDEX else resource_id
        if not 0 <= feature_index < len(geojson_records):
            raise ValueError(f"{where}: resource_id {row['resource_id']} has no GeoJSON feature")
        record = geojson_records[feature_index]
        # The notebook fills in some blank names, so only a name that is set on both sides must agree.
        if record["organization_name"] and normalize_name(record["organization_name"]) != normalize_name(row["org_name"]):
            raise ValueError(f'{where}: org_name "{row["org_name"]}" does not match feature {feature_index} "{record["organization_name"]}"')
        for column, type_ in EXTENDED_COLUMNS.items():
            record[column] = to_extended_value(row[column], type_, column, where)
    unmatched_features = sum(1 for r in geojson_records if r["resource_id"] is None)

    # --- Audience CSV: "Who is it for?" columns, joined by resource_id like the extended CSV ---

    audience_headers, audience_rows = _read_table(paths["audiences"], AUDIENCE_COLUMNS)
    for record in geojson_records:
        record.update(dict.fromkeys(AUDIENCE_COLUMNS))
    by_resource_id: dict[int, dict] = {}
    for record in geojson_records:
        if record["resource_id"] is not None:
            by_resource_id.setdefault(record["resource_id"], record)

    for i, cells in enumerate(audience_rows):
        where = f"{paths['audiences']} line {i + 2}"
        row = {h: cells[j] if j < len(cells) else "" for j, h in enumerate(audience_headers)}
        rid = row["resource_id"].strip()
        record = by_resource_id.get(int(rid)) if rid.isdigit() else None
        if record is None:
            raise ValueError(f"{where}: resource_id {row['resource_id']} is not in {paths['extended']}")
        for column, type_ in AUDIENCE_COLUMNS.items():
            record[column] = to_extended_value(row[column], type_, column, where)

    # --- NoMatch CSV: extra rows for the entries that have coordinates ---

    nomatch_headers, *nomatch_rows = parse_csv(read_text(paths["nomatch"], encoding="cp1252"))
    if (
        len(nomatch_headers) != NOMATCH_HEADER_COUNT
        or nomatch_headers[NOMATCH["lat"]] != "lat"
        or nomatch_headers[NOMATCH["lon"]] != "lon"
    ):
        raise ValueError(f"{paths['nomatch']}: header changed; update NOMATCH positions in this script.")

    extras: list[tuple[int, dict]] = []
    for i, cells in enumerate(nomatch_rows):
        where = f"{paths['nomatch']} line {i + 2}"
        lat_text, lon_text = cells[NOMATCH["lat"]].strip(), cells[NOMATCH["lon"]].strip()
        if not lat_text and not lon_text:
            continue
        try:
            latitude, longitude = to_number(lat_text), to_number(lon_text)
        except ValueError:
            raise ValueError(f"{where}: lat/lon must both be numbers") from None
        if not (math.isfinite(latitude) and math.isfinite(longitude)):
            raise ValueError(f"{where}: lat/lon must both be numbers")

        name = cells[NOMATCH["organization_name"]].strip()
        parent_index = next((j for j in range(len(geojson_records) - 1, -1, -1) if geojson_records[j]["organization_name"] == name), -1)
        if parent_index == -1:
            raise ValueError(f'{where}: no GeoJSON row has Organization Name "{name}"')

        # "162-24 Jamaica Avenue" -> street_number "162-24", street "Jamaica Avenue".
        place = cells[NOMATCH["place"]].strip()
        m = re.fullmatch(r"(\S*[0-9]\S*)\s+(.+)", place)
        street_number, street = (m[1], m[2]) if m else (None, place)
        # The parent row is the phone listing, so its row_type and borough do not describe this address.
        # Every extra row so far is a street address in NYC: the notebook's rules make that 'mapped'.
        city = to_text(cells[NOMATCH["city"]])
        borough = BOROUGH_BY_CITY.get(city or "")
        if not borough:
            raise ValueError(f'{where}: city "{city}" is not in BOROUGH_BY_CITY')
        record = {
            **geojson_records[parent_index],
            "street_number": street_number,
            "address_line_2": to_text(cells[NOMATCH["address2"]]),
            "street": street,
            "city": city,
            "borough": borough,
            "row_type": "mapped",
            "state": to_text(cells[NOMATCH["state"]]),
            "zip_code": to_text(cells[NOMATCH["zip"]]),
            "latitude": latitude,
            "longitude": longitude,
            "geocode_match": "matched",
            "geocode_source": "nomatch_csv",
            # No geocoder placed these points, and the NoMatch file does not say where they came from.
            "geocode_matched_address": None,
            "geocode_review": None,
        }
        extras.append((parent_index, record))

    # Each extra row goes right after its parent row; extras for one parent keep file order.
    records: list[dict] = []
    for i, record in enumerate(geojson_records):
        records.append(record)
        records.extend(extra for parent, extra in extras if parent == i)

    return {
        "records": records,
        "paths": paths,
        "counts": {
            "geojson": len(geojson_records),
            "extras": len(extras),
            "extended": len(extended_rows),
            "unmatched_features": unmatched_features,
            "audiences": len(audience_rows),
        },
    }


if __name__ == "__main__":
    for record in map_resources(ROOT)["records"]:
        sys.stdout.write(to_json(record) + "\n")
