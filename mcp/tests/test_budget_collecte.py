"""#211 (lot C) : tous les outils de collecte qui émettent des requêtes réseau comptent dans le budget d'enquête.

La liste est dérivée du catalogue (outils.BUDGET_ENQUETE : effet réseau, classe collecte, hors exemptions
motivées) ; chaque outil accepte le paramètre facultatif ``enquete`` (exposé dans son schéma) et ses requêtes
réellement émises sont comptées par hôte (respx)."""

from __future__ import annotations

import asyncio
import inspect

import pytest
import respx
from test_budget_enquete import mock_iiif
from test_enquetes import MANIFEST, REGISTRE, mock_ad59

from genealogiste_mcp import outils, server

# Arguments minimaux qui provoquent au moins une requête réseau. Un outil ajouté au périmètre sans exemple fait
# échouer test_exemples_couvrent_le_perimetre.
EXEMPLES: dict[str, dict] = {
    "matchid_recherche": {"nom": "Dupont", "prenom": "Jean"},
    "wikitree_recherche": {"nom": "Dupont", "prenom": "Jean"},
    "wikitree_profil": {"cle": "Dupont-1"},
    "wikitree_personne": {"cle": "Dupont-1"},
    "wikitree_ascendants": {"cle": "Dupont-1"},
    "wikitree_descendants": {"cle": "Dupont-1"},
    "gallica_recherche": {"texte": "Jean Dupont"},
    "gallica_recherche_document": {"ark": "ark:/12148/bpt6k123456", "texte": "Dupont"},
    "gallica_texte": {"ark": "ark:/12148/bpt6k123456", "page": 1},
    "gallica_alto": {"ark": "ark:/12148/bpt6k123456", "page": 1},
    "ark_resoudre": {"ark": "ark:/12148/bpt6k123456"},
    "archive_image": {"source": MANIFEST, "page": 1},
    "piece_archiver": {"source": MANIFEST, "page": 1},
    "wikidata_personne": {"nom": "Dupont", "prenom": "Jean"},
    "wikidata_sparql": {"requete": "SELECT ?x WHERE { ?x ?y ?z } LIMIT 1"},
    "geo_commune": {"nom": "Lille"},
    "geo_historique": {"code_insee": "59350"},
    "recherche_multi": {"nom": "Dupont", "prenom": "Jean", "sources": ["matchid"]},
    "archives_naviguer": {"source": REGISTRE, "page": 1, "pas": 3},
    "archives_registres": {"service": "AD59", "commune": "Lille", "annee": 1850},
    "archives_planche": {"source": REGISTRE, "de": 1, "a": 2},
}


@pytest.fixture
def routes():
    with respx.mock(assert_all_called=False) as router:
        mock_ad59(router)
        mock_iiif(router)
        router.route().respond(200, json={})  # toute autre requête : réponse vide, mais émise et comptée
        yield router


def test_perimetre_derive_du_catalogue():
    reseau_collecte = {n for n, (e, c) in outils.OUTILS.items() if e == outils.RESEAU and c == outils.COLLECTE}
    assert outils.BUDGET_ENQUETE == reseau_collecte - set(outils.HORS_BUDGET)
    assert set(outils.HORS_BUDGET) <= reseau_collecte  # exemption = outil réseau de collecte, motivée
    assert all(motif.strip() for motif in outils.HORS_BUDGET.values())
    assert {"archives_registres", "ark_resoudre", "archives_planche", "piece_archiver", "geo_commune",
            "wikitree_profil", "gallica_texte", "matchid_recherche", "wikidata_sparql"} <= outils.BUDGET_ENQUETE
    # sans réseau : jamais de paramètre enquete
    for nom in ("enquete_ouvrir", "rapport_campagne_enregistrer", "journal_ajouter", "geo_commune"):
        assert (nom in outils.BUDGET_ENQUETE) == (nom == "geo_commune")


def test_exemples_couvrent_le_perimetre():
    assert set(EXEMPLES) == outils.BUDGET_ENQUETE


