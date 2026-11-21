"""Règle commune de réduction des chemins de médias en export public (#280 Gramps XML, #307 GEDCOM).

Un chemin absolu (``/…``, ``~…``, ``C:\\…``, UNC ``\\\\serveur\\…``) ou sortant (composant ``..``) révèle l'arborescence
et le compte de la machine : il est réduit à son nom de fichier. Un chemin relatif sans ``..`` et une adresse web
(``http(s)://``…) restent tels quels. Le bilan ne contient que des identifiants de médias, jamais un chemin."""
from __future__ import annotations

import copy
import re

from ..models import Tree

ABSOLU_WINDOWS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\/])")


def sensible(c: str) -> bool:
    """Vrai pour un chemin local absolu ou sortant (jamais pour une adresse ``://``)."""
    if not c or "://" in c:
        return False
    return (c.startswith(("/", "~", "\\")) or bool(ABSOLU_WINDOWS.match(c))
            or ".." in re.split(r"[\\/]+", c))


def nom_fichier(c: str) -> str:
    return next((x for x in reversed(re.split(r"[\\/]+", c)) if x not in ("", ".", "..")), "")


def reduire(c: str) -> str:
    """Le chemin réduit à son nom de fichier s'il est absolu ou sortant, sinon inchangé."""
    return nom_fichier(c) if sensible(c) else c


def reduire_chemins_arbre(tree: Tree) -> tuple[Tree, dict]:
    """Copie de l'arbre où ``Media.fichier`` est réduit par la règle commune. Renvoie la copie et le bilan
    ``{nombre, medias}`` (médias dans l'ordre de leur identifiant)."""
    t = copy.deepcopy(tree)
    reduits = []
    for mid in sorted(t.medias):
        m = t.medias[mid]
        if sensible(m.fichier):
            m.fichier = nom_fichier(m.fichier)
            reduits.append(mid)
    return t, {"nombre": len(reduits), "medias": reduits}
