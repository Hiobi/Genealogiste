"""Statut de preuve : classification des citations, indépendance des sources, contradictions.

Règle (mode pondéré, par défaut) :
  - les citations sont regroupées par source originale indépendante : deux sources dérivées d'un même
    original (acte + table décennale, relevé d'association, index en ligne) ne comptent qu'une fois ;
  - poids d'un groupe = meilleure citation : 2 si source originale + information primaire + preuve
    directe, 1 sinon ; 0 pour une source composite (arbre en ligne : piste, pas preuve) ou une preuve négative ;
  - confirmé : ≥3 points ET ≥2 groupes indépendants ; probable : ≥2 points ; hypothèse : ≥1 point ;
  - contradictoire : valeurs incompatibles pour un même fait unique ; réfuté : forçage manuel justifié.
Mode strict (GENEALOGISTE_STRICT=1) : chaque groupe vaut 1 ; confirmé = 3 groupes, probable = 2, hypothèse = 1.
"""

from __future__ import annotations

import re

from .citations import format_citation
from .models import UNIQUE_EVENTS, Citation, Event, Tree
from .normalize.dates import compare, parse_date
from .normalize.places import place_similarity
from .statuts import LABELS

_ABREV = {"v": "vue", "vues": "vue", "view": "vue", "page": "p", "pages": "p", "pp": "p", "fo": "f", "folio": "f",
          "fol": "f", "acte": "n", "no": "n", "num": "n", "numero": "n"}


def _norm_page(p: str) -> str:
    """Localisation normalisée (#45) : casse, accents, ponctuation, abréviations (v., f°, n°) et zéros de tête
    sans effet : « Vue 01 », « vue 1 » et « v. 1 » désignent la même vue."""
    from .normalize.names import strip_accents

    t = strip_accents((p or "").lower()).replace("°", " ").replace("º", " ")
    t = re.sub(r"(\d+)", lambda m: f" {int(m.group(1))} ", t)
    words = [_ABREV.get(w, w) for w in re.split(r"[^a-z0-9]+", t) if w]
    words = [w for i, w in enumerate(words) if i == 0 or w != words[i - 1]]  # « acte n° 36 » = « acte 36 »
    return " ".join(words)


def root_source(tree: Tree, sid: str) -> str:
    """Source originale ultime : chaîne « dérivée de » suivie récursivement (cycle : arrêt)."""
    seen = set()
    while sid in tree.sources and tree.sources[sid].original and sid not in seen:
        seen.add(sid)
        sid = tree.sources[sid].original
    return sid


def citation_weight(c: Citation, tree: Tree, strict: bool = False) -> float:
    """Poids d'une citation. Règle de métier : on ne compte que ce qu'on a vu.

    - acte « non vu » (cité d'après une autre source) : 0, c'est une piste ;
    - acte vu seulement par un index/relevé/transcription : traité comme une source dérivée (1 au plus).
    """
    src = tree.sources.get(c.source)
    stype = c.type_source if c.type_source != "indeterminee" else (src.type_source if src else "indeterminee")
    if c.consultation == "non_vu" or stype == "composite" or c.preuve == "negative":
        return 0.0
    if c.consultation in ("index", "transcription") and stype == "originale":
        stype = "derivee"
    if strict:
        return 1.0
    if stype == "originale" and c.information == "primaire" and c.preuve == "directe":
        return 2.0
    return 1.0


def group_citations(citations: list[Citation], tree: Tree) -> dict[str, list[Citation]]:
    """Regroupe par source originale indépendante."""
    groups: dict[str, list[Citation]] = {}
    derived: list[tuple[str, Citation]] = []
    for c in citations:
        src = tree.sources.get(c.source)
        if src and src.original:
            derived.append((root_source(tree, c.source), c))
        else:
            groups.setdefault(f"{c.source}|{_norm_page(c.page)}", []).append(c)
    for orig, c in derived:
        target = next((k for k in groups if k.split("|")[0] == orig), None)
        groups.setdefault(target or f"{orig}|*", []).append(c)
    return groups


def assess_citations(citations: list[Citation], tree: Tree, strict: bool = False) -> dict:
    groups = group_citations(citations, tree)
    points = 0.0
    indep = 0
    details = []
    for key, cits in groups.items():
        w = max(citation_weight(c, tree, strict) for c in cits)
        points += w
        if w > 0:
            indep += 1
        details.append({
            "groupe": key.split("|")[0],
            "poids": w,
            "citations": [
                {"source": c.source, "titre": tree.sources[c.source].titre if c.source in tree.sources else "?",
                 "page": c.page, "type_source": c.type_source, "information": c.information,
                 "preuve": c.preuve, "qualite": c.qualite, "vu": c.consultation or "non précisé",
                 "reference": format_citation(tree, c)}
                for c in cits
            ],
        })
    if strict:
        statut = "confirme" if indep >= 3 else "probable" if indep >= 2 else "hypothese" if indep >= 1 else "non_source"
    else:
        statut = ("confirme" if points >= 3 and indep >= 2 else "probable" if points >= 2
                  else "hypothese" if points >= 1 else "non_source")
    pistes = [d for d in details if d["poids"] == 0]
    out = {"statut": statut, "points": points, "sources_independantes": indep, "groupes": details,
           "pistes_non_probantes": len(pistes)}
    unseen = [c for c in citations if c.consultation == "non_vu"]
    if unseen:
        out["actes_a_voir"] = [format_citation(tree, c, False) for c in unseen]
    if citations and not any(c.consultation for c in citations):
        out["avertissement"] = "Préciser pour chaque citation ce qui a été vu (original, image, index, non vu)."
    return out


