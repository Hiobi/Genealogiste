"""Billets du blog de Gramps Web (#261) : une source portant l'étiquette ``Blog``.

Correspondance (frontend gramps-web v26.11.0, ``GrampsjsViewBlog.js``, ``GrampsjsBlogPost.js``) : titre = titre
de la source, auteur = auteur, corps = PREMIÈRE note de la source, aperçu = premier média, galerie = tous les
médias ; liste triée par date de dernière modification (``-change``). Un billet n'est pas une source
généalogique : il ne compte jamais comme preuve (``evidence.citation_weight``) et n'a pas de fiche dans les
notes de recherche (``notes_generer``).

Garde-fous appliqués à toute proposition qui crée ou modifie un billet (:func:`controler`) :

- privé par défaut (``ajouter_billet``, ``ajouter_source`` avec l'étiquette ``Blog``) : seul ``prive: false``
  explicite le rend public, c'est-à-dire lisible par les comptes Invité de Gramps Web ;
- un billet public qui nomme une personne présumée vivante ou marquée privée (prénom et nom accolés, comme pour
  les exports publics, ou lien interne ``gramps://Person/gramps_id/I…``) est refusé ; privé, il porte un
  avertissement.
"""

from __future__ import annotations

import re

from . import privacy
from .models import Source, Tree

BLOG = "Blog"  # nom exact de l'étiquette (sensible à la casse, comme le frontend : tag.name === 'Blog')
INVITE = "lisible par tout compte Invité (Guest) de Gramps Web"


def est_billet(source: Source | None) -> bool:
    return bool(source) and BLOG in (source.tags or [])


def visibilite(source: Source) -> str:
    return ("privé (comptes Membre et plus ; invisible des comptes Invité)" if source.prive
            else f"PUBLIC ({INVITE})")


def _liens_personnes(textes: list[str], styles: dict[str, list[dict]]) -> set[str]:
    """Identifiants des personnes visées par un lien interne ``gramps://Person/gramps_id/I…`` (Markdown #279)."""
    from .gramps.texte import cible_interne

    out = set()
    for texte in textes:
        for cle, tags in styles.items():
            if not cle or cle not in texte:
                continue
            for t in tags:
                c = cible_interne(t.get("value"))
                if c and c[0] == "Person" and c[1] == "gramps_id":
                    out.add(c[2])
    return out


def personnes_nommees(tree: Tree, source: Source, identifiants: bool = False) -> list[dict]:
    """Personnes présumées vivantes ou marquées privées de l'arbre nommées par le billet (titre, auteur, corps,
    titres de ses médias) ou visées par un de ses liens internes. ``identifiants`` (tâches, #263) : l'identifiant
    seul (« I12 », mot entier) compte aussi comme mention."""
    caches = privacy.hidden_ids(tree)
    if not caches:
        return []
    textes = [source.titre, source.auteur, source.note] + [tree.medias[m].titre for m in source.medias
                                                          if m in tree.medias]
    lies = _liens_personnes(textes, tree.styles)
    out = []
    for pid in sorted(caches):
        p = tree.personnes[pid]
        motifs = privacy.identifying_patterns(tree, {pid})
        trouves = sorted({x for t in textes for x in privacy.residues(t, motifs)})
        if pid in lies:
            trouves.append(f"lien interne vers {pid}")
        elif identifiants and any(re.search(rf"(?<![\w@]){re.escape(pid)}(?![\w@])", t or "") for t in textes):
            trouves.append(f"identifiant {pid}")
        if not trouves:
            continue
        st = privacy.is_living(tree, p)
        raison = f"présumé(e) vivant(e) : {st['raison']}" if st["vivant"] else "marqué(e) privé(e)"
        out.append({"id": pid, "nom": p.nom_principal.complet, "raison": raison, "mentions": trouves})
    return out


def controler(before: Tree, after: Tree) -> tuple[list[str], list[str], list[str]]:
    """Billets créés ou modifiés par une proposition : (refus, avertissements, lignes de résumé)."""
    from .objets_interface import controler as controler_objets

    return controler_objets(before, after, ("billet",))
