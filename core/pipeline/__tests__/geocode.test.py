# Tests for core/pipeline/geocode.py. Run from the repo root:  uv run core/pipeline/__tests__/geocode.test.py
# Nothing here touches the network: GeoSearch and Census are replaced by fakes, and the committed
# GeoJSON is rebuilt from the CSV and the results it records.
import json
import sys
import threading
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ next to the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import geocode as g  # noqa: E402
from map_resources import read_text  # noqa: E402

TROY = [{"street": "1 Main St", "city": "Troy", "state": "NY", "zip": "12180"}]
MATCH = '"0","a","Match","Exact","a","-73.9,40.7","1","L"'


def record(**fields):
    """A full NYPL CSV row with every column blank unless overridden."""
    base = {
        "Organization Name": "", "Street Number": "", "Address Line 2": "", "Street": "", "City": "",
        "State": "", "Zip Code": "", "Phone Number": "", "Website": "", "Description": "", "Category": "",
        "Subcategory": "", "Spanish-speaking (Y/N)": "", "Works w/ Currently Incarcerated/Pre-release (Y/N)": "",
        "ATI Program (Y/N)": "", "Know Your Rights Content (Y/N)": "", "Notes": "",
    }
    return {**base, **fields}


class ParseCsv(unittest.TestCase):
    def test_splits_a_simple_grid(self):
        self.assertEqual(g.parse_csv("a,b,c\n1,2,3\n"), [["a", "b", "c"], ["1", "2", "3"]])

    # The NYPL CSV has ~39 rows like "C/O Family of Woodstock, Inc." in Address Line 2.
    def test_keeps_commas_inside_quoted_fields(self):
        self.assertEqual(g.parse_csv('name,note\nAcme,"C/O Smith, Inc."\n'), [["name", "note"], ["Acme", "C/O Smith, Inc."]])

    def test_unescapes_doubled_quotes(self):
        self.assertEqual(g.parse_csv('a\n"she said ""hi"""\n'), [["a"], ['she said "hi"']])

    def test_keeps_newlines_inside_quoted_fields(self):
        self.assertEqual(g.parse_csv('a,b\n1,"line one\nline two"\n'), [["a", "b"], ["1", "line one\nline two"]])

    def test_drops_blank_lines(self):
        self.assertEqual(g.parse_csv("a,b\n1,2\n\n3,4\n"), [["a", "b"], ["1", "2"], ["3", "4"]])

    def test_handles_crlf_line_endings(self):
        self.assertEqual(g.parse_csv("a,b\r\n1,2\r\n"), [["a", "b"], ["1", "2"]])


class CsvCell(unittest.TestCase):
    def test_quotes_only_where_needed(self):
        self.assertEqual(g.csv_cell("Kingston"), "Kingston")
        self.assertEqual(g.csv_cell("Kingston, NY"), '"Kingston, NY"')
        self.assertEqual(g.csv_cell('12 "Main" St'), '"12 ""Main"" St"')


class IsGeocodable(unittest.TestCase):
    def test_needs_a_street_plus_a_city_or_zip(self):
        self.assertTrue(g.is_geocodable(record(Street="Albany Avenue", City="Kingston")))
        self.assertTrue(g.is_geocodable(record(Street="Albany Avenue", **{"Zip Code": "12401"})))
        self.assertFalse(g.is_geocodable(record(Street="Albany Avenue")))

    # ~291 rows are hotlines or online-only resources with no address at all.
    def test_rejects_a_row_with_no_street(self):
        self.assertFalse(g.is_geocodable(record(City="Kingston", **{"Zip Code": "12401"})))
        self.assertFalse(g.is_geocodable(record()))


class CleanZip(unittest.TestCase):
    def test_fixes_the_two_known_zip_typos(self):
        r = g.clean_zip(record(**{"Organization Name": "THE BEDFORD-STUYVESANT FAMILY HEALTH CENTER - 4 (Wellness Center Program)", "Zip Code": "12116"}))
        self.assertEqual(r["Zip Code"], "11216")
        r = g.clean_zip(record(**{"Organization Name": "CENTER FOR JUSTICE INNOVATION (CJI)—THE STATEN ISLAND JUSTICE CENTER", "Zip Code": "10304"}))
        self.assertEqual(r["Zip Code"], "10301")

    def test_leaves_every_other_row_untouched(self):
        self.assertEqual(g.clean_zip(record(**{"Organization Name": "SOME OTHER ORG", "Zip Code": "10304"}))["Zip Code"], "10304")


