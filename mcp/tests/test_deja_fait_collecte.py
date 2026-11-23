"""#211 : « déjà fait le … » et notation dans l'état d'enquête pour tous les outils de collecte budgétés.

L'identité d'une demande est déclarée par outil dans le catalogue (outils.IDENTITE_REQUETE) ; les trois outils à
identité dédiée (enquetes.OUTILS_SUIVIS) gardent leur comportement (tests/test_enquetes.py). Noms fictifs."""

from __future__ import annotations

import inspect
import json

import pytest
import respx
from test_budget_collecte import EXEMPLES
from test_budget_enquete import mock_iiif
from test_enquetes import MANIFEST, REGISTRE, mock_ad59
from test_planche import preparer

from genealogiste_mcp import outils, server
from genealogiste_mcp.enquetes import OUTILS_SUIVIS, cle_requete

COUVERTS = sorted(outils.IDENTITE_REQUETE)
SRU = "https://gallica.bnf.fr/SRU"
REGISTRES_AD59 = "https://archivesdepartementales.lenord.fr/search/results"

# Même outil, un paramètre d'identité différent : pas « la même demande ».
VARIANTES: dict[str, dict] = {
    "matchid_recherche": {**EXEMPLES["matchid_recherche"], "page": 2},  # pagination
    "wikitree_recherche": {"nom": "Dupont", "prenom": "Jeanne"},
    "wikitree_profil": {"cle": "Dupont-2"},
    "wikitree_personne": {"cle": "Dupont-2"},
    "wikitree_ascendants": {"cle": "Dupont-1", "profondeur": 5},
    "wikitree_descendants": {"cle": "Dupont-1", "profondeur": 4},
    "gallica_recherche": {"texte": "Jean Dupont", "depart": 21},  # pagination
    "gallica_recherche_document": {"ark": "ark:/12148/bpt6k123456", "texte": "Durand"},
    "gallica_texte": {"ark": "ark:/12148/bpt6k123456", "page": 2},
    "gallica_alto": {"ark": "ark:/12148/bpt6k123456", "page": 2},
    "ark_resoudre": {"ark": "ark:/12148/bpt6k654321"},
    "piece_archiver": {"source": MANIFEST, "page": 2},
    "wikidata_personne": {"nom": "Dupont", "prenom": "Paul"},
    "wikidata_sparql": {"requete": "SELECT ?x WHERE { ?x ?y ?z } LIMIT 2"},
    "geo_commune": {"nom": "Douai"},
    "geo_historique": {"code_insee": "59178"},
    "lieu_historique": {"lieu": "59350", "date": "1976"},
    "archives_registres": {"service": "AD59", "commune": "Lille", "annee": 1851},
    "archives_planche": {"source": REGISTRE, "de": 1, "a": 2, "bandeau": "pct:0,0,100,35"},
}
# Même demande écrite autrement (casse, accents, espaces, défaut explicite) : « la même demande ».
EQUIVALENTS: dict[str, dict] = {
    "matchid_recherche": {"nom": " DUPONT ", "prenom": "jean", "page": 1},
    "wikidata_personne": {"nom": "dupont", "prenom": "JEAN", "limite": 20},
    "geo_commune": {"nom": "LILLE", "limite": 10},
    "gallica_recherche": {"texte": "jean   DUPONT", "exact": True},
    "archives_registres": {"service": "AD59", "commune": "lille", "annee": 1850, "page": 1},
}


@pytest.fixture
def routes(fixtures):
    with respx.mock(assert_all_called=False) as router:
        preparer(router, 0, 1)
        mock_ad59(router)
        mock_iiif(router)
        router.get(SRU).respond(200, text=(fixtures / "api" / "gallica_sru.xml").read_text())
        router.get(REGISTRES_AD59).respond(200, text=(fixtures / "ad59-recherche-positive.html").read_text())
        router.get(url__regex=r"https://gallica\.bnf\.fr/services/ContentSearch").respond(
            200, text="<results></results>")
        router.get(url__regex=r"https://gallica\.bnf\.fr/RequestDigitalElement").respond(
            200, text="<alto><Layout><Page><TextLine HPOS='1' VPOS='2'><String CONTENT='Dupont' WC='0.9'/>"
                      "</TextLine></Page></Layout></alto>")
        router.route().respond(200, json={})  # toute autre requête : réponse vide
        yield router


def _requetes(eid: str) -> list[dict]:
    return server.enquete_etat(eid)["requetes"]


# ---------------------------------------------------------------- invariants du catalogue

