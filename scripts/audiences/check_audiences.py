"""Data quality check for data/cleaned/resource_audiences.csv.

Run from the repo root before `npm run import`:

    python3 scripts/audiences/check_audiences.py

Needs only the standard library. Prints one line per check: PASS, WARN (worth a look, does not block the
import) or FAIL (the import would break or load wrong data). Exits with status 1 if any check fails.

Checks, in three groups:
  1. Structure: row count, ids, columns, value formats, allowed values (the migration's constraints).
  2. Logic: the columns agree with each other (Everyone vs restriction, PDF audiences kept, ...).
  3. Content: patterns that often match the wrong thing, audiences found only in PDF extraction notes,
     organizations whose listings disagree, and the join the import does onto the GeoJSON.
"""
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIENCES = ROOT / "data/cleaned/resource_audiences.csv"
EXTENDED = ROOT / "data/cleaned/resources_extended.csv"
PDF_LISTINGS = ROOT / "data/extracted/connections_pdf_listings.csv"
GEOJSON = ROOT / "data/nypl_connections_resources.geojson"
REVIEWED = ROOT / "scripts/audiences/reviewed_audiences.csv"

ALLOWED_AUDIENCES = {
    "Youth", "Women", "LGBTQI+", "Veterans", "Immigrants", "Older People", "People with Disabilities",
    "Parents & Caregivers", "Formerly Incarcerated People", "Survivors of violence", "People without homes",
    "Everyone",
}
LIST_COLUMNS = ["pdf_audiences", "confirmed_pdf_audiences", "unconfirmed_pdf_audiences", "name_audiences",
                "description_audiences", "pdf_text_audiences", "restricted_audiences", "focus_audiences",
                "audiences_all"]
# Columns and types the import reads (AUDIENCE_COLUMNS in scripts/database/import-resources.mjs).
IMPORT_COLUMNS = {
    "audiences_all": "list", "restricted_audiences": "list", "focus_audiences": "list",
    "confirmed_pdf_audiences": "list", "unconfirmed_pdf_audiences": "list", "pdf_audience_check": "text",
    "audience_restriction": "text", "restriction_evidence": "text", "everyone_basis": "text",
    "audience_needs_review": "boolean", "audience_reviewed": "boolean",
}
ENUMS = {
    "audience_restriction": {"restricted", "open", "mixed", "not_stated"},
    "everyone_basis": {"", "stated", "assumed"},
    "pdf_audience_check": {"", "confirmed", "partly confirmed", "not confirmed"},
}
# Same rule as the import script: the cleaning notebook merged feature 690 into resource 690.
MERGED_FEATURE_INDEX = 690
EXTRACTION_NOTE = re.compile(r"\[[^\]]*(PARTIAL|POINTER|INCOMPLETE|CORRECTED|NOTE|segment)[^\]]*\]?", re.I)
# Words a pattern matches that can mean something other than the audience. Each is checked in context.
RISKY = {
    "Survivors of violence": (r"survivors?\b", r"violence|abuse|assault|trafficking|domestic|rape|crime|harm|sexual|trauma"),
    # "military occupational code" is how veterans search for civilian jobs.
    "Veterans": (r"military", r"veteran|service member|discharge|armed forces|gi rights|military occupational"),
    # "aging rights" (legal help) and "Positive Aging" (library programs) are for older people.
    "Older People": (r"\baging\b", r"older|senior|elder|aging services|dfta|aging rights|positive aging"),
    "Women": (r"\bmothers?\b", r"women|mother"),
    "Parents & Caregivers": (r"guardians?\b", r"parent|child|legal guardian|guardian ad litem"),
    # A reentry permit is an immigration document, not reentry after prison.
    "Formerly Incarcerated People": (r"re-?entry permits?", r"incarcerat|prison|jail|parole|conviction"),
}

results = []


def report(status, name, detail="", examples=()):
    results.append(status)
    print(f"{status:4}  {name}" + (f": {detail}" if detail else ""))
    for e in list(examples)[:8]:
        print(f"        - {e}")
    if len(examples) > 8:
        print(f"        … and {len(examples) - 8} more")


