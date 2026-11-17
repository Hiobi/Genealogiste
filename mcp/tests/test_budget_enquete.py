"""#157 : budget par enquête (requêtes par hôte, images, durée, coût estimé) avec arrêt propre, et plafond
journalier par hôte des services d'archives."""

from __future__ import annotations

import json
from datetime import date

import pytest
import respx
from test_enquetes import IMAGE, MANIFEST, REGISTRE, _jpeg, mock_ad59, mock_matchid

from genealogiste_mcp import budget, server
from genealogiste_mcp.budget import PlafondJour
from genealogiste_mcp.cache import Cache
from genealogiste_mcp.config import Config, load_config
from genealogiste_mcp.http import HttpClient, SourceError

MATCHID_HOTE = "deces.matchid.io"


@pytest.fixture
def routes():
    with respx.mock(assert_all_called=False) as router:
        yield router


def mock_iiif(routes, vues=3):
    routes.get(MANIFEST).respond(200, json={"items": [
        {"items": [{"items": [{"body": {"id": IMAGE, "type": "Image"}}]}]} for _ in range(vues)]})
    return routes.get(IMAGE).respond(200, content=_jpeg(), headers={"Content-Type": "image/jpeg"})


def _fichier(app, eid):
    return app.config.data_dir / "enquetes" / f"{eid}.json"


# ---------------------------------------------------------------------------- configuration

def test_defauts_prudents_et_variables_d_environnement(monkeypatch, tmp_path):
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path))
    cfg = load_config()
    assert cfg.budget_defaut() == {"requetes_par_hote": 200, "images": 40, "duree_min": 30.0,
                                   "cout_tokens": 100_000}
    assert cfg.plafond_jour_archives == 1000
    monkeypatch.setenv("GENEALOGISTE_BUDGET_IMAGES", "5")
    monkeypatch.setenv("GENEALOGISTE_BUDGET_REQUETES_HOTE", "0")
    monkeypatch.setenv("GENEALOGISTE_PLAFOND_JOUR_ARCHIVES", "300")
    cfg = load_config()
    assert cfg.budget_images == 5 and cfg.budget_requetes_hote == 0 and cfg.plafond_jour_archives == 300
    monkeypatch.setenv("GENEALOGISTE_BUDGET_COUT_TOKENS", "-1")
    with pytest.raises(ValueError, match="GENEALOGISTE_BUDGET_COUT_TOKENS"):
        load_config()


def test_budget_declare_a_l_ouverture_et_modifiable(app):
    e = server.enquete_ouvrir("Naissance de Jean", budget={"images": 3})
    assert e["budget"] == {**app.config.budget_defaut(), "images": 3}
    assert e["consomme"] == {"requetes": {}, "images": 0, "duree_s": 0.0, "cout_tokens": 0}
    server.enquete_noter(e["id"], budget={"cout_tokens": 5000, "duree_min": 0})
    etat = server.enquete_etat(e["id"])
    assert etat["budget"]["cout_tokens"] == 5000 and etat["budget"]["duree_min"] == 0
    assert "erreur" in server.enquete_noter(e["id"], budget={"inconnu": 1})
    assert "erreur" in server.enquete_noter(e["id"], budget={"images": -2})
    assert "erreur" in server.enquete_ouvrir("x", budget={"images": "beaucoup"})


# ---------------------------------------------------------------------------- comptage côté serveur

def test_reste_du_budget_renvoye_et_cache_non_compte(app, routes):
    route = mock_matchid(routes)
    eid = server.enquete_ouvrir("Décès de Jean", budget={"requetes_par_hote": 5})["id"]
    r1 = server.recherche_multi("Dupont", "Jean", sources=["matchid"], enquete=eid)
    assert route.call_count == 1
    assert r1["budget"]["reste"]["requetes_par_hote"][MATCHID_HOTE] == 4
    assert r1["budget"]["reste"]["cout_tokens"] < 100_000  # réponse texte comptée
    r2 = server.recherche_multi("Dupont", "Jean", sources=["matchid"], enquete=eid)  # servie par le cache
    assert route.call_count == 1
    assert r2["budget"]["reste"]["requetes_par_hote"][MATCHID_HOTE] == 4
    assert server.enquete_etat(eid)["consomme"]["requetes"] == {MATCHID_HOTE: 1}
    assert "budget" not in server.recherche_multi("Dupont", "Paul", sources=["matchid"])  # sans enquête


