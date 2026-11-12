# /// script
# requires-python = ">=3.10"
# ///
"""A polite crawl of the websites of two groups of places. It sends real requests to those sites: run it on purpose.

  A  Review places in data/supplement/supplement_all.csv with hitl_review = pending and a website, from the sources
     in REVIEW_SOURCES (OSM and HRSA).
  B  Mapped NYPL Connections Guide rows (data/kavi_resources.csv) with a website, using the guide's own `website`;
     matched_osm_id lists a site-level OSM match when there is one. They enrich the guide's records and act as a
     benchmark, because their service types (`service_types_all`) are human-reviewed.

    python3 core/supplement/crawl_sites.py --cache DIR            crawl (re-runs read the cache and make no requests)
    python3 core/supplement/crawl_sites.py --list                 only list the targets and the excluded count
    python3 core/supplement/crawl_sites.py --cache DIR --limit 5  first 5 domains only

Writes data/supplement/crawl_pilot.csv (one row per place or guide row) and data/supplement/crawl_events.csv (one
row per event or program), both ignored by git. Nothing else is read for targets: no FacDB, OMH, IRS or other
source, and no ENDGBV rows. Places tagged or named as a shelter or service for abuse or violence survivors are left
out of the crawl and of every output; only their count is reported.

Crawl rules (constants below): robots.txt fetched and obeyed for every host (a page is skipped, with the reason, when
robots disallows it or cannot be read or parsed); at most one request per REQUEST_DELAY seconds per domain; the home
page plus at most PAGES_PER_DOMAIN - 1 same-domain pages found from its links (about, services, programs, events,
calendar, hours, contact), no sitemap; at most MAX_WORKERS domains at once; GET only; no cookies, forms, logins,
search or query strings; HTML only; timeout, one retry and a body cap; a redirect to another domain is recorded and
not followed. The User-Agent names the project and nothing else. Raw pages are kept only in --cache DIR, which must
be new or empty (outside the repo); page content is untrusted text, parsed but never executed.

Extraction is by rules, no LLM and no external API. Third-party text is kept as short snippets (SNIPPET_MAX), never
whole pages. Contact details are organization-level only: generic role mailboxes, and phone numbers outside blocks
that mention staff. When a domain is shared by several places (a chain or health system) hours and events are only
attributed to a place if the page names its address or name.

Standard library only (the service vocabulary is imported from build_supplement.py).
"""

import argparse
import csv
import hashlib
import json
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_supplement as b  # noqa: E402
import match_nypl as m  # noqa: E402

CRAWL_DATE = date.today()  # "today" for upcoming vs past, the same date as fetch_sources.ACCESSED
USER_AGENT = "KAVI-datathon-pilot/0.1 (research pilot; obeys robots.txt)"
GUIDE_CSV = m.ROOT / "data" / "kavi_resources.csv"
SUPP_ALL = b.OUT_CSV
MATCHES_OSM = m.SUPP_DIR / "matches_osm.csv"
OSM_CSV = m.SUPP_DIR / "osm.csv"
PILOT_CSV = m.SUPP_DIR / "crawl_pilot.csv"
EVENTS_CSV = m.SUPP_DIR / "crawl_events.csv"
CACHE_MARKER = ".kavi-crawl-cache"

REQUEST_DELAY = 2.0       # seconds between requests to one domain (robots Crawl-delay may raise it)
CRAWL_DELAY_MAX = 30.0
REVIEW_SOURCES = {"osm", "hrsa"}  # review sources whose rows carry a website; ENDGBV is never crawled    # a robots Crawl-delay above this skips the domain
PAGES_PER_DOMAIN = 5      # home plus up to 4 linked pages
MAX_WORKERS = 4           # domains in flight at once
TIMEOUT = 20              # seconds
RETRIES = 1
MAX_BODY = 1_000_000      # bytes read per page
MAX_ROBOTS = 500_000
MAX_REDIRECTS = 4
SNIPPET_MAX = 300         # description cap; other snippets use SNIPPET_SHORT
SNIPPET_SHORT = 200
SHARED_DOMAIN_PLACES = 3  # a domain on this many places or more is a chain or system, so content may be elsewhere
MAX_BLOCKS = 4000
BLOCK_MAX = 600
EVENTS_PER_DOMAIN = 25
PROGRAMS_PER_DOMAIN = 8
STRONG_MIN_KEYWORDS = 2   # a service type is "supported" with this many distinct keywords, or one in a title / heading

SKIP_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".jpg", ".jpeg", ".png", ".gif", ".svg",
            ".webp", ".mp3", ".mp4", ".mov", ".avi", ".ics", ".csv", ".xml", ".json", ".rss", ".css", ".js", ".ico"}
SKIP_PATH_RE = re.compile(r"login|log-in|signin|sign-in|register|account|cart|checkout|search|wp-admin|wp-login|logout|"
                          r"donate|giving|subscribe|cdn-cgi|admin|password", re.I)
PAGE_KINDS = [  # (role, regex on link text or path), in the order they are picked
    ("events", re.compile(r"event|calendar|what'?s[- ]on|workshop|upcoming", re.I)),
    ("services_programs", re.compile(r"program|service|activit|resources|what[- ]we[- ]do|get[- ]help|classes", re.I)),
    ("about", re.compile(r"about|who[- ]we[- ]are|mission|our[- ]story", re.I)),
    ("hours_contact", re.compile(r"hours|contact|visit|location|directions|find[- ]us", re.I)),
]
PARKED_RE = re.compile(r"domain (name )?(is|may be|might be) (for sale|available)|buy this domain|this domain is for sale|"
                       r"domain (has )?expired|sedoparking|hugedomains|afternic|parked (free|domain|by|at)|"
                       r"under construction|coming soon|website is (currently )?(unavailable|suspended)", re.I)
ABUSE_RE = re.compile(r"abus|victim|violence|survivor|battered|domestic|\bdv\b|sexual assault|rape|trafficking", re.I)
GUIDE_ABUSE_RE = re.compile(r"(?<!substance )abus|victim|violence|survivor|battered|domestic|\bdv\b|sexual assault|rape"
                            r"|trafficking", re.I)  # names only, for rows without OSM tags; substance abuse is kept
ABUSE_TAG_RE = re.compile(r"abus|victim|violence|survivor|battered|domestic|rape|trafficking", re.I)

DISABILITY_PATTERN = (r"disabilit(y|ies) services?|people with disabilities|developmental disabilit|intellectual disabilit"
                      r"|special needs|supported employment")
SERVICE_REGEX = {t: re.compile(p, re.I) for t, p in {**b.SERVICE_PATTERNS, "Disability Services": DISABILITY_PATTERN}.items()}

