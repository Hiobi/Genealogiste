"""Classeur 3 E des AD59 : état récapitulatif des registres d'état civil et de leur mise en ligne (#374).

Le référentiel ``referentiels/ad59_3e.json`` est produit par ``scripts/generer_couverture_3e_ad59.py`` à partir du
PDF public du service (nom millésimé, relevé daté, empreinte SHA-256). Lecture locale seulement : aucun réseau,
aucune personne. Un volume absent du classeur est « inconnu du classeur », jamais « inexistant ».
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .normalize.names import strip_accents

PATH = Path(__file__).parent / "referentiels" / "ad59_3e.json"
SOURCE = "https://archivesdepartementales.lenord.fr/document/classeur-3e-janvier-2026"
SEUIL_REJETS = 0.005  # part de lignes inexploitables au-delà de laquelle le référentiel est refusé
SEUIL_BORNES = 0.01   # part de lignes gardées avec une borne de date illisible
INCONNU = "inconnu_du_classeur"
LIMITE = ("État récapitulatif publié par les AD59, lu tel quel à la date du relevé : il peut être incomplet ou "
          "dépassé. Un volume connu ne prouve pas la présence d'un acte ; un volume inconnu du classeur ne prouve "
          "pas que le registre n'existe pas.")
_ARTICLES = {"LE", "LA", "LES", "L"}
_ACTES = {"N": "NB", "M": "M", "D": "DS"}  # baptêmes et sépultures des volumes anciens du classeur
_HORS_ACTES = {"TD", "TA", "T", "PM", "PUB", "DIV"}


class ClasseurError(ValueError):
    """Le PDF ne permet pas de produire un référentiel fiable."""


# ---------------------------------------------------------------------------- analyse (génération)

def _annee(texte: str) -> int | None:
    """Année d'une borne : AAAA, AAAA-MM, AAAA-MM-JJ, JJ-MM-AAAA ou JJ/MM/AAAA ; sinon None, sans rien déduire."""
    m = re.fullmatch(r"(\d{4})(?:-\d{2}){0,2}", texte) or re.fullmatch(r"\d{2}[-/]\d{2}[-/](\d{4})", texte)
    return int(m[1]) if m and 1500 <= int(m[1]) <= 2100 else None


def cle_commune(libelle: str) -> str:
    """Clé du référentiel : libellé du classeur sans accents, en capitales, espaces réduits."""
    return " ".join(strip_accents(libelle or "").upper().split())


def analyser_ligne(cellules: list) -> tuple[str, dict, bool] | None:
    """Une ligne du tableau (commune, cote, types, dates, statut, année prévue) -> (commune, volume, bornes
    complètes). None pour une ligne vide ou d'en-tête ; ClasseurError (motif) pour une ligne inexploitable.
    Une cellule coupée sur deux lignes est recollée ; une borne illisible reste None et le texte lu est gardé."""
    c = [" ".join(str(x or "").split()) for x in cellules]
    if not any(c) or c[0].upper() == "COMMUNE":
        return None
    if len(c) < 5:
        raise ClasseurError(f"{len(c)} colonnes au lieu de 5 ou 6")
    commune, cote, types, dates = c[:4]
    if not commune or not cote or not types:
        raise ClasseurError("commune, cote ou types d'actes absents")
    statut = " ".join(x for x in c[4:] if x)
    prevue = re.fullmatch(r">\s*(\d{4})", statut)
    if statut != "Mis en ligne" and not (prevue and 2000 <= int(prevue[1]) <= 2200):
        raise ClasseurError(f"statut de mise en ligne non reconnu : « {statut[:40]} »")
    bornes = [b.strip(" /") for b in re.split(r"\s+/\s*|\s*/\s+", dates, maxsplit=1)] if dates else []
    debut = _annee(bornes[0]) if bornes else None
    fin = _annee(bornes[1]) if len(bornes) == 2 else None
    if debut and fin and fin < debut:
        fin = None
    volume = {"cote": cote, "types": types, "debut": debut, "fin": fin, "en_ligne": prevue is None,
              "mise_en_ligne_prevue": int(prevue[1]) if prevue else None}
    if not re.fullmatch(r"\d{4} / \d{4}", dates) or debut is None or fin is None:
        volume["dates"] = dates  # texte du classeur : mois, jours ou borne illisible
    return cle_commune(commune), volume, debut is not None and fin is not None


