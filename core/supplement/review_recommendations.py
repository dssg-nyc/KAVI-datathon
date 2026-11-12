# /// script
# requires-python = ">=3.10"
# ///
"""The human-review list: pending supplementary places, one row per real-world place, sparse areas first.

Reads data/supplement/supplement_all.csv (build_supplement.py), data/kavi_resources.csv and, when present,
data/supplement/crawl_pilot.csv. Nothing here feeds the front end.

    python3 core/supplement/review_recommendations.py           write the review files
    python3 core/supplement/review_recommendations.py --eval    also write ranker_eval.csv (slower, rebuilds links)

Writes, in data/supplement/:
  review_queue.csv        committed. Places whose data we may republish (COMMITTABLE_SOURCES), none sensitive.
  review_queue_local.csv  ignored. Column local_reason says why each row is here: sensitive (survivor services and
                          shelters), private_practice (may name a person), or nyc_open_data_terms (not yet read).
  guide_checks.csv        committed. Guide rows whose own website has gone or moved, shows another address or closure
                          wording, or lists details the guide lacks (field names and a link, no page text).
                          These are prompts to check the guide, not corrections, and hold no page text.
  ranker_eval.csv         ignored, aggregate numbers for the notebook.

Reviewers fill hitl_review and review_note in the queue files. A rerun of this script or of build_supplement.py
keeps them. A verdict on one row applies to every source listing of that place (member_keys).

Priority, measured from the place to mapped guide sites, CATCHMENT_M being the notebook's walking range:
  1_no_guide_site_nearby   no guide site of any kind in range
  2_service_missing_nearby a guide site is in range, but none offers a service this place is proposed for
  3_already_covered        guide sites in range already offer the proposed services, or no service is proposed
  4_no_location            the source gives no coordinates, so a person has to locate it first
Within a priority, the boroughs with the fewest guide locations per resident come first, then the higher score.
Priority is where a place would help if it turned out to be relevant. It says nothing about whether it is.
"""

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_supplement as b  # noqa: E402
import match_nypl as m  # noqa: E402

SUPP = m.SUPP_DIR
SUPPLEMENT_CSV = SUPP / "supplement_all.csv"
CRAWL_CSV = SUPP / "crawl_pilot.csv"
QUEUE_CSV = SUPP / "review_queue.csv"
QUEUE_LOCAL_CSV = SUPP / "review_queue_local.csv"
GUIDE_CHECKS_CSV = SUPP / "guide_checks.csv"
EVAL_CSV = SUPP / "ranker_eval.csv"

CATCHMENT_M = 800
POPULATION = {"Manhattan": 1_694_251, "Brooklyn": 2_736_074, "The Bronx": 1_472_654, "Queens": 2_405_464, "Staten Island": 495_747}
COMMITTABLE_SOURCES = {"osm", "omh", "hrsa", "cms_otp"}  # terms read or stated; see fetch_sources.py
# Lists built around a service. FacDB and OSM are general, so sharing a place with them says little about relevance.
SERVICE_LABEL_SOURCES = {"omh", "hrsa", "cms_otp", "dycd", "endgbv", "workforce1", "doh_childcare"}
OSM_SENSITIVE_FOR = {"abused", "domestic_abuse", "victim"}
# HRSA's site-setting field has no shelter value, so a health centre inside a shelter shows only in its name.
SENSITIVE_NAME_RE = re.compile(r"domestic violence|\babuse\b|survivor|battered|refuge\b|\bshelters?\b|family residence|safe haven", re.I)
# Solo and small practices, often named after a person. A hospital with a psychiatry tag is not one.
PRIVATE_PRACTICE_TYPES = {"healthcare=psychotherapist", "healthcare=counselling", "office=therapist", "healthcare=doctor", "amenity=doctors"}
MIN_POSITIVES = 20  # fewer than this and an AUC is too unstable to report as a result

QUEUE_COLUMNS = ["hitl_review", "review_note", "priority", "borough", "name", "address", "phone", "website",
                 "proposed_service_types", "service_gaps", "m_to_nearest_guide_site", "relevance_score", "relevance_signals",
                 "sources", "listings", "source", "source_id", "member_keys", "url", "crawl_site_status", "licence", "local_reason"]
GUIDE_CHECK_COLUMNS = ["hitl_review", "review_note", "guide_id", "organization", "guide_address", "flag", "detail", "site_address",
                       "evidence_url", "crawl_date"]
EVAL_COLUMNS = ["label", "source", "places", "positives", "score_auc", "score_without_contact_auc", "baseline_auc", "enough_positives"]


def parse_types(text):
    return [t.strip().strip('"') for t in re.findall(r'"[^"]+"|[^,{}]+', text or "") if t.strip()]


