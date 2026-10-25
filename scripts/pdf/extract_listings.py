# /// script
# requires-python = ">=3.10"
# dependencies = ["pymupdf==1.26.3"]
# ///
# Extracts every listing in the Connections 2026 PDF with the chapter, section, and subheading
# it is printed under. One row per listing as printed, so an organization listed in three
# chapters gets three rows.
#
# The PDF is an InDesign export, and every level is set in one fixed style (FranklinGothic-Medium,
# black), so the assignment is read from fonts, not guessed:
#   chapter      >= 29pt  (30pt everywhere except "Physical & Mental Health" at 29pt)
#   section      20pt     (checked against the PDF's level-3 bookmarks)
#   subheading   11.5pt
#   listing name 12pt all caps (full listings) or 11pt all caps (short listings, e.g. hotlines)
# Each listing takes the most recent chapter, section, and subheading above it. A new chapter
# clears section and subheading; a new section clears subheading.
#
# Only chapter and section group listings. Every subheading in the 2026 guide titles a block of
# explanatory text (5 to 63 lines) that sits between listings, e.g. "Discovery Law" above the
# public defenders on page 224. The column is named preceding_subheading so it is not read as a
# third category level.
#
# Writes data/extracted/connections_pdf_listings.csv.
#
#   uv run scripts/pdf/extract_listings.py [path-to-pdf]
#     path-to-pdf  defaults to data/NYPL_JPS_Connections_2026.pdf (not in git; get it from NYPL)

import csv
import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
PDF = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "NYPL_JPS_Connections_2026.pdf"
OUT = ROOT / "data" / "extracted" / "connections_pdf_listings.csv"

FIRST_PAGE = 13          # pages 1-12 are the cover, front matter, and table of contents
STOP_CHAPTER = "Index"   # the index repeats every name; nothing after it is a listing
SKIP_CHAPTERS = {"Profiles"}  # interviews with people, not resources
BLACK, LINK_BLUE = 0, 2186910
# A 12pt name is always followed by contact lines or a description, so consecutive 12pt caps
# lines are one wrapped name. 11pt short listings can sit on adjacent lines (the reentry task
# forces on page 26 are at most 204pt wide), so an 11pt caps line continues the one above only
# when that one was this wide (in points) and so filled the column.
WRAP_WIDTH_11PT = 230
URL = re.compile(r"(https?://|www\.)\S+$")
SEE_PAGE = re.compile(r"See the full listing for .+? on page (\d+)", re.S)
# Caps lines that are the end of a wrapped address or phone line, e.g. "NY 11201", "TTY: 212.442.1447".
NOT_A_NAME = re.compile(r"\b[A-Z]{2} \d{5}\b|^\d{5}$|\d{3}\.\d{3}\.\d{4}|^TTY\b")


def lines(doc):
    """Yields (pdf_page, kind, text, size, width, color) for every non-empty line in reading order."""
    for page in doc:
        pdf_page = page.number + 1
        if pdf_page < FIRST_PAGE:
            continue
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                first = spans[0]
                # Running headers and footers (9pt), photo credits (6pt), and pull quotes (colored)
                # sit between the lines of a listing that runs across a page; drop them.
                if first["size"] < 9.6 or first["color"] not in (BLACK, LINK_BLUE):
                    continue
                text = " ".join("".join(s["text"] for s in spans).split())
                width = line["bbox"][2] - line["bbox"][0]
                yield pdf_page, kind_of(first, text), text, round(first["size"], 1), width, first["color"]


def kind_of(span, text):
    if "Medium" not in span["font"] or span["color"] != BLACK or "Ita" in span["font"]:
        return "body"
    size = round(span["size"], 1)
    if size >= 29:
        return "chapter"
    if size == 20.0:
        return "section"
    if size == 11.5:
        return "subheading"
    if size in (11.0, 12.0) and is_caps_name(text):
        return "name"
    return "body"


def is_caps_name(text):
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters) and not NOT_A_NAME.search(text)


def bookmark_sections(doc):
    """Level-3 bookmark titles by PDF page, with the tabs and object placeholders removed."""
    out = {}
    for level, title, page in doc.get_toc():
        if level == 3:
            out.setdefault(page, []).append(" ".join(title.replace("￼", " ").split()))
    return out


def extract(doc):
    chapter = section = subheading = None
    rows, current = [], None
    prev_kind, prev_size, prev_width = None, 0, 0

    def finish():
        nonlocal current
        if current and current["chapter"] not in SKIP_CHAPTERS:
            # \xad is the soft hyphen InDesign leaves where it split a word across lines.
            body = " ".join(current.pop("body")).replace("\xad ", "").replace("\xad", "")
            see = SEE_PAGE.search(body)
            current["is_cross_reference"] = bool(see)
            current["see_page"] = see.group(1) if see else ""
            # The first run of link-colored lines; a long URL wraps onto a second line.
            current["website"] = "".join(current.pop("links")).rstrip(".")
            del current["links_done"]
            current["listing_text"] = body
            rows.append(current)
        current = None

    for pdf_page, kind, text, size, width, color in lines(doc):
        continues = kind == prev_kind
        wrapped_name = continues and kind == "name" and size == prev_size and (
            size == 12.0 or prev_width > WRAP_WIDTH_11PT or current["name"].endswith(("—", "/", "-")))
        if kind == "chapter":
            finish()
            chapter = f"{chapter} {text}" if continues else text
            if chapter == STOP_CHAPTER:
                break
            section = subheading = None
        elif kind == "section":
            finish()
            section = f"{section} {text}" if continues else text
            subheading = None
        elif kind == "subheading":
            finish()
            subheading = f"{subheading} {text}" if continues else text
        elif wrapped_name:
            current["name"] = f"{current['name']} {text}".replace("— ", "—").replace("/ ", "/")
        elif kind == "name":
            finish()
            current = dict(name=text, chapter=chapter, section=section or "", preceding_subheading=subheading or "",
                           pdf_page=pdf_page, guide_page=pdf_page - 1, body=[], links=[], links_done=False)
        elif current:
            current["body"].append(text)
            # Link color also marks page references ("289") and URLs inside sentences, so only a
            # line that is a bare URL counts, plus one bare continuation line when the URL wraps.
            bare = color == LINK_BLUE and " " not in text
            if bare and not current["links"] and URL.match(text):
                current["links"].append(text)
            elif bare and current["links"] and not current["links_done"] and not text[0].isdigit():
                current["links"].append(text)
                current["links_done"] = True
            elif current["links"]:
                current["links_done"] = True
        prev_kind, prev_size, prev_width = kind, size, width
    finish()
    return rows


def check_sections(doc, rows):
    """Every section a listing is filed under must be a bookmarked section title."""
    titles = {t for ts in bookmark_sections(doc).values() for t in ts}
    unknown = sorted({r["section"] for r in rows if r["section"] and r["section"] not in titles})
    return unknown


def main():
    doc = pymupdf.open(PDF)
    rows = extract(doc)
    for i, row in enumerate(rows, 1):
        row["listing_id"] = i
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cols = ["listing_id", "name", "chapter", "section", "preceding_subheading", "guide_page", "pdf_page",
            "is_cross_reference", "see_page", "website", "listing_text"]
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(rows)} listings -> {OUT.relative_to(ROOT)}")
    print(f"  cross-references: {sum(r['is_cross_reference'] for r in rows)}")
    print(f"  no section: {sum(not r['section'] for r in rows)}")
    unknown = check_sections(doc, rows)
    if unknown:
        print(f"  sections not in the PDF bookmarks: {unknown}")


if __name__ == "__main__":
    main()
