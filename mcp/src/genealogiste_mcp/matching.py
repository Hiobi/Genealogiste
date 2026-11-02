"""Score de correspondance explicite entre deux personnes (détection d'homonymes).

Aucune fusion n'est jamais déclenchée par ce module : il produit une analyse argumentée.
"""

from __future__ import annotations

from .models import Person, Tree
from .normalize.dates import compare, parse_date
from .normalize.names import given_similarity, surname_similarity
from .normalize.places import place_similarity

WEIGHTS = {
    "nom": 20, "prenoms": 20, "sexe": 5, "naissance_date": 20, "naissance_lieu": 10,
    "deces_date": 10, "deces_lieu": 5, "pere": 5, "mere": 5,
}


def profile_from_person(tree: Tree, pid: str) -> dict:
    p = tree.person(pid)
    n = p.nom_principal

    def ev(*types):
        for t in types:
            for e in p.events(t):
                return {"date": e.date, "lieu": e.lieu.nom if e.lieu else ""}
        return {}

    father, mother = tree.father_mother(pid)

    def nm(x):
        if x and x in tree.personnes:
            q = tree.personnes[x].nom_principal
            return {"prenoms": q.prenoms, "nom": q.nom}
        return None

    return {
        "id": pid, "prenoms": n.prenoms, "nom": n.nom, "sexe": p.sexe,
        "naissance": ev("BIRT", "CHR", "BAPM"), "deces": ev("DEAT", "BURI"),
        "pere": nm(father), "mere": nm(mother),
    }


def _date_score(a: str, b: str) -> tuple[float, str, bool] | None:
    da, db = parse_date(a or ""), parse_date(b or "")
    if not da or not db:
        return None
    c = compare(da, db)
    if c["identique"]:
        return 1.0, "dates identiques", False
    if c["chevauchement"]:
        return (0.9 if da.is_exact_day or db.is_exact_day else 0.8), "dates compatibles", False
    if c["compatible"]:
        return 0.6, f"écart de {c['ecart_annees']} an(s), dans la tolérance de ±2 ans", False
    return 0.0, f"dates incompatibles (écart {c['ecart_annees']} ans)", c["ecart_annees"] > 2


def compare_profiles(a: dict, b: dict) -> dict:
    details = []
    contradictions = []
    total = 0.0
    weight_used = 0.0

    def add(key: str, score: float, reason: str):
        nonlocal total, weight_used
        w = WEIGHTS[key]
        total += w * score
        weight_used += w
        details.append({"critere": key, "score": round(score, 3), "poids": w, "raison": reason})

    if a.get("nom") and b.get("nom"):
        s = surname_similarity(a["nom"], b["nom"])
        add("nom", s["score"], s["raison"])
    if a.get("prenoms") and b.get("prenoms"):
        s = given_similarity(a["prenoms"], b["prenoms"])
        add("prenoms", s["score"], s["raison"])
    sa, sb = a.get("sexe", "U"), b.get("sexe", "U")
    if sa in ("M", "F") and sb in ("M", "F"):
        add("sexe", 1.0 if sa == sb else 0.0, "même sexe" if sa == sb else "sexes différents")
        if sa != sb:
            contradictions.append("sexes différents")
    for ev in ("naissance", "deces"):
        ea, eb = a.get(ev) or {}, b.get(ev) or {}
        ds = _date_score(ea.get("date"), eb.get("date"))
        if ds:
            add(f"{ev}_date", ds[0], ds[1])
            if ds[2]:
                contradictions.append(f"{ev} : {ds[1]}")
        if ea.get("lieu") and eb.get("lieu"):
            ps = place_similarity(ea["lieu"], eb["lieu"])
            add(f"{ev}_lieu", ps["score"], ps["raison"])
    for par in ("pere", "mere"):
        pa, pb = a.get(par), b.get(par)
        if pa and pb:
            g = given_similarity(pa.get("prenoms", ""), pb.get("prenoms", ""))["score"]
            s = surname_similarity(pa.get("nom", ""), pb.get("nom", ""))["score"] if pa.get("nom") and pb.get("nom") else g
            sc = (g + s) / 2
            add(par, sc, f"{par} : {pa.get('prenoms', '')} {pa.get('nom', '')} / {pb.get('prenoms', '')} {pb.get('nom', '')}")
            if sc < 0.6:
                contradictions.append(f"{par} différent(e)")
    if not weight_used:
        return {"score": 0, "verdict": "indéterminé", "details": [], "contradictions": [],
                "avertissement": "Aucune donnée comparable."}
    score = 100 * total / weight_used
    coverage = weight_used / sum(WEIGHTS.values())
    # pénalités fortes : une contradiction franche l'emporte sur les similitudes
    if contradictions:
        score = min(score, 35 if len(contradictions) == 1 else 15)
    # peu de critères comparés => on ne peut pas conclure à l'identité
    if coverage < 0.5:
        score = min(score, 70)
    score = round(score, 1)
    if contradictions:
        verdict = "homonymes probables (contradiction)"
    elif score >= 85:
        verdict = "même personne probable — à confirmer par une source reliant les deux"
    elif score >= 60:
        verdict = "à examiner : indices insuffisants pour conclure"
    else:
        verdict = "homonymes probables"
    return {
        "score": score,
        "verdict": verdict,
        "couverture_criteres": round(coverage, 2),
        "details": details,
        "contradictions": contradictions,
        "regle": "Jamais de fusion automatique : toute fusion passe par une proposition validée par l'utilisateur.",
    }


def compare_persons(tree: Tree, id1: str, id2: str) -> dict:
    res = compare_profiles(profile_from_person(tree, id1), profile_from_person(tree, id2))
    res["personnes"] = [tree.person(id1).label(), tree.person(id2).label()]
    return res


def score_candidate(query: dict, candidate: dict) -> float:
    return compare_profiles(query, candidate)["score"]


def person_from_profile_dict(d: dict) -> dict:  # pour symétrie d'API
    return d


__all__ = ["compare_profiles", "compare_persons", "profile_from_person", "score_candidate", "Person"]
