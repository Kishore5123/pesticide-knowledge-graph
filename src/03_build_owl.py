"""
03_build_owl.py - build the pesticide ontology and run a reasoner.

Inputs:
  data/processed/substances_selected.csv   active substances (step 1)
  data/manual/relations.csv                salts, esters, metabolites (hand-curated)
  data/raw/pubchem/<CAS>.csv               PubChem identity per CAS (step 2)
Outputs:
  ontology/pesticide.ttl            asserted facts (readable on GitHub)
  ontology/pesticide.owl            same, RDF/XML for Protege
  ontology/pesticide_inferred.ttl   after reasoning
"""
import re
from pathlib import Path

import pandas as pd
import owlrl
from rdflib import Graph, Literal, Namespace, OWL, RDF, RDFS, XSD

PKG = Namespace("http://example.org/pesticide-kg#")
OUT = Path("ontology")


def iri(name):
    """'2,4-D dimethylamine salt' -> PKG:2_4_D_dimethylamine_salt"""
    return PKG[re.sub(r"[^A-Za-z0-9]+", "_", str(name)).strip("_")]


def pubchem(cas):
    f = Path(f"data/raw/pubchem/{cas}.csv")
    return pd.read_csv(f).iloc[0].to_dict() if f.exists() else {}


def add_identity(g, node, name, cas):
    g.add((node, RDF.type, OWL.NamedIndividual))     # so Protege lists it as an individual
    g.add((node, RDFS.label, Literal(name)))
    g.add((node, PKG.casNumber, Literal(cas)))
    info = pubchem(cas)
    for col, prop in [("CID", PKG.pubchemCID), ("InChIKey", PKG.inchiKey),
                      ("MolecularFormula", PKG.molecularFormula)]:
        if pd.notna(info.get(col)):
            g.add((node, prop, Literal(str(info[col]).removesuffix(".0"))))


def build_schema(g):
    for cls in ["ChemicalEntity", "ActiveSubstance", "Salt", "Ester", "Metabolite"]:
        g.add((PKG[cls], RDF.type, OWL.Class))
    for cls in ["ActiveSubstance", "Salt", "Ester", "Metabolite"]:
        g.add((PKG[cls], RDFS.subClassOf, PKG.ChemicalEntity))

    # isSaltOf / isEsterOf / isMetaboliteOf are all kinds of isFormOf,
    # and isFormOf is a kind of hasDenominator -> the reasoner links every
    # form to its parent active substance (the paper's "denominator").
    for p in ["hasDenominator", "isFormOf", "isSaltOf", "isEsterOf", "isMetaboliteOf"]:
        g.add((PKG[p], RDF.type, OWL.ObjectProperty))
    g.add((PKG.isFormOf, RDFS.subPropertyOf, PKG.hasDenominator))
    for p, cls in [("isSaltOf", "Salt"), ("isEsterOf", "Ester"), ("isMetaboliteOf", "Metabolite")]:
        g.add((PKG[p], RDFS.subPropertyOf, PKG.isFormOf))
        g.add((PKG[p], RDFS.domain, PKG[cls]))           # X isSaltOf Y  =>  X is a Salt
        g.add((PKG[p], RDFS.range, PKG.ActiveSubstance))

    for p in ["casNumber", "inchiKey", "pubchemCID", "molecularFormula", "approvalStatus",
              "euFunction", "approvalDate", "expiryDate", "adi", "arfd"]:
        g.add((PKG[p], RDF.type, OWL.DatatypeProperty))


def main():
    g = Graph()
    g.bind("pkg", PKG)
    g.bind("owl", OWL)
    g.add((PKG[""], RDF.type, OWL.Ontology))
    build_schema(g)

    subs = pd.read_csv("data/processed/substances_selected.csv")
    for _, s in subs.iterrows():
        node = iri(s["name"])
        g.add((node, RDF.type, PKG.ActiveSubstance))
        g.add((node, PKG.hasDenominator, node))          # an active substance is its own denominator
        add_identity(g, node, s["name"], s["cas"])
        g.add((node, PKG.approvalStatus, Literal(s["status"])))
        if pd.notna(s.get("functions")):
            g.add((node, PKG.euFunction, Literal(s["functions"])))
        for col in ["approval_date", "expiry_date"]:
            if pd.notna(s.get(col)):
                prop = PKG.approvalDate if col == "approval_date" else PKG.expiryDate
                g.add((node, prop, Literal(s[col], datatype=XSD.date)))
        for col in ["adi", "arfd"]:
            if pd.notna(s.get(col)):
                g.add((node, PKG[col], Literal(float(s[col]), datatype=XSD.decimal)))

    rel = pd.read_csv("data/manual/relations.csv")
    for _, r in rel.iterrows():
        form = iri(r["form_name"])
        add_identity(g, form, r["form_name"], r["form_cas"])
        g.add((form, PKG[r["relation"]], iri(r["parent_name"])))
        g.add((form, RDF.type, PKG.ChemicalEntity))     # its exact type is left to the reasoner
        g.add((form, RDFS.comment, Literal(r["source"])))

    OUT.mkdir(exist_ok=True)
    g.serialize(OUT / "pesticide.ttl", format="turtle")
    g.serialize(OUT / "pesticide.owl", format="xml")
    asserted = len(g)

    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)   # the reasoner
    g.serialize(OUT / "pesticide_inferred.ttl", format="turtle")
    print(f"Asserted triples: {asserted}   after reasoning: {len(g)}")

    print("\nDenominator of every chemical form (inferred):")
    q = """
    PREFIX pkg: <http://example.org/pesticide-kg#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?formLabel ?type ?denomLabel WHERE {
      ?form pkg:hasDenominator ?d ; rdfs:label ?formLabel ; a ?t .
      ?d rdfs:label ?denomLabel .
      VALUES ?t { pkg:ActiveSubstance pkg:Salt pkg:Ester pkg:Metabolite }
      BIND(STRAFTER(STR(?t), "#") AS ?type)
    } ORDER BY ?denomLabel ?type"""
    for row in g.query(q):
        print(f"  {row.formLabel:35} {row.type:16} -> {row.denomLabel}")


if __name__ == "__main__":
    main()
