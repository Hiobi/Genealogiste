"""Point d'entrée conservé : l'ancien exporteur vulnérable n'est plus exécuté."""

from __future__ import annotations

from .base import SourceContext


def export_gedcom(ctx: SourceContext, ids: list[str], ascendants: int = 4, descendants: int = 0,
                  conjoints: bool = True, sortie: str = "") -> dict:
    return {
        "erreur": "Export FamilySearch désactivé : getmyancestors impose des dépendances vulnérables.",
        "suite": "Importer un fichier GEDCOM obtenu séparément avec arbre_importer_gedcom ; "
                 "ne pas fournir d'identifiants FamilySearch au plugin.",
    }
