"""#154 : file de propositions durable (dépôt validé à sec, reprise sur l'arbre courant, lien jeton ↔ entrée),
pour les deux backends. Données fictives uniquement."""

from __future__ import annotations

import json

import pytest
from gramps_fake import FakeGrampsWeb

from genealogiste_mcp import server
from genealogiste_mcp.tree.proposals import TTL_SECONDS

UID_DECES = "11111111-1111-4111-8111-111111111113"
CIT_DEATH = [{"op": "ajouter_citation", "cible": {"type": "evenement", "uid": UID_DECES},
              "citation": {"source": "S1", "page": "Décès 1885, acte n° 3", "type_source": "originale",
                           "information": "primaire", "consultation": "image"}}]
SUPPR_DECES = [{"op": "supprimer_evenement", "uid": UID_DECES}]
SANS_SOURCE = [{"op": "ajouter_evenement", "cible": "I1", "evenement": {"type": "OCCU", "valeur": "tonnelier"}}]


def _deposer(ops=CIT_DEATH, **kw):
    return server.propositions_deposer(ops, kw.pop("titre", "Acte de décès de Jean MARTIN"),
                                       kw.pop("justification", "Acte lu sur le registre de Rochefort."), **kw)


def _ecrire(ops, titre="t", justification="j"):
    r = server.arbre_appliquer(server.arbre_proposer(ops, titre, justification)["jeton"])
    assert "erreur" not in r, r
    return r


# ---------------------------------------------------------------------------- mode fichier

def test_depot_persistant_lisible_sans_ecriture(app_famille):
    avant = app_famille.store.text()
    r = _deposer(sources=["S1"], pieces=["medias/1885-deces-martin.jpg"], enquete="martin-rochefort")
    assert "erreur" not in r and r["statut"] == "en_attente"
    assert "I1" in r["personnes"]
    assert app_famille.store.text() == avant  # rien n'est écrit dans l'arbre
    chemin = app_famille.config.proposals_dir / "file" / f"{r['id']}.json"
    e = json.loads(chemin.read_text(encoding="utf-8"))
    assert e["operations"] == CIT_DEATH and e["pieces"] == ["medias/1885-deces-martin.jpg"]
    assert e["enquete"] == "martin-rochefort" and e["sources"] == ["S1"] and e["depose"]
    assert "diff" not in e and not e["jeton"]


@pytest.mark.parametrize("ops,motif", [(SANS_SOURCE, "citation"), ([{"op": "inexistante"}], "inconnue")])
def test_depot_invalide_refuse(app_famille, ops, motif):
    r = _deposer(ops)
    assert motif in r["erreur"]
    assert server.propositions_lister(statut="tous")["propositions"] == []


def test_depot_sans_justification_ou_sans_effet_refuse(app_famille):
    assert "Justification" in _deposer(justification=" ")["erreur"]
    assert "ne modifie rien" in _deposer([])["erreur"]


def test_reprise_puis_application_marque_appliquee(app_famille):
    d = _deposer(pieces=["acte.jpg"])
    r = server.propositions_reprendre(d["id"])
    assert r["jeton"] and "Décès 1885" in r["diff"] and "nouvelles_alertes_coherence" in r
    assert r["proposition"]["pieces"] == ["acte.jpg"] and r["proposition"]["justification"]
    assert app_famille.store.text().count("Décès 1885") == 0
    a = server.arbre_appliquer(r["jeton"])
    assert a["commit"] and a["proposition_file"] == d["id"]
    e = server.propositions_lister(statut="appliquee")["propositions"][0]
    assert e["id"] == d["id"] and e["commit"] == a["commit"]
    assert server.propositions_lister()["propositions"] == []  # par défaut : en attente ou à revoir
    assert "erreur" in server.propositions_reprendre(d["id"])


def test_reprise_apres_modification_de_l_arbre_diff_frais(app_famille):
    d = _deposer()
    _ecrire([{"op": "modifier_personne", "id": "I7", "notes_ajout": ["Note ajoutée entre-temps."]}])
    r = server.propositions_reprendre(d["id"])
    assert "erreur" not in r
    assert server.arbre_appliquer(r["jeton"])["commit"]
    assert app_famille.store.text().count("Décès 1885") == 1


