"""Fiche individuelle Markdown et analyse des lacunes."""

from __future__ import annotations

from ..coherence import check_person
from ..evidence import assess_person
from ..fr_sources import next_source_hint
from ..models import EVENT_LABELS, Tree
from ..normalize.dates import parse_date
from ..privacy import is_living
from ..statuts import ICONS, LABELS

LABEL = LABELS


def _fmt_date(d: str) -> str:
    g = parse_date(d) if d else None
    if not g:
        return d or ""
    out = g.texte()
    if g.start.calendar != "GREGORIAN" and g.qualifier is None:
        out += f" ({g.to_dict().get('equivalent_gregorien', '')})"
    return out


def fiche_markdown(tree: Tree, pid: str, strict: bool = False, mask_living: bool = True) -> str:
    p = tree.person(pid)
    living = is_living(tree, p)
    if mask_living and (living["vivant"] or p.prive):
        raison = living["raison"] if living["vivant"] else "personne marquée privée"
        return f"# Vivant [{p.id}] (données masquées)\n\nDonnées masquées (RGPD) : {raison}.\n"
    facts = assess_person(tree, pid, strict)
    lines = [f"# {p.nom_principal.complet} [{p.id}]", ""]
    sexe = {"M": "masculin", "F": "féminin"}.get(p.sexe, "inconnu")
    lines.append(f"- **Sexe** : {sexe}")
    for n in p.noms[1:]:
        lines.append(f"- **Autre nom** : {n.complet}")
    father, mother = tree.father_mother(pid)
    for role, x in (("Père", father), ("Mère", mother)):
        if x and x in tree.personnes:
            lines.append(f"- **{role}** : {tree.personnes[x].label()}")
    lines += ["", "## Faits et statut de preuve", "", "| Fait | Date | Lieu | Statut | Sources indépendantes |",
              "|---|---|---|---|---|"]
    for f in facts:
        kind = f["fait"]
        label = {"nom": "Nom", "filiation": "Filiation"}.get(kind, EVENT_LABELS.get(kind, kind).capitalize())
        val = f.get("valeur") or ""
        if kind == "filiation":
            val = f"{f.get('pere') or '?'} × {f.get('mere') or '?'}"
        label = f"{label} {val}".strip() if kind in ("nom", "OCCU", "filiation", "EVEN") else label
        lines.append(f"| {label} | {_fmt_date(f.get('date', ''))} | {f.get('lieu', '')} | "
                     f"{ICONS[f['statut']]} {LABEL[f['statut']]} | {f['sources_independantes']} ({f['points']} pt) |")
    contra = [f for f in facts if f.get("contradictions")]
    if contra:
        lines += ["", "## Contradictions", ""]
        for f in contra:
            lines.append(f"- {EVENT_LABELS.get(f['fait'], f['fait'])} : " + "; ".join(f["contradictions"]))
    unions = tree.spouses_families(pid)
    if unions:
        lines += ["", "## Unions et enfants", ""]
        for fam in unions:
            sp = fam.epouse if fam.epoux == pid else fam.epoux
            marr = next((e for e in fam.evenements if e.type == "MARR"), None)
            sp_label = tree.personnes[sp].label() if sp in tree.personnes else "conjoint inconnu"
            lines.append(f"- **{fam.id}** avec {sp_label}" + (f", mariage {_fmt_date(marr.date)}"
                                                              f"{' à ' + marr.lieu.nom if marr.lieu else ''}" if marr else ""))
            for link in fam.enfants:
                if link.enfant in tree.personnes:
                    lines.append(f"  - {tree.personnes[link.enfant].label()}")
    issues = check_person(tree, pid)
    if issues:
        lines += ["", "## Alertes de cohérence", ""]
        lines += [f"- **{i['niveau']}** : {i['message']}" for i in issues]
    refs = []
    for f in facts:
        for g in f.get("groupes", []):
            for c in g["citations"]:
                refs.append(c["reference"])
    if refs:
        lines += ["", "## Sources citées", ""]
        lines += [f"{i}. {r}" for i, r in enumerate(dict.fromkeys(refs), 1)]
    assos = [(f, a) for f in facts for a in f.get("associations", [])]
    if assos or p.associations:
        lines += ["", "## Témoins, parrains et intervenants", ""]
        lines += [f"- {EVENT_LABELS.get(f['fait'], f['fait'])} {f.get('date', '')} — {a}" for f, a in assos]
        lines += [f"- {a.libelle()}" for a in p.associations]
    unseen = [x for f in facts for x in f.get("actes_a_voir", [])]
    if unseen:
        lines += ["", "## Actes cités mais non vus", ""]
        lines += [f"- {u}" for u in dict.fromkeys(unseen)]
    todo = [f for f in facts if f.get("prochaine_source")]
    if todo:
        lines += ["", "## Prochaines sources à consulter", ""]
        for f in todo:
            first = f["prochaine_source"][0]
            lines.append(f"- {EVENT_LABELS.get(f['fait'], f['fait'])} ({LABEL[f['statut']]}) → {first['source']} "
                         f"[{first['cote_typique']}]")
    for n in p.notes:
        if not n.startswith("@"):
            lines += ["", "## Notes", "", n]
            break
    return "\n".join(lines) + "\n"


