# /// script
# requires-python = ">=3.10"
# ///
# Extends data/cleaned/resources_clean.csv (from scripts/cleaning/) with what the PDF says about
# each resource. Every column of resources_clean.csv is kept unchanged; the new columns follow.
#
# The PDF's chapter and section are turned into a service type by scripts/pdf/section_service_types.csv,
# one row per PDF section. That table is the only place where a person decides anything; this
# script applies it the same way on every run, and stops if a PDF section is missing from it.
#
# service_type_extended never replaces a service_type that resources_clean.csv already has. It
# fills a blank one, in this order:
#   pdf_section         the section this row is listed under in the PDF has a service type
#   pdf_other_listings  the section has none (e.g. Youth > Organizations & Resources), but every
#                       other PDF listing of the same organization maps to one and the same type
# A row whose other listings map to several types stays blank ("pdf_candidates"); the types are
# in pdf_org_service_types and service_types_all.
#
# pdf_contradiction is filled only where the PDF clearly disagrees with resources_clean.csv:
#   - scripts/cleaning/'s own rules (by_sub, by_cat), applied to the PDF section, give a different
#     service type than service_type. A section mapped only in section_service_types.csv (basis
#     "new") is a second opinion, not a contradiction; compare pdf_section_service_type instead.
#   - the PDF chapter differs from a non-blank guide_category.
#   - the resource is not in the PDF at all.
#
# description_keyword_types is multi-label: every service type whose pattern in SERVICE_PATTERNS
# matches the row's text, computed for every row regardless of whether service_type_extended is
# already set, so an organization's secondary services surface alongside its primary one. A row
# whose description only says "See X listing for full description" uses X's text instead
# ("pointer:<resource_id of X>").
# description_service_types is the row's entry in reviewed_service_types.csv when it has one, else
# description_keyword_types. reviewed_service_types.csv only covers rows that had no
# service_type_extended at review time, so rows that already had a primary type get unreviewed
# keyword tags here (description_service_types_source == "description_keywords").
# Two human reviews in data/review/ (see its README) then override it:
#   reviewed_service_types_human_check.csv  a person's verdict on each reviewed_service_types.csv
#                                           entry; "change" replaces the types with human_service_types
#   new_service_types_review.csv            a person's types for the rows with no type at all,
#                                           including the new type "Disability Services"
#
# Writes data/cleaned/resources_extended.csv. Run extract_listings.py first.
#
#   uv run scripts/pdf/extend_clean_resources.py

import csv
import re
import sys
from pathlib import Path

from compare_to_csv import index_by_name, load, match, norm

ROOT = Path(__file__).resolve().parents[2]
CLEAN_IN = ROOT / "data" / "cleaned" / "resources_clean.csv"
PDF_IN = ROOT / "data" / "extracted" / "connections_pdf_listings.csv"
MAPPING = Path(__file__).with_name("section_service_types.csv")
REVIEWED = Path(__file__).with_name("reviewed_service_types.csv")
HUMAN_CHECK = ROOT / "data" / "review" / "reviewed_service_types_human_check.csv"
NEW_TYPES = ROOT / "data" / "review" / "new_service_types_review.csv"
OUT = ROOT / "data" / "cleaned" / "resources_extended.csv"

TO_ASSIGN = "service_type to assign"  # the review note scripts/cleaning/ adds for a blank service_type

# The notebook's `hints`, tightened so a word that names who a resource serves, or a topic it
# mentions, does not count as a service ("formerly incarcerated", "parole", "advocacy",
# "court-involved", "unhoused", "shelter system", "employment authorization", "health care proxy",
# "medical records", "after-school hours", "does not offer legal services"), and widened for
# services the review found missing (benefits applications, stipends, bond, reduced fare, classes).
# Measured against reviewed_service_types.csv on every run; see the printed precision and recall.
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
POINTER = re.compile(r"\s*See (.+?) listing for (the )?full description", re.I)


def joined(values):
    return "; ".join(sorted({v for v in values if v}))


def service_types_in(text):
    return joined(t for t, pattern in SERVICE_PATTERNS.items() if re.search(pattern, text, re.I))


