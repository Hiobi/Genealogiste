"""Référentiel des sites tiers de généalogie (referentiels/sites_tiers.json, #181).

Associations et cercles, réseaux de relevés bénévoles, bases thématiques, annuaires, outils de lieux : ce ne sont
pas des archives publiques (voir archives.py). Un relevé est une source dérivée : il donne une piste et oblige à
remonter à l'acte original. Aucun accès réseau ici : le plugin ne fait que proposer des liens à ouvrir dans le
navigateur de l'utilisateur ; un site protégé (captcha, Cloudflare, adhésion) reste un lien, sans contournement.
Format et règles : docs/sites-tiers.md.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit

from .normalize.places import DEPARTEMENTS

PATH = Path(__file__).parent / "referentiels" / "sites_tiers.json"

TYPES = ("releves_benevoles", "annuaire", "cercle_departemental", "base_thematique", "lieux",
         "cimetieres_monuments", "arbre_collaboratif")
ACCES = ("libre", "inscription_gratuite", "adhesion", "points", "mixte", "a_determiner")
NATURES = ("releve_derive", "index", "image", "notice", "outil")
PROTECTIONS = ("aucune", "captcha", "cloudflare", "connexion")
ZONES_HORS_DEPARTEMENT = ("FR", "CA", "INT")  # France entière, Canada, international
CHAMPS_RECHERCHE = ("{nom}", "{prenom}")
CHAMPS = ("code", "nom", "url", "type", "zone", "acces", "nature", "protection", "verifie_le", "origine")

AVERTISSEMENT = ("Site tiers : un relevé ou un index est une source dérivée. Il donne une piste ; remonter à l'acte "
                 "original (registre, minute) avant de conclure.")


@lru_cache(maxsize=1)
def sites() -> tuple[dict, ...]:
    return tuple(json.loads(PATH.read_text(encoding="utf-8"))["sites"])


def _periode_valide(p) -> bool:
    if not isinstance(p, dict) or not p or set(p) - {"de", "a"}:
        return False
    if any(not isinstance(v, int) or isinstance(v, bool) for v in p.values()):
        return False
    return p.get("de", 0) <= p.get("a", 9999)


def validate() -> list[str]:
    """Problèmes de format du référentiel (tests et make verifier-archives)."""
    errs, seen = [], set()
    for s in sites():
        c = s.get("code", "")
        if not c or c in seen:
            errs.append(f"{c!r} : code manquant ou en double")
        seen.add(c)
        for champ in CHAMPS:
            if champ not in s:
                errs.append(f"{c} : champ {champ} manquant")
        if not s.get("nom"):
            errs.append(f"{c} : nom vide")
        url = urlsplit(s.get("url", ""))
        if url.scheme not in ("https", "http") or not url.hostname:
            errs.append(f"{c} : url http(s) attendue")
        if s.get("type") not in TYPES:
            errs.append(f"{c} : type {s.get('type')!r} (valeurs : {', '.join(TYPES)})")
        if s.get("acces") not in ACCES:
            errs.append(f"{c} : acces {s.get('acces')!r} (valeurs : {', '.join(ACCES)})")
        if s.get("nature") not in NATURES:
            errs.append(f"{c} : nature {s.get('nature')!r} (valeurs : {', '.join(NATURES)})")
        if s.get("protection") not in PROTECTIONS:
            errs.append(f"{c} : protection {s.get('protection')!r} (valeurs : {', '.join(PROTECTIONS)})")
        zone = s.get("zone")
        if not isinstance(zone, list) or not zone or any(
                z not in DEPARTEMENTS and z not in ZONES_HORS_DEPARTEMENT for z in zone):
            errs.append(f"{c} : zone = liste de départements ou de {', '.join(ZONES_HORS_DEPARTEMENT)}")
        if "periode" in s and not _periode_valide(s["periode"]):
            errs.append(f"{c} : periode = {{de, a}} en années entières")
        if r := s.get("recherche"):
            ru = urlsplit(r)
            if ru.scheme != "https" or not any(ch in r for ch in CHAMPS_RECHERCHE):
                errs.append(f"{c} : recherche = modèle d'URL https avec {{nom}} ou {{prenom}}")
            if s.get("protection") != "aucune":
                errs.append(f"{c} : pas de modèle de recherche sur un site protégé (lien navigateur seulement)")
        for champ in ("verifie_le", "site_repond_le"):
            if s.get(champ):
                try:
                    date.fromisoformat(s[champ])
                except ValueError:
                    errs.append(f"{c} : {champ} {s[champ]!r} n'est pas une date ISO")
    return errs


def _chevauche(s: dict, annee_min: int | None, annee_max: int | None) -> bool:
    p = s.get("periode")
    if not p or annee_min is None:
        return True
    fin = annee_max if annee_max is not None else annee_min
    return p.get("de", -9999) <= fin and annee_min <= p.get("a", 9999)


def filtrer(departement: str = "", type: str = "", acces: str = "", theme: str = "",
            annee_min: int | None = None, annee_max: int | None = None,
            nationaux: bool = True) -> list[dict]:
    """Sites dont la zone couvre le département (et, si nationaux, ceux de zone FR), filtrés par type, accès,
    thème et chevauchement de période."""
    out = []
    for s in sites():
        zone = s["zone"]
        if departement and departement not in zone and not (nationaux and "FR" in zone):
            continue
        if type and s["type"] != type:
            continue
        if acces and s["acces"] != acces:
            continue
        if theme and theme not in s.get("themes", ()):
            continue
        if not _chevauche(s, annee_min, annee_max):
            continue
        out.append(s)
    return out


def lien(s: dict, nom: str = "", prenom: str = "") -> dict:
    """Entrée prête à ouvrir dans le navigateur : URL de recherche si le site en expose une (et n'est pas
    protégé), sinon la page d'accueil ; jamais de requête faite par le plugin."""
    url = s["url"]
    if s.get("recherche") and s.get("protection") == "aucune" and (nom or prenom):
        url = s["recherche"].replace("{nom}", quote(nom)).replace("{prenom}", quote(prenom))
    out = {"site": s["nom"], "code": s["code"], "url": url, "type": s["type"], "acces": s["acces"],
           "nature": s["nature"]}
    if s.get("protection") not in (None, "aucune"):
        out["protection"] = s["protection"]
    if s.get("notes"):
        out["note"] = s["notes"]
    if s["nature"] in ("releve_derive", "index"):
        out["avertissement"] = "relevé dérivé : remonter à l'acte original"
    return out


