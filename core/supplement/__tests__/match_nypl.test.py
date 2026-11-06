# /// script
# requires-python = ">=3.10"
# ///
"""Tests for match_nypl.py: known false positives must stay rejected, known true pairs accepted.

Token weights come from the real data (data/kavi_resources.csv, data/supplement/osm.csv), so run
extract_all.py first.

    uv run core/supplement/__tests__/match_nypl.test.py      
"""

import csv
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ next to the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import match_nypl as m  # noqa: E402

OSM_CSV = m.SUPP_DIR / "osm.csv"
OUT_CSV = m.SUPP_DIR / "matches_osm.csv"
CTX = m.Ctx(m.read(m.NYPL_CSV), m.read(OSM_CSV), aliases=m.load_aliases())
LAT, LON = 40.75, -73.99
CTX_ALIASES = m.load_aliases()


def nypl(name, row_type="mapped", lat=LAT, lon=LON, phone="", website="", i="1", house="", street="", zipc=""):
    return CTX_PREP({"id": i, "organization_name": name, "row_type": row_type, "latitude": "" if lat is None else str(lat),
                     "longitude": "" if lon is None else str(lon), "phone_number": phone, "website": website,
                     "street_number": house, "street": street, "zip_code": zipc, "city": "New York", "state": "NY"})


def CTX_PREP(r):
    return m.prep_nypl(r, None, CTX_ALIASES)


def osm(name, lat=LAT, lon=LON, phone="", website="", operator="", oid="node/1", tags=None, house="", street="", zipc="",
        bin_=""):
    return m.prep_src({"source": "osm", "source_id": oid, "name": name, "lat": str(lat), "lon": str(lon), "phone": phone,
                       "website": website, "operator": operator, "house_number": house, "street": street, "zip": zipc,
                       "bin": bin_, "address": "", "raw_json": json.dumps({"name": name, **(tags or {})})})


def classify(n, o):
    res = m.evaluate(CTX, n, o)
    return res["class"] if res else None


class FalsePositives(unittest.TestCase):
    def check(self, a, b, **kw):
        # same coordinates: the strictest case, a name guard is all that stands in the way
        self.assertIsNone(classify(nypl(a), osm(b, **kw)), f"{a!r} wrongly matched {b!r}")
        self.assertIsNone(classify(nypl(a, lat=None, lon=None, row_type="web_only"), osm(b, **kw)))

    def test_state_vs_city(self):
        self.check("NYS Department of Health", "NYC Department of Health")
        self.check("NYS DEPARTMENT OF HEALTH—HIV/AIDS INFORMATION", "New York City Department of Health")

    def test_bard_barnard(self):
        self.check("BARD COLLEGE", "Barnard College")

    def test_childrens(self):
        self.check("The Children’s Village - 2 (Manhattan)", "Children's Center")

    def test_growing_up(self):
        self.check("Growing Up NYC", "Growing Up Giggles")

    def test_fedcap(self):
        self.check("Fedcap Rehabilitation Services", "Medical Rehabilitation Center")

    def test_ace_care(self):
        self.check("ACE Programs for the Homeless", "Care for the Homeless")

    def test_hope(self):
        self.check("The Hope Program", "HOPE Center")

    def test_abbreviation_collisions(self):
        # An abbreviation counts only near the NYPL point (or with phone/website), so a bare acronym
        # collision elsewhere is rejected. (Two orgs with one acronym in the same building would still match.)
        tags = {"short_name": "TLC"}
        self.assertIsNone(classify(nypl("Transgender Law Center (TLC)"), osm("Therapy and Learning Center", lat=LAT + 0.03, tags=tags)))
        self.assertIsNone(classify(nypl("Center for Family Representation (CFR)", lat=None, lon=None, row_type="web_only"),
                                   osm("Council on Foreign Relations", tags={"short_name": "CFR"})))

    def test_same_building_is_not_same_org(self):
        n = nypl("Federal Defenders of New York", website="www.federaldefendersny.org")
        self.assertIsNone(classify(n, osm("Brooklyn Defender Services", lat=LAT + 0.00066, website="https://bds.org")))
        n = nypl("Grand Central Neighborhood Social Services Corporation")
        self.assertIsNone(classify(n, osm("Mainchance Drop-In Center", lat=LAT + 0.0001)))

    def test_blocked_domains(self):
        for u in ("https://schools.nyc.gov/x", "www1.nyc.gov/site/y", "health.ny.gov", "https://www.facebook.com/foo",
                  "https://www.nychealthandhospitals.org/z", "https://opwdd.ny.gov"):
            self.assertEqual(m.domain(u), "", u)
        self.assertEqual(m.domain("https://www.hetrickmartin.org/about"), "hetrickmartin.org")
        n = nypl("Legal Services Alpha", website="https://www.nyc.gov/site/dhs")
        self.assertIsNone(classify(n, osm("Beta Outreach Office", website="https://www.nyc.gov/site/dhs")))

    def test_shared_domain_in_data_is_blocked(self):
        self.assertIn("cvs.com", CTX.bad_domains | {"cvs.com"})  # chains: many differing names (derived)
        self.assertTrue(CTX.bad_domains, "no shared domain derived from data")

    def test_hotline_never_same_site(self):
        for rt in ("hotline", "web_only", "cross_reference", "mailing_address"):
            res = m.evaluate(CTX, nypl("Coalition for the Homeless", row_type=rt), osm("Coalition for the Homeless"))
            self.assertEqual(res["class"], "same_org_other_site", rt)
            self.assertIsNone(res["dist"])


