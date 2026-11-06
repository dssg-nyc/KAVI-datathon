# Tests for core/pipeline/map_resources.py, the mapping from the pipeline's files to the rows of
# public.resources. Run from the repo root:  uv run core/pipeline/__tests__/map_resources.test.py
#
# The loader in supabase/ keeps a JavaScript copy of the same mapping (supabase/map_resources.mjs).
# test_the_loader_maps_the_same_rows runs both on the committed data and fails if they disagree.
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ next to the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import map_resources as m  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
LOADER_MAPPING = ROOT / "supabase" / "map_resources.mjs"


class Values(unittest.TestCase):
    def test_blank_is_none_for_every_type(self):
        for type_ in ("text", "list", "integer", "boolean"):
            self.assertIsNone(m.to_extended_value("  ", type_, "c", "w"))

    def test_lists_split_on_semicolon_and_drop_empty_items(self):
        self.assertEqual(m.to_extended_value("Housing; Food; ", "list", "c", "w"), ["Housing", "Food"])

    def test_integers_and_booleans_are_strict(self):
        self.assertEqual(m.to_extended_value("42", "integer", "c", "w"), 42)
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            m.to_extended_value("4.2", "integer", "c", "w")
        self.assertIs(m.to_extended_value("True", "boolean", "c", "w"), True)
        with self.assertRaisesRegex(ValueError, "must be True, False or blank"):
            m.to_extended_value("yes", "boolean", "c", "w")

    def test_yes_no_columns_keep_blank_as_unknown(self):
        self.assertIsNone(m.to_boolean("", "h", "w"))
        self.assertIs(m.to_boolean("y", "h", "w"), True)
        with self.assertRaisesRegex(ValueError, "must be Y, N or blank"):
            m.to_boolean("maybe", "h", "w")

    def test_csv_quotes_and_line_endings(self):
        self.assertEqual(m.parse_csv('a,b\r\n1,"x, ""y"""\r\n\r\n'), [["a", "b"], ["1", 'x, "y"']])

    def test_whole_numbers_stay_whole(self):
        self.assertEqual(m.to_json([m.to_number("40"), m.to_number("-73.95")]), "[40,-73.95]")


class CommittedData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = m.map_resources(ROOT)
        cls.records, cls.counts = result["records"], result["counts"]

    def test_one_row_per_feature_plus_the_located_nomatch_rows(self):
        self.assertEqual(len(self.records), self.counts["geojson"] + self.counts["extras"])
        self.assertEqual(self.counts["geojson"], 760)
        self.assertEqual(self.counts["extras"], 5)

    def test_every_row_has_every_column_the_table_expects(self):
        columns = ["organization_name", "latitude", "longitude", "geocode_match", *m.EXTENDED_COLUMNS, *m.AUDIENCE_COLUMNS]
        for record in self.records:
            for column in columns:
                self.assertIn(column, record)

    def test_extended_rows_join_onto_the_right_feature(self):
        named = [r for r in self.records if r["resource_id"] is not None and r["organization_name"]]
        self.assertGreater(len(named), 700)
        self.assertEqual(self.counts["unmatched_features"], 1)

    def test_nomatch_extras_follow_their_parent_and_carry_its_fields(self):
        extras = [(i, r) for i, r in enumerate(self.records) if r["geocode_source"] == "nomatch_csv"]
        self.assertEqual(len(extras), self.counts["extras"])
        for i, extra in extras:
            parent = next(r for r in reversed(self.records[:i]) if r["geocode_source"] != "nomatch_csv")
            self.assertEqual(extra["organization_name"], parent["organization_name"])
            self.assertEqual(extra["resource_id"], parent["resource_id"])
            self.assertEqual(extra["row_type"], "mapped")
            self.assertIsInstance(extra["latitude"], float)
            self.assertIsInstance(extra["longitude"], float)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_loader_maps_the_same_rows(self):
        script = (
            f"const {{ mapResources }} = await import({json.dumps(LOADER_MAPPING.as_uri())});"
            f"const {{ records }} = await mapResources({json.dumps(str(ROOT))});"
            "process.stdout.write(records.map((r) => JSON.stringify(r) + '\\n').join(''));"
        )
        loader = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
        js_lines = loader.stdout.splitlines()
        py_lines = [m.to_json(r) for r in self.records]
        self.assertEqual(len(js_lines), len(py_lines))
        for i, (js, py) in enumerate(zip(js_lines, py_lines)):
            self.assertEqual(py, js, f"row {i} differs: update supabase/map_resources.mjs and map_resources.py together")


if __name__ == "__main__":
    unittest.main()
