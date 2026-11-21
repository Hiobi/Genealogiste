"""#282 : fiche du chercheur et signets de la base Gramps, écrits hors transaction Gramps.

Contrat : lecture seule sans paramètre ; écriture seulement par proposition (diff), accord explicite (arbre_appliquer),
journal d'intention et annulation par Genealogiste (état antérieur mémorisé, conflit refusé). Faux Gramps Web fidèle
(écritures partielles, signet en fin de liste, hors historique), données fictives uniquement.
"""

from __future__ import annotations

import json

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed

from genealogiste_mcp import server
from genealogiste_mcp.gramps import reglages as rg

FICTIF = {"name": "Chercheur Fictif", "addr": "1 rue Inventée", "city": "Villefictive", "country": "France",
          "postal": "00000", "phone": "0100000000", "email": "chercheur@example.org"}
VIDE = {k: "" for k in rg.CHERCHEUR_CLES}


@pytest.fixture(autouse=True)
def sans_internet(monkeypatch):
    from genealogiste_mcp import diagnostic as diag
    monkeypatch.setattr(diag, "SOURCES", {})


@pytest.fixture
def fake(tree):
    with FakeGrampsWeb(role=4) as f:  # Owner : droit EditTree
        seed(f, tree)
        yield f


@pytest.fixture
def gapp(tmp_path, fake):
    a = make_app(tmp_path)
    yield a
    server.set_app(None)


def h(fake, gid):
    return fake.find("Person", gid)["handle"]


def ecritures(fake):
    return [c for c in fake.router.calls if c.request.method != "GET" and "/token/" not in str(c.request.url)]


def appliquer(res):
    assert "jeton" in res, res
    return server.arbre_appliquer(res["jeton"])


# ============================================================================ logique pure

def test_validation_du_chercheur():
    assert rg.valider_chercheur({"name": "X", "email": ""}) == {"name": "X", "email": ""}
    for mauvais in ({}, None, {"nom": "X"}, {"name": 3}, {"name": "a\nb"}, {"name": "a\x00"}, {"name": "x" * 301}):
        with pytest.raises(rg.ReglageError):
            rg.valider_chercheur(mauvais)


def test_operations_de_signets_comme_gramps():
    etat = {e: [] for e in rg.ESPACES.values()} | {"people": ["a", "b"]}
    ops = [{"action": "ajouter", "cible": "person", "id": "I3", "handle": "c"},
           {"action": "retirer", "cible": "person", "id": "I1", "handle": "a"}]
    assert rg.appliquer_operations(etat, ops)["people"] == ["b", "c"]
    with pytest.raises(rg.ReglageError):
        rg.appliquer_operations(etat, [{"action": "ajouter", "cible": "person", "id": "I2", "handle": "b"}])
    with pytest.raises(rg.ReglageError):
        rg.appliquer_operations(etat, [{"action": "retirer", "cible": "person", "id": "I9", "handle": "z"}])
    assert [o["action"] for o in rg.inverse(ops)] == ["ajouter", "retirer"]


def test_champs_hors_xml():
    xml, perdus = rg.chercheur_pour_xml({**VIDE, "name": "N", "street": "S", "county": "C", "city": "V"})
    assert xml == {"resname": "N", "rescity": "V"} and perdus == ["street", "county"]


# ============================================================================ le faux est fidèle

def test_le_faux_reproduit_le_contrat_amont(gapp, fake):
    c = gapp.backend.client
    assert c.chercheur() == VIDE
    # PUT partiel : les clés absentes ne bougent pas ; clé inconnue : 422 avant le contrôle de droit
    assert c.request("PUT", "/metadata/researcher/", json={"name": "A"}).status_code == 200
    assert c.request("PUT", "/metadata/researcher/", json={"email": "b@example.org"}).status_code == 200
    assert (c.chercheur()["name"], c.chercheur()["email"]) == ("A", "b@example.org")
    assert c.request("PUT", "/metadata/researcher/", json={"nom": "A"}).status_code == 422
    # signets : en fin de liste, 404 si l'objet ou le signet n'existe pas, namespace inconnu
    c.signet_poser("people", h(fake, "I1"))
    c.signet_poser("people", h(fake, "I2"))
    c.signet_poser("people", h(fake, "I1"))  # déjà présent : sans effet
    assert c.signets("people") == [h(fake, "I1"), h(fake, "I2")]
    assert c.request("PUT", "/bookmarks/people/inexistant").status_code == 404
    assert c.request("DELETE", "/bookmarks/people/inexistant").status_code == 404
    assert c.request("GET", "/bookmarks/gens").status_code == 404
    c.signet_retirer("people", h(fake, "I1"))
    assert c.signets("people") == [h(fake, "I2")]
    assert fake.transactions == [] and fake.messages == []  # hors historique des transactions


