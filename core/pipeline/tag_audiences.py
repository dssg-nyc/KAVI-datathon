# /// script
# requires-python = ">=3.10"
# dependencies = ["pandas"]
# ///
# Tags who each resource serves ("Who is it for?") in data/cleaned/resource_audiences.csv.
#
# This is notebooks/audience_enrichment.ipynb (Franziska) as a script, with the same rules in the
# same order and the same output. docs/audiences.md explains the rules and the columns; the notebook
# shows the intermediate results. Change the rules here and in the notebook together, or retire the
# notebook.
#
# Reads (from data/):
#   cleaned/resources_extended.csv           the cleaned guide with the PDF columns
#   extracted/connections_pdf_listings.csv   the PDF listing texts
#   review/reviewed_audiences.csv            a person's decisions; created empty, never overwritten
# Writes (to data/):
#   cleaned/resource_audiences.csv           one row per resource_id, joined onto the resource table
#   review/audience_review.csv               a fixed random sample of 50 rows for a manual check
#   review/audience_no_match.csv             rows the patterns could not match or confirm
#
# Usage:
#   uv run pipeline/4_audiences/tag_audiences.py

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
IN_FILE = DATA / "cleaned" / "resources_extended.csv"
PDF_FILE = DATA / "extracted" / "connections_pdf_listings.csv"
OUT_FILE = DATA / "cleaned" / "resource_audiences.csv"
REVIEW_FILE = DATA / "review" / "audience_review.csv"
NO_MATCH_FILE = DATA / "review" / "audience_no_match.csv"
REVIEWED_FILE = DATA / "review" / "reviewed_audiences.csv"

# Some descriptions still hold notes from the PDF extraction, e.g. "[PARTIAL/POINTER ONLY — … see the
# LGBTQI+ chapter …]". They name chapters, not who a resource serves, so they are removed before matching.
EXTRACTION_NOTE = r"\[[^\]]*(?:PARTIAL|POINTER|INCOMPLETE|CORRECTED|NOTE|segment)[^\]]*\]?"

AUDIENCES = {
    "Youth": r"\byouth|young (people|adults|men|women)|\bteens?\b|teenagers?|adolescents?|\bminors?\b",
    "Women": r"\bwomen\b|\bgirls?\b|\bmothers?\b",
    "LGBTQI+": r"lgbt|transgender|\btrans\b|queer|gender[- ](non-?conforming|fluid|expansive)|two[- ]spirit",
    "Veterans": r"veterans?\b|service members|military",
    "Immigrants": r"immigra|undocumented|asylum|refugees?\b|migrants?\b|new americans",
    "Older People": r"\bseniors?\b|older (adults|people|new yorkers)|elderly|\baging\b|ages? (6[0-9]|5[5-9]) (and|or) (older|over|up)",
    "People with Disabilities": r"disabilit|\bdeaf\b|\bblind\b|hard of hearing|visually impaired|independent living",
    "Parents & Caregivers": r"\b(grand)?parents?\b|caregivers?\b|guardians?\b|families with children|children of incarcerated|parenting",
    "Formerly Incarcerated People": r"formerly incarcerated|justice[- ](involved|impacted)|re-?entry(?! permits?)|returning (citizens|home)|(currently|recently) incarcerated|(leaving|released from|after) (prison|jail)|on (parole|probation)|(impacted|affected) by (incarceration|the (criminal )?(legal|justice) system)",
    # "survivors" alone also means a veteran's surviving family or Holocaust survivors, so it needs a violence word.
    "Survivors of violence": r"domestic violence|intimate partner|dating (abuse|violence)|sexual (assault|abuse|violence|trauma)|gender[- ]based violence|trafficking|survivors? of (\w+ ){0,3}(violence|abuse|assault|crime|trafficking|rape|trauma)|crime victims?|victims? of (crime|violence|abuse)",
    "People without homes": r"homeless|unhoused|without homes|street homeless",
}

