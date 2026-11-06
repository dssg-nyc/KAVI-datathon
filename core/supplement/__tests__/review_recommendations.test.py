"""Tests for review_recommendations.py, on small synthetic rows plus checks of the real queue files when present.

    uv run pipeline/supplement/__tests__/review_recommendations.test.py
"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ next to the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core.pipeline.supplement.build_supplement as b  # noqa: E402
import core.pipeline.supplement.match_nypl as m  # noqa: E402
import core.pipeline.supplement.review_recommendations as r  # noqa: E402

GUIDE = [{"id": "g1", "row_type": "mapped", "latitude": "40.7000", "longitude": "-74.0000", "service_types_all": '{Food}', "borough": "Brooklyn"},
         {"id": "g2", "row_type": "web_only", "latitude": "", "longitude": "", "service_types_all": '{Housing}', "borough": ""}]
NEAR, FAR = ("40.7010", "-74.0000"), ("40.8000", "-74.0000")


def place(sid, at=FAR, source="osm", score="6.5", review="pending", types="Food", group="", name="Place", corro="", ptype="amenity=social_facility", address="1 Main St"):
    return {"source": source, "source_id": sid, "name": name, "borough": "Brooklyn", "lat": at[0], "lon": at[1], "address": address,
            "phone": "", "website": "", "url": "", "licence": "x", "group_id": group, "corroborating_sources": corro,
            "proposed_service_types": types, "relevance_score": score, "relevance_signals": "", "hitl_review": review, "primary_type": ptype}


class Priority(unittest.TestCase):
    def one(self, *args, **kw):
        return r.recommendations([place("a", *args, **kw)], GUIDE)[0]

    def test_no_guide_site_in_range(self):
        self.assertEqual(self.one(FAR)["priority"], "1_no_guide_site_nearby")

    def test_guide_site_near_with_another_service(self):
        rec = self.one(NEAR, types="Housing")
        self.assertEqual((rec["priority"], rec["service_gaps"]), ("2_service_missing_nearby", "Housing"))

    def test_service_already_in_range(self):
        self.assertEqual(self.one(NEAR)["priority"], "3_already_covered")

    def test_unmapped_guide_rows_do_not_count_as_sites(self):
        every, by_type, _ = r.guide_sites(GUIDE)
        self.assertEqual(len(every), 1)
        self.assertNotIn("Housing", by_type)


class Collapse(unittest.TestCase):
    def test_group_is_one_row_shown_from_a_republishable_source(self):
        rows = [place("n", source="dycd", score="8.0", group="g"), place("o", source="omh", score="6.0", group="g", types="Housing")]
        recs = r.recommendations(rows, GUIDE)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["source"], "omh")
        self.assertEqual(recs[0]["member_keys"], "dycd:n|omh:o")
        self.assertEqual(recs[0]["proposed_service_types"], "Food; Housing")

    def test_one_name_at_one_address_is_one_row(self):
        recs = r.recommendations([place("a", name="New Horizon Inc", address="116-10 Myrtle Avenue"),
                                  place("b", name="New Horizon Inc.", address="116-10 Myrtle Ave")], GUIDE)
        self.assertEqual((len(recs), recs[0]["listings"], recs[0]["member_keys"]), (1, 2, "osm:a|osm:b"))

    def test_same_name_at_another_address_stays_separate(self):
        recs = r.recommendations([place("a", name="New Horizon Inc", address="116-10 Myrtle Avenue"),
                                  place("b", name="New Horizon Inc", address="115-02 Ocean Promenade")], GUIDE)
        self.assertEqual(len(recs), 2)

    def test_listings_with_no_address_never_merge(self):
        recs = r.recommendations([place("a", name="Same Name", address=""), place("b", name="Same Name", address="")], GUIDE)
        self.assertEqual(len(recs), 2)

    def test_rows_with_no_review_status_stay_out(self):
        self.assertEqual(r.recommendations([place("a", review="")], GUIDE), [])

    def test_blank_coordinates_do_not_crash(self):
        self.assertEqual(r.recommendations([place("a", at=("", ""))], GUIDE)[0]["priority"], "4_no_location")


class Split(unittest.TestCase):
    def sides(self, *rows, raws=None):
        return r.split_queue(r.recommendations(list(rows), GUIDE, raws=raws))

    def test_nyc_terms_source_stays_local(self):
        public, local = self.sides(place("a", source="dycd"))
        self.assertEqual((len(public), len(local)), (0, 1))

    def test_endgbv_corroboration_keeps_a_place_local(self):
        public, local = self.sides(place("a", corro="endgbv"))
        self.assertEqual((len(public), len(local)), (0, 1))

    def test_survivor_service_by_osm_tag_or_name_stays_local(self):
        self.assertFalse(self.sides(place("a"), raws={"osm:a": {"social_facility:for": "senior;abused"}})[0])
        self.assertFalse(self.sides(place("a", name="Domestic Violence Project"))[0])

    def test_health_centre_inside_a_shelter_stays_local(self):
        for name in ("Barbara Kleinman Shelter", "Jackson Avenue Family Residence", "Kingsboro Men's MICA Shelter"):
            public, local = self.sides(place("a", source="hrsa", name=name))
            self.assertEqual((len(public), local[0]["local_reason"]), (0, "sensitive"), name)

    def test_private_practice_stays_local(self):
        public, local = self.sides(place("a", ptype="healthcare=psychotherapist", name="Some Therapy"))
        self.assertEqual((len(public), local[0]["local_reason"]), (0, "private_practice"))

    def test_practice_tag_on_a_place_another_list_has_is_committable(self):
        public, local = self.sides(place("a", ptype="healthcare=counselling", corro="omh"))
        self.assertEqual((len(public), len(local)), (1, 0))

    def test_psychiatric_hospital_is_not_a_private_practice(self):
        public, _ = self.sides(place("a", ptype="amenity=hospital", name="Creedmoor Psychiatric Center"))
        self.assertEqual(len(public), 1)

    def test_ordinary_osm_place_is_committable(self):
        self.assertEqual(len(self.sides(place("a"), raws={"osm:a": {"social_facility:for": "senior"}})[0]), 1)


class Verdicts(unittest.TestCase):
    def queue(self, rows, path):
        r.write_csv(r.split_queue(r.recommendations(rows, GUIDE, previous=r.read_previous((path,))))[0], r.QUEUE_COLUMNS, path)
        return m.read(path)

    def test_rerun_keeps_verdict_and_note(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "q.csv"
            first = self.queue([place("a")], path)
            first[0].update(hitl_review="accept", review_note="called them")
            r.write_csv(first, r.QUEUE_COLUMNS, path)
            again = self.queue([place("a")], path)[0]
            self.assertEqual((again["hitl_review"], again["review_note"]), ("accept", "called them"))

    def test_judged_place_stays_listed_after_falling_below_threshold(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "q.csv"
            first = self.queue([place("a")], path)
            first[0]["hitl_review"] = "reject"
            r.write_csv(first, r.QUEUE_COLUMNS, path)
            self.assertEqual(self.queue([place("a", review="")], path)[0]["hitl_review"], "reject")

    def test_build_supplement_reads_verdict_for_every_listing(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "q.csv"
            rows = [{"hitl_review": "accept", "member_keys": "omh:1|osm:node/2"}, {"hitl_review": "pending", "member_keys": "osm:node/3"}]
            with path.open("w", newline="") as f:
                w = csv.DictWriter(f, ["hitl_review", "member_keys"])
                w.writeheader()
                w.writerows(rows)
            self.assertEqual(b.read_queue_verdicts((path,)), {("omh", "1"): "accept", ("osm", "node/2"): "accept"})


class Label(unittest.TestCase):
    def test_general_lists_and_own_source_are_not_independent(self):
        self.assertEqual(r.corroboration_label({"source": "omh", "corroborating_sources": "facdb;osm;omh"}), 0)
        self.assertEqual(r.corroboration_label({"source": "osm", "corroborating_sources": "facdb;hrsa"}), 1)


class GuideChecks(unittest.TestCase):
    def test_flag_carries_no_page_text(self):
        guide = [{"id": "g", "organization_name": "Org", "street_number": "1", "street": "Main", "city": "NY", "zip_code": ""}]
        crawl = [{"group": "B", "source_id": "g", "address_check": "different_address_listed", "site_address": "2 Main", "contact_url": "u",
                  "final_url": "f", "closure_wording": "we have closed for good", "closure_url": "c"}]
        out = r.guide_checks(crawl, guide)
        self.assertEqual([x["flag"] for x in out], ["closure wording on site", "different address on site"])
        self.assertNotIn("closed for good", str(out))


@unittest.skipUnless(r.QUEUE_CSV.exists(), "run review_recommendations.py first")
class RealOutput(unittest.TestCase):
    def test_committed_queue_has_only_allowed_sources_and_nothing_sensitive(self):
        hidden = {x["source_id"] for x in m.read(m.SUPP_DIR / "endgbv.csv")} if (m.SUPP_DIR / "endgbv.csv").exists() else set()
        for row in m.read(r.QUEUE_CSV):
            self.assertIn(row["source"], r.COMMITTABLE_SOURCES)
            self.assertNotIn("endgbv", row["sources"])
            self.assertNotIn("endgbv:", row["member_keys"])
            self.assertFalse(r.SENSITIVE_NAME_RE.search(row["name"]), row["name"])
            self.assertNotIn(row["source_id"], hidden)


if __name__ == "__main__":
    unittest.main()
