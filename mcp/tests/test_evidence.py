from genealogiste_mcp.evidence import assess_citations, assess_person
from genealogiste_mcp.models import Citation, Source, Tree


def _arbre():
    t = Tree()
    t.sources["S1"] = Source("S1", titre="Registre AD59 5 Mi 014 R 042", type_source="originale")
    t.sources["S2"] = Source("S2", titre="Table décennale", type_source="derivee", original="S1")
    return t


def _cit(src, page, **kw):
    d = {"type_source": "originale" if src == "S1" else "derivee",
         "information": "primaire", "preuve": "directe", "consultation": "image"}
    d.update(kw)
    return Citation(source=src, page=page, **d)


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


# ---------------------------------------------------------------- #105 : même acte, citations variées

def test_page_vide_rattachee_au_groupe_existant():
    r = assess_citations([_cit("S1", ""), _cit("S1", "vue 287, acte n°47")], _arbre())
    assert r["sources_independantes"] == 1
    assert r["statut"] == "probable"


def test_total_de_vues_et_commentaire_ignores():
    r = assess_citations([_cit("S1", "vue 287/1024, acte n°47 (4 juillet 1837)"),
                          _cit("S1", "vue 287, n° 47")], _arbre())
    assert r["sources_independantes"] == 1


def test_notations_equivalents_une_seule_source():
    r = assess_citations([_cit("S1", "p.287 n.47"), _cit("S1", "vue 287 acte 47")], _arbre())
    assert r["sources_independantes"] == 1


def test_deux_actes_distincts_deux_groupes():
    r = assess_citations([_cit("S1", "vue 287, n°47"), _cit("S1", "vue 353, n°72")], _arbre())
    assert r["sources_independantes"] == 2


def test_meme_vue_actes_differents_avertissement():
    r = assess_citations([_cit("S1", "vue 287, n°47"), _cit("S1", "vue 287, n°48")], _arbre())
    assert r["sources_independantes"] == 2
    assert r.get("localisation_ambigue")


def test_non_regression_45_zeros_de_tete():
    r = assess_citations([_cit("S1", "vue 1"), _cit("S1", "vue 01")], _arbre())
    assert r["sources_independantes"] == 1
