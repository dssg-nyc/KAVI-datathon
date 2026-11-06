# /// script
# requires-python = ">=3.10"
# ///
"""Fetches non-OSM candidate sources and normalizes each to data/supplement/<source>.csv.

Sources carry a service or facility type, which OSM rarely does. This script only fetches and
normalizes; matching to NYPL rows is a later stage.

    python3 core/supplement/fetch_sources.py [source ...]       (no arguments = every source)
    python3 core/supplement/fetch_sources.py --list
    python3 core/supplement/fetch_sources.py --cache DIR --out DIR facdb

Standard library only. Downloads go to a fresh directory under the system temp dir (or --cache,
which must be new or empty) and are treated as untrusted data: they are only parsed as CSV/JSON.
Requests use the repo's generic User-Agent, no keys, one request every REQUEST_DELAY seconds.
If Python's own TLS store cannot verify a host, the download falls back to the system curl.

Output columns: source, source_id, name, lat, lon, borough, primary_type, address, house_number,
street, zip, phone, website, opening_hours, operator, last_edit, url, bin, raw_json.
raw_json is the source's own fields (empty values and fields already copied into a column are
left out, geometry is dropped), so the service/type fields stay available. Rows are NYC only,
sorted by source_id, boroughs spelled Manhattan, Brooklyn, Queens, The Bronx, Staten Island.
Blank means the source does not have it. BINs ending in 000000 are NYC's "unknown building"
placeholders and are blanked.

Sources and terms (accessed 2026-11-05; each SOURCES entry repeats these). Verification means the
wording was read on the publisher's own page, not inferred.

  source         publisher / dataset                          terms                                  verified
  facdb          NYC DCP Facilities Database (ji82-xba5)      NYC OpenData Terms of Use (see below)  partial
  irs_eo         IRS Exempt Orgs Business Master File, NY     no licence stated (IRC 6104 public)    no statement
  omh            NYS OMH Local Mental Health Programs         OPEN-NY Terms of Use (see below)       yes
  doh_childcare  NYC DOHMH Active Child Care Programs         NYC OpenData Terms of Use              partial
  dycd           NYC DYCD Program Sites                       NYC OpenData Terms of Use              partial
  endgbv         NYC ENDGBV Resource Directory                NYC OpenData Terms of Use              partial
  workforce1     NYC SBS Workforce1 Center & Service Locs     NYC OpenData Terms of Use              partial
  hrsa           HRSA Health Center Service Delivery Sites    page lists "Usage limitations: None"   no licence text
  cms_otp        CMS OTP Providers (data.cms.gov)             license field in the dataset's data.json: https://www.usa.gov/government-works

OPEN-NY (read from the NYS PDF): "So long as you are not doing anything malicious with NYS data, you
may use it as you wish, subject to no other requirements." The terms "do not contain restrictions
requiring members of the public to use attribution ... nor require the public to obtain pre-approval
before re-use". Other terms "may be imposed specifically on specific Content".

NYC OpenData: the nyc.gov/html/data/terms.html page and opendata.cityofnewyork.us answer automated
requests with 403 and archive copies were unavailable, so the full Terms of Use were NOT read. What
was read is NYC's Open Data Technical Standards Manual, which says "By accessing data sets and feeds
available through the NYC OpenData portal ... the user agrees to all of the Terms of Use of NYC.gov as
well as the NYC.gov Privacy Policy" and that re-publishers should identify source, version and
modifications. Permission for the NYC sources is therefore unverified; confirm before redistributing.

Regeneration: data/supplement/.gitignore leaves out every downloaded source except osm.csv. Rebuild them with
`python3 core/supplement/fetch_sources.py` (network needed); name sources to fetch only those.

Skipped: OASAS (no bulk directory; the provider directory is an HTML search tool), SAMHSA
(findtreatment.gov is a search tool; the data.gov entry links only to it; CMS's OTP list stands in). Findhelp and 211 are
not used.
"""

