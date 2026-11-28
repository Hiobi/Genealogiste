"""Recensements de population des AD59 : état de la collection, cotes et mode d'accès par commune (#375).

Le référentiel ``referentiels/ad59_recensements.json`` est produit par
``scripts/generer_couverture_recensements_ad59.py`` à partir du PDF public « Recensements de population, État de
la collection » (relevé daté, empreinte SHA-256). Lecture locale seulement : aucun réseau, aucune personne.
Un millésime absent du référentiel est « inconnu du référentiel », jamais « inexistant ».
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .normalize.names import strip_accents

PATH = Path(__file__).parent / "referentiels" / "ad59_recensements.json"
SOURCE = "https://archivesdepartementales.lenord.fr/ark:/33518/c7r0j89k6phb"  # notice du document
DOCUMENT = "https://archivesdepartementales.lenord.fr/media/318b224b-e7f9-4b64-a1cd-c3b6e8cac76f.pdf"
SOCFACE = {  # base de noms : seule piste nominative, jamais interrogée par le plugin (relevé du 27 novembre 2026)
    "page": "https://archivesdepartementales.lenord.fr/page/socface-et-les-recensements-de-population",
    "recherche": "https://francearchives.gouv.fr/fr/basedenoms",
    "consigne": ("Recherche par nom : base de noms Socface sur FranceArchives, à consulter soi-même dans un "
                 "navigateur (défi JavaScript et cookies : aucune interrogation automatique, aucun nom envoyé par "
                 "le plugin). Couverture du Nord et des millésimes non vérifiée ; un index est une source dérivée : "
                 "vérifier sur la liste nominative (archives_naviguer sur l'ARK du recensement)."),
}
ENTETE = ("COMMUNE", "ANNEE", "COTE", "MIS EN LIGNE", "SALLE DE LECTURE")
SEUIL_REJETS = 0.005  # part de lignes inexploitables au-delà de laquelle le référentiel est refusé
SEUIL_ANNEES = 0.01   # part de lignes gardées dont le millésime est illisible
EN_LIGNE, SALLE = "en_ligne", "salle_de_lecture"
INCONNU = "inconnu_du_referentiel"
LIMITE = ("État de la collection publié par les AD59, lu tel quel à la date du relevé : il peut être incomplet ou "
          "dépassé. Un recensement connu ne prouve pas la présence d'une personne ; un millésime inconnu du "
          "référentiel ne prouve pas que le recensement n'existe pas. Listes nominatives : communicables après "
          "75 ans (outil communicabilite), y compris en salle de lecture.")
_ARTICLES = {"LE", "LA", "LES", "L"}
# mots de quartier, canton ou section qui suivent le nom de la commune dans un libellé (« LILLE CANTON SUD EST »)
_SECTEURS = {"CANTON", "NORD", "SUD", "EST", "OUEST", "CENTRE", "ET", "EXTRA", "INTRA", "MUROS", "CAMPAGNE", "VILLE"}


class EtatCollectionError(ValueError):
    """Le PDF ne permet pas de produire un référentiel fiable."""


# ---------------------------------------------------------------------------- analyse (génération)

def _cellules(ligne: list) -> list[str]:
    return [" ".join(str(x or "").split()) for x in ligne]


def _est_entete(c: list[str]) -> bool:
    return tuple(strip_accents(x).upper() for x in c) == ENTETE


def analyser_ligne(cellules: list) -> tuple[str, dict, bool] | None:
    """Une ligne du tableau (commune, année, cote, « Mis en ligne », « Salle de lecture ») -> (commune, volume,
    millésime lu). None pour une ligne vide ou d'en-tête ; EtatCollectionError (motif) pour une ligne inexploitable.
    Le mode d'accès ne tient qu'à la colonne de la croix : une croix dans les deux colonnes, dans aucune, ou un
    autre contenu est refusé plutôt que deviné. Commune et cote sont gardées telles qu'écrites."""
    c = _cellules(cellules)
    if not any(c) or _est_entete(c):
        return None
    if len(c) != 5:
        raise EtatCollectionError(f"{len(c)} colonnes au lieu de 5")
    commune, annee, cote, ligne, salle = c
    if not commune or not annee or not cote:
        raise EtatCollectionError("commune, année ou cote absente")
    croix = [x.upper() for x in (ligne, salle)]
    if croix not in (["X", ""], ["", "X"]):
        raise EtatCollectionError(f"mode d'accès ambigu : « {ligne[:20]} » / « {salle[:20]} »")
    m = re.fullmatch(r"(\d{4})(?:\s*-\s*(\d{4}))?", annee) or re.match(r"(\d{4})()\b", annee)
    debut = int(m[1]) if m and 1500 <= int(m[1]) <= 2100 else None
    fin = int(m[2]) if debut and m[2] else debut
    if debut and not debut <= fin <= 2100:
        debut = fin = None
    volume = {"debut": debut, "fin": fin, "cote": cote, "acces": EN_LIGNE if croix[0] else SALLE}
    if not re.fullmatch(r"\d{4}", annee) or debut is None:
        volume["annee"] = annee  # texte du document : années doubles (an VIII), mention ou valeur illisible
    return commune, volume, debut is not None


