"""Writes the data files the site reads, from the pipeline's output.

The rows are the same ones the loader sends to Supabase (map_resources.py), keyed by the
stable id from data/resource_ids.csv instead of the database id. They are split in two files:

  data/public/resources.public.json      the columns the finder shows and filters on, plus
                                         review_flags, which names what nobody has checked yet
  data/public/resources.provenance.json  everything else: source fields, review flags, how each
                                         value was derived; joined to the public file by id
  data/public/resources.meta.json        where the data comes from and when it last changed

Every row goes into both files, including the cross-reference and blank rows; the finder decides
what to list, as it does today. The files are committed, so the site needs no build step on
deploy and a change to the data shows up as a diff. A third file, data/review/needs_address.csv,
lists the rows that have an address but no point on the map, for someone to check.

  uv run core/pipeline/build_data.py            check: fail if any file would change
  uv run core/pipeline/build_data.py --write    write the files
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from map_resources import ROOT, map_resources, read_text, to_json
from resource_ids import assign_ids, read_mapping
from resource_ids import to_csv as mapping_to_csv

PUBLIC_PATH = ROOT / "data" / "public" / "resources.public.json"
PROVENANCE_PATH = ROOT / "data" / "public" / "resources.provenance.json"
NEEDS_ADDRESS_PATH = ROOT / "data" / "review" / "needs_address.csv"
META_PATH = ROOT / "data" / "public" / "resources.meta.json"

# What the finder reads (app/lib/csv.js FINDER_COLUMNS), with the stable id in place of the database one.
# review_flags is not a table column: it is derived here, see review_flags().
PUBLIC_COLUMNS = [
    "id", "resource_id", "organization_name", "street_number", "street", "address_line_2", "city", "state", "zip_code",
    "phone_number", "website", "description", "spanish_speaking", "latitude", "longitude", "borough", "row_type",
    "service_types_all", "audiences_all", "restricted_audiences", "focus_audiences", "pdf_audiences", "review_flags",
]

# What the site says about where the data comes from. data_updated is the day the two row files last changed.
SOURCE = "The NYPL Connections guide, extended from the printed guide and geocoded by the DSSG NYC pipeline"

# The values a row shows that nobody has confirmed yet, so the site can say so (requirement D4, D5).
# Each flag names one part of the card, and the finder's wording for it is in app/lib/resources.js.
#   services     the service types came from keywords in the description, not from the guide's chapter,
#                the organization's other listings or a person
#   audiences    the audience tagger asked for a check (audience_needs_review)
#   eligibility  "Everyone" was assumed because the listing states no restriction (everyone_basis)
#   location     the geocoder could not place the address, or left a note to confirm the point
#   details      the pipeline left a note on the listing itself (duplicate, missing from the PDF, ...)
REVIEW_FLAGS = ["services", "audiences", "eligibility", "location", "details"]

CONFIRMED_SERVICE_SOURCES = ["pr:guide_mapping", "pdf_section", "pr:organization_consensus"]


def review_flags(record: dict) -> list[str]:
    flags = []
    services_confirmed = record.get("service_type_extended_source") in CONFIRMED_SERVICE_SOURCES or str(
        record.get("description_service_types_source") or ""
    ).startswith("human_")
    if not services_confirmed:
        flags.append("services")
    if record.get("audience_needs_review") is True:
        flags.append("audiences")
    if record.get("everyone_basis") == "assumed":
        flags.append("eligibility")
    if record.get("geocode_match") == "unmatched" or record.get("geocode_review"):
        flags.append("location")
    if record.get("needs_review_extended") is True and record.get("review_notes_extended") != "service_type to assign":
        flags.append("details")
    return flags


def needs_address(record: dict) -> bool:
    """A row that someone could place on the map but the geocoder did not: it names a street but has no
    coordinates, and is not a hotline, web-only or cross-reference listing."""
    placeable = record.get("row_type") in ("mapped", "mailing_address", "outside_nyc")
    return placeable and record.get("latitude") is None and bool(record.get("street") or record.get("street_number"))


def split_rows(records: list[dict], ids: list[str]) -> tuple[list[dict], list[dict]]:
    public_rows, provenance_rows = [], []
    for record, id_ in zip(records, ids):
        pub = {"id": id_}
        for column in PUBLIC_COLUMNS[1:]:
            pub[column] = record.get(column)
        pub["review_flags"] = review_flags(record)
        prov = {"id": id_}
        prov.update((column, value) for column, value in record.items() if column not in PUBLIC_COLUMNS)
        public_rows.append(pub)
        provenance_rows.append(prov)
    return public_rows, provenance_rows


def rows_json(rows: list[dict]) -> str:
    """One row per line, so a data change is a readable diff."""
    return "[\n" + ",\n".join("  " + to_json(r) for r in rows) + "\n]\n"


def _csv_cell(v) -> str:
    s = "" if v is None else str(v)
    return '"' + s.replace('"', '""') + '"' if re.search(r'[",\n\r]', s) else s


def needs_address_csv(records: list[dict], ids: list[str]) -> str:
    columns = ["id", "organization_name", "row_type", "street_number", "street", "address_line_2", "city", "state", "zip_code", "geocode_match", "geocode_review"]
    lines = [",".join(columns)]
    for record, id_ in zip(records, ids):
        if needs_address(record):
            lines.append(",".join(_csv_cell(id_ if c == "id" else record.get(c)) for c in columns))
    return "\n".join(lines) + "\n"


def _read_or_blank(path: Path) -> str:
    try:
        return read_text(path)
    except FileNotFoundError:
        return ""


def meta_json(row_files: dict[Path, str], today: date | None = None) -> str:
    """The meta file keeps its date while the row files are unchanged, so a check run writes nothing new."""
    current = _read_or_blank(META_PATH)
    unchanged = bool(current) and all(_read_or_blank(path) == content for path, content in row_files.items())
    if unchanged:
        updated = json.loads(current)["data_updated"]
    else:
        updated = (today or datetime.now(timezone.utc).date()).isoformat()
    return json.dumps({"source": SOURCE, "data_updated": updated}, indent=2, ensure_ascii=False) + "\n"


def build_data() -> tuple[list[dict], dict[Path, str]]:
    records = map_resources(ROOT)["records"]
    existing = read_mapping()
    mapping = assign_ids(records, existing)["rows"]
    if mapping_to_csv(mapping) != mapping_to_csv(existing):
        raise RuntimeError("data/resource_ids.csv is out of date: run `npm run ids -- --write` first and commit it")
    ids = [r["id"] for r in mapping[: len(records)]]
    public_rows, provenance_rows = split_rows(records, ids)
    row_files = {PUBLIC_PATH: rows_json(public_rows), PROVENANCE_PATH: rows_json(provenance_rows)}
    files = {
        **row_files,
        META_PATH: meta_json(row_files),
        NEEDS_ADDRESS_PATH: needs_address_csv(records, ids),
    }
    return records, files


def main() -> int:
    write = "--write" in sys.argv[1:]
    records, files = build_data()
    print(f"{len(records)} rows, {sum(map(needs_address, records))} with an address but no point on the map")
    stale = 0
    for path, content in files.items():
        if _read_or_blank(path) == content:
            print(f"{path} is up to date")
            continue
        stale += 1
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
            print(f"Wrote {path}")
        else:
            print(f"{path} would change", file=sys.stderr)
    if stale and not write:
        print("Run with --write to update the files, then commit them.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
