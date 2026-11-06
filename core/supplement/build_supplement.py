# /// script
# requires-python = ">=3.10"
# ///
"""One table of every supplementary place with a relevance score from proxy signals and a human-review column.

Reads data/supplement/<source>.csv (all sources in SOURCES), data/supplement/matches_<source>.csv (from
match_nypl.py) and data/kavi_resources.csv. Writes data/supplement/supplement_all.csv: one row per place,
keyed by source + source_id, every row kept, no raw_json, with the source's licence.

    python3 core/supplement/build_supplement.py              build the table
    python3 core/supplement/build_supplement.py --validate   also print the held-out validation and threshold options

Score. relevance_score is a sum of fixed points, no fitted numbers (WEIGHTS):
  type_field       3.0  x 0 / 0.5 / 1   the source's own type: OSM tags, NTEE code, FacDB facsubgrp, OMH program
                                       category, DYCD program area, ENDGBV services, HRSA / CMS OTP / Workforce1
  name_keywords    2.0  x 0 / 1         the name uses the guide's own service vocabulary (core/pipeline/extend_with_pdf.py SERVICE_PATTERNS)
  corroborated     2.0  x 0 / 1         another, independent source has the same place (phone, website domain, or
                                       name at the same spot / address)
  contact          1.0  x 0 / 1         phone plus an address, website or opening hours
  recent           0.5  x 0 / 1         last edit within RECENT_YEARS (only sources whose date is a real edit date)
Each signal is also written as signal_<name>, so it can be evaluated alone. The guide match is never an input.
guide_org_tie (the place's operator or website belongs to an org that is in the guide) is a signal too, but it
encodes the guide, so it is NOT in relevance_score; relevance_score_with_org_tie adds ORG_TIE_WEIGHT for
comparison only. Borough is not used. has_website is not in the score either (it is reported on its own).

Independence. FacDB republishes some of the other sources (datasource nysomh_mentalhealth, dycd_service_sites,
dohmh_daycare, sbs_workforce1). A FacDB row and its source's row are the same place but not independent
evidence: origin() maps a FacDB row to the source it copies, and only links across different origins corroborate.
A shared building (BIN) alone is never a link.

Review column. hitl_review is blank below REVIEW_THRESHOLD; "pending" at or above it when the place is not a
site-level guide match (nor in a cross-source group with one); reviewers enter verdicts in the queue files from
review_recommendations.py, and a rebuild keeps every verdict, keyed on source + source_id.

Confidentiality. ENDGBV rows with display_physical_address != Yes have blank address, house_number, street, zip,
lat, lon, bin and url everywhere, never join a cross-source group or corroborate, and have blank hitl_review.
"""

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coverage_report as cov  # noqa: E402
import fetch_sources as fetch_sources  # noqa: E402
import match_nypl as m  # noqa: E402

OUT_CSV = m.SUPP_DIR / "supplement_all.csv"
QUEUE_FILES = (m.SUPP_DIR / "review_queue.csv", m.SUPP_DIR / "review_queue_local.csv")
SOURCES = ["osm", "facdb", "irs_eo", "omh", "doh_childcare", "dycd", "endgbv", "workforce1", "hrsa", "cms_otp"]
OSM_LICENCE = "ODbL 1.0, (c) OpenStreetMap contributors (https://www.openstreetmap.org/copyright)"
SITE = ("same_site", "program_at_host")
ORG = SITE + ("same_org_other_site",)

# ---- scoring ----------------------------------------------------------------------------------
WEIGHTS = {"type_field": 3.0, "name_keywords": 2.0, "corroborated": 2.0, "contact": 1.0, "recent": 0.5}
ORG_TIE_WEIGHT = 2.0
# 6.0 needs at least three kinds of evidence (for example type + independent corroboration + contact), which is
# the top ~2% of places; the mass at 5.0 is type + name keyword with nothing independent behind it.
REVIEW_THRESHOLD = 6.0  # chosen from the score distribution, see --validate; one constant
THRESHOLD_OPTIONS = (5.0, 6.0, 7.0)
RECENT_YEARS = 3
RECENT_CUTOFF = date(2023, 11, 5)  # fetch_sources.ACCESSED minus RECENT_YEARS
RECENCY_SOURCES = {"osm", "cms_otp"}  # OMH last_edit is the download date, not an edit date

# ---- links between sources ----------------------------------------------------------------------
LINK_M = 75               # metres: the same place
LINK_NAME_JACCARD = 0.67  # token-set similarity that counts as the same name
LINK_PHONE_NAME = 0.4     # a shared phone needs at least this much name overlap when the spot is unknown
PHONE_ROWS_MAX = 3        # a phone on more rows than this is a switchboard
DOMAIN_ROWS_MAX = 5       # a website on more rows than this is a chain or portal
MIN_NAME_TOKENS = 2       # a guide org name needs this many distinctive tokens to identify an operator
FACDB_COPY_OF = {"nysomh_mentalhealth": "omh", "dycd_service_sites": "dycd", "dohmh_daycare": "doh_childcare",
                 "sbs_workforce1": "workforce1"}
HIDDEN_COLS = m.HIDDEN_LOCATION_COLS

# ---- validation ---------------------------------------------------------------------------------
FOLDS = 5
TE_PRIOR_ROWS = 5  # smoothing rows for the primary-type baseline
WEBSITE_STRATUM_MIN = 40  # a category needs this many places with and without a website to be listed

