"""Tâches de Gramps Web (#263) : une source portant l'étiquette ``ToDo``, avec les attributs de source ``Status``
et ``Priority`` et une description en première note (type ``To Do``, étiquetée ``ToDo``).

Correspondance relevée dans le frontend gramps-web (v26.11.0 ``8df68202`` et v26.11.3 ``20c7655d``,
``src/taskConstants.js``, ``src/views/GrampsjsViewTasks.js``, ``GrampsjsViewNewTask.js``,
``src/components/GrampsjsTask.js``) :

- liste : ``GET /api/sources/?rules={"rules":[{"name":"HasTag","values":["ToDo"]}]}&sort=-gramps_id&extend=tag_list``
  (nom d'étiquette exact, casse comprise), puis tri local par statut (Open, In Progress, Blocked, autre, Done)
  et priorité ;
- attributs ``SrcAttribute`` à type personnalisé (chaîne) ``Status`` ∈ Open | In Progress | Blocked | Done (un
  autre statut, venu par exemple de Gramps Desktop, est affiché tel quel) et ``Priority`` en chaîne : l'interface
  écrit ``"1"`` (High), ``"5"`` (Medium), ``"9"`` (Low) ; toute valeur numérique < 5 est haute, > 5 basse, une
  valeur absente ou non numérique n'a pas de priorité ;
- création : ``Priority "5"`` puis ``Status "Open"`` ; la note de description est de type ``To Do``, porte les
  étiquettes de la tâche et sa confidentialité ;
- changement de statut ou de priorité (une tâche ou plusieurs, en lot) : ``PUT /api/sources/<handle>`` de
  l'objet complet, l'attribut retiré puis remis en fin de liste.

Gramps Desktop n'a pas de vue Tâches : son gramplet « To Do » liste les NOTES de type ``To Do`` ; la description
d'une tâche y figure donc (rattachée à sa source), sans statut ni priorité.

Une tâche n'est pas une source de preuve : jamais comptée comme preuve, pas de fiche dans les notes de recherche
(voir :mod:`objets_interface`). Tout dépend de ``GENEALOGISTE_GRAMPS_TACHES`` : désactivé (défaut), aucune
source n'est lue ni écrite comme tâche (``Source.tache`` reste vide).
"""

from __future__ import annotations

import math
import re

from .enquetes import MOTIF_CONTEXTE_SEUL, est_contexte_seul
from .models import Source, Tree

TODO = "ToDo"  # nom exact de l'étiquette (sensible à la casse : tag.name === 'ToDo')
TYPE_NOTE = "To Do"  # NoteType.TODO (25) de Gramps
STATUS, PRIORITY = "Status", "Priority"  # types (chaînes personnalisées) des attributs de source
STATUTS = ("Open", "In Progress", "Blocked", "Done")
STATUT_DEFAUT, PRIORITE_DEFAUT = "Open", "5"  # valeurs posées par l'interface à la création
PRIORITES = {"haute": "1", "moyenne": "5", "basse": "9"}  # valeurs écrites par l'interface (High, Medium, Low)
_ALIAS_STATUT = {"ouverte": "Open", "a_faire": "Open", "en_cours": "In Progress", "bloquee": "Blocked",
                 "bloque": "Blocked", "terminee": "Done", "faite": "Done", "close": "Done"}
LIBELLES_STATUT = {"Open": "ouverte", "In Progress": "en cours", "Blocked": "bloquée", "Done": "terminée"}
DESACTIVE = ("tâches de Gramps Web désactivées : GENEALOGISTE_GRAMPS_TACHES=true (et GENEALOGISTE_BACKEND=gramps) "
             "pour lire et écrire les tâches")

# Référence d'une tâche créée depuis une enquête (#263) : dernière ligne de sa description.
_REF = re.compile(r"^Enquête Genealogiste : ([a-z0-9][a-z0-9_-]{0,79}) · ([pt]\d+)\s*$", re.M)
ELEMENT = re.compile(r"^[pt]\d+$")


class TacheError(ValueError):
    pass


def est_tache(source: Source | None) -> bool:
    """Vrai pour une source lue ou écrite comme tâche (étiquette ToDo et réglage activé)."""
    return bool(source) and bool(source.tache)


def statut(valeur) -> str:
    """Statut Gramps depuis une valeur Gramps (Open…) ou un alias français (ouverte, en_cours, bloquee, terminee)."""
    if not isinstance(valeur, str) or not valeur.strip():
        raise TacheError(f"statut : {' | '.join(STATUTS)} (ou ouverte, en_cours, bloquee, terminee)")
    v = valeur.strip()
    for s in STATUTS:
        if v.casefold() == s.casefold():
            return s
    if v.casefold() in _ALIAS_STATUT:
        return _ALIAS_STATUT[v.casefold()]
    raise TacheError(f"statut {valeur!r} : {' | '.join(STATUTS)} (ou ouverte, en_cours, bloquee, terminee)")