DAYS = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*"
TIME = r"\d{1,2}(?::\d\d)?\s*(?:a\.?m\.?|p\.?m\.?)"
HOURS_RE = re.compile(rf"\b{DAYS}\b[^.]{{0,60}}?{TIME}", re.I)
HOURS_WORD_RE = re.compile(r"hours|open|office", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?\(?([2-9]\d{2})\)?[\s.\-]?(\d{3})[\s.\-](\d{4})(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
STAFF_RE = re.compile(r"director|manager|coordinator|officer|\bext\b|extension|attorney|counselor|specialist|\bdr\.|"
                      r"\bceo\b|president|staff|supervisor|case worker|caseworker|\bfax\b|\bmr\.|\bms\.|\bmrs\.", re.I)
GENERIC_MAILBOXES = {"info", "contact", "hello", "office", "admin", "help", "helpdesk", "intake", "referrals", "referral",
                     "programs", "services", "support", "general", "inquiries", "enroll", "enrollment", "reception",
                     "frontdesk", "mail", "outreach", "contactus", "askus", "welcome"}
LANGUAGES = ["Spanish", "Chinese", "Mandarin", "Cantonese", "Russian", "Arabic", "Haitian Creole", "Creole", "Bengali",
             "Korean", "French", "Polish", "Yiddish", "Hebrew", "Urdu", "Hindi", "Italian", "Vietnamese", "Albanian",
             "Tagalog", "Portuguese", "American Sign Language", "ASL"]
LANGUAGE_RE = re.compile(r"\b(" + "|".join(LANGUAGES) + r")\b")
LANGUAGE_CUE_RE = re.compile(r"languages? spoken|we speak|spoken|available in|services? (are )?(offered |provided )?in|"
                             r"se habla|interpret|bilingual|multilingual|translation (is )?available|in (english|spanish)", re.I)
LANGUAGE_WIDGET_RE = re.compile(r"select language|translate|choose (a )?language|google", re.I)
ELIGIBILITY_RE = re.compile(r"\beligib|who (can|may) (apply|qualify|receive|participate)|must be (a |an )?(resident|\d+|at least|"
                            r"over|under)|open to (all )?(residents|adults|youth|seniors|women|men|families|new yorkers)|"
                            r"income[- ]eligible|ages? \d+\s*(-|to|and)\s*\d+|\bqualif(y|ies|ied)\b", re.I)
REFERRAL_RE = re.compile(r"referral|referred|self-?refer|walk-?ins? (are )?(welcome|accepted|only)|no appointment|"
                         r"intake|how to apply|to apply,|call (us )?to (enroll|register|schedule|apply)", re.I)
BOILERPLATE_RE = re.compile(r"cookie|privacy", re.I)
CLOSURE_RE = re.compile(r"permanently closed|has (been )?closed|is (now )?closed (permanently|indefinitely)|"
                        r"no longer (accepting|offering|available|operating|providing|open)|program (has )?(ended|"
                        r"been discontinued)|discontinued|has (moved|relocated) to|we have moved|new location", re.I)
CLOSURE_SKIP_RE = re.compile(r"closed (on|for|mon|tue|wed|thu|fri|sat|sun)", re.I)
EVENT_WORD_RE = re.compile(r"event|workshop|class|session|meeting|webinar|orientation|support group|fair|distribution|"
                           r"clinic|training|screening|open house|forum|town hall|group|drop-?in|office hours", re.I)
NOT_EVENT_RE = re.compile(r"posted|published|©|copyright|updated|press release|news|blog|read more|privacy", re.I)
MONTH_NUM = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
             "nov": 11, "dec": 12}
DATE_RE = re.compile(r"\b(?P<m>january|february|march|april|may|june|july|august|september|october|november|december|"
                     r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\.?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?\b"
                     r"(?:,?\s+(?P<y>(?:19|20)\d\d)\b)?", re.I)
NUMERIC_DATE_RE = re.compile(r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>(?:19|20)?\d\d)\b")
ISO_DATE_RE = re.compile(r"\b(?P<y>20\d\d)-(?P<m>\d\d)-(?P<d>\d\d)\b")
RECUR_RE = re.compile(r"\bevery (?:other )?(?:mon|tues|wednes|thurs|fri|satur|sun)day|\b(?:mon|tues|wednes|thurs|fri|satur|sun)"
                      r"days\b|\bweekly\b|\bmonthly\b|\b(?:first|second|third|fourth|last) (?:mon|tues|wednes|thurs|fri|satur|"
                      r"sun)day\b", re.I)
TIME_RE = re.compile(TIME, re.I)
LOCATION_RE = re.compile(r"(?:location|where|venue|address)\s*:\s*([^|•\n]{3,100})", re.I)
PERSON_TAIL_RE = re.compile(r"\s+(?:with|by|led by|presented by|featuring)\s+(?:dr\.?|prof\.?|mr\.?|ms\.?|mrs\.?)?\s*"
                            r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+.*$")
GENERIC_HEADINGS = re.compile(r"^(home|menu|contact|contact us|about|about us|donate|subscribe|search|login|log in|sign up|"
                              r"follow us|newsletter|our team|staff|board|careers|jobs|news|blog|privacy|terms|share|"
                              r"related|events|upcoming events|calendar|footer|navigation|skip to|get involved|"
                              r"volunteer|partners|sponsors|testimonials|faq|faqs|resources|programs|services)\b", re.I)
WEAK_TITLE_RE = re.compile(r"^(when|where|date|time)\s*:|^(featured |upcoming |past )?events?( (&|and) happenings)?$|^calendar$", re.I)
WEEKDAY_RE = re.compile(r"\b(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?\b", re.I)
EVENT_TYPE_WORDS = {  # event wording the guide's service vocabulary misses (guide descriptions are about services)
    "Employment": r"training program|information session|info session|hiring|job fair|apprentice|interview|toastmasters|\bempleos?\b",
    "Health & Mental Health": r"support group|sober|anonymous|drop-?in|vaccin|screening|acupuncture|health fair|wellness|\bsalud\b|grupos? de apoyo|consejer[ií]a",
    "Financial Assistance": r"medicaid|open enrollment|benefits|tax|underearners|money|beneficios|impuestos",
    "Legal & Rights": r"legal|know your rights|immigrants?|immigration|inmigrantes?|inmigraci[oó]n|abogad[oa]s?|derechos",
    "Education": r"\bged\b|\besol\b|computer class|literacy|tutor|clases? de ingl[eé]s|alfabetizaci[oó]n",
    "Food": r"\bcomida\b|alimentos|despensa",
    "Housing": r"\bvivienda\b|desalojo"}
EVENT_TYPE_REGEX = {t: re.compile(p, re.I) for t, p in EVENT_TYPE_WORDS.items()}
EVENT_STATUS_SKIP = ("EventCancelled", "EventPostponed")

PILOT_FIELDS = ["group", "source", "source_id", "matched_osm_id", "name", "borough", "website", "domain", "crawl_date",
                "site_status", "status_detail", "final_url", "redirect_host", "shared_domain", "domain_place_count",
                "pages_fetched", "pages_skipped", "description", "description_origin", "description_url",
                "service_types_found", "service_evidence", "site_supports_service", "hours", "hours_url", "phone",
                "email", "contact_url", "site_address", "address_check", "languages", "languages_url", "eligibility",
                "eligibility_url", "referral", "referral_url", "closure_wording", "closure_url", "ics_links",
                "n_events", "n_upcoming", "n_programs_undated", "withheld_shared_domain", "guide_service_types",
                "guide_has_description", "relevance_score", "primary_type"]
EVENT_FIELDS = ["group", "place_keys", "domain", "kind", "title", "date_text", "timing", "upcoming", "location_text",
                "source_url", "extracted", "extraction_detail", "attribution", "service_types", "relevance", "crawl_date"]


# ---- targets --------------------------------------------------------------------------------------
def read_csv(path):
    csv.field_size_limit(10**9)
    with Path(path).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def is_abuse_related(name, raw):
    """True for an OSM place tagged as a shelter or service for abuse or violence survivors: a social_facility
    value such as abused or victim, or a name that says so on a place tagged social_facility."""
    social = {k: str(v) for k, v in raw.items() if k.startswith("social_facility")}
    if any(ABUSE_TAG_RE.search(v) for v in social.values()):
        return True
    return bool(social) and bool(ABUSE_RE.search(name or ""))


def first_url(value):
    """First website in a free-text field as an http(s) URL without query or fragment, or ''."""
    for tok in re.split(r"[\s;,]+", (value or "").strip()):
        if not tok or "." not in tok:
            continue
        if not re.match(r"https?://", tok, re.I):
            tok = "https://" + tok.lstrip("/")
        parts = urlsplit(tok)
        if parts.hostname:
            return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", "", ""))
    return ""


def site_key(url):
    """Host without a leading www.: the unit that is crawled once."""
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def load_targets():
    """([target dicts], counts). Excluded places are counted and dropped here; nothing downstream sees them."""
    supp = [r for r in read_csv(SUPP_ALL) if r["source"] != "endgbv"]
    raw_by_id = {r["source_id"]: json.loads(r.get("raw_json") or "{}") for r in read_csv(OSM_CSV)}
    guide = {r["id"]: r for r in read_csv(GUIDE_CSV)}
    counts = Counter()
    targets = []
    for r in supp:
        if r["source"] not in REVIEW_SOURCES or r["hitl_review"] != "pending" or not r["website"]:
            continue
        if is_abuse_related(r["name"], raw_by_id.get(r["source_id"], {})) or GUIDE_ABUSE_RE.search(r["name"]):
            counts["excluded_A"] += 1
            continue
        url = first_url(r["website"])
        if not url:
            counts["A_no_usable_url"] += 1
            continue
        targets.append({"group": "A", "source": r["source"], "source_id": r["source_id"], "matched_osm_id": "",
                        "name": r["name"], "borough": r["borough"], "website": r["website"], "url": url,
                        "house_number": r["house_number"], "street": r["street"], "guide_types": "",
                        "guide_has_description": "", "relevance_score": r["relevance_score"],
                        "primary_type": r["primary_type"]})
    site_matches = defaultdict(list)
    for r in read_csv(MATCHES_OSM):
        if r["match_class"] in b.SITE:
            site_matches[r["nypl_id"]].append(r["source_id"])
    for nid, g in sorted(guide.items(), key=lambda kv: int(kv[0])):
        if g["row_type"] != "mapped":
            continue
        osm_ids = site_matches.get(nid, [])
        if any(is_abuse_related("", raw_by_id.get(o, {})) for o in osm_ids) or GUIDE_ABUSE_RE.search(g["organization_name"]):
            counts["excluded_B"] += 1
            continue
        url = first_url(g["website"])
        if not url:
            counts["B_no_website"] += 1
            continue
        targets.append({"group": "B", "source": "nypl_guide", "source_id": nid,
                        "matched_osm_id": ";".join(sorted(set(osm_ids))), "name": g["organization_name"],
                        "borough": g["borough"], "website": g["website"], "url": url, "house_number": g["street_number"],
                        "street": g["street"], "guide_types": g["service_types_all"],
                        "guide_has_description": str(bool(g["description"].strip())), "relevance_score": "",
                        "primary_type": ""})
    # places per registrable domain: supplement groups, plus guide organizations not already matched to one
    places = defaultdict(set)
    matched_ids = {r["matched_nypl_id"] for r in supp if r["matched_nypl_id"]}
    for r in supp:
        d = m.domain(r["website"])
        if d:
            places[d].add(r["group_id"] or (r["source"], r["source_id"]))
    for nid, g in guide.items():
        d = m.domain(g["website"])
        if d and nid not in matched_ids:
            places[d].add(("guide", g["organization_name"].lower()))
    for t in targets:
        t["domain_place_count"] = len(places.get(m.domain(t["url"]), ()))
    return targets, counts


def group_by_host(targets):
    """{site_key: (start_url, [targets])}: each domain once, starting at the shortest path among its targets."""
    hosts = defaultdict(list)
    for t in targets:
        hosts[site_key(t["url"])].append(t)
    return {h: (min((t["url"] for t in ts), key=lambda u: (len(urlsplit(u).path), u)), ts)
            for h, ts in sorted(hosts.items())}


# ---- fetching -------------------------------------------------------------------------------------
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def error_kind(exc):
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, socket.gaierror):
        return "dns"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(reason, ssl.SSLError) or "CERTIFICATE" in str(reason).upper():
        return "tls"
    if isinstance(reason, ConnectionRefusedError):
        return "refused"
    return "error:" + type(reason).__name__


class Fetcher:
    """GET with a per-domain delay, cached on disk. Redirects are returned, not followed."""

    def __init__(self, cache_dir, delay=REQUEST_DELAY, clock=time.monotonic, sleep=time.sleep):
        self.dir = Path(cache_dir)
        if self.dir.exists() and any(self.dir.iterdir()) and not (self.dir / CACHE_MARKER).exists():
            raise SystemExit(f"{self.dir} is not empty and not a crawl cache: use a new, empty directory")
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / CACHE_MARKER).write_text("raw downloads, untrusted; not for the repo\n")
        self.delay, self.clock, self.sleep = delay, clock, sleep
        self.last = {}
        self.lock = threading.Lock()
        self.requests = 0
        self.cached = 0

    def _paths(self, url):
        key = hashlib.sha1(url.encode()).hexdigest()
        return self.dir / f"{key}.json", self.dir / f"{key}.body"

    def _wait(self, key, delay):
        with self.lock:
            last = self.last.get(key)
        now = self.clock()
        if last is not None and now - last < delay:
            self.sleep(delay - (now - last))
        with self.lock:
            self.last[key] = self.clock()
            self.requests += 1

    def fetch(self, url, key, delay=None, max_body=MAX_BODY):
        """{status, location, ctype, error, body: bytes}; status 0 with an error kind when there was no response."""
        meta_p, body_p = self._paths(url)
        if meta_p.exists():
            res = json.loads(meta_p.read_text())
            res["body"] = body_p.read_bytes() if body_p.exists() else b""
            with self.lock:
                self.cached += 1
            return res
        res = {"url": url, "status": 0, "location": "", "ctype": "", "error": "", "body": b""}
        for _ in range(RETRIES + 1):
            self._wait(key, delay or self.delay)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity",
                                                       "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8"})
            # plain http(s) handlers that never follow redirects and keep no cookies; one opener per request (threads)
            opener = urllib.request.build_opener(urllib.request.HTTPHandler, urllib.request.HTTPSHandler, NoRedirect)
            opener.addheaders = []
            try:
                with opener.open(req, timeout=TIMEOUT) as resp:
                    res.update(status=resp.status, ctype=resp.headers.get("Content-Type", ""), location="", error="",
                               body=resp.read(max_body + 1)[:max_body])
            except urllib.error.HTTPError as e:
                res.update(status=e.code, location=e.headers.get("Location", ""), ctype=e.headers.get("Content-Type", ""),
                           error="", body=b"")
                try:
                    if e.code >= 400:
                        res["body"] = e.read(max_body + 1)[:max_body]
                except Exception:  # noqa: BLE001  a broken error body is not worth a failure
                    pass
            except Exception as e:  # noqa: BLE001  network failures are data: they become the site status
                res.update(status=0, error=error_kind(e), body=b"")
            transient = res["status"] >= 500 or res["error"] in ("timeout", "refused", "tls") or res["error"].startswith("error:")
            if not transient:
                break
        body = res.pop("body")
        meta_p.write_text(json.dumps(res))
        body_p.write_bytes(body)
        res["body"] = body
        return res