# The guide's own vocabulary: core/pipeline/extend_with_pdf.py SERVICE_PATTERNS (copied, not imported, because
# that module reads the whole pipeline), plus a few extra words that name a service in an organization name.
SERVICE_PATTERNS = {
    "Food": r"\bfood\b|pantr|soup kitchen|\bmeals?\b|grocer|nutrition",
    "Family & Childcare": r"child ?care|day ?care|after-?school(?! hours)|parenting|child welfare|family support"
                          r"|caregiver support|caregivers? (support|groups?)",
    "Housing": r"housing(?! status)|shelters?(?! system)|homelessness prevention|tenant|eviction|rent assistance",
    "Health & Mental Health": r"mental health|(?<!career )(?<!financial )(?<!legal )(?<!housing )(?<!benefits )"
                              r"(?<!vocational )(?<!rehabilitation )(?<!discharge )counseling"
                              r"|therap|medical(?! records)(?! directives)|health ?care(?! proxy)|health clinic|clinicians?"
                              r"|psychiatr|primary care|cancer|mammogra|crisis (line|support|intervention|counseling)|suicide"
                              r"|health information|wellness (care|services)",
    "Addiction & Recovery": r"addiction|substance|detox|sobriety|harm reduction|recovery (services|support|program)",
    "Legal & Rights": r"(?<!not offer )(?<!not provide )legal (assistance|help|services|screenings?|referrals?|representation"
                      r"|aid|advice|counsel|protection)|attorney|lawyer|civil rights|know your rights|court advocacy|expunge"
                      r"|record sealing|immigration (law|cases|matters|applications)|citizenship applications|guardianship",
    "Education": r"college|literacy|\bged\b|\bhse\b|\besol\b|english (classes|lessons)|tutoring|high school"
                 r"|adult education|education(al)? (services|programs?|classes|assistance)|\bclasses\b|\bcourses\b",
    "Employment": r"\bjobs?\b|employ(?!ment authorization)|workforce|career|vocational|resume|internship",
    "Financial Assistance": r"financial (assistance|literacy|counseling|coaching|help|aid)"
                            r"|benefits (advocacy|assistance|enrollment|screening|applications?|counseling)|(apply|applying) for benefits"
                            r"|help with benefits|public benefits|entitlements|social security|\btax(es)? (preparation|filing|help)"
                            r"|public assistance|cash assistance|\bsnap\b|stipends?|fare discounts?|\bbond\b|reduced[- ]fare|money management"
                            r"|disability compensation",
    "Reentry Support": r"re-?entry (services|support|programs?|case management|initiative)"
                       r"|alternatives?[- ]to[- ](detention|incarceration|prison)|pre-release|during incarceration",
}
NAME_EXTRA = {  # service words that appear in organization names but not in descriptions
    "Reentry Support": r"re-?entry|formerly incarcerated",
    "Legal & Rights": r"legal aid|legal services|defender|\blegal\b",
    "Food": r"food bank|\bpantry|food pantry|soup kitchen",
    "Housing": r"homeless|supportive housing|\bshelter\b",
    "Health & Mental Health": r"\bclinic\b|health center|community health",
    "Employment": r"job training|career center",
    "Family & Childcare": r"family services|child care|day care",
    "Disability Services": r"disabilit|special needs|independent living",
}
NAME_GENERIC = r"community (center|centre|services|development)|social services|settlement|outreach|case management|immigrant|domestic violence"
NAME_REGEXES = {t: re.compile(p + ("|" + NAME_EXTRA[t] if t in NAME_EXTRA else ""), re.I) for t, p in SERVICE_PATTERNS.items()}
NAME_REGEXES["Disability Services"] = re.compile(NAME_EXTRA["Disability Services"], re.I)
NAME_SCHOOL_RE = re.compile(r"high school|middle school|elementary|college point|university|\bcollege\b|\bP\.?S\.? ?\d|\bI\.?S\.? ?\d", re.I)
NAME_GENERIC_RE = re.compile(NAME_GENERIC, re.I)

# ---- source-specific type fields: (strength, service types) ---------------------------------------
OSM_FOR_TARGET = {"homeless", "migrant", "refugee", "abused", "domestic_abuse", "victim", "drug_addicted", "mental_health",
                  "unemployed", "juvenile", "orphan", "underprivileged", "low_income", "ex_offender", "prisoner",
                  "disabled", "diseased", "child", "youth", "senior"}
OSM_FOR_TYPES = {"homeless": "Housing", "drug_addicted": "Addiction & Recovery", "mental_health": "Health & Mental Health",
                 "unemployed": "Employment", "disabled": "Disability Services", "ex_offender": "Reentry Support",
                 "prisoner": "Reentry Support"}
OSM_SOCIAL_WEAK = {"nursing_home", "assisted_living", "retirement_home"}
OSM_SOCIAL_TYPES = {"food_bank": "Food", "soup_kitchen": "Food", "shelter": "Housing", "transitional_housing": "Housing",
                    "group_home": "Housing", "outreach": "Housing"}
OSM_MH_SPECIALITY = {"psychiatry", "psychotherapy", "psychology", "addiction", "counselling", "child_psychiatry"}
OSM_STRONG_AMENITY = {"community_centre": None, "social_centre": None, "food_bank": "Food"}
OSM_OFFICE = {"ngo": (1.0, None), "charity": (1.0, None), "employment_agency": (1.0, "Employment"),
              "association": (0.5, None), "foundation": (0.5, None), "lawyer": (0.5, "Legal & Rights"),
              "government": (0.5, None), "multiservice": (0.5, None), "tutoring": (0.5, "Education")}
OSM_WEAK_AMENITY = {"clinic": "Health & Mental Health", "hospital": "Health & Mental Health",
                    "doctors": "Health & Mental Health", "childcare": "Family & Childcare",
                    "kindergarten": "Family & Childcare", "language_school": "Education"}
OSM_WEAK_HEALTHCARE = {"clinic", "centre", "hospital", "doctor"}

NTEE_STRONG = {"F": "Health & Mental Health", "I": "Legal & Rights", "J": "Employment", "K": "Food", "L": "Housing",
               "P": None}