def test_conflit_marque_a_revoir_avec_raison(app_famille):
    d = _deposer()
    _ecrire(SUPPR_DECES)
    r = server.propositions_reprendre(d["id"])
    assert r["statut"] == "a_revoir" and r["erreur"]
    e = server.propositions_lister()["propositions"][0]
    assert e["statut"] == "a_revoir" and e["raison"] == r["raison"] and e["raison"]


def test_nouvelle_reprise_annule_l_ancien_jeton(app_famille):
    d = _deposer()
    j1 = server.propositions_reprendre(d["id"])["jeton"]
    j2 = server.propositions_reprendre(d["id"])["jeton"]
    assert j1 != j2 and not app_famille.tokens._path(j1).exists()
    assert "erreur" in server.arbre_appliquer(j1)


def test_abandon(app_famille):
    d = _deposer()
    jeton = server.propositions_reprendre(d["id"])["jeton"]
    r = server.propositions_abandonner(d["id"], motif="doublon d'une autre piste")
    assert r["statut"] == "abandonnee" and not app_famille.tokens._path(jeton).exists()
    assert "erreur" in server.propositions_reprendre(d["id"])
    assert "erreur" in server.propositions_abandonner(d["id"])
    assert "erreur" in server.propositions_reprendre("../etc")


def test_lister_resume_sans_operations(app_famille):
    _deposer(enquete="e1")
    _deposer(CIT_DEATH, titre="Autre")
    r = server.propositions_lister()
    assert r["compte"] == {"en_attente": 2}
    p = r["propositions"][0]
    assert p["nb_operations"] == 1 and "operations" not in p and p["enquete"] == "e1"
    assert "statut inconnu" in server.propositions_lister(statut="xyz")["erreur"]


def test_file_survit_au_redemarrage(app_famille, config):
    d = _deposer()
    b = server.App(config, sleeper=lambda s: None)
    server.set_app(b)
    assert server.propositions_lister()["propositions"][0]["id"] == d["id"]


def test_pending_sans_jetons_expires(app_famille):
    jeton = server.propositions_reprendre(_deposer()["id"])["jeton"]
    path = app_famille.tokens._path(jeton)
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["cree"] -= TTL_SECONDS + 1
    path.write_text(json.dumps(rec), encoding="utf-8")
    assert app_famille.backend.pending() == [] and not path.exists()
    assert server.propositions_lister()["propositions"][0]["statut"] == "en_attente"  # l'entrée survit


# ---------------------------------------------------------------------------- mode gramps

@pytest.fixture
def gapp(tmp_path, tree):
    from test_gramps_backend import make_app, seed
    with FakeGrampsWeb() as fake:
        seed(fake, tree)
        a = make_app(tmp_path)
        a.fake = fake
        yield a
    server.set_app(None)


def test_gramps_depot_reprise_application(gapp):
    n = len(gapp.fake.transactions)
    d = _deposer()
    assert "erreur" not in d and len(gapp.fake.transactions) == n
    r = server.propositions_reprendre(d["id"])
    assert r["jeton"] and "transaction_gramps" in r
    a = server.arbre_appliquer(r["jeton"])
    assert a["transaction"] == r["jeton"] and a["proposition_file"] == d["id"]
    e = server.propositions_lister(statut="appliquee")["propositions"][0]
    assert e["transaction"] == r["jeton"]


def test_gramps_conflit_a_revoir(gapp):
    d = _deposer()
    _ecrire(SUPPR_DECES)
    r = server.propositions_reprendre(d["id"])
    assert r["statut"] == "a_revoir"
    assert server.propositions_lister()["propositions"][0]["raison"]


def test_gramps_pending_sans_jetons_expires(gapp):
    jeton = server.propositions_reprendre(_deposer()["id"])["jeton"]
    path = gapp.tokens._path(jeton)
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["cree"] -= TTL_SECONDS + 1
    path.write_text(json.dumps(rec), encoding="utf-8")
    assert gapp.backend.pending() == []