def priorite(valeur) -> str:
    """Valeur de l'attribut Priority : haute | moyenne | basse (1, 5, 9 comme l'interface) ou un entier de 0 à 9."""
    if isinstance(valeur, str) and valeur.strip().casefold() in PRIORITES:
        return PRIORITES[valeur.strip().casefold()]
    if isinstance(valeur, bool):
        raise TacheError("priorite : haute | moyenne | basse, ou entier de 0 à 9")
    try:
        n = int(str(valeur).strip())
    except ValueError:
        n = -1
    if not 0 <= n <= 9:
        raise TacheError(f"priorite {valeur!r} : haute | moyenne | basse, ou entier de 0 à 9")
    return str(n)


def libelle_priorite(valeur: str) -> str:
    """haute | moyenne | basse | "" : règle de l'interface (``priorityLabel`` : < 5 haute, 5 moyenne, > 5 basse ;
    absente ou non numérique : sans priorité)."""
    try:
        n = float((valeur or "").strip())
    except ValueError:
        return ""
    if math.isnan(n):
        return ""
    return "haute" if n < 5 else "moyenne" if n == 5 else "basse"


def ouverte(st: str) -> bool:
    return st != "Done"


def etat(source: Source) -> dict:
    """Statut et priorité d'une tâche, pour la lecture (arbre_recherche, enquêtes)."""
    st, pr = source.tache.get("statut", ""), source.tache.get("priorite", "")
    return {"statut": st, "statut_libelle": LIBELLES_STATUT.get(st, st), "priorite": pr,
            "priorite_libelle": libelle_priorite(pr), "ouverte": ouverte(st)}


def ligne_reference(enquete: str, element: str) -> str:
    return f"Enquête Genealogiste : {enquete} · {element}"


def reference(texte: str) -> tuple[str, str] | None:
    """(enquête, élément) de la ligne de référence d'une description, ou None."""
    m = _REF.search(texte or "")
    return (m.group(1), m.group(2)) if m else None


def priorite_lacune(score: int) -> str:
    """Priorité Gramps d'une lacune depuis sa priorité de plan (``export.fiche.gaps``) : 0 (contradiction, erreur)
    et 1 (fait manquant, non sourcé, filiation inconnue) -> haute (1) ; 2 (hypothèse, avertissement) -> moyenne
    (5) ; 3 et plus (probable) -> basse (9)."""
    return PRIORITES["haute"] if score <= 1 else PRIORITES["moyenne"] if score == 2 else PRIORITES["basse"]


def normaliser(tree: Tree, avant: Tree) -> None:
    """Après les opérations, réglage activé : une source portant ToDo est une tâche (statut et priorité vides si
    l'étiquette vient d'être posée sur une source existante : rien n'est inventé) ; une source qui perd ToDo cesse
    d'en être une (ses attributs Status et Priority restent dans Gramps, intacts)."""
    for sid, s in tree.sources.items():
        if TODO in s.tags and not s.tache:
            s.tache = dict((avant.sources.get(sid) or Source(id=sid)).tache) or {"statut": "", "priorite": ""}
        elif TODO not in s.tags and s.tache:
            s.tache = {}


