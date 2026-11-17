"""#155 : état de recherche persistant et reprenable, par enquête (pistes, registres, tâches, « déjà fait »)."""

from __future__ import annotations

import io
import json

import pytest
import respx

from genealogiste_mcp import server
from genealogiste_mcp.config import Config

HOST = "https://archivesdepartementales.lenord.fr"
API = HOST + "/visualizer/api"
REGISTRE = "ark:/33518/registrefictif"
UUID = "11111111-1111-4111-8111-111111111111"
PARAMS = {"naan": "33518", "arkName": "registrefictif"}
MATCHID = "https://deces.matchid.io/deces/api/v1/search"
MANIFEST = "https://archives.exemple.org/manifest.json"
IMAGE = "https://archives.exemple.org/vues/vue.jpg"


def _jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 60), "white").save(buf, "JPEG")
    return buf.getvalue()


def _media():
    return {"uuid": UUID, "url": f"{HOST}/{REGISTRE}/{UUID}", "location": {"original": "/images/vue.jpg"},
            "record": {"title": ["Registre fictif"], "referenceCode": ["3 E 1/1"]}}


def mock_ad59(routes, count=6, fenetres=((0, 2), (3, 5))) -> dict:
    """Une route par fenêtre de vues : compter les appels dit quelle fenêtre a été redemandée."""
    out = {}
    for de, a in fenetres:
        batch = {str(i): _media() for i in range(de, min(count, a + 1))}
        out[(de, a)] = routes.get(API, params={**PARAMS, "start": de, "end": a, "group": 0}).respond(200, json=batch)
    routes.get(API, params={**PARAMS, "uuid": UUID}).respond(200, json={"counts": {"media": count}})
    return out


def mock_matchid(routes):
    return routes.get(MATCHID).respond(200, json={"response": {"persons": [], "total": 0}})


@pytest.fixture
def routes():
    with respx.mock(assert_all_called=False) as router:
        yield router


# ---------------------------------------------------------------------------- stockage

def test_ouvrir_fichier_json_lisible_dans_les_donnees(app):
    e = server.enquete_ouvrir("Naissance de Jean Dupont vers 1860", personnes=["I1"])
    assert e["id"] == "naissance-de-jean-dupont-vers-1860"
    chemin = app.config.data_dir / "enquetes" / f"{e['id']}.json"
    contenu = json.loads(chemin.read_text(encoding="utf-8"))
    assert contenu["sujet"] == "Naissance de Jean Dupont vers 1860" and contenu["personnes"] == ["I1"]
    assert "\n  " in chemin.read_text(encoding="utf-8")  # indenté : lisible et diffable
    assert server.enquete_ouvrir("Naissance de Jean Dupont vers 1860")["id"].endswith("-2")
    assert "erreur" in server.enquete_ouvrir("x", id=e["id"])
    assert "erreur" in server.enquete_ouvrir("x", id="../evasion")
    assert e["id"] in {x["id"] for x in server.enquete_etat()["enquetes"]}


def test_etat_versionne_avec_le_journal(app):
    e = server.enquete_ouvrir("Décès de Marie", id="deces-marie")
    server.enquete_noter(e["id"], tache={"description": "Demander l'acte en mairie"})
    app.store.commit_internes()
    suivis = app.store._git("ls-files").split()
    assert "enquetes/deces-marie.json" in suivis
    assert not any(x.endswith(".lock") for x in suivis)


def test_noter_pistes_registres_taches(app):
    eid = server.enquete_ouvrir("Naissance de Jean", personnes=["I1"])["id"]
    r = server.enquete_noter(eid, piste={"question": "Naissance de Jean", "hypotheses": ["Somain 1860"],
                                         "sources": ["Tables décennales", {"libelle": "multi", "outil": "recherche_multi",
                                                                           "parametres": {"nom": "Dupont"}}]})
    assert r["modifie"] == ["piste p1"]
    server.enquete_noter(eid, registre={"source": f"{HOST}/{REGISTRE}/{UUID}", "service": "AD59", "piste": "p1",
                                        "nb_vues": 900, "bornes": [760, 900], "vues_lues": [[760, 800], 802, 801],
                                        "lectures": [{"vue": 834, "date": "1860-05-28", "type": "naissance",
                                                      "numero": "112"}]})
    server.enquete_noter(eid, tache={"description": "Registre paroissial non numérisé : salle de lecture",
                                     "service": "AD59"})
    etat = server.enquete_etat(eid)
    reg = etat["registres"][0]
    assert reg["cle"] == REGISTRE  # ARK de vue ramené au registre
    assert reg["vues_lues"] == [[760, 802], [834, 834]]
    assert etat["taches_manuelles"][0]["statut"] == "a_faire"
    assert etat["coherence_journal"] == "ok"
    reprise = server.enquete_reprendre(eid)
    assert reprise["registres_en_cours"][0]["vues_restantes"] == [[803, 833], [835, 900]]
    assert [a.get("outil") for a in reprise["a_faire"]] == [None, "recherche_multi", "archives_naviguer"]
    assert reprise["a_faire"][2]["parametres"] == {"source": f"{HOST}/{REGISTRE}/{UUID}", "page": 803, "pas": 20}
    assert len(reprise["taches_manuelles"]) == 1
    assert "erreur" in server.enquete_noter(eid, piste={"id": "p1", "statut": "trouvé"})  # orthographe sans accent
    assert "erreur" in server.enquete_noter("inconnue", tache={"description": "x"})