def analyser(lignes: list, source: str = SOURCE, sha256: str = "", releve_le: str = "",
             seuil_rejets: float = SEUIL_REJETS, seuil_bornes: float = SEUIL_BORNES) -> dict:
    """Lignes du tableau -> référentiel. Refuse (ClasseurError) un tableau vide ou dont trop de lignes sont
    inexploitables, plutôt que de produire un référentiel silencieusement faux."""
    communes: dict[str, list] = {}
    rejets, total, doublons, incompletes = [], 0, 0, 0
    for numero, cellules in enumerate(lignes, 1):
        try:
            lue = analyser_ligne(cellules)
        except ClasseurError as exc:
            total += 1
            rejets.append({"ligne": numero, "motif": str(exc)})
            continue
        if lue is None:
            continue
        total += 1
        commune, volume, complet = lue
        volumes = communes.setdefault(commune, [])
        if volume in volumes:
            doublons += 1
            continue
        incompletes += not complet
        volumes.append(volume)
    if not total:
        raise ClasseurError("Aucune ligne de volume lue : le PDF n'a pas le tableau attendu.")
    if len(rejets) > seuil_rejets * total:
        exemples = " ; ".join(f"ligne {r['ligne']} ({r['motif']})" for r in rejets[:5])
        raise ClasseurError(f"{len(rejets)} lignes inexploitables sur {total} (seuil {seuil_rejets:.1%}) : format "
                            f"du classeur non reconnu, référentiel refusé. Exemples : {exemples}")
    if incompletes > seuil_bornes * total:
        raise ClasseurError(f"{incompletes} lignes à bornes illisibles sur {total} (seuil {seuil_bornes:.1%}) : "
                            "format des dates non reconnu, référentiel refusé.")
    return {"service": "AD59", "source": source, "releve_le": releve_le, "sha256": sha256, "lignes": total,
            "volumes": sum(len(v) for v in communes.values()), "doublons": doublons,
            "bornes_incompletes": incompletes, "lignes_rejetees": rejets, "communes": communes}


def serialiser(referentiel: dict) -> str:
    """JSON stable : une commune puis un volume par ligne, pour des différences lisibles d'un millésime à l'autre."""
    def court(v) -> str:
        return json.dumps(v, ensure_ascii=False)
    entete = [f"  {court(k)}: {court(v)}," for k, v in referentiel.items() if k != "communes"]
    corps = []
    for commune, volumes in referentiel["communes"].items():
        corps.append(f"    {court(commune)}: [\n" + ",\n".join(f"      {court(v)}" for v in volumes) + "\n    ]")
    return "{\n" + "\n".join(entete) + '\n  "communes": {\n' + ",\n".join(corps) + "\n  }\n}\n"


# ---------------------------------------------------------------------------- lecture

@lru_cache(maxsize=1)
def referentiel() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def cle(texte: str) -> str:
    """Forme de comparaison d'un nom de commune : sans accents ni casse, traits d'union, apostrophes et espaces
    ignorés, ST/STE développés. « Allennes les Marais » et « ALLENNES-LES-MARAIS » ont la même clé."""
    mots = re.sub(r"[^A-Z0-9]+", " ", strip_accents(texte or "").upper()).split()
    return "".join({"ST": "SAINT", "STE": "SAINTE"}.get(m, m) for m in mots)


def _alias(libelle: str) -> set[str]:
    """Clés sous lesquelles un libellé du classeur est trouvé : « BASSEE (LA) » -> La Bassée ; « AUBRY (DU
    HAINAUT) » -> Aubry et Aubry-du-Hainaut ; « LILLE (FIVES) », « BAILLEUL - LA CRECHE » -> aussi la commune."""
    m = re.fullmatch(r"(.*?)\s*\((.*)\)\s*", libelle)
    base, qualif = (m[1], m[2]) if m else libelle.split(" - ", 1) if " - " in libelle else (libelle, "")
    out = {cle(libelle), cle(base)}
    if qualif:
        out.add(cle(f"{qualif} {base}" if qualif.upper().rstrip("'") in _ARTICLES else f"{base} {qualif}"))
    return out - {""}


@lru_cache(maxsize=1)
def _index() -> dict[str, tuple[str, ...]]:
    index: dict[str, list[str]] = {}
    for libelle in referentiel()["communes"]:
        for a in _alias(libelle):
            index.setdefault(a, []).append(libelle)
    return {k: tuple(v) for k, v in index.items()}


def actes(types: str) -> frozenset[str]:
    """Lettres d'actes d'une cellule « types » (N, M, D, B, S), hors parenthèses, tables et publications."""
    nu = re.sub(r"[(\[].*?(?:[)\]]|$)", " ", strip_accents(types or "").upper())
    lettres: set[str] = set()
    for mot in re.findall(r"[A-Z]+", nu):
        if mot not in _HORS_ACTES and set(mot) <= set("NMDBS"):
            lettres |= set(mot)
    return frozenset(lettres)