class Robots:
    """robots.txt per exact host, through the same Fetcher (so it is cached and rate limited)."""

    def __init__(self, fetcher):
        self.f = fetcher
        self.hosts = {}

    def state(self, url, key):
        """(parser or None, reason). parser None means robots could not be read or parsed: skip the page."""
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self.hosts:
            self.hosts[host] = self._load(host, key)
        return self.hosts[host]

    def _load(self, host, key):
        url = host + "/robots.txt"
        for _ in range(MAX_REDIRECTS + 1):  # robots.txt often redirects http to https or to www: same site only
            res = self.f.fetch(url, key, max_body=MAX_ROBOTS)
            if 300 <= res["status"] < 400 and res["location"]:
                url = urljoin(url, res["location"].strip())
                if site_key(url) != key:
                    return None, "robots_redirect_offsite"
                continue
            break
        status = res["status"]
        rp = robotparser.RobotFileParser()
        if status == 0:
            return None, "robots_unreachable:" + res["error"]
        if 300 <= status < 400:
            return None, f"robots_redirect_{status}"
        if status in (401, 403):
            rp.parse(["User-agent: *", "Disallow: /"])
            rp.modified()  # without this can_fetch() is always False
            return rp, "robots_forbidden"
        if 400 <= status < 500:  # no robots.txt: everything is allowed
            rp.parse([])
            rp.modified()
            return rp, ""
        if status != 200:
            return None, f"robots_http_{status}"
        text = res["body"].decode("utf-8", "replace")
        head = text.lstrip()[:200].lower()
        if head.startswith("<") or "<html" in head or "<!doctype" in head:
            return None, "robots_unparseable_html"
        rp.parse(text.splitlines())
        rp.modified()
        return rp, ""

    @staticmethod
    def delay_for(rp):
        d = rp.crawl_delay(USER_AGENT)
        return max(REQUEST_DELAY, float(d)) if d else REQUEST_DELAY


