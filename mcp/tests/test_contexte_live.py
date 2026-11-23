"""Recette de contrat contre les services de contexte historique réels (make test-contexte, #323). Ignorée sans
GENEALOGISTE_TEST_CONTEXTE=1 : jamais exécutée par make test ni par la CI.

Une à deux requêtes par service qui a un analyseur (gabarits de contexte_bibliographie, services de
lieu_historique, Gallica de presse_recherche, OAI-PMH de Persée). On vérifie la FORME attendue par l'analyseur
(les champs qu'il lit), jamais le contenu : un service qui répond autrement qu'un 2xx lisible (protégé, limité,
muet, en panne) rend AVERT (test ignoré avec le motif), pas un échec. Seule une réponse reçue mais illisible par
l'analyseur est un échec : le service a changé, relire l'analyseur et réenregistrer la réponse
(scripts/enregistrer_contexte.py).

Requêtes : lieux et sujets seulement (Courrières, Billy-Montigny code INSEE 62133, « mines », 1906), jamais un nom
de personne. Débit, coupe-circuit anti-robot, plafonds et cache du plugin respectés (réels, pas simulés) ; aucun
contournement : une protection arrête le service."""

from __future__ import annotations

import os
import re

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.config import Config
from genealogiste_mcp.contexte import services
from genealogiste_mcp.contexte.gabarits import GABARITS, Notice, Recherche
from genealogiste_mcp.contexte.protocoles import ReponseInvalide, oai
from genealogiste_mcp.http import SourceError

ACTIVE = os.environ.get("GENEALOGISTE_TEST_CONTEXTE") == "1"
pytestmark = [pytest.mark.contexte_live,
              pytest.mark.skipif(not ACTIVE, reason="GENEALOGISTE_TEST_CONTEXTE=1 non défini (make test-contexte)")]

RECHERCHE = Recherche(lieux=("Courrières",), sujet="mines", limite=3)
# Identifiant OAI de la réponse GetRecord enregistrée (tests/fixtures/contexte/reponses/persee/MANIFESTE.json).
PERSEE_ID = "oai:persee:article/rnord_0035-2624_1982_num_64_253_3879"
DISPONIBILITE = re.compile(r"HTTP \d{3}|accès refusé|blocage|protection|tentatives|indisponible|Timeout|timed? out|"
                           r"échec|mémorisé|plafond|hors-ligne|coupe-circuit|exclu|ralenti|pas de réponse", re.I)


@pytest.fixture(autouse=True)
def dns_fictif():
    """Annule la fixture DNS simulée de conftest : la politique réseau résout réellement les hôtes."""
    yield


@pytest.fixture(scope="module")
def app_reelle(tmp_path_factory):
    base = tmp_path_factory.mktemp("recette_contexte")
    config = Config(data_dir=base / "donnees", cache_path=base / "cache.sqlite", http_timeout=60)
    a = server.App(config)
    a.http.max_retries = 2
    server.set_app(a)
    yield a
    server.set_app(None)


def avert(motif: str):
    pytest.skip(f"AVERT : {motif}")


def _indisponible(exc: Exception) -> bool:
    """Service protégé, limité, muet ou en panne (à ne pas confondre avec une réponse illisible)."""
    if isinstance(exc, SourceError):
        return (exc.bloque_antirobot or exc.status in (401, 403, 429) or (exc.status or 0) >= 500
                or exc.status is None or bool(DISPONIBILITE.search(str(exc))))
    return False


# ---------------------------------------------------------------------------- contexte_bibliographie

@pytest.mark.parametrize("code", list(GABARITS))
def test_forme_bibliographique(code, app_reelle):
    gab, entree = GABARITS[code], services.par_code(code)
    if refus := services.refus(code, app_reelle.config):
        avert(refus["erreur"])
    params = gab.parametres(RECHERCHE, app_reelle.config)
    try:
        contenu, _ = app_reelle.http.get(entree["url_api"], params=params, parse=gab.parse, ttl=3600,
                                         source=f"contexte:{code}")
    except SourceError as exc:
        if _indisponible(exc):
            avert(f"{code} : {str(exc)[:200]}")
        raise
    try:
        total, notices = gab.analyser(contenu)
    except ReponseInvalide as exc:
        pytest.fail(f"{code} : réponse reçue mais illisible par l'analyseur {gab.protocole} ({exc}) : le service a "
                    "changé, relire l'analyseur et réenregistrer la réponse (scripts/enregistrer_contexte.py)")
    assert total is None or isinstance(total, int), total
    assert all(isinstance(n, Notice) for n in notices)
    if not notices:
        avert(f"{code} : réponse sans notice (total annoncé : {total}), forme des notices non vérifiable")
    assert any(n.champs.get("titre") or n.titre_brut for n in notices), \
        f"{code} : aucune notice dont l'analyseur ait pu lire un titre : champs attendus absents"