def test_identite_couvre_exactement_les_outils_budgetes():
    """Tout outil qui prend enquete (budget) a une identité : déclarée ici, ou dédiée (OUTILS_SUIVIS)."""
    assert set(OUTILS_SUIVIS) <= outils.BUDGET_ENQUETE
    assert set(outils.IDENTITE_REQUETE) == outils.BUDGET_ENQUETE - set(OUTILS_SUIVIS)
    assert set(VARIANTES) == set(outils.IDENTITE_REQUETE)
    assert "matchid_appariement_statut" not in outils.IDENTITE_REQUETE  # état d'un traitement en cours


@pytest.mark.parametrize("nom", COUVERTS)
def test_identite_conforme_a_la_signature(nom):
    """Chaque paramètre est dans l'identité ou exclu avec un motif ; défauts identiques à la signature."""
    signature = inspect.signature(inspect.unwrap(getattr(server, nom))).parameters
    identite = outils.IDENTITE_REQUETE[nom]
    exclus = {**outils.HORS_IDENTITE, **outils.HORS_IDENTITE_OUTIL.get(nom, {})}
    assert set(identite) <= set(signature), nom
    assert not set(identite) & set(exclus), nom
    assert set(signature) - {"enquete"} <= set(identite) | set(exclus), nom
    assert all(motif.strip() for motif in exclus.values())
    for param, (nature, defaut) in identite.items():
        assert nature in (outils.TEXTE, outils.EXACT, outils.ENTIER, outils.BOOLEEN), (nom, param)
        if signature[param].default is not inspect.Parameter.empty:
            assert defaut == signature[param].default, (nom, param)


def test_cle_normalisee_et_defauts():
    a = cle_requete("geo_commune", {"nom": "Saint-Étienne  "})
    assert a == cle_requete("geo_commune", {"nom": "saint-etienne", "limite": 10, "code_insee": ""})
    assert a != cle_requete("geo_commune", {"nom": "saint-etienne", "limite": 5})
    assert cle_requete("wikitree_profil", {"cle": "Dupont-1"}) != cle_requete("wikitree_profil", {"cle": "dupont-1"})
    assert cle_requete("archives_planche", {"source": REGISTRE, "de": 1}) == \
        cle_requete("archives_planche", {"source": REGISTRE, "de": "1", "a": 0, "gris": True})
    # personne (id local) et métadonnées de nommage ne changent pas la demande
    assert cle_requete("matchid_recherche", {"nom": "Dupont", "personne": "I1"}) == \
        cle_requete("matchid_recherche", {"nom": "Dupont"})
    assert cle_requete("piece_archiver", {"source": MANIFEST, "page": 1, "nom_fichier": "x"}) == \
        cle_requete("piece_archiver", {"source": MANIFEST, "page": 1})


# ---------------------------------------------------------------- signal et notation, par outil

@pytest.mark.parametrize("nom", COUVERTS)
def test_deja_fait_par_outil(app, routes, nom):
    outil = getattr(server, nom)
    eid = server.enquete_ouvrir(f"Déjà fait {nom}")["id"]
    premier = outil(**EXEMPLES[nom], enquete=eid)
    assert "erreur" not in premier and "refus" not in premier, (nom, premier)
    assert "deja_fait" not in premier and premier["enquete"] == eid, nom
    notee = [r for r in _requetes(eid) if r["outil"] == nom]
    assert len(notee) == 1 and notee[0]["resultat"] in ("positif", "negatif"), nom

    meme = outil(**EXEMPLES[nom])  # sans enquete : signalé, jamais bloqué ni modifié (deja_fait ajouté)
    assert meme["deja_fait"][0]["enquete"] == eid, nom
    assert meme["deja_fait"][0]["message"].startswith("Déjà fait le "), nom
    if nom != "piece_archiver":  # second archivage : réponse propre (pièce déjà présente)
        assert set(meme) - {"deja_fait"} == set(premier) - {"enquete", "budget"}, nom

    autre = outil(**VARIANTES[nom])
    assert "erreur" not in autre, (nom, autre)
    assert "deja_fait" not in autre, nom  # un paramètre d'identité différent : autre demande
    assert len(_requetes(eid)) == 1, nom  # sans enquete : rien noté


@pytest.mark.parametrize("nom", sorted(EQUIVALENTS))
def test_meme_demande_ecrite_autrement(app, routes, nom):
    eid = server.enquete_ouvrir(f"Équivalent {nom}")["id"]
    getattr(server, nom)(**EXEMPLES[nom], enquete=eid)
    assert getattr(server, nom)(**EQUIVALENTS[nom])["deja_fait"][0]["enquete"] == eid