def resume(s: dict) -> dict:
    keys = ("code", "nom", "url", "type", "zone", "acces", "nature", "protection", "periode", "themes",
            "verifie_le")
    return {k: s[k] for k in keys if s.get(k) not in (None, "", [])}


# Services interrogés directement par le plugin (outils réseau), pour le catalogue
API = (
    {"code": "MATCHID", "nom": "matchID — décès INSEE depuis 1970", "url": "https://deces.matchid.io/",
     "outils": ["matchid_recherche", "matchid_appariement_csv", "matchid_appariement_statut"]},
    {"code": "WIKITREE", "nom": "WikiTree (API publique)", "url": "https://api.wikitree.com/",
     "outils": ["wikitree_recherche", "wikitree_profil", "wikitree_personne", "wikitree_ascendants",
                "wikitree_descendants"]},
    {"code": "GALLICA", "nom": "Gallica (BnF) — SRU, texte, ALTO, IIIF", "url": "https://gallica.bnf.fr/",
     "outils": ["gallica_recherche", "gallica_recherche_document", "gallica_texte", "gallica_alto", "gallica_iiif"]},
    {"code": "WIKIDATA", "nom": "Wikidata (API et SPARQL)", "url": "https://www.wikidata.org/",
     "outils": ["wikidata_personne", "wikidata_sparql"]},
    {"code": "API-GEO", "nom": "API Géo et Code officiel géographique (INSEE)", "url": "https://geo.api.gouv.fr/",
     "outils": ["geo_commune", "geo_historique", "normaliser_lieu"]},
    {"code": "ARCHIVES", "nom": "Visionneuses d'archives (IIIF, éditeurs d'AD) et résolution ARK",
     "url": "https://n2t.net/", "outils": ["ark_resoudre", "archive_image", "archives_naviguer",
                                           "archives_registres", "archives_planche", "piece_archiver"]},
)
