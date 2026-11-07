"""Liens de fichiers Markdown : destination URL encodée et libellé littéral."""

from urllib.parse import quote


def lien_fichier(chemin: str, libelle: str = '', *, image: bool = False) -> str:
    libelle = libelle.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]').replace('\n', ' ')
    return f"{'!' if image else ''}[{libelle}]({quote(chemin, safe='/')})"
