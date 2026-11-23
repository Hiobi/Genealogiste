"""#138 : un outil réseau ne laisse jamais échapper d'exception ; toute erreur distante ou de validation
revient sous forme d'enveloppe d'erreur journalisée."""

from __future__ import annotations

import httpx
import pytest
import respx

from genealogiste_mcp import outils, server

# Paramètres minimaux plausibles pour appeler chaque outil réseau du catalogue.
APPELS: dict[str, dict] = {
    "matchid_recherche": {"nom": "Durand", "prenom": "Jean", "ne_vers": "1850"},
    "matchid_appariement_statut": {"job": "abc123"},
    "wikitree_recherche": {"nom": "Durand", "prenom": "Jean"},
    "wikitree_profil": {"cle": "Durand-1"},
    "wikitree_personne": {"cle": "Durand-1"},
    "wikitree_ascendants": {"cle": "Durand-1"},
    "wikitree_descendants": {"cle": "Durand-1"},
    "gallica_recherche": {"texte": "Durand"},
    "gallica_recherche_document": {"ark": "ark:/12148/bpt6k123456", "texte": "Durand"},
    "gallica_texte": {"ark": "ark:/12148/bpt6k123456", "page": 2},
    "gallica_alto": {"ark": "ark:/12148/bpt6k123456", "page": 2},
    "ark_resoudre": {"ark": "ark:/12148/bpt6k123456"},
    "archive_image": {"source": "https://iiif.example/iiif/vue1/info.json"},
    "piece_archiver": {"source": "https://iiif.example/iiif/vue1/info.json"},
    "wikidata_personne": {"nom": "Durand", "prenom": "Jean"},
    "wikidata_sparql": {"requete": "SELECT ?x WHERE { ?x wdt:P31 wd:Q5 } LIMIT 1"},
    "geo_commune": {"nom": "Lille"},
    "geo_historique": {"nom": "Lille"},
    "lieu_historique": {"lieu": "Lille, Nord", "date": "1975"},
    "recherche_multi": {"nom": "Durand", "prenom": "Jean"},
    "archives_naviguer": {"source": "https://iiif.example/iiif/registre/manifest.json"},
    "archives_registres": {"service": "AD59", "commune": "Somain", "annee": 1860},
    "gramps_recherche": {"texte": "Durand"},
    "gramps_personne": {"handle": "h1"},
    "diagnostic": {},
    "archives_planche": {"source": "ark:/33518/registrefictif", "de": 1},
    "presse_recherche": {"texte": "grève", "lieu": "Courrières"},
    "contexte_bibliographie": {"sujet": "mines", "lieu": "Courrières"},
}
# Hors périmètre : lit un fichier local avant tout appel réseau (couvert par test_sources).
SANS_APPEL = {"matchid_appariement_csv"}

RESEAU = sorted(n for n, (effet, _) in outils.OUTILS.items() if effet == outils.RESEAU)

PANNES = {
    "404": httpx.Response(404, text="introuvable"),
    "500": httpx.Response(500, text="erreur"),
    "timeout": httpx.ConnectTimeout("délai dépassé"),
}


def test_catalogue_couvert():
    assert set(RESEAU) == set(APPELS) | SANS_APPEL


@pytest.mark.parametrize("panne", sorted(PANNES))
@pytest.mark.parametrize("outil", sorted(APPELS))
def test_erreur_http_jamais_exception(app, outil, panne):
    app.config.gramps_url = "https://gramps.example"
    p = PANNES[panne]
    with respx.mock(assert_all_called=False) as m:
        route = m.route()
        if isinstance(p, Exception):
            route.mock(side_effect=p)
        else:
            route.mock(return_value=p)
        res = getattr(server, outil)(**APPELS[outil])
    assert isinstance(res, dict), res


@pytest.mark.parametrize("outil", ["gallica_recherche_document", "gallica_texte", "gallica_alto"])
def test_gallica_identifiant_invalide(app, outil):
    params = dict(APPELS[outil], ark="pas-un-ark")
    with respx.mock(assert_all_called=False):
        res = getattr(server, outil)(**params)
    assert "erreur" in res
    assert res.get("journal")
    entree = app.journal.entries(source="gallica")[0]
    assert entree["statut"] == "erreur"


def test_gallica_iiif_identifiant_invalide(app):
    res = server.gallica_iiif("pas-un-ark")
    assert "erreur" in res


def test_archives_naviguer_manifeste_404_enveloppe(app):
    with respx.mock(assert_all_called=False) as m:
        m.route().mock(return_value=httpx.Response(404))
        res = server.archives_naviguer("https://iiif.example/iiif/registre/manifest.json")
    assert "erreur" in res
    assert res.get("journal")
    assert app.journal.entries(statut="erreur")


def test_archives_naviguer_ark_service_non_qualifie(app):
    with respx.mock(assert_all_called=False) as m:
        m.route().mock(return_value=httpx.Response(404))
        res = server.archives_naviguer("ark:/64297/abc123")
    assert "erreur" in res
    assert res.get("journal")
    assert res.get("conseil")
