"""Parcours MCP complet sur une recherche et une image synthétiques (#112)."""
import hashlib
from pathlib import Path

import pytest
import respx
from chaine_archives import parcourir
from test_visionneuses import API, HOST, IMAGE, PARAMS, jpeg, metadata


def preparer(routes, fixtures):
    html = (fixtures / "ad59-recherche-positive.html").read_text().replace("registrefictif121", "registrefictif")
    html = html.replace("5 Mi FICTIF R 001", "2 E FICTIF")
    routes.get(HOST + "/search/results").respond(200, text=html)
    data = metadata()
    item = data["media"].pop("1")
    data["media"]["0"] = item
    data["positions"]["media"] = 0
    routes.get(API, params={"naan": "33518", "arkName": "registrefictif", "start": 0, "end": 0, "group": 0}).respond(200, json={"0": item})
    routes.get(API, params=PARAMS).respond(200, json=data)
    return routes.get(IMAGE).respond(200, content=jpeg())


@respx.mock
def test_recherche_navigation_archive_provenance_et_idempotence(app, fixtures):
    image = preparer(respx, fixtures)
    rapport = parcourir(app, "Commune-Fictive", 1860)
    assert rapport["vue_candidate_archivee"] and not rapport["acte_identifie"]
    assert image.call_count == 1
    archive = rapport["etapes"]["archivage"]
    fichier = Path(archive["chemin_absolu"])
    assert fichier.read_bytes() == jpeg()
    assert hashlib.sha256(jpeg()).hexdigest() in fichier.with_suffix(".md").read_text()
    assert any(e["operation"] == "piece_archiver" for e in app.journal.entries())


@respx.mock
def test_recherche_vide_arrete_la_chaine(app, fixtures):
    respx.get(HOST + "/search/results").respond(200, text=(fixtures / "ad59-recherche-negative.html").read_text())
    rapport = parcourir(app, "Commune-Fictive", 1200)
    assert list(rapport["etapes"]) == ["recherche"]
    assert app.journal.entries()[-1]["statut"] == "negatif"
    assert len(respx.calls) == 1


@pytest.mark.parametrize("etape", ["recherche", "navigation", "archivage"])
@respx.mock
def test_protection_arrete_chaine_et_conserve_tache(app, fixtures, etape):
    preparer(respx, fixtures)
    url = {"recherche": HOST + "/search/results", "navigation": API, "archivage": IMAGE}[etape]
    options = {"params": {"naan": "33518", "arkName": "registrefictif", "start": 0, "end": 0, "group": 0}} if etape == "navigation" else {}
    respx.get(url, **options).respond(403, text='<html><title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/cloudflare"></script></html>', headers={"content-type": "text/html"})
    rapport = parcourir(app, "Commune-Fictive", 1860)
    resultat = rapport["etapes"][etape]
    assert resultat.get("statut") == "bloque_antirobot" and resultat.get("tache_manuelle"), resultat
    assert list(rapport["etapes"])[-1] == etape
    assert not rapport.get("vue_candidate_archivee")
    assert app.journal.entries(statut="bloque_antirobot")


@respx.mock
def test_personne_decedee_fictive_guide_recherche_sans_envoyer_identite(app_famille, fixtures):
    arbre = app_famille.tree()
    naissance = arbre.personnes["I1"].events("BIRT")[0]
    naissance.date = "1860"
    naissance.lieu.nom = "Commune-Fictive, Nord, France"
    app_famille.store.write(arbre)  # préparation de fixture, avant le parcours
    preparer(respx, fixtures)
    personne = app_famille.tree().personnes["I1"]
    evenement = personne.events("BIRT")[0]
    rapport = parcourir(app_famille, evenement.lieu.nom.split(",")[0], int(evenement.date), personne.id)
    assert rapport["vue_candidate_archivee"]
    for appel in respx.calls:
        assert "MARTIN" not in str(appel.request.url) and "I1" not in str(appel.request.url)


@respx.mock
def test_personne_vivante_refusee_avant_reseau(app_famille):
    rapport = parcourir(app_famille, "Commune-Fictive", 1860, "I9")
    assert "refus" in rapport["etapes"]["recherche"]
    assert len(respx.calls) == 0