def test_navigation_et_images_consomment(app, routes):
    mock_ad59(routes)
    image = mock_iiif(routes)
    eid = server.enquete_ouvrir("Naissance de Jean")["id"]
    nav = server.archives_naviguer(REGISTRE, page=1, pas=3, enquete=eid)
    assert sum(server.enquete_etat(eid)["consomme"]["requetes"].values()) >= 1
    assert "budget" in nav
    img = server.archive_image(MANIFEST, page=1, enquete=eid)
    assert image.call_count == 1
    consomme = server.enquete_etat(eid)["consomme"]
    assert consomme["images"] == 1 and consomme["cout_tokens"] > 0 and consomme["duree_s"] >= 0
    assert img["budget"]["reste"]["images"] == 39


# ---------------------------------------------------------------------------- épuisement : arrêt propre

def test_depassement_refus_reste_a_faire_et_aucune_requete(app, routes):
    route = mock_matchid(routes)
    eid = server.enquete_ouvrir("Décès de Jean", personnes=["I1"], budget={"requetes_par_hote": 1})["id"]
    assert "refus" not in server.recherche_multi("Dupont", "Jean", sources=["matchid"], enquete=eid)
    assert route.call_count == 1

    r = server.recherche_multi("Dupont", "Pierre", sources=["matchid"], enquete=eid)
    assert route.call_count == 1  # refus AVANT la requête : rien n'est parti
    assert r["statut"] == "bloque" and r["motif"] == "budget" and r["limite"] == "requetes_par_hote"
    assert "refus" in r and r["budget"]["reste"]["requetes_par_hote"][MATCHID_HOTE] == 0
    etat = server.enquete_etat(eid)
    assert etat["statut"] == "bloque" and etat["blocage"]["motif"] == "budget"
    assert etat["reste_a_faire"][0]["outil"] == "recherche_multi"
    assert etat["reste_a_faire"][0]["parametres"]["prenom"] == "Pierre"
    assert etat["reste_a_faire"][0]["parametres"]["sources"] == ["matchid"]

    # bloquée : plus rien ne part, même vers un autre outil, et l'état reste exploitable
    nav = mock_ad59(routes)
    refus = server.archives_naviguer(REGISTRE, page=1, pas=3, enquete=eid)
    assert refus["statut"] == "bloque" and not any(x.called for x in nav.values())
    reprise = server.enquete_reprendre(eid)
    assert reprise["statut"] == "bloque" and reprise["blocage"]["motif"] == "budget"
    assert [a["outil"] for a in reprise["a_faire"][:2]] == ["recherche_multi", "archives_naviguer"]
    assert reprise["a_faire"][0]["type"] == "budget"
    assert eid in {x["id"] for x in server.enquete_reprendre()["enquetes"]}  # listée à reprendre

    # budget relevé : l'enquête repart et le reste à faire se vide en le faisant
    server.enquete_noter(eid, budget={"requetes_par_hote": 10})
    assert server.enquete_etat(eid)["statut"] == "ouverte"
    action = server.enquete_reprendre(eid)["a_faire"][0]
    r = getattr(server, action["outil"])(**action["parametres"], enquete=eid)
    assert "refus" not in r and route.call_count == 2
    assert [x["outil"] for x in server.enquete_etat(eid)["reste_a_faire"]] == ["archives_naviguer"]


def test_recherche_multi_partielle_garde_les_sources_restantes(app, routes):
    mock_matchid(routes)
    wikidata = routes.route(host="www.wikidata.org").respond(200, json={"search": []})
    eid = server.enquete_ouvrir("Décès de Jean", budget={"requetes_par_hote": 1})["id"]
    server.recherche_multi("Dupont", "Jean", sources=["matchid"], enquete=eid)
    r = server.recherche_multi("Dupont", "Paul", sources=["matchid", "wikidata"], enquete=eid)
    assert r["statut"] == "bloque" and not wikidata.called  # arrêt propre : sources suivantes non lancées
    assert server.enquete_etat(eid)["reste_a_faire"][0]["parametres"]["sources"] == ["matchid", "wikidata"]


def test_images_epuisees_refus_avant_telechargement(app, routes):
    image = mock_iiif(routes)
    eid = server.enquete_ouvrir("Naissance", budget={"images": 1})["id"]
    assert "refus" not in server.archive_image(MANIFEST, page=1, enquete=eid)
    r = server.archive_image(MANIFEST, page=2, enquete=eid)
    assert r["limite"] == "images" and image.call_count == 1
    assert server.enquete_etat(eid)["reste_a_faire"][0]["parametres"]["page"] == 2


def test_cout_estime_refuse_une_image_trop_chere(app, routes):
    image = mock_iiif(routes)
    eid = server.enquete_ouvrir("Naissance", budget={"cout_tokens": 50})["id"]
    r = server.archive_image(MANIFEST, page=1, largeur=1500, enquete=eid)
    assert r["limite"] == "cout_tokens" and not image.called
    assert not routes.calls  # même le manifeste n'est pas demandé