def decode(res):
    mt = re.search(r"charset=([\w\-]+)", res["ctype"], re.I)
    try:
        return res["body"].decode(mt.group(1) if mt else "utf-8", "replace")
    except LookupError:
        return res["body"].decode("utf-8", "replace")


def is_html(res):
    c = res["ctype"].lower()
    return not c or c.startswith(("text/html", "application/xhtml"))


def fetch_page(fetcher, robots, url, key, home_key):
    """Fetch one page obeying robots and following same-site redirects. Returns an outcome dict whose `kind` is
    ok | robots_blocked | robots_unreadable | crawl_delay | offsite | http_error | net_error | not_html."""
    for _ in range(MAX_REDIRECTS + 1):
        rp, why = robots.state(url, key)
        if rp is None and why.rsplit(":", 1)[-1] in ("dns", "refused"):
            return {"kind": "net_error", "url": url, "detail": why.rsplit(":", 1)[-1]}  # the host itself is gone
        if rp is None:
            return {"kind": "robots_unreadable", "url": url, "detail": why}
        if why == "robots_forbidden" or not rp.can_fetch(USER_AGENT, url):
            return {"kind": "robots_blocked", "url": url, "detail": why or "disallowed"}
        delay = robots.delay_for(rp)
        if delay > CRAWL_DELAY_MAX:
            return {"kind": "crawl_delay", "url": url, "detail": f"crawl-delay {delay:g}s"}
        res = fetcher.fetch(url, key, delay=delay)
        status = res["status"]
        if status == 0:
            return {"kind": "net_error", "url": url, "detail": res["error"]}
        if 300 <= status < 400 and res["location"]:
            nxt = urljoin(url, res["location"].strip())
            if urlsplit(nxt).scheme not in ("http", "https"):
                return {"kind": "http_error", "url": url, "status": status, "detail": "redirect to non-http"}
            if site_key(nxt) != home_key:
                return {"kind": "offsite", "url": url, "detail": site_key(nxt), "redirect_url": nxt}
            url = nxt
            continue
        if status != 200:
            return {"kind": "http_error", "url": url, "status": status, "detail": f"http_{status}"}
        if not is_html(res):
            return {"kind": "not_html", "url": url, "detail": res["ctype"][:60]}
        return {"kind": "ok", "url": url, "html": decode(res)}
    return {"kind": "http_error", "url": url, "status": 0, "detail": "too_many_redirects"}


