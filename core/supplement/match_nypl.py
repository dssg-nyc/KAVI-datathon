# /// script
# requires-python = ">=3.10"
# ///
"""Candidate matches between the NYPL Connections Guide rows and any supplementary source.

The NYPL guide (data/kavi_resources.csv) is the human-verified source of truth. A supplementary source
is any data/supplement/<source>.csv in the common schema (COLUMNS_IN below; raw_json holds the source's
own fields, e.g. OSM tags). Output: data/supplement/matches_<source>.csv, one row per candidate pair
(NYPL row x source feature), plus one match_class=no_match row (source_id blank) for every NYPL row that
has no candidate, so the denominators stay visible. is_best marks the top candidate of each NYPL row.

    python3 pipeline/supplement/match_nypl.py --source osm
    flags: --no-address --no-aliases --no-bin switch one kind of evidence off (to measure its contribution)

match_class (best first)
  same_site               same org at the same place: NYPL coordinates, a row_type in SITE_ROW_TYPES, a
                          feature within the proximity radius or at the same address / BIN, and a name
                          that matches (or phone/website corroborating a partly matching name).
  program_at_host         the NYPL row is a program of an org (name split at "-" "--" or an em dash) and the
                          org's feature, or a feature operated by it, is at the same place.
  same_org_other_site     the org matches by name (distinctive tokens) or phone/website but the feature is
                          elsewhere, or the NYPL row has no physical site.
  same_building_unconfirmed  the same address (exact house number + street) or BIN, but no name, phone or
                          domain evidence that it is the same org. Something is in that building; it may
                          or may not be the NYPL org. Never counted as a match.
  no_match                nothing plausible.

Why not name similarity alone. Names are compared as IDF-weighted token sets (weights from both
datasets), after normalizing &/and, possessives, "NY" = "New York", abbreviations in parentheses, the
team's " - 1 (Bronx)" suffixes and "[...]" notes. A state/city swap (NYS vs NYC) is a hard conflict. Shared
generic tokens carry little weight, and a match that is not near the NYPL point needs a token that is rare
in the data (DISTINCT_DF_MAX). Being in the same building proves nothing without a corroborating name,
phone or domain. Domains are not identity when blocklisted or shared by many unrelated features; phone
numbers shared by several features or toll free are not identity either.

Address. House number + street are normalized (76-A = 76A, 104-106 matches 106, St = Street, E = East,
First = 1st, Queens 37-18 kept whole) and must also agree on zip when both have one. Same address is
building-level evidence: it widens "near" and lowers the name threshold to NAME_BUILDING, never to zero.
BIN. NYPL BINs come from NYC GeoSearch (fetch_bins.py cache); a source BIN comes from its `bin` column.

Aliases: data/osm/nypl_aliases.csv (org_name_key, alias, evidence), each backed by the data.

no_match_reason (NYPL rows that end without a site-level match): no_physical_site (hotline, web_only,
cross_reference, mailing_address), outside_nyc, or for mapped rows org_elsewhere_in_osm_only (the org matched,
but elsewhere), named_feature_nearby_unrecognized (a named feature within NEAR_NAMED_M, not recognised),
no_named_feature_nearby, org_not_found (no coordinates to look around).
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
import core.pipeline.supplement.fetch_bins as fetch_bins  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NYPL_CSV = ROOT / "data" / "kavi_resources.csv"
SUPP_DIR = ROOT / "data" / "supplement"
ALIASES_CSV = ROOT / "data" / "osm" / "nypl_aliases.csv"
BIN_CACHE = fetch_bins.CACHE

COLUMNS_IN = ["source", "source_id", "name", "lat", "lon", "borough", "primary_type", "address", "house_number",
              "street", "zip", "phone", "website", "opening_hours", "operator", "last_edit", "url", "bin", "raw_json"]

# ---- thresholds -------------------------------------------------------------------------------
NAME_STRONG = 0.85        # IDF-weighted Jaccard of token sets that counts as "same name" on its own
NAME_CORROBORATED = 0.5   # enough name overlap when a phone or website also matches
CONTAINED_SIM = 0.9       # score given to "the source name is wholly inside the program / site label"
NAME_BUILDING = 0.6       # enough name overlap (with a distinctive shared token) at the same address/BIN
EXACT = 0.999             # token sets equal
DISTINCT_DF_MAX = 25      # a token in <= this many name variants (both datasets) is "distinctive"
GEO_WEIGHT = 0.3          # borough/place tokens count for less
SAME_SITE_M_POINT = 100   # metres, point feature
SAME_SITE_M_AREA = 250    # metres, way/relation (centre of a campus or building outline)
ADDRESS_MAX_M = 600       # an address match this far apart is a different street of the same name
BIN_MAX_M = 300           # a BIN match this far apart is a data error (one building cannot span it)
NEAR_NAMED_M = 50         # a named feature this close to an unmatched NYPL point is "nearby"
DOMAIN_UNRELATED_MIN = 3  # a domain on >= this many features with this many distinct names is shared
PHONE_SHARED_MAX = 2      # a phone on more features than this is a switchboard, not identity
MAX_CANDIDATES = 3
ORG_LEVEL_ONLY_SOURCES = {"irs_eo"}  # filing / mailing addresses, no coordinates: never a site
SITE_ROW_TYPES = {"mapped"}  # row types that are a physical service site
NO_SITE_REASON = {"hotline": "no_physical_site", "web_only": "no_physical_site", "cross_reference": "no_physical_site",
                  "mailing_address": "no_physical_site", "outside_nyc": "outside_nyc"}

STOP = set("the of and inc llc corp corporation co for a an at in on to incorporated ltd".split())
# Low-weight tokens: places, and generic org words. Dropping "center"/"program" outright would make
# "The Hope Program" and "HOPE Center" identical, so they stay but count for little.
GEO = set("new york brooklyn bronx queens manhattan harlem staten island".split())
GENERIC = set("center centre service program project company".split())
SCOPE = {"nyc", "nys"}
ABBREV = {"dept": "department", "ctr": "center", "assn": "association", "assoc": "association",
          "hosp": "hospital", "univ": "university", "intl": "international", "svcs": "services",
          "cmty": "community", "comm": "community"}
BLOCKED_DOMAINS = {  # social media, link hubs, site builders, shared government portals
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com", "youtube.com", "tiktok.com",
    "yelp.com", "linktr.ee", "google.com", "sites.google.com", "eventbrite.com", "wixsite.com",
    "squarespace.com", "blogspot.com", "wordpress.com", "weebly.com", "nychealthandhospitals.org",
    "nyc.gov", "ny.gov", "schools.nyc.gov", "usa.gov", "va.gov", "ssa.gov", "medicare.gov",
}
BLOCKED_SUFFIXES = (".nyc.gov", ".ny.gov")
TOLL_FREE = {"800", "833", "844", "855", "866", "877", "888"}

TEAM_SUFFIX = re.compile(r"\s+-\s*\d+\s*(\([^()]*\))?\s*$|\s*\([^()]*\blisting\)\s*$", re.I)
TEAM_LABEL = re.compile(r"\s+-\s*\d+\s*\(([^()]*)\)\s*$")  # the site label in "Name - 2 (Broadway Family Health Center)"
DASH_SPLIT = re.compile(r"\s*(?:—|--|\s–\s)\s*")
ABBR_PAREN = re.compile(r"^[A-Z][A-Z0-9:&.\-]{1,11}$")
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.\-]*)?\(?(\d{3})\)?[\s.\-]*(\d{3})[\s.\-]*(\d{4})(?!\d)")
RANK = {"same_site": 0, "program_at_host": 1, "same_org_other_site": 2, "same_building_unconfirmed": 3}


# ---- names ------------------------------------------------------------------------------------
def stem(t):
    return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t


def tokens(text):
    """Normalized token set (frozenset). Scope tokens nyc/nys are kept; stopwords dropped."""
    s = (text or "").lower().replace("’", "'").replace("‘", "'")
    s = re.sub(r"'s\b", "s", s).replace("'", "")
    s = s.replace("&", " and ").replace("+", " and ")
    s = re.sub(r"\bu\.\s?s\.?(?=\W|$)", " us ", s)  # "U.S." = "US"
    s = re.sub(r"\bnew york state\b|\bstate of new york\b|\bny state\b|\bnys\b", " nys ", s)
    s = re.sub(r"\bnew york city\b|\bcity of new york\b|\bnyc\b", " nyc ", s)
    out = []
    for t in re.sub(r"[^a-z0-9]+", " ", s).split():
        if t == "ny":
            out += ["new", "york"]
            continue
        t = stem(ABBREV.get(t, t))
        if t not in STOP and t != "s":
            out.append(t)
    return frozenset(out)


def name_key(raw):
    """Readable key of an NYPL parent org name: head only, no team suffix / brackets / parentheses."""
    s = re.sub(r"\[[^\]]*\]", " ", raw or "")
    s = TEAM_SUFFIX.sub("", s.strip()).strip()
    head = DASH_SPLIT.split(s, maxsplit=1)[0]
    head = re.sub(r"\([^()]*\)", " ", head).lower().replace("’", "'").replace("'", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", head).split())


def load_aliases(path=ALIASES_CSV):
    out = defaultdict(list)
    if path.exists():
        for r in csv.DictReader(path.open(encoding="utf-8")):
            if r.get("org_name_key") and r.get("alias"):
                out[r["org_name_key"].strip().lower()].append(tokens(r["alias"]))
    return out


def parse_nypl_name(raw, aliases=None):
    """-> dict(parent, aliases (short, abbreviations), long_aliases, program, has_prog, full, key)."""
    s = re.sub(r"\[[^\]]*\]", " ", raw or "")
    lm = TEAM_LABEL.search(s.strip())
    label = tokens(lm.group(1)) if lm else frozenset()
    s = TEAM_SUFFIX.sub("", s.strip()).strip()
    head, *rest = DASH_SPLIT.split(s, maxsplit=1)
    program_text = rest[0] if rest else ""
    # "NYCHA--Jobs-Plus -- BronxWorks": the last segment is the partner org that runs the site
    partner = tokens(re.sub(r"\([^()]*\)", " ", DASH_SPLIT.split(program_text)[-1])) if DASH_SPLIT.search(program_text) else frozenset()
    short, kept = [], []
    # parenthesised abbreviations are aliases; other parenthesised notes are program text
    for m in re.finditer(r"\(([^()]*)\)", head):
        inner = m.group(1).strip()
        if ABBR_PAREN.match(inner) or inner.lower().startswith("the "):  # "(NYPL)", "(The Center)"
            short.append(tokens(inner))
        elif inner:
            kept.append(inner)
    head = re.sub(r"\([^()]*\)", " ", head)
    program_text = " ".join([program_text, *kept]).strip()
    parent = tokens(head)
    program = tokens(program_text) if program_text else None
    full = tokens(f"{head} {program_text}")
    key = name_key(raw)
    long_aliases = []
    for a in (aliases or {}).get(key, ()):
        (short if len(a) == 1 and len(next(iter(a))) <= 5 else long_aliases).append(a)
    return {"parent": parent, "aliases": [a for a in short if a], "long_aliases": long_aliases,
            "program": program or None, "has_prog": bool(program), "full": full, "key": key,
            "label": label, "partner": partner}


def source_variants(row, raw):
    """-> list of (kind, tokens). kind: name | operator."""
    out = []
    names = [row["name"]] + [v for k in ("alt_name", "short_name", "official_name", "old_name")
                             for v in re.split(r";", str(raw.get(k, ""))) if v.strip()]
    for nm in names:
        nm = nm.strip()
        base = re.sub(r"\([^()]*\)", " ", nm)
        out.append(("name", tokens(base)))
        for m in re.finditer(r"\(([^()]*)\)", nm):
            if ABBR_PAREN.match(m.group(1).strip()):
                out.append(("name", tokens(m.group(1))))
    for v in (row.get("operator") or raw.get("operator", ""), raw.get("brand", "")):
        if v and str(v).strip():
            out.append(("operator", tokens(str(v))))
    return [(k, t) for k, t in out if t]


# ---- phone / domain / geometry -----------------------------------------------------------------
def phones(text):
    out = set()
    for m in PHONE.finditer(text or ""):
        if m.group(1) not in TOLL_FREE:
            out.add("".join(m.groups()))
    return out


def _reg_domain(host):
    if host in BLOCKED_DOMAINS or host.endswith(BLOCKED_SUFFIXES):
        return ""
    reg = ".".join(host.split(".")[-2:])
    return "" if reg in BLOCKED_DOMAINS else reg


def domains(text):
    """All usable registrable domains in a (possibly multi-URL) website field."""
    return {d for h in re.findall(r"(?:https?://)?(?:www\d?\.)?([a-z0-9][a-z0-9.\-]*\.[a-z]{2,})", (text or "").lower())
            if (d := _reg_domain(h))}


def domain(url):
    """First usable domain, or ''."""
    m = re.search(r"(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9.\-]*\.[a-z]{2,})", (url or "").lower())
    return _reg_domain(m.group(1)) if m else ""


def metres(a_lat, a_lon, b_lat, b_lon):
    r = math.radians
    return 6371000 * math.hypot(r(b_lon - a_lon) * math.cos(r((a_lat + b_lat) / 2)), r(b_lat - a_lat))


# ---- addresses ----------------------------------------------------------------------------------
ORDINAL_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
                 "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12}
STREET_ABBR = {"st": "street", "str": "street", "ave": "avenue", "av": "avenue", "aven": "avenue", "blvd": "boulevard",
               "bld": "boulevard", "rd": "road", "pl": "place", "dr": "drive", "sq": "square", "ct": "court",
               "pkwy": "parkway", "pky": "parkway", "hwy": "highway", "ln": "lane", "ter": "terrace",
               "terr": "terrace", "plz": "plaza", "tpke": "turnpike", "expy": "expressway", "bway": "broadway",
               "cir": "circle", "pk": "park", "hts": "heights", "mt": "mount", "ft": "fort"}
DIRECTION = {"e": "east", "w": "west", "n": "north", "s": "south"}
STREET_ALIAS = {"avenue of the americas": "6th avenue", "sixth avenue": "6th avenue"}


def ordinal(n):
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def norm_street(text):
    s = (text or "").lower().replace("&", " and ")
    s = re.sub(r"\b(suite|ste|floor|fl|room|rm|unit|apt)\b.*$", "", s)  # trailing unit text
    toks = re.sub(r"[^a-z0-9 ]+", " ", s).split()
    out = []
    for i, t in enumerate(toks):
        if t == "st" and i == 0 and len(toks) > 2:
            out.append("saint")
        elif t in DIRECTION and i == 0 and len(toks) > 2:
            out.append(DIRECTION[t])
        elif t in ORDINAL_WORDS:
            out.append(ordinal(ORDINAL_WORDS[t]))
        elif re.fullmatch(r"\d+", t) and i + 1 < len(toks) and toks[i + 1] in ("street", "st", "avenue", "ave", "av") \
                and not (i == 0 and False):
            out.append(ordinal(int(t)))  # "5 Avenue" = "5th Avenue"
        elif t in STREET_ABBR and i > 0:
            out.append(STREET_ABBR[t])
        else:
            out.append(t)
    key = " ".join(out)
    key = re.sub(r"^(\d+)(?:st|nd|rd|th)(?= )", r"\1th", key)  # ordinals compare by number below
    return STREET_ALIAS.get(re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", lambda m: ordinal(int(m.group(1))), key),
                            re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", lambda m: ordinal(int(m.group(1))), key))


def house_numbers(text):
    """-> set of comparable house-number forms. 76-A = 76A = 76; 104-106 -> {104, 106}; Queens 37-18 whole."""
    forms = set()
    for part in re.split(r"[;,/]|\band\b", (text or "").upper().replace("–", "-").replace("—", "-")):
        p = re.sub(r"[^0-9A-Z\-]", "", part).strip("-")
        if not p:
            continue
        m = re.fullmatch(r"(\d+)-(\d+)[A-Z]?", p)
        if m:
            x, y = m.group(1), m.group(2)
            if int(x) >= 100 and int(y) > int(x) and int(y) - int(x) <= 20 and len(x) == len(y):
                forms |= {x, y}  # a range of one street's numbers
            else:
                forms.add(f"{int(x)}-{y}")  # Queens-style grid number, kept whole
                if int(x) < 100:
                    forms.add(f"{int(x)}{y}")  # written without the hyphen
            continue
        m = re.fullmatch(r"(\d+)-?[A-Z]{0,2}", p)
        if m:
            forms.add(str(int(m.group(1))))
    return forms


def parse_address(house, street, zipc, address=""):
    """-> (house number forms, street key, zip5) or None when there is no usable house number + street."""
    if (not house or not street) and address:
        m = re.match(r"\s*(\d[\dA-Za-z\-–]*)\s+([^,]+)", address)
        if m:
            house, street = house or m.group(1), street or m.group(2)
    if street and not house:
        m = re.match(r"\s*(\d[\dA-Za-z\-–]*)\s+(.+)", street)
        if m:
            house, street = m.group(1), m.group(2)
    hn, st = house_numbers(house), norm_street(street)
    if not hn or not st:
        return None
    z = re.search(r"\b(\d{5})\b", zipc or "")
    return hn, st, z.group(1) if z else ""


def same_address(a, b):
    if not a or not b:
        return False
    if not (a[0] & b[0]) or a[1] != b[1]:
        return False
    return not (a[2] and b[2] and a[2] != b[2])


# ---- context ----------------------------------------------------------------------------------
class Ctx:
    def __init__(self, nypl_rows, src_rows, bins=None, aliases=None, use_address=True, use_bin=True):
        self.use_address, self.use_bin = use_address, use_bin
        self.nypl = [prep_nypl(r, bins, aliases) for r in nypl_rows]
        self.src = [prep_src(r) for r in src_rows]
        df = Counter()
        for o in self.src:
            df.update({t for _, ts in o["variants"] for t in ts if _ == "name"})
        for n in self.nypl:
            df.update(n["parent"])
        self.df = df
        self.n_docs = len(self.src) + len(self.nypl)
        # shared-phone and shared-domain blocklists, derived from the data
        pc = Counter(p for o in self.src for p in o["phones"])
        self.bad_phones = {p for p, c in pc.items() if c > PHONE_SHARED_MAX}
        dn = defaultdict(set)
        for o in self.src:
            if o["domain"]:
                dn[o["domain"]].add(frozenset(o["variants"][0][1]) if o["variants"] else frozenset())
        self.bad_domains = {d for d, names in dn.items() if len(names) >= DOMAIN_UNRELATED_MIN}
        nd = defaultdict(set)
        for n in self.nypl:
            for d in n["domains"]:
                nd[d].add(n["parent"])
        self.bad_domains |= {d for d, names in nd.items() if len(names) >= DOMAIN_UNRELATED_MIN}
        self.idx_tok, self.idx_phone, self.idx_dom = defaultdict(list), defaultdict(list), defaultdict(list)
        self.idx_addr, self.idx_bin, self.grid = defaultdict(list), defaultdict(list), defaultdict(list)
        for i, o in enumerate(self.src):
            for t in {t for _, ts in o["variants"] for t in ts}:
                self.idx_tok[t].append(i)
            for p in o["phones"] - self.bad_phones:
                self.idx_phone[p].append(i)
            if o["domain"] and o["domain"] not in self.bad_domains:
                self.idx_dom[o["domain"]].append(i)
            if o["addr"] and o["row"]["source"] not in ORG_LEVEL_ONLY_SOURCES:
                self.idx_addr[o["addr"][1]].append(i)
            if o["bin"]:
                self.idx_bin[o["bin"]].append(i)
            if o["lat"] is not None:
                self.grid[(round(o["lat"] / 0.001), round(o["lon"] / 0.001))].append(i)

    def weight(self, t):
        w = math.log(1 + self.n_docs / max(self.df.get(t, 1), 1))
        return w * GEO_WEIGHT if (t in GEO or t in GENERIC) else w

    def sim(self, a, b):
        """IDF-weighted Jaccard with the NYS/NYC conflict rule. Returns (sim, shared tokens)."""
        if not a or not b:
            return 0.0, frozenset()
        sa, sb = a & SCOPE, b & SCOPE
        if sa and sb and sa != sb:
            return 0.0, frozenset()
        shared = a & b
        if not shared:
            return 0.0, shared
        num = sum(self.weight(t) for t in shared)
        den = sum(self.weight(t) for t in a | b)
        return num / den, shared

    def distinctive(self, shared):
        return any(self.df.get(t, 1) <= DISTINCT_DF_MAX and t not in GEO and t not in GENERIC
                   and t not in SCOPE for t in shared)

    def candidates(self, n):
        c = set()
        for t in n["all_tokens"]:
            c.update(self.idx_tok.get(t, ()))
        for p in n["phones"] - self.bad_phones:
            c.update(self.idx_phone.get(p, ()))
        for d in n["domains"] - self.bad_domains:
            c.update(self.idx_dom.get(d, ()))
        if self.use_address and n["addr"] and n["site"]:
            c.update(self.idx_addr.get(n["addr"][1], ()))
        if self.use_bin and n["bin"] and n["site"]:
            c.update(self.idx_bin.get(n["bin"], ()))
        return sorted(c)

    def nearest(self, n, max_m=NEAR_NAMED_M):
        """Nearest named source feature within max_m of the NYPL point -> (metres, row) or None."""
        if n["lat"] is None:
            return None
        ci, cj = round(n["lat"] / 0.001), round(n["lon"] / 0.001)
        best = None
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for i in self.grid.get((ci + di, cj + dj), ()):
                    o = self.src[i]
                    d = metres(n["lat"], n["lon"], o["lat"], o["lon"])
                    if d <= max_m and (best is None or d < best[0]):
                        best = (d, o["row"])
        return best


def prep_nypl(r, bins=None, aliases=None):
    p = parse_nypl_name(r.get("organization_name", ""), aliases)
    lat, lon = r.get("latitude", ""), r.get("longitude", "")
    p.update(row=r, phones=phones(r.get("phone_number", "")), domains=domains(r.get("website", "")),
             lat=float(lat) if lat else None, lon=float(lon) if lon else None)
    p["site"] = r.get("row_type") in SITE_ROW_TYPES and p["lat"] is not None
    p["addr"] = parse_address(r.get("street_number", ""), r.get("street", ""), r.get("zip_code", "")) \
        if r.get("row_type") in SITE_ROW_TYPES else None
    p["bin"] = (bins or {}).get(fetch_bins.address_query(r), "") if p["site"] else ""
    p["all_tokens"] = p["parent"] | p["full"] | (p["program"] or frozenset()) | frozenset().union(
        *p["aliases"], *p["long_aliases"], p["label"], p["partner"])
    return p


HIDDEN_LOCATION_COLS = ("address", "house_number", "street", "zip", "lat", "lon", "bin", "url")


def is_hidden_location(row, raw):
    """ENDGBV programs whose address the publisher withholds (display_physical_address != Yes)."""
    return row.get("source") == "endgbv" and str(raw.get("display_physical_address", "")).strip().lower() != "yes"


def prep_src(r):
    raw = json.loads(r.get("raw_json") or "{}")
    if is_hidden_location(r, raw):  # belt and braces: the fetch already blanks these
        r = {**r, **{c: "" for c in HIDDEN_LOCATION_COLS}}
    located = bool(r.get("lat") and r.get("lon"))  # a row with only one of the two is not located
    return {"row": r, "raw": raw, "variants": source_variants(r, raw), "phones": phones(r.get("phone", "")),
            "domain": domain(r.get("website", "")), "lat": float(r["lat"]) if located else None,
            "lon": float(r["lon"]) if located else None,
            "addr": parse_address(r.get("house_number", ""), r.get("street", ""), r.get("zip", ""), r.get("address", "")),
            "bin": re.sub(r"\D", "", r.get("bin", "") or ""),
            "radius": SAME_SITE_M_AREA if r["source_id"].startswith(("way/", "relation/")) else SAME_SITE_M_POINT}


# ---- evaluation -------------------------------------------------------------------------------
def best_sim(ctx, left, o, kinds):
    """Best (sim, shared, left-label, kind) of `left` [(label, tokens)] vs the source variants of `kinds`."""
    best = (0.0, frozenset(), "", "")
    for lab, lt in left:
        for kind, ot in o["variants"]:
            if kind in kinds:
                s, sh = ctx.sim(lt, ot)
                if s > best[0]:
                    best = (s, sh, lab, kind)
    return best


def contained(ctx, left, o):
    """The source name, minus place/generic words, is wholly inside `left` (a program or site label of the
    NYPL name) and has a distinctive token: "Mainchance" inside "Mainchance Drop-In Center". -> (sim, shared)."""
    best = (0.0, frozenset())
    for kind, ot in o["variants"]:
        core = ot - GEO - GENERIC - SCOPE
        if kind == "name" and core and core <= left and ctx.distinctive(core) and len(core) / len(left - GEO - GENERIC) >= 0.34:
            best = max(best, (CONTAINED_SIM, frozenset(core)), key=lambda b: b[0])
    return best


def host_label(n, lab):
    """A site label or partner name matched on a row that is a program of an org: the feature is the host."""
    return lab == "partner" or (n["has_prog"] and lab in ("label", "parent+label", "label-contains"))


def evaluate(ctx, n, o):
    """Classify one NYPL x source pair. -> dict or None."""
    dist = metres(n["lat"], n["lon"], o["lat"], o["lon"]) if n["site"] and o["lat"] is not None else None
    orgonly = o["row"]["source"] in ORG_LEVEL_ONLY_SOURCES
    unlocated_ok = dist is None and not orgonly and n["site"] and bool(o["addr"] and o["addr"][2] and n["addr"] and n["addr"][2])
    addr = bool(ctx.use_address and n["site"] and not orgonly and same_address(n["addr"], o["addr"])
                and (unlocated_ok if dist is None else dist <= ADDRESS_MAX_M))
    binm = bool(ctx.use_bin and n["site"] and n["bin"] and n["bin"] == o["bin"] and dist is not None and dist <= BIN_MAX_M)
    bldg = addr or binm
    near = (dist is not None and dist <= o["radius"]) or bldg
    phone = bool((n["phones"] & o["phones"]) - ctx.bad_phones)
    web = bool(o["domain"] and o["domain"] in n["domains"] and o["domain"] not in ctx.bad_domains)
    alias = [("alias", a) for a in n["aliases"]]
    long_alias = [("alias", a) for a in n["long_aliases"]]
    if n["has_prog"]:
        site_left = [("full", n["full"]), ("program", n["program"])]
        site_kinds = {"name"}
    else:  # the NYPL name is the entity itself; the source operator may name it too
        site_left = [("parent", n["parent"])] + alias + long_alias
        site_kinds = {"name", "operator"}
    if n["label"]:  # the guide's own label for this site, e.g. "(Broadway Family Health Center)"
        site_left += [("label", n["label"]), ("parent+label", n["parent"] | n["label"])]
    if n["partner"]:
        site_left += [("partner", n["partner"])]
    s_site, sh_site, lab_site, kind_site = best_sim(ctx, site_left, o, site_kinds)
    for lab, left in (("program", n["program"]), ("label", n["label"])):
        if left:
            cs, csh = contained(ctx, left, o)
            if cs > s_site:
                s_site, sh_site, lab_site, kind_site = cs, csh, f"{lab}-contains", "name"
    org_left = [("parent", n["parent"])] + alias + long_alias
    s_org, sh_org, lab_org, kind_org = best_sim(ctx, org_left, o, {"name", "operator"})
    # an abbreviation ("TLC", "CFR") names many orgs: it counts only with proximity or a phone/website
    s_far, sh_far, lab_far, kind_far = best_sim(ctx, [("parent", n["parent"])] + long_alias, o, {"name", "operator"})
    corro = phone or web

    def ok_guard(sim, shared, require_distinct):
        return sim >= NAME_STRONG and (ctx.distinctive(shared) or (not require_distinct and sim >= EXACT))

    cls = sim = basis = None
    if near:
        if ok_guard(s_site, sh_site, False):
            # a feature that only carries the org as operator is the org's, not the same entity
            cls = "program_at_host" if (kind_site == "operator" or host_label(n, lab_site)) else "same_site"
            sim, basis = s_site, f"{lab_site}~{kind_site}"
        elif (corro and max(s_site, s_org) >= NAME_CORROBORATED) or (phone and web):  # phone+website alone suffice
            if n["has_prog"] and s_site < NAME_CORROBORATED:
                cls, sim, basis = "program_at_host", s_org, f"{lab_org}~{kind_org}"
            elif s_site >= s_org:
                cls, sim, basis = ("program_at_host" if (kind_site == "operator" or host_label(n, lab_site)) else "same_site"), s_site, f"{lab_site}~{kind_site}"
            else:
                cls, sim, basis = ("program_at_host" if kind_org == "operator" else "same_site"), s_org, f"{lab_org}~{kind_org}"
        elif n["has_prog"] and ok_guard(s_org, sh_org, False):
            cls, sim, basis = "program_at_host", s_org, f"{lab_org}~{kind_org}"
        elif bldg and corro:  # same building and the same phone or website
            cls, sim, basis = ("program_at_host" if n["has_prog"] else "same_site"), max(s_site, s_org), "building+" + ("phone" if phone else "website")
        elif bldg and s_site >= NAME_BUILDING and ctx.distinctive(sh_site):
            cls, sim, basis = ("program_at_host" if (kind_site == "operator" or host_label(n, lab_site)) else "same_site"), s_site, f"{lab_site}~{kind_site}"
        elif bldg and s_org >= NAME_BUILDING and ctx.distinctive(sh_org):
            cls = "program_at_host" if (n["has_prog"] or kind_org == "operator") else "same_site"
            sim, basis = s_org, f"{lab_org}~{kind_org}"
    if cls is None:
        if ok_guard(s_far, sh_far, True) or (s_far >= EXACT and len(n["parent"]) >= 2):
            cls, sim, basis = "same_org_other_site", s_far, f"{lab_far}~{kind_far}"
        elif corro and s_org >= NAME_CORROBORATED:
            cls, sim, basis = "same_org_other_site", s_org, f"{lab_org}~{kind_org}"
        elif phone and web and s_org >= 0.3 and ctx.distinctive(sh_org):
            cls, sim, basis = "same_org_other_site", s_org, f"{lab_org}~{kind_org}"
    if cls is None and bldg:
        # the same building and nothing else. Reject if the data says it is a different org
        scope_clash = any((a & SCOPE) and (b & SCOPE) and (a & SCOPE) != (b & SCOPE)
                          for _, a in org_left for _, b in o["variants"])
        domain_clash = bool(n["domains"] and o["domain"] and o["domain"] not in n["domains"])
        if not scope_clash and not domain_clash:
            cls, sim, basis = "same_building_unconfirmed", max(s_site, s_org), "building only"
    if cls is None:
        return None
    reasons = [f"name {sim:.2f} ({basis})"]
    if dist is None and addr:
        reasons.append("source row has no coordinates")
    if dist is not None:
        reasons.append(f"{dist:.0f}m{'' if near else ' (outside radius)'}")
    if addr:
        reasons.append("same address")
    if binm:
        reasons.append("same BIN")
    if phone:
        reasons.append("phone")
    if web:
        reasons.append("website")
    if cls == "program_at_host":
        reasons.append("NYPL row is a program of the matched org")
    if cls == "same_building_unconfirmed":
        reasons.append("no name/phone/domain evidence that this is the NYPL org")
    score = sim + 0.5 * phone + 0.5 * web + 0.2 * addr + 0.2 * binm - (dist or 0) / 10000
    return {"class": cls, "sim": sim, "basis": basis, "dist": dist, "phone": phone, "web": web, "addr": addr,
            "bin": binm, "reason": "; ".join(reasons), "score": score}


def miss_reason(ctx, n, best_class):
    """Why an NYPL row has no site-level match ('' when it has one)."""
    if best_class in ("same_site", "program_at_host"):
        return "", None
    rt = n["row"].get("row_type", "")
    if rt in NO_SITE_REASON:
        return NO_SITE_REASON[rt], None
    if rt not in SITE_ROW_TYPES:
        return "no_physical_site", None
    if best_class == "same_org_other_site":
        return "org_elsewhere_in_osm_only", ctx.nearest(n)
    if n["lat"] is None:
        return "org_not_found", None
    near = ctx.nearest(n)
    return ("named_feature_nearby_unrecognized" if near else "no_named_feature_nearby"), near


def match_all(ctx):
    rows = []
    for n in ctx.nypl:
        found = []
        for i in ctx.candidates(n):
            o = ctx.src[i]
            res = evaluate(ctx, n, o)
            if res:
                found.append((RANK[res["class"]], -res["score"], o["row"]["source_id"], o, res))
        found.sort(key=lambda x: x[:3])
        r = n["row"]
        best_class = found[0][4]["class"] if found else "no_match"
        reason, near = miss_reason(ctx, n, best_class)
        base = {"nypl_id": r["id"], "resource_id": r.get("resource_id", ""), "nypl_name": r.get("organization_name", ""),
                "row_type": r.get("row_type", ""), "no_match_reason": reason,
                "nearest_feature_m": "" if not near else round(near[0]), "nearest_feature": "" if not near else near[1]["name"]}
        blank = {"source": "", "source_id": "", "match_name": "", "match_primary_type": "", "match_borough": "",
                 "match_class": "no_match", "is_best": False, "name_sim": "", "name_basis": "", "distance_m": "",
                 "phone_match": "", "website_match": "", "address_match": "", "bin_match": "", "n_candidates": 0,
                 "match_reason": "no candidate", "match_url": ""}
        if not found:
            rows.append({**base, **blank})
            continue
        for k, (_, _, _, o, res) in enumerate(found[:MAX_CANDIDATES]):
            orow = o["row"]
            rows.append({**base, "source": orow["source"], "source_id": orow["source_id"], "match_name": orow["name"],
                         "match_primary_type": orow["primary_type"], "match_borough": orow["borough"],
                         "match_class": res["class"], "is_best": k == 0, "name_sim": round(res["sim"], 3),
                         "name_basis": res["basis"], "distance_m": "" if res["dist"] is None else round(res["dist"]),
                         "phone_match": res["phone"], "website_match": res["web"], "address_match": res["addr"],
                         "bin_match": res["bin"], "n_candidates": len(found), "match_reason": res["reason"],
                         "match_url": orow["url"]})
    return rows


COLUMNS = ["nypl_id", "resource_id", "nypl_name", "row_type", "source", "source_id", "match_name", "match_primary_type",
           "match_borough", "match_class", "is_best", "name_sim", "name_basis", "distance_m", "phone_match",
           "website_match", "address_match", "bin_match", "n_candidates", "match_reason", "match_url",
           "no_match_reason", "nearest_feature_m", "nearest_feature"]


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_bins():
    if not BIN_CACHE.exists():
        return {}
    return {r["query"]: r["bin"] for r in read(BIN_CACHE) if r["bin"]}


def summary(rows):
    best = [r for r in rows if r["is_best"] in (True, "True") or r["match_class"] == "no_match"]
    mapped = [r for r in best if r["row_type"] == "mapped"]
    return Counter(r["match_class"] for r in mapped), Counter(r["match_class"] for r in best)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="osm", help="data/supplement/<source>.csv")
    ap.add_argument("--no-address", action="store_true")
    ap.add_argument("--no-aliases", action="store_true")
    ap.add_argument("--no-bin", action="store_true")
    ap.add_argument("--out", help="default data/supplement/matches_<source>.csv")
    a = ap.parse_args()
    src_path = SUPP_DIR / f"{a.source}.csv"
    out_path = Path(a.out) if a.out else SUPP_DIR / f"matches_{a.source}.csv"
    nypl, src = read(NYPL_CSV), read(src_path)
    missing = [c for c in COLUMNS_IN if src and c not in src[0]]
    if missing:
        raise SystemExit(f"{src_path} lacks columns {missing}")
    ctx = Ctx(nypl, src, bins=None if a.no_bin else load_bins(), aliases=None if a.no_aliases else load_aliases(),
              use_address=not a.no_address, use_bin=not a.no_bin)
    rows = match_all(ctx)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        w.writerows(rows)
    mapped, allrows = summary(rows)
    print(f"{len(nypl)} NYPL rows x {len(src)} {a.source} features -> {len(rows)} rows in {out_path}")
    print("blocked domains (derived):", len(ctx.bad_domains), " blocked phones (derived):", len(ctx.bad_phones))
    print("mapped rows (400), best class:", dict(mapped))
    print("all rows, best class:", dict(allrows))
    best = [r for r in rows if r["is_best"] or r["match_class"] == "no_match"]
    print("no_match_reason:", dict(Counter(r["no_match_reason"] or "(site-level match)" for r in best)))
    for cls in RANK:
        print(f"unique features in any {cls} pair:", len({r["source_id"] for r in rows if r["match_class"] == cls}))


if __name__ == "__main__":
    main()
