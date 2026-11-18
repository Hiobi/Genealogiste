"""Images d'une citation rattachées aussi à ce qu'elle prouve (#246).

Une image jointe à une citation (``citation.medias``) n'apparaît, sans cela, que sous la citation : l'onglet
Médias de la personne, de l'événement et de la source (Gramps Web) ne la montre pas. Les cibles se déduisent du
seul titulaire de la citation, jamais du contenu de l'image : une vue collective (table, recensement) n'est liée
qu'aux personnes effectivement citées avec elle.

- événement individuel : l'événement, la personne, la source ;
- événement familial : l'événement, la famille, les deux conjoints, la source ;
- preuve de l'union (citations de la famille) : la famille, les deux conjoints, la source ;
- nom ou citation générale d'une personne : la personne, la source ;
- filiation : l'enfant, la source ;
- association (témoin, parrain…) : la source seulement ; les citations d'un média ne sont pas concernées.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from ..models import Citation, Tree


def _titulaires(tree: Tree) -> Iterator[tuple[Citation, list[str]]]:
    """(citation, cibles) pour chaque citation de l'arbre portant des images."""
    for p in tree.personnes.values():
        for e in p.evenements:
            for c in e.citations:
                yield c, [e.uid, p.id]
            for a in e.associations:
                for c in a.citations:
                    yield c, []
        for n in p.noms:
            for c in n.citations:
                yield c, [p.id]
        for c in p.citations:
            yield c, [p.id]
        for a in p.associations:
            for c in a.citations:
                yield c, []
    for f in tree.familles.values():
        conjoints = [x for x in (f.epoux, f.epouse) if x]
        for e in f.evenements:
            for c in e.citations:
                yield c, [e.uid, f.id, *conjoints]
            for a in e.associations:
                for c in a.citations:
                    yield c, []
        for c in f.citations:
            yield c, [f.id, *conjoints]
        for lien in f.enfants:
            for c in lien.citations:
                yield c, [lien.enfant]


def cibles(tree: Tree, retenir: Callable[[Citation], bool] | None = None) -> dict[str, list[str]]:
    """Média -> cibles (uid d'événement, I…, F…, S…) déduites des citations qui le portent, sans doublon."""
    out: dict[str, list[str]] = {}
    for c, titulaires in _titulaires(tree):
        if not c.medias or (retenir and not retenir(c)):
            continue
        for mid in c.medias:
            liste = out.setdefault(mid, [])
            for cible in (*titulaires, c.source):
                if cible and cible not in liste:
                    liste.append(cible)
    return out


def _deja_lie(tree: Tree, mid: str, cible: str) -> bool:
    owner = tree.personnes.get(cible) or tree.familles.get(cible) or tree.sources.get(cible)
    if owner is None:
        found = tree.find_event(cible)
        if not found:
            return True  # cible absente : rien à proposer (l'intégrité la signale ailleurs)
        owner = found[1]
    return mid in owner.medias or any(
        isinstance(x, dict) and x.get("tag") == "OBJE" and (x.get("value") or "").strip() == f"@{mid}@"
        for x in getattr(owner, "extra", None) or [])


def a_lier(tree: Tree) -> list[dict]:
    """Rattrapage : images liées à des citations mais pas à ce qu'elles prouvent, avec l'opération modifier_media
    qui les rattache (à soumettre par arbre_proposer, rien n'est écrit ici)."""
    out = []
    for mid, liste in sorted(cibles(tree).items()):
        manquantes = [c for c in liste if mid in tree.medias and not _deja_lie(tree, mid, c)]
        if manquantes:
            m = tree.medias[mid]
            out.append({"media": mid, "titre": m.titre or m.fichier, "cibles": manquantes,
                        "operation": {"op": "modifier_media", "id": mid, "lier_a": manquantes}})
    return out
