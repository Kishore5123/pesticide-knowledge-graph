"""
01_select.py
Step 1 of the pesticide ontology proof of concept.

Reads the EU Pesticides Database export (active substances), keeps the
columns that matter for the ontology and for later feature engineering,
cleans them, and writes two CSV files:

  data/processed/active_substances_clean.csv   all substances, cleaned
  data/processed/substances_selected.csv       only the substances you chose

Run from the repo root:
  python src/01_select.py
"""

import re
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
RAW_FILE = Path("data/raw/active_substances.xlsx")
# Hand-checked fixes for CAS errors in the EU file (name, corrected CAS, reason)
CORRECTIONS_FILE = Path("data/manual/cas_corrections.csv")
OUT_DIR = Path("data/processed")

# Substances for the proof of concept (lower case, as in the EU database name)
SELECTED = [
    "glyphosate",
    "chlorpyrifos",
    "captan",
    "mcpa",
    "2,4-d",
]

# Columns to keep: new_name -> keywords that must ALL appear in the original
# header (case-insensitive). Keywords are used because the exact header text
# can change between exports.
COLUMN_RULES = {
    "id":             ["active substance id"],
    "name":           ["substance"],
    "cas":            ["cas"],
    "status":         ["status"],
    "approval_date":  ["date of approval"],
    "expiry_date":    ["expir"],
    "remark":         ["remark"],
    "functions":      ["functions"],
    "candidate_for_substitution": ["candidate for substitution"],
    "basic_substance": ["basic substance"],
    "low_risk":       ["low-risk"],
    "authorised_in":  ["authorised"],
    "adi":            ["adi"],
    "arfd":           ["arfd"],
    "aoel":           ["aoel"],
    "aaoel":          ["aaoel"],
    "classification": ["classification"],
}

# Columns that hold a number with a unit, e.g. "0.5 mg/kg bw/day"
NUMERIC_COLS = ["adi", "arfd", "aoel", "aaoel"]
DATE_COLS = ["approval_date", "expiry_date"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def find_header_row(path: Path) -> int:
    """Return the row index that contains 'Active Substance ID'."""
    preview = pd.read_excel(path, header=None, nrows=20)
    for i, row in preview.iterrows():
        if row.astype(str).str.contains("Active Substance ID", case=False).any():
            return i
    raise ValueError("Could not find the header row with 'Active Substance ID'.")


def match_columns(columns) -> dict:
    """Map each original header to a short new name using COLUMN_RULES."""
    mapping = {}
    used = set()
    for new_name, keywords in COLUMN_RULES.items():
        for col in columns:
            text = str(col).lower()
            if col in used:
                continue
            # 'aoel' must not match 'aaoel', and 'substance' must not match the ID column
            if new_name == "aoel" and "aaoel" in text:
                continue
            if new_name == "name" and "id" in text:
                continue
            # only the first 'Remark' column (next to the RMS), not 'Remark.1' ...
            if new_name == "remark" and text != "remark":
                continue
            # skip the "reference" columns that sit next to ADI, ARfD, ...
            if new_name in NUMERIC_COLS and ("ref" in text or "source" in text):
                continue
            if all(k in text for k in keywords):
                mapping[col] = new_name
                used.add(col)
                break
    return mapping


def to_number(value):
    """'0.5 mg/kg bw/day' -> 0.5 ; 'Not applicable' or empty -> NaN."""
    if pd.isna(value):
        return float("nan")
    match = re.search(r"\d+(\.\d+)?", str(value).replace(",", "."))
    return float(match.group()) if match else float("nan")


def strip_html(value):
    """Remove tags like <p> ... </p> left in some cells."""
    if pd.isna(value):
        return value
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value))).strip()


# A CAS number looks like 1071-83-6. The last digit is a check digit.
# The last group may have 2 digits here only to catch typos like "133-06-02".
CAS_PATTERN = r"(?<![\d-])(\d{2,7})-(\d{2})-(\d{1,2})(?![\d-])"


def cas_checksum_ok(cas: str) -> bool:
    """CAS check digit: weighted sum of the other digits (from the right) mod 10."""
    digits = cas.replace("-", "")
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (i + 1) for i, d in enumerate(reversed(body)))
    return total % 10 == check


def parse_cas_list(text):
    """
    Find every CAS number in a piece of text and validate it.
    Returns a list of (cas, status) with status 'valid', 'repaired' or 'invalid'.
    'repaired' = a leading zero in the last group was removed (133-06-02 -> 133-06-2)
    and the result passed the checksum.
    """
    if pd.isna(text):
        return []
    # join digit groups split by a space, e.g. "101 205-02-1" -> "101205-02-1"
    # (only when the first part is not the end of another CAS number)
    text = re.sub(r"(?<![\d-])(\d{1,4}) (\d{2,6}-\d{2}-\d)", r"\1\2", str(text))
    results = []
    for a, b, c in re.findall(CAS_PATTERN, text):
        if len(c) == 1:
            cas = f"{a}-{b}-{c}"
            results.append((cas, "valid" if cas_checksum_ok(cas) else "invalid"))
        elif c.startswith("0"):
            cas = f"{a}-{b}-{c[1]}"
            results.append((cas, "repaired" if cas_checksum_ok(cas) else "invalid"))
        else:
            results.append((f"{a}-{b}-{c}", "invalid"))
    return results