# A restriction needs explicit wording right before or after the audience, or an age range in the first sentence.
WINDOW = r"(?:[ \t]+[\w'’-]+){0,5}?[ \t]+"  # words separated by spaces only, so ")", "." or "," break a match
EXCLUSIVE = r"\b(only|exclusively|solely|limited to|restricted to|must be)\b"
AGE_RANGE = r"\bages? (\d{1,2})\s*(?:-|–|—|to|through)\s*(\d{1,2})\b|\b(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\s*years? old\b"
OPEN = r"\b(anyone|everyone|all new yorkers|all (?:ages|people|residents|individuals)|regardless of|open to (?:all|the public)|no (?:eligibility|referral) (?:requirements?|needed))\b"
CUE = r"\b(for|serv(?:es|ing)|supports?|assists?|helps?|connects|works with|dedicated to|designed for|run by and for)\b"

EVERYONE_BASIS = {"restricted": "", "mixed": "stated", "open": "stated", "not_stated": "assumed"}

OUTPUT_COLUMNS = ["resource_id", "org_name", "pdf_audiences", "confirmed_pdf_audiences", "unconfirmed_pdf_audiences",
                  "pdf_audience_check", "name_audiences", "description_audiences", "pdf_text_audiences",
                  "restricted_audiences", "focus_audiences", "audience_restriction", "restriction_evidence",
                  "everyone_basis", "audiences_all", "audience_needs_review", "audience_reviewed"]
REVIEW_COLUMNS = ["resource_id", "org_name", "description", "pdf_audiences", "pdf_audience_check",
                  "restricted_audiences", "focus_audiences", "audience_restriction", "audiences_all"]
NO_MATCH_COLUMNS = ["resource_id", "org_name", "row_type", "issue", "pdf_audiences", "unconfirmed_pdf_audiences",
                    "description", "pdf_text"]


def found_audiences(text):
    return [name for name, pattern in AUDIENCES.items() if re.search(pattern, text, re.I)]


def split(value):
    return [v.strip() for v in value.split(";") if v.strip()]


def join(values):
    return "; ".join(dict.fromkeys(values))


def first_sentence(text):
    return re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]


# ---------- 1. LOAD and find audiences in the three texts ----------
def load(in_file=IN_FILE, pdf_file=PDF_FILE):
    df = pd.read_csv(in_file, dtype=str, keep_default_na=False)
    pdf = pd.read_csv(pdf_file, dtype=str, keep_default_na=False)
    df["pdf_text"] = df["pdf_listing_id"].map(pdf.set_index("listing_id")["listing_text"]).fillna("")
    for column in ("description", "pdf_text"):
        df[column] = df[column].str.replace(EXTRACTION_NOTE, " ", regex=True, flags=re.I).str.strip()
    return df


def find_audiences(df):
    for column, text in [("name_audiences", "org_name"), ("description_audiences", "description"),
                         ("pdf_text_audiences", "pdf_text")]:
        df[column] = df[text].apply(lambda t: join(found_audiences(t)))
    df["text_audiences"] = df.apply(
        lambda r: join(split(r["name_audiences"]) + split(r["description_audiences"]) + split(r["pdf_text_audiences"])),
        axis=1)
    return df


# ---------- 2. CONFIRM the PDF audiences against the texts ----------
def confirm(row):
    pdf_aud, text_aud = split(row["pdf_audiences"]), split(row["text_audiences"])
    confirmed = [a for a in pdf_aud if a in text_aud]
    unconfirmed = [a for a in pdf_aud if a not in text_aud]
    if not pdf_aud:
        check = ""
    elif not unconfirmed:
        check = "confirmed"
    elif confirmed:
        check = "partly confirmed"
    else:
        check = "not confirmed"
    return pd.Series({"confirmed_pdf_audiences": join(confirmed), "unconfirmed_pdf_audiences": join(unconfirmed),
                      "pdf_audience_check": check})


