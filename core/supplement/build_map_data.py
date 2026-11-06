# /// script
# requires-python = ">=3.10"
# ///
"""Data for the local review map (map.html): what each source could add to the guide, by service area.

    python3 core/supplement/build_map_data.py

Run it after review_recommendations.py. Writes data/supplement/map_data.geojson, which is ignored by git because it
holds NYC Open Data rows and crawled page text that we may not republish. Nothing here feeds the front end.

Each mapped guide row and each place awaiting review becomes one point, with a status:
  matched  a source lists the same site (SITE match classes), or the guide's own website had something to add
  guide    mapped in the guide, and nothing matched it
  review   not in the guide and pending in a review queue, so a person decides whether it belongs

For a matched row, `adds` is only what the guide lacks: a phone or website it leaves blank, opening hours (the guide
has none), and service types it doesn't list. A match that adds nothing still confirms the site.

Each point also carries what its card shows: the guide's description and labels, or for a review place, what the crawl
of its own website found (unverified, and skipped when the site is shared or redirects elsewhere, as it may describe
someone else).

The output's top-level `events` lists events found on the websites of drawn places, one entry per event, from the saved
crawl output: nothing here fetches a page. Events are unverified. Upcoming ones that match no service stay in the data as
"Not classified" for the map to hide by default, since the service check misses real programs, but they don't count as
something a website adds to the guide. A recurring event has no date to check, so it needs a service match to appear.

Left out on purpose:
- Survivor services and shelters awaiting review (local_reason=sensitive). Reviewers use the local queue for these.
- ENDGBV listings with no coordinates: those are the confidential addresses, so even a match to a guide row could
  link a program to a place.
- Places with no coordinates, which can't be drawn. meta in the output counts both exclusions for review rows.
"""

import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_supplement as b  # noqa: E402
import crawl_sites as c  # noqa: E402
import match_nypl as m  # noqa: E402
import review_recommendations as r  # noqa: E402

OUT = m.SUPP_DIR / "map_data.geojson"
EVENTS_CSV = m.SUPP_DIR / "crawl_events.csv"
WEBSITE_PILOT = "website_pilot"
MAX_DESCRIPTION = 300
NOT_CLASSIFIED = "Not classified"
# A page heading, and rows of a calendar widget: the citywide school calendar, whose text puts each date beside the wrong item.
NOT_AN_EVENT = re.compile(r"^\W*upcoming events\W*$|^\W*add to my calendar\b", re.I)
EARLIEST_START_HOUR = 6  # A site's structured data says ONPOINT opens 1:00 AM. An earlier start is a bad clock, so only the date shows.
DATE_IN_TEXT = re.compile(r"(\d{4})-(\d\d)-(\d\d)|\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})")
TIME_ISO = re.compile(r"T(\d\d):(\d\d)")
TIME_TEXT = re.compile(r"\b(\d{1,2})(?::(\d\d))?\s*([ap])\.?m?\b\.?", re.I)
MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
GUIDE_FLAGS = {"spanish_speaking": "Spanish spoken", "works_with_currently_incarcerated": "Works with people in custody",
               "ati_program": "Alternative to incarceration", "know_your_rights_content": "Know your rights"}
SOURCE_LABELS = {"osm": "OpenStreetMap", "facdb": "NYC Facilities Database", "irs_eo": "IRS nonprofit filings", "omh": "NYS Office of Mental Health",
                 "doh_childcare": "NYC licensed child care", "dycd": "NYC youth & community programs", "endgbv": "NYC gender-based violence services",
                 "workforce1": "Workforce1 career centers", "hrsa": "HRSA health centers", "cms_otp": "CMS opioid treatment programs",
                 WEBSITE_PILOT: "Guide's own website (pilot)"}


def guide_address(g):
    return " ".join(x for x in (g["street_number"], g["street"], g["city"], g["zip_code"]) if x)


def additions(guide, place):
    """What this listing has that the guide row doesn't."""
    have = set(r.parse_types(guide["service_types_all"]))
    adds = {}
    if place["phone"] and not guide["phone_number"]:
        adds["phone"] = place["phone"]
    if place["website"] and not guide["website"]:
        adds["website"] = place["website"]
    if place["opening_hours"]:
        adds["hours"] = place["opening_hours"]
    services = [t for t in r.split_types(place["proposed_service_types"]) if t not in have]
    if services:
        adds["services"] = services
    return adds


def source_matches(matches, places):
    """{guide id: [enrichment record]} from best site-level matches. Confidential ENDGBV listings never link to a site."""
    out = defaultdict(list)
    for x in matches:
        if x["match_class"] not in b.SITE or x["is_best"] != "True":
            continue
        place = places.get((x["source"], x["source_id"]))
        if place is None or (x["source"] == "endgbv" and not place["lat"]):
            continue
        out[x["nypl_id"]].append((x, place))
    return out