def analyser(lignes: list, source: str = SOURCE, sha256: str = "", releve_le: str = "", document: str = DOCUMENT,
             seuil_rejets: float = SEUIL_REJETS, seuil_annees: float = SEUIL_ANNEES) -> dict:
    """Lignes du tableau -> référentiel. La première ligne non vide doit être l'en-tête attendu : sans lui, rien
    ne dit quelle colonne est « Mis en ligne ». Refuse (EtatCollectionError) un tableau vide ou dont trop de
    lignes sont inexploitables, plutôt que de produire un référentiel silencieusement faux."""
    communes: dict[str, list] = {}
    rejets, total, doublons, illisibles, entete = [], 0, 0, 0, False
    for numero, ligne in enumerate(lignes, 1):
        c = _cellules(ligne)
        if not any(c):
            continue
        if not entete:
            if not _est_entete(c):
                raise EtatCollectionError("En-tête « COMMUNE / ANNEE / COTE / Mis en ligne / Salle de lecture » "
                                          f"absent ou différent ({' / '.join(c)[:80]}) : colonnes d'accès non "
                                          "identifiables, référentiel refusé.")
            entete = True
            continue
        try:
            lue = analyser_ligne(c)
        except EtatCollectionError as exc:
            total += 1
            rejets.append({"ligne": numero, "motif": str(exc)})
            continue
        if lue is None:
            continue
        total += 1
        commune, volume, lisible = lue
        volumes = communes.setdefault(commune, [])
        if volume in volumes:
            doublons += 1
            continue
        illisibles += not lisible
        volumes.append(volume)
    if not total:
        raise EtatCollectionError("Aucune ligne de recensement lue : le PDF n'a pas le tableau attendu.")
    if len(rejets) > seuil_rejets * total:
        exemples = " ; ".join(f"ligne {r['ligne']} ({r['motif']})" for r in rejets[:5])
        raise EtatCollectionError(f"{len(rejets)} lignes inexploitables sur {total} (seuil {seuil_rejets:.1%}) : "
                                  f"format de l'état de la collection non reconnu, référentiel refusé. "
                                  f"Exemples : {exemples}")
    if illisibles > seuil_annees * total:
        raise EtatCollectionError(f"{illisibles} lignes à millésime illisible sur {total} (seuil "
                                  f"{seuil_annees:.1%}) : format des années non reconnu, référentiel refusé.")
    tous = [v for volumes in communes.values() for v in volumes]
    return {"service": "AD59", "source": source, "document": document, "releve_le": releve_le, "sha256": sha256,
            "lignes": total, "volumes": len(tous), "doublons": doublons,
            EN_LIGNE: sum(v["acces"] == EN_LIGNE for v in tous), SALLE: sum(v["acces"] == SALLE for v in tous),
            "annees_illisibles": illisibles, "lignes_rejetees": rejets, "communes": communes}


def serialiser(referentiel: dict) -> str:
    """JSON stable : une commune puis un volume par ligne, pour des différences lisibles d'un relevé à l'autre."""
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