# ---------------------------------------------------------------------------- journal / état

def test_negatif_sans_reference_cree_une_entree_de_journal(app):
    eid = server.enquete_ouvrir("Mariage de Pierre", personnes=["I2"])["id"]
    server.enquete_noter(eid, piste={"question": "Mariage à Somain"})
    r = server.enquete_noter(eid, piste={"id": "p1", "statut": "negatif", "note": "Tables 1850-1870 vues"},
                             registre={"cote": "3 E 12/4", "statut": "negatif", "verdict": "pas d'acte en 1860"},
                             requete={"outil": "geneanet", "parametres": {"nom": "Martin"}, "resultat": "negatif"})
    assert len(r["journal_cree"]) == 3
    entrees = {e["id"]: e for e in server.journal_lister(source="enquete")}
    assert set(r["journal_cree"]) <= set(entrees)
    assert all(entrees[j]["statut"] == "negatif" and entrees[j]["personne"] == "I2" for j in r["journal_cree"])
    assert server.enquete_etat(eid)["coherence_journal"] == "ok"
    # renoter sans changement ne duplique pas la trace
    assert server.enquete_noter(eid, piste={"id": "p1", "statut": "negatif"})["journal_cree"] == []


def test_negatif_reference_existante_verifiee(app):
    eid = server.enquete_ouvrir("Décès de Paul")["id"]
    jid = server.journal_ajouter("ad59", "tables", "negatif", "Tables décennales 1860-1870 : absent")["journal"]
    r = server.enquete_noter(eid, piste={"question": "Décès", "statut": "negatif", "journal": jid})
    assert r["journal_cree"] == []
    assert server.enquete_etat(eid)["pistes"][0]["journal"] == [jid]
    assert "introuvable" in server.enquete_noter(eid, piste={"question": "Autre", "statut": "negatif",
                                                             "journal": "absent0000"})["erreur"]


def test_coherence_signale_un_negatif_sans_trace(app):
    eid = server.enquete_ouvrir("Édition manuelle")["id"]
    chemin = app.config.data_dir / "enquetes" / f"{eid}.json"
    e = json.loads(chemin.read_text(encoding="utf-8"))
    e["pistes"].append({"id": "p9", "question": "q", "statut": "negatif", "journal": []})
    chemin.write_text(json.dumps(e), encoding="utf-8")
    assert server.enquete_etat(eid)["coherence_journal"] != "ok"


# ---------------------------------------------------------------------------- « déjà fait le … »

def test_recherche_multi_deja_faite_signalee_sans_bloquer(app, routes):
    route = mock_matchid(routes)
    eid = server.enquete_ouvrir("Décès de Jean")["id"]
    r1 = server.recherche_multi("Dupont", "Jean", sources=["matchid"], enquete=eid)
    assert "deja_fait" not in r1 and r1["enquete"] == eid
    r2 = server.recherche_multi("  DUPONT ", "jean", sources=["matchid"])  # même requête normalisée
    assert route.call_count == 2  # jamais bloqué
    assert r2["deja_fait"][0]["enquete"] == eid and r2["deja_fait"][0]["message"].startswith("Déjà fait le ")
    assert "deja_fait" not in server.recherche_multi("Dupont", "Jeanne", sources=["matchid"])  # prudent
    requete = server.enquete_etat(eid)["requetes"][0]
    assert requete["resultat"] == "negatif" and requete["journal"]  # trace du journal de la source
    assert server.enquete_etat(eid)["coherence_journal"] == "ok"


