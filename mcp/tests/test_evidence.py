from genealogiste_mcp.evidence import assess_citations, assess_person
from genealogiste_mcp.models import Citation


def _fact(facts, kind, date=None):
    return next(f for f in facts if f["fait"] == kind and (date is None or f.get("date") == date))


def test_confirmed_with_independent_sources(tree):
    birth = _fact(assess_person(tree, "I1"), "BIRT")
    # acte (original primaire direct = 2) + table décennale (dérivée de S1 : même groupe) + recensement (1)
    assert birth["statut"] == "confirme"
    assert birth["sources_independantes"] == 2
    assert birth["points"] == 3


def test_derived_sources_count_once(tree):
    cits = [Citation("S1", "acte 45", type_source="derivee"), Citation("S2", "TD")]
    r = assess_citations(cits, tree)
    assert r["sources_independantes"] == 1


def test_single_primary_original_is_probable(tree):
    marr = _fact(assess_person(tree, "I1"), "MARR")
    assert marr["statut"] == "probable"
    assert marr["prochaine_source"]


def test_composite_is_not_evidence(tree):
    death = _fact(assess_person(tree, "I2"), "DEAT")
    assert death["statut"] == "non_source"
    assert death["pistes_non_probantes"] == 1


def test_contradiction_detected(tree):
    facts = assess_person(tree, "I3")
    births = [f for f in facts if f["fait"] == "BIRT"]
    assert len(births) == 2 and all(f["statut"] == "contradictoire" for f in births)
    assert "dates incompatibles" in births[0]["contradictions"][0]


def test_strict_mode(tree):
    birth = _fact(assess_person(tree, "I1", strict=True), "BIRT")
    assert birth["statut"] == "probable"  # 2 groupes indépendants seulement


def test_unsourced_fact_points_next_source(tree):
    death = _fact(assess_person(tree, "I1"), "DEAT")
    assert death["statut"] == "non_source"
    assert any("décès" in s["source"].lower() for s in death["prochaine_source"])


def test_manual_refutation(tree):
    e = tree.personnes["I3"].events("BIRT")[1]
    from genealogiste_mcp.models import Assertion
    e.statut_manuel = Assertion("refute", "arbre en ligne sans source, contredit par l'acte")
    facts = assess_person(tree, "I3")
    good = _fact(facts, "BIRT", "3 MAY 1846")
    bad = _fact(facts, "BIRT", "1848")
    assert bad["statut"] == "refute"
    assert good["statut"] == "probable"  # la contradiction est levée