ESSENTIAL = [("BIRT", ("BIRT", "CHR", "BAPM")), ("DEAT", ("DEAT", "BURI")), ("MARR", None)]


def gaps(tree: Tree, pid: str, strict: bool = False) -> dict:
    """Faits manquants ou faibles d'une personne + plan de recherche priorisé."""
    p = tree.person(pid)
    facts = assess_person(tree, pid, strict)
    plan = []
    prio = {"non_source": 1, "contradictoire": 0, "hypothese": 2, "probable": 3}

    def ctx_date():
        for e in p.events("BIRT", "CHR", "BAPM"):
            return e.date
        return ""

    living = is_living(tree, p)["vivant"]
    for code, types in ESSENTIAL:
        if code == "MARR":
            has = any(any(e.type == "MARR" for e in f.evenements) for f in tree.spouses_families(pid))
            if tree.spouses_families(pid) and not has:
                plan.append({"priorite": 1, "fait": "MARR", "probleme": "union sans mariage enregistré",
                             "sources": next_source_hint("MARR", ctx_date())})
            continue
        if code == "DEAT" and living:
            continue
        if not p.events(*types):
            plan.append({"priorite": 1, "fait": code, "probleme": "fait manquant",
                         "sources": next_source_hint(code, ctx_date())})
    father, mother = tree.father_mother(pid)
    if not (father and mother):
        plan.append({"priorite": 1, "fait": "FILIATION", "probleme": "parent(s) inconnu(s)",
                     "sources": next_source_hint("FILIATION", ctx_date())})
    for f in facts:
        if f["statut"] in prio:
            plan.append({"priorite": prio[f["statut"]], "fait": f["fait"], "date": f.get("date", ""),
                         "probleme": f"statut {LABEL[f['statut']]}"
                                     + (f" : {'; '.join(f['contradictions'])}" if f.get("contradictions") else ""),
                         "sources": f.get("prochaine_source") or next_source_hint(f["fait"], f.get("date", ""))})
    for i in check_person(tree, pid):
        plan.append({"priorite": 0 if i["niveau"] == "erreur" else 2, "fait": i["code"], "probleme": i["message"],
                     "sources": []})
    plan.sort(key=lambda x: x["priorite"])
    return {"personne": p.label(), "nb_actions": len(plan), "plan": plan}


def tree_gaps(tree: Tree, strict: bool = False, limit: int = 30) -> dict:
    rows = []
    for pid in sorted(tree.personnes):
        if is_living(tree, tree.personnes[pid])["vivant"]:
            continue
        g = gaps(tree, pid, strict)
        top = [x for x in g["plan"] if x["priorite"] <= 1]
        if top:
            rows.append({"personne": g["personne"], "urgent": len(top), "total": g["nb_actions"],
                         "premiere_action": top[0]["probleme"]})
    rows.sort(key=lambda r: -r["urgent"])
    return {"personnes_a_traiter": len(rows), "classement": rows[:limit]}