class Census(unittest.TestCase):
    def test_batch_csv_pairs_each_id_with_its_address_quoting_where_needed(self):
        csv = g.build_batch_csv([5, 9], [
            {"street": "31 Albany Avenue", "city": "Kingston", "state": "NY", "zip": "12401"},
            {"street": "1 Main St", "city": "Troy, Rensselaer", "state": "NY", "zip": "12180"},
        ])
        self.assertEqual(csv, '5,31 Albany Avenue,Kingston,NY,12401\n9,1 Main St,"Troy, Rensselaer",NY,12180')

    def test_reads_coordinates_and_the_matched_address_out_of_a_matched_row(self):
        csv = '"1","350 Fifth Avenue, New York, NY, 10118","Match","Exact","350 5TH AVE, NEW YORK, NY, 10118","-73.985075577551,40.747850846857","59653473","L"'
        self.assertEqual(g.parse_geocode_response(csv)[1], {"matched": True, "lon": -73.985075577551, "lat": 40.747850846857, "matched_address": "350 5TH AVE, NEW YORK, NY, 10118"})

    def test_marks_a_no_match_row_as_unmatched(self):
        self.assertEqual(g.parse_geocode_response('"2","1 Police Plaza, New York, NY, 10038","No_Match"')[2], {"matched": False})

    def test_handles_multiple_rows(self):
        results = g.parse_geocode_response('"1","a","Match","Exact","a","-1,2","id","L"\n"2","b","No_Match"')
        self.assertEqual(len(results), 2)
        self.assertTrue(results[1]["matched"])
        self.assertEqual(results[1]["lon"], -1)
        self.assertFalse(results[2]["matched"])

    def test_posts_the_batch_as_multipart_form_data_and_parses_the_response(self):
        seen = {}

        def post(body, content_type):
            seen["body"], seen["type"] = body.decode(), content_type
            return 200, MATCH

        results = g.geocode([0], TROY, post=post)
        self.assertTrue(results[0]["matched"])
        self.assertTrue(seen["type"].startswith("multipart/form-data; boundary="))
        self.assertIn('name="benchmark"\r\n\r\nPublic_AR_Current\r\n', seen["body"])
        self.assertIn('name="addressFile"; filename="addresses.csv"', seen["body"])
        self.assertIn("0,1 Main St,Troy,NY,12180", seen["body"])

    def test_retries_on_a_busy_response_and_succeeds_once_the_server_recovers(self):
        calls, waits = [], []

        def post(body, content_type):
            calls.append(1)
            return (503, "busy") if len(calls) == 1 else (200, MATCH)

        results = g.geocode([0], TROY, post=post, sleep=waits.append)
        self.assertEqual(len(calls), 2)
        self.assertEqual(waits, [10])
        self.assertTrue(results[0]["matched"])

    def test_gives_up_after_four_busy_responses(self):
        calls = []

        def post(body, content_type):
            calls.append(1)
            return 503, "busy"

        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            g.geocode([0], TROY, post=post, sleep=lambda s: None)
        self.assertEqual(len(calls), 4)

    def test_throws_with_the_status_and_body_on_a_non_retryable_error(self):
        with self.assertRaisesRegex(RuntimeError, "HTTP 400.*bad request"):
            g.geocode([0], TROY, post=lambda body, content_type: (400, "bad request"), sleep=lambda s: None)


class ToFeature(unittest.TestCase):
    def test_builds_addr_tags_from_the_present_address_columns(self):
        f = g.to_feature(
            record(**{"Street Number": "31", "Street": "Albany Avenue", "City": "Kingston", "State": "NY", "Zip Code": "12401"}),
            {"matched": True, "lon": -74.0, "lat": 41.9, "source": "census"},
        )
        p = f["properties"]
        self.assertEqual([p["addr:housenumber"], p["addr:street"], p["addr:city"], p["addr:state"], p["addr:postcode"], p["addr:country"]],
                         ["31", "Albany Avenue", "Kingston", "NY", "12401", "US"])
        self.assertEqual(p["geocode_match"], "matched")
        self.assertEqual(p["geocode_source"], "census")
        self.assertEqual(f["geometry"], {"type": "Point", "coordinates": [-74.0, 41.9]})

    def test_carries_the_matched_address_and_review_note(self):
        f = g.to_feature(record(Street="Suffolk Street"), {"matched": True, "lon": -73.98, "lat": 40.71, "source": "census",
                                                           "matched_address": "45 SUFFOLK ST, NEW YORK, NY, 10002", "review": "Confirm the address."})
        self.assertEqual(f["properties"]["geocode_matched_address"], "45 SUFFOLK ST, NEW YORK, NY, 10002")
        self.assertEqual(f["properties"]["geocode_review"], "Confirm the address.")

    def test_omits_addr_tags_for_a_row_with_no_address_fields(self):
        f = g.to_feature(record(), None)
        self.assertFalse([k for k in f["properties"] if k.startswith("addr:")])
        self.assertEqual(f["properties"]["geocode_match"], "not_attempted")
        self.assertEqual(f["properties"]["geocode_source"], "")
        self.assertIsNone(f["geometry"])

    def test_marks_an_address_that_failed_to_geocode_as_unmatched(self):
        f = g.to_feature(record(Street="Box 188", City="Yaphank"), {"matched": False})
        self.assertEqual(f["properties"]["geocode_match"], "unmatched")
        self.assertIsNone(f["geometry"])

    def test_keeps_every_original_column_unchanged(self):
        f = g.to_feature(record(**{"Organization Name": "Acme", "Notes": "see page 12"}), None)
        self.assertEqual(f["properties"]["Organization Name"], "Acme")
        self.assertEqual(f["properties"]["Notes"], "see page 12")


