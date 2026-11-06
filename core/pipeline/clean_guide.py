# /// script
# requires-python = ">=3.10"
# dependencies = ["pandas"]
# ///
# Cleans the Connections Guide export into data/cleaned/resources_clean.csv.
#
# This is notebooks/data_cleaning_added_features.ipynb (Franziska) as a script, so the stage can
# run from the command line. The steps, rules and column names are the notebook's, in the same
# order, and the output is byte-for-byte the same; the notebook's markdown cells document the
# columns. Change the rules here and in the notebook together, or retire the notebook.
#
# Reads (from data/):
#   NYPL Connections Resources.csv   the guide, one row per listing
#   NYPLConnections_NoMatch.csv      rows the geocoders could not place (Windows-1252)
# Writes (to data/cleaned/):
#   resources_clean.csv              every row, cleaned, with empty latitude/longitude
#   review_list.csv                  the rows a person should look at (needs_review)
#
# Usage:
#   uv run pipeline/1_clean/clean_guide.py

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
OUT_DIR = DATA_DIR / "cleaned"

ADDRESS_COLUMNS = ["Street Number", "Address Line 2", "Street", "City", "State", "Zip Code", "note"]

ACRONYMS = ["NYC", "NYS", "NY", "HRA", "DSS", "DHS", "HIV", "AIDS", "LGBTQ", "LGBTQI", "CUNY",
            "SUNY", "YMCA", "YWCA", "GED", "HSE", "ESOL", "ATI", "PREA", "NEON", "II", "III"]
SMALL = ["and", "of", "for", "the", "in", "on", "to", "a", "an", "at", "with", "by", "or"]

# Guide subcategory and category to a standard service type. Subcategory wins.
BY_SUB = {"Organizations for People Without Homes": "Housing", "Tenant Rights & Housing Discrimination": "Housing",
          "Free & Low-Cost Medical Care": "Health & Mental Health", "HIV & AIDS": "Health & Mental Health",
          "General Health Information Resources": "Health & Mental Health", "Mental Health": "Health & Mental Health",
          "Helplines & Other Mental Health Resources": "Health & Mental Health",
          "Reproductive Health Information & Resources": "Health & Mental Health",
          "Treatment Programs & Organizations": "Addiction & Recovery", "Harm Reduction": "Addiction & Recovery",
          "Representation & Assistance": "Legal & Rights", "Grievances, Complaints & Government Agencies": "Legal & Rights",
          "Reporting Sexual Abuse & Assault (PREA)": "Legal & Rights", "Adult Literacy, HSE, & ESOL": "Education",
          "Continuing Education": "Education", "College Programs in Prison": "Education",
          "Computer Literacy & Digital Life Skills": "Education", "Food": "Food",
          "Financial Counseling & Rights": "Financial Assistance", "Taxes": "Financial Assistance"}
BY_CAT = {"Housing": "Housing", "Legal": "Legal & Rights", "Physical & Mental Health": "Health & Mental Health",
          "Addiction": "Addiction & Recovery", "Education": "Education", "Financial Assistance": "Financial Assistance",
          "Organizations for Job Seekers": "Employment", "Preparing for the Job Search": "Employment"}

# Description keywords, used only when the guide gives no type and exactly one service matches.
HINTS = {"Food": r"\bfood\b|pantr|soup kitchen|\bmeals?\b|grocer|nutrition",
         "Family & Childcare": r"child ?care|day ?care|after-?school|parenting|child welfare",
         "Housing": r"housing|shelter|homeless|tenant|eviction|rent assistance",
         "Health & Mental Health": r"mental health|counsel|therap|medical|clinic|health care|\bhealthcare\b",
         "Addiction & Recovery": r"addiction|substance|recovery|detox|sobriety",
         "Legal & Rights": r"legal|attorney|lawyer|court|civil rights|advocacy",
         "Education": r"college|literacy|\bged\b|\besol\b|school|training|education",
         "Employment": r"\bjobs?\b|employ|workforce|career|vocational|resume",
         "Financial Assistance": r"financial|benefits|\btax|public assistance|cash assistance",
         "Reentry Support": r"re-?entry|formerly incarcerated|parole|probation|prison release"}

RENAME = {"City": "city", "State": "state", "Phone Number": "phone", "Description": "description",
          "Category": "guide_category", "Subcategory": "guide_subcategory", "Address Line 2": "address_line_2",
          "Spanish-speaking (Y/N)": "spanish_speaking", "Works w/ Currently Incarcerated/Pre-release (Y/N)": "pre_release",
          "ATI Program (Y/N)": "ati_program", "Know Your Rights Content (Y/N)": "know_your_rights"}