def check(name, bad, detail_ok="", fail=True):
    if bad:
        report("FAIL" if fail else "WARN", name, f"{len(bad)} rows", bad)
    else:
        report("PASS", name, detail_ok)


def load(path, **kw):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, **kw))


def split(value):
    return [v.strip() for v in value.split(";") if v.strip()]


rows = load(AUDIENCES)
extended = load(EXTENDED)
ext_by_id = {r["resource_id"]: r for r in extended}
pdf_text = {r["listing_id"]: r["listing_text"] for r in load(PDF_LISTINGS)}
label = lambda r: f'{r["resource_id"]} {r["org_name"][:50]}'

print(f"Checking {AUDIENCES.relative_to(ROOT)} ({len(rows)} rows)\n")
print("1. Structure")

check("one row per row of resources_extended.csv",
      [] if len(rows) == len(extended) else [f"{len(rows)} rows here, {len(extended)} in resources_extended.csv"],
      f"{len(rows)} rows")
ids = Counter(r["resource_id"] for r in rows)
check("resource_id is unique", [f"{i} appears {n} times" for i, n in ids.items() if n > 1])
check("resource_id is a positive integer", [label(r) for r in rows if not re.fullmatch(r"[1-9]\d*", r["resource_id"])])
check("every resource_id exists in resources_extended.csv", [label(r) for r in rows if r["resource_id"] not in ext_by_id])
check("every resources_extended.csv row has an audience row",
      [f'{i} {r["org_name"][:50]}' for i, r in ext_by_id.items() if i not in ids])
check("org_name matches resources_extended.csv",
      [label(r) for r in rows if r["resource_id"] in ext_by_id
       and r["org_name"].strip().lower() != ext_by_id[r["resource_id"]]["org_name"].strip().lower()])
check("pdf_audiences is copied unchanged from resources_extended.csv",
      [label(r) for r in rows if r["resource_id"] in ext_by_id
       and split(r["pdf_audiences"]) != split(ext_by_id[r["resource_id"]]["pdf_audiences"])])
check("every column the import reads is present", [c for c in IMPORT_COLUMNS if c not in rows[0]])
check("booleans are True or False",
      [f'{label(r)}: {c}={r[c]!r}' for r in rows for c, t in IMPORT_COLUMNS.items()
       if t == "boolean" and r[c] not in ("True", "False")])
for column, allowed in ENUMS.items():
    check(f"{column} only has allowed values",
          [f"{label(r)}: {r[column]!r}" for r in rows if r[column] not in allowed],
          ", ".join(sorted(v or "(blank)" for v in allowed)))
check("list cells use '; ' with no empty or padded items",
      [f"{label(r)}: {c}={r[c]!r}" for r in rows for c in LIST_COLUMNS
       if r[c] and r[c] != "; ".join(split(r[c]))])
check("no audience is repeated inside a cell",
      [f"{label(r)}: {c}" for r in rows for c in LIST_COLUMNS if len(split(r[c])) != len(set(split(r[c])))])
check("every audience is one of the 12 known values",
      [f"{label(r)}: {c} has {v!r}" for r in rows for c in LIST_COLUMNS for v in split(r[c]) if v not in ALLOWED_AUDIENCES])
check("Everyone appears only in audiences_all",
      [f"{label(r)}: {c}" for r in rows for c in LIST_COLUMNS if c != "audiences_all" and "Everyone" in split(r[c])])

print("\n2. Logic")

tags = {r["resource_id"]: set(split(r["audiences_all"])) for r in rows}
check("no resource has an empty audiences_all", [label(r) for r in rows if not tags[r["resource_id"]]])
check("every PDF audience is kept in audiences_all",
      [label(r) for r in rows if not set(split(r["pdf_audiences"])) <= tags[r["resource_id"]]])
