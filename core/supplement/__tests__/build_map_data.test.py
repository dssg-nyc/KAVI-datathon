"""Tests for build_map_data.py. Run: uv run core/supplement/__tests__/build_map_data.test.py"""

import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ next to the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_map_data as d  # noqa: E402


def guide(gid="1", phone="212-555-0100", website="", types='{Food}', row_type="mapped", lat="40.7"):
    return {"id": gid, "row_type": row_type, "latitude": lat, "longitude": "-74.0", "organization_name": "Org", "street_number": "1", "street": "Main St",
            "city": "New York", "zip_code": "10001", "borough": "Bronx", "phone_number": phone, "website": website, "service_types_all": types, "pdf_guide_page": "12",
            "description": "A food pantry.", "restricted_audiences": "", "focus_audiences": "", "spanish_speaking": "", "works_with_currently_incarcerated": "", "ati_program": "", "know_your_rights_content": ""}


def place(source="osm", sid="n/1", phone="", website="", hours="", types="", lat="40.7"):
    return {"source": source, "source_id": sid, "name": "Listing", "lat": lat, "lon": "-74.0" if lat else "", "phone": phone, "website": website, "opening_hours": hours,
            "proposed_service_types": types, "url": "https://example.org/x"}


def match(cls="same_site", source="osm", sid="n/1", best="True", gid="1"):
    return {"nypl_id": gid, "source": source, "source_id": sid, "match_class": cls, "is_best": best}


def queued(source="osm", sid="n/2", reason="", review="pending"):
    return {"hitl_review": review, "local_reason": reason, "source": source, "source_id": sid, "name": "Place", "address": "", "borough": "Brooklyn", "phone": "", "website": "",
            "proposed_service_types": "Food", "sources": source, "priority": "1_no_guide_site_nearby", "service_gaps": "Food", "relevance_score": "6.5", "relevance_signals": "",
            "m_to_nearest_guide_site": "900", "listings": "1", "url": "", "member_keys": f"{source}:{sid}"}


def event(title="Fair", keys="B:nypl_guide:1", upcoming="yes", attribution="place", relevance="service_type", types="Food", when="Dec 1, 2026", timing="upcoming"):
    return {"title": title, "place_keys": keys, "upcoming": upcoming, "attribution": attribution, "relevance": relevance, "service_types": types,
            "date_text": when, "source_url": "https://org.example/e", "crawl_date": "2026-11-05", "timing": timing}


def props(data, status):
    return [f["properties"] for f in data["features"] if f["properties"]["status"] == status]


class Additions(unittest.TestCase):
    def test_only_what_the_guide_lacks(self):
        adds = d.additions(guide(), place(phone="212-555-0199", website="https://a.org", hours="Mo-Fr 09:00-17:00", types="Food; Housing"))
        self.assertEqual(adds, {"website": "https://a.org", "hours": "Mo-Fr 09:00-17:00", "services": ["Housing"]})

    def test_a_match_with_nothing_new_adds_nothing(self):
        self.assertEqual(d.additions(guide(), place(phone="212-555-0199", types="Food")), {})


class Status(unittest.TestCase):
    def build(self, matches, places=None, queue=(), nypl=None):
        places = places if places is not None else {("osm", "n/1"): place()}
        return d.build(nypl or [guide()], places, matches, queue)

    def test_site_match_is_matched(self):
        self.assertEqual(props(self.build([match()]), "matched")[0]["sources"], ["osm"])

    def test_org_or_building_match_is_not_a_site_match(self):
        for cls in ("same_org_other_site", "same_building_unconfirmed", "no_match"):
            self.assertEqual(len(props(self.build([match(cls)]), "guide")), 1, cls)

    def test_only_the_best_candidate_counts(self):
        self.assertEqual(len(props(self.build([match(best="False")]), "guide")), 1)

    def test_unmapped_guide_row_is_not_drawn(self):
        self.assertEqual(self.build([], nypl=[guide(row_type="hotline", lat="")])["features"], [])

    def test_a_service_only_a_source_proposes_is_filterable(self):
        data = self.build([match()], {("osm", "n/1"): place(types="Housing")})
        self.assertEqual(props(data, "matched")[0]["domains"], ["Food", "Housing"])