def events_conflict(a: Event, b: Event) -> list[str]:
    reasons = []
    da, db = parse_date(a.date), parse_date(b.date)
    if da and db:
        cmp = compare(da, db, tolerance_years=0)
        if not cmp["compatible"]:
            reasons.append(f"dates incompatibles ({a.date} / {b.date}, écart {cmp['ecart_annees']} an(s))")
        elif da.is_exact_day and db.is_exact_day and not cmp["identique"]:
            reasons.append(f"jours différents ({a.date} / {b.date})")
    if a.lieu and b.lieu and a.lieu.nom and b.lieu.nom:
        ps = place_similarity(a.lieu.nom, b.lieu.nom)
        if ps["score"] < 0.6:
            reasons.append(f"lieux différents ({a.lieu.nom} / {b.lieu.nom})")
    return reasons


def contradictions(events: list[Event]) -> dict[str, list[str]]:
    """uid -> raisons, pour les faits uniques ayant plusieurs valeurs incompatibles."""
    out: dict[str, list[str]] = {}
    by_type: dict[str, list[Event]] = {}
    for e in events:
        if e.type in UNIQUE_EVENTS and not (e.statut_manuel and e.statut_manuel.statut == "refute"):
            by_type.setdefault(e.type, []).append(e)
    for evs in by_type.values():
        for i, a in enumerate(evs):
            for b in evs[i + 1:]:
                r = events_conflict(a, b)
                if r:
                    out.setdefault(a.uid, []).extend(r)
                    out.setdefault(b.uid, []).extend(r)
    return out


def assess_event(e: Event, tree: Tree, conflicts: dict[str, list[str]], strict: bool = False) -> dict:
    res = assess_citations(e.citations, tree, strict)
    if e.uid in conflicts:
        res["statut"] = "contradictoire"
        res["contradictions"] = sorted(set(conflicts[e.uid]))
    if e.statut_manuel and e.statut_manuel.statut:
        res["statut"] = e.statut_manuel.statut
        res["justification_manuelle"] = e.statut_manuel.justification
    res["libelle"] = LABELS.get(res["statut"], res["statut"])
    return res


def assess_person(tree: Tree, pid: str, strict: bool = False) -> list[dict]:
    from .fr_sources import next_source_hint

    p = tree.person(pid)
    facts = []
    for i, n in enumerate(p.noms):
        r = assess_citations(n.citations, tree, strict)
        if n.statut_manuel and n.statut_manuel.statut:
            r["statut"] = n.statut_manuel.statut
        r["libelle"] = LABELS[r["statut"]]
        facts.append({"fait": "nom", "index": i, "valeur": n.complet, **r})
    conflicts = contradictions(p.evenements)
    for e in p.evenements:
        r = assess_event(e, tree, conflicts, strict)
        fact = {"fait": e.type, "uid": e.uid, "date": e.date, "lieu": e.lieu.nom if e.lieu else "",
                "valeur": e.valeur, **r}
        if e.associations:
            fact["associations"] = [a.libelle() for a in e.associations]
        if r["statut"] not in ("confirme", "refute"):
            fact["prochaine_source"] = next_source_hint(e.type, e.date, e.lieu.nom if e.lieu else "")
        facts.append(fact)
    for fam, link in tree.parents(pid):
        r = assess_citations(link.citations, tree, strict)
        if link.statut_manuel and link.statut_manuel.statut:
            r["statut"] = link.statut_manuel.statut
        r["libelle"] = LABELS[r["statut"]]
        fact = {"fait": "filiation", "famille": fam.id, "pere": fam.epoux, "mere": fam.epouse, **r}
        if r["statut"] != "confirme":
            birth = next(iter(p.events("BIRT", "CHR", "BAPM")), None)
            fact["prochaine_source"] = next_source_hint("FILIATION", birth.date if birth else "", "")
        facts.append(fact)
    for fam in tree.spouses_families(pid):
        fconf = contradictions(fam.evenements)
        for e in fam.evenements:
            r = assess_event(e, tree, fconf, strict)
            fact = {"fait": e.type, "famille": fam.id, "uid": e.uid, "date": e.date,
                    "lieu": e.lieu.nom if e.lieu else "", **r}
            if e.associations:
                fact["associations"] = [a.libelle() for a in e.associations]
            if r["statut"] not in ("confirme", "refute"):
                fact["prochaine_source"] = next_source_hint(e.type, e.date, e.lieu.nom if e.lieu else "")
            facts.append(fact)
    return facts