def test_demande_refaite_une_seule_entree(app, routes):
    eid = server.enquete_ouvrir("Refaite")["id"]
    server.geo_commune(nom="Lille", enquete=eid)
    again = server.geo_commune(nom="lille", enquete=eid)
    assert again["deja_fait"][0]["enquete"] == eid and again["enquete"] == eid
    assert [r["outil"] for r in _requetes(eid)] == ["geo_commune"]


def test_resultat_negatif_reference_le_journal(app, routes):
    eid = server.enquete_ouvrir("Négatif")["id"]
    res = server.geo_historique(code_insee="59350", enquete=eid)
    assert res["resultats"] == []
    (r,) = _requetes(eid)
    assert r["resultat"] == "negatif" and r["journal"] == [res["journal"]]
    assert server.enquete_etat(eid)["coherence_journal"] == "ok"


def test_enquete_inconnue_avertit_sans_bloquer(app, routes):
    res = server.geo_commune(nom="Lille", enquete="inexistante")
    assert "erreur" not in res and "enquete_avertissement" in res


# ---------------------------------------------------------------- vivants, erreurs, refus

def test_refus_vivant_ni_signale_ni_note(app_famille, routes):
    eid = server.enquete_ouvrir("Vivant")["id"]
    # même demande notée à la main (paramètres d'une personne vivante) : le refus « vivant » passe avant tout
    server.enquete_noter(eid, requete={"outil": "wikidata_personne", "parametres": {"nom": "Martin",
                                       "prenom": "Lucas"}, "resultat": "positif"})
    avant = len(_requetes(eid))
    res = server.wikidata_personne(nom="Martin", prenom="Lucas", enquete=eid)
    assert "refus" in res and "deja_fait" not in res and "enquete" not in res
    assert len(_requetes(eid)) == avant
    assert not routes.calls


def test_erreur_non_notee(app):
    with respx.mock(assert_all_called=False) as router:
        router.route().respond(500)
        eid = server.enquete_ouvrir("Erreur")["id"]
        res = server.wikitree_profil(cle="Dupont-1", enquete=eid)
    assert "erreur" in res and "deja_fait" not in res
    assert _requetes(eid) == []


# ---------------------------------------------------------------- reprise

def test_refus_budget_refait_sort_du_reste_a_faire(app, routes):
    eid = server.enquete_ouvrir("Reprise", budget={"requetes_par_hote": 1})["id"]
    server.geo_commune(nom="Lille", enquete=eid)
    assert server.geo_commune(nom="Douai", enquete=eid)["statut"] == "bloque"
    server.enquete_noter(eid, budget={"requetes_par_hote": 10})
    action = server.enquete_reprendre(eid)["a_faire"][0]
    assert action["type"] == "budget" and action["outil"] == "geo_commune"
    res = getattr(server, action["outil"])(**action["parametres"], enquete=eid)
    assert "refus" not in res and res["enquete"] == eid
    reprise = server.enquete_reprendre(eid)
    assert server.enquete_etat(eid)["reste_a_faire"] == []
    assert not [x for x in reprise["a_faire"] if x["type"] == "budget"]
    assert {(d["outil"], d["parametres"].get("nom")) for d in reprise["deja_fait"]} == \
        {("geo_commune", "Lille"), ("geo_commune", "Douai")}


def test_refus_consigne_avec_une_ancienne_cle_sort_du_reste_a_faire(app, routes):
    """Refus consigné avant l'identité déclarée (clé générique de tous les paramètres reçus) : la clé est
    recalculée depuis ses paramètres."""
    eid = server.enquete_ouvrir("Ancienne clé")["id"]
    chemin = app.config.data_dir / "enquetes" / f"{eid}.json"
    e = json.loads(chemin.read_text())
    e["reste_a_faire"] = [{"outil": "wikitree_profil", "parametres": {"cle": "Dupont-1"},
                           "cle": {"cle": "dupont-1"}, "date": "2026-11-01T00:00:00+00:00",
                           "limite": "requetes_par_hote"}]
    chemin.write_text(json.dumps(e))
    server.wikitree_profil(cle="Dupont-1", enquete=eid)
    assert server.enquete_etat(eid)["reste_a_faire"] == []


def test_piste_dont_la_source_est_faite_n_est_plus_a_faire(app, routes):
    eid = server.enquete_ouvrir("Piste")["id"]
    server.enquete_noter(eid, piste={"question": "Commune ?", "sources": [
        {"libelle": "API Géo", "outil": "geo_commune", "parametres": {"nom": "Lille", "limite": 10}}]})
    assert any(x.get("outil") == "geo_commune" for x in server.enquete_reprendre(eid)["a_faire"])
    server.geo_commune(nom="LILLE", enquete=eid)
    assert not any(x.get("outil") == "geo_commune" for x in server.enquete_reprendre(eid)["a_faire"])