def test_le_faux_refuse_au_dessous_du_droit(gapp, fake):
    fake.role = 3  # Editor : signets oui, fiche du chercheur non
    c = gapp.backend.client
    c._exp = 0
    c._renew()
    assert c.request("PUT", "/metadata/researcher/", json={"name": "A"}).status_code == 403
    assert c.request("PUT", f"/bookmarks/people/{h(fake, 'I1')}").status_code == 200
    fake.role = 1
    c._exp = 0
    c._renew()
    assert c.request("PUT", f"/bookmarks/people/{h(fake, 'I2')}").status_code == 403


# ============================================================================ lecture

def test_lecture_sans_ecriture_ni_valeur(gapp, fake):
    fake.chercheur.update(FICTIF)
    fake.signets["people"].append(h(fake, "I2"))
    fake.formats_noms.append({"number": -1, "name": "Prénom NOM", "format": "%f %S", "active": True})
    r = server.gramps_reglages()
    assert "erreur" not in r and "jeton" not in r and r["nature"].startswith("lecture")
    assert r["chercheur"]["renseigne"] is True
    assert set(r["chercheur"]["champs_renseignes"]) == {"name", "addr", "city", "country", "postal", "phone", "email"}
    assert "Fictif" not in json.dumps(r) and "example.org" not in json.dumps(r)  # jamais les valeurs
    assert r["signets"] == {"person": [{"id": "I2", "handle": h(fake, "I2")}]}
    assert r["formats_noms"] == [{"numero": -1, "nom": "Prénom NOM", "format": "%f %S", "actif": True}]
    assert r["droits"] == {"chercheur_modifiable": True, "signets_modifiables": True}
    assert not ecritures(fake)


def test_mode_fichier_refuse(tmp_path):
    a = make_app(tmp_path, backend="fichier")
    try:
        assert "mode gramps" in server.gramps_reglages()["erreur"]
        assert "mode gramps" in server.gramps_reglages(chercheur={"name": "X"})["erreur"]
    finally:
        server.set_app(None)
    del a


# ============================================================================ fiche du chercheur

def test_chercheur_editor_refuse_avant_tout_calcul(tmp_path, tree):
    with FakeGrampsWeb(role=3) as f:
        seed(f, tree)
        make_app(tmp_path)
        try:
            r = server.gramps_reglages(chercheur=FICTIF)
            assert "Owner" in r["erreur"] and "jeton" not in r
            assert not ecritures(f)
            assert server.gramps_reglages()["droits"]["chercheur_modifiable"] is False
        finally:
            server.set_app(None)


def test_chercheur_cycle_complet_et_etat_initial_exact(gapp, fake, tmp_path):
    avant = dict(fake.chercheur)
    n_tx, n_msg = len(fake.transactions), len(fake.messages)
    prop = server.gramps_reglages(chercheur=FICTIF)
    assert prop["reglage"] == "chercheur" and prop["nature"].startswith("Écriture HORS transaction")
    assert {d["champ"] for d in prop["diff"]} == set(FICTIF)
    assert all(d["avant"] == "" for d in prop["diff"]) and {d["apres"] for d in prop["diff"]} >= {"Chercheur Fictif"}
    assert fake.chercheur == avant and not ecritures(fake)  # la proposition n'écrit rien
    # rien de la fiche dans le résumé des propositions en attente (listes, journal)
    assert "Fictif" not in json.dumps(gapp.backend.pending())
    res = server.arbre_appliquer(prop["jeton"])
    assert res["relecture"] == "conforme" and res["reglage"] == "chercheur" and "erreur" not in res
    assert fake.chercheur == {**VIDE, **FICTIF}
    assert len(fake.transactions) == n_tx and len(fake.messages) == n_msg  # hors historique du serveur
    journal = [e for e in gapp.backend.transactions() if e["id"] == prop["jeton"]][0]
    assert journal["type"] == "reglage" and journal["etat"] == "terminee" and journal["avant"] == avant
    assert journal["apres"] == fake.chercheur
    assert server.arbre_statut_transaction(prop["jeton"])["etat"] == "appliquee"
    assert server.arbre_historique()[0]["reglage"] == "chercheur"
    # annulation : proposition, accord, état initial EXACT (champs vides compris)
    und = server.arbre_annuler_modification(prop["jeton"])
    assert "jeton" in und and {d["champ"] for d in und["diff"]} == set(FICTIF)
    assert fake.chercheur == {**VIDE, **FICTIF}
    res2 = server.arbre_appliquer(und["jeton"])
    assert res2["annule"] == prop["jeton"] and fake.chercheur == avant == VIDE
    assert "déjà été annulée" in server.arbre_annuler_modification(prop["jeton"])["erreur"]
    assert len(fake.transactions) == n_tx