# ---------- 3. RESTRICTED, open or not stated ----------
def explicit_restrictions(text, first_sentences):
    found = {}
    for name, pattern in AUDIENCES.items():
        aud = "(?:" + pattern + ")"
        m = (re.search(EXCLUSIVE + WINDOW + aud, text, re.I)
             or re.search(aud + r"(?:[ \t]+[\w'’-]+){0,2}?[ \t]+only\b", text, re.I))
        if m:
            found[name] = m.group(0)
    for sentence in first_sentences:
        for m in re.finditer(AGE_RANGE, sentence, re.I):
            low, high = [int(x) for x in m.groups() if x][:2]
            if 12 <= low and high <= 25:
                found.setdefault("Youth", m.group(0))
            elif low >= 55:
                found.setdefault("Older People", m.group(0))
    return found


def focus(row):
    named = split(row["name_audiences"])
    first = first_sentence(row["description"])
    cued = [n for n, p in AUDIENCES.items() if re.search(CUE + r"(?:\W+[\w'’-]+){0,6}?\W+(?:" + p + ")", first, re.I)]
    return join(named + cued)


def classify(row):
    text = row["description"] + " " + row["pdf_text"]
    limits = explicit_restrictions(text, [first_sentence(row["description"]), first_sentence(row["pdf_text"])])
    is_open = re.search(OPEN, text, re.I)
    if limits and is_open:
        status = "mixed"
    elif limits:
        status = "restricted"
    elif is_open:
        status = "open"
    else:
        status = "not_stated"
    evidence = list(limits.values()) + ([is_open.group(0)] if is_open else [])
    return pd.Series({
        "restricted_audiences": join(limits),
        "focus_audiences": focus(row),
        "audience_restriction": status,
        "restriction_evidence": " | ".join(evidence),
        "everyone_basis": EVERYONE_BASIS[status],
    })


# ---------- 4. COMBINE: no-match rule, audiences_all, needs_review ----------
def combine(row):
    tags = (split(row["pdf_audiences"]) + split(row["text_audiences"]) + split(row["restricted_audiences"])
            + split(row["focus_audiences"]))
    if row["everyone_basis"]:
        tags.append("Everyone")
    return join(tags)


def apply_rules(df):
    df = df.join(df.apply(confirm, axis=1))
    df = df.join(df.apply(classify, axis=1))

    # No-match rule: a row whose audiences the texts don't confirm is never restricted. Its audiences
    # stay (from the PDF or the text), the restriction becomes a focus, and it gets Everyone.
    no_match = (df["unconfirmed_pdf_audiences"] != "") | ((df["text_audiences"] == "") & (df["audience_restriction"] == "restricted"))
    lifted = no_match & (df["audience_restriction"] == "restricted")
    df.loc[lifted, "focus_audiences"] = df[lifted].apply(
        lambda r: join(split(r["focus_audiences"]) + split(r["restricted_audiences"])), axis=1)
    df.loc[lifted, "restricted_audiences"] = ""
    df.loc[lifted, "audience_restriction"] = "not_stated"
    df.loc[lifted, "everyone_basis"] = "assumed"

    df["audiences_all"] = df.apply(combine, axis=1)
    df["audience_needs_review"] = (
        df["audience_restriction"].isin(["restricted", "mixed"])
        | df["pdf_audience_check"].isin(["partly confirmed", "not confirmed"])
    )
    return df


def rank_for(data, audience):
    """Resources for one audience, best matches first. Adds a `rank` column (1, 2 or 3).

    The reference for the finder's filter: first resources made for the audience (restricted to or
    focused on it), then resources tagged with it, then resources for Everyone."""
    def rank(row):
        if audience in split(row["restricted_audiences"]) or audience in split(row["focus_audiences"]):
            return 1
        if audience in split(row["audiences_all"]):
            return 2
        if row["everyone_basis"]:
            return 3
        return None
    ranked = data.assign(rank=data.apply(rank, axis=1)).dropna(subset=["rank"])
    return ranked.astype({"rank": int}).sort_values(["rank", "org_name"])


# ---------- 5. REVIEW LISTS ----------
def issues_for_review(df):
    issues = pd.concat([
        df[df["unconfirmed_pdf_audiences"] != ""].assign(issue="PDF audience not confirmed"),
        df[(df["pdf_audiences"] == "") & (df["text_audiences"] == "")].assign(issue="no audience anywhere"),
    ])
    issues["is_cross_reference"] = issues["row_type"] == "cross_reference"
    return issues.sort_values(["is_cross_reference", "issue", "org_name"])


