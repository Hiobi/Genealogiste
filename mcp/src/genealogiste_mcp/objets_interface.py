"""Objets d'interface de Gramps Web : sources que l'interface présente autrement qu'une source, selon une étiquette.

- billet du blog (#261) : étiquette ``Blog`` (:mod:`billets`) ;
- tâche (#263) : étiquette ``ToDo``, seulement avec ``GENEALOGISTE_GRAMPS_TACHES`` (:mod:`taches`).

Mécanique commune : le texte affiché est la PREMIÈRE note de la source (créée avec l'étiquette de l'objet, sa
confidentialité suit celle de la source, les notes générées viennent après ou pas du tout), un objet inchangé
n'est jamais réécrit, l'objet n'est pas une source de preuve (poids 0, ``evidence``) et n'a pas de fiche dans les
notes de recherche (``notes``). Garde-fous de toute proposition qui en crée ou en modifie un (:func:`controler`) :
privé par défaut ; public nommant une personne présumée vivante ou marquée privée : refusé ; privé : averti.
"""

from __future__ import annotations

from . import billets, taches
from .models import Source, Tree

INVITE = billets.INVITE


def genre(source: Source | None) -> str:
    """« billet », « tache » ou "" (le billet prime si une source porte les deux étiquettes)."""
    if billets.est_billet(source):
        return "billet"
    if taches.est_tache(source):
        return "tache"
    return ""


def est_objet_interface(source: Source | None) -> bool:
    return bool(genre(source))


ETIQUETTES = {"billet": billets.BLOG, "tache": taches.TODO}

# Messages par genre (ceux des billets sont ceux de #261, inchangés).
MESSAGES = {
    "billet": {
        "prive": "privé (comptes Membre et plus ; invisible des comptes Invité)",
        "public": f"PUBLIC ({INVITE})",
        "resume": "Billet {sid} « {titre} » : {visibilite}",
        "rendu_public": "Billet {sid} rendu public : il devient {invite} (corps et médias publics compris).",
        "cree_public": "Billet {sid} public : {invite}. « prive: true » pour le réserver aux comptes Membre et plus.",
        "devenu": ("Source {sid} devenue billet : ses {n} citation(s) ne comptent plus comme preuve (un billet est "
                   "un récit) ; statuts de preuve recalculés en conséquence."),
        "sans_texte": "Billet {sid} sans texte : la page Blog affiche la première note de la source.",
        "nomme_prive": ("Billet {sid} privé : il nomme des personnes présumées vivantes ou privées : {liste}. "
                        "Il ne doit pas devenir public en l'état."),
        "refus": ("Billet {sid} public refusé : il nomme des personnes présumées vivantes ou privées ({liste}) et "
                  "serait {invite}. Retirer ces noms, ou garder le billet privé (prive: true, défaut)."),
    },
    "tache": {
        "prive": "privée (comptes Membre et plus ; invisible des comptes Invité)",
        "public": f"PUBLIQUE ({INVITE})",
        "resume": "Tâche {sid} « {titre} » : {visibilite}{details}",
        "rendu_public": "Tâche {sid} rendue publique : elle devient {invite} (description comprise).",
        "cree_public": ("Tâche {sid} publique : {invite}. « prive: true » pour la réserver aux comptes Membre et "
                        "plus."),
        "devenu": ("Source {sid} devenue tâche : ses {n} citation(s) ne comptent plus comme preuve (une tâche est "
                   "un plan de recherche) ; statuts de preuve recalculés en conséquence."),
        "sans_texte": "",
        "nomme_prive": ("Tâche {sid} privée : elle nomme des personnes présumées vivantes ou privées : {liste}. "
                        "Elle ne doit pas devenir publique en l'état."),
        "refus": ("Tâche {sid} publique refusée : elle nomme des personnes présumées vivantes ou privées ({liste}) "
                  "et serait {invite}. Retirer ces noms et identifiants, ou garder la tâche privée (prive: true, "
                  "défaut)."),
    },
}


def visibilite(source: Source) -> str:
    m = MESSAGES[genre(source) or "billet"]
    return m["prive"] if source.prive else m["public"]