def test_chercheur_modification_partielle_restauree_exactement(gapp, fake):
    fake.chercheur.update({"name": "Ancien Nom", "city": "Ancienneville", "phone": "0"})
    avant = dict(fake.chercheur)
    prop = server.gramps_reglages(chercheur={"name": "Nouveau Nom", "city": ""})
    assert [d["champ"] for d in prop["diff"]] == ["name", "city"]
    server.arbre_appliquer(prop["jeton"])
    assert fake.chercheur == {**avant, "name": "Nouveau Nom", "city": ""}
    server.arbre_appliquer(server.arbre_annuler_modification(prop["jeton"])["jeton"])
    assert fake.chercheur == avant


def test_chercheur_sans_changement_refuse(gapp, fake):
    fake.chercheur["name"] = "Déjà"
    assert "ne modifie rien" in server.gramps_reglages(chercheur={"name": "Déjà"})["erreur"]


def test_chercheur_conflit_a_l_application(gapp, fake):
    prop = server.gramps_reglages(chercheur={"name": "Voulu"})
    fake.chercheur["name"] = "Modifié ailleurs"  # Gramps Desktop ou Web entre-temps
    r = server.arbre_appliquer(prop["jeton"])
    assert "Conflit" in r["erreur"] and fake.chercheur["name"] == "Modifié ailleurs" and not ecritures(fake)
    assert "inconnu" in server.arbre_appliquer(prop["jeton"])["erreur"]  # jeton consommé


def test_chercheur_conflit_a_l_annulation(gapp, fake):
    prop = server.gramps_reglages(chercheur={"name": "Voulu"})
    server.arbre_appliquer(prop["jeton"])
    fake.chercheur["name"] = "Autre"
    r = server.arbre_annuler_modification(prop["jeton"])
    assert "plus dans l'état" in r["erreur"] and fake.chercheur["name"] == "Autre"
    # conflit survenu entre la proposition d'annulation et son application
    fake.chercheur["name"] = "Voulu"
    und = server.arbre_annuler_modification(prop["jeton"])
    fake.chercheur["name"] = "Encore autre"
    assert "Conflit" in server.arbre_appliquer(und["jeton"])["erreur"] and fake.chercheur["name"] == "Encore autre"


def test_chercheur_valeurs_refusees(gapp, fake):
    for mauvais in ({"name": "a\nb"}, {"nom": "X"}, {"name": 3}, {}):
        assert "erreur" in server.gramps_reglages(chercheur=mauvais)
    assert not ecritures(fake)