class Confidential(unittest.TestCase):
    def test_endgbv_listing_without_coordinates_never_links_to_a_site(self):
        places = {("endgbv", "e1"): place("endgbv", "e1", phone="212-555-0111", lat="")}
        data = d.build([guide(phone="")], places, [match(source="endgbv", sid="e1")], [])
        self.assertEqual(len(props(data, "guide")), 1)
        self.assertNotIn("212-555-0111", json.dumps(data))

    def test_sensitive_review_place_is_left_out_and_counted(self):
        places = {("hrsa", "n/2"): place("hrsa", "n/2")}
        data = d.build([], places, [], [queued("hrsa", reason="sensitive")])
        self.assertEqual((data["features"], data["meta"]["left_out"]), ([], {"sensitive": 1}))


class Review(unittest.TestCase):
    def test_pending_place_with_coordinates_is_drawn(self):
        data = d.build([], {("osm", "n/2"): place(sid="n/2")}, [], [queued()])
        self.assertEqual(props(data, "review")[0]["gaps"], ["Food"])

    def test_no_coordinates_or_a_verdict_is_left_out(self):
        places = {("osm", "n/2"): place(sid="n/2", lat=""), ("osm", "n/3"): place(sid="n/3")}
        data = d.build([], places, [], [queued(), queued(sid="n/3", review="accept")])
        self.assertEqual(data["meta"]["left_out"], {"no_location": 1, "already_judged": 1})


class Crawl(unittest.TestCase):
    ROW = {"group": "B", "source_id": "1", "description": "We help.", "guide_has_description": "False", "phone": "", "hours": "Mon 9-5", "languages": "", "eligibility": "An eligible sentence.",
           "referral": "A stray sentence.", "final_url": "https://org.example/"}

    def test_site_findings_count_as_the_pilot_source(self):
        data = d.build([guide()], {}, [], [], [self.ROW], [event()])
        e = props(data, "matched")[0]["enrich"][0]
        self.assertEqual((e["source"], e["adds"]["description"], e["adds"]["events"][0]["title"]), (d.WEBSITE_PILOT, "We help.", "Fair"))

    def test_noisy_fields_are_not_shown(self):
        adds = d.crawl_additions({**self.ROW, "description": "", "hours": ", , , ,"}, guide(), [])
        self.assertEqual(adds, {})

    def test_general_event_is_not_shown(self):
        events = d.upcoming_events(d.clean_events([event(relevance="general", types="")]))
        self.assertEqual(dict(events), {})

    def test_nothing_found_stays_guide_only(self):
        empty = {**self.ROW, "description": "", "hours": ""}
        self.assertEqual(len(props(d.build([guide()], {}, [], [], [empty]), "guide")), 1)

    def test_unattributed_event_is_not_shown(self):
        self.assertEqual(d.clean_events([event(attribution="shared_domain_unattributed")]), [])


class Card(unittest.TestCase):
    SITE = {"group": "A", "source": "osm", "source_id": "n/2", "shared_domain": "False", "redirect_host": "", "description": "We feed people.", "description_url": "https://org.example/about",
            "final_url": "https://org.example/", "languages": "Arabic", "hours": ", , ,"}
    PLACES = {("osm", "n/2"): place(sid="n/2", hours="Mo-Fr 09:00-17:00")}

    def review(self, **site):
        return props(d.build([], self.PLACES, [], [queued()], [self.SITE | site]), "review")[0]

    def test_guide_row_carries_its_description_and_labels(self):
        g = guide() | {"restricted_audiences": "{Youth}", "focus_audiences": '{Youth,"LGBTQI+"}', "spanish_speaking": "t", "ati_program": "f"}
        p = props(d.build([g], {}, [], []), "guide")[0]
        self.assertEqual(p["description"], "A food pantry.")
        self.assertEqual(p["labels"], ["Youth only", "Focus: LGBTQI+", "Spanish spoken"])

    def test_review_place_gets_what_its_own_site_says(self):
        p = self.review()
        self.assertEqual((p["description"], p["languages"], p["site_url"]), ("We feed people.", "Arabic", "https://org.example/about"))
        self.assertEqual(p["hours"], "")  # the extractor's empty day list
        self.assertEqual(p["osm_hours"], "Mo-Fr 09:00-17:00")

    def test_shared_or_redirected_site_says_nothing_about_the_place(self):
        for site in ({"shared_domain": "True"}, {"redirect_host": "other.example"}):
            self.assertNotIn("description", self.review(**site))


