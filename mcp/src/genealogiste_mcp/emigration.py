"""Fenêtre de départ d'un émigrant (#284), tirée des seuls faits de l'arbre.

Bornes : le dernier fait daté situé en France avant le premier fait daté situé à l'étranger, et ce premier fait.
Le pays de chaque fait vient de ``pays_du_lieu`` (#283) ; un fait non daté ou de pays inconnu n'est jamais une
borne (il est listé dans ``faits_ecartes``). Chaque borne cite le fait qui la fonde (type, date, lieu, uid,
statut de preuve, citations). Aucune date n'est déduite d'ailleurs que de l'arbre ; sans borne possible, la
fenêtre est dite indéterminée. Un événement générique (EVEN) situé à l'étranger donne une proposition de typage
à soumettre par ``arbre_proposer`` : rien n'est écrit, aucun type n'est choisi à la place de la source.
"""

from __future__ import annotations

from .evidence import assess_event, contradictions
from .fr_sources import next_source_hint
from .models import EVENT_LABELS, Event, Tree
from .normalize.dates import parse_date
from .normalize.pays import pays_du_lieu, pays_resume

FAITS_MIGRATION = ("EMIG", "IMMI", "NATU")
TYPES_PROPOSES = ("IMMI", "NATU", "RESI", "CENS", "MILI")
AVERTISSEMENT = ("Fenêtre tirée des seuls faits datés et situés de l'arbre : elle encadre le départ, elle ne le date "
                 "pas. Une borne fondée sur un fait non sourcé ou en hypothèse est fragile ; un fait antérieur "
                 "inconnu de l'arbre peut la déplacer.")


def _faits(tree: Tree, pid: str) -> list[tuple[Event, str, dict]]:
    """Événements de la personne et de ses unions, avec porteur et statut de preuve."""
    p = tree.person(pid)
    out = []
    conf = contradictions(p.evenements)
    out += [(e, pid, assess_event(e, tree, conf)) for e in p.evenements]
    for fam in tree.spouses_families(pid):
        fconf = contradictions(fam.evenements)
        out += [(e, fam.id, assess_event(e, tree, fconf)) for e in fam.evenements]
    return out


def _borne(e: Event, porteur: str, preuve: dict, pays: dict) -> dict:
    g = parse_date(e.date)
    refs = [c["reference"] for gr in preuve.get("groupes", []) for c in gr["citations"]]
    return {"fait": e.type, "libelle": EVENT_LABELS.get(e.type, e.type), "uid": e.uid, "porteur": porteur,
            "date": e.date, "date_texte": g.texte() if g else e.date, "lieu": e.lieu.nom if e.lieu else "",
            "pays": pays_resume(pays), "statut": preuve["statut"], "statut_libelle": preuve["libelle"],
            "sources_independantes": preuve.get("sources_independantes", 0), "citations": list(dict.fromkeys(refs)),
            "source_de_la_borne": "fait de l'arbre" + ("" if refs else " non sourcé")}


def _phrase(b: dict, quoi: str) -> str:
    return (f"{b['date_texte']} ({quoi} : {b['libelle']} à {b['lieu']}, {b['statut_libelle']}"
            + ("" if b["citations"] else ", aucune citation") + ")")


def _typage(tree: Tree, e: Event, porteur: str) -> dict:
    """Proposition de typage d'un événement générique : opérations prêtes par type, rien n'est appliqué."""
    ev = {"date": e.date, "lieu": e.lieu.nom if e.lieu else ""}
    for k in ("valeur", "type_detail", "age", "cause", "note"):
        if getattr(e, k):
            ev[k] = getattr(e, k)
    cits = []
    for c in e.citations:
        d = {k: v for k, v in c.to_dict().items() if k not in ("extra",) and v not in ("", None, [])}
        cits.append(d)
    if cits:
        ev["citations"] = cits
    else:
        ev.update(non_source=True, motif="événement générique retypé, sans citation dans l'arbre")
    if e.tags:
        ev["tags"] = list(e.tags)
    out = {"uid": e.uid, "porteur": porteur, "date": e.date, "lieu": ev["lieu"],
           "message": ("Événement générique sans type situé à l'étranger : si sa source le permet (arrivée, "
                       "naturalisation, résidence, recensement, enregistrement militaire…), le typer. Choisir le type "
                       "d'après la source, puis soumettre les opérations par arbre_proposer (diff, accord explicite "
                       "avant arbre_appliquer). Rien n'est modifié automatiquement."),
           "operations_par_type": {t: [{"op": "ajouter_evenement", "cible": porteur, "evenement": {"type": t, **ev}},
                                       {"op": "supprimer_evenement", "uid": e.uid}] for t in TYPES_PROPOSES}}
    if e.medias or e.associations:
        out["a_reporter"] = ("médias et intervenants de l'événement à reporter sur le nouvel événement "
                             "(ajouter_association, modifier_media lier_a) avant la suppression")
    return out