def test_schema_expose_enquete_facultatif():
    exposes = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    for nom in outils.BUDGET_ENQUETE:
        schema = exposes[nom].input_schema
        assert schema["properties"]["enquete"]["type"] == "string", nom
        assert schema["properties"]["enquete"].get("default") == "", nom
        assert "enquete" not in schema.get("required", []), nom
        assert "enquete" in exposes[nom].description, nom
        assert "enquete" in inspect.signature(getattr(server, nom)).parameters, nom
    for nom in set(outils.OUTILS) - outils.BUDGET_ENQUETE:
        if nom in ("enquete_noter", "enquete_etat", "enquete_reprendre", "propositions_deposer", "archives_sonder"):
            continue  # « enquete » y désigne l'enquête gérée, pas un budget
        assert "enquete" not in exposes[nom].input_schema["properties"], nom


@pytest.mark.parametrize("nom", sorted(EXEMPLES))
def test_requetes_comptees_dans_le_budget(app, routes, nom):
    eid = server.enquete_ouvrir(f"Budget {nom}")["id"]
    res = getattr(server, nom)(**EXEMPLES[nom], enquete=eid)
    consomme = server.enquete_etat(eid)["consomme"]
    assert sum(consomme["requetes"].values()) >= 1, (nom, res)
    assert sum(consomme["requetes"].values()) == len(routes.calls), nom
    assert "budget" in res and "reste" in res["budget"], nom


@pytest.mark.parametrize("nom", sorted(EXEMPLES))
def test_sans_enquete_rien_n_est_compte(app, routes, nom):
    eid = server.enquete_ouvrir(f"Témoin {nom}")["id"]
    res = getattr(server, nom)(**EXEMPLES[nom])
    assert "budget" not in res
    assert server.enquete_etat(eid)["consomme"]["requetes"] == {}


@pytest.mark.parametrize("nom", sorted(EXEMPLES))
def test_enquete_bloquee_aucune_requete(app, routes, nom):
    eid = server.enquete_ouvrir(f"Bloquée {nom}", budget={"requetes_par_hote": 1})["id"]
    assert "refus" not in server.geo_commune(nom="Lille", enquete=eid)
    server.geo_commune(nom="Douai", enquete=eid)  # 2e requête vers le même hôte : refusée, enquête bloquée
    assert server.enquete_etat(eid)["statut"] == "bloque"
    avant = len(routes.calls)
    res = getattr(server, nom)(**EXEMPLES[nom], enquete=eid)
    assert len(routes.calls) == avant, nom  # refus AVANT toute requête
    assert res["statut"] == "bloque" and res["motif"] == "budget", nom
    assert any(x["outil"] == nom for x in server.enquete_etat(eid)["reste_a_faire"]), nom


def test_refus_en_cours_d_appel_consigne_l_appel(app, routes):
    eid = server.enquete_ouvrir("Géo", budget={"requetes_par_hote": 1})["id"]
    server.geo_commune(nom="Lille", enquete=eid)
    res = server.geo_commune(nom="Douai", enquete=eid)
    assert res["statut"] == "bloque" and res["limite"] == "requetes_par_hote"
    reste = server.enquete_etat(eid)["reste_a_faire"]
    assert reste == [{**reste[0], "outil": "geo_commune", "parametres": {"nom": "Douai"}}]
    # le reste à faire se rejoue tel quel, une fois le budget relevé
    server.enquete_noter(eid, budget={"requetes_par_hote": 10})
    action = server.enquete_reprendre(eid)["a_faire"][0]
    assert "refus" not in getattr(server, action["outil"])(**action["parametres"], enquete=eid)


def test_planche_compte_une_image(app):
    from test_planche import preparer

    with respx.mock(assert_all_called=False) as planche:
        preparer(planche, 0, 1)
        eid = server.enquete_ouvrir("Planche", budget={"images": 1})["id"]
        res = server.archives_planche(REGISTRE, de=1, a=2, enquete=eid)
        assert "erreur" not in res, res
        assert res["cout_estime_tokens"] > 0  # information, sans limite
        assert server.enquete_etat(eid)["consomme"]["images"] == 1
        avant = len(planche.calls)
        refus = server.archives_planche(REGISTRE, de=1, a=2, enquete=eid)
        assert refus["limite"] == "images" and len(planche.calls) == avant


def test_appel_par_le_protocole_mcp(app, routes):
    """Le paramètre ajouté par l'enveloppe est accepté par la validation du SDK et transmis à la mesure."""
    eid = server.enquete_ouvrir("Protocole")["id"]
    res = asyncio.run(server.mcp.call_tool("geo_commune", {"nom": "Lille", "enquete": eid}))
    assert not res.is_error
    assert sum(server.enquete_etat(eid)["consomme"]["requetes"].values()) == 1
