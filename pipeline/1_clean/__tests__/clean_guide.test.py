# /// script
# requires-python = ">=3.10"
# dependencies = ["pandas"]
# ///
# Tests for pipeline/1_clean/clean_guide.py: the row-level rules on their own, and the whole stage on a
# small guide. No file I/O. Run:
#
#   uv run pipeline/1_clean/__tests__/clean_guide.test.py

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.dont_write_bytecode = True  # no __pycache__ next to the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clean_guide import borough, clean_resources, description_match, row_type, title  # noqa: E402

GUIDE_COLUMNS = ["Organization Name", "Street Number", "Address Line 2", "Street", "City", "State", "Zip Code",
                 "Phone Number", "Website", "Description", "Category", "Subcategory", "Spanish-speaking (Y/N)",
                 "Works w/ Currently Incarcerated/Pre-release (Y/N)", "ATI Program (Y/N)",
                 "Know Your Rights Content (Y/N)", "Notes"]


def guide(*rows):
    """A guide frame as load() would return it: text columns, blanks as NA."""
    frame = pd.DataFrame([dict.fromkeys(GUIDE_COLUMNS) | r for r in rows], columns=GUIDE_COLUMNS, dtype=str)
    return frame.where(frame.notna(), pd.NA)


def listing(r):
    """A row as row_type() sees it after clean(): the guide's columns plus the derived ones."""
    return pd.Series({"Phone Number": pd.NA, "Street": pd.NA, "Notes": pd.NA, "street": pd.NA, "latitude": pd.NA,
                      "borough": pd.NA, "org_name": "Org", "website": pd.NA, "Description": pd.NA} | r)


class Title(unittest.TestCase):
    def test_all_caps_becomes_title_case_with_acronyms_and_small_words(self):
        self.assertEqual(title("CENTER FOR COMMUNITY ALTERNATIVES (CCA)"), "Center for Community Alternatives (CCA)")
        self.assertEqual(title("NYC DEPARTMENT OF HOMELESS SERVICES"), "NYC Department of Homeless Services")

    def test_mixed_case_is_left_alone(self):
        self.assertEqual(title("Artistic Noise"), "Artistic Noise")
        self.assertEqual(title("The Fortune Society"), "The Fortune Society")


class Borough(unittest.TestCase):
    def test_zip_ranges(self):
        self.assertEqual(borough("10027"), "Manhattan")
        self.assertEqual(borough("11216"), "Brooklyn")
        self.assertEqual(borough("10457"), "Bronx")
        self.assertEqual(borough("11101"), "Queens")
        self.assertEqual(borough("10301"), "Staten Island")

    def test_outside_nyc_and_missing(self):
        self.assertIsNone(borough("07030"))
        self.assertIsNone(borough(pd.NA))


class RowType(unittest.TestCase):
    def test_street_in_a_borough_is_mapped(self):
        self.assertEqual(row_type(listing({"street": "1 Main St", "borough": "Brooklyn"})), "mapped")

    def test_street_outside_a_borough_is_outside_nyc(self):
        self.assertEqual(row_type(listing({"street": "1 Main St"})), "outside_nyc")

    def test_po_box_is_a_mailing_address(self):
        self.assertEqual(row_type(listing({"Street": "PO Box 12", "street": "PO Box 12"})), "mailing_address")

    def test_three_digit_number_or_hotline_name_is_a_hotline(self):
        self.assertEqual(row_type(listing({"Phone Number": "988"})), "hotline")
        self.assertEqual(row_type(listing({"org_name": "Crisis Helpline", "Phone Number": "212.555.0100"})), "hotline")

    def test_website_only_is_web_only(self):
        self.assertEqual(row_type(listing({"website": "https://example.org"})), "web_only")

    def test_see_full_listing_is_a_cross_reference(self):
        self.assertEqual(row_type(listing({"Description": "See the full listing on page 40."})), "cross_reference")


class DescriptionMatch(unittest.TestCase):
    def test_one_service_is_used(self):
        self.assertEqual(description_match("Free legal representation in housing court"), None)  # legal + housing
        self.assertEqual(description_match("Weekly food pantry"), "Food")

    def test_no_service_is_none(self):
        self.assertIsNone(description_match("Open Monday to Friday"))


class WholeStage(unittest.TestCase):
    def setUp(self):
        self.out = clean_resources(
            guide({"Organization Name": "BROOKLYN FOOD BANK", "Street Number": "1", "Street": "Main St",
                   "City": "Brooklyn", "State": "NY", "Zip Code": "12116", "Phone Number": "718.555.0100",
                   "Website": "example.org", "Description": "Weekly food pantry.", "Subcategory": "Food"},
                  {"Street Number": "2", "Street": "Side St", "City": "Brooklyn", "State": "NY", "Zip Code": "11216"},
                  {"Organization Name": "Helpline", "Phone Number": "988", "Description": "Call any time."},
                  {"Address Line 2": "Open 9-5"}),
            guide())

    def test_address_only_row_copies_the_row_above_and_extra_text_joins_it(self):
        out = self.out
        self.assertEqual(list(out["resource_id"]), [1, 2, 3])
        self.assertEqual(list(out["org_name"]), ["Brooklyn Food Bank", "Brooklyn Food Bank", "Helpline"])
        self.assertEqual(out.at[1, "street"], "2 Side St")
        self.assertIn("details copied from row above", out.at[1, "review_notes"])
        self.assertIn("Extra text: Open 9-5", out.at[2, "review_notes"])

    def test_cleaning_and_enrichment(self):
        row = self.out.iloc[0]
        self.assertEqual(row["zip"], "11216")                      # the known 12116 typo
        self.assertEqual(row["website"], "https://example.org")
        self.assertEqual(row["borough"], "Brooklyn")
        self.assertEqual(row["row_type"], "mapped")
        self.assertEqual(row["service_type"], "Food")
        self.assertEqual(row["service_type_source"], "guide_mapping")
        self.assertEqual(row["service_type_confidence"], "high")
        self.assertEqual(self.out.at[2, "row_type"], "hotline")
        self.assertTrue(self.out.at[2, "needs_review"])            # service_type to assign


if __name__ == "__main__":
    unittest.main()
