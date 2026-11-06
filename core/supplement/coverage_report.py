# /// script
# requires-python = ">=3.10"
# ///
"""Coverage of the NYPL guide by one supplementary source, at row level and parent-organization level.

Reads data/kavi_resources.csv and data/supplement/matches_<source>.csv (from match_nypl.py). Writes
data/supplement/coverage_<source>.csv (long format: scope, measure, dimension, value, denominator, matched,
rate, note) and data/supplement/parent_orgs_<source>.csv (one line per parent org, for auditing the grouping).

Definitions
  site_level   best class same_site or program_at_host: the source has the org (or a program's host) at the
               NYPL row's own place. Denominator: rows with a physical site (row_type mapped); hotlines,
               web-only, cross-reference, mailing-address and outside-NYC rows have no site to find.
  org_level    site_level, or same_org_other_site: the source knows the org, perhaps elsewhere. Denominator:
               all rows. This does NOT say the row's location is in the source.
  building_only  same_building_unconfirmed. Reported on its own, never counted as a match.
  Parent org   rows grouped by the normalised head of organization_name (program text, team "- 2 (label)"
               suffixes, bracket notes and parenthesised abbreviations removed), merged when one's parent
               name equals another's parenthesised abbreviation or alias, or when they share a website domain
               used by at most DOMAIN_MERGE_MAX groups (rows with several domains are ignored for this). Every merge is listed in the parents file with its
               reason. A parent is site_level if any of its mapped rows is; its site-level rate is over
               parents that have a mapped row.
No precision or recall here: there are no gold labels, these are rates of rows the matcher accepted.

    python3 core/supplement/coverage_report.py --source osm
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import match_nypl as m  # noqa: E402

DOMAIN_MERGE_MAX = 4
SITE = ("same_site", "program_at_host")
ORG = SITE + ("same_org_other_site",)


def group_parents(nypl_rows, aliases):
    """-> (group id per NYPL row id, {group id: info}). Union-find over name sets, abbreviations, domains."""
    parsed = {r["id"]: m.parse_nypl_name(r["organization_name"], aliases) for r in nypl_rows}
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    reasons = defaultdict(set)

    def union(a, b, why):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
            reasons[ra] |= reasons.pop(rb, set()) | {why}

    keys = {}
    for r in nypl_rows:
        p = parsed[r["id"]]["parent"]
        keys[r["id"]] = p or frozenset({f"row{r['id']}"})  # nameless: stays alone
        find(keys[r["id"]])
    # abbreviation / alias equals another group's parent name
    for r in nypl_rows:
        for a in parsed[r["id"]]["aliases"] + parsed[r["id"]]["long_aliases"]:
            if a in parent and a != keys[r["id"]]:
                union(keys[r["id"]], a, "alias")
    # shared, specific website domain
    by_dom = defaultdict(set)
    for r in nypl_rows:
        ds = m.domains(r.get("website", ""))
        if len(ds) == 1:  # a row listing several domains is a directory (e.g. "NYC Public Libraries"), not identity
            by_dom[next(iter(ds))].add(find(keys[r["id"]]))
    for d, groups in by_dom.items():
        groups = sorted({find(g) for g in groups}, key=sorted)
        if 1 < len(groups) <= DOMAIN_MERGE_MAX:
            for g in groups[1:]:
                union(groups[0], g, f"domain {d}")
    gid = {r["id"]: find(keys[r["id"]]) for r in nypl_rows}
    return gid, reasons


def pct(a, b):
    return f"{a / b:.3f}" if b else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="osm")
    a = ap.parse_args()
    nypl = m.read(m.NYPL_CSV)
    pairs = m.read(m.SUPP_DIR / f"matches_{a.source}.csv")
    best = {}
    for x in pairs:
        if x["is_best"] == "True" or x["match_class"] == "no_match":
            best[x["nypl_id"]] = x
    rows = []
    for r in nypl:
        b = best[r["id"]]
        rows.append({**r, "cls": b["match_class"], "reason": b["no_match_reason"],
                     "site_row": r["row_type"] in m.SITE_ROW_TYPES, "borough_k": r["borough"] or "(none)",
                     "category_k": r["category"] or "(blank)", "type_k": r["service_type"] or "(unclassified)",
                     "rt": r["row_type"] or "(blank)"})
    out = []

    def emit(scope, measure, dim, value, den, num, note):
        out.append({"scope": scope, "measure": measure, "dimension": dim, "value": value, "denominator": den,
                    "matched": num, "rate": pct(num, den), "note": note})

    n_site_note = "denominator = rows with a physical site (row_type mapped)"
    n_all_note = "denominator = all rows"
    # ---- row level ----
    dims = [("overall", lambda r: "all"), ("row_type", lambda r: r["rt"]), ("borough", lambda r: r["borough_k"]),
            ("category", lambda r: r["category_k"]), ("service_type", lambda r: r["type_k"])]
    for dim, fn in dims:
        for v in sorted({fn(r) for r in rows}):
            grp = [r for r in rows if fn(r) == v]
            sg = [r for r in grp if r["site_row"]]
            emit("row", "site_level", dim, v, len(sg), sum(r["cls"] in SITE for r in sg), n_site_note)
            emit("row", "building_only", dim, v, len(sg), sum(r["cls"] == "same_building_unconfirmed" for r in sg), n_site_note)
            emit("row", "org_level", dim, v, len(grp), sum(r["cls"] in ORG for r in grp), n_all_note)
    for cls in ("same_site", "program_at_host", "same_org_other_site", "same_building_unconfirmed", "no_match"):
        sg = [r for r in rows if r["site_row"]]
        emit("row", "match_class", "mapped rows", cls, len(sg), sum(r["cls"] == cls for r in sg), n_site_note)
        emit("row", "match_class", "all rows", cls, len(rows), sum(r["cls"] == cls for r in rows), n_all_note)
    reasons = Counter(r["reason"] or "(site-level match)" for r in rows)
    for k, c in sorted(reasons.items()):
        emit("row", "no_match_reason", "all rows", k, len(rows), c, n_all_note)
    # ---- parent-org level ----
    gid, why = group_parents(nypl, m.load_aliases())
    groups = defaultdict(list)
    for r in rows:
        groups[gid[r["id"]]].append(r)
    prow = []
    for g, rs in groups.items():
        mapped = [r for r in rs if r["site_row"]]
        names = Counter(m.name_key(r["organization_name"]) for r in rs)
        prow.append({
            "parent": names.most_common(1)[0][0], "n_rows": len(rs), "n_mapped": len(mapped),
            "category": Counter(r["category_k"] for r in rs).most_common(1)[0][0],
            "service_type": Counter(r["type_k"] for r in rs).most_common(1)[0][0],
            "borough": Counter(r["borough_k"] for r in mapped).most_common(1)[0][0] if mapped else "(none)",
            "any_site": any(r["cls"] in SITE for r in mapped), "any_org": any(r["cls"] in ORG for r in rs),
            "any_building": any(r["cls"] == "same_building_unconfirmed" for r in mapped),
            "mapped_site_share": pct(sum(r["cls"] in SITE for r in mapped), len(mapped)),
            "name_variants": " | ".join(sorted(names)), "merged_via": "; ".join(sorted(why.get(g, ()))),
            "domains": " ".join(sorted({d for r in rs for d in m.domains(r.get("website", ""))})),
            "row_ids": " ".join(r["id"] for r in rs),
            "row_types": ",".join(sorted({r["rt"] for r in rs}))})
    pdims = [("overall", lambda p: "all"), ("category", lambda p: p["category"]),
             ("service_type", lambda p: p["service_type"]), ("borough", lambda p: p["borough"])]
    for dim, fn in pdims:
        for v in sorted({fn(p) for p in prow}):
            grp = [p for p in prow if fn(p) == v]
            sg = [p for p in grp if p["n_mapped"]]
            emit("parent_org", "site_level", dim, v, len(sg), sum(p["any_site"] for p in sg),
                 "denominator = parent orgs with at least one mapped row; matched = any mapped row site_level")
            emit("parent_org", "org_level", dim, v, len(grp), sum(p["any_org"] for p in grp),
                 "denominator = all parent orgs; matched = any row org_level")
    only_site = [p for p in prow if p["n_mapped"] == 0]
    emit("parent_org", "no_physical_site_at_all", "overall", "all", len(prow), len(only_site),
         "parent orgs whose every row lacks a physical site")
    outp = m.SUPP_DIR / f"coverage_{a.source}.csv"
    with outp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, list(out[0]))
        w.writeheader()
        w.writerows(out)
    pp = m.SUPP_DIR / f"parent_orgs_{a.source}.csv"
    with pp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, list(prow[0]))
        w.writeheader()
        w.writerows(sorted(prow, key=lambda p: (-p["n_rows"], p["parent"])))
    print(f"{len(out)} coverage lines -> {outp}; {len(prow)} parent orgs -> {pp}")
    for x in out:
        if x["dimension"] in ("overall", "borough") and x["measure"] in ("site_level", "org_level"):
            print(f"  {x['scope']:10} {x['measure']:10} {x['dimension']:8} {x['value']:14} {x['matched']:>4}/{x['denominator']:<4} {x['rate']}")


if __name__ == "__main__":
    main()