def load_corrections() -> dict:
    """name -> corrected CAS, from data/manual/cas_corrections.csv (optional file)."""
    if not CORRECTIONS_FILE.exists():
        return {}
    fixes = pd.read_csv(CORRECTIONS_FILE)
    return dict(zip(fixes["name"].str.strip(), fixes["cas_corrected"].str.strip()))


CORRECTIONS = {}


def resolve_cas(row):
    """
    Pick the CAS for one substance.
    Uses the CAS column; if it says 'see remark', looks in the Remark column.
    """
    if row["name"] in CORRECTIONS:
        cas = CORRECTIONS[row["name"]]
        ok = cas_checksum_ok(cas)
        return pd.Series({"cas": cas if ok else pd.NA, "cas_all": cas if ok else pd.NA,
                          "cas_status": "manual_fix" if ok else "invalid"})
    found = parse_cas_list(row["cas_raw"])
    source = "cas_column"
    if not found and "remark" in str(row["cas_raw"]).lower() and "remark" in row:
        found = parse_cas_list(row["remark"])
        source = "remark"
    good = [cas for cas, status in found if status != "invalid"]
    if not good:
        status = "invalid" if found else "missing"
        return pd.Series({"cas": pd.NA, "cas_all": pd.NA, "cas_status": status})
    first_status = next(s for c, s in found if c == good[0])
    status = first_status if source == "cas_column" else f"{first_status}_from_remark"
    return pd.Series({"cas": good[0], "cas_all": ";".join(good), "cas_status": status})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global CORRECTIONS
    CORRECTIONS = load_corrections()
    if CORRECTIONS:
        print(f"Loaded {len(CORRECTIONS)} manual CAS corrections")
    header_row = find_header_row(RAW_FILE)
    df = pd.read_excel(RAW_FILE, header=header_row)

    mapping = match_columns(df.columns)
    print("Columns kept (original -> new):")
    for old, new in mapping.items():
        print(f"  {old!r:55} -> {new}")
    missing = set(COLUMN_RULES) - set(mapping.values())
    if missing:
        print(f"\nWARNING: not found, check the headers: {sorted(missing)}")

    df = df[list(mapping)].rename(columns=mapping)
    df = df.dropna(subset=["name"])

    # Cleaning
    df["name"] = df["name"].astype(str).str.strip()
    df["name_key"] = df["name"].str.lower()           # for matching
    df["cas_raw"] = df["cas"]                          # keep original text for the README
    df[["cas", "cas_all", "cas_status"]] = df.apply(resolve_cas, axis=1)
    for col in NUMERIC_COLS:
        if col in df:
            df[col] = df[col].apply(to_number)
    for col in DATE_COLS:
        if col in df:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce").dt.date
    for col in df.columns:
        if df[col].dtype == object or pd.api.types.is_string_dtype(df[col]):
            df[col] = df[col].apply(strip_html)

    # Extra features
    if "authorised_in" in df:
        df["n_countries_authorised"] = df["authorised_in"].apply(
            lambda v: 0 if pd.isna(v) or not str(v).strip()
            else len([c for c in str(v).split(",") if c.strip()])
        )
    for col in ["candidate_for_substitution", "basic_substance", "low_risk"]:
        if col in df:
            # a filled cell means "yes"; empty means "no"
            df[col] = df[col].notna() & (df[col].astype(str).str.strip() != "")

    # Data-quality summary (useful for the README)
    print(f"\nTotal substances: {len(df)}")
    print(df["status"].value_counts(dropna=False).to_string())
    print(f"Without a valid CAS number: {df['cas'].isna().sum()}")
    print("\nCAS status:")
    print(df["cas_status"].value_counts().to_string())

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_DIR / "active_substances_clean.csv", index=False)

    selected = df[df["name_key"].isin(SELECTED)]
    not_found = set(SELECTED) - set(selected["name_key"])
    if not_found:
        print(f"\nWARNING: not found in the file: {sorted(not_found)}")
    selected.to_csv(OUT_DIR / "substances_selected.csv", index=False)

    print(f"\nSaved {len(df)} rows to active_substances_clean.csv")
    print(f"Saved {len(selected)} rows to substances_selected.csv")
    print(selected[["id", "name", "cas", "status", "adi", "arfd"]].to_string(index=False))
    print("\nRaw CAS text for the selected substances:")
    print(selected[["name", "cas_raw", "cas_all", "cas_status"]].to_string(index=False))
    if "remark" in selected:
        print("\nRemarks for the selected substances:")
        for _, r in selected.iterrows():
            if pd.notna(r["remark"]) and str(r["remark"]).strip():
                print(f"- {r['name']}: {r['remark']}")


if __name__ == "__main__":
    main()
