"""Gives every resource an id that does not change between builds.

The database id changes on every `import --replace`, and resource_id is the row's position in
the guide export, which repeats (the NEON clothing closets are five rows for one resource_id)
and would shift if NYPL re-exported the guide. So the id is taken from resource_id, with a
suffix where it repeats, and the result is written to data/resource_ids.csv and committed.
On the next run a row is looked up in that file by name and address first, so it keeps its id
even if its resource_id moved; only rows not seen before get a new id. A row that is no longer
in the data stays in the file as retired, so its id is never given to another resource.

  uv run core/pipeline/resource_ids.py            check: fail if the file would change
  uv run core/pipeline/resource_ids.py --write    update data/resource_ids.csv
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from map_resources import ROOT, map_resources, parse_csv, read_text

MAPPING_PATH = ROOT / "data" / "resource_ids.csv"
MAPPING_COLUMNS = ["id", "status", "resource_id", "organization_name", "street_number", "street", "city", "zip_code"]


def _text(v) -> str:
    return "" if v is None else str(v)


def fingerprint(row: dict) -> str:
    """How a row is recognised across builds: its name and address, case and spacing ignored."""
    key = "|".join(
        re.sub(r"\s+", " ", row[c].lower()).strip()
        for c in ("organization_name", "street_number", "street", "city", "zip_code")
    )
    # A row with no name or address (one such row exists) is matched by its source id instead, so a reorder
    # of the source cannot swap its id with another blank row's.
    return f"resource_id:{row['resource_id'].strip()}" if key == "||||" else key


def _describe(record: dict) -> dict:
    return {c: _text(record.get(c)) for c in ("resource_id", "organization_name", "street_number", "street", "city", "zip_code")}


def assign_ids(records: list[dict], existing: list[dict]) -> dict:
    """The mapping for these records, given the committed one. Rows come out in record order, then
    the retired rows in their old order."""
    unclaimed: dict[str, list[dict]] = {}
    for row in existing:
        unclaimed.setdefault(fingerprint(row), []).append(row)
    taken = {r["id"] for r in existing}
    rows: list[dict] = []
    kept = added = 0
    for index, record in enumerate(records):
        fields = _describe(record)
        candidates = unclaimed.get(fingerprint(fields))
        if candidates:
            previous = candidates.pop(0)
            kept += 1
            rows.append({"id": previous["id"], "status": "active", **fields})
            continue
        base = fields["resource_id"] or f"feature-{index}"
        new_id, n = base, 2
        while new_id in taken:
            new_id, n = f"{base}-{n}", n + 1
        taken.add(new_id)
        added += 1
        rows.append({"id": new_id, "status": "active", **fields})
    retired = [row for group in unclaimed.values() for row in group]
    rows.extend({**row, "status": "retired"} for row in retired)
    return {"rows": rows, "kept": kept, "added": added, "retired": len(retired)}


def csv_cell(v: str) -> str:
    return '"' + v.replace('"', '""') + '"' if re.search(r'[",\n\r]', v) else v


def to_csv(rows: list[dict]) -> str:
    lines = [",".join(MAPPING_COLUMNS)]
    lines += [",".join(csv_cell(row[c]) for c in MAPPING_COLUMNS) for row in rows]
    return "\n".join(lines) + "\n"


def from_csv(content: str) -> list[dict]:
    parsed = parse_csv(content)
    header, body = (parsed[0], parsed[1:]) if parsed else ([], [])
    missing = [c for c in MAPPING_COLUMNS if c not in header]
    if missing:
        raise ValueError(f"{MAPPING_PATH}: missing columns {', '.join(missing)}")
    return [{h: cells[j] if j < len(cells) else "" for j, h in enumerate(header)} for cells in body]


def read_mapping(path: Path = MAPPING_PATH) -> list[dict]:
    try:
        return from_csv(read_text(path))
    except FileNotFoundError:
        return []


def main() -> int:
    write = "--write" in sys.argv[1:]
    existing = read_mapping()
    records = map_resources(ROOT)["records"]
    result = assign_ids(records, existing)
    ids = [r["id"] for r in result["rows"]]
    if len(set(ids)) != len(ids):
        raise ValueError("ids are not unique")
    print(f"{len(records)} rows: {result['kept']} keep their id, {result['added']} new, {result['retired']} retired")
    new = to_csv(result["rows"])
    current = to_csv(existing) if existing else ""
    if new == current:
        print(f"{MAPPING_PATH} is up to date")
        return 0
    if not write:
        print(f"{MAPPING_PATH} would change. Run with --write to update it, then commit the file.", file=sys.stderr)
        return 1
    with open(MAPPING_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    print(f"Wrote {MAPPING_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