NTEE_WEAK = {"E": "Health & Mental Health", "O": "Family & Childcare"}
NTEE_CODE_TYPES = {"F20": "Addiction & Recovery", "F21": "Addiction & Recovery", "F22": "Addiction & Recovery",
                   "F23": "Addiction & Recovery", "P30": "Family & Childcare", "P31": "Family & Childcare",
                   "P32": "Family & Childcare", "P33": "Family & Childcare", "P40": "Family & Childcare",
                   "P60": "Financial Assistance", "P70": "Housing", "P75": "Housing", "P85": "Housing"}
FACDB_SUBGROUP = {  # facsubgrp -> (strength, service type)
    "SOUP KITCHENS AND FOOD PANTRIES": (1.0, "Food"), "LEGAL AND INTERVENTION SERVICES": (1.0, "Legal & Rights"),
    "NON-RESIDENTIAL HOUSING AND HOMELESS SERVICES": (1.0, "Housing"),
    "COMMUNITY CENTERS AND COMMUNITY PROGRAMS": (1.0, None),
    "PROGRAMS FOR PEOPLE WITH DISABILITIES": (1.0, "Disability Services"),
    "WORKFORCE DEVELOPMENT": (1.0, "Employment"), "ADULT AND IMMIGRANT LITERACY": (1.0, "Education"),
    "IMMIGRANT SERVICES": (1.0, "Legal & Rights"), "FINANCIAL ASSISTANCE AND SOCIAL SERVICES": (1.0, "Financial Assistance"),
    "MENTAL HEALTH": (1.0, "Health & Mental Health"), "SUBSTANCE USE DISORDER TREATMENT PROGRAMS": (1.0, "Addiction & Recovery"),
    "GED AND ALTERNATIVE HIGH SCHOOL EQUIVALENCY": (1.0, "Education"),
    "YOUTH CENTERS, LITERACY PROGRAMS, AND JOB TRAINING SERVICES": (1.0, "Education"),
    "HOSPITALS AND CLINICS": (0.5, "Health & Mental Health"), "OTHER HEALTH CARE": (0.5, "Health & Mental Health"),
    "SENIOR SERVICES": (0.5, None), "AFTER-SCHOOL PROGRAMS": (0.5, "Family & Childcare"),
    "DAY CARE": (0.5, "Family & Childcare"), "CHILD NUTRITION": (0.5, "Food"),
    "HEALTH PROMOTION AND DISEASE PREVENTION": (0.5, "Health & Mental Health")}
OMH_CATEGORY = {"Outpatient": 1.0, "Support": 1.0, "Emergency/Crisis": 1.0, "Residential": 0.5, "Inpatient": 0.5}
OMH_SUBCATEGORY_TYPES = {"Vocational": "Employment", "Education": "Education", "Unlicensed Housing": "Housing",
                         "Treatment Program": "Housing"}
DYCD_AREA = {"Literacy and Immigrant Services": (1.0, "Education"), "RHY": (1.0, "Housing"), "WIOA": (1.0, "Employment"),
             "Advance and Earn": (1.0, "Employment"), "SYEP": (1.0, "Employment"), "CSBG": (1.0, "Financial Assistance"),
             "Cornerstone": (0.5, "Family & Childcare"), "Beacon": (0.5, "Family & Childcare"),
             "Compass": (0.5, "Family & Childcare"), "Office of Neighborhood Safety": (0.5, None), "CRED": (0.5, None),
             "Discretionary": (0.5, None), "Strategic Partnerships": (0.5, None)}
WHOLE_SOURCE_TYPE = {"hrsa": (1.0, "Health & Mental Health"), "cms_otp": (1.0, "Addiction & Recovery"),
                     "workforce1": (1.0, "Employment"), "doh_childcare": (0.5, "Family & Childcare"),
                     "endgbv": (1.0, None)}
ENDGBV_TYPES = (("Legal", "Legal & Rights"), ("Counseling", "Health & Mental Health"), ("Housing", "Housing"))

OUT_COLUMNS = ["source", "source_id", "name", "borough", "lat", "lon", "primary_type", "address", "house_number", "street",
               "zip", "phone", "website", "opening_hours", "operator", "last_edit", "url", "bin", "licence",
               "has_website", "best_match_class", "matched_nypl_id", "group_id", "group_size", "corroborating_sources",
               "signal_type_field", "signal_name_keywords", "signal_corroborated", "signal_contact", "signal_recent",
               "signal_guide_org_tie", "relevance_score", "relevance_score_with_org_tie", "relevance_signals",
               "guide_org_tie", "proposed_service_types", "hitl_review"]


# ---- reading --------------------------------------------------------------------------------------
def licences():
    out = {s: fetch_sources.SOURCES[s]["licence"] for s in SOURCES if s in fetch_sources.SOURCES}
    out["osm"] = OSM_LICENCE
    return out


def load_places(sources=SOURCES, supp_dir=m.SUPP_DIR):
    """-> list of place dicts. A hidden ENDGBV row loses every location field here, whatever the file holds."""
    places = []
    for s in sources:
        for r in m.read(supp_dir / f"{s}.csv"):
            raw = json.loads(r.get("raw_json") or "{}")
            hidden = m.is_hidden_location(r, raw)
            if hidden:
                r = {**r, **{c: "" for c in HIDDEN_COLS}}
            located = bool(r["lat"] and r["lon"])
            tok = m.tokens(r["name"])
            ops = [r["operator"]] if r["operator"] else []
            if s == "irs_eo":
                ops = [r["name"]]
            places.append({
                "key": (s, r["source_id"]), "src": s, "row": r, "raw": raw, "hidden": hidden, "tok": tok,
                "org_tokens": [t for t in (m.tokens(o) for o in ops) if t],
                "lat": float(r["lat"]) if located else None, "lon": float(r["lon"]) if located else None,
                "addr": m.parse_address(r["house_number"], r["street"], r["zip"], r["address"]),
                "phones": m.phones(r["phone"]), "domains": m.domains(r["website"]),
                "origin": FACDB_COPY_OF.get(raw.get("datasource"), "facdb") if s == "facdb" else s})
    return places