def split_types(text):
    return [t.strip() for t in (text or "").split(";") if t.strip()]


def to_xy(lat, lon):
    return (lon + 74.0) * 84_400.0, (lat - 40.7) * 111_100.0


def nearest(xy, targets):
    return min((math.hypot(xy[0] - t[0], xy[1] - t[1]) for t in targets), default=math.inf)


def normal_borough(text):
    boro = (text or "").strip()
    return "The Bronx" if boro.lower() in ("bronx", "the bronx") else boro


def guide_sites(nypl_rows):
    """-> (every mapped guide site, sites per service type, guide locations per 100k per borough)."""
    every, by_type, per_boro = [], defaultdict(list), defaultdict(set)
    for r in nypl_rows:
        if r["row_type"] != "mapped" or not r["latitude"]:
            continue
        xy = to_xy(float(r["latitude"]), float(r["longitude"]))
        every.append(xy)
        for t in parse_types(r["service_types_all"]):
            by_type[t].append(xy)
        per_boro[normal_borough(r["borough"])].add((r["latitude"][:7], r["longitude"][:8]))
    rate = {k: len(per_boro[k]) / v * 1e5 for k, v in POPULATION.items()}
    return every, by_type, rate


def is_sensitive(row, raw=None):
    """A survivor service stays out of anything committed, even with a public address."""
    if row["source"] == "endgbv" or SENSITIVE_NAME_RE.search(row["name"]):
        return True
    values = (raw or {}).get("social_facility:for", "")
    return bool(OSM_SENSITIVE_FOR & {v.strip() for v in values.split(";")})


def is_private_practice(rep, sources):
    """Only OSM lists it, under a practice tag. A service list naming the same place makes it an organization."""
    return rep["source"] == "osm" and set(sources) == {"osm"} and rep["primary_type"] in PRIVATE_PRACTICE_TYPES


def local_reason(rep, sources, sensitive):
    """Why a place stays out of the committed queue; blank if it may be committed. Sensitive comes first."""
    if sensitive:
        return "sensitive"
    if is_private_practice(rep, sources):
        return "private_practice"
    return "" if rep["source"] in COMMITTABLE_SOURCES else "nyc_open_data_terms"


def member_key(row):
    return f"{row['source']}:{row['source_id']}"


def best_listing(members):
    return max(members, key=lambda r: (r["source"] in COMMITTABLE_SOURCES, float(r["relevance_score"]), bool(r["phone"]), r["source"], r["source_id"]))


def merge_same_address(groups):
    """Source lists repeat a place per program, so listings with one name at one address are one row to review.
    A place with no address never merges: a shared name alone can be two sites, or a confidential one."""
    merged = {}
    for key, members in groups.items():
        rep = best_listing(members)
        same = (m.norm_street(rep["name"]), m.norm_street(rep["address"])) if rep["address"].strip() else key
        merged.setdefault(same, []).extend(members)
    return merged


def read_previous(paths):
    """Reviewer entries in existing queue files: {member key: (verdict, note)}. 'pending' with no note is not one."""
    out = {}
    for path in paths:
        if not Path(path).exists():
            continue
        for r in m.read(path):
            verdict = "" if r["hitl_review"] == "pending" else r["hitl_review"]
            if verdict or r["review_note"]:
                out.update({k: (verdict, r["review_note"]) for k in r["member_keys"].split("|") if k})
    return out


def priority_of(xy, types, every, by_type):
    """-> (priority, service types with no guide site in range, metres to the nearest guide site)."""
    any_m = nearest(xy, every)
    gaps = [t for t in types if nearest(xy, by_type.get(t, ())) > CATCHMENT_M]
    if any_m > CATCHMENT_M:
        return "1_no_guide_site_nearby", gaps, any_m
    return ("2_service_missing_nearby" if gaps else "3_already_covered"), gaps, any_m


