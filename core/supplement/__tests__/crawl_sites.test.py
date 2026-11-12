"""Tests for crawl_sites.py. Pure functions use small synthetic pages; the fetch tests talk to a throwaway server
on 127.0.0.1 (no outside requests). The last class reads data/supplement/crawl_pilot.csv if it has been built.

    uv run core/supplement/__tests__/crawl_sites.test.py
"""

import csv
import json
import sys
import tempfile
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ next to the module under test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import crawl_sites as c  # noqa: E402

PAGES = {}
HITS = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        HITS.append((self.path, self.headers.get("User-Agent"), self.headers.get("Cookie")))
        status, headers, body = PAGES.get(self.path, (404, {}, b"not found"))
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def html(body, head=""):
    return (200, {"Content-Type": "text/html; charset=utf-8"}, f"<html><head>{head}</head><body>{body}</body></html>".encode())


class Clock:
    """Fake time: sleep advances the clock and records the wait."""

    def __init__(self):
        self.t, self.sleeps = 100.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        PAGES.clear()
        HITS.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.f = c.Fetcher(Path(self.tmp.name) / "cache", clock=self.clock.now, sleep=self.clock.sleep)
        self.robots = c.Robots(self.f)

    def page(self, url):
        return c.fetch_page(self.f, self.robots, url, "127.0.0.1", "127.0.0.1")