check("confirmed + unconfirmed PDF audiences = pdf_audiences",
      [label(r) for r in rows if sorted(split(r["confirmed_pdf_audiences"]) + split(r["unconfirmed_pdf_audiences"]))
       != sorted(split(r["pdf_audiences"]))])


def expected_check(r):
    if not r["pdf_audiences"]:
        return ""
    if not r["unconfirmed_pdf_audiences"]:
        return "confirmed"
    return "partly confirmed" if r["confirmed_pdf_audiences"] else "not confirmed"


check("pdf_audience_check agrees with the confirmed/unconfirmed columns",
      [f"{label(r)}: {r['pdf_audience_check']!r}" for r in rows if r["pdf_audience_check"] != expected_check(r)])
check("text audiences (name, description, PDF text) are all in audiences_all",
      [label(r) for r in rows if not set(split(r["name_audiences"]) + split(r["description_audiences"])
                                          + split(r["pdf_text_audiences"])) <= tags[r["resource_id"]]])
check("focus and restricted audiences are in audiences_all",
      [label(r) for r in rows if not set(split(r["focus_audiences"]) + split(r["restricted_audiences"])) <= tags[r["resource_id"]]])
check("Everyone is set exactly when the resource isn't restricted",
      [f'{label(r)}: {r["audience_restriction"]}, Everyone={"Everyone" in tags[r["resource_id"]]}' for r in rows
       if ("Everyone" in tags[r["resource_id"]]) != (r["audience_restriction"] != "restricted")])
check("everyone_basis agrees with audience_restriction",
      [f'{label(r)}: {r["audience_restriction"]}/{r["everyone_basis"]!r}' for r in rows
       if r["everyone_basis"] != {"restricted": "", "open": "stated", "mixed": "stated", "not_stated": "assumed"}[r["audience_restriction"]]
       and r["audience_reviewed"] == "False"])
check("restricted rows name who they are restricted to and why",
      [label(r) for r in rows if r["audience_restriction"] == "restricted"
       and not (r["restricted_audiences"] and r["restriction_evidence"])])
check("only restricted or mixed rows have restricted_audiences",
      [label(r) for r in rows if r["restricted_audiences"] and r["audience_restriction"] not in ("restricted", "mixed")])
check("open and mixed rows quote the wording that makes them open",
      [label(r) for r in rows if r["audience_restriction"] in ("open", "mixed") and not r["restriction_evidence"]])
check("no-match rows (a PDF audience no text confirms) are never restricted and have Everyone",
      [label(r) for r in rows if r["unconfirmed_pdf_audiences"]
       and (r["audience_restriction"] == "restricted" or "Everyone" not in tags[r["resource_id"]])])
check("restricted rows have their audience confirmed by a text",
      [label(r) for r in rows if r["audience_restriction"] == "restricted"
       and not set(split(r["restricted_audiences"])) & set(split(r["name_audiences"]) + split(r["description_audiences"])
                                                         + split(r["pdf_text_audiences"]))])
needs = lambda r: r["audience_restriction"] in ("restricted", "mixed") or r["pdf_audience_check"] in ("partly confirmed", "not confirmed")
check("audience_needs_review agrees with its definition",
      [label(r) for r in rows if r["audience_reviewed"] == "False" and (r["audience_needs_review"] == "True") != needs(r)])
reviewed = load(REVIEWED) if REVIEWED.exists() else []
check("rows marked audience_reviewed match reviewed_audiences.csv",
      sorted({r["resource_id"] for r in rows if r["audience_reviewed"] == "True"} ^ {r["resource_id"] for r in reviewed}),
      f"{len(reviewed)} manual decisions")

print("\n3. Content")