# ---- parsing --------------------------------------------------------------------------------------
BLOCK_TAGS = {"p", "div", "li", "tr", "td", "th", "section", "article", "header", "footer", "nav", "ul", "ol", "table",
              "br", "aside", "main", "dd", "dt", "blockquote", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
CHROME = {"nav", "header", "footer", "aside"}
SKIP = {"script", "style", "noscript", "template", "svg"}


class PageParser(HTMLParser):
    """Visible text as blocks, links, meta tags and JSON-LD scripts. Scripts are never run, only read as data."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.links, self.meta, self.ld, self.ics, self.title_parts = [], [], {}, [], [], []
        self.buf, self.skip, self.chrome, self.heading = [], 0, 0, 0
        self.in_title, self.in_ld, self.ld_buf = False, False, []
        self.a_href, self.a_text, self.pending_dt = None, [], []
        self.title = ""

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if text and len(self.blocks) < MAX_BLOCKS:
            self.blocks.append({"kind": "h" if self.heading else "p", "text": text[:BLOCK_MAX], "chrome": self.chrome > 0,
                                "dt": self.pending_dt})
            self.pending_dt = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag in SKIP:
            self.skip += 1
            if tag == "script" and "ld+json" in a.get("type", "").lower():
                self.in_ld, self.ld_buf = True, []
            return
        if self.skip:
            return
        if tag in BLOCK_TAGS:
            self._flush()
        if tag in HEADINGS:
            self.heading += 1
        if tag in CHROME:
            self.chrome += 1
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key and "content" in a:
                self.meta.setdefault(key, a["content"].strip())
        elif tag == "time" and a.get("datetime"):
            self.pending_dt.append(a["datetime"].strip())
        elif tag == "a" and a.get("href"):
            href = a["href"].strip()
            self.a_href, self.a_text = href, []
            if re.search(r"\.ics(\?|$)|^webcal:", href, re.I):
                self.ics.append(href)

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            if tag == "script" and self.in_ld:
                self.ld.append("".join(self.ld_buf))
                self.in_ld = False
            return
        if self.skip:
            return
        if tag in BLOCK_TAGS:
            self._flush()
        if tag in HEADINGS:
            self.heading = max(0, self.heading - 1)
        if tag in CHROME:
            self.chrome = max(0, self.chrome - 1)
        if tag == "title":
            self.in_title = False
        elif tag == "a" and self.a_href is not None:
            self.links.append((self.a_href, re.sub(r"\s+", " ", "".join(self.a_text)).strip()))
            self.a_href = None

    def handle_data(self, data):
        if self.in_ld:
            self.ld_buf.append(data)
            return
        if self.skip:
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        self.buf.append(data)
        if self.a_href is not None:
            self.a_text.append(data)


def parse_page(html):
    p = PageParser()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001  malformed markup: keep what was parsed
        pass
    p._flush()
    p.title = re.sub(r"\s+", " ", "".join(p.title_parts)).strip()
    return p


def cap(text, n=SNIPPET_SHORT):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


# ---- link discovery and the crawl of one domain ---------------------------------------------------
def pick_links(home_url, links):
    """Up to PAGES_PER_DOMAIN - 1 same-domain pages, one per role in PAGE_KINDS order. No query strings, fragments,
    files, logins or search."""
    home_key = site_key(home_url)
    seen = {urlsplit(home_url)._replace(fragment="").geturl().rstrip("/")}
    cands = []
    for href, text in links:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "webcal:")):
            continue
        url = urljoin(home_url, href)
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or site_key(url) != home_key or parts.query:
            continue
        path = parts.path or "/"
        if Path(path).suffix.lower() in SKIP_EXT or SKIP_PATH_RE.search(path) or SKIP_PATH_RE.search(text or ""):
            continue
        clean = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
        if clean.rstrip("/") in seen:
            continue
        seen.add(clean.rstrip("/"))
        for rank, (role, rx) in enumerate(PAGE_KINDS):
            if rx.search(text or "") or rx.search(path):
                cands.append((rank, 0 if rx.search(text or "") else 1, path.count("/"), clean, role))
                break
    picked, roles = [], set()
    for _, _, _, url, role in sorted(cands):
        if role not in roles:
            picked.append((url, role))
            roles.add(role)
        if len(picked) >= PAGES_PER_DOMAIN - 1:
            break
    return picked


def crawl_host(fetcher, robots, host, start_url):
    """Crawl one domain: home plus up to 4 pages. Returns the status fields and the pages [(url, role, parsed)]."""
    out = {"host": host, "status": "", "detail": "", "final_url": "", "redirect_host": "", "pages": [], "skipped": []}
    home = fetch_page(fetcher, robots, start_url, host, host)
    kind = home["kind"]
    if kind == "ok":
        pg = parse_page(home["html"])
        text = " ".join(bk["text"] for bk in pg.blocks)
        out["final_url"] = home["url"]
        if PARKED_RE.search(pg.title + " " + text[:3000]) and len(text) < 1500:
            out.update(status="parked", detail="parked, for-sale or placeholder wording")
            return out
        out.update(status="live")
        out["pages"].append((home["url"], "home", pg))
        for url, role in pick_links(home["url"], pg.links):
            res = fetch_page(fetcher, robots, url, host, host)
            if res["kind"] == "ok":
                out["pages"].append((res["url"], role, parse_page(res["html"])))
            else:
                out["skipped"].append(f"{url} [{role}]: {res['kind']} {res.get('detail', '')}".strip())
        return out
    if kind == "offsite":
        out.update(status="redirected", detail="to another domain, not followed", redirect_host=home["detail"],
                   final_url=home.get("redirect_url", ""))
    elif kind in ("robots_blocked", "robots_unreadable", "crawl_delay"):
        out.update(status="robots_blocked", detail=f"{kind}: {home['detail']}")
    elif kind == "http_error":
        out.update(status="dead" if home.get("status") in (404, 410) else "other_failure", detail=home["detail"])
    elif kind == "net_error":
        out.update(status="dead" if home["detail"] in ("dns", "refused") else "other_failure", detail=home["detail"])
    else:
        out.update(status="other_failure", detail=f"{kind} {home['detail']}")
    return out


# ---- extraction -----------------------------------------------------------------------------------
def walk_ld(node, events, orgs):
    if isinstance(node, list):
        for n in node:
            walk_ld(n, events, orgs)
    elif isinstance(node, dict):
        types = node.get("@type", [])
        types = [types] if isinstance(types, str) else [str(t) for t in types]
        if any(t.endswith("Event") for t in types):
            events.append(node)
        elif any(re.search(r"Organization|LocalBusiness|NGO|Library|School|GovernmentOffice|Medical|Place|Store", t)
                 for t in types):
            orgs.append(node)
        for v in node.values():
            if isinstance(v, (dict, list)):
                walk_ld(v, events, orgs)


def ld_documents(parsed):
    events, orgs = [], []
    for raw in parsed.ld:
        try:
            walk_ld(json.loads(raw), events, orgs)
        except (ValueError, RecursionError):
            continue
    return events, orgs


def iso_date(value):
    mt = re.match(r"(\d{4})-(\d\d)-(\d\d)", str(value or ""))
    if not mt:
        return None
    try:
        return date(int(mt.group(1)), int(mt.group(2)), int(mt.group(3)))
    except ValueError:
        return None


def timing_of(full_dates, partial, recurring):
    """(timing, upcoming) from dates as stated; never guesses a missing year or date."""
    if full_dates:
        return ("upcoming", "yes") if max(full_dates) >= CRAWL_DATE else ("past", "no")
    if recurring:
        return "recurring", "unknown"
    if partial:
        return "partial_date", "unknown"
    return "undated", "unknown"


def text_dates(text):
    """(full dates, month-day strings with no year, all date strings as stated) found in a block."""
    full, partial, stated = [], [], []
    for mt in DATE_RE.finditer(text):
        mo = MONTH_NUM[mt.group("m").lower()[:3]]
        if mt.group("y"):
            try:
                full.append(date(int(mt.group("y")), mo, int(mt.group("d"))))
                stated.append(mt.group(0))
            except ValueError:
                pass
        else:
            partial.append(mt.group(0))
            stated.append(mt.group(0))
    for mt in NUMERIC_DATE_RE.finditer(text):
        y = int(mt.group("y"))
        y += 2000 if y < 100 else 0
        try:
            full.append(date(y, int(mt.group("m")), int(mt.group("d"))))
            stated.append(mt.group(0))
        except ValueError:
            pass
    for mt in ISO_DATE_RE.finditer(text):
        d = iso_date(mt.group(0))
        if d:
            full.append(d)
            stated.append(mt.group(0))
    return full, partial, stated


def clean_title(text):
    """Short title without a trailing 'with <Person Name>' (no staff names)."""
    return cap(PERSON_TAIL_RE.sub("", text), 120)


def service_types_in(text):
    return [t for t in SERVICE_REGEX if SERVICE_REGEX[t].search(text) or (t in EVENT_TYPE_REGEX and EVENT_TYPE_REGEX[t].search(text))]


def weak_title(text):
    """A title that is only a date, a 'When:' label or a generic page heading."""
    rest = WEEKDAY_RE.sub("", DATE_RE.sub("", NUMERIC_DATE_RE.sub("", ISO_DATE_RE.sub("", text))))
    return bool(WEAK_TITLE_RE.search(text.strip())) or len(re.findall(r"[A-Za-z]{2,}", rest)) < 2


def structured_events(parsed, url):
    """(event rows from JSON-LD, organization nodes from JSON-LD)."""
    events, orgs = ld_documents(parsed)
    rows = []
    for ev in events:
        if any(s in str(ev.get("eventStatus", "")) for s in EVENT_STATUS_SKIP):
            continue
        name = ev.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        start, end = iso_date(ev.get("startDate")), iso_date(ev.get("endDate"))
        sched = ev.get("eventSchedule")
        sched = sched[0] if isinstance(sched, list) and sched else sched
        recurring = bool(isinstance(sched, dict) and (sched.get("repeatFrequency") or sched.get("byDay")))
        timing, upcoming = timing_of([d for d in (start, end) if d], False, recurring)
        loc = ev.get("location")
        loc = loc[0] if isinstance(loc, list) and loc else loc
        loc_text = ""
        if isinstance(loc, dict):
            addr = loc.get("address")
            addr = addr.get("streetAddress", "") if isinstance(addr, dict) else (addr or "")
            loc_text = ", ".join(x for x in (str(loc.get("name", "")), str(addr)) if x)
        elif isinstance(loc, str):
            loc_text = loc
        stated = " to ".join(str(x) for x in (ev.get("startDate"), ev.get("endDate")) if x)
        if recurring:
            stated = cap(stated + " " + json.dumps({k: sched[k] for k in ("repeatFrequency", "byDay", "startTime")
                                                    if k in sched}), 120)
        rows.append({"kind": "event", "title": clean_title(name), "date_text": stated, "timing": timing,
                     "upcoming": upcoming, "location_text": cap(loc_text, 120), "source_url": url,
                     "extracted": "structured", "detail": "json-ld", "context": name})
    return rows, orgs


def text_events(parsed, url, role):
    """Events and recurring activities stated in page text: a block with a date or a recurrence and an event word."""
    rows, heading, since, prev = [], "", 99, ""
    for bk in parsed.blocks:
        since += 1
        text, before = bk["text"], prev
        prev = text if not bk["chrome"] else prev
        if bk["kind"] == "h":
            heading, since = text, 0
            continue
        if bk["chrome"] or len(text) > 400 or NOT_EVENT_RE.search(text):
            continue
        full, partial, stated = text_dates(text)
        tagged = [(dt, iso_date(dt)) for dt in bk["dt"] if iso_date(dt)]
        if tagged:  # a <time datetime> is the page's own machine-readable date: use it instead of the text's
            full, partial, stated = [d for _, d in tagged], [], [dt for dt, _ in tagged]
        recurring = bool(RECUR_RE.search(text))
        if not (full or partial or recurring):
            continue
        context = (heading if since <= 2 else "") + " " + text
        if not EVENT_WORD_RE.search(context) and not (role == "events" and (full or partial)):
            continue
        if HOURS_RE.search(text) and HOURS_WORD_RE.search(text) and not EVENT_WORD_RE.search(text):
            continue  # opening hours, not an event
        timing, upcoming = timing_of(full, partial, recurring)
        title = heading if since <= 2 and heading else text
        if weak_title(title):  # take the line before (usually the name), else drop: a date alone is not an event
            title = before if before and len(before) <= 100 and not weak_title(before) else ""
            if not title:
                continue
        stated_text = "; ".join(dict.fromkeys(stated)) or RECUR_RE.search(text).group(0)
        tm = TIME_RE.search(text)
        if tm and tm.group(0) not in stated_text:
            stated_text += " " + tm.group(0)
        lm = LOCATION_RE.search(text)
        rows.append({"kind": "event", "title": clean_title(title), "date_text": cap(stated_text, 120), "timing": timing,
                     "upcoming": upcoming, "location_text": cap(lm.group(1), 120) if lm else "", "source_url": url,
                     "extracted": "text", "detail": "time-tag" if bk["dt"] else "text", "context": context})
    return rows


def text_programs(parsed, url):
    """Program names from headings on a services or programs page; always undated."""
    rows = []
    for bk in parsed.blocks:
        t = bk["text"]
        if bk["kind"] != "h" or bk["chrome"] or not 4 <= len(t) <= 80 or GENERIC_HEADINGS.match(t) or t.isdigit():
            continue
        rows.append({"kind": "program", "title": clean_title(t), "date_text": "", "timing": "undated", "upcoming": "unknown",
                     "location_text": "", "source_url": url, "extracted": "text", "detail": "heading on services page",
                     "context": t})
    return rows


def names_place(blob, name, house_number, street):
    """True when text gives the place's address (number then street word) or its full name."""
    blob = blob.lower()
    num = (re.match(r"\d+", (house_number or "").strip()) or [""])[0]  # "104-106" -> "104"
    words = [w for w in re.findall(r"[a-z]+|\d+(?:st|nd|rd|th)", (street or "").lower())
             if w not in ("north", "south", "east", "west", "n", "s", "e", "w")]
    if num and words and re.search(rf"\b{num}\s+(?:[nsew]\.?\s+|north\s+|south\s+|east\s+|west\s+)?{re.escape(words[0])}", blob):
        return True
    nm = re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).strip()
    return len(nm.split()) >= 2 and nm in re.sub(r"[^a-z0-9 ]", "", blob)