def fenetre_depart(tree: Tree, pid: str) -> dict | None:
    """Fenêtre de départ de France de ``pid`` ; ``None`` si l'arbre ne situe aucun fait de la personne à
    l'étranger et ne porte aucun fait de migration (rien à dire)."""
    faits = _faits(tree, pid)
    situes, ecartes, generiques = [], [], []
    a_l_etranger = False
    for e, porteur, preuve in faits:
        pays = pays_du_lieu(e.lieu) if e.lieu else None
        a_l_etranger = a_l_etranger or bool(pays and pays["france"] is False)
        g = parse_date(e.date) if e.date else None
        if pays and pays["france"] is False and e.type == "EVEN":
            generiques.append(_typage(tree, e, porteur))
        if pays is None or pays["france"] is None:
            if e.lieu or e.type in FAITS_MIGRATION:
                ecartes.append({"fait": e.type, "uid": e.uid, "date": e.date, "lieu": e.lieu.nom if e.lieu else "",
                                "raison": "lieu absent" if pays is None else "pays du lieu inconnu"})
            continue
        if not g:
            ecartes.append({"fait": e.type, "uid": e.uid, "date": e.date, "lieu": e.lieu.nom,
                            "raison": "fait non daté"})
            continue
        situes.append((g.interval, e, porteur, preuve, pays))
    etranger = sorted((x for x in situes if not x[4]["france"]), key=lambda x: x[0])
    if not a_l_etranger and not any(e.type in FAITS_MIGRATION for e, _, _ in faits):
        return None
    out: dict = {"personne": pid, "determinee": False, "debut": None, "fin": None}
    if not etranger:
        out["motif"] = "aucun fait daté situé hors de France : fenêtre indéterminée"
    else:
        (lo_a, _), ea, pa, prea, paysa = etranger[0]
        out["fin"] = _borne(ea, pa, prea, paysa)
        avant = [x for x in situes if x[4]["france"] and x[0][0] <= lo_a]
        apres = [x for x in situes if x[4]["france"] and x[0][0] > lo_a]
        if avant:
            _, ef, pf, pref, paysf = max(avant, key=lambda x: x[0])
            out["debut"] = _borne(ef, pf, pref, paysf)
            out["determinee"] = True
            debut = _phrase(out["debut"], "dernier fait situé en France")
            fin = _phrase(out["fin"], "premier fait situé à l'étranger")
            out["texte"] = f"Départ de France entre {debut} et {fin}."
            pistes = next_source_hint("EMIG", ef.date, ef.lieu)
            nom = paysa["nom"]
            for d in pistes:
                if d.get("versant") == "etranger" and nom:
                    d["pays_arrivee"] = pays_resume(paysa)
            out["pistes"] = pistes
        else:
            out["motif"] = ("aucun fait daté situé en France avant le premier fait situé à l'étranger : début de la "
                            "fenêtre indéterminé")
        if apres:
            out["faits_en_france_apres"] = [_borne(e, p, pr, py) for _, e, p, pr, py in apres]
            out["remarque"] = ("faits situés en France après le premier fait à l'étranger : retour ou séjours "
                               "multiples possibles ; la fenêtre ne couvre que le premier départ attesté")
    if "texte" not in out:
        out["texte"] = "Fenêtre de départ indéterminée : " + out["motif"] + "."
    if ecartes:
        out["faits_ecartes"] = ecartes
    if generiques:
        out["typage_propose"] = generiques
    out["avertissement"] = AVERTISSEMENT
    return out