class PickGeoSearchMatch(unittest.TestCase):
    def test_returns_coordinates_when_the_postalcode_matches(self):
        match = g.pick_geosearch_match([{"geometry": {"coordinates": [-74.003463, 40.713036]}, "properties": {"postalcode": "10007", "housenumber": "1", "label": "1 CENTER STREET, New York, NY, USA"}}], "10007", "1")
        self.assertEqual(match, {"lon": -74.003463, "lat": 40.713036, "house_number_matches": True, "label": "1 CENTER STREET, New York, NY, USA"})

    # Asking GeoSearch about a Kingston, NY address gets back a Brooklyn street with zip 11213.
    def test_rejects_a_fallback_match_whose_zip_differs(self):
        self.assertIsNone(g.pick_geosearch_match([{"geometry": {"coordinates": [-73.93931, 40.675917]}, "properties": {"postalcode": "11213"}}], "12401"))

    def test_rejects_when_there_is_no_zip_to_validate_against(self):
        self.assertIsNone(g.pick_geosearch_match([{"geometry": {"coordinates": [-74, 40.7]}, "properties": {"postalcode": "10007"}}], ""))

    def test_compares_only_the_first_5_digits(self):
        match = g.pick_geosearch_match([{"geometry": {"coordinates": [-74, 40.7]}, "properties": {"postalcode": "10007-1234", "housenumber": "1"}}], "10007", "1")
        self.assertEqual(match, {"lon": -74, "lat": 40.7, "house_number_matches": True, "label": ""})

    def test_returns_none_when_nothing_matches(self):
        self.assertIsNone(g.pick_geosearch_match([], "10007"))

    # "581 Rogers Avenue" came back as 1038 Rogers Avenue, 1.4 km away.
    def test_flags_a_same_zip_result_with_a_different_house_number(self):
        match = g.pick_geosearch_match([{"geometry": {"coordinates": [-73.95, 40.64]}, "properties": {"postalcode": "11226", "housenumber": "1038", "label": "1038 ROGERS AVENUE, Brooklyn, NY, USA"}}], "11226", "581")
        self.assertFalse(match["house_number_matches"])
        self.assertEqual(match["label"], "1038 ROGERS AVENUE, Brooklyn, NY, USA")


class HouseNumbersMatch(unittest.TestCase):
    def test_matches_identical_numbers_including_queens_style(self):
        self.assertTrue(g.house_numbers_match("581", "581"))
        self.assertTrue(g.house_numbers_match("29-76", "29-76"))

    def test_rejects_a_different_building_on_the_same_street(self):
        self.assertFalse(g.house_numbers_match("581", "1038"))
        self.assertFalse(g.house_numbers_match("180", "80"))
        self.assertFalse(g.house_numbers_match("16-16", "16-00"))

    def test_ignores_letter_suffixes(self):
        self.assertTrue(g.house_numbers_match("76-A", "76"))
        self.assertTrue(g.house_numbers_match("150D", "150"))
        self.assertTrue(g.house_numbers_match("201A", "201"))

    # The source CSV writes some ranges with an en dash ("3807–3809 Church Avenue").
    def test_accepts_either_end_of_a_range(self):
        self.assertTrue(g.house_numbers_match("400-430", "400"))
        self.assertTrue(g.house_numbers_match("104-106", "106"))
        self.assertTrue(g.house_numbers_match("3807–3809", "3807"))
        self.assertFalse(g.house_numbers_match("3807–3809", "3419"))

    def test_never_matches_when_either_side_is_blank(self):
        self.assertFalse(g.house_numbers_match("", "1"))
        self.assertFalse(g.house_numbers_match("1", ""))