def review_sample(df):
    unreviewed = df[(df["row_type"] != "cross_reference") & ~df["audience_reviewed"]]
    sample = unreviewed.sample(min(50, len(unreviewed)), random_state=42)  # fewer than 50 left is fine
    review = sample[REVIEW_COLUMNS].copy()
    review["human_verdict"] = ""        # agree / change / unsure
    review["human_audiences"] = ""      # only for change: the correct list, separated by "; "
    review["human_restriction"] = ""    # only for change: restricted / open / not_stated
    review["human_notes"] = ""
    return review.sort_values("resource_id", key=lambda s: s.astype(int))


# ---------- 6. MANUAL DECISIONS override the rules ----------
def apply_reviewed(df, reviewed):
    df["audience_reviewed"] = False
    for _, r in reviewed.iterrows():
        rid = r["resource_id"].strip()
        match = df.index[df["resource_id"] == rid]
        if len(match) == 0:
            raise ValueError(f"reviewed_audiences.csv: resource_id {rid} is not in the data")
        i = match[0]
        if df.at[i, "org_name"].strip().lower() != r["org_name"].strip().lower():
            raise ValueError(f"reviewed_audiences.csv: resource_id {rid} is '{df.at[i, 'org_name']}', not '{r['org_name']}'")
        status = r["human_restriction"].strip()
        if status:
            if status not in ("restricted", "open", "not_stated"):
                raise ValueError(f"reviewed_audiences.csv: resource_id {rid}: human_restriction must be restricted, open or not_stated")
            df.at[i, "audience_restriction"] = status
            df.at[i, "everyone_basis"] = {"restricted": "", "open": "stated", "not_stated": "assumed"}[status]
        audiences = ([a for a in split(r["human_audiences"]) if a != "Everyone"]
                     or [a for a in split(df.at[i, "audiences_all"]) if a != "Everyone"])
        if df.at[i, "audience_restriction"] == "restricted" and r["human_audiences"].strip():
            df.at[i, "restricted_audiences"] = join(audiences)
        df.at[i, "audiences_all"] = join(audiences + (["Everyone"] if df.at[i, "everyone_basis"] else []))
        df.at[i, "audience_reviewed"] = True
        df.at[i, "audience_needs_review"] = False
    return df


def tag_audiences(df, reviewed):
    """The whole stage on a loaded frame; returns the full frame with every column."""
    return apply_reviewed(apply_rules(find_audiences(df)), reviewed)


def main():
    REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not REVIEWED_FILE.exists():
        pd.DataFrame(columns=["resource_id", "org_name", "human_audiences", "human_restriction", "human_notes"]).to_csv(REVIEWED_FILE, index=False)
    reviewed = pd.read_csv(REVIEWED_FILE, dtype=str, keep_default_na=False)

    df = tag_audiences(load(), reviewed)

    issues = issues_for_review(df)
    issues[NO_MATCH_COLUMNS].to_csv(NO_MATCH_FILE, index=False)
    df[OUTPUT_COLUMNS].to_csv(OUT_FILE, index=False)
    review = review_sample(df)
    review.to_csv(REVIEW_FILE, index=False)

    print(len(df), "rows,", (df["pdf_audiences"] != "").sum(), "with pdf_audiences,", (df["pdf_text"] != "").sum(), "with PDF listing text")
    print("Everyone:", df["audiences_all"].str.contains("Everyone").sum(), "of", len(df),
          "| restricted:", (df["audience_restriction"] == "restricted").sum(),
          "| manual decisions applied:", len(reviewed))
    print(len(issues), "rows written to", NO_MATCH_FILE.relative_to(ROOT))
    print(len(df), "rows written to", OUT_FILE.relative_to(ROOT))
    print(len(review), "rows written to", REVIEW_FILE.relative_to(ROOT))


if __name__ == "__main__":
    sys.exit(main())
