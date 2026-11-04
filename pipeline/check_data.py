"""Checks the pipeline's data files against the schemas in pipeline/schemas/.

    python3 pipeline/check_data.py                       every schema whose file exists
    python3 pipeline/check_data.py resources_clean       only these schemas
    python3 pipeline/check_data.py --max-problems 50     show more problems per file (default 20)

Standard library only. Prints PASS or FAIL per file, with one line per problem (line number, column, what is
wrong), and exits 1 if any file fails. A file that is missing is skipped with a note, unless its schema was
named on the command line, when that is a failure.

A schema is a JSON file: the data file it describes, its format (csv or geojson), how booleans and lists are
written in it, and one entry per column. Column keys:

    type       text | integer | number | boolean | yes_no | list
    required   true when the cell may not be blank (a blank cell is otherwise always allowed)
    unique     true when no two rows may share a value
    values     the allowed values, as a list or "$name" for a list in vocabularies.json
    items      for a list column, the allowed items (same forms as values)
    pattern    a regular expression the whole value must match
    min, max   bounds for integer and number columns
    planned    true for a column that is not in the data yet: checked when present, not missing when absent
    extends    (top level) another schema whose columns come first; this schema adds to or overrides them

The columns in the file must be exactly the columns in the schema, planned ones aside: a missing or unexpected
column is a problem, because the next step and the site read these files by column name.
"""
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "pipeline" / "schemas"

BOOLEANS = {"python": {"True": True, "False": False}, "postgres": {"t": True, "f": False}}
YES_NO = {"Y": True, "N": False}


# --- Schemas ---

def load_vocabularies():
    vocab = json.loads((SCHEMAS / "vocabularies.json").read_text(encoding="utf-8"))
    return {k: v for k, v in vocab.items() if not k.startswith("_")}


def load_schema(name, vocab=None):
    """A schema with its parent's columns merged in and every "$name" replaced by the list it refers to."""
    vocab = load_vocabularies() if vocab is None else vocab
    schema = json.loads((SCHEMAS / f"{name}.json").read_text(encoding="utf-8"))
    schema["name"] = name
    if "extends" in schema:
        base = load_schema(schema["extends"], vocab)
        schema["columns"] = {**base["columns"], **schema["columns"]}
        for key in ("booleans", "lists"):
            schema.setdefault(key, base[key])
    for column, spec in schema["columns"].items():
        for key in ("values", "items"):
            if isinstance(spec.get(key), str):
                ref = spec[key]
                if not ref.startswith("$") or ref[1:] not in vocab:
                    raise ValueError(f"{name}.json: {column}.{key} refers to unknown vocabulary {ref}")
                spec[key] = vocab[ref[1:]]
    return schema


def schema_names():
    return sorted(p.stem for p in SCHEMAS.glob("*.json") if p.stem != "vocabularies")


# --- Reading data files ---

def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return rows[0], [dict(zip(rows[0], r)) for r in rows[1:]]