def recommendations(rows, nypl_rows, crawl=None, raws=None, previous=None):
    """One record per place: a cross-source group, or one name at one address, collapses to its best listing.
    Blank hitl_review stays out, unless a reviewer already judged that listing."""
    previous, crawl, raws = previous or {}, crawl or {}, raws or {}
    every, by_type, rate = guide_sites(nypl_rows)
    groups = defaultdict(list)
    for r in rows:
        if r["hitl_review"] or member_key(r) in previous:
            groups[r["group_id"] or member_key(r)].append(r)
    recs = []
    for members in merge_same_address(groups).values():
        rep = best_listing(members)
        keys = sorted(member_key(r) for r in members)
        sources = sorted({r["source"] for r in members} | {s for r in members for s in r["corroborating_sources"].split(";") if s})
        types = sorted({t for r in members for t in split_types(r["proposed_service_types"])})
        if rep["lat"]:
            prio, gaps, dist = priority_of(to_xy(float(rep["lat"]), float(rep["lon"])), types, every, by_type)
        else:
            prio, gaps, dist = "4_no_location", [], math.inf
        verdict, note = next((previous[k] for k in keys if k in previous), ("", ""))
        current = next((r["hitl_review"] for r in members if r["hitl_review"] not in ("", "pending")), "")
        status = next((crawl[k] for k in keys if crawl.get(k)), "")
        sensitive = "endgbv" in sources or any(is_sensitive(r, raws.get(member_key(r))) for r in members)
        recs.append({"hitl_review": verdict or current or "pending", "review_note": note, "priority": prio, "borough": rep["borough"],
                     "name": rep["name"], "address": rep["address"], "phone": rep["phone"], "website": rep["website"],
                     "proposed_service_types": "; ".join(types), "service_gaps": "; ".join(gaps),
                     "m_to_nearest_guide_site": "" if math.isinf(dist) else round(dist), "relevance_score": rep["relevance_score"],
                     "relevance_signals": rep["relevance_signals"], "sources": ";".join(sources), "listings": len(members),
                     "source": rep["source"], "source_id": rep["source_id"], "member_keys": "|".join(keys), "url": rep["url"],
                     "crawl_site_status": status, "licence": rep["licence"], "local_reason": local_reason(rep, sources, sensitive), "_sensitive": sensitive,
                     "_rate": rate.get(rep["borough"], math.inf)})
    recs.sort(key=lambda x: (x["priority"], x["_rate"], -float(x["relevance_score"]), x["name"], x["source_id"]))
    return recs


def split_queue(recs):
    """-> (committable, local only). Only the listing shown decides the licence, so it must be one we may republish."""
    public, local = [], []
    for r in recs:
        (local if r["local_reason"] else public).append(r)
    return public, local


# Details a guide row has no column for (or left blank) that its own site lists: field, crawl column, page column.
GAP_FIELDS = (("phone", "phone", "contact_url"), ("email", "email", "contact_url"), ("hours", "hours", "hours_url"),
              ("languages", "languages", "languages_url"), ("eligibility", "eligibility", "eligibility_url"),
              ("referral", "referral", "referral_url"))
GUIDE_HAS = {"phone": "phone_number"}  # the only gap field the guide has a column for


def guide_checks(crawl_rows, nypl_rows, previous=None):
    """Guide rows whose own site disagrees, has gone, or lists details the guide lacks. The flag, the field names and a
    link only, never page text: a person reads the page and decides."""
    previous = previous or {}
    guide = {r["id"]: r for r in nypl_rows}
    out = []
    for r in crawl_rows:
        if r["group"] != "B" or r["source_id"] not in guide:
            continue
        g = guide[r["source_id"]]
        flags = []  # (flag, detail, site_address, evidence_url)
        if r.get("site_status") == "dead":
            flags.append(("website unreachable", r.get("status_detail", ""), "", r.get("website", "")))
        if r.get("site_status") == "redirected" and r.get("redirect_host"):
            flags.append(("website moved", r["redirect_host"], "", r.get("final_url", "")))
        if r["address_check"] == "different_address_listed":
            flags.append(("different address on site", "", r["site_address"], r["contact_url"] or r["final_url"]))
        if r["closure_wording"]:
            flags.append(("closure wording on site", "", "", r["closure_url"]))
        gaps = [(f, r.get(url) or r.get("final_url", "")) for f, col, url in GAP_FIELDS
                if r.get(col) and not g.get(GUIDE_HAS.get(f, ""), "").strip()]
        if gaps:
            flags.append(("site lists details the guide lacks", "; ".join(f for f, _ in gaps), "", gaps[0][1]))
        for flag, detail, addr, url in flags:
            verdict, note = previous.get((g["id"], flag), ("", ""))
            out.append({"hitl_review": verdict or "pending", "review_note": note, "guide_id": g["id"], "organization": g["organization_name"],
                        "guide_address": " ".join(x for x in (g["street_number"], g["street"], g["city"], g["zip_code"]) if x),
                        "flag": flag, "detail": detail, "site_address": addr, "evidence_url": url, "crawl_date": r.get("crawl_date", "")})
    return sorted(out, key=lambda x: (x["organization"], x["guide_id"], x["flag"]))


