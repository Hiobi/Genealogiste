"""Confinement des chemins : rien de ce qu'un outil ou un média désigne ne doit sortir du répertoire de données
ni écraser un fichier interne (arbre, journal, Git). Liens symboliques résolus avant contrôle."""

from __future__ import annotations

import filecmp
import re
from pathlib import Path


class CheminRefuse(ValueError):
    pass


def nom_simple(nom: str) -> str:
    """Nom de fichier sans aucun séparateur ni composant spécial (refuse « ../x », « /x », « a/b », « a\\b »)."""
    if not nom or nom in (".", "..") or "/" in nom or "\\" in nom or "\0" in nom or Path(nom).name != nom:
        raise CheminRefuse(f"Nom de fichier invalide : {nom!r} (nom simple attendu, sans répertoire)")
    return nom


def sous(base: Path, chemin: str | Path) -> Path:
    """Chemin résolu (relatif à base s'il n'est pas absolu), garanti à l'intérieur de base."""
    racine = Path(base).resolve()
    p = Path(chemin).expanduser()
    cible = (p if p.is_absolute() else racine / p).resolve()
    if not cible.is_relative_to(racine):
        raise CheminRefuse(f"Chemin hors du répertoire autorisé ({racine}) : {chemin}")
    return cible


class CheminAmbigu(CheminRefuse):
    """Chemin relatif présent sous plusieurs racines avec des contenus différents : aucun n'est choisi."""

    def __init__(self, chemin, candidats: list[Path]):
        self.candidats = candidats
        super().__init__(f"Chemin ambigu : {chemin} désigne des fichiers différents sous plusieurs racines ("
                         + ", ".join(str(c) for c in candidats) + ") ; utiliser le chemin absolu ou "
                         "supprimer le doublon")


def localiser(racines, chemin: str | Path) -> Path:
    """Fichier désigné par chemin sous l'une des racines autorisées (#192, #193).

    Un chemin absolu doit se trouver sous l'une d'elles. Un chemin relatif est essayé contre chacune, dans l'ordre :
    - existant sous une seule racine (ou sous plusieurs avec un contenu identique) : la première occurrence ;
    - existant sous plusieurs racines avec des contenus différents : CheminAmbigu (jamais de choix silencieux) ;
    - absent partout : le chemin sous la première racine qui l'admet (absent).
    CheminRefuse si aucune racine ne l'admet (absolu ailleurs, traversée « .. » ou lien symbolique sortants)."""
    admis: list[Path] = []
    trouves: list[Path] = []
    for racine in dict.fromkeys(Path(r).resolve() for r in racines if r is not None):
        try:
            p = sous(racine, chemin)
        except CheminRefuse:
            continue
        admis.append(p)
        if p.is_file() and p not in trouves:
            trouves.append(p)
    if trouves:
        differents = [t for t in trouves[1:] if not filecmp.cmp(trouves[0], t, shallow=False)]
        if differents:
            raise CheminAmbigu(chemin, [trouves[0], *differents])
        return trouves[0]
    if admis:
        return admis[0]
    raise CheminRefuse(f"Chemin hors des répertoires autorisés (données, médias) : {chemin}")


def sortie_donnees(data_dir: Path, chemin: str, suffixe: str) -> Path:
    """Fichier de sortie d'un outil : dans le répertoire de données, hors .git, avec l'extension attendue
    (ce qui exclut arbre.ged, journal.jsonl et les autres fichiers internes)."""
    cible = sous(data_dir, chemin)
    if cible.suffix.lower() != suffixe:
        raise CheminRefuse(f"Extension {suffixe} attendue : {chemin}")
    if ".git" in cible.relative_to(Path(data_dir).resolve()).parts:
        raise CheminRefuse(f"Écriture interdite dans .git : {chemin}")
    return cible


# ============================================================================ bilan de résolution (#280)

_WINDOWS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")  # « C:\… », « C:/… », « \\serveur\… » : jamais un chemin d'ici
_NOM_SERVEUR = re.compile(r"^[0-9a-f]{32}\.[A-Za-z0-9]{1,8}$")  # nom donné par Gramps Web après l'envoi (somme.ext)
CAUSES_MEDIAS = ("introuvables", "ambigus", "hors_racines")
LIMITE_MEDIAS = 2000  # médias examinés au plus : un gros arbre ne ralentit ni le diagnostic ni l'import


def bilan_chemins_medias(entrees, racines, base=None, limite: int = LIMITE_MEDIAS, echantillon: int = 10) -> dict:
    """Où se résout le chemin de chaque média, par la règle commune (:func:`localiser`) : confiné aux ``racines``
    autorisées, jamais ailleurs ; aucun contenu de fichier lu hors le contrôle d'ambiguïté de ``localiser``.

    ``entrees`` : couples (identifiant, chemin). ``base`` : racine de l'arborescence des pièces, le « chemin de base
    des médias » qu'un Gramps Desktop doit avoir pour retrouver directement un chemin relatif (``desktop_direct`` :
    chemin relatif dont le fichier existe sous cette base). Comptes par cause : ``introuvables`` (admis mais
    absent), ``ambigus`` (fichiers différents sous plusieurs racines), ``hors_racines`` (absolu ailleurs,
    traversée « .. », lien sortant, chemin Windows), ``nom_serveur`` (nom attribué par Gramps Web, sans fichier
    ici) ; ``distants`` (adresses web) et ``sans_chemin`` à part. ``echantillon`` : identifiants seulement (jamais
    un titre, un nom de personne ni un chemin)."""
    base_resolue = Path(base).resolve() if base else None
    out: dict = {"total": 0, "examines": 0, "non_verifies": 0, "resolus": 0, "desktop_direct": 0, "absolus": 0,
                 "distants": 0, "sans_chemin": 0, "nom_serveur": 0, **{c: 0 for c in CAUSES_MEDIAS}}
    ech: dict[str, list[str]] = {c: [] for c in (*CAUSES_MEDIAS, "nom_serveur")}

    def noter(cause: str, ident: str) -> None:
        out[cause] += 1
        if len(ech[cause]) < echantillon:
            ech[cause].append(ident)

    for ident, chemin in entrees:
        out["total"] += 1
        chemin = (chemin or "").strip()
        if not chemin:
            out["sans_chemin"] += 1
            continue
        if "://" in chemin:
            out["distants"] += 1
            continue
        if out["examines"] >= limite:
            out["non_verifies"] += 1
            continue
        out["examines"] += 1
        if _WINDOWS.match(chemin):
            out["absolus"] += 1
            noter("hors_racines", ident)
            continue
        try:
            absolu = Path(chemin).expanduser().is_absolute()
            p = localiser(racines, chemin)
            existe = p.is_file()
        except CheminAmbigu:
            out["absolus"] += Path(chemin).is_absolute()
            noter("ambigus", ident)
            continue
        except (CheminRefuse, RuntimeError, ValueError, OSError):
            # refusé, ou chemin de fichier tiers inutilisable (« ~inconnu », octet nul, nom trop long) : jamais lu
            out["absolus"] += chemin.startswith(("/", "~", "\\"))
            noter("hors_racines", ident)
            continue
        out["absolus"] += absolu
        if not existe:
            noter("nom_serveur" if _NOM_SERVEUR.match(chemin) else "introuvables", ident)
            continue
        out["resolus"] += 1
        if base_resolue and not absolu and (base_resolue / chemin).is_file() \
                and (base_resolue / chemin).resolve() == p:
            out["desktop_direct"] += 1
    out["echantillon"] = {c: v for c, v in ech.items() if v}
    return out