class GeocodeWithGeoSearch(unittest.TestCase):
    def test_records_a_validated_match_with_its_source_and_address(self):
        def get(text):
            return {"features": [{"geometry": {"coordinates": [-74.003463, 40.713036]}, "properties": {"postalcode": "10007", "housenumber": "1", "label": "1 CENTER STREET, New York, NY, USA"}}]}

        results = g.geocode_with_geosearch([{"id": 0, "house_number": "1", "street": "1 Centre St", "city": "New York", "state": "NY", "zip": "10007"}], get)
        self.assertEqual(results[0], {"matched": True, "lon": -74.003463, "lat": 40.713036, "source": "geosearch", "matched_address": "1 CENTER STREET, New York, NY, USA"})

    def test_keeps_a_wrong_house_number_result_as_unmatched_with_its_point(self):
        def get(text):
            return {"features": [{"geometry": {"coordinates": [-73.95, 40.64]}, "properties": {"postalcode": "11226", "housenumber": "1038", "label": "1038 ROGERS AVENUE, Brooklyn, NY, USA"}}]}

        results = g.geocode_with_geosearch([{"id": 0, "house_number": "581", "street": "581 Rogers Avenue", "city": "Brooklyn", "state": "NY", "zip": "11226"}], get)
        self.assertFalse(results[0]["matched"])
        self.assertEqual(results[0]["matched_address"], "1038 ROGERS AVENUE, Brooklyn, NY, USA")

    def test_leaves_no_entry_when_the_result_fails_zip_validation(self):
        def get(text):
            return {"features": [{"geometry": {"coordinates": [-73.93931, 40.675917]}, "properties": {"postalcode": "11213"}}]}

        self.assertEqual(g.geocode_with_geosearch([{"id": 0, "street": "31 Albany Avenue", "city": "Kingston", "state": "NY", "zip": "12401"}], get), {})

    def test_treats_a_failed_request_as_unresolved(self):
        def get(text):
            raise OSError("network down")

        self.assertEqual(g.geocode_with_geosearch([{"id": 0, "street": "1 Centre St", "city": "New York", "state": "NY", "zip": "10007"}], get), {})

    def test_never_runs_more_than_the_concurrency_limit(self):
        lock, state = threading.Lock(), {"now": 0, "max": 0}

        def get(text):
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.01)
            with lock:
                state["now"] -= 1
            return None

        rows = [{"id": i, "street": "x", "city": "", "state": "", "zip": ""} for i in range(20)]
        g.geocode_with_geosearch(rows, get)
        self.assertLessEqual(state["max"], g.GEOSEARCH_CONCURRENCY)


class MergeResults(unittest.TestCase):
    records = [record(**{"Organization Name": "A", "Street Number": "581"}), record(**{"Organization Name": "Chinese-American Planning Council"})]

    def test_geosearch_first_then_census_then_the_same_street_point_with_a_note(self):
        near = {"matched": False, "lon": -73.95, "lat": 40.64, "source": "geosearch", "matched_address": "1038 ROGERS AVENUE"}
        results = g.merge_results(self.records, {0: near}, {0: {"matched": False}})
        self.assertTrue(results[0]["matched"])
        self.assertEqual(results[0]["source"], "geosearch")
        self.assertIn("not house number 581", results[0]["review"])

    def test_census_results_are_labelled_and_review_notes_apply(self):
        results = g.merge_results(self.records, {}, {1: {"matched": True, "lon": -73.98, "lat": 40.71, "matched_address": "45 SUFFOLK ST"}})
        self.assertEqual(results[1]["source"], "census")
        self.assertEqual(results[1]["review"], g.REVIEW_NOTES["Chinese-American Planning Council"])


class CommittedGeoJson(unittest.TestCase):
    def test_is_what_the_csv_and_its_recorded_results_produce(self):
        committed = read_text(g.OUTPUT)
        features = json.loads(committed)["features"]
        records = g.read_records()
        self.assertEqual(len(features), len(records))
        results = {}
        for i, f in enumerate(features):
            p = f["properties"]
            if p["geocode_match"] == "unmatched":
                results[i] = {"matched": False}
            elif p["geocode_match"] == "matched":
                lon, lat = f["geometry"]["coordinates"]
                results[i] = {"matched": True, "lon": lon, "lat": lat, "source": p["geocode_source"],
                              "matched_address": p["geocode_matched_address"], "review": p["geocode_review"]}
        self.assertEqual(sorted(results), [row["id"] for row in g.address_rows(records)])
        self.assertEqual(g.feature_collection(records, results), committed)


if __name__ == "__main__":
    unittest.main()
