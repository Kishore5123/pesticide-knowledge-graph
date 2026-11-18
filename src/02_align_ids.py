"""
02_align_ids.py - combine the PubChem CSV files you downloaded by hand.

Put one file per CAS number in data/raw/pubchem/, named <CAS>.csv
(e.g. 1071-83-6.csv). Output: data/processed/identities.csv
"""
from pathlib import Path

import pandas as pd

subs = pd.read_csv("data/processed/substances_selected.csv")

rows = []
for f in sorted(Path("data/raw/pubchem").glob("*.csv")):
    info = pd.read_csv(f).iloc[0].to_dict()   # first row = best PubChem match
    info["cas"] = f.stem
    rows.append(info)
pubchem = pd.DataFrame(rows)

# one row per (substance, CAS form); the first CAS in cas_all is the main form
forms = subs[["id", "name", "cas_all"]].dropna(subset=["cas_all"]).copy()
forms["cas"] = forms["cas_all"].str.split(";")
forms = forms.explode("cas")
forms["is_primary_form"] = ~forms.duplicated("id")

ident = forms.drop(columns="cas_all").merge(pubchem, on="cas", how="left")
ident.to_csv("data/processed/identities.csv", index=False)

print(ident.to_string(index=False))
missing = ident[ident["CID"].isna()]["cas"].tolist()
if missing:
    print("\nNo PubChem file yet for:", missing)