import argparse
import csv
import json
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "supplement"
USER_AGENT = "KAVI-datathon resource map (github.com/dssg-nyc/KAVI-datathon)"  # as in extract_all.py
REQUEST_DELAY = 1.5
ACCESSED = "2026-11-05"

COLUMNS = ["source", "source_id", "name", "lat", "lon", "borough", "primary_type", "address", "house_number",
           "street", "zip", "phone", "website", "opening_hours", "operator", "last_edit", "url", "bin", "raw_json"]

NYC_PORTAL = "https://data.cityofnewyork.us"
NYC_TERMS = "NYC Open Data terms of use (https://www.nyc.gov/html/data/terms.html); dataset has no licence field"

BOROUGH_NAMES = {
    "MANHATTAN": "Manhattan", "NEW YORK": "Manhattan", "NEW YORK COUNTY": "Manhattan", "MN": "Manhattan",
    "BROOKLYN": "Brooklyn", "KINGS": "Brooklyn", "KINGS COUNTY": "Brooklyn", "BK": "Brooklyn",
    "QUEENS": "Queens", "QUEENS COUNTY": "Queens", "QN": "Queens",
    "BRONX": "The Bronx", "THE BRONX": "The Bronx", "BRONX COUNTY": "The Bronx", "BX": "The Bronx",
    "STATEN ISLAND": "Staten Island", "RICHMOND": "Staten Island", "RICHMOND COUNTY": "Staten Island",
    "SI": "Staten Island",
}
BOROUGHS = ["Manhattan", "Brooklyn", "Queens", "The Bronx", "Staten Island"]


# ---------------------------------------------------------------------------------------------
# Normalizing helpers
# ---------------------------------------------------------------------------------------------

def s(v) -> str:
    """Any value to a trimmed single-line string; None and 'NULL' become blank."""
    if v is None:
        return ""
    v = re.sub(r"\s+", " ", str(v)).strip()
    return "" if v.upper() in ("NULL", "NAN", "N/A") else v


def norm_borough(v) -> str:
    return BOROUGH_NAMES.get(s(v).upper(), "")


def zip5(v) -> str:
    m = re.match(r"\d{5}", s(v))
    return m.group(0) if m else ""


def borough_from_zip(z) -> str:
    """NYC borough for a ZIP, '' if the ZIP is outside the five boroughs."""
    z = zip5(z)
    if not z:
        return ""
    n = int(z)
    if 10001 <= n <= 10282:
        return "Manhattan"
    if 10301 <= n <= 10314:
        return "Staten Island"
    if 10451 <= n <= 10475:
        return "The Bronx"
    if 11201 <= n <= 11256:
        return "Brooklyn"
    if n in (11004, 11005) or 11101 <= n <= 11109 or 11351 <= n <= 11436 or 11691 <= n <= 11697:
        return "Queens"
    return ""


def num(v, lo, hi) -> str:
    """A coordinate as text if it parses and lies in a plausible NYC box, else blank."""
    try:
        f = float(s(v))
    except ValueError:
        return ""
    return repr(round(f, 7)) if lo <= f <= hi else ""


def lat_(v) -> str:
    return num(v, 40.3, 41.0)


def lon_(v) -> str:
    return num(v, -74.5, -73.5)


def clean_bin(v) -> str:
    b = s(v)
    b = b.split(".")[0] if re.fullmatch(r"\d+\.0+", b) else b
    return "" if not re.fullmatch(r"[1-5]\d{6}", b) or b.endswith("000000") else b


def split_address(addr: str) -> tuple[str, str]:
    """('123', 'MAIN ST') from '123 MAIN ST'; ('', addr) when no leading house number."""
    m = re.match(r"^(\d[\w\-/]*)\s+(.+)$", addr)
    return (m.group(1), m.group(2)) if m else ("", addr)


def phone_(v) -> str:
    return s(v)