def load_matches(sources=SOURCES, supp_dir=m.SUPP_DIR):
    """-> {(source, source_id): (best class, [nypl ids with that class])}; missing files give no entries."""
    found = defaultdict(list)
    for s in sources:
        path = supp_dir / f"matches_{s}.csv"
        if not path.exists():
            continue
        for r in m.read(path):
            if r["source_id"]:
                found[(r["source"], r["source_id"])].append((m.RANK[r["match_class"]], r["match_class"], r["nypl_id"]))
    out = {}
    for k, pairs in found.items():
        best = min(p[0] for p in pairs)
        top = [p for p in pairs if p[0] == best]
        out[k] = (top[0][1], sorted({p[2] for p in top}, key=int))
    return out


# ---- signals: type field ------------------------------------------------------------------------------
def tag_values(raw, key):
    return {v.strip() for v in str(raw.get(key, "")).split(";") if v.strip()}


def type_osm(raw):
    """-> (strength, labels, service types) from OSM tags; the strongest rule wins, labels list every hit."""
    hits = []  # (strength, label, type)
    amenity, healthcare, office = raw.get("amenity", ""), raw.get("healthcare", ""), raw.get("office", "")
    social, for_ = raw.get("social_facility", ""), tag_values(raw, "social_facility:for")
    target = for_ & OSM_FOR_TARGET
    if amenity == "social_facility" or social:
        weak = social in OSM_SOCIAL_WEAK and not (target - {"senior"})
        hits.append((0.5 if weak else 1.0, f"social_facility={social or 'yes'}", OSM_SOCIAL_TYPES.get(social)))
    for f in sorted(target):
        hits.append((1.0, f"social_facility:for={f}", OSM_FOR_TYPES.get(f)))
    if amenity in OSM_STRONG_AMENITY:
        hits.append((1.0, f"amenity={amenity}", OSM_STRONG_AMENITY[amenity]))
    speciality = tag_values(raw, "healthcare:speciality") & OSM_MH_SPECIALITY
    if healthcare in ("counselling", "psychotherapist") or raw.get("healthcare:counselling") or speciality:
        label = f"healthcare={healthcare}" if healthcare in ("counselling", "psychotherapist") else \
            "healthcare:speciality=" + ";".join(sorted(speciality)) if speciality else "healthcare:counselling"
        kind = "Addiction & Recovery" if "addiction" in speciality or "addiction" in str(raw.get("healthcare:counselling", "")) \
            else "Health & Mental Health"
        hits.append((1.0, label, kind))
    if office in OSM_OFFICE:
        strength, kind = OSM_OFFICE[office]
        hits.append((strength, f"office={office}", kind))
    if amenity in OSM_WEAK_AMENITY:
        hits.append((0.5, f"amenity={amenity}", OSM_WEAK_AMENITY[amenity]))
    if healthcare in OSM_WEAK_HEALTHCARE:
        hits.append((0.5, f"healthcare={healthcare}", "Health & Mental Health"))
    if not hits:
        return 0.0, [], set()
    top = max(h[0] for h in hits)
    return top, [h[1] for h in hits if h[0] == top], {h[2] for h in hits if h[2]}


def type_irs(row):
    code = (row["primary_type"] or "").upper()
    if not code:
        return 0.0, [], set()
    kind = NTEE_CODE_TYPES.get(code[:3]) or NTEE_STRONG.get(code[0]) or NTEE_WEAK.get(code[0])
    strength = 1.0 if code[0] in NTEE_STRONG else 0.5 if code[0] in NTEE_WEAK else 0.0
    return strength, ([f"ntee={code}"] if strength else []), ({kind} if kind and strength else set())


def type_field(p):
    """-> (strength 0 / 0.5 / 1, labels, service types) from the source's own type fields. No guide data."""
    s, row, raw = p["src"], p["row"], p["raw"]
    if s == "osm":
        return type_osm(raw)
    if s == "irs_eo":
        return type_irs(row)
    if s == "facdb":
        strength, kind = FACDB_SUBGROUP.get(raw.get("facsubgrp", ""), (0.0, None))
        return strength, ([f"facsubgrp={raw.get('facsubgrp')}"] if strength else []), ({kind} if kind else set())
    if s == "omh":
        strength = OMH_CATEGORY.get(raw.get("program_category_description", ""), 0.0)
        sub = raw.get("program_subcategory_description", "")
        types = {"Health & Mental Health"} | ({OMH_SUBCATEGORY_TYPES[sub]} if sub in OMH_SUBCATEGORY_TYPES else set())
        return strength, ([f"omh={raw.get('program_category_description')}/{sub}"] if strength else []), (types if strength else set())
    if s == "dycd":
        strength, kind = DYCD_AREA.get(raw.get("program_area", ""), (0.0, None))
        return strength, ([f"dycd={raw.get('program_area')}"] if strength else []), ({kind} if kind else set())
    if s in WHOLE_SOURCE_TYPE:
        strength, kind = WHOLE_SOURCE_TYPE[s]
        types = {kind} if kind else set()
        if s == "endgbv":
            types |= {t for word, t in ENDGBV_TYPES if word in row["primary_type"]}
        return strength, [f"{s} listing"], types
    return 0.0, [], set()