def first_hit(pages, rx, skip=None):
    """(snippet, url) of the first block matching rx, page content before navigation and footers."""
    chrome_hit = ("", "")
    for url, _, pg in pages:
        for bk in pg.blocks:
            t = bk["text"]
            if rx.search(t) and not (skip and skip.search(t)):
                if not bk["chrome"]:
                    return cap(t), url
                chrome_hit = chrome_hit if chrome_hit[0] else (cap(t), url)
    return chrome_hit


def pick_description(pages):
    """(text, origin, url): meta or og description, else the first substantive paragraph; at most SNIPPET_MAX."""
    for url, _, pg in pages:
        for key in ("description", "og:description", "twitter:description"):
            d = re.sub(r"\s+", " ", pg.meta.get(key, "")).strip()
            if len(d) >= 40 and not re.search(r"just another|wordpress site|lorem ipsum", d, re.I):
                return cap(d, SNIPPET_MAX), key, url
        for bk in pg.blocks:
            t = bk["text"]
            if (bk["kind"] == "p" and not bk["chrome"] and len(t.split()) >= 12 and len(t) >= 80
                    and not re.search(r"cookie|privacy|javascript|©|all rights reserved|subscribe", t, re.I)):
                return cap(t, SNIPPET_MAX), "paragraph", url
    return "", "", ""


