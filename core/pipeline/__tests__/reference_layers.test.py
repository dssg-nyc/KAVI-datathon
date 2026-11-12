# Tests for core/pipeline/reference_layers.py. Run from the repo root:  uv run core/pipeline/__tests__/reference_layers.test.py
# Nothing here touches the network: the conversion is tested on sample ArcGIS rows and a fake server,
# and the committed files in data/public/layers/ are checked against each other.
import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ next to the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reference_layers as rl  # noqa: E402
from map_resources import read_text  # noqa: E402

NYC = [-73.95, 40.75]


def layer(key):
    return next(item for item in rl.LAYERS if item.key == key)


class TitleCase(unittest.TestCase):
    def test_lowercases_the_shouting_and_capitalizes_each_word(self):
        self.assertEqual(rl.title_case("GREENPOINT LIBRARY"), "Greenpoint Library")
        self.assertEqual(rl.title_case("ST. JOHN-RIVERSIDE (ANNEX)"), "St. John-Riverside (Annex)")
        self.assertEqual(rl.title_case("163-18 JAMAICA AVENUE"), "163-18 Jamaica Avenue")

    def test_is_blank_for_none(self):
        self.assertEqual(rl.title_case(None), "")


class ToFeature(unittest.TestCase):
    def test_a_library_keeps_its_name_address_and_system(self):
        f = layer("libraries").to_feature({"FACNAME": "GREENPOINT LIBRARY", "ADDRESS": "107 NORMAN AVENUE", "CITY": "BROOKLYN", "ZIPCODE": "11222", "OPNAME": "BPL"}, NYC)
        self.assertEqual(f, {"type": "Feature", "geometry": {"type": "Point", "coordinates": NYC}, "properties": {"name": "Greenpoint Library", "address": "107 Norman Avenue, Brooklyn 11222", "kind": "BPL"}})

    def test_a_library_without_an_address_has_address_none(self):
        f = layer("libraries").to_feature({"FACNAME": "A", "ADDRESS": None, "CITY": None, "ZIPCODE": None, "OPNAME": None}, NYC)
        self.assertEqual(f["properties"], {"name": "A", "address": None, "kind": None})

    def test_a_health_facility_uses_its_facility_type_as_kind(self):
        f = layer("health_facilities").to_feature({"FACNAME": "JOBNET", "ADDRESS": "163-18 JAMAICA AVENUE", "CITY": "JAMAICA", "ZIPCODE": "11432", "FACTYPE": "SUPPORT MENTAL HEALTH"}, NYC)
        self.assertEqual(f["properties"], {"name": "Jobnet", "address": "163-18 Jamaica Avenue, Jamaica 11432", "kind": "Support Mental Health"})

    def test_a_cooling_site_names_the_park_and_feature_with_borough_and_status(self):
        f = layer("cooling_sites").to_feature({"PropertyName": "Prospect Park", "SubPropertyName": "Vanderbilt Playground", "Borough": "Brooklyn", "FeatureType": "Spray Shower", "Status": "Activated"}, NYC)
        self.assertEqual(f["properties"], {"name": "Prospect Park: Vanderbilt Playground", "address": "Brooklyn", "kind": "Spray Shower", "status": "Activated"})
        bare = layer("cooling_sites").to_feature({"PropertyName": "Prospect Park", "SubPropertyName": None, "Borough": None, "FeatureType": None, "Status": None}, NYC)
        self.assertEqual(bare["properties"], {"name": "Prospect Park", "address": None, "kind": None, "status": None})


class FetchLayer(unittest.TestCase):
    def test_pages_until_the_service_stops_and_skips_unnamed_or_non_point_features(self):
        def feature(name):
            return {"geometry": {"type": "Point", "coordinates": NYC}, "properties": {"FACNAME": name}}

        pages = [
            {"features": [feature("A"), feature(None), {"geometry": None, "properties": {"FACNAME": "B"}}], "exceededTransferLimit": True},
            {"features": [feature("C")]},
        ]
        urls = []

        def get_json(url):
            urls.append(url)
            return pages[len(urls) - 1]

        features = rl.fetch_layer(layer("libraries"), get_json)
        self.assertEqual([f["properties"]["name"] for f in features], ["A", "C"])
        self.assertIn("resultOffset=0&", urls[0])
        self.assertIn("resultOffset=3&", urls[1])

    def test_an_error_from_the_service_is_raised(self):
        with self.assertRaisesRegex(RuntimeError, "Invalid query"):
            rl.fetch_layer(layer("libraries"), lambda url: {"error": {"message": "Invalid query"}})


class ToGeoJson(unittest.TestCase):
    def test_writes_a_feature_collection_with_one_feature_per_line(self):
        f = layer("libraries").to_feature({"FACNAME": "A"}, NYC)
        text = rl.to_geojson([f, f])
        self.assertEqual(json.loads(text), {"type": "FeatureCollection", "features": [f, f]})
        self.assertEqual(len(text.split("\n")), 5)


class IndexJson(unittest.TestCase):
    def test_lists_every_layer_with_its_file_count_and_the_date_it_changed(self):
        counts = {item.key: 1 for item in rl.LAYERS}
        changed = {item.key: True for item in rl.LAYERS}
        entries = json.loads(rl.index_json(counts, changed, date(2026, 1, 2)))
        self.assertEqual([e["key"] for e in entries], [item.key for item in rl.LAYERS])
        for e in entries:
            self.assertEqual(e["file"], f"data/public/layers/{e['key']}.geojson")
            self.assertEqual(e["count"], 1)
            self.assertEqual(e["fetched"], "2026-01-02")
            self.assertTrue(e["label"] and e["note"] and e["color"] and e["source"], e["key"])

    def test_keeps_the_committed_date_for_a_layer_that_did_not_change(self):
        committed = json.loads(read_text(rl.INDEX_PATH))
        counts = {e["key"]: e["count"] for e in committed}
        text = rl.index_json(counts, {key: False for key in counts}, date(2030, 1, 1))
        self.assertEqual(text, read_text(rl.INDEX_PATH))


class CommittedFiles(unittest.TestCase):
    def test_the_index_matches_the_geojson_files_which_hold_named_points_in_nyc(self):
        entries = json.loads(read_text(rl.INDEX_PATH))
        self.assertEqual([e["key"] for e in entries], [item.key for item in rl.LAYERS])
        for item in rl.LAYERS:
            text = read_text(rl.layer_path(item))
            features = json.loads(text)["features"]
            entry = next(e for e in entries if e["key"] == item.key)
            self.assertEqual(len(features), entry["count"], item.key)
            self.assertGreater(len(features), 100, item.key)
            self.assertEqual(rl.to_geojson(features), text, f"{item.key}: written in another format")
            for f in features:
                self.assertEqual(f["geometry"]["type"], "Point")
                lon, lat = f["geometry"]["coordinates"]
                self.assertTrue(-74.3 < lon < -73.6 and 40.4 < lat < 41, f"{item.key}: {f['properties']['name']} at {lon}, {lat}")
                self.assertTrue(f["properties"]["name"], item.key)


if __name__ == "__main__":
    unittest.main()
