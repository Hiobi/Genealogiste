"""#46 : dates impossibles refusées avec un message clair ; #45 : indépendance des sources."""

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.evidence import _norm_page, assess_citations, root_source
from genealogiste_mcp.models import Citation, Source, Tree
from genealogiste_mcp.normalize.dates import convert, date_problem, parse_date


@pytest.mark.parametrize("texte", ["31 FEB 2000", "29 FEB 1900", "2000-13-01", "2000-02-30", "31/04/1850",
                                   "BET 1900 AND 1850", "FRENCH_R 6 COMP 2", "31 février 1850", "0",
                                   "JULIAN 30 FEB 1700", "FRENCH_R 31 VEND 3", "99999999"])
def test_date_impossible_refusee_sans_exception(texte):
    assert parse_date(texte) is None
    assert "erreur" in convert(texte)


@pytest.mark.parametrize("texte", ["29 FEB 2000", "JULIAN 29 FEB 1900", "FRENCH_R 6 COMP 3", "BET 1850 AND 1900",
                                   "12 vendémiaire an III", "31 DEC 1999", "ABT 1820"])
def test_date_valide(texte):
    assert parse_date(texte) is not None


def test_message_clair():
    assert "29 jours" in date_problem("31 FEB 2000")
    assert "Intervalle inversé" in date_problem("BET 1900 AND 1850")
    assert date_problem("n'importe quoi") == ""


def test_proposition_date_impossible(app_famille):
    r = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I1",
                                "evenement": {"type": "RESI", "date": "31 FEB 1850", "non_source": True,
                                              "motif": "test"}}], "t", "j")
    assert "Date impossible" in r["erreur"] and "28 jours" in r["erreur"]


# ---------------------------------------------------------------- #45

def _arbre():
    t = Tree()
    t.sources["S1"] = Source("S1", titre="Registre", type_source="originale")
    t.sources["S2"] = Source("S2", titre="Relevé", type_source="derivee", original="S1")
    t.sources["S3"] = Source("S3", titre="Relevé du relevé", type_source="derivee", original="S2")
    t.sources["S4"] = Source("S4", titre="Autre registre", type_source="originale")
    return t


def _cit(src, page):
    return Citation(source=src, page=page, type_source="originale" if src in ("S1", "S4") else "derivee",
                    information="primaire", consultation="image")


@pytest.mark.parametrize("a,b", [("vue 1", "vue 01"), ("Vue 12", "v. 12"), ("f° 3", "folio 3"),
                                 ("acte n° 36", "acte 36"), ("p.466 n.36", "P. 466, n° 36")])
def test_localisations_equivalentes(a, b):
    assert _norm_page(a) == _norm_page(b)


def test_meme_acte_ecrit_differemment_une_seule_source():
    t = _arbre()
    r = assess_citations([_cit("S1", "vue 1"), _cit("S1", "vue 01")], t)
    assert r["sources_independantes"] == 1 and r["statut"] != "confirme"


def test_derivations_successives_non_independantes():
    t = _arbre()
    assert root_source(t, "S3") == "S1"
    r = assess_citations([_cit("S2", "p. 4"), _cit("S3", "p. 9")], t)
    assert r["sources_independantes"] == 1


def test_cycle_de_derivation_sans_boucle_infinie():
    t = _arbre()
    t.sources["S1"].original = "S3"
    assert root_source(t, "S2") in {"S1", "S2", "S3"}


def test_deux_originaux_distincts_confirment():
    t = _arbre()
    r = assess_citations([_cit("S1", "vue 1"), _cit("S4", "vue 7")], t)
    assert r["sources_independantes"] == 2