def test_navigation_et_image_deja_faites(app, routes):
    mock_ad59(routes)
    eid = server.enquete_ouvrir("Naissance de Jean")["id"]
    r = server.archives_naviguer(REGISTRE, page=1, pas=3, enquete=eid)
    assert "erreur" not in r and "deja_fait" not in r
    reg = server.enquete_etat(eid)["registres"][0]
    assert reg["nb_vues"] == 6 and reg["cote"] == "3 E 1/1"
    again = server.archives_naviguer(f"{HOST}/{REGISTRE}", page=1, pas=3)
    assert again["deja_fait"][0]["enquete"] == eid
    assert "deja_fait" not in server.archives_naviguer(REGISTRE, page=4, pas=3)  # autre fenêtre
    # vue lue et notée : une image de la même vue le signale
    server.enquete_noter(eid, registre={"source": REGISTRE, "lectures": [{"vue": 2, "date": "1860-05-28",
                                                                         "type": "naissance", "numero": "12"}]})
    routes.get(MANIFEST).respond(200, json={"items": [
        {"items": [{"items": [{"body": {"id": IMAGE, "type": "Image"}}]}]} for _ in range(3)]})
    routes.get(IMAGE).respond(200, content=_jpeg(), headers={"Content-Type": "image/jpeg"})
    assert "deja_fait" not in server.archive_image(MANIFEST, page=2, enquete=eid)
    autre = server.archive_image(MANIFEST, page=2)
    assert autre["deja_fait"][0]["enquete"] == eid
    reg_iiif = [x for x in server.enquete_etat(eid)["registres"] if x["cle"] == MANIFEST][0]
    assert reg_iiif["vues_lues"] == [[2, 2]]
    assert "deja_fait" not in server.archive_image(MANIFEST, page=3)


def test_enquete_inconnue_n_empeche_pas_l_appel(app, routes):
    mock_matchid(routes)
    r = server.recherche_multi("Dupont", sources=["matchid"], enquete="inconnue")
    assert "enquete_avertissement" in r and "personnes" in r


def test_vivant_rien_ne_part_rien_n_est_note(app_famille, routes):
    route = routes.route().respond(200, json={})
    eid = server.enquete_ouvrir("Lucas", personnes=["I9"])["id"]
    r = server.recherche_multi("Martin", "Lucas", personne="I9", enquete=eid)
    assert "refus" in r and not route.called
    assert server.enquete_etat(eid)["requetes"] == []


# ---------------------------------------------------------------------------- reprise après interruption

def test_reprise_ne_relance_aucune_requete_deja_notee(app, routes, tmp_path):
    fenetres = mock_ad59(routes)
    matchid = mock_matchid(routes)
    eid = server.enquete_ouvrir("Naissance de Jean Dupont", personnes=["I1"])["id"]
    server.enquete_noter(eid, piste={"question": "Naissance de Jean", "sources": [
        {"libelle": "index des décès", "outil": "recherche_multi",
         "parametres": {"nom": "Dupont", "prenom": "Jean", "sources": ["matchid"]}},
        "Tables décennales de Somain"]})
    # session 1 : une recherche, une fenêtre de registre lue (vues 1 à 3), puis interruption
    server.recherche_multi("Dupont", "Jean", sources=["matchid"], enquete=eid)
    server.archives_naviguer(REGISTRE, page=1, pas=3, enquete=eid)
    server.enquete_noter(eid, registre={"source": REGISTRE, "vues_lues": [[1, 3]], "piste": "p1"})
    assert (matchid.call_count, fenetres[(0, 2)].call_count, fenetres[(3, 5)].call_count) == (1, 1, 0)

    # redémarrage : nouveau serveur, cache HTTP vide (toute requête relancée partirait sur le réseau)
    cfg = Config(data_dir=app.config.data_dir, cache_path=tmp_path / "autre-cache.sqlite",
                 wikitree_app_id="genealogiste-tests")
    server.set_app(server.App(cfg, sleeper=lambda s: None))
    reprise = server.enquete_reprendre(eid)
    assert {d["outil"] for d in reprise["deja_fait"]} == {"recherche_multi", "archives_naviguer"}
    for action in reprise["a_faire"]:
        if action.get("outil"):
            getattr(server, action["outil"])(**action["parametres"], enquete=eid)

    assert matchid.call_count == 1  # recherche notée : pas relancée
    assert fenetres[(0, 2)].call_count == 1  # vues 1-3 lues : pas refeuilletées
    assert fenetres[(3, 5)].call_count == 1  # seule la suite est demandée
    assert server.enquete_reprendre(eid)["registres_en_cours"][0]["vues_restantes"] == [[4, 6]]
    assert server.enquete_etat(eid)["coherence_journal"] == "ok"
