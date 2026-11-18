"""Confinement des chemins : rien de ce qu'un outil ou un média désigne ne doit sortir du répertoire de données
ni écraser un fichier interne (arbre, journal, Git). Liens symboliques résolus avant contrôle."""

from __future__ import annotations

import filecmp
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