def pick_hours(pages, ld_orgs):
    for url, org in ld_orgs:
        spec = org.get("openingHours")
        if isinstance(spec, list):
            spec = "; ".join(str(s) for s in spec)
        items = org.get("openingHoursSpecification")
        if not spec and isinstance(items, (list, dict)):
            items = items if isinstance(items, list) else [items]
            spec = "; ".join(f"{i.get('dayOfWeek', '')} {i.get('opens', '')}-{i.get('closes', '')}" for i in items
                             if isinstance(i, dict))
        if spec:
            return cap(str(spec)), url
    for url, role, pg in sorted(pages, key=lambda x: x[1] != "hours_contact"):
        for bk in pg.blocks:
            t = bk["text"]
            if (HOURS_RE.search(t) and len(t) <= 300 and not NOT_EVENT_RE.search(t)
                    and (HOURS_WORD_RE.search(t) or role == "hours_contact")
                    and not (EVENT_WORD_RE.search(t) and not re.search(r"hours|office", t, re.I))):
                return cap(t), url
    return "", ""


def own_mailbox(email, host):
    local, _, dom = email.lower().partition("@")
    return local in GENERIC_MAILBOXES and (dom == host or dom.endswith("." + host) or host.endswith("." + dom))


def pick_contacts(pages, host):
    """Organization-level phones (not in blocks that mention staff) and generic role mailboxes on the site's own domain."""
    phones, emails, src = [], [], ""
    for url, _, pg in sorted(pages, key=lambda x: x[1] != "hours_contact"):
        for bk in pg.blocks:
            t = bk["text"]
            if STAFF_RE.search(t) or len(t) > 250:
                continue
            for mt in PHONE_RE.finditer(t):
                num = f"({mt.group(1)}) {mt.group(2)}-{mt.group(3)}"
                if num not in phones and len(phones) < 2:
                    phones.append(num)
                    src = src or url
            for em in EMAIL_RE.findall(t):
                if own_mailbox(em, host) and em.lower() not in emails and len(emails) < 2:
                    emails.append(em.lower())
                    src = src or url
        for href, _ in pg.links:
            if href.lower().startswith("mailto:"):
                em = href[7:].split("?")[0].strip().lower()
                if own_mailbox(em, host) and em not in emails and len(emails) < 2:
                    emails.append(em)
                    src = src or url
    return phones, emails, src


STREET_RE = re.compile(r"\b\d{1,5}\s+(?:[NSEW]\.?\s+)?[A-Z0-9][\w.'\-]*(?:\s+[A-Z0-9][\w.'\-]*){0,3}\s+(?:Street|St\.?|Avenue|"
                       r"Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Place|Pl\.?|Drive|Dr\.?|Broadway|Parkway|Lane|Ln\.?|Plaza|"
                       r"Court|Ct\.?)\b[^.]{0,40}?(?:NY|New York)\b[^.]{0,12}\d{5}")


def pick_addresses(pages, ld_orgs):
    out = []
    for _, org in ld_orgs:
        addr = org.get("address")
        if isinstance(addr, dict) and addr.get("streetAddress"):
            out.append(cap(f"{addr.get('streetAddress')} {addr.get('addressLocality', '')} {addr.get('postalCode', '')}", 120))
    for _, _, pg in pages:
        for bk in pg.blocks:
            mt = STREET_RE.search(bk["text"])
            if mt and cap(mt.group(0), 120) not in out:
                out.append(cap(mt.group(0), 120))
    return out[:3]


def analyse_host(crawl, targets):
    """Domain-level extraction from the crawled pages, plus per-target flags for attribution."""
    pages, host = crawl["pages"], crawl["host"]
    res = {"events": [], "targets": {}}
    if not pages:
        return res
    struct_events, ld_orgs = [], []
    for url, _, pg in pages:
        evs, orgs = structured_events(pg, url)
        struct_events += evs
        ld_orgs += [(url, o) for o in orgs]
    res["description"] = pick_description(pages)
    strong, weak = defaultdict(set), defaultdict(set)
    for _, _, pg in pages:
        headline = [pg.title, pg.meta.get("description", ""), pg.meta.get("og:description", "")]
        headline += [bk["text"] for bk in pg.blocks if bk["kind"] == "h"]
        for t, rx in SERVICE_REGEX.items():
            for text in headline:
                strong[t].update(x.group(0).lower() for x in rx.finditer(text))
            for bk in pg.blocks:
                weak[t].update(x.group(0).lower() for x in rx.finditer(bk["text"]))
    res["services"] = {t: sorted(weak[t] | strong[t])[:4] for t in SERVICE_REGEX
                       if strong[t] or len(weak[t] | strong[t]) >= STRONG_MIN_KEYWORDS}
    res["hours"] = pick_hours(pages, ld_orgs)
    res["phones"], res["emails"], res["contact_url"] = pick_contacts(pages, host)
    for url, org in ld_orgs:
        mt = PHONE_RE.search(str(org.get("telephone", "")))
        if mt and not res["phones"]:
            res["phones"] = [f"({mt.group(1)}) {mt.group(2)}-{mt.group(3)}"]
            res["contact_url"] = res["contact_url"] or url
    res["addresses"] = pick_addresses(pages, ld_orgs)
    lang_blocks = [(bk["text"], url) for url, _, pg in pages for bk in pg.blocks
                   if len(bk["text"]) <= 300 and LANGUAGE_RE.search(bk["text"]) and LANGUAGE_CUE_RE.search(bk["text"])
                   and not LANGUAGE_WIDGET_RE.search(bk["text"])]
    res["languages"] = (sorted({x for t, _ in lang_blocks for x in LANGUAGE_RE.findall(t)}),
                        lang_blocks[0][1] if lang_blocks else "")
    res["eligibility"] = first_hit(pages, ELIGIBILITY_RE, skip=BOILERPLATE_RE)
    res["referral"] = first_hit(pages, REFERRAL_RE, skip=BOILERPLATE_RE)
    res["closure"] = first_hit(pages, CLOSURE_RE, skip=CLOSURE_SKIP_RE)
    res["ics"] = sorted({urljoin(url, h) for url, _, pg in pages for h in pg.ics})[:3]
    events, programs = list(struct_events), []
    for url, role, pg in pages:
        events += text_events(pg, url, role)
        if role == "services_programs":
            programs += text_programs(pg, url)
    seen, rows = set(), []
    for ev in events + programs:
        k = (ev["kind"], ev["title"].lower(), ev["date_text"].lower())
        if k not in seen and ev["title"]:
            seen.add(k)
            rows.append(ev)
    rows = ([r for r in rows if r["kind"] == "event"][:EVENTS_PER_DOMAIN]
            + [r for r in rows if r["kind"] == "program"][:PROGRAMS_PER_DOMAIN])
    for ev in rows:
        types = service_types_in(ev["title"] + " " + ev.pop("context"))
        ev["service_types"] = "; ".join(types)
        ev["relevance"] = "service_type" if types else "general"
    res["events"] = rows
    blob = "\n".join([bk["text"] for _, _, pg in pages for bk in pg.blocks] + res["addresses"])
    for t in targets:
        res["targets"][(t["group"], t["source"], t["source_id"])] = {
            "named": names_place(blob, t["name"], t["house_number"], t["street"]),
            "address_on_site": names_place(blob, "", t["house_number"], t["street"])}
    return res


