"""Tests for the pure helpers in fetch_sources.py (no network).

    uv run pipeline/supplement/__tests__/fetch_sources.test.py
"""

import csv
import json
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ next to the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core.pipeline.supplement.fetch_sources as f  # noqa: E402


class Helpers(unittest.TestCase):
    def test_borough_from_zip(self):
        for z, b in [("10001-1234", "Manhattan"), ("10301", "Staten Island"), ("10458", "The Bronx"),
                     ("11201", "Brooklyn"), ("11375", "Queens"), ("11004", "Queens"), ("11693", "Queens")]:
            self.assertEqual(f.borough_from_zip(z), b)
        for z in ("11550", "07030", "12207", "", "abc"):
            self.assertEqual(f.borough_from_zip(z), "")

    def test_norm_borough(self):
        self.assertEqual(f.norm_borough("BRONX"), "The Bronx")
        self.assertEqual(f.norm_borough("Kings County"), "Brooklyn")
        self.assertEqual(f.norm_borough("New York"), "Manhattan")
        self.assertEqual(f.norm_borough("Richmond"), "Staten Island")
        self.assertEqual(f.norm_borough("Albany"), "")

    def test_bin_placeholders_blanked(self):
        self.assertEqual(f.clean_bin("1026911"), "1026911")
        self.assertEqual(f.clean_bin("3000000"), "")
        self.assertEqual(f.clean_bin("1026911.0"), "1026911")
        self.assertEqual(f.clean_bin(""), "")

    def test_split_address(self):
        self.assertEqual(f.split_address("33-27 97TH STREET"), ("33-27", "97TH STREET"))
        self.assertEqual(f.split_address("PO BOX 12"), ("", "PO BOX 12"))

    def test_coordinates_outside_nyc_blanked(self):
        self.assertEqual(f.lat_("40.75"), "40.75")
        self.assertEqual(f.lat_("0"), "")
        self.assertEqual(f.lon_("-73.99"), "-73.99")

    def test_unique_ids(self):
        rows = [{"source_id": "a"}, {"source_id": "a"}, {"source_id": "b"}]
        self.assertEqual([r["source_id"] for r in f.unique_ids(rows)], ["a", "a-2", "b"])

    def test_finish_sorts_and_filters(self):
        rows = [f.row("x", "2", "B", borough="Queens"), f.row("x", "1", "A", borough="Brooklyn"),
                f.row("x", "3", "C", borough="")]
        kept, info = f.finish("x", rows)
        self.assertEqual([r["source_id"] for r in kept], ["1", "2"])
        self.assertEqual(info["dropped"], 1)


class ConfidentialEndgbv(unittest.TestCase):
    """Runs on the real data/supplement/endgbv.csv. That file is not committed, so a clean clone skips this:
    regenerate it with fetch_sources.py to run these checks before relying on it."""

    LOCATION_COLUMNS = ("address", "house_number", "street", "zip", "lat", "lon", "bin", "url")
    LOCATION_KEYS = ("address", "zip", "latitude", "longitude", "bin", "bbl", "community_board", "council_district",
                     "census_tract", "nta", "url", "loc", "location", "geocoded_column")
    STREET = re.compile(r"\b\d+[A-Za-z]?\s+(?:[NSEW]\.?\s+)?[A-Za-z0-9 ]*\b(?:st|street|ave|avenue|rd|road|blvd|"
                        r"boulevard|pl|place|dr|drive|ln|lane|way|pkwy|parkway|broadway)\b", re.I)

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[3] / "data" / "supplement" / "endgbv.csv"
        if not path.exists():
            raise unittest.SkipTest("endgbv.csv not generated")
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        cls.hidden = [(r, json.loads(r["raw_json"] or "{}")) for r in rows
                      if json.loads(r["raw_json"] or "{}").get("display_physical_address") == "No"]

    def test_there_are_confidential_rows(self):
        self.assertGreater(len(self.hidden), 0)

    def test_location_columns_blank(self):
        for r, _ in self.hidden:
            for col in self.LOCATION_COLUMNS:
                self.assertEqual(r[col], "", f"{r['source_id']} {col}")

    def test_raw_json_has_no_location_fields(self):
        for r, raw in self.hidden:
            self.assertEqual([k for k in raw if k in self.LOCATION_KEYS], [], r["source_id"])

    def test_free_text_has_no_street_address(self):
        for r, raw in self.hidden:
            for field, value in [("name", r["name"]), ("operator", r["operator"]),
                                 ("primary_type", r["primary_type"]), *raw.items()]:
                self.assertIsNone(self.STREET.search(str(value)), f"{r['source_id']} {field}: {value}")


if __name__ == "__main__":
    unittest.main()