def _mots(texte: str) -> list[str]:
    mots = re.sub(r"[^A-Z0-9]+", " ", strip_accents(texte or "").upper()).split()
    return [{"ST": "SAINT", "STE": "SAINTE"}.get(m, m) for m in mots]


def _cles(mots: list[str]) -> set[str]:
    """Clé de comparaison, avec et sans article initial (« LA CHAPELLE D'ARMENTIERES » / « CHAPELLE D'… »)."""
    out = {"".join(mots)}
    if len(mots) > 1 and mots[0] in _ARTICLES:
        out.add("".join(mots[1:]))
    return out - {""}


def _alias(libelle: str) -> set[str]:
    """Clés sous lesquelles un libellé est trouvé : le libellé entier, puis la commune sans ses précisions de
    quartier ou de volume : « ROUBAIX (Canton Est) », « LILLE CANTON SUD EST », « BOURBOURG Campagne »,
    « Lille : non versé » répondent aussi à la commune. Le libellé d'origine est rendu avec chaque volume."""
    base = _mots(re.sub(r"\(.*?\)", " ", libelle).split(" : ")[0])
    commune = list(base)
    while len(commune) > 1 and commune[-1] in _SECTEURS:
        commune.pop()
    return _cles(_mots(libelle)) | _cles(base) | _cles(commune)


@lru_cache(maxsize=1)
def _index() -> dict[str, tuple[str, ...]]:
    index: dict[str, list[str]] = {}
    for libelle in referentiel()["communes"]:
        for a in _alias(libelle):
            index.setdefault(a, []).append(libelle)
    return {k: tuple(v) for k, v in index.items()}


def libelles(commune: str) -> tuple[str, ...]:
    """Libellés du référentiel répondant à un nom de commune (sans accents ni casse, tirets, apostrophes et
    espaces ignorés, ST/STE développés, article initial facultatif)."""
    trouves: list[str] = []
    for k in sorted(_cles(_mots(commune)), key=len, reverse=True):
        trouves.extend(x for x in _index().get(k, ()) if x not in trouves)
    return tuple(trouves)


def _recoupe(volume: dict, periode: list[int]) -> bool | None:
    """Recouvrement du volume et de la période ; None si le millésime est illisible (à vérifier)."""
    if volume["debut"] is None:
        return None
    return volume["debut"] <= periode[1] and periode[0] <= volume["fin"]


def _message(volume: dict) -> str:
    if volume["acces"] == EN_LIGNE:
        return "en ligne selon l'état de la collection"
    return ("pas en ligne : consultation en salle de lecture seulement selon l'état de la collection, sous "
            "réserve de communicabilité (75 ans)")


def _rendu(libelle: str, volume: dict, **plus) -> dict:
    return {"commune": libelle, **volume, **plus, "message": _message(volume)}


def _millesimes(volumes: list[dict]) -> dict:
    return {acces: sorted({v["debut"] for v in volumes if v["acces"] == acces and v["debut"] is not None})
            for acces in (EN_LIGNE, SALLE)}


def chercher(commune: str, annee: int, annee_fin: int = 0) -> dict:
    """Recensements du référentiel pour une commune et une année ou un intervalle [annee, annee_fin] : cote
    telle qu'écrite, millésime, mode d'accès (en_ligne / salle_de_lecture) et message. millesimes_connus donne
    tous les millésimes de la commune, pour lire un négatif : un millésime absent est inconnu du référentiel."""
    data = referentiel()
    periode = [annee, annee_fin or annee]
    noms = libelles(commune)
    tous = [(libelle, v) for libelle in noms for v in data["communes"][libelle]]
    volumes = [_rendu(libelle, v, recoupe_periode=r) for libelle, v in tous
               if (r := _recoupe(v, periode)) is not False]
    connus = _millesimes([v for _, v in tous])
    quoi = (f"{' / '.join(noms[:4]) + (' …' if len(noms) > 4 else '') or ' '.join(_mots(commune))} "
            f"{periode[0]}" + (f"-{periode[1]}" if periode[1] != periode[0] else ""))
    if volumes:
        salle = [v for v in volumes if v["acces"] == SALLE]
        message = f"{len(volumes)} recensement(s) connu(s) de l'état de la collection pour {quoi}" + (
            f", dont {len(salle)} en salle de lecture seulement, pas en ligne ("
            + " ; ".join(f"{v['cote']}" for v in salle[:5]) + ")." if salle
            else ", en ligne selon l'état de la collection.")
    else:
        message = f"Aucun recensement connu de l'état de la collection pour {quoi} : inconnu du référentiel"
        if not noms:
            message += " (commune absente du référentiel sous ce nom)"
        elif any(connus.values()):
            message += (" ; millésimes connus pour la commune : " + " ; ".join(
                f"{', '.join(map(str, annees))} ({'en ligne' if acces == EN_LIGNE else 'salle de lecture'})"
                for acces, annees in connus.items() if annees))
        message += ", ce qui ne prouve pas que le recensement n'existe pas."
    return {"source": data["source"], "releve_le": data["releve_le"], "commune_connue": bool(noms),
            "communes": list(noms), "periode": periode, "statut": "connu" if volumes else INCONNU,
            "volumes": volumes, "millesimes_connus": connus, "message": message, "limite": LIMITE,
            "recherche_nominative": dict(SOCFACE)}