OUTPUT_COLUMNS = ["resource_id", "org_name", "service_type", "service_type_suggested", "guide_category", "guide_subcategory",
                  "street", "address_line_2", "city", "state", "zip", "borough", "latitude", "longitude", "phone", "website",
                  "description", "spanish_speaking", "pre_release", "ati_program", "know_your_rights",
                  "row_type", "status", "source", "in_nomatch_file", "service_type_source", "service_type_confidence",
                  "organization_service_types", "service_type_conflict", "needs_review", "review_notes"]


# ---------- 0. LOAD (everything as text so ZIPs keep their zeros) ----------
def load(path):
    for enc in ("utf-8", "cp1252"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc, keep_default_na=False, na_values=[""])
        except UnicodeDecodeError:
            pass
    raise ValueError(f"{path}: not UTF-8 or Windows-1252")


# ---------- 1. NAMELESS ROWS (address or hours text of the row above) ----------
def merge_nameless_rows(df):
    for i in list(df.index[df["Organization Name"].isna()]):
        above = df.index[df.index.get_loc(i) - 1]
        if pd.notna(df.at[i, "Street"]):                       # second address -> copy details from above
            for col in df.columns:
                if col not in ADDRESS_COLUMNS:
                    df.at[i, col] = df.at[above, col]
            df.at[i, "note"] = "Address-only row, details copied from row above - verify"
        else:                                                  # text only -> add to note of row above
            df.at[above, "note"] += "Extra text: " + str(df.at[i, "Address Line 2"]) + " | "
            df = df.drop(index=i)
    return df.reset_index(drop=True)


# ---------- 2. NOMATCH PROVENANCE (matched by name+phone+website, in order) ----------
def key(d):
    k = d["Organization Name"].fillna("") + "|" + d["Phone Number"].fillna("") + "|" + d["Website"].fillna("")
    return k, k.groupby(k).cumcount()


def mark_nomatch(df, nm):
    df["k"], df["n"] = key(df)
    nm["k"], nm["n"] = key(nm)
    nm["in_nomatch_file"] = True
    df = df.merge(nm[["k", "n", "in_nomatch_file"]], how="left", on=["k", "n"])
    df["in_nomatch_file"] = df["in_nomatch_file"].fillna(False).astype(bool)
    df["latitude"] = pd.NA
    df["longitude"] = pd.NA
    return df


# ---------- 3. CLEAN ----------
def title(name):
    """ALL CAPS names to title case, keeping acronyms and anything in (brackets)."""
    if re.sub(r"\([^)]*\)", "", name).replace(" ", "").isupper():          # only ALL CAPS names
        parts = re.split(r"(\([^)]*\))", name)                               # keep (BRACKETS) as they are

        def fix(m):
            w = m.group(0)
            if w in ACRONYMS:
                return w
            if w.lower() in SMALL and m.start() > 0:
                return w.lower()
            return w.capitalize()

        def words(p):
            return re.sub(r"[A-Za-z][A-Za-z'’]*", fix, p)

        return "".join(p if p.startswith("(") else words(p) for p in parts)
    return name


def clean(df):
    df["org_name"] = df["Organization Name"].apply(title)
    df["street"] = (df["Street Number"].fillna("") + " " + df["Street"].fillna("")).str.strip()
    df["street"] = df["street"].replace("", None)
    df["zip"] = df["Zip Code"].str.zfill(5)
    df.loc[(df["City"] == "Brooklyn") & (df["zip"] == "12116"), "note"] += "ZIP 12116 changed to 11216 | "
    df.loc[(df["City"] == "Brooklyn") & (df["zip"] == "12116"), "zip"] = "11216"
    df["website"] = df["Website"].apply(lambda u: u if pd.isna(u) or u.startswith("http") else "https://" + u)
    return df


# ---------- 4. ENRICH ----------
def borough(z):
    if pd.isna(z):
        return None
    z = int(z)
    if 10001 <= z <= 10282:
        return "Manhattan"
    if 10301 <= z <= 10314:
        return "Staten Island"
    if 10451 <= z <= 10475:
        return "Bronx"
    if 11201 <= z <= 11256:
        return "Brooklyn"
    if 11004 <= z <= 11005 or 11101 <= z <= 11109 or 11351 <= z <= 11436 or 11691 <= z <= 11697:
        return "Queens"
    return None


def row_type(r):
    phone = str(r["Phone Number"])
    if re.search(r"\bbox\b", str(r["Street"]), re.I) or "mailing address" in str(r["Notes"]).lower():
        return "mailing_address"
    if pd.notna(r["street"]) or pd.notna(r["latitude"]):
        return "mapped" if (pd.notna(r["borough"]) or pd.notna(r["latitude"])) else "outside_nyc"
    if re.search(r"hotline|helpline|lifeline", phone + str(r["org_name"]), re.I) or re.match(r"\d{3}(?![\d.])", phone):
        return "hotline"
    if pd.notna(r["website"]):
        return "web_only"
    if pd.notna(r["Phone Number"]):
        return "hotline"
    if "see the full listing" in str(r["Description"]).lower():
        return "cross_reference"
    return "unclassified"


