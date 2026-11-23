"""Pays d'un lieu (#283) : une seule résolution, réutilisée par toutes les pistes et requêtes.

``pays_du_lieu(lieu)`` renvoie ``{code, nom, provenance, france, detail}`` :

- ``code`` : ISO 3166-1 alpha-2 (``"FR"``, ``"BE"``, ``"US"``…) ou ``""`` si inconnu ou hors de la table ;
- ``nom`` : nom français du pays (ou le libellé de la hiérarchie si le pays est hors de la table), ``""`` si inconnu ;
- ``provenance`` : ``hierarchie`` (niveau pays de Gramps, ou ``FORM`` du ``PLAC`` GEDCOM), ``code_insee``
  (code commune français, ou code pays 99xxx du COG), ``libelle`` (nom de pays en dernier segment, sinon
  département français reconnu), ``inconnu`` ;
- ``france`` : ``True``, ``False`` ou ``None`` (inconnu : jamais présumé français) ;
- ``detail`` : ce qui a décidé, en clair.

Ordre : hiérarchie → code INSEE → libellé → inconnu. Le nom de la commune (premier segment) ne décide jamais
seul : « Charleroi » reste inconnu, « Charleroi, Nord » est en France, « Charleroi, Hainaut, Belgique » en
Belgique. Les DOM sont la France.
"""

from __future__ import annotations

import re
from typing import Any

from .names import basic
from .places import DEPARTEMENTS, normalize_place

# Table fermée : code ISO -> (nom français, formes reconnues : français, anglais, langue locale, formes historiques)
PAYS: dict[str, tuple[str, tuple[str, ...]]] = {
    "FR": ("France", ("france", "republique francaise", "royaume de france", "empire francais", "frankreich",
                      "francia")),
    "BE": ("Belgique", ("belgique", "belgium", "belgie", "belgien", "royaume de belgique")),
    "CH": ("Suisse", ("suisse", "switzerland", "schweiz", "svizzera", "confederation suisse",
                      "confederation helvetique")),
    "DE": ("Allemagne", ("allemagne", "germany", "deutschland", "empire allemand", "deutsches reich",
                         "reich allemand", "prusse", "prussia", "preussen")),
    "LU": ("Luxembourg", ("luxembourg", "luxemburg", "grand duche de luxembourg")),
    "NL": ("Pays-Bas", ("pays bas", "netherlands", "nederland", "the netherlands", "hollande", "holland")),
    "IT": ("Italie", ("italie", "italy", "italia", "royaume d italie")),
    "ES": ("Espagne", ("espagne", "spain", "espana")),
    "PT": ("Portugal", ("portugal",)),
    "GB": ("Royaume-Uni", ("royaume uni", "united kingdom", "uk", "grande bretagne", "great britain",
                           "angleterre", "england", "ecosse", "scotland", "pays de galles", "wales")),
    "IE": ("Irlande", ("irlande", "ireland", "eire")),
    "US": ("États-Unis", ("etats unis", "etats unis d amerique", "usa", "u s a", "us", "united states",
                          "united states of america")),
    "CA": ("Canada", ("canada",)),
    "DZ": ("Algérie", ("algerie", "algeria")),
    "MA": ("Maroc", ("maroc", "morocco")),
    "TN": ("Tunisie", ("tunisie", "tunisia")),
    "PL": ("Pologne", ("pologne", "poland", "polska")),
    "AT": ("Autriche", ("autriche", "austria", "osterreich", "oesterreich")),
    "HU": ("Hongrie", ("hongrie", "hungary")),
    "RO": ("Roumanie", ("roumanie", "romania")),
    "RU": ("Russie", ("russie", "russia", "empire russe")),
    "GR": ("Grèce", ("grece", "greece")),
    "TR": ("Turquie", ("turquie", "turkey", "empire ottoman")),
    "DK": ("Danemark", ("danemark", "denmark")),
    "SE": ("Suède", ("suede", "sweden")),
    "NO": ("Norvège", ("norvege", "norway")),
    "FI": ("Finlande", ("finlande", "finland")),
    "MC": ("Monaco", ("monaco",)),
    "AD": ("Andorre", ("andorre", "andorra")),
    "EG": ("Égypte", ("egypte", "egypt")),
    "LB": ("Liban", ("liban", "lebanon")),
    "SN": ("Sénégal", ("senegal",)),
    "VN": ("Viêt Nam", ("viet nam", "vietnam")),
    "AR": ("Argentine", ("argentine", "argentina")),
    "BR": ("Brésil", ("bresil", "brazil", "brasil")),
    "MX": ("Mexique", ("mexique", "mexico")),
    "CL": ("Chili", ("chili", "chile")),
    "UY": ("Uruguay", ("uruguay",)),
    "AU": ("Australie", ("australie", "australia")),
    "NZ": ("Nouvelle-Zélande", ("nouvelle zelande", "new zealand")),
}

# Codes pays du COG (code INSEE 99xxx, lieu de naissance à l'étranger) -> ISO
COG_PAYS = {
    "99100": "FR", "99109": "DE", "99110": "AT", "99122": "PL", "99123": "RU", "99127": "IT", "99131": "BE",
    "99132": "GB", "99134": "ES", "99135": "NL", "99136": "IE", "99137": "LU", "99138": "MC", "99139": "PT",
    "99140": "CH", "99350": "MA", "99351": "TN", "99352": "DZ", "99401": "CA", "99404": "US", "99405": "MX",
    "99415": "AR", "99416": "BR",
}