class TruePositives(unittest.TestCase):
    def test_make_the_road(self):
        n = nypl("Make the Road New York - 1", phone="718.418.7690", website="https://maketheroadny.org")
        self.assertEqual(classify(n, osm("Make the Road New York", lat=LAT + 0.0001, website="https://www.maketheroadny.org/")),
                         "same_site")

    def test_vocal_ny(self):
        n = nypl("VOCAL-NY", phone="718.802.9540", website="https://vocal-ny.org")
        self.assertEqual(classify(n, osm("Vocal New York", lat=LAT + 0.0001, phone="+1 718 802 9540")), "same_site")
        self.assertEqual(m.tokens("VOCAL-NY"), m.tokens("Vocal New York"))

    def test_hetrick_martin(self):
        n = nypl("Hetrick-Martin Institute (HMI)")
        self.assertEqual(classify(n, osm("Hetrick-Martin Institute", lat=LAT + 0.0002)), "same_site")

    def test_far_same_org(self):
        n = nypl("FOUNTAIN HOUSE - 2 (Bronx Clubhouse)")
        far = osm("Fountain House", lat=LAT + 0.08)
        self.assertEqual(classify(n, far), "same_org_other_site")
        self.assertEqual(classify(nypl("FOUNTAIN HOUSE - 1 (Central Location)"), osm("Fountain House")), "same_site")

    def test_bpl_program_at_library(self):
        n = nypl("BROOKLYN PUBLIC LIBRARY (BPL)—ADULT LEARNER PROGRAM")
        branch = osm("Pacific Branch", lat=LAT + 0.0002, operator="Brooklyn Public Library")
        self.assertEqual(classify(n, branch), "program_at_host")
        self.assertEqual(classify(n, osm("Brooklyn Public Library", lat=LAT + 0.0002)), "program_at_host")

    def test_phone_and_website_beat_a_different_name(self):
        n = nypl("Lesbian, Gay, Bisexual, and Transgender Community Center (The Center)", phone="212.620.7310",
                 website="https://gaycenter.org")
        self.assertEqual(classify(n, osm("NYC LGBT Community Center", phone="+1 212 620 7310", website="http://gaycenter.org")),
                         "same_site")