def _details(g: str, s: Source) -> str:
    if g != "tache":
        return ""
    e = taches.etat(s)
    pr = f"{e['priorite']} ({e['priorite_libelle']})" if e["priorite_libelle"] else (e["priorite"] or "aucune")
    return f", statut {e['statut'] or 'aucun'}, priorité {pr}"


def _liens_media(tree: Tree, mid: str, sauf: str) -> list[str]:
    """Objets de l'arbre (hors la source ``sauf``) qui lient le média ``mid`` : personnes, familles, sources,
    événements et citations (par leur porteur)."""
    from .privacy import _citations

    out = []
    for coll in (tree.personnes, tree.familles, tree.sources):
        for oid, o in coll.items():
            if oid == sauf:
                continue
            cits = [c for cs in _citations(o) for c in cs]
            if mid in (getattr(o, "medias", None) or []) or any(mid in e.medias for e in getattr(o, "evenements", [])
                                                                 or []) or any(mid in c.medias for c in cits):
                out.append(oid)
    return out


def medias_publics(tree: Tree, sid: str, s: Source, g: str) -> list[str]:
    """#264 (limite laissée par #261) : un média garde sa propre confidentialité ; l'image d'un objet d'interface
    privé reste lisible d'un compte Invité (objet, fichier, vignette) si le média est public. Avertissement, avec
    l'opération qui le rend privé ; s'il est lié ailleurs, ces liens sont nommés (il y serait masqué aussi)."""
    out = []
    quoi = "Billet" if g == "billet" else "Tâche"
    for mid in s.medias:
        m = tree.medias.get(mid)
        if m is None or m.prive:
            continue
        ailleurs = _liens_media(tree, mid, sid)
        op = f'{{"op": "modifier_media", "id": "{mid}", "champs": {{"prive": true}}}}'
        out.append(f"{quoi} {sid} privé : son média {mid} est public ({INVITE} : objet, fichier et vignette). "
                   + (f"Le rendre privé : {op}." if not ailleurs else
                      f"Il est aussi lié à {', '.join(ailleurs)} : le rendre privé ({op}) le masquerait aussi là."))
    return out


def controler(before: Tree, after: Tree, genres: tuple[str, ...] = ("billet", "tache")
              ) -> tuple[list[str], list[str], list[str]]:
    """Objets d'interface créés ou modifiés par une proposition : (refus, avertissements, lignes de résumé)."""
    refus, avis, resume = [], [], []
    for sid, s in sorted(after.sources.items()):
        g = genre(s)
        if g not in genres:
            continue
        m = MESSAGES[g]
        avant = before.sources.get(sid)
        if avant is not None and avant.to_dict() == s.to_dict():
            continue
        meme = genre(avant) == g
        resume.append(m["resume"].format(sid=sid, titre=s.titre, visibilite=visibilite(s), details=_details(g, s)))
        if avant is not None and meme and avant.prive and not s.prive:
            avis.append(m["rendu_public"].format(sid=sid, invite=INVITE))
        elif not s.prive and not meme:
            avis.append(m["cree_public"].format(sid=sid, invite=INVITE))
        if avant is not None and not meme:
            from .tree.ops import _toutes_listes_citations

            n = sum(c.source == sid for _, cits in _toutes_listes_citations(after) for c in cits)
            if n:
                avis.append(m["devenu"].format(sid=sid, n=n))
        if not s.note and m["sans_texte"]:
            avis.append(m["sans_texte"].format(sid=sid))
        if s.prive:
            avis += medias_publics(after, sid, s, g)
        noms = billets.personnes_nommees(after, s, identifiants=True)
        if not noms:
            continue
        liste = " ; ".join(f"{n['id']} {n['nom']} ({n['raison']} ; {', '.join(n['mentions'])})" for n in noms)
        if s.prive:
            avis.append(m["nomme_prive"].format(sid=sid, liste=liste))
        else:
            refus.append(m["refus"].format(sid=sid, liste=liste, invite=INVITE))
    return refus, avis, resume