def write_csv(rows, columns, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def corroboration_label(row):
    """Another service-focused list has this place. Corroboration is in the score, so test the score without it."""
    others = set(row["corroborating_sources"].split(";")) - {"", row["source"]}
    return 1 if others & SERVICE_LABEL_SOURCES else 0


def score_parts(rows):
    without_corro = [float(r["relevance_score"]) - b.WEIGHTS["corroborated"] * float(r["signal_corroborated"]) for r in rows]
    without_contact = [s - b.WEIGHTS["contact"] * float(r["signal_contact"]) for s, r in zip(without_corro, rows)]
    return without_corro, without_contact


def eval_rows(label, rows, y, score, reduced, folds, scopes):
    """AUC per scope for one label, with a held-out primary-type baseline. Scopes: {name: set of sources}."""
    ptype = [(r["source"], r["primary_type"]) for r in rows]
    n = len(rows)
    base = [0.0] * n
    for k in range(b.FOLDS):
        train = [i for i in range(n) if folds[i] != k and rows[i]["source"] != "irs_eo"]
        te = b.fit_te(ptype, y, train)
        for i in range(n):
            if folds[i] == k:
                base[i] = te(ptype[i])
    out = []
    for name, scope in scopes.items():
        idx = [i for i in range(n) if rows[i]["source"] in scope]
        pos = sum(y[i] for i in idx)

        def result(vector):
            value = b.auc([vector[i] for i in idx], [y[i] for i in idx])
            return "" if value is None else round(value, 3)

        out.append({"label": label, "source": name, "places": len(idx), "positives": pos, "score_auc": result(score),
                    "score_without_contact_auc": result(reduced) if reduced else "", "baseline_auc": result(base),
                    "enough_positives": pos >= MIN_POSITIVES})
    return out


def ranker_eval():
    """Two tests. The label is never a measure of true relevance: unlabeled places are not negatives."""
    nypl, aliases = m.read(m.NYPL_CSV), m.load_aliases()
    places, matches = b.load_places(), b.load_matches()
    linked = b.link_places(places)
    rows = b.build_rows(places, matches, nypl, aliases, {}, linked=linked)
    folds = b.cv_groups(places, linked[0], matches, nypl, aliases)
    labelled = [s for s in b.SOURCES if s != "irs_eo"]
    scopes = {"all but irs_eo": set(labelled), **{s: {s} for s in labelled}}
    score = [float(r["relevance_score"]) for r in rows]
    out = eval_rows("guide match", rows, [1 if r["best_match_class"] in b.SITE else 0 for r in rows], score, None, folds, scopes)
    without_corro, without_contact = score_parts(rows)
    out += eval_rows("other service list", rows, [corroboration_label(r) for r in rows], without_corro, without_contact, folds, scopes)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="store_true", help="also write ranker_eval.csv")
    a = ap.parse_args()
    rows = m.read(SUPPLEMENT_CSV)
    nypl = m.read(m.NYPL_CSV)
    crawl_rows = m.read(CRAWL_CSV) if CRAWL_CSV.exists() else []
    crawl = {member_key(r): r["site_status"] for r in crawl_rows if r["group"] == "A"}  # OSM and HRSA places
    raws = {f"osm:{r['source_id']}": json.loads(r["raw_json"]) for r in m.read(SUPP / "osm.csv")}
    previous = read_previous((QUEUE_CSV, QUEUE_LOCAL_CSV))
    recs = recommendations(rows, nypl, crawl, raws, previous)
    public, local = split_queue(recs)
    write_csv(public, QUEUE_COLUMNS, QUEUE_CSV)
    write_csv(local, QUEUE_COLUMNS, QUEUE_LOCAL_CSV)
    print(f"{len(recs)} places: {len(public)} -> {QUEUE_CSV.name}, {len(local)} -> {QUEUE_LOCAL_CSV.name} {dict(Counter(r['local_reason'] for r in local))}")
    for name, part in (("committed", public), ("local", local)):
        print(name, sorted(Counter((r["priority"], r["borough"]) for r in part).items()))
    if crawl_rows:
        earlier = {}
        if GUIDE_CHECKS_CSV.exists():
            earlier = {(r["guide_id"], r["flag"]): ("" if r["hitl_review"] == "pending" else r["hitl_review"], r["review_note"]) for r in m.read(GUIDE_CHECKS_CSV)}
        checks = guide_checks(crawl_rows, nypl, earlier)
        write_csv(checks, GUIDE_CHECK_COLUMNS, GUIDE_CHECKS_CSV)
        print(f"{len(checks)} guide checks -> {GUIDE_CHECKS_CSV.name}")
    if a.eval:
        out = ranker_eval()
        write_csv(out, EVAL_COLUMNS, EVAL_CSV)
        for r in out:
            print(r)


if __name__ == "__main__":
    main()
