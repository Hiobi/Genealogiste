"""Confinement des chemins : rien de ce qu'un outil ou un média désigne ne doit sortir du répertoire de données
ni écraser un fichier interne (arbre, journal, Git). Liens symboliques résolus avant contrôle."""

from __future__ import annotations

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


def sortie_donnees(data_dir: Path, chemin: str, suffixe: str) -> Path:
    """Fichier de sortie d'un outil : dans le répertoire de données, hors .git, avec l'extension attendue
    (ce qui exclut arbre.ged, journal.jsonl et les autres fichiers internes)."""
    cible = sous(data_dir, chemin)
    if cible.suffix.lower() != suffixe:
        raise CheminRefuse(f"Extension {suffixe} attendue : {chemin}")
    if ".git" in cible.relative_to(Path(data_dir).resolve()).parts:
        raise CheminRefuse(f"Écriture interdite dans .git : {chemin}")
    return cible