def test_chercheur_jamais_deduit_de_l_environnement(gapp, fake, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Nom Git Secret")
    monkeypatch.setenv("USER", "nom_systeme")
    r = server.gramps_reglages(chercheur={"email": "x@example.org"})
    assert [d["champ"] for d in r["diff"]] == ["email"]  # un seul champ : aucun autre n'est inventé


def test_ecriture_refusee_par_le_serveur_ne_laisse_pas_d_ecriture(gapp, fake):
    prop = server.gramps_reglages(chercheur={"name": "X"})
    fake.role = 3  # compte rétrogradé entre-temps
    gapp.backend.client._exp = 0
    gapp.backend.client._renew()
    r = server.arbre_appliquer(prop["jeton"])
    assert "Owner" in r["erreur"] and fake.chercheur == VIDE


# ============================================================================ signets

def test_signets_cycle_complet_avec_signet_de_l_utilisateur(gapp, fake):
    fake.signets["people"] = [h(fake, "I5")]  # signet de l'utilisateur
    avant = {k: list(v) for k, v in fake.signets.items()}
    prop = server.gramps_reglages(signets={"ajouter": [{"cible": "person", "id": "I1"},
                                                        {"cible": "family", "id": "F1"}]})
    assert prop["diff"] == ["+ signet person I1", "+ signet family F1"] and prop["ajouts"] == 2
    assert fake.signets == avant and not ecritures(fake)
    res = server.arbre_appliquer(prop["jeton"])
    assert res["relecture"] == "conforme" and res["signets"] == {"ajoutes": ["I1", "F1"], "retires": []}
    assert fake.signets["people"] == [h(fake, "I5"), h(fake, "I1")]
    assert fake.signets["families"] == [fake.find("Family", "F1")["handle"]]
    assert fake.transactions == [] and fake.messages == []
    und = server.arbre_annuler_modification(prop["jeton"])
    assert und["diff"] == ["- signet family F1", "- signet person I1"] and und["ordre_restitue"] is True
    server.arbre_appliquer(und["jeton"])
    assert fake.signets == avant  # état initial exact, signet de l'utilisateur à sa place


def test_signets_retrait_annule_ordre_non_restitue(gapp, fake):
    fake.signets["people"] = [h(fake, "I1"), h(fake, "I2"), h(fake, "I3")]
    prop = server.gramps_reglages(signets={"retirer": [{"cible": "person", "id": "I1"}]})
    assert "ordre" in " ".join(prop["avertissements"])
    server.arbre_appliquer(prop["jeton"])
    assert fake.signets["people"] == [h(fake, "I2"), h(fake, "I3")]
    und = server.arbre_annuler_modification(prop["jeton"])
    assert und["ordre_restitue"] is False and "fin de liste" in und["avertissement"]
    res = server.arbre_appliquer(und["jeton"])
    assert res["relecture"] == "conforme"
    assert fake.signets["people"] == [h(fake, "I2"), h(fake, "I3"), h(fake, "I1")]  # mêmes signets, I1 en fin


def test_signets_refus_avant_proposition(gapp, fake):
    fake.signets["people"] = [h(fake, "I1")]
    for sig in ({"ajouter": [{"cible": "person", "id": "I1"}]},   # déjà en signet
                {"retirer": [{"cible": "person", "id": "I2"}]},   # pas en signet
                {"ajouter": [{"cible": "person", "id": "I99"}]},  # objet inconnu
                {"ajouter": [{"cible": "gens", "id": "I2"}]},     # cible inconnue
                {"ajouter": [{"cible": "person", "id": "I2"}, {"cible": "person", "id": "I2"}]},
                {"ajouter": [{"cible": "person"}]}, {"ajoute": []}, {}):
        assert "erreur" in server.gramps_reglages(signets=sig), sig
    assert not ecritures(fake)


def test_signets_conflit(gapp, fake):
    prop = server.gramps_reglages(signets={"ajouter": [{"cible": "person", "id": "I1"}]})
    fake.signets["people"].append(h(fake, "I2"))  # l'utilisateur ajoute un signet entre-temps
    r = server.arbre_appliquer(prop["jeton"])
    assert "Conflit" in r["erreur"] and fake.signets["people"] == [h(fake, "I2")]


def test_signets_annulation_refusee_si_modifies_depuis(gapp, fake):
    prop = server.gramps_reglages(signets={"ajouter": [{"cible": "person", "id": "I1"}]})
    server.arbre_appliquer(prop["jeton"])
    fake.signets["people"].append(h(fake, "I2"))
    assert "plus dans l'état" in server.arbre_annuler_modification(prop["jeton"])["erreur"]


def test_signets_editor_suffit_mais_pas_guest(tmp_path, tree):
    with FakeGrampsWeb(role=3) as f:
        seed(f, tree)
        make_app(tmp_path)
        try:
            r = server.gramps_reglages(signets={"ajouter": [{"cible": "person", "id": "I1"}]})
            server.arbre_appliquer(r["jeton"])
            assert f.signets["people"] == [h(f, "I1")]
        finally:
            server.set_app(None)
    with FakeGrampsWeb(role=1) as f:
        seed(f, tree)
        make_app(tmp_path)
        try:
            assert "erreur" in server.gramps_reglages(signets={"ajouter": [{"cible": "person", "id": "I1"}]})
        finally:
            server.set_app(None)


def test_reprise_apres_interruption_compare_l_etat(gapp, fake):
    """Intention journalisée puis arrêt : recover() compare l'état de la base à l'état avant / après."""
    prop = server.gramps_reglages(signets={"ajouter": [{"cible": "person", "id": "I1"}]})
    b = gapp.backend
    record = b.tokens.peek(prop["jeton"])
    b._log({"id": "x1", "type": "reglage", "reglage": "signets", "message": "m", "resume": [], "items": [],
            "avant": record["avant"], "apres": record["apres"], "operations": record["operations"],
            "etat": "intention"})
    assert b.recover() == [{"transaction": "x1", "etat": "non_envoyee"}]
    b._log({"id": "x2", "type": "reglage", "reglage": "signets", "message": "m", "resume": [], "items": [],
            "avant": record["avant"], "apres": record["apres"], "operations": record["operations"],
            "etat": "indeterminee"})
    fake.signets["people"].append(h(fake, "I1"))
    assert b.recover() == [{"transaction": "x2", "etat": "envoyee"}]
    assert [e for e in b.transactions() if e["id"] == "x2"][0]["etat"] == "envoyee"


# ============================================================================ signets d'une enquête

def test_enquete_signets_poses_puis_retires_sans_toucher_a_ceux_de_l_utilisateur(gapp, fake):
    fake.signets["people"] = [h(fake, "I2")]  # l'utilisateur a déjà I2 en signet
    e = server.enquete_ouvrir("naissance de Jean", ["I1", "I2", "I99"], signets=True)
    sig = e["signets"]
    assert sig["diff"] == ["+ signet person I1"] and sig["enquete"] == e["id"]
    assert any("I2" in n and "utilisateur" in n for n in sig["notes"]) and any("I99" in n for n in sig["notes"])
    assert fake.signets["people"] == [h(fake, "I2")]  # jamais appliqué seul
    res = server.arbre_appliquer(sig["jeton"])
    assert fake.signets["people"] == [h(fake, "I2"), h(fake, "I1")]
    assert res["enquete_signets"] == {"enquete": e["id"], "signets_poses": 1}
    etat = server.enquete_etat(e["id"])
    assert [t["id"] for t in etat["signets_poses"]] == ["I1"] and h(fake, "I2") not in json.dumps(etat["signets_poses"])
    # clôture : signalé, jamais exécuté seul
    cl = server.enquete_noter(e["id"], statut="close")
    assert cl["signets_a_retirer"]["nombre"] == 1 and "gramps_reglages" in cl["signets_a_retirer"]["consigne"]
    assert fake.signets["people"] == [h(fake, "I2"), h(fake, "I1")]
    ret = server.gramps_reglages(signets={"enquete": e["id"], "action": "retirer"})
    assert ret["diff"] == ["- signet person I1"]
    server.arbre_appliquer(ret["jeton"])
    assert fake.signets["people"] == [h(fake, "I2")]  # le signet de l'utilisateur reste
    assert "signets_poses" not in server.enquete_etat(e["id"])
    assert "ne modifie rien" in server.gramps_reglages(signets={"enquete": e["id"], "action": "retirer"})["erreur"]


def test_enquete_signet_retire_a_la_main_n_est_pas_reproposé(gapp, fake):
    e = server.enquete_ouvrir("x", ["I1"], signets=True)
    server.arbre_appliquer(e["signets"]["jeton"])
    fake.signets["people"].remove(h(fake, "I1"))  # retiré par l'utilisateur
    r = server.gramps_reglages(signets={"enquete": e["id"], "action": "retirer"})
    assert "erreur" in r and "ne modifie rien" in r["erreur"]


def test_enquete_annulation_met_la_trace_a_jour(gapp, fake):
    e = server.enquete_ouvrir("x", ["I1"], signets=True)
    server.arbre_appliquer(e["signets"]["jeton"])
    und = server.arbre_annuler_modification(e["signets"]["jeton"])
    res = server.arbre_appliquer(und["jeton"])
    assert fake.signets["people"] == [] and res["enquete_signets"]["signets_poses"] == 0
    assert "signets_poses" not in server.enquete_etat(e["id"])


def test_enquete_ouvrir_sans_signets_ne_touche_pas_a_gramps(gapp, fake):
    e = server.enquete_ouvrir("x", ["I1"])
    assert "signets" not in e and not ecritures(fake) and gapp.backend.pending() == []


def test_enquete_signets_hors_mode_gramps(tmp_path):
    make_app(tmp_path, backend="fichier")
    try:
        e = server.enquete_ouvrir("x", ["I1"], signets=True)
        assert "mode gramps" in e["signets"]["erreur"] and e["id"] == "x"
    finally:
        server.set_app(None)