def lignes(avant: Tree, apres: Tree) -> list[str]:
    """Diff concis des tâches (statut, priorité) : invisibles dans le GEDCOM, une ligne par tâche créée ou dont le
    statut ou la priorité change (« tâche S5 : statut Open → Done »)."""
    out = []
    for sid, s in sorted(apres.sources.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if not est_tache(s):
            continue
        a = (avant.sources.get(sid) or Source(id=sid)).tache
        parts = []
        for cle, nom in (("statut", "statut"), ("priorite", "priorité")):
            v0, v1 = a.get(cle, ""), s.tache.get(cle, "")
            if v0 != v1 or not a:
                lib = f" ({libelle_priorite(v1)})" if cle == "priorite" and libelle_priorite(v1) else ""
                parts.append(f"{nom} {v0 or '∅'} → {v1 or '∅'}{lib}" if a else f"{nom} {v1 or '∅'}{lib}")
        if parts:
            out.append(f"tâche {sid}{'' if a else ' (créée)'} : " + ", ".join(parts))
    return out


# ---------------------------------------------------------------------------- enquêtes (a_faire <-> tâches)

PISTE_FERMEE = ("trouve", "negatif")  # enquetes.TERMINES
_STATUT_PISTE = {"a_faire": "Open", "en_cours": "In Progress", "bloque": "Blocked", "manuel": "Open"}


def _elements(e: dict) -> list[tuple[str, str, dict]]:
    """(id, nature, élément) des pistes et tâches manuelles d'une enquête."""
    return ([(p["id"], "piste", p) for p in e.get("pistes", []) if p.get("id")]
            + [(t["id"], "tache_manuelle", t) for t in e.get("taches_manuelles", []) if t.get("id")])


def _ouvert(nature: str, el: dict) -> bool:
    st = el.get("statut", "a_faire")
    return st == "a_faire" if nature == "tache_manuelle" else st not in PISTE_FERMEE


def _liens(e: dict, tree: Tree) -> dict[str, tuple[str, str]]:
    """élément -> (identifiant de tâche, origine du lien : « memorise » dans l'état, ou « reference » lue dans la
    description d'une tâche de l'arbre)."""
    out = {}
    for sid, s in sorted(tree.sources.items(), key=lambda kv: (len(kv[0]), kv[0])):
        ref = reference(s.note) if est_tache(s) else None
        if ref and ref[0] == e.get("id"):
            out.setdefault(ref[1], (sid, "reference"))
    for eid, _, el in _elements(e):
        if el.get("tache_gramps"):
            out[eid] = (el["tache_gramps"], "memorise")
    return out


def correspondance(e: dict, tree: Tree) -> dict:
    """Pistes et tâches manuelles d'une enquête <-> tâches de Gramps Web, en lecture seule : liens (mémorisés dans
    l'état ou lus dans la ligne de référence des descriptions), écarts ouvert/terminé signalés avec, pour chaque
    sens, l'appel à faire après accord (jamais exécuté ici), liens à mémoriser, éléments ouverts sans tâche."""
    eid = e.get("id", "")
    liens = _liens(e, tree)
    liees, ecarts, a_memoriser, non_liees, contexte_seul = [], [], [], [], []
    for xid, nature, el in _elements(e):
        ouvert = _ouvert(nature, el)
        cle = "piste" if nature == "piste" else "tache"
        if nature == "piste" and est_contexte_seul(el) and xid not in liens:
            contexte_seul.append(xid)  # #325 : jamais une tâche, donc jamais « à lier »
            continue
        if xid not in liens:
            if ouvert:
                non_liees.append(xid)
            continue
        sid, origine = liens[xid]
        s = tree.sources.get(sid)
        ligne = {"element": xid, "nature": nature, "statut_enquete": el.get("statut", "a_faire"), "tache": sid,
                 "lien": origine}
        if origine == "reference":
            a_memoriser.append({"outil": "enquete_noter",
                                "parametres": {"enquete": eid, cle: {"id": xid, "tache_gramps": sid}}})
        if not est_tache(s):
            ligne["constat"] = (f"{sid} introuvable dans l'arbre" if s is None else
                                f"{sid} n'est plus une tâche (étiquette ToDo retirée)")
            ecarts.append({**ligne, "vers_enquete": {"outil": "enquete_noter", "parametres": {
                "enquete": eid, cle: {"id": xid, "tache_gramps": ""}}}})
            liees.append(ligne)
            continue
        ligne.update(titre=s.titre, **{f"{k}_gramps" if k in ("statut", "priorite") else k: v
                                       for k, v in etat(s).items() if k != "ouverte"})
        liees.append(ligne)
        if ouverte(s.tache.get("statut", "")) == ouvert:
            continue
        if ouvert:  # terminée dans Gramps Web, ouverte dans l'enquête
            st = "faite" if nature == "tache_manuelle" else "<trouve|negatif>"
            ecarts.append({**ligne, "constat": f"tâche {sid} terminée (Done) dans Gramps Web, {nature} {xid} "
                                               f"encore ouverte dans l'enquête",
                           "vers_enquete": {"outil": "enquete_noter",
                                            "parametres": {"enquete": eid, cle: {"id": xid, "statut": st}}},
                           "vers_gramps": {"op": "modifier_tache", "id": sid, "statut": "Open"}})
        else:
            ecarts.append({**ligne, "constat": f"{nature} {xid} terminée dans l'enquête "
                                               f"({el.get('statut')}), tâche {sid} encore ouverte dans Gramps Web",
                           "vers_gramps": {"op": "modifier_tache", "id": sid, "statut": "Done"},
                           "vers_enquete": {"outil": "enquete_noter", "parametres": {
                               "enquete": eid, cle: {"id": xid, "statut": "a_faire" if nature == "tache_manuelle"
                                                     else "en_cours"}}}})
    out = {"liees": liees, "ecarts": ecarts, "non_liees": non_liees}
    if contexte_seul:
        out["contexte_seul"] = {"elements": contexte_seul, "motif": MOTIF_CONTEXTE_SEUL}
    if a_memoriser:
        out["a_memoriser"] = a_memoriser
    if ecarts:
        out["consigne"] = ("Écarts signalés, rien n'est modifié : montrer chaque écart à l'utilisateur et lui faire "
                           "choisir le sens. Vers Gramps Web : vers_gramps dans arbre_proposer (diff, accord, "
                           "arbre_appliquer) ; vers l'enquête : vers_enquete (enquete_noter) après son accord.")
    return out


def _court(texte: str, n: int = 90) -> str:
    t = " ".join((texte or "").split())
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def operations_enquete(e: dict, tree: Tree, elements: list[str] | None = None) -> dict:
    """Opérations ``ajouter_tache`` prêtes pour arbre_proposer : une par piste ou tâche manuelle ouverte sans
    tâche liée (ou par élément demandé), privée, priorité moyenne, statut dérivé de l'élément, personnes de
    l'enquête nommées, ligne de référence de l'enquête. Une piste « contexte seul » ne donne jamais d'opération,
    même demandée par ``elements`` : elle est rendue dans ``refuses`` avec le motif (#325). Rien n'est écrit."""
    eid = e.get("id", "")
    liens = _liens(e, tree)
    voulus = set(elements or [])
    ops, ignores, refuses = [], [], []
    personnes = [p for p in e.get("personnes", []) if p in tree.personnes]
    for xid, nature, el in _elements(e):
        if voulus and xid not in voulus:
            continue
        if nature == "piste" and est_contexte_seul(el):  # #325 : verrou, avec ou sans sélection explicite
            refuses.append({"element": xid, "motif": MOTIF_CONTEXTE_SEUL})
            continue
        if xid in liens:
            ignores.append(f"{xid} : déjà liée à {liens[xid][0]}")
            continue
        if not _ouvert(nature, el):
            ignores.append(f"{xid} : terminée dans l'enquête")
            continue
        if nature == "piste":
            titre = el.get("question", "")
            lignes = [titre] + [f"Hypothèse : {h}" for h in el.get("hypotheses", [])] + [
                f"À consulter : {s.get('libelle', '')}" for s in el.get("sources", []) if not s.get("fait")]
            statut_g = _STATUT_PISTE.get(el.get("statut", "a_faire"), "Open")
        else:
            titre = el.get("description", "")
            lignes = [titre] + [f"{k.capitalize()} : {el[k]}" for k in ("service", "url") if el.get(k)]
            statut_g = "Open"
        op = {"op": "ajouter_tache", "ref": xid, "titre": _court(titre) or f"Enquête {eid} : {xid}",
              "description": "\n".join(x for x in lignes if x), "statut": statut_g, "priorite": "moyenne",
              "enquete": eid, "element": xid}
        if personnes:
            op["personnes"] = personnes
        ops.append(op)
    inconnus = sorted(voulus - {x for x, _, _ in _elements(e)})
    out = {"operations": ops, "titre": f"Tâches Gramps Web de l'enquête {eid}",
           "justification": f"Plan de recherche de l'enquête « {e.get('sujet', '')} » ({eid}) rendu visible dans "
                            "la vue Tâches de Gramps Web (tâches privées).",
           "apres_application": ("Pour chaque tâche créée, mémoriser le lien : enquete_noter(enquete, piste|tache="
                                 "{id: <élément>, tache_gramps: references_creees[<élément>]})."),
           "ignores": ignores}
    if refuses:
        out["refuses"] = refuses
    if inconnus:
        out["inconnus"] = inconnus
    return out


def operations_lacunes(plan: dict, pid: str) -> list[dict]:
    """Opérations ``ajouter_tache`` prêtes pour arbre_proposer depuis le plan de lacunes d'une personne
    (``export.fiche.gaps``) : une par action, priorité Gramps depuis la priorité de plan (:func:`priorite_lacune`),
    privée, personne nommée. Rien n'est écrit."""
    ops = []
    for i, a in enumerate(plan.get("plan", []), 1):
        fait = a.get("fait", "")
        titre = _court(f"{plan.get('personne', pid)} — {fait} : {a.get('probleme', '')}")
        sources = a.get("sources") or []
        lignes = [f"{fait} : {a.get('probleme', '')}" + (f" ({a['date']})" if a.get("date") else "")]
        for s in sources[:5]:
            if isinstance(s, dict):
                lignes.append(f"À consulter : {s.get('source', '')}"
                              + (f" ({s['cote_typique']})" if s.get("cote_typique") else ""))
            elif s:
                lignes.append(f"À consulter : {s}")
        lignes.append(f"Priorité de lacune : {a.get('priorite')} (0 = la plus urgente)")
        ops.append({"op": "ajouter_tache", "ref": f"lacune{i}", "titre": titre, "description": "\n".join(lignes),
                    "priorite": priorite_lacune(int(a.get("priorite", 3))), "personnes": [pid]})
    return ops
