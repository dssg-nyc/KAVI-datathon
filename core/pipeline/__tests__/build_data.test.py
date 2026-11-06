# Tests for core/pipeline/build_data.py. Run from the repo root:  uv run core/pipeline/__tests__/build_data.test.py
import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ next to the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_data as b  # noqa: E402
from map_resources import ROOT, read_text  # noqa: E402

KAVI_SCHEMA = json.loads(read_text(ROOT / "core" / "schemas" / "kavi_resources.json"))
TABLE_COLUMNS = [name for name, spec in KAVI_SCHEMA["columns"].items() if not spec.get("planned")]


class SplitRows(unittest.TestCase):
    record = {"organization_name": "A", "street": None, "latitude": 40.7, "service_types_all": ["Food"], "needs_review": True, "geocode_match": "match"}

    def setUp(self):
        self.public, self.provenance = b.split_rows([self.record], ["7"])

    def test_public_rows_have_exactly_the_public_columns_blank_where_the_record_has_none(self):
        self.assertEqual(list(self.public[0]), b.PUBLIC_COLUMNS)
        self.assertEqual(self.public[0]["id"], "7")
        self.assertEqual(self.public[0]["organization_name"], "A")
        self.assertIsNone(self.public[0]["row_type"])
        self.assertEqual(self.public[0]["review_flags"], b.review_flags(self.record))

    def test_provenance_rows_carry_the_id_and_every_other_column(self):
        self.assertEqual(self.provenance[0], {"id": "7", "needs_review": True, "geocode_match": "match"})

    def test_json_is_one_row_per_line(self):
        self.assertEqual(b.rows_json([{"a": 1}, {"b": [2]}]), '[\n  {"a":1},\n  {"b":[2]}\n]\n')


class ReviewFlags(unittest.TestCase):
    # A row with everything confirmed: guide-mapped services, checked audiences, stated eligibility, a clean geocode, no notes.
    clean = {
        "service_type_extended_source": "pr:guide_mapping", "description_service_types_source": "description_keywords",
        "audience_needs_review": False, "everyone_basis": "stated", "geocode_match": "matched", "geocode_review": None,
        "needs_review_extended": False, "review_notes_extended": None,
    }
    # What raises each flag on its own.
    raise_ = {
        "services": {"service_type_extended_source": "pr:description_match"},
        "audiences": {"audience_needs_review": True},
        "eligibility": {"everyone_basis": "assumed"},
        "location": {"geocode_match": "unmatched"},
        "details": {"needs_review_extended": True, "review_notes_extended": "In NoMatch file"},
    }

    def test_a_confirmed_row_has_no_flags(self):
        self.assertEqual(b.review_flags(self.clean), [])

    def test_each_flag_is_raised_by_its_own_column_alone(self):
        for flag in b.REVIEW_FLAGS:
            self.assertEqual(b.review_flags({**self.clean, **self.raise_[flag]}), [flag])

    def test_every_combination_of_flags_comes_out_in_review_flags_order(self):
        for bits in range(1 << len(b.REVIEW_FLAGS)):
            expected = [flag for i, flag in enumerate(b.REVIEW_FLAGS) if bits & (1 << i)]
            record = dict(self.clean)
            for flag in expected:
                record.update(self.raise_[flag])
            self.assertEqual(b.review_flags(record), expected, f"bits {bits:b}")

    def test_services_are_confirmed_by_the_guide_the_organization_or_a_person(self):
        c = self.clean
        self.assertEqual(b.review_flags({**c, "service_type_extended_source": "pdf_section"}), [])
        self.assertEqual(b.review_flags({**c, "service_type_extended_source": "pr:organization_consensus"}), [])
        self.assertEqual(b.review_flags({**c, "service_type_extended_source": "unassigned", "description_service_types_source": "human_agreed"}), [])
        self.assertEqual(b.review_flags({**c, "service_type_extended_source": "unassigned"}), ["services"])
        self.assertEqual(b.review_flags({**c, "service_type_extended_source": None, "description_service_types_source": None}), ["services"])
        self.assertEqual(b.review_flags({**c, "geocode_review": "Confirm the location."}), ["location"])

    def test_service_type_to_assign_alone_is_the_services_flag_not_a_details_note(self):
        c = {**self.clean, "needs_review_extended": True}
        self.assertEqual(b.review_flags({**c, "review_notes_extended": "service_type to assign"}), [])
        self.assertEqual(b.review_flags({**c, "review_notes_extended": "In NoMatch file | service_type to assign"}), ["details"])