def raw_json(rec: dict, drop=()) -> str:
    skip = set(drop)
    out = {k: s(v) if not isinstance(v, (dict, list)) else v for k, v in rec.items()
           if k not in skip and not k.startswith(":@") and v not in (None, "") and s(v) != ""}
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def row(source, source_id, name, **kw) -> dict:
    r = {c: "" for c in COLUMNS}
    r.update(source=source, source_id=s(source_id), name=s(name))
    r.update({k: v for k, v in kw.items()})
    return r


# ---------------------------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------------------------

_last_request = [0.0]


def download(url: str, dest: Path) -> None:
    wait = REQUEST_DELAY - (time.monotonic() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    _last_request[0] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        return
    except urllib.error.URLError as e:
        if not isinstance(e.reason, ssl.SSLError):
            raise
    # Some Python builds lack an intermediate certificate that the system store has.
    subprocess.run(["curl", "-sSfL", "-A", USER_AGENT, "-o", str(dest), url], check=True)


def socrata(domain: str, dataset: str, cache: Path, where: str = "", page: int = 50000) -> list[dict]:
    """All rows of a Socrata dataset through its documented SODA JSON API, paged."""
    rows: list[dict] = []
    while True:
        q = {"$limit": page, "$offset": len(rows), "$order": ":id"}
        if where:
            q["$where"] = where
        dest = cache / f"{dataset}_{len(rows)}.json"
        download(f"https://{domain}/resource/{dataset}.json?" + urllib.parse.urlencode(q), dest)
        chunk = json.loads(dest.read_text(encoding="utf-8"))
        if not isinstance(chunk, list):
            raise RuntimeError(f"{dataset}: unexpected response {str(chunk)[:200]}")
        rows += chunk
        if len(chunk) < page:
            return rows


def csv_rows(url: str, cache: Path, name: str, encoding="utf-8-sig") -> list[dict]:
    dest = cache / name
    download(url, dest)
    with open(dest, encoding=encoding, newline="") as f:
        return list(csv.DictReader(f))


def unique_ids(rows: list[dict]) -> list[dict]:
    """Make source_id unique within a source: a repeat gets '-2', '-3', ... in input order."""
    seen: dict[str, int] = {}
    for r in rows:
        k = r["source_id"]
        seen[k] = seen.get(k, 0) + 1
        if seen[k] > 1:
            r["source_id"] = f"{k}-{seen[k]}"
    return rows


# ---------------------------------------------------------------------------------------------
# Sources. Each has a config (url, access date, licence) and a build(cache) -> rows function.
# ---------------------------------------------------------------------------------------------

def build_facdb(cache: Path) -> list[dict]:
    out = []
    for r in socrata("data.cityofnewyork.us", "ji82-xba5", cache):
        out.append(row(
            "facdb", r.get("uid"), r.get("facname"), lat=lat_(r.get("latitude")), lon=lon_(r.get("longitude")),
            borough=norm_borough(r.get("boro")) or borough_from_zip(r.get("zipcode")),
            primary_type=s(r.get("factype")), address=s(r.get("address")), house_number=s(r.get("addressnum")),
            street=s(r.get("streetname")), zip=zip5(r.get("zipcode")), operator=s(r.get("opname")),
            bin=clean_bin(r.get("bin")),
            raw_json=raw_json(r, ("uid", "facname", "latitude", "longitude", "boro", "borocode", "factype", "address",
                                  "addressnum", "streetname", "zipcode", "opname", "bin", "city", "xcoord", "ycoord",
                                  "geometry", "ct2010", "nta2010", "schooldist", "policeprct", "cd", "council"))))
    return out


# Code-only fields with no descriptions in the file; dropped from raw_json to keep the file smaller.
IRS_LOW_VALUE = ("PF_FILING_REQ_CD", "FILING_REQ_CD", "ACCT_PD", "ASSET_CD", "INCOME_CD", "GROUP", "ORGANIZATION",
                 "AFFILIATION", "DEDUCTIBILITY", "TAX_PERIOD")


def build_irs_eo(cache: Path) -> list[dict]:
    out = []
    for r in csv_rows("https://www.irs.gov/pub/irs-soi/eo_ny.csv", cache, "eo_ny.csv", "utf-8"):
        borough = borough_from_zip(r["ZIP"])
        if not borough:
            continue
        addr = s(r["STREET"])
        num_, street = split_address(addr)
        out.append(row(
            "irs_eo", r["EIN"], r["NAME"], borough=borough, primary_type=s(r["NTEE_CD"]), address=addr,
            house_number=num_, street=street, zip=zip5(r["ZIP"]), url=f"https://projects.propublica.org/nonprofits/organizations/{int(r['EIN'])}",
            raw_json=raw_json(r, ("EIN", "NAME", "STREET", "STATE", "SORT_NAME", "CITY", *IRS_LOW_VALUE))))
    return out


def build_omh(cache: Path) -> list[dict]:
    out = []
    for r in socrata("data.ny.gov", "6nvr-tbv8", cache, "program_region='New York City'"):
        coords = (r.get("georeference") or {}).get("coordinates") or ["", ""]
        addr = s(r.get("program_address_1"))
        num_, street = split_address(addr)
        out.append(row(
            "omh", f"{r.get('facility_code')}-{r.get('program_code')}", r.get("facility_name"),
            lat=lat_(coords[1]), lon=lon_(coords[0]),
            borough=norm_borough(r.get("program_county")) or borough_from_zip(r.get("program_zip")),
            primary_type=s(r.get("program_type_description")), address=addr, house_number=num_, street=street,
            zip=zip5(r.get("program_zip")), phone=phone_(r.get("program_phone") or r.get("agency_phone")),
            operator=s(r.get("sponsor_name")), last_edit=s(r.get("row_created_date_time"))[:10],
            raw_json=raw_json(r, ("facility_name", "program_address_1", "program_zip", "georeference", "program_phone",
                                  "program_state", "program_city", "row_created_date_time", "program_region"))))
    return out


def build_doh_childcare(cache: Path) -> list[dict]:
    out = []
    for r in socrata("data.cityofnewyork.us", "gy3q-4tzp", cache):
        addr = s(r.get("address"))
        num_, street = split_address(addr)
        out.append(row(
            "doh_childcare", r.get("dcid"), r.get("program_name"), lat=lat_(r.get("latitude")),
            lon=lon_(r.get("longitude")), borough=norm_borough(r.get("borough")) or borough_from_zip(r.get("zipcode")),
            primary_type=s(r.get("program_type")), address=addr, house_number=num_, street=street,
            zip=zip5(r.get("zipcode")), phone=phone_(r.get("phone")), bin=clean_bin(r.get("bin")),
            raw_json=raw_json(r, ("dcid", "program_name", "latitude", "longitude", "borough", "program_type", "address",
                                  "zipcode", "phone", "bin", "community_board", "council_district", "census_tract",
                                  "nta_code"))))
    return unique_ids(out)


def build_dycd(cache: Path) -> list[dict]:
    """Latest program year only (the dataset repeats every site for each year since 2018)."""
    out = []
    for r in socrata("data.cityofnewyork.us", "ebkm-iyma", cache, "date='2026'"):
        addr = s(r.get("street_address"))
        num_, street = split_address(addr)
        out.append(row(
            "dycd", f"{r.get('contract')}-{r.get('program_area')}-{r.get('program_site_name')}-{addr}",
            r.get("program_site_name"), lat=lat_(r.get("latitude")), lon=lon_(r.get("longitude")),
            borough=norm_borough(r.get("borough")) or borough_from_zip(r.get("zipcode")),
            primary_type=s(r.get("service_category")), address=addr, house_number=num_, street=street,
            zip=zip5(r.get("zipcode")), operator=s(r.get("provider")),
            bin=clean_bin(r.get("bin")),
            raw_json=raw_json(r, ("program_site_name", "latitude", "longitude", "borough", "service_category",
                                  "street_address", "zipcode", "provider", "bin", "city", "state", "x_coordinate",
                                  "y_coordinate", "geocoded_column", "communitydistrict", "city_council_district",
                                  "census_tract_2010", "nda", "nta"))))
    return unique_ids(sorted(out, key=lambda x: x["source_id"]))


def build_endgbv(cache: Path) -> list[dict]:
    """Rows with display_physical_address = No (confidential sites) keep no address or coordinates.

    Rows without a borough take the one in boroughs_served when it names a single borough; the rest
    (citywide or confidential programs with no location) are dropped by finish().
    """
    out = []
    for r in socrata("data.cityofnewyork.us", "5ziv-wcy4", cache):
        show = s(r.get("display_physical_address")).lower() == "yes"
        addr = s(r.get("address")) if show else ""
        num_, street = split_address(addr)
        served = [norm_borough(b) for b in s(r.get("boroughs_served")).split(";") if b.strip()]
        hours = s(r.get("program_hours"))
        if hours.lower() == "other":
            hours = s(r.get("program_hours_other"))
        loc = ("address", "zip", "latitude", "longitude", "bin", "bbl", "community_board", "council_district",
               "census_tract", "nta")
        out.append(row(
            "endgbv", r.get("id"), r.get("name"), lat=lat_(r.get("latitude")) if show else "",
            lon=lon_(r.get("longitude")) if show else "",
            borough=(norm_borough(r.get("borough")) or borough_from_zip(r.get("zip"))
                     or (served[0] if len(served) == 1 else "")),
            primary_type=s(r.get("svcs_provided")), address=addr, house_number=num_, street=street,
            zip=zip5(r.get("zip")) if show else "", phone=phone_(r.get("phone") or r.get("hotline_phone")),
            website=s(r.get("website")), opening_hours=hours, url=s(r.get("url")) if show else "",
            bin=clean_bin(r.get("bin")) if show else "",
            raw_json=raw_json(r, ("id", "name", "borough", "svcs_provided", "phone", "website", "program_hours", "url",
                                  *loc))))
    return out


def build_workforce1(cache: Path) -> list[dict]:
    out = []
    for r in socrata("data.cityofnewyork.us", "6smc-7mk6", cache):
        num_, street = s(r.get("number")), s(r.get("street"))
        out.append(row(
            "workforce1", f"{r.get('name')}-{num_}-{street}", r.get("name"), lat=lat_(r.get("latitude")),
            lon=lon_(r.get("longitude")), borough=norm_borough(r.get("borough")) or borough_from_zip(r.get("postcode")),
            primary_type=s(r.get("location_type")), address=f"{num_} {street}".strip(), house_number=num_,
            street=street, zip=zip5(r.get("postcode")), opening_hours=s(r.get("hours")), bin=clean_bin(r.get("bin")),
            raw_json=raw_json(r, ("name", "latitude", "longitude", "borough", "location_type", "number", "street",
                                  "postcode", "hours", "bin", "city", "state", "nta", "councildistrict", "censustract",
                                  "communityboard"))))
    return unique_ids(sorted(out, key=lambda x: x["source_id"]))


GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/search"  # NYC GeoSearch, as in core/pipeline/geocode.py


def geosearch(address: str, zip_: str, tmp: Path) -> tuple[str, str, str]:
    """(lat, lon, bin) from NYC GeoSearch, or blanks. Trusted only when the returned ZIP and house number
    match the input, since GeoSearch otherwise returns the nearest same-named street."""
    num_, _ = split_address(address)
    dest = tmp / "geosearch.json"
    try:
        q = urllib.parse.urlencode({"text": f"{address}, {zip_}", "size": 1})
        download(f"{GEOSEARCH}?{q}", dest)
        feats = json.loads(dest.read_text(encoding="utf-8")).get("features") or []
    except (urllib.error.URLError, subprocess.CalledProcessError, ValueError):
        return "", "", ""
    for ft in feats:
        p = ft.get("properties", {})
        if zip5(p.get("postalcode")) == zip_ and num_ and s(p.get("housenumber")).upper() == num_.upper():
            lon, lat = ft["geometry"]["coordinates"]
            pad = (p.get("addendum") or {}).get("pad") or {}
            return lat_(lat), lon_(lon), clean_bin(pad.get("bin"))
    return "", "", ""


def build_cms_otp(cache: Path) -> list[dict]:
    """Medicare-enrolled Opioid Treatment Programs in the five boroughs (CMS has no coordinates, so each
    address is looked up once in NYC GeoSearch, about 60 requests)."""
    meta = cache / "dataset-type.json"
    download("https://data.cms.gov/data-api/v1/dataset-type", meta)
    slug = "/provider-characteristics/medicare-provider-supplier-enrollment/opioid-treatment-program-providers"
    latest = next(d["latest_version_uuid"] for d in json.loads(meta.read_text(encoding="utf-8"))["data"]
                  if d["slug"] == slug)
    dest = cache / "otp.json"
    download(f"https://data.cms.gov/data-api/v1/dataset/{latest}/data?size=5000", dest)
    out = []
    for r in json.loads(dest.read_text(encoding="utf-8")):
        borough = borough_from_zip(r.get("ZIP"))
        if r.get("STATE") != "NY" or not borough:
            continue
        addr = s(r.get("ADDRESS LINE 1"))
        num_, street = split_address(addr)
        lat, lon, bin_ = geosearch(addr, zip5(r.get("ZIP")), cache)
        out.append(row(
            "cms_otp", r.get("NPI"), r.get("PROVIDER NAME").rstrip(", "), lat=lat, lon=lon, borough=borough,
            primary_type="Opioid Treatment Program", address=addr, house_number=num_, street=street,
            zip=zip5(r.get("ZIP")), phone=phone_(r.get("PHONE")), last_edit=s(r.get("MEDICARE ID EFFECTIVE DATE")),
            url=f"https://npiregistry.cms.hhs.gov/provider-view/{s(r.get('NPI'))}", bin=bin_,
            raw_json=raw_json(r, ("NPI", "PROVIDER NAME", "ADDRESS LINE 1", "ZIP", "PHONE", "STATE", "CITY",
                                  "MEDICARE ID EFFECTIVE DATE"))))
    return unique_ids(out)


HRSA_COUNTIES = {"New York County", "Kings County", "Queens County", "Bronx County", "Richmond County"}


def build_hrsa(cache: Path) -> list[dict]:
    out = []
    url = "https://data.hrsa.gov/DataDownload/DD_Files/Health_Center_Service_Delivery_and_LookAlike_Sites.csv"
    for r in csv_rows(url, cache, "hrsa_sites.csv"):
        if r["Site State Abbreviation"] != "NY" or r["Complete County Name"] not in HRSA_COUNTIES:
            continue
        addr = s(r["Site Address"])
        num_, street = split_address(addr)
        out.append(row(
            "hrsa", r["BPHC Assigned Number"], r["Site Name"], lat=lat_(r["Geocoding Artifact Address Primary Y Coordinate"]),
            lon=lon_(r["Geocoding Artifact Address Primary X Coordinate"]),
            borough=norm_borough(r["Complete County Name"]), primary_type=s(r["Health Center Type"]), address=addr,
            house_number=num_, street=street, zip=zip5(r["Site Postal Code"]), phone=phone_(r["Site Telephone Number"]),
            website=s(r["Site Web Address"]), operator=s(r["Health Center Name"]),
            raw_json=raw_json(r, ("BPHC Assigned Number", "Site Name", "Site Address", "Site Postal Code", "Health Center Type",
                                  "Site Telephone Number", "Site Web Address", "Health Center Name", "Site City",
                                  "Site State Abbreviation", "Health Center Number", "BHCMIS Organization Identification Number",
                                  "Health Center Location Setting Identification Number",
                                  "Health Center Status Identification Number", "Health Center Location Identification Number",
                                  "Health Center Type Identification Number", "Health Center Operator Identification Number",
                                  "Health Center Operating Schedule Identification Number",
                                  "Health Center Operating Calendar Surrogate Key", "Geocoding Artifact Address Primary X Coordinate",
                                  "Geocoding Artifact Address Primary Y Coordinate", "U.S. - Mexico Border 100 Kilometer Indicator",
                                  "U.S. - Mexico Border County Indicator", "State and County Federal Information Processing Standard Code",
                                  "County Equivalent Name", "County Description", "HHS Region Code", "HHS Region Name",
                                  "State FIPS Code", "State Name", "State FIPS and Congressional District Number Code",
                                  "Congressional District Number", "Congressional District Name", "Congressional District Code",
                                  "U.S. Congressional Representative Name", "Name of U.S. Senator Number One",
                                  "Name of U.S. Senator Number Two", "Data Warehouse Record Create Date", "",
                                  "Health Center Organization Street Address", "Health Center Organization City",
                                  "Health Center Organization State", "Health Center Organization ZIP Code"))))
    return unique_ids(out)


SOURCES = {
    "facdb": dict(
        build=build_facdb, publisher="NYC Department of City Planning", title="Facilities Database (FacDB)",
        url=f"{NYC_PORTAL}/resource/ji82-xba5.json (landing: {NYC_PORTAL}/d/ji82-xba5)", accessed=ACCESSED,
        licence=NYC_TERMS, updated="2026-07-16 (updated every 6 months)"),
    "irs_eo": dict(
        build=build_irs_eo, publisher="IRS Statistics of Income", title="Exempt Organizations Business Master File, NY",
        url="https://www.irs.gov/pub/irs-soi/eo_ny.csv", accessed=ACCESSED,
        licence="US federal public record; page states no licence or terms of use", updated="2026-10-13"),
    "omh": dict(
        build=build_omh, publisher="NYS Office of Mental Health", title="Local Mental Health Programs (6nvr-tbv8)",
        url="https://data.ny.gov/resource/6nvr-tbv8.json", accessed=ACCESSED,
        licence="NY Open Data terms of use; dataset has no licence field", updated="2026-11-02"),
    "doh_childcare": dict(
        build=build_doh_childcare, publisher="NYC DOHMH", title="Active NYC Health Code Regulated Child Care Programs (gy3q-4tzp)",
        url=f"{NYC_PORTAL}/resource/gy3q-4tzp.json", accessed=ACCESSED, licence="Public Domain (dataset licence field)",
        updated="2026-11-05"),
    "dycd": dict(
        build=build_dycd, publisher="NYC DYCD", title="DYCD Program Sites (ebkm-iyma), program year 2026",
        url=f"{NYC_PORTAL}/resource/ebkm-iyma.json", accessed=ACCESSED, licence=NYC_TERMS, updated="2026-09-24"),
    "endgbv": dict(
        build=build_endgbv, publisher="NYC Mayor's Office to End Domestic and Gender-Based Violence",
        title="Resource Directory (5ziv-wcy4)", url=f"{NYC_PORTAL}/resource/5ziv-wcy4.json", accessed=ACCESSED,
        licence=NYC_TERMS, updated="2024-01-31"),
    "workforce1": dict(
        build=build_workforce1, publisher="NYC Small Business Services", title="Center & Service Locations (6smc-7mk6)",
        url=f"{NYC_PORTAL}/resource/6smc-7mk6.json", accessed=ACCESSED, licence=NYC_TERMS, updated="2020-02-08"),
    "cms_otp": dict(
        build=build_cms_otp, publisher="CMS (Medicare enrollment)", title="Opioid Treatment Program Providers",
        url="https://data.cms.gov/data-api/v1/dataset-type (latest version of "
            "data.cms.gov/provider-characteristics/medicare-provider-supplier-enrollment/opioid-treatment-program-providers)",
        accessed=ACCESSED, licence="U.S. Government Works (https://www.usa.gov/government-works), from the dataset's "
        "data.json 'license' field", updated="2026-11-03 (weekly)"),
    "hrsa": dict(
        build=build_hrsa, publisher="HRSA Bureau of Primary Health Care", title="Health Center Service Delivery and Look-Alike Sites",
        url="https://data.hrsa.gov/DataDownload/DD_Files/Health_Center_Service_Delivery_and_LookAlike_Sites.csv",
        accessed=ACCESSED, licence='HRSA data download page: "Usage limitations: None"; no licence stated', updated="2026-11-04"),
}


# ---------------------------------------------------------------------------------------------
# Output and checks
# ---------------------------------------------------------------------------------------------

def finish(source: str, rows: list[dict]) -> tuple[list[dict], dict]:
    kept = [r for r in rows if r["name"] and r["source_id"] and r["borough"] in BOROUGHS]
    dropped = len(rows) - len(kept)
    kept.sort(key=lambda r: r["source_id"])
    ids = [r["source_id"] for r in kept]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"{source}: source_id not unique")
    return kept, {"dropped": dropped}


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def summary(source: str, rows: list[dict], path: Path, dropped: int) -> str:
    n = len(rows) or 1
    fill = lambda c: f"{c}={100 * sum(1 for r in rows if r[c]) / n:.0f}%"  # noqa: E731
    boro = ", ".join(f"{b}={sum(1 for r in rows if r['borough'] == b)}" for b in BOROUGHS)
    coords = sum(1 for r in rows if r["lat"] and r["lon"])
    return (f"{source}: {len(rows)} rows ({dropped} dropped: no name/id or outside NYC), {path.stat().st_size / 1e6:.1f} MB\n"
            f"  {boro}\n  coords={100 * coords / n:.0f}% " + " ".join(fill(c) for c in (
                "name", "address", "phone", "website", "opening_hours", "operator", "bin", "primary_type")))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sources", nargs="*", help=f"any of: {', '.join(SOURCES)} (default: all)")
    ap.add_argument("--cache", type=Path, help="new or empty directory for raw downloads (default: a fresh temp dir)")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="output directory (default: data/supplement)")
    ap.add_argument("--list", action="store_true", help="print each source's URL, access date and licence")
    a = ap.parse_args(argv)
    unknown = [x for x in a.sources if x not in SOURCES]
    if unknown:
        ap.error(f"unknown source(s): {', '.join(unknown)}")
    if a.list:
        for k, v in SOURCES.items():
            print(f"{k}: {v['title']} | {v['url']} | accessed {v['accessed']} | updated {v['updated']} | {v['licence']}")
        return 0
    if a.cache:
        a.cache.mkdir(parents=True, exist_ok=True)
        if any(a.cache.iterdir()):
            ap.error("--cache must be an empty directory")
        cache_root = a.cache
    else:
        cache_root = Path(tempfile.mkdtemp(prefix="kavi-sources-"))
    failed = []
    for name in a.sources or SOURCES:
        cache = cache_root / name
        cache.mkdir()
        try:
            rows, info = finish(name, SOURCES[name]["build"](cache))
            path = a.out / f"{name}.csv"
            write_csv(path, rows)
            print(summary(name, rows, path, info["dropped"]))
        except Exception as e:  # report and carry on with the other sources
            failed.append(name)
            print(f"{name}: FAILED: {type(e).__name__}: {e}", file=sys.stderr)
    print(f"raw downloads in {cache_root}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