class EventList(unittest.TestCase):
    def build(self, rows, nypl=None, places=None, queue=()):
        return d.build(nypl if nypl is not None else [guide()], places or {}, [], queue, [], rows)

    def test_general_event_is_listed_as_not_classified(self):
        e = self.build([event(relevance="general", types="")])["events"][0]
        self.assertEqual((e["domains"], e["places"]), (["Not classified"], [0]))

    def test_event_points_at_a_review_place_through_its_listing(self):
        places = {("osm", "n/2"): place(sid="n/2")}
        data = self.build([event(keys="A:osm:n/2")], nypl=[], places=places, queue=[queued()])
        self.assertEqual(data["events"][0]["places"], [0])

    def test_event_at_a_sensitive_place_stays_out(self):
        places = {("hrsa", "n/2"): place("hrsa", "n/2")}
        data = self.build([event(title="Secret group", keys="A:hrsa:n/2")], nypl=[], places=places, queue=[queued("hrsa", reason="sensitive")])
        self.assertEqual(data["events"], [])
        self.assertNotIn("Secret group", json.dumps(data))

    def test_past_undated_and_heading_rows(self):
        self.assertEqual(self.build([event(upcoming="no")])["events"], [])
        self.assertEqual(self.build([event(title="\u200bUpcoming Events")])["events"], [])
        self.assertEqual(self.build([event(title="Add to My Calendar Winter Recess, schools closed")])["events"], [])

    def test_same_day_runs_in_time_order(self):
        rows = [event("Noon", when="Nov 9, 2026 12:00 PM"), event("Nine", when="Nov 9, 2026 9:00 AM"), event("Dinner", when="Nov 9, 2026 6:30 PM")]
        self.assertEqual([e["title"] for e in self.build(rows)["events"]], ["Nine", "Noon", "Dinner"])

    def test_soonest_first_and_undated_last(self):
        rows = [event("Later", when="Dec 1, 2026"), event("No date", when="soon"), event("Sooner", when="Nov 9, 2026")]
        self.assertEqual([e["title"] for e in self.build(rows)["events"]], ["Sooner", "Later", "No date"])

    def test_spanish_title_gets_a_service_from_the_saved_row(self):
        e = self.build([event("Center Support: Inmigrantes LGBTQIA+", relevance="general", types="")])["events"][0]
        self.assertEqual(e["domains"], ["Legal & Rights"])

    def test_recurring_event_needs_a_service_and_sorts_after_dated_ones(self):
        rows = [event("Pantry", upcoming="unknown", timing="recurring", when="Saturdays"), event("Dated"),
                event("Board meeting", upcoming="unknown", timing="recurring", when="Monthly", relevance="general", types="")]
        events = self.build(rows)["events"]
        self.assertEqual([x["title"] for x in events], ["Dated", "Pantry"])
        self.assertEqual((events[1]["date"], events[1]["when"]), ("", "Recurring: Saturdays"))

    def test_title_entities_are_decoded(self):
        self.assertEqual(self.build([event("Medicaid &amp; You")])["events"][0]["title"], "Medicaid & You")


class EventDates(unittest.TestCase):
    CRAWLED = date(2026, 11, 5)

    def test_formats_the_crawl_produced(self):
        cases = {"2026-11-05T18:00:00-05:00 to 2026-11-05T19:30:00-05:00": ("2026-11-05", "Nov 5, 2026, 6:00 PM"), "November 13, 2026": ("2026-11-13", "Nov 13, 2026"),
                 "DECEMBER 31st 2026": ("2026-12-31", "Dec 31, 2026"), "Nov 12th, 2026 10 AM": ("2026-11-12", "Nov 12, 2026, 10:00 AM"),
                 "Nov 12th, 2026 12:30p": ("2026-11-12", "Nov 12, 2026, 12:30 PM")}
        for text, want in cases.items():
            self.assertEqual(d.event_when(text, self.CRAWLED), want, text)

    def test_next_date_when_there_are_several_and_no_guessed_time(self):
        self.assertEqual(d.event_when("2026-09-11; 2026-11-30 10:00 AM", self.CRAWLED), ("2026-11-30", "Nov 30, 2026"))

    def test_implausible_start_keeps_the_date_only(self):
        self.assertEqual(d.event_when("2026-11-05T01:00:00-05:00 to 2026-11-05T18:00:00-05:00", self.CRAWLED), ("2026-11-05", "Nov 5, 2026"))

    def test_unreadable_date_shows_as_written(self):
        self.assertEqual(d.event_when("Every Tuesday", self.CRAWLED), ("", "Every Tuesday"))


if __name__ == "__main__":
    unittest.main()
