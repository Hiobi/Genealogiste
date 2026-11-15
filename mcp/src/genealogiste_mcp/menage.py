"""Ménage des caches sur disque : plafond de taille de cache-images (vues et originales), les plus anciennes
d'abord. Le cache SQLite des réponses se borne lui-même (cache.Cache.borner)."""

from __future__ import annotations

import contextlib
from pathlib import Path

MO = 1024 * 1024


def borner_dossier(racine: Path, max_octets: int) -> int:
    """Supprime les fichiers les plus anciens (date de modification) de racine jusqu'à tenir dans max_octets.
    Ignore les fichiers cachés (verrous, temporaires) ; une originale part avec ses métadonnées (.json).
    Renvoie le nombre de fichiers supprimés ; max_octets <= 0 = aucun plafond."""
    racine = Path(racine)
    if max_octets <= 0 or not racine.is_dir():
        return 0
    fichiers = []
    for p in racine.rglob("*"):
        if p.name.startswith(".") or p.is_symlink() or not p.is_file():
            continue
        if p.suffix == ".json" and p.with_suffix(".bin").is_file():
            continue  # compté avec son originale
        st = p.stat()
        taille = st.st_size
        meta = p.with_suffix(".json") if p.suffix == ".bin" else None
        if meta and meta.is_file():
            taille += meta.stat().st_size
        fichiers.append((st.st_mtime, p, taille, meta))
    total = sum(f[2] for f in fichiers)
    supprimes = 0
    for _, p, taille, meta in sorted(fichiers, key=lambda f: f[0]):
        if total <= max_octets:
            break
        with contextlib.suppress(OSError):
            p.unlink()
            if meta:
                meta.unlink(missing_ok=True)
            total -= taille
            supprimes += 1
    return supprimes


def borner_images(config) -> int:
    return borner_dossier(config.cache_images_dir, int(config.cache_images_max_mo * MO))
