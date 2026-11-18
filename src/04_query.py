"""
04_query.py - run the SPARQL queries in queries/*.rq on the ontology.

Prints each result as a table and saves it as Markdown in results/
(ready to paste into the README). Q4 is special: it shows only the facts
that the reasoner added (inferred graph minus asserted graph).

Run from the repo root (after 03_build_owl.py):
  python3 src/04_query.py
"""
from pathlib import Path

import pandas as pd
from rdflib import Graph

asserted = Graph().parse("ontology/pesticide.ttl")
inferred = Graph().parse("ontology/pesticide_inferred.ttl")
Path("results").mkdir(exist_ok=True)


def run(graph, query):
    res = graph.query(query)
    cols = [str(v) for v in res.vars]
    return pd.DataFrame([[str(x) if x is not None else "" for x in row] for row in res], columns=cols)


for qfile in sorted(Path("queries").glob("*.rq")):
    query = qfile.read_text()
    title = query.splitlines()[0].lstrip("# ").strip()
    df = run(inferred, query)

    if qfile.stem.startswith("q4"):
        before = run(asserted, query)
        df = df.merge(before, how="left", indicator=True)
        df = df[df["_merge"] == "left_only"].drop(columns="_merge")
        title += "  [only facts added by the reasoner]"

    print(f"\n{title}\n" + "-" * len(title))
    print(df.to_string(index=False) if not df.empty else "(no results)")
    (Path("results") / f"{qfile.stem}.md").write_text(f"**{title}**\n\n" + df.to_markdown(index=False) + "\n")

print("\nSaved results to results/*.md")
