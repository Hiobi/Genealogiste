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
  avertissement ;
- contexte historique (#291) : un billet créé, dont le texte change ou qui devient public, et dont le texte a une
  section « Contexte », n'est proposé que si ``contexte_verifier`` le déclare conforme pour la personne donnée
  (``personne`` d'``ajouter_billet``, d'``ajouter_source`` ou de ``modifier_source``) ; sinon refus, avec le rapport
  (:func:`controler_contexte`). Un texte sans section « Contexte » n'est pas contrôlé.
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


# ------------------------------------------------------------------------------------ contexte historique (#291)

RUBRIQUES_CONTEXTE = ("phrases_sans_reference", "references_non_consultees", "hors_portee", "causalites",
                      "formulations")
_MAX_SIGNALEMENTS = 5  # par rubrique, dans le message de refus (le rapport complet : contexte_verifier)


def texte_markdown(tree: Tree, source: Source, bruts: dict[str, str] | None = None) -> str:
    """Texte du billet tel que ``contexte_verifier`` le lit : le Markdown donné à l'opération (``bruts`` : texte
    converti -> texte d'origine, ``format_texte: "markdown"``), sinon le texte de la note. Un billet relu de
    Gramps Web a perdu ses astérisques (le gras est une mise en forme) : une ligne isolée qui porte le nom d'une
    section lue par le contrôle (« Contexte », « Hypothèses », « Questions ouvertes », « Notes et sources »…) est
    rétablie en titre (``**Contexte**``)."""
    from .contexte.verifier import _GRAS, _TITRE, _genre

    note = source.note or ""
    lignes = (bruts.get(note, note) if bruts else note).split("\n")
    for i, ligne in enumerate(lignes):
        nu = ligne.strip()
        isolee = (i == 0 or not lignes[i - 1].strip()) and (i + 1 == len(lignes) or not lignes[i + 1].strip())
        if (nu and isolee and len(nu) <= 60 and not _TITRE.match(ligne) and not _GRAS.match(ligne)
                and _genre(nu.rstrip(" :")) != "autre"):
            lignes[i] = f"**{nu.rstrip(' :')}**"
    return "\n".join(lignes)


def a_section_contexte(texte: str) -> bool:
    from .contexte.verifier import analyser

    return analyser(texte).sections_contexte > 0


def resume_rapport(rapport: dict) -> str:
    """Rapport de ``contexte_verifier`` en une ligne par rubrique signalée (phrase et motif)."""
    lignes = []
    for r in RUBRIQUES_CONTEXTE:
        items = rapport.get(r) or []
        if not items:
            continue
        details = []
        for x in items[:_MAX_SIGNALEMENTS]:
            phrase = " ".join((x.get("phrase") or "").split())
            if len(phrase) > 160:
                phrase = phrase[:157] + "…"
            motif = x.get("motif") or ("phrase de contexte sans appel de note" if r == "phrases_sans_reference"
                                       else "")
            precision = x.get("identifiant") or x.get("marqueur") or x.get("connecteur") or ""
            details.append(f"« {phrase} »" + (f" [{precision}]" if precision else "")
                           + (f" ({motif})" if motif else ""))
        if len(items) > _MAX_SIGNALEMENTS:
            details.append(f"… et {len(items) - _MAX_SIGNALEMENTS} autre(s)")
        lignes.append(f"{r} ({len(items)}) : " + " | ".join(details))
    return " ; ".join(lignes)


def controler_contexte(before: Tree, after: Tree, personnes: dict[str, str], registre,
                       bruts: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    """#291 : (refus, lignes de résumé) pour les billets créés, dont le texte change ou qui deviennent publics.
    ``personnes`` : billet -> personne donnée par l'opération ; ``registre`` : registre des références consultées
    (absent : un billet à section « Contexte » est refusé, le contrôle ne pouvant pas être fait)."""
    refus, resume = [], []
    for sid, s in sorted(after.sources.items()):
        if not est_billet(s):
            continue
        avant = before.sources.get(sid)
        if (avant is not None and est_billet(avant) and (avant.note or "") == (s.note or "")
                and not (avant.prive and not s.prive)):
            continue
        texte = texte_markdown(after, s, bruts)
        if not a_section_contexte(texte):
            continue
        pid = personnes.get(sid, "")
        if not pid:
            refus.append(
                f"Billet {sid} refusé : son texte a une section « Contexte » et aucune personne n'est donnée pour "
                "le contrôler. Donner « personne » (id de l'individu du billet) sur ajouter_billet (ou ajouter_source), "
                "ou sur modifier_source pour un billet existant : la proposition n'est faite que si contexte_verifier "
                "rend conforme: true.")
            continue
        if registre is None:
            refus.append(f"Billet {sid} refusé : registre des références consultées indisponible, la section "
                         "« Contexte » ne peut pas être contrôlée.")
            continue
        from .contexte.local import ContexteInvalide
        from .contexte.verifier import verifier

        try:
            rapport = verifier(texte, after, pid, registre)
        except ContexteInvalide as exc:
            refus.append(f"Billet {sid} refusé : contrôle de la section « Contexte » impossible ({exc}).")
            continue
        if not rapport["conforme"]:
            refus.append(
                f"Billet {sid} refusé : section « Contexte » non conforme (contexte_verifier, personne {pid}, "
                f"conforme: false). {resume_rapport(rapport)}. Corriger le texte en retirant la phrase ou en la "
                "documentant par une référence consultée (jamais en inventant une référence), puis reproposer.")
            continue
        m = rapport["mesures"]
        resume.append(f"Billet {sid} : section « Contexte » contrôlée (contexte_verifier, personne {pid}) : conforme, "
                      f"{m['phrases_contexte']} phrase(s) de contexte, {m['references_consultees']} référence(s) "
                      "consultée(s)")
    return refus, resume
