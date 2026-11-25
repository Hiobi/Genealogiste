"""citation.qualite : entier 0-3 exigé à la proposition, valeur illisible signalée à la lecture (#371)."""

import dataclasses

import pytest
from test_gramps_backend import fake, gapp  # noqa: F401 — fixtures

from genealogiste_mcp import server
from genealogiste_mcp.coherence import check_tree
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom


def _ops(qualite):
    return [{"op": "ajouter_evenement", "cible": "I1",
             "evenement": {"type": "OCCU", "valeur": "laboureur",
                           "citations": [{"source": "S1", "page": "f° 1", "qualite": qualite}]}}]


@pytest.mark.parametrize("qualite", ["originale", "2", 4, -1, 2.0, True, [3]])
def test_qualite_invalide_refusee(app_famille, qualite):
    avant = app_famille.store.text()
    out = server.arbre_proposer(_ops(qualite), "t", "j")
    assert "jeton" not in out, out
    assert "qualite doit valoir 0, 1, 2 ou 3" in out["erreur"] and "type_source" in out["erreur"]
    assert app_famille.store.text() == avant


@pytest.mark.parametrize("qualite", [0, 3, None])
def test_qualite_valide_acceptee(app_famille, qualite):
    out = server.arbre_proposer(_ops(qualite), "t", "j")
    assert out.get("jeton"), out


def test_gedcom_quay_invalide_signale(app_famille):
    texte = app_famille.store.text()
    assert "2 SOUR @S1@\n" in texte
    texte = texte.replace("2 SOUR @S1@\n", "2 SOUR @S1@\n3 QUAY originale\n", 1)
    tree = read_gedcom(texte)[0]
    alertes = [i for i in check_tree(tree) if i["code"] == "qualite_invalide"]
    assert len(alertes) == 1 and "'originale'" in alertes[0]["message"]
    assert alertes[0]["niveau"] == "alerte"
    # l'anomalie n'est pas sérialisée et ne change pas l'égalité des arbres
    assert "QUAY originale" not in write_gedcom(tree)
    assert dataclasses.replace(tree, anomalies=[]) == tree
    assert read_gedcom(write_gedcom(tree))[0].anomalies == []


def test_gramps_confiance_invalide_lisible(gapp, fake):
    cit = next(iter(fake.objects["Citation"].values()))
    cit["confidence"] = "originale"
    tree = gapp.tree()
    alertes = [i for i in check_tree(tree) if i["code"] == "qualite_invalide"]
    assert len(alertes) == 1 and "'originale'" in alertes[0]["message"]
    assert "supprimer_citation" in alertes[0]["message"]