note_only = []
for r in rows:
    ext = ext_by_id.get(r["resource_id"], {})
    for source, column in (("description", "description_audiences"), ("PDF text", "pdf_text_audiences")):
        text = ext.get("description", "") if source == "description" else pdf_text.get(ext.get("pdf_listing_id", ""), "")
        if not EXTRACTION_NOTE.search(text):
            continue
        cleaned = EXTRACTION_NOTE.sub(" ", text)
        for a in split(r[column]):
            name_word = {"Older People": r"older|senior|elder|aging"}.get(a, re.escape(a.split()[0][:5]))
            if not re.search(name_word, cleaned, re.I) and re.search(name_word, text, re.I):
                note_only.append(f"{label(r)}: {a} from {source}")
check("no audience comes only from a PDF extraction note ('[PARTIAL …]')", note_only, fail=False)

risky = []
for r in rows:
    ext = ext_by_id.get(r["resource_id"], {})
    text = " ".join([r["org_name"], ext.get("description", ""), pdf_text.get(ext.get("pdf_listing_id", ""), "")])
    for audience, (word, context) in RISKY.items():
        if audience in tags[r["resource_id"]] and re.search(word, text, re.I) and not re.search(context, text, re.I):
            m = re.search(word, text, re.I)
            risky.append(f'{label(r)}: {audience} from "…{text[max(0, m.start() - 40):m.end() + 40]}…"')
check("ambiguous words are used in the right sense (survivor, military, aging, mother, guardian, reentry)",
      risky, fail=False)

# Listings of one organization may differ (different programs or sites), but a row whose description only
# points to another listing ("See X - 1 listing for full description") should match that listing. Rows the
# finder hides (row_type cross_reference) are skipped.
base = lambda name: re.sub(r"\s*-\s*\d+\s*(\(.*\))?$", "", name).strip().lower()
by_name = {r["org_name"].strip().lower(): r for r in rows}
pointer_mismatch = []
for r in rows:
    ext = ext_by_id.get(r["resource_id"], {})
    m = re.match(r"see (.+?) listing for (the )?full description", ext.get("description", "").strip(), re.I)
    if not m or ext.get("row_type") == "cross_reference":
        continue
    target = by_name.get(m.group(1).strip().lower())
    if target and set(split(target["audiences_all"])) != tags[r["resource_id"]]:
        pointer_mismatch.append(f'{label(r)}: {r["audiences_all"]} vs {target["resource_id"]}: {target["audiences_all"]}')
check("rows that point to another listing have that listing's audiences", pointer_mismatch, fail=False)

empty_text = [label(r) for r in rows if not ext_by_id.get(r["resource_id"], {}).get("description", "").strip()
              and tags[r["resource_id"]] != {"Everyone"} and not r["pdf_audiences"] and not r["name_audiences"]]
check("rows without a description only have audiences from the PDF or the name", empty_text)

geo = json.loads(GEOJSON.read_text(encoding="utf-8"))["features"]
join_errors = []
for r in rows:
    rid = int(r["resource_id"])
    index = rid - 1 if rid <= MERGED_FEATURE_INDEX else rid
    if index >= len(geo):
        join_errors.append(f"{label(r)}: no GeoJSON feature {index}")
        continue
    name = (geo[index]["properties"].get("Organization Name") or "").strip().lower()
    if name and name != r["org_name"].strip().lower():
        join_errors.append(f'{label(r)}: feature {index} is "{name[:40]}"')
check("the import's resource_id → GeoJSON join lands on the same organization", join_errors)

print("\nSummary")
counts = Counter(a for t in tags.values() for a in t)
print("  audiences_all values: " + ", ".join(f"{a} {n}" for a, n in counts.most_common()))
print("  audience_restriction: " + ", ".join(f"{k} {v}" for k, v in Counter(r["audience_restriction"] for r in rows).most_common()))
print("  pdf_audience_check:   " + ", ".join(f"{k or '(no PDF audience)'} {v}" for k, v in Counter(r["pdf_audience_check"] for r in rows).most_common()))
print(f"  Everyone only:        {sum(t == {'Everyone'} for t in tags.values())} rows")
print(f"\n{results.count('PASS')} passed, {results.count('WARN')} warnings, {results.count('FAIL')} failed")
sys.exit(1 if "FAIL" in results else 0)