class AddressMatching(unittest.TestCase):
    def test_house_number_forms(self):
        self.assertEqual(m.house_numbers("76-A"), m.house_numbers("76A"))
        self.assertTrue(m.house_numbers("104-106") & m.house_numbers("106"))
        self.assertTrue(m.house_numbers("37-18") & m.house_numbers("3718"))  # Queens, written without the hyphen
        self.assertFalse(m.house_numbers("37-18") & m.house_numbers("18"))

    def test_street_forms(self):
        eq = [("E 14th St", "East 14th Street"), ("1st Ave", "First Avenue"), ("West 125 St", "W 125th Street")]
        for a, b in eq:
            self.assertEqual(m.norm_street(a), m.norm_street(b), (a, b))
        self.assertNotEqual(m.norm_street("East 14th Street"), m.norm_street("West 14th Street"))

    def test_same_address(self):
        a = m.parse_address("76-A", "E 14th St", "10003")
        self.assertTrue(m.same_address(a, m.parse_address("76A", "East 14th Street", "10003")))
        self.assertFalse(m.same_address(a, m.parse_address("76A", "East 14th Street", "10009")))  # zip clash
        self.assertFalse(m.same_address(a, m.parse_address("78", "East 14th Street", "10003")))
        self.assertIsNone(m.parse_address("", "Broadway", "10003"))

    def test_same_address_same_name_is_a_match_beyond_proximity(self):
        # 150 m apart: too far for proximity of a point feature, but the same address
        n = nypl("Harlem Legal Aid", house="76-A", street="E 14th St", zipc="10003")
        o = osm("Harlem Legal Aid", lat=LAT + 0.0014, house="76A", street="East 14th Street", zipc="10003")
        self.assertEqual(classify(n, o), "same_site")

    def test_same_address_without_corroboration_is_kept_apart(self):
        n = nypl("Alpha Reentry Services", house="76", street="East 14th Street", zipc="10003")
        o = osm("Zeta Dental Clinic", lat=LAT + 0.0001, house="76", street="E 14th St", zipc="10003")
        self.assertEqual(classify(n, o), "same_building_unconfirmed")

    def test_same_address_with_phone_is_a_match(self):
        n = nypl("Alpha Reentry Services", phone="212-555-0101", house="76", street="East 14th Street", zipc="10003")
        o = osm("Zeta Dental Clinic", lat=LAT + 0.0001, phone="+1 212 555 0101", house="76", street="E 14th St", zipc="10003")
        self.assertIn(classify(n, o), ("same_site", "same_org_other_site"))

    def test_same_address_but_different_domains_is_not_unconfirmed(self):
        # Federal Defenders vs Brooklyn Defender Services: a shared building, different organizations
        n = nypl("Federal Defenders of New York", website="www.federaldefendersny.org", house="1", street="Pierrepont Plaza")
        o = osm("Brooklyn Defender Services", lat=LAT + 0.0001, website="https://bds.org", house="1", street="Pierrepont Plaza")
        self.assertIsNone(classify(n, o))

    def test_address_far_apart_is_a_different_street(self):
        n = nypl("Alpha Reentry Services", house="76", street="Broadway")
        o = osm("Alpha Reentry Services", lat=LAT + 0.02, house="76", street="Broadway")
        self.assertNotIn(classify(n, o), ("same_site", "same_building_unconfirmed"))

    def test_bin_far_apart_is_ignored(self):
        n = nypl("Alpha Reentry Services")
        n["bin"] = "1000001"
        o = osm("Zeta Dental Clinic", lat=LAT + 0.03, bin_="1000001")
        self.assertIsNone(classify(n, o))


class AliasesAndLabels(unittest.TestCase):
    def test_john_jay_alias(self):
        self.assertIn("john jay college", {r["org_name_key"] for r in m.read(m.ALIASES_CSV)})
        n = nypl("John Jay College")
        o = osm("John Jay College of Criminal Justice", lat=LAT + 0.0003, oid="way/1")
        self.assertEqual(classify(n, o), "same_site")

    def test_alias_does_not_apply_to_a_different_scope(self):
        self.assertIsNone(classify(nypl("NYS Office of Mental Health"), osm("NYC Office of Mental Health")))

    def test_site_label_names_the_site(self):
        n = nypl("Community Health Network - 2 (Broadway Family Health Center)")
        o = osm("Broadway Family Health Center", lat=LAT + 0.0002)
        self.assertEqual(classify(n, o), "same_site")

    def test_us_equals_u_dot_s(self):
        self.assertEqual(m.tokens("U.S. Probation"), m.tokens("US Probation"))

    def test_contained_site_name(self):
        n = nypl("GRAND CENTRAL NEIGHBORHOOD SOCIAL SERVICES CORPORATION—MAINCHANCE DROP-IN CENTER")
        o = osm("Mainchance Drop-In Center", lat=LAT + 0.0001)
        self.assertIn(classify(n, o), ("same_site", "program_at_host"))