def _recoupe(volume: dict, periode: list[int]) -> bool | None:
    """Recouvrement du volume et de la période ; None si une borne du classeur est illisible (à vérifier)."""
    debut, fin = volume.get("debut"), volume.get("fin")
    if debut is not None and debut > periode[1] or fin is not None and fin < periode[0]:
        return False
    return True if debut is not None and fin is not None else None


def _message(volume: dict) -> str:
    if volume["en_ligne"]:
        return "en ligne selon le classeur"
    return f"pas en ligne avant {volume['mise_en_ligne_prevue']} ; consultation en salle de lecture"


def chercher(commune: str, annee: int, annee_fin: int = 0, type_acte: str = "") -> dict:
    """Volumes du classeur d'une commune qui recoupent l'année ou l'intervalle [annee, annee_fin], filtrés par
    type d'acte (N, M, D ; NMD ou vide : tous). Chaque volume porte cote, types, bornes, statut et message."""
    data = referentiel()
    periode = [annee, annee_fin or annee]
    type_acte = (type_acte or "").strip().upper()
    voulus = set(_ACTES.get(type_acte, ""))
    libelles = _index().get(cle(commune), ())
    volumes = []
    for libelle in libelles:
        for v in data["communes"][libelle]:
            recoupe = _recoupe(v, periode)
            if recoupe is False or voulus and not voulus & actes(v["types"]):
                continue
            volumes.append({"commune": libelle, **v, "recoupe_periode": recoupe,
                            "statut": "en_ligne" if v["en_ligne"] else "mise_en_ligne_prevue",
                            "message": _message(v)})
    quoi = f"{' / '.join(libelles) or cle_commune(commune)} {periode[0]}" + (
        f"-{periode[1]}" if periode[1] != periode[0] else "") + (f" ({type_acte})" if voulus else "")
    if volumes:
        hors = [v for v in volumes if not v["en_ligne"]]
        message = f"{len(volumes)} volume(s) du classeur 3 E pour {quoi}" + (
            f", dont {len(hors)} pas encore en ligne ("
            + " ; ".join(f"{v['cote']} : {v['message']}" for v in hors[:5]) + ")." if hors
            else ", en ligne selon le classeur.")
    else:
        message = (f"Aucun volume du classeur 3 E pour {quoi} : inconnu du classeur"
                   + ("" if libelles else " (commune absente du classeur sous ce nom)")
                   + ", ce qui ne prouve pas que le registre n'existe pas.")
    return {"source": data["source"], "releve_le": data["releve_le"], "commune_connue": bool(libelles),
            "communes": list(libelles), "periode": periode, "type_acte": type_acte,
            "statut": "connu" if volumes else INCONNU, "volumes": volumes, "message": message, "limite": LIMITE}


def _cle_cote(cote: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (cote or "").upper())


def pour_recherche(commune: str, periode: list[int], type_acte: str, resultats: list[dict]) -> dict | None:
    """Constat à joindre à une recherche en ligne AD59 : rendu quand elle est vide ou quand un volume du classeur
    recoupe la période sans être en ligne ; None sinon. Distingue « absent en ligne » de « inexistant »."""
    constat = chercher(commune, periode[0], periode[1], type_acte)
    if resultats and all(v["en_ligne"] for v in constat["volumes"]):
        return None
    trouvees = {_cle_cote(r.get("cote") or "") for r in resultats}
    for v in constat["volumes"]:
        if not v["en_ligne"]:
            continue
        if not resultats:
            v["message"] = "en ligne selon le classeur mais absent de la recherche"
        elif _cle_cote(v["cote"]) in trouvees:
            v["message"] = "en ligne selon le classeur et présent dans la recherche"
        else:
            v["message"] = ("en ligne selon le classeur ; cote non reconnue parmi les résultats de cette page "
                            "(autre page ou cote différente en ligne)")
    absents = [v for v in constat["volumes"] if v["en_ligne"] and not resultats]
    if absents:
        constat["message"] += (f" {len(absents)} volume(s) en ligne selon le classeur mais absent(s) de la "
                               "recherche : vérifier les variantes de la commune, le type d'acte et l'inventaire.")
    if any(not v["en_ligne"] for v in constat["volumes"]):
        constat["message"] += " Absent en ligne ne veut pas dire inexistant : le volume existe sous la cote citée."
    return constat


def pour_fait(document: str, annee: int | None, commune: str) -> list[dict]:
    """Cotes 3 E connues pour un acte (naissance, mariage, deces) d'une commune du Nord et d'une année."""
    type_acte = {"naissance": "N", "mariage": "M", "deces": "D"}.get(document)
    if not type_acte or not annee or not commune:
        return []
    return [{k: v[k] for k in ("commune", "cote", "types", "debut", "fin", "en_ligne", "mise_en_ligne_prevue",
                               "message")}
            for v in chercher(commune, annee, 0, type_acte)["volumes"]]
