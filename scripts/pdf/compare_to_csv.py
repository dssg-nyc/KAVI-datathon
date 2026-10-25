# /// script
# requires-python = ">=3.10"
# ///
# Compares the team's CSV (data/NYPL Connections Resources.csv, left unchanged) with the
# listings extracted from the PDF by extract_listings.py.
#
# Writes data/extracted/connections_pdf_vs_csv.csv with one row per CSV row, plus one row per
# PDF listing that no CSV row matched (csv_row blank, match_method "pdf_only").
#
# A CSV row matches the PDF listings with the same name after normalizing case and punctuation.
# Names are tried in this order, and match_method records which one matched:
#   exact              the CSV name as written
#   suffix_removed     the CSV name without the team's location suffix, e.g. "OSBORNE ASSOCIATION - 1 (Bronx)"
#   annotation_removed the CSV name without the suffix and without a trailing bracketed or
#                      parenthesized note or " -- site" part, e.g. "QUEENS PUBLIC LIBRARY (Tech Workshops)",
#                      "OBT [CORRECTED/COMPLETE ...] - 1 (Bushwick Office)", "NYCHA--Jobs-Plus -- FEDCAP"
#   row_above          the CSV row has no name (a second address); the name of the row above is used
#   in_listing_text    the name is not a listing of its own but appears in a listing's text in the
#                      same chapter (names under 12 normalized characters are not searched)
# When several PDF listings share the name, the one in the CSV row's chapter and section wins.
#
#   uv run scripts/pdf/compare_to_csv.py

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSV_IN = ROOT / "data" / "NYPL Connections Resources.csv"
PDF_IN = ROOT / "data" / "extracted" / "connections_pdf_listings.csv"
OUT = ROOT / "data" / "extracted" / "connections_pdf_vs_csv.csv"

# " - 1 (Bronx)", " - 2", " (Education Listing)": added by the team to tell rows apart.
SUFFIX = re.compile(r"\s+-\s*\d+\s*(\([^()]*\))?\s*$|\s*\([^()]*\blisting\)\s*$", re.I)
ANNOTATION = re.compile(r"(\s*\[[^\]]*\]|\s*\([^()]*\)|\s+--?\s+[^—]*)\s*$")
MIN_TEXT_SEARCH = 12


def norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def load(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def pick(listings, chapter, section):
    """The listing in the same chapter and section, else the same chapter, else the first."""
    for want in ((chapter, section), (chapter, None)):
        for listing in listings:
            if norm(listing["chapter"]) == norm(want[0]) and (want[1] is None or norm(listing["section"]) == norm(want[1])):
                return listing
    return listings[0]


def index_by_name(pdf_rows):
    by_name = defaultdict(list)
    for listing in pdf_rows:
        by_name[norm(listing["name"])].append(listing)
    return by_name


def match(name, chapter, section, prev_name, pdf_rows, by_name):
    """(match_method, every PDF listing with the matched name, the one listing this row is)."""
    tries = ([("exact", name), ("suffix_removed", SUFFIX.sub("", name)), ("annotation_removed", ANNOTATION.sub("", SUFFIX.sub("", name)))]
             if name else [("row_above", prev_name)])
    method, listings = "no_match", []
    for how, candidate in tries:
        if candidate and by_name.get(norm(candidate)):
            method, listings = how, by_name[norm(candidate)]
            break
    if not listings and len(norm(ANNOTATION.sub("", name))) >= MIN_TEXT_SEARCH:
        needle = norm(ANNOTATION.sub("", name))
        listings = [l for l in pdf_rows if needle in norm(l["listing_text"]) and norm(l["chapter"]) == norm(chapter)]
        method = "in_listing_text" if listings else method
    return method, listings, pick(listings, chapter, section) if listings else None


def main():
    csv_rows, pdf_rows = load(CSV_IN), load(PDF_IN)
    by_name = index_by_name(pdf_rows)

    out, used, prev_name = [], set(), ""
    for i, row in enumerate(csv_rows, 2):  # 2 = line number in the file, after the header
        name = row["Organization Name"].strip()
        method, listings, listing = match(name, row["Category"], row["Subcategory"], prev_name, pdf_rows, by_name)
        if listing and method != "in_listing_text":
            used.add(listing["listing_id"])
        out.append(dict(
            csv_row=i, csv_name=name, csv_category=row["Category"], csv_subcategory=row["Subcategory"],
            match_method=method, pdf_listings_with_name=len(listings),
            listing_id=listing["listing_id"] if listing else "", pdf_name=listing["name"] if listing else "",
            pdf_chapter=listing["chapter"] if listing else "", pdf_section=listing["section"] if listing else "",
            pdf_preceding_subheading=listing["preceding_subheading"] if listing else "", guide_page=listing["guide_page"] if listing else "",
            chapter_agrees=agrees(row["Category"], listing, "chapter"),
            section_agrees=agrees(row["Subcategory"], listing, "section"),
        ))
        prev_name = name or prev_name

    for listing in pdf_rows:
        if listing["listing_id"] not in used:
            out.append(dict(
                csv_row="", csv_name="", csv_category="", csv_subcategory="", match_method="pdf_only",
                pdf_listings_with_name=len(by_name[norm(listing["name"])]), listing_id=listing["listing_id"],
                pdf_name=listing["name"], pdf_chapter=listing["chapter"], pdf_section=listing["section"],
                pdf_preceding_subheading=listing["preceding_subheading"], guide_page=listing["guide_page"],
                chapter_agrees="", section_agrees=""))

    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)

    matched = [r for r in out if r["csv_row"] and r["listing_id"]]
    print(f"{len(csv_rows)} CSV rows, {len(pdf_rows)} PDF listings -> {OUT.relative_to(ROOT)}")
    print("  match_method:", dict(Counter(r["match_method"] for r in out)))
    print("  of matched CSV rows, chapter agrees:", dict(Counter(r["chapter_agrees"] for r in matched)))
    print("  of matched CSV rows, section agrees:", dict(Counter(r["section_agrees"] for r in matched)))


def agrees(csv_value, listing, field):
    """"yes"/"no", or "csv_blank" when the CSV has no value to compare."""
    if not listing:
        return ""
    if not csv_value.strip():
        return "csv_blank"
    return "yes" if norm(csv_value) == norm(listing[field]) else "no"


if __name__ == "__main__":
    main()