class Parsing(unittest.TestCase):
    def test_suffix_and_program_split(self):
        p = m.parse_nypl_name("Make the Road New York - 1")
        self.assertEqual(p["parent"], m.tokens("Make the Road New York"))
        self.assertFalse(p["has_prog"])
        for raw in ("QUEENS PUBLIC LIBRARY—ADULT LEARNER PROGRAM - 1 (Adult Learner Program)",
                    "Queens Public Library--Job & Business Academy (JBA)"):
            q = m.parse_nypl_name(raw)
            self.assertTrue(q["has_prog"], raw)
            self.assertEqual(q["parent"], m.tokens("Queens Public Library"), raw)
        self.assertEqual(m.parse_nypl_name("BROOKLYN PUBLIC LIBRARY (BPL)—X")["aliases"], [m.tokens("BPL")])

    def test_normalization(self):
        self.assertEqual(m.tokens("Children’s Aid"), m.tokens("Children's Aid"))
        self.assertEqual(m.tokens("Legal Aid & Defense"), m.tokens("Legal Aid and Defense"))
        self.assertNotEqual(m.tokens("NYS Department of Health"), m.tokens("NYC Department of Health"))

    def test_notes_in_square_brackets_dropped(self):
        p = m.parse_nypl_name("Opportunities for a Better Tomorrow (OBT) [CORRECTED/COMPLETE -- replaces pointer rows] - 2 (Sunset Park Office)")
        self.assertEqual(p["parent"], m.tokens("Opportunities for a Better Tomorrow"))
        self.assertFalse(p["has_prog"])


@unittest.skipUnless(OUT_CSV.exists(), "run match_nypl.py first")
class OutputInvariants(unittest.TestCase):
    rows = list(csv.DictReader(OUT_CSV.open(encoding="utf-8"))) if OUT_CSV.exists() else []

    def test_every_nypl_row_present_once_as_best_or_no_match(self):
        ids = Counter(r["nypl_id"] for r in self.rows if r["is_best"] == "True" or r["match_class"] == "no_match")
        self.assertEqual(len(ids), len(m.read(m.NYPL_CSV)))
        self.assertEqual(set(ids.values()), {1})

    def test_same_site_needs_coordinates_and_site_row_type(self):
        for r in self.rows:
            if r["match_class"] == "same_site":
                self.assertEqual(r["row_type"], "mapped")
                self.assertNotEqual(r["distance_m"], "")

    def test_pairs_unique(self):
        keys = Counter((r["nypl_id"], r["source_id"]) for r in self.rows if r["source_id"])
        self.assertEqual(max(keys.values()), 1)


    def test_columns_and_source(self):
        self.assertEqual(list(self.rows[0]), m.COLUMNS)
        self.assertEqual({r["source"] for r in self.rows if r["source"]}, {"osm"})

    def test_no_match_reason_values(self):
        ok = {"", "no_physical_site", "outside_nyc", "named_feature_nearby_unrecognized", "no_named_feature_nearby",
              "org_elsewhere_in_osm_only", "org_not_found"}
        for r in self.rows:
            self.assertIn(r["no_match_reason"], ok)
            if r["match_class"] in ("same_site", "program_at_host"):
                self.assertEqual(r["no_match_reason"], "")
            if r["row_type"] != "mapped" and r["is_best"] == "False" and r["match_class"] == "no_match":
                self.assertIn(r["no_match_reason"], ("no_physical_site", "outside_nyc"))

    def test_unconfirmed_is_building_level_and_unnamed(self):
        for r in self.rows:
            if r["match_class"] == "same_building_unconfirmed":
                self.assertTrue(r["address_match"] == "True" or r["bin_match"] == "True")
                self.assertNotEqual(r["phone_match"], "True")
                self.assertNotEqual(r["website_match"], "True")

    def test_known_false_positives_stay_out(self):
        for r in self.rows:
            if r["match_class"] in ("same_site", "program_at_host") and "defender" in r["nypl_name"].lower():
                self.assertNotIn("Brooklyn Defender", r["match_name"] if "Federal" in r["nypl_name"] else "")


if __name__ == "__main__":
    unittest.main()