def main():
    clean, pdf_rows = load(CLEAN_IN), load(PDF_IN)
    mapping = {(norm(m["chapter"]), norm(m["section"])): m for m in load(MAPPING)}
    missing = sorted({(l["chapter"], l["section"]) for l in pdf_rows if (norm(l["chapter"]), norm(l["section"])) not in mapping})
    if missing:
        sys.exit(f"{MAPPING.name} has no row for these PDF sections: {missing}")
    audience_chapters = {norm(m["chapter"]): m["audience"] for m in mapping.values() if m["audience"]}
    by_name = index_by_name(pdf_rows)

    def mapped(listing):
        return mapping[(norm(listing["chapter"]), norm(listing["section"]))]

    out, texts = [], []
    for row in clean:
        method, listings, own = match(row["org_name"], row["guide_category"], row["guide_subcategory"], "", pdf_rows, by_name)
        # A name found only inside another listing's text shares that listing's section, but the
        # other listings of that organization are not this organization's.
        org_listings = [own] if method == "in_listing_text" else listings
        own_type = mapped(own)["service_type"] if own else ""
        # True when scripts/cleaning/'s own by_sub/by_cat rules give this section's type
        # (basis pr_subcategory or pr_chapter), not a mapping added in section_service_types.csv.
        own_type_is_pr_rule = bool(own) and mapped(own)["basis"].startswith("pr_")
        org_types = joined(mapped(l)["service_type"] for l in org_listings)
        audiences = joined([mapped(l)["audience"] for l in org_listings] + [audience_chapters.get(norm(row["guide_category"]), "")])

        if row["service_type"]:
            extended, source = row["service_type"], f"pr:{row['service_type_source']}"
        elif own_type:
            extended, source = own_type, "pdf_section"
        elif org_types and ";" not in org_types:
            extended, source = org_types, "pdf_other_listings"
        else:
            extended, source = "", "pdf_candidates" if org_types else "unassigned"
        subtype = mapped(own)["service_subtype"] if own and own_type == extended else ""

        contradictions = []
        if not own:
            contradictions.append("Not found in PDF")
        else:
            if row["service_type"] and own_type_is_pr_rule and own_type != row["service_type"]:
                contradictions.append(f"service_type is {row['service_type']} ({row['service_type_source']}); "
                                      f"PDF section {own['chapter']} > {own['section']} is {own_type}")
            if method != "in_listing_text" and row["guide_category"] and norm(own["chapter"]) != norm(row["guide_category"]):
                contradictions.append(f"guide_category is {row['guide_category']}; PDF chapter is {own['chapter']}")

        # The PR's notes, minus "service_type to assign" once the PDF filled it, plus contradictions.
        notes = [n for n in (row["review_notes"] or "").split(" | ") if n and not (n == TO_ASSIGN and extended)]
        notes += contradictions

        out.append(row | dict(
            pdf_match_method=method,
            pdf_listing_id=own["listing_id"] if own else "",
            pdf_chapter=own["chapter"] if own else "",
            pdf_section=own["section"] if own else "",
            pdf_preceding_subheading=own["preceding_subheading"] if own else "",
            pdf_guide_page=own["guide_page"] if own else "",
            pdf_is_cross_reference=own["is_cross_reference"] if own else "",
            pdf_section_service_type=own_type,
            pdf_appearances="; ".join(f"{l['chapter']} > {l['section']} (p. {l['guide_page']})" for l in org_listings),
            pdf_org_service_types=org_types,
            pdf_audiences=audiences,
            service_type_extended=extended,
            service_type_extended_source=source,
            service_subtype_extended=subtype,
            description_keyword_types="",
            description_service_types="",
            description_service_types_source="",
            service_types_all=joined([extended] + org_types.split("; ")),
            pdf_contradiction=" | ".join(contradictions),
            needs_review_extended=str(bool(notes)),
            review_notes_extended=" | ".join(notes),
        ))
        # The PDF's text is complete where the team's sheet cut a description short ("[PARTIAL ...]"),
        # but a name found inside another listing's text would get that listing's services.
        texts.append(row["description"] + (" " + own["listing_text"] if own and method != "in_listing_text" else ""))

    # Description tags, for every row. A row in
    # reviewed_service_types.csv takes its reviewed types; the keyword types stay alongside.
    by_id = {r["resource_id"]: r for r in out}

    def keyed(path):
        table = {}
        for rev in load(path):
            row = by_id.get(rev["resource_id"])
            if not row or row["org_name"] != rev["org_name"]:
                sys.exit(f"{path.name}: resource_id {rev['resource_id']} is no longer {rev['org_name']!r}; "
                         "resources_clean.csv was renumbered, so re-key the table")
            table[rev["resource_id"]] = rev
        return table

    reviewed, checked, new_types = keyed(REVIEWED), keyed(HUMAN_CHECK), keyed(NEW_TYPES)
    for rid, check in checked.items():
        if rid not in reviewed:
            sys.exit(f"{HUMAN_CHECK.name}: resource_id {rid} is not in {REVIEWED.name}")
        if check["human_verdict"] not in ("agree", "change", "unsure", ""):
            sys.exit(f"{HUMAN_CHECK.name}: resource_id {rid} has human_verdict {check['human_verdict']!r}")
        if check["human_verdict"] == "change" and not check["human_service_types"].strip():
            sys.exit(f"{HUMAN_CHECK.name}: resource_id {rid} is 'change' but human_service_types is blank")
    for rid in new_types:
        if by_id[rid]["service_type_extended"]:
            sys.exit(f"{NEW_TYPES.name}: resource_id {rid} already has service_type_extended; the review is for rows without one")
    by_org = {norm(r["org_name"]): (r, text) for r, text in zip(out, texts)}
    # Two passes, so a pointer row reads its target's keyword types and never types the target
    # got from the review or from the PDF chapter it is printed in.
    for r, text in zip(out, texts):
        pointer = POINTER.match(r["description"])
        target = by_org.get(norm(pointer.group(1))) if pointer else None
        if target:
            target_row, target_text = target
            r["description_keyword_types"] = service_types_in(target_text)
            r["description_service_types_source"] = f"pointer:{target_row['resource_id']}"
        else:
            r["description_keyword_types"] = service_types_in(text)
            r["description_service_types_source"] = "description_keywords" if r["description_keyword_types"] else ""
    for r in out:
        rid, types = r["resource_id"], r["description_keyword_types"]
        if rid in reviewed:
            types = reviewed[rid]["reviewed_service_types"]
            r["description_service_types_source"] = "reviewed"
            verdict = checked.get(rid, {}).get("human_verdict")
            if verdict == "agree":
                r["description_service_types_source"] = "human_agreed"
            elif verdict == "change":
                types = joined(t.strip() for t in checked[rid]["human_service_types"].split(";"))
                r["description_service_types_source"] = "human_changed"
        if rid in new_types:
            rev = new_types[rid]
            proposed = joined(t.strip() for t in f"{rev['proposed_service_type']};{rev['fits_existing_type']}".split(";"))
            if r["description_service_types_source"] == "human_changed" and proposed and proposed != types:
                sys.exit(f"resource_id {rid}: {NEW_TYPES.name} gives {proposed!r}, {HUMAN_CHECK.name} gives {types!r}")
            if proposed and r["description_service_types_source"] != "human_changed":
                types, r["description_service_types_source"] = proposed, "human_new_types"
        r["description_service_types"] = types
        r["service_types_all"] = joined((r["service_types_all"] + "; " + types).split("; "))
    # new_service_types_review.csv leaves a cross-reference row blank: it takes the types of the
    # organization's full listing. A separate pass, because the full listing may come later in the file.
    for rid, rev in new_types.items():
        r = by_id[rid]
        if r["description_service_types"] or r["row_type"] != "cross_reference":
            continue
        full = next((o for o in out if o["org_name"] == r["org_name"] and o["row_type"] != "cross_reference"), None)
        if full:
            r["description_service_types"] = r["service_types_all"] = full["service_types_all"]
            r["description_service_types_source"] = f"cross_reference:{full['resource_id']}"

    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)

    count = lambda pred: sum(1 for r in out if pred(r))
    print(f"{len(out)} rows -> {OUT.relative_to(ROOT)}")
    print(f"  service_type blank: {count(lambda r: not r['service_type'])} before, "
          f"{count(lambda r: not r['service_type_extended'])} after")
    for source in ("pdf_section", "pdf_other_listings", "pdf_candidates", "unassigned"):
        print(f"    {source}: {count(lambda r: r['service_type_extended_source'] == source)}")
    print(f"  service_subtype_extended filled: {count(lambda r: r['service_subtype_extended'])}")
    for source in ("description_keywords", "pointer"):
        print(f"  description_service_types from {source}: "
              f"{count(lambda r: r['description_service_types'] and r['description_service_types_source'].startswith(source))}")
    for source in ("reviewed", "human_agreed", "human_changed", "human_new_types", "cross_reference"):
        print(f"  description_service_types from {source}: "
              f"{count(lambda r: r['description_service_types_source'].split(':')[0] == source)}")
    print(f"  service_types_all with Disability Services: {count(lambda r: 'Disability Services' in r['service_types_all'])}")
    pairs = [(set(filter(None, r["description_keyword_types"].split("; "))), set(filter(None, reviewed[r["resource_id"]]["reviewed_service_types"].split("; "))))
             for r in out if r["resource_id"] in reviewed]
    right = sum(len(k & e) for k, e in pairs)
    print(f"  keyword types vs reviewed: precision {right}/{sum(len(k) for k, _ in pairs)}, recall {right}/{sum(len(e) for _, e in pairs)}")
    print(f"  still no service type at all: {count(lambda r: not r['service_types_all'])}")
    multi = lambda field: count(lambda r: len(list(filter(None, r[field].split("; ")))) > 1)
    print(f"  rows with more than one type in service_types_all: {multi('service_types_all')} "
          f"(service_type_extended alone: {count(lambda r: r['service_type_extended'] and not r['description_service_types'])})")
    print(f"  pdf_audiences filled: {count(lambda r: r['pdf_audiences'])}")
    print(f"  pdf_contradiction: {count(lambda r: r['pdf_contradiction'])} "
          f"(service_type {count(lambda r: 'service_type is' in r['pdf_contradiction'])}, "
          f"chapter {count(lambda r: 'guide_category is' in r['pdf_contradiction'])}, "
          f"not in PDF {count(lambda r: 'Not found in PDF' in r['pdf_contradiction'])})")
    print(f"  needs_review: {count(lambda r: r['needs_review'] == 'True')} before, "
          f"{count(lambda r: r['needs_review_extended'] == 'True')} after")


if __name__ == "__main__":
    main()