# ---- signals: name, contact, recency ---------------------------------------------------------------------
def name_keywords(name):
    """-> (types matched, words). Uses only the guide's own service vocabulary on the name."""
    found, words = set(), []
    for t, rx in NAME_REGEXES.items():
        if t == "Education" and NAME_SCHOOL_RE.search(name or ""):  # a school's name is not a service
            continue
        mt = rx.search(name or "")
        if mt:
            found.add(t)
            words.append(mt.group(0).lower())
    g = NAME_GENERIC_RE.search(name or "")
    if g:
        words.append(g.group(0).lower())
    return found, words


def contact(row):
    """Phone plus an address, website or opening hours."""
    has_phone = bool(re.search(r"\d{3}\D*\d{3}\D*\d{4}", row.get("phone", "")))
    return has_phone and bool(row.get("address") or row.get("street") or row.get("website") or row.get("opening_hours"))


def recent(p):
    if p["src"] not in RECENCY_SOURCES:
        return False
    s = p["row"]["last_edit"]
    for pat in (r"(\d{4})-(\d{2})-(\d{2})", r"(\d{2})/(\d{2})/(\d{4})"):
        mt = re.match(pat, s or "")
        if mt:
            g = mt.groups()
            y, mo, d = (int(g[0]), int(g[1]), int(g[2])) if len(g[0]) == 4 else (int(g[2]), int(g[0]), int(g[1]))
            try:
                return date(y, mo, d) >= RECENT_CUTOFF
            except ValueError:
                return False
    return False


