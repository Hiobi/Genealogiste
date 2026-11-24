"""#323 : forme commune des manifestes de réponses enregistrées et règle « aucun analyseur sans réponse réelle ».

Chaque dossier de ``tests/fixtures/contexte/reponses/<service>/`` porte un ``MANIFESTE.json`` de même forme
(docs/contexte-historique.md, « Recette et réponses enregistrées »). Aucun accès réseau."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from test_enregistrer_contexte import rec

from genealogiste_mcp.config import Config
from genealogiste_mcp.contexte import lieux, presse, services
from genealogiste_mcp.contexte.gabarits import GABARITS
from genealogiste_mcp.sources import geo

REPONSES = Path(__file__).parent / "fixtures" / "contexte" / "reponses"
DOSSIERS = sorted(p for p in REPONSES.iterdir() if p.is_dir())

CHAMPS_ENTREE = ("fichier", "url", "methode", "date", "statut", "type", "reduction", "empreinte", "client")
CHAMPS_FACULTATIFS = ("octets_origine", "resultat", "duree_s", "rejouable", "note")
CHAMPS_MANIFESTE = ("service", "objet", "reponses")
CHAMPS_MANIFESTE_FACULTATIFS = ("enregistre_par", "commune_temoin", "non_verifie")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}Z)?")
COURRIEL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CLE = re.compile(r"(?i)\b(?:api[_-]?key|wskey|apikey|access[_-]?token|authorization|bearer)\b")

# Adresses institutionnelles contenues dans des réponses réelles, laissées telles quelles (« sans modifier le
# contenu des réponses enregistrées ») : contact du service ou de l'éditeur, jamais une personne.
COURRIELS_INSTITUTIONNELS = {
    "IGN-GEOPLATEFORME/GetCapabilities.xml": {"geoplateforme@ign.fr"},  # ServiceContact du GetCapabilities
    "isidore/courrieres-mines.json": {"calenda@revues.org", "contact@persee.fr"},  # contacts des revues sources
}
HORS_REFERENTIEL = {"API-GEO": "geo.api.gouv.fr (sources/geo.py)", "COG-INSEE": "insee.fr (sources/geo.py, COG)"}

# Services qu'un outil interroge avec un analyseur sans qu'une réponse 2xx réelle soit enregistrée.
# Exception nommée et motivée : ne pas la masquer ni l'élargir (le test exige qu'elle soit encore nécessaire).
EXCEPTIONS_ANALYSEUR = {
    "GALLICA": ("l'analyseur SRU (sources/gallica.py : parse_sru) et la recherche dans le document (ContentSearch) "
                "précèdent #323 et sont testés sur tests/fixtures/api/gallica_sru.xml et des réponses au format du "
                "parseur, pas sur des réponses enregistrées sur le réseau : le SRU répond 403 Cloudflare "
                "(2026-11-21 et 2026-11-23), ContentSearch n'a jamais été joignable ; seule la page de blocage est "
                "enregistrée. À lever dès qu'une réponse 200 réelle (SRU, ContentSearch) est enregistrée."),
}


def _manifeste(dossier: Path) -> dict:
    return json.loads((dossier / "MANIFESTE.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("dossier", DOSSIERS, ids=lambda d: d.name)
def test_forme_du_manifeste(dossier):
    m = _manifeste(dossier)
    assert set(CHAMPS_MANIFESTE) <= set(m) <= {*CHAMPS_MANIFESTE, *CHAMPS_MANIFESTE_FACULTATIFS}, sorted(m)
    assert m["service"] == dossier.name.upper(), "le champ service est le nom du dossier en majuscules"
    assert isinstance(m["objet"], str) and m["objet"].strip()
    assert isinstance(m["reponses"], list) and m["reponses"]
    declares = []
    for e in m["reponses"]:
        assert set(CHAMPS_ENTREE) <= set(e) <= {*CHAMPS_ENTREE, *CHAMPS_FACULTATIFS}, (sorted(e), e.get("fichier"))
        assert e["methode"] == "GET"
        assert DATE.fullmatch(e["date"]), e["date"]
        assert isinstance(e["statut"], int) and not isinstance(e["statut"], bool) and 100 <= e["statut"] <= 599
        assert isinstance(e["type"], str) and e["type"]
        assert isinstance(e["reduction"], str) and e["reduction"].strip()
        assert isinstance(e["client"], str) and e["client"].strip()
        assert rec.controle_url(e["url"]) == "", e["url"]  # https, ni clé, ni courriel, ni nom de personne
        assert " " not in urlsplit(e["url"]).netloc and "(" not in e["url"], e["url"]
        for cle in ("octets_origine",):
            assert cle not in e or (isinstance(e[cle], int) and e[cle] > 0)
        if "rejouable" in e:
            assert e["rejouable"] is False  # absent = rejouable ; seule la valeur false a un sens
        if e["fichier"] is None:
            assert e["empreinte"] is None and e["reduction"] == "corps non conservé"
            continue
        declares.append(e["fichier"])
        fichier = dossier / e["fichier"]
        assert fichier.is_file(), e["fichier"]
        assert e["empreinte"] == "sha256:" + hashlib.sha256(fichier.read_bytes()).hexdigest(), e["fichier"]
    assert len(declares) == len(set(declares)), "un fichier décrit deux fois"
    presents = {p.name for p in dossier.iterdir()} - {"MANIFESTE.json"}
    assert presents == set(declares), f"fichiers non décrits ou décrits en trop : {presents ^ set(declares)}"


def test_chaque_dossier_est_un_service_connu():
    codes = set(services.codes())
    for d in DOSSIERS:
        assert d.name.upper() in codes or d.name.upper() in HORS_REFERENTIEL, d.name


@pytest.mark.parametrize("dossier", DOSSIERS, ids=lambda d: d.name)
def test_aucune_cle_courriel_ni_nom_de_personne(dossier):
    noms = rec.noms_cas_temoins()
    assert noms, "noms des cas témoins introuvables"
    for fichier in sorted(dossier.iterdir()):
        texte = fichier.read_text(encoding="utf-8")
        cle = f"{dossier.name}/{fichier.name}"
        autorises = COURRIELS_INSTITUTIONNELS.get(cle, set())
        assert set(COURRIEL.findall(texte)) <= autorises, (cle, set(COURRIEL.findall(texte)) - autorises)
        assert not CLE.search(texte), (cle, CLE.search(texte).group(0))
        haut = texte.upper()
        assert not [n for n in noms if n in haut], (cle, [n for n in noms if n in haut])


def test_courriels_institutionnels_encore_presents():
    """Une exception qui ne sert plus est retirée : elle ne doit pas masquer une adresse future."""
    for cle, adresses in COURRIELS_INSTITUTIONNELS.items():
        texte = (REPONSES / cle).read_text(encoding="utf-8")
        assert adresses <= set(COURRIEL.findall(texte)), cle


# --------------------------------------------------------------------- aucun analyseur sans réponse réelle

def services_avec_analyseur() -> dict[str, str]:
    """Service -> outil, dérivé du code : gabarits de contexte_bibliographie, services interrogés par
    lieu_historique, services de presse_recherche interrogés avec un analyseur."""
    out: dict[str, str] = {code: "contexte_bibliographie" for code in GABARITS}
    source_lieux = inspect.getsource(lieux)
    for code in re.findall(r'services\.refus\("([A-Z-]+)"', source_lieux):
        out[code] = "lieu_historique"
    # Services de sources/geo.py (hors référentiel de contexte) : hôtes lus dans le code, nommés par dossier.
    assert "geo.history(" in source_lieux and "geo.commune(" in source_lieux
    assert urlsplit(geo.GEO).hostname == "geo.api.gouv.fr"
    assert urlsplit(Config(data_dir=Path("d"), cache_path=Path("c")).cog_communes_url).hostname == "www.insee.fr"
    out["API-GEO"] = out["COG-INSEE"] = "lieu_historique"
    for code in re.findall(r'code == "([A-Z-]+)"', inspect.getsource(presse.rechercher)):
        out[code] = "presse_recherche"
    return out


def _reponse_2xx_enregistree(code: str) -> bool:
    dossier = next((d for d in DOSSIERS if d.name.upper() == code), None)
    if dossier is None or not (dossier / "MANIFESTE.json").is_file():
        return False
    return any(e["fichier"] and 200 <= e["statut"] < 300 for e in _manifeste(dossier)["reponses"])


def test_liste_derivee_du_code():
    attendu = {"HAL", "ISIDORE", "SUDOC", "BNF-CATALOGUE", "THESES-FR", "CROSSREF", "WIKIDATA", "INSEE-MELODI",
               "IGN-GEOPLATEFORME", "API-GEO", "COG-INSEE", "GALLICA", "EUROPEANA"}
    assert set(services_avec_analyseur()) == attendu, set(services_avec_analyseur()) ^ attendu


def test_aucun_analyseur_sans_reponse_reelle_enregistree():
    manque = {code: outil for code, outil in services_avec_analyseur().items()
              if not _reponse_2xx_enregistree(code) and code not in EXCEPTIONS_ANALYSEUR}
    assert not manque, f"analyseur sans réponse réelle (2xx) enregistrée et sans exception motivée : {manque}"


def test_exceptions_nommees_motivees_et_encore_necessaires():
    liste = services_avec_analyseur()
    for code, motif in EXCEPTIONS_ANALYSEUR.items():
        assert code in liste, f"{code} n'a plus d'analyseur : retirer l'exception"
        assert len(motif) > 80, "motif circonstancié attendu"
        assert not _reponse_2xx_enregistree(code), f"{code} a maintenant une réponse 2xx : retirer l'exception"