def matches(text):
    return [service for service, pattern in HINTS.items() if re.search(pattern, text, re.I)]


def description_match(description):
    """The one service a description names, or None when it names none or several."""
    found = matches(str(description))
    return found[0] if len(found) == 1 else None


def suggest(r):
    if pd.notna(r["service_type"]):
        return None
    text = " ".join(str(r[col]) for col in ["Description", "Subcategory", "Category"])
    found = matches(text)
    return "; ".join(found[:2]) or None


def org_key(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def enrich(df):
    df["borough"] = df["zip"].apply(borough)
    df.loc[df["State"] != "NY", "borough"] = None
    df["row_type"] = df.apply(row_type, axis=1)

    df["service_type"] = df["Subcategory"].map(BY_SUB).fillna(df["Category"].map(BY_CAT))
    df["service_type_source"] = df["service_type"].notna().map({True: "guide_mapping", False: "unassigned"})

    missing = df["service_type"].isna()
    df.loc[missing, "service_type"] = df.loc[missing, "Description"].apply(description_match)
    df.loc[missing & df["service_type"].notna(), "service_type_source"] = "description_match"
    df["service_type_confidence"] = df["service_type_source"].map({
        "guide_mapping": "high",
        "description_match": "medium",
        "unassigned": "unassigned",
    })
    df["service_type_suggested"] = df.apply(suggest, axis=1)

    # Apply an organization-wide type only when every known listing agrees.
    df["organization_key"] = df["org_name"].apply(org_key)
    org_types = df.groupby("organization_key")["service_type"].transform(
        lambda values: "; ".join(sorted(values.dropna().unique()))
    )
    df["organization_service_types"] = org_types.replace("", None)
    df["service_type_conflict"] = df.groupby("organization_key")["service_type"].transform(
        lambda values: values.dropna().nunique() > 1
    )

    org_type_counts = df.groupby("organization_key")["service_type"].transform(
        lambda values: values.dropna().nunique()
    )
    org_consensus = org_types.where(org_type_counts == 1)
    consensus_rows = df["service_type"].isna() & org_consensus.notna()
    df.loc[consensus_rows, "service_type"] = org_consensus[consensus_rows]
    df.loc[consensus_rows, "service_type_source"] = "organization_consensus"
    df.loc[consensus_rows, "service_type_confidence"] = "medium"

    # Conflicting organization listings are deliberately left blank rather than guessed.
    conflict_rows = df["service_type_conflict"]
    df.loc[conflict_rows, "service_type"] = pd.NA
    df.loc[conflict_rows, "service_type_source"] = "organization_conflict"
    df.loc[conflict_rows, "service_type_confidence"] = "unassigned"
    df["service_type_suggested"] = df.apply(suggest, axis=1)

    df["status"] = "active"
    df["source"] = "NYPL Connections 2026 team sheet"
    df["resource_id"] = list(range(1, len(df) + 1))
    return df


# ---------- 5. REVIEW FLAGS ----------
def flag_for_review(df):
    dup = df["org_name"] + "|" + df["street"].fillna("") + "|" + df["zip"].fillna("")
    df.loc[df["street"].notna() & dup.duplicated(keep=False), "note"] += "Same place under several chapters | "
    df.loc[df["in_nomatch_file"], "note"] += "In NoMatch file | "
    df.loc[df["Notes"].notna(), "note"] += "Original note: " + df["Notes"].fillna("") + " | "
    df.loc[df["service_type"].isna(), "note"] += "service_type to assign | "
    df.loc[df["row_type"] == "unclassified", "note"] += "row_type needs a decision | "
    df["review_notes"] = df["note"].str.strip(" |").replace("", None)
    df["needs_review"] = df["review_notes"].notna()
    return df


def clean_resources(guide, nomatch):
    """The whole stage on two loaded frames; returns the output frame with OUTPUT_COLUMNS."""
    df = guide.apply(lambda c: c.str.replace(r"\s+", " ", regex=True).str.strip())   # trim spaces
    df["note"] = ""
    df = merge_nameless_rows(df)
    df = mark_nomatch(df, nomatch)
    df = clean(df)
    df = enrich(df)
    df = flag_for_review(df)
    return df.rename(columns=RENAME)[OUTPUT_COLUMNS]


# ---------- 6. SAVE ----------
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = clean_resources(load(DATA_DIR / "NYPL Connections Resources.csv"),
                          load(DATA_DIR / "NYPLConnections_NoMatch.csv"))
    out.to_csv(OUT_DIR / "resources_clean.csv", index=False)
    out[out["needs_review"]].to_csv(OUT_DIR / "review_list.csv", index=False)
    print(len(out), "rows")
    print(out["row_type"].value_counts().to_string())
    print("service_type blank:", out["service_type"].isna().sum(), "| needs_review:", out["needs_review"].sum())


if __name__ == "__main__":
    sys.exit(main())