# ---- output rows ----------------------------------------------------------------------------------
def place_label(t):
    return f"{t['group']}:{t['source']}:{t['source_id']}"


def build_rows(host, crawl, an, targets, shared, date_s):
    """(pilot rows for the targets of one domain, event rows for the domain)."""
    events = []
    for ev in an.get("events", []):
        attributed = (not shared) or any(
            names_place(ev["title"] + " " + ev["location_text"], t["name"], t["house_number"], t["street"]) for t in targets)
        events.append({"group": "+".join(sorted({t["group"] for t in targets})),
                       "place_keys": ";".join(place_label(t) for t in targets[:5]), "domain": host, "kind": ev["kind"],
                       "title": ev["title"], "date_text": ev["date_text"], "timing": ev["timing"],
                       "upcoming": ev["upcoming"], "location_text": ev["location_text"], "source_url": ev["source_url"],
                       "extracted": ev["extracted"], "extraction_detail": ev["detail"],
                       "attribution": "place" if attributed else "shared_domain_unattributed",
                       "service_types": ev["service_types"], "relevance": ev["relevance"], "crawl_date": date_s})
    pilot = []
    for t in targets:
        flags = an.get("targets", {}).get((t["group"], t["source"], t["source_id"]),
                                          {"named": False, "address_on_site": False})
        withheld = []
        ok_loc = (not shared) or flags["named"]
        hours, hours_url = an.get("hours", ("", ""))
        if hours and not ok_loc:
            hours, hours_url = "", ""
            withheld.append("hours")
        if shared:
            mine = [e for e in events if names_place(e["title"] + " " + e["location_text"], t["name"], t["house_number"],
                                                     t["street"])]
            if len(mine) < len(events):
                withheld.append("events")
        else:
            mine = events
        found = an.get("services", {})
        langs, langs_url = an.get("languages", ([], ""))
        addrs = an.get("addresses", [])
        check = ""
        if t["group"] == "B" and crawl["status"] == "live":
            check = "found" if flags["address_on_site"] else ("different_address_listed" if addrs else "no_address_on_site")
        desc = an.get("description", ("", "", ""))
        elig, elig_url = an.get("eligibility", ("", ""))
        ref, ref_url = an.get("referral", ("", ""))
        clo, clo_url = an.get("closure", ("", ""))
        pilot.append({
            "group": t["group"], "source": t["source"], "source_id": t["source_id"], "matched_osm_id": t["matched_osm_id"],
            "name": t["name"], "borough": t["borough"], "website": t["website"], "domain": host, "crawl_date": date_s,
            "site_status": crawl["status"], "status_detail": crawl["detail"], "final_url": crawl["final_url"],
            "redirect_host": crawl["redirect_host"], "shared_domain": str(shared),
            "domain_place_count": t["domain_place_count"], "pages_fetched": len(crawl["pages"]),
            "pages_skipped": " | ".join(crawl["skipped"])[:600], "description": desc[0], "description_origin": desc[1],
            "description_url": desc[2], "service_types_found": "; ".join(sorted(found)),
            "service_evidence": "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(found.items())),
            "site_supports_service": str(bool(found)) if crawl["status"] == "live" else "", "hours": hours,
            "hours_url": hours_url, "phone": "; ".join(an.get("phones", [])), "email": "; ".join(an.get("emails", [])),
            "contact_url": an.get("contact_url", ""), "site_address": " | ".join(addrs), "address_check": check,
            "languages": "; ".join(langs), "languages_url": langs_url, "eligibility": elig, "eligibility_url": elig_url,
            "referral": ref, "referral_url": ref_url, "closure_wording": clo, "closure_url": clo_url,
            "ics_links": " ".join(an.get("ics", [])),
            "n_events": sum(e["kind"] == "event" for e in mine),
            "n_upcoming": sum(e["kind"] == "event" and e["upcoming"] == "yes" for e in mine),
            "n_programs_undated": sum(e["kind"] == "program" for e in mine),
            "withheld_shared_domain": ";".join(withheld), "guide_service_types": t["guide_types"],
            "guide_has_description": t["guide_has_description"], "relevance_score": t["relevance_score"],
            "primary_type": t["primary_type"]})
    return pilot, events


def write_csv(path, fields, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def run_host(fetcher, robots, host, start_url, targets, date_s):
    crawl = crawl_host(fetcher, robots, host, start_url)
    shared = max(t["domain_place_count"] for t in targets) >= SHARED_DOMAIN_PLACES
    pilot, events = build_rows(host, crawl, analyse_host(crawl, targets), targets, shared, date_s)
    print(f"  {host}: {crawl['status']} {crawl['detail']}".rstrip(), file=sys.stderr)
    return pilot, events


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", help="new or empty directory (outside the repo) for raw downloads")
    ap.add_argument("--list", action="store_true", help="list targets and counts, make no requests")
    ap.add_argument("--limit", type=int, help="crawl only the first N domains")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = ap.parse_args()
    if not args.list and not args.cache:
        ap.error("--cache is required unless --list")
    targets, counts = load_targets()
    hosts = group_by_host(targets)
    print(f"targets: A {sum(t['group'] == 'A' for t in targets)}, B {sum(t['group'] == 'B' for t in targets)}; "
          f"domains {len(hosts)}; excluded abuse or violence services (counted, not listed): "
          f"A {counts['excluded_A']}, B {counts['excluded_B']}; B without website {counts['B_no_website']}",
          file=sys.stderr)
    if args.list:
        return
    fetcher = Fetcher(args.cache)
    robots = Robots(fetcher)
    date_s = CRAWL_DATE.isoformat()
    pilot, events = [], []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, MAX_WORKERS))) as ex:
        futs = [ex.submit(run_host, fetcher, robots, h, s, ts, date_s) for h, (s, ts) in list(hosts.items())[: args.limit]]
        for fu in futs:
            p, e = fu.result()
            pilot += p
            events += e
    pilot.sort(key=lambda r: (r["group"], r["source"], r["source_id"]))
    write_csv(PILOT_CSV, PILOT_FIELDS, pilot)
    write_csv(EVENTS_CSV, EVENT_FIELDS, events)
    print(f"requests made {fetcher.requests}, served from cache {fetcher.cached}; {len(pilot)} places, "
          f"{len(events)} events/programs; status {dict(Counter(r['site_status'] for r in pilot))}", file=sys.stderr)


if __name__ == "__main__":
    main()