def _cle_cote(cote: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (cote or "").upper())


def _meme_cote(volume: dict, resultat: dict) -> bool:
    """Cote du document et cote affichée en ligne : même suite de caractères, au nom de commune final près
    (« M 474 5 19 SOMAIN » / « M474 5 / 19 SOMAIN », « M 474 572 » / « M 474 / 572 »), pour le même millésime."""
    a, b = _cle_cote(volume["cote"]), _cle_cote(resultat.get("cote") or "")
    bornes = resultat.get("bornes")
    if not a or not b or bornes and volume["debut"] is not None and not _recoupe(volume, bornes):
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def pour_recherche(commune: str, periode: list[int], resultats: list[dict]) -> dict | None:
    """Constat à joindre à une recherche de recensements AD59 : rendu quand elle est vide ou quand un recensement
    de la période n'est qu'en salle de lecture ; None sinon. Distingue « pas en ligne » de « inexistant »."""
    constat = chercher(commune, periode[0], periode[1])
    if resultats and all(v["acces"] == EN_LIGNE for v in constat["volumes"]):
        return None
    absents = 0
    for v in constat["volumes"]:
        if v["acces"] != EN_LIGNE:
            continue
        if not resultats:
            absents += 1
            v["message"] = "en ligne selon l'état de la collection mais absent de la recherche"
        elif any(_meme_cote(v, r) for r in resultats):
            v["message"] = "en ligne selon l'état de la collection et présent dans la recherche"
        else:
            v["message"] = ("en ligne selon l'état de la collection ; cote non reconnue parmi les résultats de "
                            "cette page (autre page ou cote différente en ligne)")
    if absents:
        constat["message"] += (f" {absents} recensement(s) en ligne selon l'état de la collection mais absent(s) "
                               "de la recherche : vérifier le nom de la commune, la page et l'inventaire.")
    if any(v["acces"] == SALLE for v in constat["volumes"]):
        constat["message"] += " Pas en ligne ne veut pas dire inexistant : le recensement existe sous la cote citée."
    return constat


def pour_fait(annee: int | None, commune: str, avant: bool = True) -> list[dict]:
    """Cotes de recensement connues pour une commune du Nord autour d'une année : le millésime qui la contient
    (position « annee ») et les recensements connus les plus proches avant (si ``avant``) et après."""
    if not annee or not commune:
        return []
    data = referentiel()
    dates = [(libelle, v) for libelle in libelles(commune) for v in data["communes"][libelle]
             if v["debut"] is not None]
    precedent = max((v["fin"] for _, v in dates if v["fin"] < annee), default=None) if avant else None
    suivant = min((v["debut"] for _, v in dates if v["debut"] > annee), default=None)
    out = []
    for libelle, v in dates:
        position = ("annee" if v["debut"] <= annee <= v["fin"] else "avant" if v["fin"] == precedent
                    else "apres" if v["debut"] == suivant else "")
        if position:
            out.append(_rendu(libelle, v, position=position))
    return sorted(out, key=lambda v: (v["debut"], v["commune"], v["cote"]))
