"""Étiquettes (tags) des objets de l'arbre (#262) : noms, ordre conservé, sans doublon.

- Modèle : ``tags: list[str]`` sur personne, famille, événement, citation, source, dépôt, média ; ``Tree.notes_tags``
  pour les notes partagées. Noms sensibles à la casse (comme Gramps Web).
- Étiquettes gérées par Genealogiste (``Genealogiste:auto`` / historique ``Sosa:auto``, statut de preuve
  « Preuve : … ») : jamais dans ``tags`` ; elles gardent leur traitement (ignorées à la lecture, recalculées) et une
  opération ne peut ni les poser ni les retirer.
- GEDCOM : extension ``_ETIQUETTE`` (une ligne par étiquette sous l'enregistrement ou la structure), voir
  docs/gedcom-extensions.md ; Gramps Web : ``tag_list`` (handles) et objets ``Tag``, voir docs/gramps-web.md.
"""

from __future__ import annotations

from . import marqueurs

GEDCOM_TAG = "_ETIQUETTE"
LONGUEUR_MAX = 100
STATUT_PREFIXE = "Preuve : "  # étiquettes de statut de preuve générées (gramps/mapping.py STATUS_TAG)
_AUTO = {marqueurs.AUTO[f] for f in marqueurs.FORMES}


def geree(nom: str) -> bool:
    """Étiquette gérée par Genealogiste (notes générées, statut de preuve) : hors du modèle."""
    return marqueurs.canon(nom or "") in _AUTO or (nom or "").startswith(STATUT_PREFIXE)


def valider(nom) -> str:
    """Nom d'étiquette accepté d'une opération (ValueError sinon) : chaîne non vide, sans retour à la ligne ni
    caractère de contrôle, au plus LONGUEUR_MAX caractères, pas une étiquette gérée (même à la casse près)."""
    if not isinstance(nom, str) or not nom.strip():
        raise ValueError(f"étiquette vide ou invalide : {nom!r}")
    if any(ord(c) < 32 or ord(c) == 127 for c in nom):
        raise ValueError(f"étiquette {nom!r} : retour à la ligne ou caractère de contrôle interdit")
    if nom != nom.strip():
        raise ValueError(f"étiquette {nom!r} : espaces en début ou en fin interdits")
    if len(nom) > LONGUEUR_MAX:
        raise ValueError(f"étiquette de plus de {LONGUEUR_MAX} caractères : {nom[:30]!r}…")
    pli = nom.casefold()
    if any(pli == a.casefold() for a in _AUTO) or pli.startswith(STATUT_PREFIXE.casefold()):
        raise ValueError(f"étiquette {nom!r} gérée par Genealogiste (notes générées, statut de preuve) : "
                         "ni posée ni retirée par une opération")
    return nom


def liste(valeur, champ: str = "tags") -> list[str]:
    """Liste de noms d'une opération, validés, sans doublon (ordre conservé)."""
    if valeur is None:
        return []
    if isinstance(valeur, str):
        valeur = [valeur]
    if not isinstance(valeur, list):
        raise ValueError(f"{champ} : liste de noms d'étiquettes attendue")
    return list(dict.fromkeys(valider(x) for x in valeur))


def unique(noms) -> list[str]:
    """Noms sans doublon ni vide, ordre conservé (lecture)."""
    return [x for x in dict.fromkeys(noms) if x]


def appliquer(actuelles: list[str], ajout: list[str], retrait: list[str]) -> tuple[list[str], list[str], list[str],
                                                                                    list[str]]:
    """(nouvelle liste, ajoutées, retirées, retraits absents) : retrait puis ajout, ordre conservé, nouvelles en fin."""
    absentes = [x for x in retrait if x not in actuelles]
    out = [x for x in actuelles if x not in retrait]
    ajoutees = [x for x in ajout if x not in out]
    retirees = [x for x in actuelles if x in retrait]
    return out + ajoutees, ajoutees, retirees, absentes


def ligne(libelle: str, ajoutees: list[str], retirees: list[str]) -> str:
    """Ligne concise du diff : « étiquettes I12 : +Blog −ToDo »."""
    return f"étiquettes {libelle} : " + " ".join([f"+{x}" for x in ajoutees] + [f"−{x}" for x in retirees])


def difference(avant: list[str], apres: list[str]) -> tuple[list[str], list[str]]:
    return [x for x in apres if x not in avant], [x for x in avant if x not in apres]


def lignes_arbres(avant, apres) -> list[str]:
    """Une ligne par objet dont les étiquettes changent entre deux arbres (objets à identifiant stable : personnes,
    familles, événements, sources, dépôts, médias, notes partagées ; citations par position dans leur porteur)."""
    from .models import EVENT_LABELS

    out: list[str] = []

    def comparer(label: str, a: list[str], b: list[str]) -> None:
        plus, moins = difference(a, b)
        if plus or moins:
            out.append(ligne(label, plus, moins))

    def citations(label: str, a_cits, b_cits) -> None:
        if len(a_cits) == len(b_cits):
            for i, (ca, cb) in enumerate(zip(a_cits, b_cits, strict=True)):
                comparer(f"citation {cb.source}" + (f" ({cb.page})" if cb.page else "") + f" sur {label}"
                         + (f" #{i + 1}" if len(b_cits) > 1 else ""), ca.tags, cb.tags)
        else:
            for c in b_cits:
                if c.tags and c not in a_cits:
                    comparer(f"citation {c.source}" + (f" ({c.page})" if c.page else "") + f" sur {label}", [], c.tags)

    def evenements(owner_id: str, a_evs, b_evs) -> None:
        anciens = {e.uid: e for e in a_evs}
        for e in b_evs:
            label = f"{owner_id} {EVENT_LABELS.get(e.type, e.type)}"
            before = anciens.get(e.uid)
            comparer(label, before.tags if before else [], e.tags)
            citations(label, before.citations if before else [], e.citations)

    for kind in ("personnes", "familles"):
        a_coll, b_coll = getattr(avant, kind), getattr(apres, kind)
        for oid in sorted(b_coll):
            o, b = a_coll.get(oid), b_coll[oid]
            comparer(oid, o.tags if o else [], b.tags)
            citations(oid, o.citations if o else [], b.citations)
            evenements(oid, o.evenements if o else [], b.evenements)
    for kind in ("sources", "depots", "medias"):
        a_coll, b_coll = getattr(avant, kind), getattr(apres, kind)
        for oid in sorted(b_coll):
            o = a_coll.get(oid)
            comparer(oid, o.tags if o else [], b_coll[oid].tags)
            if kind == "medias":
                citations(oid, o.citations if o else [], b_coll[oid].citations)
    for nid in sorted(apres.notes):
        comparer(nid, avant.notes_tags.get(nid, []) if nid in avant.notes else [], apres.notes_tags.get(nid, []))
    return out