def test_duree_cumulee_epuisee(app, routes):
    route = mock_matchid(routes)
    eid = server.enquete_ouvrir("Décès", budget={"duree_min": 1})["id"]
    e = json.loads(_fichier(app, eid).read_text(encoding="utf-8"))
    e["consomme"]["duree_s"] = 61.0
    _fichier(app, eid).write_text(json.dumps(e), encoding="utf-8")
    r = server.recherche_multi("Dupont", sources=["matchid"], enquete=eid)
    assert r["limite"] == "duree_min" and not route.called


def test_zero_signifie_illimite(app, routes):
    route = mock_matchid(routes)
    eid = server.enquete_ouvrir("Décès", budget={"requetes_par_hote": 0})["id"]
    for prenom in ("A", "B", "C"):
        assert "refus" not in server.recherche_multi("Dupont", prenom, sources=["matchid"], enquete=eid)
    assert route.call_count == 3


def test_vivant_refuse_avant_tout_budget(app_famille, routes):
    route = routes.route().respond(200, json={})
    eid = server.enquete_ouvrir("Lucas", personnes=["I9"])["id"]
    r = server.recherche_multi("Martin", "Lucas", personne="I9", enquete=eid)
    assert "refus" in r and not route.called and "budget" not in r
    assert server.enquete_etat(eid)["consomme"]["requetes"] == {}


def test_fichier_d_enquete_ancien_sans_budget(app, routes):
    mock_matchid(routes)
    eid = server.enquete_ouvrir("Ancienne")["id"]
    e = json.loads(_fichier(app, eid).read_text(encoding="utf-8"))
    del e["budget"], e["consomme"]
    _fichier(app, eid).write_text(json.dumps(e), encoding="utf-8")
    r = server.recherche_multi("Dupont", sources=["matchid"], enquete=eid)
    assert r["budget"]["limites"] == app.config.budget_defaut()


# ---------------------------------------------------------------------------- plafond journalier

def test_plafond_journalier_par_hote_persistant(tmp_path):
    jour = [date(2026, 11, 17)]
    chemin = tmp_path / "cache.sqlite"

    def client():
        plafond = PlafondJour(Cache(chemin), 2, {"archives.exemple.org"}, jour=lambda: jour[0])
        return HttpClient(Cache(chemin), "test", plafond=plafond)

    with respx.mock(assert_all_called=False) as routes:
        archives = routes.get(url__startswith="https://archives.exemple.org/").respond(200, json={})
        autre = routes.get(url__startswith="https://ailleurs.exemple/").respond(200, json={})
        http = client()
        http.get("https://archives.exemple.org/a", use_cache=False)
        http.get("https://archives.exemple.org/b", use_cache=False)
        with pytest.raises(SourceError, match="plafond journalier") as exc:
            http.get("https://archives.exemple.org/c", use_cache=False)
        assert exc.value.reessayer_apres > 0
        assert archives.call_count == 2
        for _ in range(3):
            http.get("https://ailleurs.exemple/x", use_cache=False)  # hors services d'archives : pas de plafond
        assert autre.call_count == 3
        with pytest.raises(SourceError):  # redémarrage : le compteur persiste
            client().get("https://archives.exemple.org/d", use_cache=False)
        assert archives.call_count == 2
        jour[0] = date(2026, 11, 18)
        client().get("https://archives.exemple.org/e", use_cache=False)  # nouveau jour
        assert archives.call_count == 3


def test_plafond_journalier_applique_aux_services_d_archives(tmp_path, routes):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite",
                 wikitree_app_id="genealogiste-tests", plafond_jour_archives=1)
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    try:
        assert a.http.plafond.concerne("archivesdepartementales.lenord.fr")
        assert not a.http.plafond.concerne(MATCHID_HOTE)
        fenetres = mock_ad59(routes)
        r = server.archives_naviguer(REGISTRE, page=1, pas=3)  # sans enquête : seul le plafond s'applique
        assert "plafond journalier" in r["erreur"]
        assert sum(c.request.url.host == "archivesdepartementales.lenord.fr" for c in routes.calls) == 1
        assert fenetres
        assert a.cache.purge() >= 0 and a.http.plafond.etat()["consomme"]  # cache_purger ne remet pas à zéro
    finally:
        server.set_app(None)


def test_mesure_sans_enquete_inactive():
    assert budget._MESURE.get() is None
    budget.avant_envoi("x")  # sans mesure : aucun effet