def crawl_additions(row, guide, events):
    """What the crawl of the guide's own website found. Unverified, so the map labels it as a pilot.
    Eligibility and referral are left out: on a read of the pilot they are often a stray sentence with the keyword."""
    adds = {}
    if row["description"] and row["guide_has_description"] != "True":
        adds["description"] = row["description"][:MAX_DESCRIPTION]
    if row["phone"] and not guide["phone_number"]:
        adds["phone"] = row["phone"]
    if re.search(r"\d", row["hours"]):  # the extractor also yields empty day lists such as ", , ,"
        adds["hours"] = row["hours"][:MAX_DESCRIPTION]
    if row["languages"]:
        adds["languages"] = row["languages"]
    if events:
        adds["events"] = events
    return adds


def guide_labels(g):
    only = r.parse_types(g["restricted_audiences"])
    focus = [a for a in r.parse_types(g["focus_audiences"]) if a not in only]
    return [f"{a} only" for a in only] + [f"Focus: {a}" for a in focus] + [label for col, label in GUIDE_FLAGS.items() if g[col] == "t"]


def site_details(row):
    """What the crawl found on a review place's own website, for its card."""
    if not row or row["shared_domain"] == "True" or row["redirect_host"]:
        return {}
    found = {"description": row["description"][:MAX_DESCRIPTION], "languages": row["languages"], "hours": row["hours"][:MAX_DESCRIPTION] if re.search(r"\d", row["hours"]) else ""}
    return {"site_url": row["description_url"] or row["final_url"], **found} if any(found.values()) else {}


def dates_in(text):
    out = []
    for x in DATE_IN_TEXT.finditer(text or ""):
        month = MONTHS.get(x[4][:3].lower()) if x[4] else int(x[2])
        try:
            out.append(date(int(x[1] or x[6]), month, int(x[3] or x[5])) if month else None)
        except ValueError:
            continue
    return [d for d in out if d]


def time_in(text):
    """Start time in the text as '6:00 PM', or blank."""
    iso, plain = TIME_ISO.search(text), TIME_TEXT.search(text)
    if iso:
        hour, minute = int(iso[1]), iso[2]
    elif plain:
        hour, minute = int(plain[1]) % 12 + (12 if plain[3].lower() == "p" else 0), plain[2] or "00"
    else:
        return ""
    if hour < EARLIEST_START_HOUR:
        return ""
    return f"{hour % 12 or 12}:{minute} {'AM' if hour < 12 else 'PM'}"


def event_when(text, crawled):
    """-> (ISO date of the next occurrence on or after the crawl, label to show). Unparsed text shows as written."""
    dates = dates_in(text)
    ahead = [d for d in dates if d >= crawled]
    if not ahead:
        return "", text
    start = ahead[0]
    label = f"{start:%b} {start.day}, {start.year}"
    clock = time_in(text) if len(set(dates)) == 1 else ""  # with several dates, a time could belong to any of them
    return start.isoformat(), f"{label}, {clock}" if clock else label


def clean_events(event_rows):
    """Events attributed to one place's own site, with readable titles and sortable dates. Titles are re-checked here, so
    new keywords apply to the saved crawl output without fetching anything."""
    out = []
    for e in event_rows:
        title = html.unescape(e["title"]).strip()
        types = r.split_types(e["service_types"]) or c.service_types_in(title)
        recurring = e["timing"] == "recurring"
        if e["attribution"] != "place" or NOT_AN_EVENT.match(title) or not (e["upcoming"] == "yes" or (recurring and types)):
            continue
        day, when = ("", f"Recurring: {e['date_text']}") if recurring else event_when(e["date_text"], date.fromisoformat(e["crawl_date"]))
        out.append({"title": title, "date": day, "when": when, "url": e["source_url"], "domains": types or [NOT_CLASSIFIED],
                    "matches_service": bool(types), "keys": e["place_keys"].split(";")})
    return out


def upcoming_events(events):
    """{guide id: events} for events on that guide row's own site that match a service."""
    out = defaultdict(list)
    for e in events:
        if e["matches_service"]:
            for key in e["keys"]:
                if key.startswith("B:nypl_guide:"):
                    out[key.rsplit(":", 1)[1]].append({"title": e["title"], "when": e["when"], "url": e["url"]})
    return out


def start_minutes(when):
    """Minutes past midnight in a label from event_when. No time sorts first in its day, as the event may run all day."""
    t = TIME_TEXT.search(when)
    return (int(t[1]) % 12 + (12 if t[3].lower() == "p" else 0)) * 60 + int(t[2] or 0) if t else -1


def events_at_places(events, owners):
    """One entry per event, soonest first, undated last. An event at no drawn place stays out, so hiding a place hides its events."""
    out = []
    for e in events:
        places = sorted({owners[k] for k in e["keys"] if k in owners})
        if places:
            out.append({k: e[k] for k in ("title", "date", "when", "url", "domains")} | {"places": places})
    return sorted(out, key=lambda e: (not e["date"], e["date"], start_minutes(e["when"]), e["title"]))