# Départements d'outre-mer : formes courantes en plus des noms de DEPARTEMENTS
DOM = {"reunion": "974", "ile de la reunion": "974", "guyane francaise": "973"}

_CODE_INSEE = re.compile(r"^(?:\d{5}|2[AB]\d{3})$", re.I)
_FORME_PAYS = {"country", "pays", "nation", "land", "staat"}


def _cle(s: str) -> str:
    return re.sub(r"\s+", " ", basic(s).replace("-", " ").replace("'", " ")).strip()


_PAR_NOM = {_cle(forme): code for code, (_, formes) in PAYS.items() for forme in formes}
_PAR_NOM.update({_cle(nom): code for code, (nom, _) in PAYS.items()})


def pays_par_nom(nom: str) -> str:
    """Code ISO d'un nom de pays de la table fermée (français, anglais, local, historique) ; ``""`` sinon."""
    return _PAR_NOM.get(_cle(nom or ""), "")


def _res(code: str, nom: str, provenance: str, detail: str, france: bool | None = None) -> dict:
    if france is None and provenance != "inconnu":
        france = code == "FR"
    return {"code": code, "nom": nom or (PAYS[code][0] if code in PAYS else ""), "provenance": provenance,
            "france": france, "detail": detail}


def _champs(lieu: Any) -> tuple[str, str, str, str]:
    """(libellé, code INSEE, pays de la hiérarchie Gramps, FORM GEDCOM) d'un texte, dict ou Place."""
    if lieu is None:
        return "", "", "", ""
    if isinstance(lieu, str):
        return lieu, "", "", ""
    get = lieu.get if isinstance(lieu, dict) else (lambda k, d="": getattr(lieu, k, d))
    forme = get("forme", "") or ""
    for n in get("extra", None) or []:
        if isinstance(n, dict) and n.get("tag") == "FORM" and not forme:
            forme = n.get("value", "")
    return get("nom", "") or "", (get("code_insee", "") or "").strip(), get("pays", "") or "", forme


def _hierarchie(nom: str, pays: str, forme: str) -> dict | None:
    if pays.strip():
        code = pays_par_nom(pays)
        return _res(code, PAYS[code][0] if code else pays.strip(), "hierarchie",
                    f"niveau pays de la hiérarchie du lieu : {pays.strip()}", code == "FR")
    if forme:
        niveaux = [_cle(x) for x in forme.split(",")]
        segments = [x.strip() for x in nom.split(",")]
        for i, niveau in enumerate(niveaux):
            if niveau in _FORME_PAYS and i < len(segments) and segments[i]:
                code = pays_par_nom(segments[i])
                return _res(code, PAYS[code][0] if code else segments[i], "hierarchie",
                            f"niveau « {forme.split(',')[i].strip()} » du FORM du lieu : {segments[i]}", code == "FR")
    return None


def _code_insee(code_insee: str) -> dict | None:
    if not _CODE_INSEE.match(code_insee):
        return None
    if code_insee.startswith("99"):
        code = COG_PAYS.get(code_insee, "")
        return _res(code, "", "code_insee", f"code pays du COG {code_insee}"
                    + ("" if code else " (pays hors de la table)"), code == "FR")
    return _res("FR", "", "code_insee", f"code commune INSEE {code_insee.upper()}", True)


def _libelle(nom: str) -> dict | None:
    segments = [x.strip() for x in nom.split(",") if x.strip()]
    if not segments:
        return None
    dernier = segments[-1]
    code = pays_par_nom(dernier)
    if code:
        return _res(code, "", "libelle", f"nom de pays en fin de libellé : {dernier}")
    for s in segments[1:]:
        if (dom := DOM.get(_cle(s))) is not None:
            return _res("FR", "", "libelle", f"département d'outre-mer : {DEPARTEMENTS[dom]} ({dom})", True)
    dep = normalize_place(nom).get("departement_code")
    if dep:
        quoi = next((s for s in segments[1:] if normalize_place(f"x, {s}").get("departement_code") == dep), "")
        dom = " d'outre-mer" if dep.startswith("97") else ""
        return _res("FR", "", "libelle", f"département français{dom} reconnu : "
                    + (f"{quoi} ({dep})" if quoi else f"{DEPARTEMENTS.get(dep, dep)} ({dep})"), True)
    return None


def pays_du_lieu(lieu: Any) -> dict:
    """Pays d'un lieu (texte, dict ``{nom, code_insee, pays, forme}`` ou ``Place``) : voir le module."""
    nom, code_insee, pays, forme = _champs(lieu)
    for essai in (lambda: _hierarchie(nom, pays, forme), lambda: _code_insee(code_insee), lambda: _libelle(nom)):
        if (r := essai()) is not None:
            return r
    return _res("", "", "inconnu", "pays non déterminé : préciser le pays ou le département du lieu" if nom.strip()
                else "aucun lieu", None)


def pays_resume(p: dict) -> dict:
    """Forme courte jointe aux pistes : ``{code, nom, provenance}``."""
    return {k: p[k] for k in ("code", "nom", "provenance")}
