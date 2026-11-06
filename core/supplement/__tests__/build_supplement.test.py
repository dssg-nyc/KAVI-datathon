"""Tests for build_supplement.py. The output tests read the real data/supplement/supplement_all.csv
(build it first: python3 pipeline/supplement/build_supplement.py); the rest use small synthetic places.

    uv run pipeline/supplement/__tests__/build_supplement.test.py
"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ next to the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core.pipeline.supplement.build_supplement as b  # noqa: E402
import core.pipeline.supplement.match_nypl as m  # noqa: E402

OUT = b.OUT_CSV
LOCATION_COLS = ("address", "house_number", "street", "zip", "lat", "lon", "bin", "url")
BLANK_ROW = {c: "" for c in b.OUT_COLUMNS}


def read_out():
    with OUT.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def hidden_keys():
    keys = set()
    for r in m.read(m.SUPP_DIR / "endgbv.csv"):
        if m.is_hidden_location(r, json.loads(r.get("raw_json") or "{}")):
            keys.add(("endgbv", r["source_id"]))
    return keys


def place(src, sid, name, lat=None, lon=None, origin=None, phone="", website="", raw=None, **kw):
    row = {**BLANK_ROW, "source": src, "source_id": sid, "name": name, "lat": lat or "", "lon": lon or "",
           "phone": phone, "website": website, **kw}
    return {"key": (src, sid), "src": src, "row": row, "raw": raw or {}, "hidden": False, "tok": m.tokens(name),
            "org_tokens": [], "lat": lat, "lon": lon, "addr": None, "phones": m.phones(phone),
            "domains": m.domains(website), "origin": origin or src}


@unittest.skipUnless(OUT.exists(), "supplement_all.csv not built")
class RealOutput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = read_out()
        cls.hidden = hidden_keys()

    def test_one_row_per_place_and_unique_keys(self):
        expected = sum(len(m.read(m.SUPP_DIR / f"{s}.csv")) for s in b.SOURCES)
        self.assertEqual(len(self.rows), expected)
        keys = [(r["source"], r["source_id"]) for r in self.rows]
        self.assertEqual(len(keys), len(set(keys)))

    def test_columns_and_no_raw_json(self):
        self.assertEqual(list(self.rows[0]), b.OUT_COLUMNS)
        self.assertNotIn("raw_json", self.rows[0])
        self.assertTrue(all(r["licence"] for r in self.rows))

    def test_hidden_endgbv_rows_have_no_location_and_are_never_pending(self):
        self.assertTrue(self.hidden, "expected some display_physical_address=No rows")
        seen = 0
        for r in self.rows:
            if (r["source"], r["source_id"]) in self.hidden:
                seen += 1
                for c in LOCATION_COLS:
                    self.assertEqual(r[c], "", c)
                self.assertEqual(r["group_id"], "")
                self.assertEqual(r["corroborating_sources"], "")
                self.assertEqual(r["hitl_review"], "")
        self.assertEqual(seen, len(self.hidden))

    def test_hidden_rows_never_share_a_group(self):
        groups = {r["group_id"] for r in self.rows if (r["source"], r["source_id"]) in self.hidden}
        self.assertEqual(groups, {""})

    def test_match_files_carry_no_location_for_hidden_rows(self):
        for r in m.read(m.SUPP_DIR / "matches_endgbv.csv"):
            if ("endgbv", r["source_id"]) in self.hidden:
                for c in ("distance_m", "address_match", "bin_match", "match_url", "nearest_feature_m", "nearest_feature"):
                    self.assertEqual(r[c], "", c)
        # coverage and parent-org files hold no place coordinates at all
        for path in m.SUPP_DIR.glob("coverage_endgbv.csv"):
            for r in m.read(path):
                self.assertFalse({"lat", "lon", "address", "bin"} & set(r))

    def test_pending_rules(self):
        for r in self.rows:
            if r["hitl_review"] == "pending":
                self.assertGreaterEqual(float(r["relevance_score"]), b.REVIEW_THRESHOLD)
                self.assertNotIn(r["best_match_class"], b.SITE)
            elif float(r["relevance_score"]) >= b.REVIEW_THRESHOLD and r["best_match_class"] not in b.SITE:
                self.assertTrue(r["hitl_review"] or (r["source"], r["source_id"]) in self.hidden
                                or r["group_id"], "above threshold but not pending")

    def test_score_is_sum_of_signals_without_org_tie(self):
        for r in self.rows[:: max(1, len(self.rows) // 5000)]:
            want = sum(b.WEIGHTS[k] * float(r[f"signal_{k}"]) for k in b.WEIGHTS)
            self.assertAlmostEqual(float(r["relevance_score"]), want, places=2)
            tie = b.ORG_TIE_WEIGHT if r["signal_guide_org_tie"] == "1" else 0
            self.assertAlmostEqual(float(r["relevance_score_with_org_tie"]), want + tie, places=2)

    def test_borough_not_a_feature(self):
        self.assertNotIn("borough", b.WEIGHTS)


class Scoring(unittest.TestCase):
    def test_score_ignores_guide_match(self):
        p = place("osm", "1", "Food Pantry", 40.7, -74.0, phone="212-555-0100")
        p["row"]["primary_type"] = "amenity=food_bank"
        a = b.score_place(p, set())
        self.assertEqual(a, b.score_place({**p, "key": ("osm", "2")}, set()))

    def test_build_rows_score_independent_of_matches(self):
        places = [place("osm", "1", "Food Pantry", 40.7, -74.0)]
        for p in places:
            p["row"]["last_edit"] = "2025-01-01"
        kw = dict(nypl_rows=[], aliases={}, previous={})
        with_match = b.build_rows(places, {("osm", "1"): ("same_site", ["5"])}, **kw)
        without = b.build_rows(places, {}, **kw)
        self.assertEqual(with_match[0]["relevance_score"], without[0]["relevance_score"])
        self.assertEqual(with_match[0]["hitl_review"], "")  # already in the guide: never pending
        self.assertEqual(with_match[0]["best_match_class"], "same_site")


class Linking(unittest.TestCase):
    def test_facdb_copy_is_not_independent(self):
        omh = place("omh", "1", "Bronx Mental Health Clinic", 40.8, -73.9)
        copy = place("facdb", "9", "Bronx Mental Health Clinic", 40.8, -73.9, origin="omh")
        links, corro = b.link_places([omh, copy])
        self.assertTrue(links)  # they are the same place and share a group
        self.assertFalse(corro)  # but neither corroborates the other

    def test_independent_sources_corroborate(self):
        osm = place("osm", "1", "Bronx Mental Health Clinic", 40.8, -73.9)
        omh = place("omh", "1", "Bronx Mental Health Clinic", 40.8, -73.9)
        _, corro = b.link_places([osm, omh])
        self.assertEqual(corro[0], {"omh"})
        self.assertEqual(corro[1], {"osm"})

    def test_nearby_unrelated_names_are_not_linked(self):
        a = place("osm", "1", "Joes Pizza", 40.8, -73.9)
        c = place("omh", "1", "Bronx Mental Health Clinic", 40.8, -73.9)
        links, corro = b.link_places([a, c])
        self.assertFalse(links)
        self.assertFalse(corro)

    def test_same_bin_alone_is_not_a_link(self):
        a = place("osm", "1", "Joes Pizza", None, None, bin="1001")
        c = place("omh", "1", "Bronx Mental Health Clinic", None, None, bin="1001")
        a["row"]["bin"] = c["row"]["bin"] = "1001"
        links, _ = b.link_places([a, c])
        self.assertFalse(links)

    def test_hidden_and_irs_rows_never_link(self):
        a = place("endgbv", "1", "Safe Horizon Legal", 40.8, -73.9)
        a["hidden"] = True
        c = place("omh", "1", "Safe Horizon Legal", 40.8, -73.9)
        irs = place("irs_eo", "1", "Safe Horizon Legal", 40.8, -73.9)
        links, _ = b.link_places([a, c, irs])
        self.assertFalse(links)


class Verdicts(unittest.TestCase):
    def test_verdicts_survive_rebuild_and_pending_does_not(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "out.csv"
            rows = [{c: "" for c in b.OUT_COLUMNS} for _ in range(3)]
            for i, (r, v) in enumerate(zip(rows, ("accepted", "pending", ""))):
                r.update({"source": "osm", "source_id": str(i), "hitl_review": v})
            b.write_rows(rows, path)
            self.assertEqual(b.read_verdicts(path), {("osm", "0"): "accepted"})
            self.assertEqual(b.read_verdicts(Path(d) / "missing.csv"), {})

    def test_verdict_kept_on_rebuild_even_below_threshold(self):
        p = place("osm", "1", "Joes Pizza", 40.8, -73.9)
        rows = b.build_rows([p], {}, [], {}, previous={("osm", "1"): "rejected"})
        self.assertEqual(rows[0]["hitl_review"], "rejected")


class Signals(unittest.TestCase):
    def test_name_keywords_and_school_exclusion(self):
        self.assertTrue(b.name_keywords("Neighborhood Food Pantry")[1])
        self.assertFalse(b.name_keywords("Joes Pizza")[1])
        self.assertNotIn("Education", b.name_keywords("Bronx High School for Science")[0])

    def test_threshold_is_one_constant_in_options(self):
        self.assertIn(b.REVIEW_THRESHOLD, b.THRESHOLD_OPTIONS)

    def test_auc(self):
        self.assertEqual(b.auc([3, 2, 1, 0], [1, 1, 0, 0]), 1.0)
        self.assertEqual(b.auc([0, 1, 2, 3], [1, 1, 0, 0]), 0.0)
        self.assertEqual(b.auc([1, 1, 1, 1], [1, 0, 1, 0]), 0.5)


if __name__ == "__main__":
    unittest.main()
