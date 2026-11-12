# Tests for core/pipeline/resource_ids.py. Run from the repo root:  uv run core/pipeline/__tests__/resource_ids.test.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ next to the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from map_resources import ROOT, map_resources  # noqa: E402
from resource_ids import assign_ids, fingerprint, from_csv, read_mapping, to_csv  # noqa: E402


def row(resource_id, organization_name, street=None):
    return {"resource_id": resource_id, "organization_name": organization_name, "street_number": None, "street": street, "city": None, "zip_code": None}


class AssignIds(unittest.TestCase):
    def test_ids_come_from_resource_id_with_a_suffix_where_it_repeats(self):
        result = assign_ids([row(1, "A"), row(2, "NEON"), row(2, "NEON", "Adams St"), row(2, "NEON", "Bay St")], [])
        self.assertEqual([r["id"] for r in result["rows"]], ["1", "2", "2-2", "2-3"])
        self.assertEqual(result["added"], 4)

    def test_a_row_without_a_resource_id_is_named_by_its_position(self):
        rows = assign_ids([row(1, "A"), row(None, "")], [])["rows"]
        self.assertEqual(rows[1]["id"], "feature-1")

    def test_a_row_keeps_its_id_when_its_resource_id_moves(self):
        first = assign_ids([row(1, "A"), row(2, "B")], [])["rows"]
        result = assign_ids([row(1, "New"), row(2, "A"), row(3, "B")], first)
        self.assertEqual([[r["id"], r["organization_name"]] for r in result["rows"]], [["1-2", "New"], ["1", "A"], ["2", "B"]])
        self.assertEqual(result["kept"], 2)
        self.assertEqual(result["added"], 1)

    def test_a_row_that_disappears_is_retired_and_its_id_is_not_reused(self):
        first = assign_ids([row(1, "A"), row(2, "B")], [])["rows"]
        second = assign_ids([row(1, "A")], first)["rows"]
        self.assertEqual([[r["id"], r["status"]] for r in second], [["1", "active"], ["2", "retired"]])
        third = assign_ids([row(1, "A"), row(2, "C")], second)["rows"]
        self.assertEqual(
            [[r["id"], r["organization_name"], r["status"]] for r in third],
            [["1", "A", "active"], ["2-2", "C", "active"], ["2", "B", "retired"]],
        )

    def test_fingerprints_ignore_case_and_spacing(self):
        a = {"resource_id": "7", "organization_name": "The  Fortune Society", "street_number": "29-76", "street": "Northern Blvd", "city": "Queens", "zip_code": "11101"}
        self.assertEqual(fingerprint(a), fingerprint({**a, "organization_name": "the fortune society ", "street": "northern  blvd"}))

    def test_a_row_with_no_name_or_address_is_matched_by_its_source_id(self):
        blank = {"organization_name": "", "street_number": "", "street": "", "city": "", "zip_code": ""}
        self.assertNotEqual(fingerprint({**blank, "resource_id": "3"}), fingerprint({**blank, "resource_id": "4"}))
        first = assign_ids([{"resource_id": "3", **blank}, {"resource_id": "4", **blank}], [])["rows"]
        reordered = assign_ids([{"resource_id": "4", **blank}, {"resource_id": "3", **blank}], first)["rows"]
        self.assertEqual([[r["resource_id"], r["id"]] for r in reordered], [["4", "4"], ["3", "3"]])

    def test_the_csv_round_trips(self):
        rows = [{"id": "1", "status": "active", "resource_id": "1", "organization_name": 'A, "B"', "street_number": "", "street": "", "city": "", "zip_code": ""}]
        self.assertEqual(from_csv(to_csv(rows)), rows)


class CommittedMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.existing = read_mapping()
        cls.records = map_resources(ROOT)["records"]
        cls.result = assign_ids(cls.records, cls.existing)

    def test_is_what_the_committed_data_produces_so_ids_do_not_change(self):
        self.assertEqual(to_csv(self.result["rows"]), to_csv(self.existing))
        self.assertEqual(self.result["added"], 0)
        self.assertEqual(self.result["retired"], 0)

    def test_has_one_active_id_per_row_and_no_duplicates(self):
        active = [r for r in self.existing if r["status"] == "active"]
        self.assertEqual(len(active), len(self.records))
        self.assertEqual(len({r["id"] for r in self.existing}), len(self.existing))


if __name__ == "__main__":
    unittest.main()