class MetaJson(unittest.TestCase):
    def test_names_the_source_and_dates_the_data(self):
        meta = json.loads(b.meta_json({b.PUBLIC_PATH: "changed"}, date(2026, 1, 2)))
        self.assertEqual(meta, {"source": b.SOURCE, "data_updated": "2026-01-02"})

    def test_keeps_the_committed_date_while_the_row_files_are_unchanged(self):
        committed = json.loads(read_text(b.META_PATH))
        same = {b.PUBLIC_PATH: read_text(b.PUBLIC_PATH), b.PROVENANCE_PATH: read_text(b.PROVENANCE_PATH)}
        self.assertEqual(json.loads(b.meta_json(same, date(2099, 1, 1))), committed)
        self.assertRegex(committed["data_updated"], r"^\d{4}-\d{2}-\d{2}$")


class NeedsAddress(unittest.TestCase):
    def test_is_a_placeable_row_with_a_street_but_no_coordinates(self):
        self.assertTrue(b.needs_address({"row_type": "mapped", "street": "Main St", "latitude": None}))
        self.assertTrue(b.needs_address({"row_type": "mailing_address", "street_number": "1", "street": None, "latitude": None}))
        self.assertFalse(b.needs_address({"row_type": "mapped", "street": "Main St", "latitude": 40.7}))
        self.assertFalse(b.needs_address({"row_type": "hotline", "street": "Main St", "latitude": None}))
        self.assertFalse(b.needs_address({"row_type": "mapped", "street": None, "street_number": None, "latitude": None}))


class CommittedFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records, cls.files = b.build_data()
        cls.public = json.loads(read_text(b.PUBLIC_PATH))
        cls.provenance = json.loads(read_text(b.PROVENANCE_PATH))

    def test_are_what_the_committed_data_produces(self):
        for path, content in self.files.items():
            self.assertEqual(read_text(path), content, path)

    def test_keep_every_row_the_loader_produces(self):
        # D2: nothing is dropped between source and site.
        self.assertEqual(len(self.public), len(self.records))
        self.assertEqual(len(self.provenance), len(self.records))
        self.assertEqual(len(self.records), 765)

    def test_use_ids_that_are_unique_and_the_same_in_both_files(self):
        ids = [r["id"] for r in self.public]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual([r["id"] for r in self.provenance], ids)

    def test_together_hold_every_table_column_once_plus_review_flags(self):
        columns = [*self.public[0], *(c for c in self.provenance[0] if c != "id")]
        self.assertEqual(sorted(columns), sorted([*TABLE_COLUMNS, "review_flags"]))

    def test_flag_what_the_data_says_is_unconfirmed(self):
        def flagged(flag):
            return sum(1 for r in self.public if flag in r["review_flags"])

        self.assertEqual(flagged("audiences"), sum(1 for r in self.records if r["audience_needs_review"] is True))
        self.assertEqual(flagged("eligibility"), sum(1 for r in self.records if r["everyone_basis"] == "assumed"))
        self.assertTrue(flagged("services") > 0 and flagged("location") > 0 and flagged("details") > 0)

    def test_list_the_rows_with_an_address_but_no_map_point(self):
        lines = read_text(b.NEEDS_ADDRESS_PATH).strip().split("\n")
        self.assertEqual(len(lines) - 1, sum(map(b.needs_address, self.records)))


if __name__ == "__main__":
    unittest.main()