class FetchRules(Server):
    def test_robots_disallow_skips_page_and_is_fetched_first(self):
        PAGES["/robots.txt"] = (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /private\n")
        PAGES["/private/a"] = html("secret")
        PAGES["/ok"] = html("fine")
        self.assertEqual(self.page(self.base + "/private/a")["kind"], "robots_blocked")
        self.assertEqual(self.page(self.base + "/ok")["kind"], "ok")
        self.assertEqual(HITS[0][0], "/robots.txt")
        self.assertNotIn("/private/a", [h[0] for h in HITS])

    def test_robots_forbidden_html_and_server_error_all_skip(self):
        for status, body, kind in [(403, b"no", "robots_blocked"), (200, b"<html>soft 404</html>", "robots_unreadable"),
                                   (500, b"x", "robots_unreadable")]:
            PAGES.clear()
            HITS.clear()
            self.robots.hosts.clear()
            PAGES["/robots.txt"] = (status, {"Content-Type": "text/html"}, body)
            PAGES["/p"] = html("x")
            f = c.Fetcher(Path(self.tmp.name) / f"c{status}", clock=self.clock.now, sleep=self.clock.sleep)
            out = c.fetch_page(f, c.Robots(f), self.base + "/p", "k", "127.0.0.1")
            self.assertEqual(out["kind"], kind, status)
            self.assertNotIn("/p", [h[0] for h in HITS])

    def test_robots_redirect_same_site_is_followed(self):
        PAGES["/robots.txt"] = (301, {"Location": "/real-robots.txt"}, b"")
        PAGES["/real-robots.txt"] = (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /no\n")
        PAGES["/no/x"] = html("x")
        self.assertEqual(self.page(self.base + "/no/x")["kind"], "robots_blocked")

    def test_missing_robots_allows(self):
        PAGES["/p"] = html("x")
        self.assertEqual(self.page(self.base + "/p")["kind"], "ok")

    def test_rate_limit_user_agent_and_no_cookies(self):
        PAGES["/robots.txt"] = (404, {}, b"")
        PAGES["/a"], PAGES["/b"] = html("a"), html("b")
        self.page(self.base + "/a")
        self.page(self.base + "/b")
        self.assertTrue(self.clock.sleeps)
        self.assertTrue(all(s <= c.REQUEST_DELAY + 1e-9 and s > 0 for s in self.clock.sleeps))
        self.assertGreaterEqual(sum(self.clock.sleeps), 2 * c.REQUEST_DELAY - 1e-6)  # robots, /a, /b: two gaps
        self.assertTrue(all(h[1] == c.USER_AGENT and h[2] is None for h in HITS))
        self.assertNotIn("@", c.USER_AGENT)

    def test_crawl_delay_in_robots_raises_the_gap(self):
        PAGES["/robots.txt"] = (200, {"Content-Type": "text/plain"}, b"User-agent: *\nCrawl-delay: 5\n")
        PAGES["/a"], PAGES["/b"] = html("a"), html("b")
        self.page(self.base + "/a")
        self.page(self.base + "/b")
        self.assertGreaterEqual(max(self.clock.sleeps), 4.99)

    def test_cache_means_no_second_request(self):
        PAGES["/robots.txt"] = (404, {}, b"")
        PAGES["/a"] = html("a")
        self.page(self.base + "/a")
        n = len(HITS)
        self.robots.hosts.clear()
        self.assertEqual(self.page(self.base + "/a")["kind"], "ok")
        self.assertEqual(len(HITS), n)
        self.assertGreater(self.f.cached, 0)

    def test_cross_domain_redirect_recorded_not_followed(self):
        PAGES["/robots.txt"] = (404, {}, b"")
        PAGES["/go"] = (301, {"Location": f"http://localhost:{self.port}/dest"}, b"")
        PAGES["/dest"] = html("elsewhere")
        out = self.page(self.base + "/go")
        self.assertEqual((out["kind"], out["detail"]), ("offsite", "localhost"))
        self.assertNotIn("/dest", [h[0] for h in HITS])

    def test_same_domain_redirect_followed(self):
        PAGES["/robots.txt"] = (404, {}, b"")
        PAGES["/old"] = (302, {"Location": "/new"}, b"")
        PAGES["/new"] = html("here")
        out = self.page(self.base + "/old")
        self.assertEqual((out["kind"], out["url"]), ("ok", self.base + "/new"))

    def test_non_html_and_error_statuses(self):
        PAGES["/robots.txt"] = (404, {}, b"")
        PAGES["/doc.pdf"] = (200, {"Content-Type": "application/pdf"}, b"%PDF")
        self.assertEqual(self.page(self.base + "/doc.pdf")["kind"], "not_html")
        self.assertEqual(self.page(self.base + "/missing")["detail"], "http_404")

    def test_body_is_capped(self):
        PAGES["/robots.txt"] = (404, {}, b"")
        PAGES["/big"] = (200, {"Content-Type": "text/html"}, b"<p>" + b"x" * (c.MAX_BODY + 5000))
        self.assertLessEqual(len(self.page(self.base + "/big")["html"]), c.MAX_BODY)

    def test_one_retry_on_server_error(self):
        PAGES["/robots.txt"] = (404, {}, b"")
        PAGES["/flaky"] = (503, {}, b"")
        self.page(self.base + "/flaky")
        self.assertEqual([h[0] for h in HITS].count("/flaky"), 1 + c.RETRIES)

    def test_dead_host_is_dead(self):
        out = c.crawl_host(self.f, self.robots, "nonexistent.invalid", "https://nonexistent.invalid/")
        self.assertEqual(out["status"], "dead")

    def test_cache_dir_must_be_new_or_ours(self):
        d = Path(self.tmp.name) / "other"
        d.mkdir()
        (d / "something").write_text("x")
        with self.assertRaises(SystemExit):
            c.Fetcher(d)

    def test_crawl_host_limits_pages_and_skips_query_and_files(self):
        PAGES["/robots.txt"] = (404, {}, b"")
        links = "".join(f'<a href="{h}">{t}</a>' for h, t in [
            ("/events", "Events"), ("/programs", "Programs"), ("/about", "About us"), ("/contact", "Contact"),
            ("/hours", "Hours"), ("/search?q=x", "Search"), ("/report.pdf", "Services report"),
            ("https://other.example/events", "Events elsewhere"), ("/login", "Programs login")])
        PAGES["/"] = html(links + "<p>Home</p>")
        for p in ("/events", "/programs", "/about", "/contact", "/hours"):
            PAGES[p] = html(f"<p>{p}</p>")
        out = c.crawl_host(self.f, self.robots, "127.0.0.1", self.base + "/")
        self.assertEqual(out["status"], "live")
        self.assertLessEqual(len(out["pages"]), c.PAGES_PER_DOMAIN)
        paths = [h[0] for h in HITS]
        for bad in ("/search?q=x", "/report.pdf", "/login"):
            self.assertNotIn(bad, paths)
        self.assertTrue(all("?" not in p for p in paths))


class Parsing(unittest.TestCase):
    def test_pick_links_roles_and_filters(self):
        links = [("/about-us", "About"), ("/calendar", "Calendar"), ("mailto:a@b.org", "Email"), ("/x?y=1", "Services"),
                 ("/services", "Our services"), ("#top", "Top"), ("/files/a.pdf", "Programs"), ("/privacy", "Privacy")]
        got = c.pick_links("https://example.org/", links)
        self.assertEqual([r for _, r in got], ["events", "services_programs", "about"])

    def test_parked_and_script_text_ignored(self):
        pg = c.parse_page("<title>x</title><script>var a='Call 212-555-0100 Food pantry'</script><p>Real text here</p>")
        self.assertEqual([b["text"] for b in pg.blocks], ["Real text here"])

    def test_json_ld_event_and_cancelled(self):
        ld = json.dumps({"@graph": [
            {"@type": "Event", "name": "Job fair", "startDate": "2026-12-01T10:00:00",
             "location": {"name": "Main Hall", "address": {"streetAddress": "1 Main St"}}},
            {"@type": "Event", "name": "Old fair", "startDate": "2026-01-01"},
            {"@type": "Event", "name": "Gone", "startDate": "2027-01-01", "eventStatus": "https://schema.org/EventCancelled"}]})
        pg = c.parse_page(f'<script type="application/ld+json">{ld}</script><p>x</p>')
        rows, _ = c.structured_events(pg, "u")
        got = {r["title"]: (r["timing"], r["upcoming"], r["extracted"]) for r in rows}
        self.assertEqual(got, {"Job fair": ("upcoming", "yes", "structured"), "Old fair": ("past", "no", "structured")})
        self.assertIn("Main Hall", rows[0]["location_text"])

    def test_text_events_dates_never_guessed(self):
        pg = c.parse_page("<h3>Resume workshop</h3><p>Workshop on December 3, 2026 at 6 pm</p>"
                          "<h3>Food drive</h3><p>Food distribution on March 3, 2026</p>"
                          "<h3>Legal clinic</h3><p>Legal clinic on March 9</p>"
                          "<h3>Support group</h3><p>Support group every Tuesday at 5 pm</p>"
                          "<p>Posted March 3, 2027 in news</p>")
        got = {r["title"]: (r["timing"], r["upcoming"]) for r in c.text_events(pg, "u", "events")}
        self.assertEqual(got, {"Resume workshop": ("upcoming", "yes"), "Food drive": ("past", "no"),
                               "Legal clinic": ("partial_date", "unknown"), "Support group": ("recurring", "unknown")})

    def test_time_tag_date_and_opening_hours_are_not_events(self):
        pg = c.parse_page('<p>Open house <time datetime="2026-11-20">Nov 20</time></p>'
                          "<p>Office hours: Monday - Friday 9am - 5pm</p>")
        rows = c.text_events(pg, "u", "home")
        self.assertEqual([(r["date_text"][:10], r["timing"]) for r in rows], [("2026-11-20", "upcoming")])

    def test_undated_programs_flagged(self):
        pg = c.parse_page("<h2>Food Pantry</h2><h2>Contact us</h2><h2>Legal Help Desk</h2>")
        rows = c.text_programs(pg, "u")
        self.assertEqual([(r["title"], r["timing"]) for r in rows],
                         [("Food Pantry", "undated"), ("Legal Help Desk", "undated")])

    def test_person_names_dropped_from_titles(self):
        self.assertEqual(c.clean_title("Money talk with Maria Gonzalez"), "Money talk")

    def test_timing_boundary(self):
        self.assertEqual(c.timing_of([c.CRAWL_DATE], False, False), ("upcoming", "yes"))
        self.assertEqual(c.timing_of([date(2026, 11, 4)], False, False), ("past", "no"))
        self.assertEqual(c.timing_of([], False, False), ("undated", "unknown"))

    def test_description_cap_and_source(self):
        long = "word " * 200
        pg = c.parse_page(f'<meta name="description" content="{long}"><p>x</p>')
        text, origin, url = c.pick_description([("https://e.org/", "home", pg)])
        self.assertLessEqual(len(text), c.SNIPPET_MAX)
        self.assertEqual((origin, url), ("description", "https://e.org/"))

    def test_contacts_org_level_only(self):
        pg = c.parse_page("<p>Call us: (212) 555-0100</p><p>Jane Smith, Director, 212-555-0199</p>"
                          "<p>info@example.org</p><p>jane.smith@example.org</p><p>info@gmail.com</p>")
        phones, emails, _ = c.pick_contacts([("u", "home", pg)], "example.org")
        self.assertEqual((phones, emails), (["(212) 555-0100"], ["info@example.org"]))

    def test_services_need_evidence_and_languages_skip_widgets(self):
        pg = c.parse_page("<h1>Food pantry</h1><p>We speak Spanish and Russian here.</p>"
                          "<p>Select language: Spanish Chinese Arabic</p><p>Employment help</p>")
        crawl = {"pages": [("u", "home", pg)], "host": "example.org"}
        t = {"group": "A", "source": "osm", "source_id": "1", "name": "X Y", "house_number": "", "street": ""}
        an = c.analyse_host(crawl, [t])
        self.assertIn("Food", an["services"])
        self.assertNotIn("Housing", an["services"])
        self.assertEqual(an["languages"][0], ["Russian", "Spanish"])

    def test_names_place(self):
        blob = "Visit us at 123 West 14th Street, New York"
        self.assertTrue(c.names_place(blob, "", "123", "West 14th Street"))
        self.assertFalse(c.names_place(blob, "", "99", "West 14th Street"))
        self.assertTrue(c.names_place("Welcome to Hope Center Bronx", "Hope Center Bronx", "", ""))

    def test_shared_domain_withholds_location_specific_data(self):
        pg = c.parse_page("<p>Hours: Monday - Friday 9am - 5pm</p><h2>Health fair</h2><p>Health fair on 12/05/2026</p>")
        crawl = {"pages": [("u", "home", pg)], "host": "system.org", "status": "live", "detail": "", "final_url": "u",
                 "redirect_host": "", "skipped": []}
        t = {"group": "A", "source": "osm", "source_id": "1", "name": "Branch One", "house_number": "5", "street": "Oak",
             "website": "w", "borough": "Queens", "domain_place_count": 9, "guide_types": "", "guide_has_description": "",
             "relevance_score": "", "primary_type": "", "matched_osm_id": ""}
        an = c.analyse_host(crawl, [t])
        pilot, events = c.build_rows("system.org", crawl, an, [t], True, "2026-11-05")
        self.assertEqual(pilot[0]["hours"], "")
        self.assertIn("hours", pilot[0]["withheld_shared_domain"])
        self.assertEqual(events[0]["attribution"], "shared_domain_unattributed")
        self.assertEqual(pilot[0]["n_events"], 0)
        pilot, events = c.build_rows("system.org", crawl, an, [t], False, "2026-11-05")
        self.assertNotEqual(pilot[0]["hours"], "")
        self.assertEqual(events[0]["attribution"], "place")


class Targets(unittest.TestCase):
    def test_abuse_exclusion(self):
        self.assertTrue(c.is_abuse_related("Safe Haven", {"social_facility": "shelter", "social_facility:for": "abused"}))
        self.assertTrue(c.is_abuse_related("X", {"social_facility:for": "victim"}))
        self.assertTrue(c.is_abuse_related("Domestic Violence Shelter", {"social_facility": "shelter"}))
        self.assertFalse(c.is_abuse_related("Food Pantry", {"social_facility": "food_bank", "social_facility:for": "senior"}))
        self.assertFalse(c.is_abuse_related("Domestic Cleaning Co", {"office": "company"}))

    def test_first_url_drops_query_and_fragment(self):
        self.assertEqual(c.first_url("www.Example.org/a?b=1#c; other.com"), "https://www.example.org/a")
        self.assertEqual(c.first_url("not a url"), "")
        self.assertEqual(c.site_key("https://www.Example.org/x"), "example.org")

    def test_service_vocabulary_has_all_guide_types(self):
        self.assertEqual(len(c.SERVICE_REGEX), 11)


@unittest.skipUnless(c.PILOT_CSV.exists(), "crawl_pilot.csv not built")
class RealOutput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with c.PILOT_CSV.open(encoding="utf-8", newline="") as f:
            cls.rows = list(csv.DictReader(f))
        with c.EVENTS_CSV.open(encoding="utf-8", newline="") as f:
            cls.events = list(csv.DictReader(f))

    def test_columns_groups_and_no_endgbv(self):
        self.assertEqual(list(self.rows[0]), c.PILOT_FIELDS)
        self.assertTrue({r["group"] for r in self.rows} <= {"A", "B"})
        self.assertNotIn("endgbv", {r["source"] for r in self.rows})
        keys = [(r["group"], r["source"], r["source_id"]) for r in self.rows]
        self.assertEqual(len(keys), len(set(keys)))

    def test_snippet_caps_and_no_personal_email(self):
        for r in self.rows:
            self.assertLessEqual(len(r["description"]), c.SNIPPET_MAX)
            for e in filter(None, r["email"].split("; ")):
                self.assertIn(e.split("@")[0], c.GENERIC_MAILBOXES)

    def test_events_are_flagged_and_dates_consistent(self):
        for e in self.events:
            self.assertIn(e["timing"], {"upcoming", "past", "recurring", "partial_date", "undated"})
            self.assertEqual(e["upcoming"] == "yes", e["timing"] == "upcoming")
            if e["kind"] == "program":
                self.assertEqual(e["timing"], "undated")

    def test_excluded_places_absent(self):
        # Group A is every review source (OSM and HRSA), so names come from the supplement table; only OSM has tags.
        osm = {r["source_id"]: json.loads(r["raw_json"] or "{}") for r in c.read_csv(c.OSM_CSV)}
        names = {(r["source"], r["source_id"]): r["name"] for r in c.read_csv(c.SUPP_ALL)}
        for r in self.rows:
            if r["group"] == "A":
                name = names[(r["source"], r["source_id"])]
                self.assertFalse(c.is_abuse_related(name, osm.get(r["source_id"], {})))
                self.assertIsNone(c.GUIDE_ABUSE_RE.search(name))


if __name__ == "__main__":
    unittest.main()
