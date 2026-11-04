# Tests for pipeline/check_data.py. Run from the repo root:  python3 pipeline/__tests__/check_data.test.py
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_data  # noqa: E402

SCHEMA = {
    "booleans": "python",
    "lists": "semicolon",
    "columns": {
        "id": {"type": "integer", "required": True, "unique": True, "min": 1},
        "name": {"type": "text", "required": True},
        "kind": {"type": "text", "values": ["a", "b"]},
        "tags": {"type": "list", "items": ["x", "y"]},
        "ok": {"type": "boolean"},
        "yn": {"type": "yes_no"},
        "lat": {"type": "number", "min": -90, "max": 90},
        "zip": {"type": "text", "pattern": "^\\d{5}$"},
        "hours": {"type": "text", "planned": True},
    },
}
HEADER = ["id", "name", "kind", "tags", "ok", "yn", "lat", "zip"]


def row(**changes):
    base = {"id": "1", "name": "A", "kind": "a", "tags": "x; y", "ok": "True", "yn": "Y", "lat": "40.7", "zip": "10001"}
    base.update(changes)
    return base


def problems(*rows, header=HEADER):
    return check_data.validate(SCHEMA, header, list(rows))


class Cells(unittest.TestCase):
    def test_valid_row_has_no_problems(self):
        self.assertEqual(problems(row()), [])

    def test_blank_is_fine_unless_required(self):
        self.assertEqual(problems(row(kind="", tags="", ok="", yn="", lat="", zip="")), [])
        self.assertEqual([p[1] for p in problems(row(name=""))], ["name"])

    def test_types(self):
        self.assertEqual([p[1] for p in problems(row(id="x"))], ["id"])
        self.assertEqual([p[1] for p in problems(row(ok="yes"))], ["ok"])
        self.assertEqual([p[1] for p in problems(row(yn="true"))], ["yn"])
        self.assertEqual([p[1] for p in problems(row(lat="north"))], ["lat"])

    def test_bounds_values_pattern(self):
        self.assertEqual([p[1] for p in problems(row(id="0"))], ["id"])
        self.assertEqual([p[1] for p in problems(row(lat="91"))], ["lat"])
        self.assertEqual([p[1] for p in problems(row(kind="c"))], ["kind"])
        self.assertEqual([p[1] for p in problems(row(zip="1001"))], ["zip"])

    def test_lists(self):
        self.assertEqual([p[1] for p in problems(row(tags="x; z"))], ["tags"])
        self.assertEqual([p[1] for p in problems(row(tags="x; x"))], ["tags"])
        self.assertEqual([p[1] for p in problems(row(tags="x;"))], ["tags"])

    def test_postgres_booleans_and_arrays(self):
        self.assertEqual(check_data.split_list('{"Formerly Incarcerated People",Everyone}', "postgres"),
                         ["Formerly Incarcerated People", "Everyone"])
        self.assertEqual(check_data.split_list("{}", "postgres"), [])
        self.assertIsNone(check_data.check_cell({"type": "boolean"}, "t", "postgres", "postgres"))
        self.assertIsNotNone(check_data.check_cell({"type": "boolean"}, "True", "postgres", "postgres"))
        self.assertIsNotNone(check_data.check_cell({"type": "list"}, "a; b", "python", "postgres"))


class Files(unittest.TestCase):
    def test_duplicate_key(self):
        found = problems(row(id="1"), row(id="1", name="B"))
        self.assertEqual([(p[0], p[1]) for p in found], [(3, "id")])

    def test_missing_and_unexpected_columns(self):
        found = problems(row(), header=["id", "name", "kind", "tags", "ok", "yn", "lat", "extra"])
        self.assertEqual(sorted((p[1], p[2]) for p in found),
                         [("extra", "column is not in the schema"), ("zip", "column is missing")])

    def test_planned_column_may_be_absent_or_present(self):
        self.assertEqual(problems(row()), [])
        self.assertEqual(problems({**row(), "hours": "Mon-Fri 9-5"}, header=HEADER + ["hours"]), [])

    def test_short_row(self):
        found = check_data.validate(SCHEMA, HEADER, [dict(zip(HEADER[:3], ["1", "A", "a"]))])
        self.assertEqual(len(found), 1)
        self.assertIn("cells", found[0][2])

    def test_geometry(self):
        self.assertIsNone(check_data.check_geometry(None))
        self.assertIsNone(check_data.check_geometry({"type": "Point", "coordinates": [-73.9, 40.7]}))
        self.assertIn("not a Point", check_data.check_geometry({"type": "Polygon", "coordinates": []}))
        self.assertIn("out of range", check_data.check_geometry({"type": "Point", "coordinates": [-73.9, 140.7]}))
        self.assertIn("not [longitude", check_data.check_geometry({"type": "Point", "coordinates": [1]}))

    def test_json_cells(self):
        self.assertEqual(check_data.json_cell(None), "")
        self.assertEqual(check_data.json_cell(True), "True")
        self.assertEqual(check_data.json_cell(40.7), "40.7")
        self.assertEqual(check_data.json_cell(["Food", "Housing"]), "Food; Housing")
        self.assertEqual(check_data.json_cell([]), "")


class RealSchemas(unittest.TestCase):
    def test_every_schema_loads_and_vocabularies_resolve(self):
        names = check_data.schema_names()
        self.assertIn("resources_clean", names)
        for name in names:
            schema = check_data.load_schema(name)
            self.assertIn(schema["format"], ("csv", "geojson", "json"), name)
            for column, spec in schema["columns"].items():
                self.assertIn(spec["type"], ("text", "integer", "number", "boolean", "yes_no", "list"), f"{name}.{column}")
                for key in ("values", "items"):
                    if key in spec:
                        self.assertIsInstance(spec[key], list, f"{name}.{column}.{key}")

    def test_extended_starts_with_the_clean_columns(self):
        clean = list(check_data.load_schema("resources_clean")["columns"])
        extended = list(check_data.load_schema("resources_extended")["columns"])
        self.assertEqual(extended[:len(clean)], clean)


if __name__ == "__main__":
    unittest.main()