def guide_feature(g, found, crawl, events):
    enrich = []
    for x, place in found.get(g["id"], []):
        enrich.append({"source": x["source"], "match": x["match_class"], "listing": place["name"], "url": place["url"], "adds": additions(g, place)})
    site = crawl.get(g["id"])
    if site:
        adds = crawl_additions(site, g, events.get(g["id"], []))
        if adds:
            enrich.append({"source": WEBSITE_PILOT, "match": "guide_website", "listing": "", "url": site["final_url"], "adds": adds})
    types = r.parse_types(g["service_types_all"])
    extra = sorted({t for e in enrich for t in e["adds"].get("services", ())} - set(types))
    props = {"status": "matched" if enrich else "guide", "name": g["organization_name"], "address": guide_address(g), "borough": r.normal_borough(g["borough"]),
             "phone": g["phone_number"], "website": g["website"], "guide_types": types, "domains": types + extra or [NOT_CLASSIFIED],
             "sources": sorted({e["source"] for e in enrich}), "enrich": enrich, "page": g["pdf_guide_page"],
             "description": g["description"], "labels": guide_labels(g)}
    return point(g["latitude"], g["longitude"], props)


def review_feature(q, place, site=None):
    types = r.split_types(q["proposed_service_types"])
    props = {"status": "review", "name": q["name"], "address": q["address"], "borough": q["borough"], "phone": q["phone"], "website": q["website"],
             "domains": types or [NOT_CLASSIFIED], "sources": [s for s in q["sources"].split(";") if s], "priority": q["priority"],
             "gaps": r.split_types(q["service_gaps"]), "score": q["relevance_score"], "signals": q["relevance_signals"],
             "m_to_guide": q["m_to_nearest_guide_site"], "listings": q["listings"], "url": q["url"], "local_reason": q["local_reason"], "osm_hours": place["opening_hours"], **site_details(site)}
    return point(place["lat"], place["lon"], props)


def point(lat, lon, props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(float(lon), 6), round(float(lat), 6)]}, "properties": props}


def build(nypl, places, matches, queue, crawl_rows=(), event_rows=()):
    """-> GeoJSON dict. `places` is {(source, source_id): supplement row}; `queue` is the rows of both review queues."""
    found = source_matches(matches, places)
    crawl = {x["source_id"]: x for x in crawl_rows if x["group"] == "B"}
    crawl_review = {f"{x['source']}:{x['source_id']}": x for x in crawl_rows if x["group"] == "A"}
    events = clean_events(event_rows)
    by_guide = upcoming_events(events)
    features, owners = [], {}
    for g in nypl:
        if g["row_type"] == "mapped" and g["latitude"]:
            owners[f"B:nypl_guide:{g['id']}"] = len(features)
            features.append(guide_feature(g, found, crawl, by_guide))
    left_out = Counter()
    for q in queue:
        if q["hitl_review"] != "pending":
            left_out["already_judged"] += 1
        elif q["local_reason"] == "sensitive":
            left_out["sensitive"] += 1
        elif not places[(q["source"], q["source_id"])]["lat"]:
            left_out["no_location"] += 1
        else:
            owners.update({f"A:{k}": len(features) for k in q["member_keys"].split("|") if k})
            site = next((crawl_review[k] for k in q["member_keys"].split("|") if k in crawl_review), None)
            features.append(review_feature(q, places[(q["source"], q["source_id"])], site))
    for i, f in enumerate(features):
        f["properties"]["id"] = i
    crawled = max((e["crawl_date"] for e in event_rows), default="")
    meta = {"source_labels": SOURCE_LABELS, "left_out": dict(left_out), "catchment_m": r.CATCHMENT_M, "crawl_date": crawled}
    return {"type": "FeatureCollection", "meta": meta, "features": features, "events": events_at_places(events, owners)}


def main():
    nypl = m.read(m.NYPL_CSV)
    places = {(x["source"], x["source_id"]): x for x in m.read(r.SUPPLEMENT_CSV)}
    matches = [x for s in b.SOURCES if (m.SUPP_DIR / f"matches_{s}.csv").exists() for x in m.read(m.SUPP_DIR / f"matches_{s}.csv")]
    queue = [x for path in (r.QUEUE_CSV, r.QUEUE_LOCAL_CSV) for x in m.read(path)]
    crawl_rows = m.read(r.CRAWL_CSV) if r.CRAWL_CSV.exists() else []
    event_rows = m.read(EVENTS_CSV) if EVENTS_CSV.exists() else []
    data = build(nypl, places, matches, queue, crawl_rows, event_rows)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(data['features'])} points -> {OUT.name}: {dict(Counter(f['properties']['status'] for f in data['features']))}; {len(data['events'])} events; left out {data['meta']['left_out']}")
    table = Counter()
    for f in data["features"]:
        for e in f["properties"].get("enrich", ()):
            table[e["source"], "matched"] += 1
            table[e["source"], "adds"] += bool(e["adds"])
        if f["properties"]["status"] == "review":
            for s in f["properties"]["sources"]:
                table[s, "review"] += 1
    for s in SOURCE_LABELS:
        print(f"  {s:15} matched {table[s, 'matched']:4}  adds {table[s, 'adds']:4}  review {table[s, 'review']:4}")


if __name__ == "__main__":
    main()