# ---- cross-source links ---------------------------------------------------------------------------------
def name_overlap(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def distinctive_shared(a, b):
    return bool((a & b) - m.GEO - m.GENERIC - m.SCOPE)


def link_places(places):
    """-> (links: {i: {j: kind}}, corroboration: {i: set(origin)}).
    A link is the same place in two sources. Hidden ENDGBV rows and IRS rows (no location) take no part.
    Corroboration counts only links across different origins. Org-name agreement with an IRS record is not used:
    it says the organization exists, not that this place does."""
    idx = [i for i, p in enumerate(places) if not p["hidden"] and p["src"] != "irs_eo"]
    phone_rows, dom_rows = defaultdict(list), defaultdict(list)
    grid, addr_rows = defaultdict(list), defaultdict(list)
    for i in idx:
        p = places[i]
        for ph in p["phones"]:
            phone_rows[ph].append(i)
        for d in p["domains"]:
            dom_rows[d].append(i)
        if p["lat"] is not None:
            grid[(round(p["lat"] / 0.001), round(p["lon"] / 0.001))].append(i)
        if p["addr"]:
            addr_rows[p["addr"][1]].append(i)
    cand = defaultdict(set)
    for i in idx:
        p = places[i]
        if p["lat"] is not None:
            ci, cj = round(p["lat"] / 0.001), round(p["lon"] / 0.001)
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    cand[i].update(j for j in grid.get((ci + di, cj + dj), ()) if j > i)
        if p["addr"]:
            cand[i].update(j for j in addr_rows[p["addr"][1]] if j > i)
        for ph in p["phones"]:
            if len(phone_rows[ph]) <= PHONE_ROWS_MAX:
                cand[i].update(j for j in phone_rows[ph] if j > i)
    links = defaultdict(dict)
    for i, js in cand.items():
        a = places[i]
        for j in js:
            b = places[j]
            if a["src"] == b["src"]:
                continue
            dist = m.metres(a["lat"], a["lon"], b["lat"], b["lon"]) if a["lat"] is not None and b["lat"] is not None else None
            here = (dist is not None and dist <= LINK_M) or m.same_address(a["addr"], b["addr"])
            sim = name_overlap(a["tok"], b["tok"])
            phone = bool(a["phones"] & b["phones"]) and all(len(phone_rows[ph]) <= PHONE_ROWS_MAX for ph in a["phones"] & b["phones"])
            dom = bool(a["domains"] & b["domains"]) and all(len(dom_rows[d]) <= DOMAIN_ROWS_MAX for d in a["domains"] & b["domains"])
            kind = None
            if sim >= LINK_NAME_JACCARD and here and distinctive_shared(a["tok"], b["tok"]):
                kind = "name+place"
            elif phone and (here or sim >= LINK_PHONE_NAME):
                kind = "phone"
            elif dom and here:
                kind = "website"
            if kind:
                links[i][j] = links[j][i] = kind
    corro = defaultdict(set)
    for i, nbrs in links.items():
        for j in nbrs:
            if places[j]["origin"] != places[i]["origin"]:
                corro[i].add(places[j]["origin"])
    return links, corro


def groups_of(places, links):
    """-> group id per place index (blank for singletons and hidden rows) and sizes, by union-find over links."""
    parent = list(range(len(places)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, nbrs in links.items():
        for j in nbrs:
            parent[find(j)] = find(i)
    members = defaultdict(list)
    for i in range(len(places)):
        members[find(i)].append(i)
    gid, size = {}, {}
    for ms in members.values():
        tag = "" if len(ms) == 1 else "g" + hashlib.sha1("|".join(sorted(f"{places[i]['src']}:{places[i]['key'][1]}" for i in ms)).encode()).hexdigest()[:10]
        for i in ms:
            gid[i], size[i] = tag, len(ms)
    return gid, size, members


# ---- operator / website tied to a guide org (encodes the guide: kept out of relevance_score) ----------------
def guide_orgs(nypl_rows, aliases):
    names, doms = set(), defaultdict(set)
    for r in nypl_rows:
        parsed = m.parse_nypl_name(r["organization_name"], aliases)
        if len(parsed["parent"] - m.GEO - m.GENERIC - m.SCOPE) >= MIN_NAME_TOKENS:
            names.add(parsed["parent"])
        for d in m.domains(r["website"]):
            doms[d].add(parsed["parent"])
    return names, {d for d, ps in doms.items() if len(ps) < m.DOMAIN_UNRELATED_MIN}


def org_tie(p, names, doms):
    for d in sorted(p["domains"] & doms):
        return f"domain:{d}"
    for t in p["org_tokens"]:
        if t in names:
            return "operator:" + " ".join(sorted(t))
    return ""


# ---- scoring -----------------------------------------------------------------------------------------------
def score_place(p, corroborators):
    """-> dict of signal values, score, signal text, proposed types. Takes no guide-match information."""
    row = p["row"]
    strength, type_labels, types = type_field(p)
    kw_types, kw_words = name_keywords(row["name"])
    sig = {"type_field": strength, "name_keywords": 1.0 if kw_words else 0.0,
           "corroborated": 1.0 if corroborators else 0.0, "contact": 1.0 if contact(row) else 0.0,
           "recent": 1.0 if recent(p) else 0.0}
    text = []
    if strength:
        text.append(f"type:{'; '.join(type_labels)}" + (" (weak)" if strength < 1 else ""))
    if kw_words:
        text.append("name:" + ",".join(sorted(set(kw_words))))
    if corroborators:
        text.append("corroborated:" + ",".join(sorted(corroborators)))
    if sig["contact"]:
        text.append("contact")
    if sig["recent"]:
        text.append(f"recent:{row['last_edit'][:10]}")
    score = round(sum(WEIGHTS[k] * v for k, v in sig.items()), 2)
    return sig, score, " | ".join(text), "; ".join(sorted(types | kw_types))


def build_rows(places, matches, nypl_rows, aliases, previous=None, threshold=REVIEW_THRESHOLD, linked=None):
    """-> list of output dicts, in source order. `matches` only labels rows; it never reaches score_place."""
    previous = previous or {}
    lic = licences()
    links, corro = linked or link_places(places)
    gid, gsize, members = groups_of(places, links)
    names, doms = guide_orgs(nypl_rows, aliases)
    scored = [score_place(p, {o for o in corro.get(i, ())}) for i, p in enumerate(places)]
    site_group = {g for i, g in gid.items() if g and matches.get(places[i]["key"], ("",))[0] in SITE}
    out = []
    for i, p in enumerate(places):
        row, (sig, score, text, types) = p["row"], scored[i]
        cls, ids = matches.get(p["key"], ("no_match", []))
        tie = "" if p["hidden"] else org_tie(p, names, doms)
        in_guide = cls in SITE or (gid[i] in site_group if gid[i] else False)
        pending = score >= threshold and not in_guide and not p["hidden"]
        verdict = previous.get(p["key"], "")
        review = "" if p["hidden"] else (verdict if verdict and verdict != "pending" else "pending" if pending else "")
        rec = {c: row.get(c, "") for c in OUT_COLUMNS if c in row and c != "raw_json"}
        rec.update({"licence": lic[p["src"]], "has_website": str(bool(row["website"])), "best_match_class": cls,
                    "matched_nypl_id": ";".join(ids), "group_id": "" if p["hidden"] else gid[i],
                    "group_size": "" if p["hidden"] or gsize[i] == 1 else gsize[i],
                    "corroborating_sources": "" if p["hidden"] else ";".join(sorted(corro.get(i, ()))),
                    **{f"signal_{k}": v for k, v in sig.items()}, "signal_guide_org_tie": 1 if tie else 0,
                    "relevance_score": score,
                    "relevance_score_with_org_tie": round(score + (ORG_TIE_WEIGHT if tie else 0), 2),
                    "relevance_signals": text, "guide_org_tie": tie, "proposed_service_types": types,
                    "hitl_review": review, "_in_guide": in_guide, "_hidden": p["hidden"]})
        if p["hidden"]:
            rec.update({c: "" for c in HIDDEN_COLS})
        out.append(rec)
    return out


def read_verdicts(path):
    """Reviewer verdicts in an earlier build: {(source, source_id): verdict}. 'pending' is not a verdict."""
    if not path.exists():
        return {}
    return {(r["source"], r["source_id"]): r["hitl_review"] for r in m.read(path)
            if r.get("hitl_review") and r["hitl_review"] != "pending"}


def read_queue_verdicts(paths=None):
    """Verdicts reviewers entered in review_recommendations.py's queue files: {(source, source_id): verdict}."""
    out = {}
    for path in paths if paths is not None else QUEUE_FILES:
        if path.exists():
            for r in m.read(path):
                if r["hitl_review"] and r["hitl_review"] != "pending":
                    out.update({tuple(k.split(":", 1)): r["hitl_review"] for k in r["member_keys"].split("|") if k})
    return out


def write_rows(rows, path):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, OUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ---- validation (positive-unlabeled, grouped by organization) ---------------------------------------------
def auc(scores, labels):
    """P(score of a random positive > score of a random unlabeled), ties half. None without both kinds."""
    pos = sum(labels)
    neg = len(labels) - pos
    if not pos or not neg:
        return None
    order = sorted(range(len(scores)), key=lambda k: scores[k])
    rank_sum, k = 0.0, 0
    while k < len(order):
        j = k
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[k]]:
            j += 1
        mid = (k + j) / 2 + 1
        rank_sum += mid * sum(labels[order[t]] for t in range(k, j + 1))
        k = j + 1
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def cv_groups(places, links, matches, nypl_rows, aliases):
    """Organization groups for the folds: cross-source links, the same operator or name, and the same guide parent
    org (used only to keep an org on one side of the split)."""
    gids, _ = cov.group_parents(nypl_rows, aliases)
    parent = list(range(len(places)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for i, nbrs in links.items():
        for j in nbrs:
            union(i, j)
    seen = {}
    for i, p in enumerate(places):
        key = m.name_key(p["row"]["operator"] or p["row"]["name"])
        if len(key) > 3:
            union(i, seen.setdefault(("org", key), i))
        _, ids = matches.get(p["key"], ("", []))
        for nid in ids:
            union(i, seen.setdefault(("guide", gids.get(nid, nid)), i))
    first = {}
    for i, p in enumerate(places):
        r = find(i)
        if r not in first or p["key"] < first[r]:
            first[r] = p["key"]
    return [int(hashlib.sha1("|".join(first[find(i)]).encode()).hexdigest(), 16) % FOLDS for i in range(len(places))]


def fit_te(keys, labels, train):
    """Smoothed positive rate per key from the training rows only."""
    prior = sum(labels[i] for i in train) / max(len(train), 1)
    tot, pos = Counter(), Counter()
    for i in train:
        tot[keys[i]] += 1
        pos[keys[i]] += labels[i]
    return lambda k: (pos[k] + TE_PRIOR_ROWS * prior) / (tot[k] + TE_PRIOR_ROWS)


def fit_weights(sig_rows, labels, train, names):
    """Naive log-odds weight per signal from the training rows only, clipped at zero."""
    w = {}
    for n in names:
        on = [labels[i] for i in train if sig_rows[i][n] > 0]
        off = [labels[i] for i in train if sig_rows[i][n] == 0]
        r_on = (sum(on) + 0.5) / (len(on) + 1)
        r_off = (sum(off) + 0.5) / (len(off) + 1)
        w[n] = max(0.0, math.log(r_on / r_off))
    return w


def validate(places, rows, matches, links, nypl_rows, aliases):
    """Prints held-out results. Positives are site-level guide matches; everything else is unlabeled, not negative."""
    sig_names = list(WEIGHTS)
    y_site = [1 if r["best_match_class"] in SITE else 0 for r in rows]
    y_org = [1 if r["best_match_class"] in ORG else 0 for r in rows]
    fold = cv_groups(places, links, matches, nypl_rows, aliases)
    src = [r["source"] for r in rows]
    sigs = [{n: float(r[f"signal_{n}"]) for n in sig_names} for r in rows]
    score = [float(r["relevance_score"]) for r in rows]
    score_org = [float(r["relevance_score_with_org_tie"]) for r in rows]
    tie = [float(r["signal_guide_org_tie"]) for r in rows]
    ptype = [(r["source"], r["primary_type"]) for r in rows]
    n = len(rows)
    print(f"places {n}; folds {FOLDS} by organization group; fold sizes {sorted(Counter(fold).values())}")
    print("positives (site-level) per source:", {s: sum(y for y, x in zip(y_site, src) if x == s) for s in SOURCES})
    # held-out predictions: baseline and fitted-weight score, each fitted on the other folds only
    base, fitted = [0.0] * n, [0.0] * n
    for k in range(FOLDS):
        train = [i for i in range(n) if fold[i] != k and src[i] != "irs_eo"]
        te = fit_te(ptype, y_site, train)
        w = fit_weights(sigs, y_site, train, sig_names)
        for i in range(n):
            if fold[i] == k:
                base[i] = te(ptype[i])
                fitted[i] = sum(w[nm] * sigs[i][nm] for nm in sig_names)
    wall = fit_weights(sigs, y_site, [i for i in range(n) if src[i] != "irs_eo"], sig_names)
    print("log-odds weights fitted on all rows (for reference, not used):", {k: round(v, 2) for k, v in wall.items()})

    def fmt(v):
        return "  n/a" if v is None else f"{v:5.3f}"

    def by(group_sources, labels, vector):
        idx = [i for i in range(n) if src[i] in group_sources]
        return auc([vector[i] for i in idx], [labels[i] for i in idx])

    methods = [("baseline: primary type (held-out)", base), ("fixed-weight score", score), ("fitted-weight score (held-out)", fitted),
               ("score + guide_org_tie (circular)", score_org), ("guide_org_tie alone (circular)", tie)]
    methods += [(f"signal {nm} alone", [s[nm] for s in sigs]) for nm in sig_names]
    methods += [(f"score without {nm}", [score[i] - WEIGHTS[nm] * sigs[i][nm] for i in range(n)]) for nm in sig_names]
    labelled = [s for s in SOURCES if s != "irs_eo"]
    cols = [("all but irs", labelled)] + [(s, [s]) for s in labelled]
    print("\nAUC = chance a guide-matched place outranks an unlabeled one (0.5 = no better than a coin)")
    print(f"{'method':38}" + "".join(f"{c:>14}" for c, _ in cols))
    for label, vec in methods:
        print(f"{label:38}" + "".join(f"{fmt(by(g, y_site, vec)):>14}" for _, g in cols))
    print("\nper-fold AUC, all but irs (min / mean / max)")
    for scope in (labelled, ["osm"], ["facdb"], ["omh"]):
        print(f"  {'+'.join(scope) if len(scope) == 1 else 'all but irs'}")
        for label, vec in methods[:3]:
            vals = [auc([vec[i] for i in range(n) if fold[i] == k and src[i] in scope],
                        [y_site[i] for i in range(n) if fold[i] == k and src[i] in scope]) for k in range(FOLDS)]
            vals = [v for v in vals if v is not None]
            print(f"    {label:36} {min(vals):.3f} / {sum(vals) / len(vals):.3f} / {max(vals):.3f}  ({len(vals)} folds with positives)")
    print("\nirs_eo, org-level label (same_org_other_site counts): AUC",
          fmt(by(["irs_eo"], y_org, score)), "score;", fmt(by(["irs_eo"], y_org, [s["type_field"] for s in sigs])), "type_field;",
          fmt(by(["irs_eo"], y_org, [s["name_keywords"] for s in sigs])), "name;", fmt(by(["irs_eo"], y_org, [s["corroborated"] for s in sigs])), "corroborated")
    site_by_source = {s: (sum(1 for i in range(n) if src[i] == s and y_site[i]), sum(1 for i in range(n) if src[i] == s)) for s in SOURCES}
    print("site-level positives / places:", site_by_source)
    borough_coverage(rows, y_site)
    website_lift(rows, y_site, sigs)
    threshold_options(rows, y_site)


def borough_coverage(rows, y):
    """Descriptive only: where the guide-matched places are. Borough is not a feature of the score."""
    print("\nguide-matched (site-level) places by borough, all sources but irs_eo; the guide's own mapped rows are "
          "Manhattan-heavy, so the positives are too")
    for b in ("Manhattan", "Brooklyn", "Queens", "The Bronx", "Staten Island"):
        sel = [i for i, r in enumerate(rows) if r["borough"] == b and r["source"] != "irs_eo"]
        top = [i for i in sel if float(rows[i]["relevance_score"]) >= REVIEW_THRESHOLD]
        print(f"  {b:14} places {len(sel):6}; guide-matched {rate(sum(y[i] for i in sel), len(sel)):16}; "
              f"at or above threshold {len(top):5} ({len(top) / len(sel):.3f} of places)")


def rate(pos, tot):
    return f"{pos}/{tot} = {pos / tot:.3f}" if tot else "n/a"


def website_lift(rows, y, sigs):
    print("\nhas_website lift (sources that carry a website field: osm, hrsa, endgbv), site-level positive rate")
    idx = [i for i, r in enumerate(rows) if r["source"] in ("osm", "hrsa", "endgbv")]
    for label, sel in (("all three", idx), ("osm", [i for i in idx if rows[i]["source"] == "osm"]),
                       ("hrsa", [i for i in idx if rows[i]["source"] == "hrsa"])):
        w = [i for i in sel if rows[i]["has_website"] == "True"]
        nw = [i for i in sel if rows[i]["has_website"] != "True"]
        a, b = sum(y[i] for i in w), sum(y[i] for i in nw)
        print(f"  {label:10} with website {rate(a, len(w))}; without {rate(b, len(nw))}"
              f"; ratio {(a / len(w)) / (b / len(nw)) if w and nw and b else float('nan'):.2f}")
    print("  within category (osm primary_type with enough places on both sides):")
    cats = defaultdict(list)
    for i in idx:
        if rows[i]["source"] == "osm":
            cats[rows[i]["primary_type"]].append(i)
    num = den = 0.0
    for cat, sel in sorted(cats.items(), key=lambda kv: -len(kv[1])):
        w = [i for i in sel if rows[i]["has_website"] == "True"]
        nw = [i for i in sel if rows[i]["has_website"] != "True"]
        if len(w) >= WEBSITE_STRATUM_MIN and len(nw) >= WEBSITE_STRATUM_MIN:
            a, b = sum(y[i] for i in w), sum(y[i] for i in nw)
            print(f"    {cat:32} with {rate(a, len(w)):16} without {rate(b, len(nw))}")
        # Mantel-Haenszel common risk ratio over all categories with both kinds of place
        t = len(w) + len(nw)
        if w and nw:
            num += sum(y[i] for i in w) * len(nw) / t
            den += sum(y[i] for i in nw) * len(w) / t
    print(f"  Mantel-Haenszel risk ratio across all osm primary types: {num / den if den else float('nan'):.2f}")
    print("  within type_field strength (osm):")
    for st in (0.0, 0.5, 1.0):
        sel = [i for i in idx if rows[i]["source"] == "osm" and sigs[i]["type_field"] == st]
        w = [i for i in sel if rows[i]["has_website"] == "True"]
        nw = [i for i in sel if rows[i]["has_website"] != "True"]
        print(f"    type_field {st}: with {rate(sum(y[i] for i in w), len(w))}; without {rate(sum(y[i] for i in nw), len(nw))}")


def threshold_options(rows, y):
    scores = Counter(float(r["relevance_score"]) for r in rows)
    print("\nscore distribution (places):", {k: scores[k] for k in sorted(scores)})
    boroughs = ["Manhattan", "Brooklyn", "Queens", "The Bronx", "Staten Island"]
    for t in THRESHOLD_OPTIONS:
        sel = [i for i, r in enumerate(rows) if float(r["relevance_score"]) >= t]
        pend = [i for i in sel if not rows[i]["_in_guide"] and not rows[i]["_hidden"]]
        n_pos = sum(y)
        got = sum(y[i] for i in sel)
        print(f"\nthreshold {t}: places at or above {len(sel)}; guide-matched among them {got} of {n_pos} "
              f"({got / n_pos:.2f} of guide-matched places); positive rate above {got / max(len(sel), 1):.3f} vs {n_pos / len(rows):.3f} overall")
        print("   rows above that are not in the guide at site level and not hidden (these become pending):")
        by_src = Counter(rows[i]["source"] for i in pend)
        print("   by source:", {s: by_src[s] for s in SOURCES if by_src[s]})
        by_b = Counter(rows[i]["borough"] for i in pend)
        print("   by borough:", {b: by_b[b] for b in boroughs}, "blank:", by_b[""])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true", help="print held-out validation and threshold options")
    ap.add_argument("--out", help=f"default {OUT_CSV}")
    a = ap.parse_args()
    out = Path(a.out) if a.out else OUT_CSV
    nypl = m.read(m.NYPL_CSV)
    aliases = m.load_aliases()
    places = load_places()
    matches = load_matches()
    linked = link_places(places)
    rows = build_rows(places, matches, nypl, aliases, {**read_verdicts(out), **read_queue_verdicts()}, linked=linked)
    write_rows(rows, out)
    print(f"{len(rows)} places -> {out} ({out.stat().st_size / 1e6:.1f} MB)")
    print("hitl_review:", dict(Counter(r["hitl_review"] or "(blank)" for r in rows)))
    if a.validate:
        validate(places, rows, matches, linked[0], nypl, aliases)


if __name__ == "__main__":
    main()