def read_geojson(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise ValueError("not a GeoJSON FeatureCollection")
    # Features need not carry the same properties (the geocoder adds addr:* only where it matched), so the
    # header is every property seen and a property a feature lacks counts as blank.
    header = []
    rows = []
    for feature in data["features"]:
        props = feature.get("properties") or {}
        header.extend(k for k in props if k not in header)
        rows.append({k: "" if v is None else str(v) for k, v in props.items()})
    for row in rows:
        for k in header:
            row.setdefault(k, "")
    return header, rows, data["features"]


# --- Checking cells ---

def split_list(cell, style):
    if style == "semicolon":
        return [item.strip() for item in cell.split(";")]
    if style != "postgres":
        raise ValueError(f"unknown list style {style}")
    if not (cell.startswith("{") and cell.endswith("}")):
        raise ValueError("not a Postgres array")
    inner = cell[1:-1]
    if inner == "":
        return []
    items, current, quoted, i = [], "", False, 0
    while i < len(inner):
        c = inner[i]
        if quoted:
            if c == "\\" and i + 1 < len(inner):
                current += inner[i + 1]
                i += 1
            elif c == '"':
                quoted = False
            else:
                current += c
        elif c == '"':
            quoted = True
        elif c == ",":
            items.append(current)
            current = ""
        else:
            current += c
        i += 1
    items.append(current)
    return items


def check_cell(spec, value, booleans, lists):
    """The problem with one cell, or None. The value is a string; blank is a missing value."""
    if value == "":
        return "is blank" if spec.get("required") else None
    kind = spec["type"]
    if kind == "text":
        pass
    elif kind == "integer":
        if not re.fullmatch(r"-?\d+", value):
            return f"{value!r} is not an integer"
        return check_bounds(spec, int(value), value)
    elif kind == "number":
        try:
            number = float(value)
        except ValueError:
            return f"{value!r} is not a number"
        if number != number:
            return f"{value!r} is not a number"
        return check_bounds(spec, number, value)
    elif kind == "boolean":
        if value not in BOOLEANS[booleans]:
            return f"{value!r} is not one of {', '.join(BOOLEANS[booleans])}"
    elif kind == "yes_no":
        if value not in YES_NO:
            return f"{value!r} is not Y or N"
    elif kind == "list":
        try:
            items = split_list(value, lists)
        except ValueError as e:
            return f"{value!r}: {e}"
        if any(item == "" for item in items):
            return f"{value!r} has an empty item"
        if len(set(items)) != len(items):
            return f"{value!r} repeats an item"
        if "items" in spec:
            bad = [item for item in items if item not in spec["items"]]
            if bad:
                return f"{', '.join(repr(b) for b in bad)} not in the allowed items"
    else:
        raise ValueError(f"unknown column type {kind}")
    if "values" in spec and value not in spec["values"]:
        return f"{value!r} is not one of {', '.join(spec['values'])}"
    if "pattern" in spec and not re.search(spec["pattern"], value):
        return f"{value!r} does not match {spec['pattern']}"
    return None


def check_bounds(spec, number, value):
    if "min" in spec and number < spec["min"]:
        return f"{value} is below {spec['min']}"
    if "max" in spec and number > spec["max"]:
        return f"{value} is above {spec['max']}"
    return None


# --- Checking files ---

def validate(schema, header, rows, features=None):
    """Problems as (line, column, message); line is the CSV line number or the feature index + 1."""
    problems = []
    columns = schema["columns"]
    booleans, lists = schema["booleans"], schema["lists"]
    expected = [c for c, spec in columns.items() if not spec.get("planned")]
    for column in expected:
        if column not in header:
            problems.append((1, column, "column is missing"))
    for column in header:
        if column not in columns:
            problems.append((1, column, "column is not in the schema"))
    if problems:
        return problems
    present = [c for c in columns if c in header]
    seen = {c: {} for c in present if columns[c].get("unique")}
    for i, row in enumerate(rows):
        line = i + 2
        if len(row) != len(header):
            problems.append((line, "", f"has {len(row)} cells, the header has {len(header)}"))
            continue
        for column in present:
            value = row[column]
            problem = check_cell(columns[column], value, booleans, lists)
            if problem:
                problems.append((line, column, problem))
            elif column in seen and value != "":
                if value in seen[column]:
                    problems.append((line, column, f"{value!r} repeats line {seen[column][value]}"))
                else:
                    seen[column][value] = line
    if features is not None:
        for i, feature in enumerate(features):
            problem = check_geometry(feature.get("geometry"))
            if problem:
                problems.append((i + 1, "geometry", problem))
    return problems


def check_geometry(geometry):
    if geometry is None:
        return None
    if geometry.get("type") != "Point":
        return f"is {geometry.get('type')!r}, not a Point or null"
    coordinates = geometry.get("coordinates")
    if not (isinstance(coordinates, list) and len(coordinates) == 2
            and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in coordinates)):
        return f"coordinates {coordinates!r} are not [longitude, latitude]"
    lon, lat = coordinates
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return f"coordinates {coordinates!r} are out of range (expected [longitude, latitude])"
    return None


def check_file(schema):
    path = ROOT / schema["file"]
    if schema["format"] == "csv":
        header, rows = read_csv(path)
        return validate(schema, header, rows), len(rows)
    if schema["format"] == "geojson":
        header, rows, features = read_geojson(path)
        return validate(schema, header, rows, features), len(rows)
    raise ValueError(f"unknown format {schema['format']}")


def main(argv):
    max_problems = 20
    if "--max-problems" in argv:
        at = argv.index("--max-problems")
        max_problems = int(argv[at + 1])
        argv = argv[:at] + argv[at + 2:]
    names = schema_names()
    unknown = [a for a in argv if a not in names]
    if unknown:
        print(f"unknown schema {', '.join(unknown)}; schemas are {', '.join(names)}", file=sys.stderr)
        return 2
    wanted = argv or names
    failed = 0
    for name in wanted:
        schema = load_schema(name)
        path = ROOT / schema["file"]
        if not path.exists():
            if argv:
                print(f"FAIL {schema['file']}: missing")
                failed += 1
            else:
                print(f"SKIP {schema['file']}: missing")
            continue
        try:
            problems, count = check_file(schema)
        except (ValueError, UnicodeDecodeError, csv.Error) as e:
            print(f"FAIL {schema['file']}: cannot read it: {e}")
            failed += 1
            continue
        if not problems:
            print(f"PASS {schema['file']} ({count} rows, {name}.json)")
            continue
        failed += 1
        print(f"FAIL {schema['file']}: {len(problems)} problems ({name}.json)")
        for line, column, message in problems[:max_problems]:
            where = f"line {line}" if schema["format"] == "csv" else f"feature {line}"
            print(f"  {where}, {column}: {message}" if column else f"  {where}: {message}")
        if len(problems) > max_problems:
            print(f"  ... and {len(problems) - max_problems} more (--max-problems to see them)")
    if failed:
        print(f"{failed} of {len(wanted)} files failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
