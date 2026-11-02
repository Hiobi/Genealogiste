"""Rapport de preuve (proof argument) : trame pré-remplie à partir de l'arbre et du journal."""

from __future__ import annotations

from datetime import date

from ..coherence import check_person
from ..evidence import LABELS, assess_person
from ..journal import Journal
from ..models import EVENT_LABELS, Tree


def proof_report(tree: Tree, journal: Journal, pid: str, fait: str = "", strict: bool = False) -> str:
    p = tree.person(pid)
    facts = [f for f in assess_person(tree, pid, strict)
             if not fait or f["fait"] == fait.upper() or f["fait"] == fait or f.get("uid") == fait]
    label = EVENT_LABELS.get(fait.upper(), fait) if fait else "identité et faits"
    L = [f"# Rapport de preuve — {label} de {p.nom_principal.complet} [{pid}]", "",
         f"*Établi le {date.today().strftime('%d/%m/%Y')} — méthode : Genealogical Proof Standard.*", "",
         "## 1. Question de recherche", "",
         f"> {label.capitalize()} de {p.nom_principal.complet} : *(préciser la question : quand, où, "
         "qui sont les parents… et pourquoi elle se pose)*", "",
         "## 2. Pièces examinées", ""]
    for f in facts:
        head = EVENT_LABELS.get(f["fait"], f["fait"])
        L.append(f"### {head.capitalize()} {f.get('date', '')} {f.get('lieu', '')}".rstrip())
        L.append("")
        if not f.get("groupes"):
            L.append("- *Aucune pièce : fait non sourcé.*")
        for g in f.get("groupes", []):
            for c in g["citations"]:
                L.append(f"- {c['reference']} — poids du groupe {g['poids']:g}")
        for a in f.get("associations", []):
            L.append(f"- Intervenant : {a}")
        L.append("")
    neg = [e for e in journal.entries(personne=pid, limite=500) if e["statut"] in ("negatif", "erreur")]
    L += ["## 3. Recherches négatives et limites", ""]
    if neg:
        L += [f"- {e['date'][:10]} — {e['source']} ({e['operation']}) : {e['statut']} ; paramètres "
              f"{', '.join(f'{k}={v}' for k, v in e['parametres'].items())}" for e in neg]
    else:
        L.append("- *Aucune recherche négative tracée : la recherche est-elle raisonnablement exhaustive ?*")
    L += ["", "## 4. Analyse et corrélation", "",
          "*Pour chaque pièce : qui a fourni l'information, était-il témoin direct, à quelle distance "
          "de l'événement, avec quel intérêt ? Les pièces sont-elles indépendantes ?*", ""]
    for f in facts:
        L.append(f"- {EVENT_LABELS.get(f['fait'], f['fait'])} : {LABELS[f['statut']]} "
                 f"({f['sources_independantes']} source(s) indépendante(s), {f['points']:g} pt)")
    contra = [f for f in facts if f.get("contradictions")]
    issues = check_person(tree, pid)
    L += ["", "## 5. Contradictions et homonymes", ""]
    if contra or issues:
        L += [f"- {EVENT_LABELS.get(f['fait'], f['fait'])} : {'; '.join(f['contradictions'])}" for f in contra]
        L += [f"- Cohérence ({i['niveau']}) : {i['message']}" for i in issues]
        L.append("- *Pour chaque contradiction : versions, sources, argument retenu.*")
    else:
        L.append("- Aucune contradiction détectée. *Homonymes recherchés (même nom, même lieu, ±5 ans) : préciser.*")
    L += ["", "## 6. Conclusion", "",
          "*Rédiger la conclusion et son niveau de certitude (confirmé, probable, hypothèse), en "
          "reprenant les arguments décisifs.*", "", "## 7. Suite de la recherche", ""]
    for f in facts:
        for s in (f.get("prochaine_source") or [])[:2]:
            L.append(f"- {EVENT_LABELS.get(f['fait'], f['fait'])} : {s['source']} [{s['cote_typique']}]")
    return "\n".join(L) + "\n"