def test_forme_oai_persee(app_reelle):
    if refus := services.refus("PERSEE", app_reelle.config):
        avert(refus["erreur"])
    try:
        texte, _ = app_reelle.http.get(services.par_code("PERSEE")["url_api"], ttl=3600, parse="text", source="contexte:PERSEE",
                                       params={"verb": "GetRecord", "identifier": PERSEE_ID,
                                               "metadataPrefix": "oai_dc"})
    except SourceError as exc:
        if _indisponible(exc):
            avert(f"PERSEE : {str(exc)[:200]}")
        raise
    try:
        notices = oai.notices(texte)
    except ReponseInvalide as exc:
        pytest.fail(f"PERSEE : réponse OAI-PMH illisible ({exc}) : le service a changé")
    if not notices:
        avert("PERSEE : notice supprimée ou absente, forme non vérifiable")
    assert notices[0].identifiant and notices[0].valeurs("title"), "champs oai_dc attendus (identifier, title) absents"


# --------------------------------------------------------------------------------------- lieu_historique

@pytest.fixture(scope="module")
def lieu(app_reelle):
    """Une seule exécution de l'outil : COG, API Géo, Wikidata, Melodi, Géoplateforme (une à deux requêtes chacun,
    caches du plugin)."""
    res = server.lieu_historique("62133", "1906")
    assert "erreur" not in res or res.get("requetes"), res
    return res


# clé de ``requetes`` -> (service, un résultat « negatif » est-il un échec de forme ?)
LIEU = {"cog": ("COG-INSEE", True), "geo": ("API-GEO", True), "wikidata": ("WIKIDATA", False),
        "melodi": ("INSEE-MELODI", True), "geoplateforme": ("IGN-GEOPLATEFORME", True)}


@pytest.mark.parametrize("cle", list(LIEU))
def test_forme_lieu_historique(cle, lieu):
    service, negatif_est_echec = LIEU[cle]
    if "erreur" in lieu and not lieu.get("requetes"):  # COG indisponible : rien d'autre n'a été demandé
        avert(f"{service} : {str(lieu['erreur'])[:200]}")
    etat = lieu["requetes"].get(cle, "absent")
    if etat == "positif":
        return
    if etat.startswith(("erreur", "non interrogé")):
        if DISPONIBILITE.search(etat) or etat.startswith("non interrogé"):
            avert(f"{service} : {etat[:200]}")
        pytest.fail(f"{service} : réponse reçue mais illisible ({etat[:200]})")
    if etat == "negatif" and not negatif_est_echec:
        avert(f"{service} : aucune donnée pour la commune témoin, forme des données non vérifiée")
    pytest.fail(f"{service} : état {etat!r} pour la commune témoin 62133 (lecture de la réponse impossible)")


# ---------------------------------------------------------------------------------- presse_recherche

def test_forme_gallica_presse(app_reelle):
    res = server.presse_recherche("grève", lieu="Courrières", periode="1906", services="GALLICA", nombre=3)
    etat = next(e for e in res["services"] if e["service"] == "GALLICA")
    if etat["statut"] == "interroge":
        assert isinstance(etat["total"], int) and etat["nb_resultats"] <= 3
        return
    motif = etat.get("motif", "")
    if (etat["statut"] in ("bloque_antirobot", "refuse", "lien_seulement") or etat.get("coupe_circuit")
            or etat.get("echec_memorise") or DISPONIBILITE.search(motif)):
        avert(f"GALLICA : {etat['statut']} {motif[:200]}")
    pytest.fail(f"GALLICA : réponse reçue mais illisible par parse_sru ({motif[:200]})")
