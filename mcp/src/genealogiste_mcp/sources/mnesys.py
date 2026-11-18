"""Formulaires de recherche Mnesys Expo (éditeur Naoned) : lecture du formulaire public d'un service (#128).

Chaque service expose ``/search/form/<uuid>`` (HTML serveur) puis ``/search/results`` (GET). Les indices des champs
diffèrent d'un site à l'autre (``2-date``, ``4-date``, ``date``) et le vocabulaire des communes aussi
(« NEVERS », « Delle (Territoire de Belfort, France) », « Lamentin (Le) »). Plutôt que de recopier ces détails dans
le référentiel, le formulaire est lu (une requête, en cache) : nom des champs, communes proposées, typologies.
Relevés des 18 novembre 2026 : docs/releves-archives-2026-11-18.md. Aucun nom de personne n'est envoyé.
"""

from __future__ import annotations

import json
import re

from ..normalize.names import strip_accents

TYPES_FONDS = {"RM": "matricules", "SUCC": "successions"}  # type_acte -> clé du formulaire dédié

ARTICLES = ("LE", "LA", "LES", "L")
# qualificatifs d'une commune ancienne ou absorbée : à départager seulement si aucune autre forme
_ANCIENNE = re.compile(r"jusqu|ancienne|absorb|fusionn", re.I)
# typologie (option du formulaire, en minuscules sans accent) -> types d'acte du plugin
_TYPOLOGIE = (
    (re.compile(r"\btables?\b"), "TD"),
    (re.compile(r"publication"), ""),  # publications de mariage : ni M ni filtre
    (re.compile(r"naissance|bapteme"), "N"),
    (re.compile(r"mariage"), "M"),
    (re.compile(r"deces|sepulture"), "D"),
)


class FormulaireError(ValueError):
    """Formulaire Mnesys non reconnu : la recherche ne peut pas être construite."""


def cle(texte: str) -> str:
    """Forme de comparaison d'un nom de commune : sans accents, capitales, tirets et apostrophes en espaces."""
    s = strip_accents(texte or "").upper().replace("-", " ").replace("_", " ").replace("'", " ").replace("’", " ")
    return " ".join(s.split())


def _base(option: str) -> tuple[str, str]:
    """(nom sans qualificatif, qualificatif) ; « Lamentin (Le) » devient « Le Lamentin »."""
    m = re.fullmatch(r"(.*?)\s*\(([^()]*)\)\s*", option)
    if not m:
        return option, ""
    nom, qualif = m[1], m[2]
    if cle(qualif) in ARTICLES:
        return f"{qualif} {nom}", ""
    article = re.fullmatch(r"(.*?)\s*\(([^()]*)\)", nom)  # « Andelys (Les) (Eure, France) » (AD27)
    if article and cle(article[2]) in ARTICLES:
        return f"{article[2]} {article[1]}", qualif
    return nom, qualif


def _sans_bureau(texte: str) -> str:
    """« BUREAU DE DELLE » -> « DELLE » (bureaux de l'enregistrement, AD69 et AD90)."""
    return re.sub(r"^BUREAU (D |DE |DU |DES )?", "", texte)


def _champ(nom: str) -> str:
    """Nom de champ sans son indice (« 2-date » -> « date »)."""
    return re.sub(r"^\d+-", "", nom)


_LIEUX = ("controlledAccessGeographicName", "title", "controlledAccessTitle", "controlledAccessCorporateName")


def lire_formulaire(noeuds) -> dict:
    """Champs utiles d'un formulaire Mnesys (arbre HTML de registres._HTML) : lieu (commune ou, pour les fonds
    militaires et l'enregistrement, bureau ; avec ses options), date exacte, début et fin de période, champs de
    typologie (avec leurs options)."""
    champs: dict[str, list] = {}
    for n in noeuds:
        nom = n.attrs.get("data-name") or n.attrs.get("name") or ""
        if not nom or nom in champs and champs[nom]:
            continue
        options = []
        if "data-options" in n.attrs:
            try:
                options = json.loads(n.attrs["data-options"])
            except ValueError as exc:
                raise FormulaireError(f"Options du champ {nom} illisibles.") from exc
            if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
                raise FormulaireError(f"Options du champ {nom} inattendues.")
        champs.setdefault(nom, options)
    out: dict = {"commune": None, "communes": [], "date": None, "debut": None, "fin": None, "typologies": {}}
    lieux = {}
    for nom, options in champs.items():
        sans = _champ(nom)
        if sans in _LIEUX and options:
            lieux.setdefault(sans, (nom, options))
        elif sans == "date" and out["date"] is None:
            # année proposée en liste (classes des matricules, AD19 et AD58) : paramètre multiple « nom[] »
            out["date"] = nom + "[]" if options else nom
        elif sans in ("date_begin", "period_begin") and out["debut"] is None:
            out["debut"] = nom
        elif sans in ("date_end", "period_end") and out["fin"] is None:
            out["fin"] = nom
        elif sans == "controlledAccessPhysicalCharacteristic" and options:
            out["typologies"][nom] = options
    for sans in _LIEUX:  # la commune d'abord, sinon le bureau (titre ou collectivité)
        if sans in lieux:
            out["commune"], out["communes"] = lieux[sans]
            break
    return out


def typologie(option: str) -> str | None:
    """Type d'acte (N, M, D, TD) d'une option de typologie ; '' pour une option connue sans type ; None sinon."""
    bas = strip_accents(option).lower()
    for motif, code in _TYPOLOGIE:
        if motif.search(bas):
            return code
    return None


def _correspond(option: str, type_acte: str) -> bool:
    bas = strip_accents(option).lower()
    if type_acte == "RM":  # registre matricule, pas son répertoire ni une liste annexe
        return "matricule" in bas and not re.search(r"repertoire|liste|table", bas)
    if type_acte == "SUCC":
        return "succession" in bas and "table" in bas
    return typologie(option) == type_acte


def options_typologie(formulaire: dict, type_acte: str) -> tuple[str | None, list[str]]:
    """(champ, options) du premier champ de typologie qui propose ce type ; (None, []) sinon."""
    for nom, options in formulaire["typologies"].items():
        retenues = [o for o in options if _correspond(o, type_acte)]
        if retenues:
            return nom, retenues
    return None, []


def choisir_commune(options: list[str], commune: str) -> str:
    """Valeur exacte du vocabulaire du site pour une commune. Une valeur identique à une option est reprise telle
    quelle ; sinon comparaison sans accents ni casse, article inversé compris. Plusieurs candidates : la forme
    actuelle l'emporte sur une commune ancienne ; une ambiguïté restante est une erreur qui liste les valeurs."""
    if commune in options:
        return commune
    cible = _sans_bureau(cle(commune))
    candidates = [o for o in options if _sans_bureau(cle(_base(o)[0])) == cible]
    if len(candidates) > 1:
        actuelles = [o for o in candidates if not _ANCIENNE.search(_base(o)[1])]
        sans_qualif = [o for o in actuelles if not _base(o)[1] or "France" in _base(o)[1]]
        candidates = sans_qualif or actuelles or candidates
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        proches = [o for o in options if cible and cible in cle(o)][:10]
        raise ValueError(f"Commune « {commune} » absente du vocabulaire du service"
                         + (f" ; valeurs proches : {proches}" if proches else "")
                         + ". Reprendre une valeur exacte comme commune.")
    raise ValueError(f"Commune « {commune} » ambiguë dans le vocabulaire du service : {candidates[:10]}. "
                     "Reprendre la valeur exacte voulue comme commune.")
