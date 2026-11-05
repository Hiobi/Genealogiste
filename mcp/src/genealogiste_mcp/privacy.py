"""Protection des personnes vivantes (RGPD) : présumé vivant tant qu'une naissance il y a moins de 100 ans reste
possible (borne haute de l'intervalle de naissance), sauf décès non réfuté ou marquage manuel."""

from __future__ import annotations

from datetime import date

from .models import Person, Tree
from .normalize.dates import jdn_to_gregorian, parse_date

LIVING_YEARS = 100


DEATH_EVENTS = ("DEAT", "BURI", "CREM")
BIRTH_EVENTS = ("BIRT", "CHR", "BAPM")
# Écarts prudents : on borne la naissance par le HAUT (naissance la plus récente encore possible).
AGE_MIN_UNION = 15  # mariage ou premier enfant : naissance au plus tard 15 ans avant
AGE_MAX_PARENT = 50  # parent : enfant né au plus tard 50 ans après lui


def _refute(e) -> bool:
    return bool(e.statut_manuel and e.statut_manuel.statut == "refute")


def _years(d: str) -> tuple[int, int] | None:
    """Intervalle [année min, année max] d'une date GEDCOM (BEF, AFT, BET, ABT… conservés)."""
    g = parse_date(d) if d else None
    if not g or not g.start:
        return None
    lo, hi = g.interval
    return jdn_to_gregorian(lo)[0], jdn_to_gregorian(hi)[0]


def birth_bounds(tree: Tree, p: Person, _depth: int = 0) -> tuple[tuple[int, int] | None, str]:
    """Intervalle de naissance possible : (année min, année max), avec sa justification.

    La borne haute (naissance la plus récente encore possible) décide de la présomption de vie : on ne la réduit
    jamais au milieu d'un intervalle incertain. Les faits réfutés sont ignorés."""
    for e in p.events(*BIRTH_EVENTS):
        y = None if _refute(e) else _years(e.date)
        if y:
            return y, f"{e.type} {e.date}"
    bornes: list[tuple[int, str]] = []
    for fam in tree.spouses_families(p.id):
        for e in fam.evenements:
            y = None if _refute(e) else _years(e.date)
            if e.type == "MARR" and y:
                bornes.append((y[1] - AGE_MIN_UNION, f"mariage {e.date} - {AGE_MIN_UNION} ans"))
        for link in fam.enfants:
            c = tree.personnes.get(link.enfant)
            for e in c.events(*BIRTH_EVENTS) if c else []:
                y = None if _refute(e) else _years(e.date)
                if y:
                    bornes.append((y[1] - AGE_MIN_UNION, f"naissance d'un enfant {e.date} - {AGE_MIN_UNION} ans"))
    for e in p.evenements:
        y = None if _refute(e) else _years(e.date)
        if y and e.type not in DEATH_EVENTS:
            bornes.append((y[1], f"{e.type} {e.date}"))
    if bornes:
        hi, why = min(bornes)
        return (hi - 100, hi), f"au plus tard {hi} ({why})"
    if _depth == 0:
        father, mother = tree.father_mother(p.id)
        for par in (father, mother):
            if par and par in tree.personnes:
                y, why = birth_bounds(tree, tree.personnes[par], 1)
                if y:
                    return (y[0], y[1] + AGE_MAX_PARENT), f"parent né au plus tard en {y[1]} + {AGE_MAX_PARENT} ans"
    return None, "aucune date"


def estimated_birth_year(tree: Tree, p: Person) -> tuple[int | None, str]:
    """Année de naissance la plus récente possible (borne haute prudente)."""
    y, why = birth_bounds(tree, p)
    return (y[1] if y else None), why


def is_living(tree: Tree, p: Person, today: date | None = None) -> dict:
    today = today or date.today()
    deaths = p.events(*DEATH_EVENTS)
    actifs = [e for e in deaths if not _refute(e)]
    contradictions = []
    if p.vivant == "Y" and actifs:
        contradictions.append("marqué vivant mais un décès ou une inhumation est enregistré")
    if deaths and not actifs:
        contradictions.append("décès enregistré mais réfuté : ignoré pour la présomption de vie")
    extra = {"contradictions": contradictions} if contradictions else {}
    if p.vivant == "Y":
        return {"vivant": True, "raison": "marqué vivant manuellement", **extra}
    if p.vivant == "N":
        return {"vivant": False, "raison": "marqué décédé manuellement", **extra}
    if actifs:
        return {"vivant": False, "raison": "décès/inhumation enregistré", **extra}
    y, why = birth_bounds(tree, p)
    if y is None:
        return {"vivant": True, "raison": "aucune date : présumé vivant par prudence", **extra}
    living = today.year - y[1] < LIVING_YEARS
    return {"vivant": living, "raison": f"naissance au plus tard {y[1]} ({why}) ; seuil {LIVING_YEARS} ans",
            "naissance_estimee": y[1], "naissance_intervalle": list(y), **extra}


def living_ids(tree: Tree, today: date | None = None) -> set[str]:
    return {pid for pid, p in tree.personnes.items() if is_living(tree, p, today)["vivant"]}


def mask_tree(tree: Tree, today: date | None = None) -> tuple[Tree, set[str]]:
    """Copie de l'arbre où les vivants sont réduits à « Vivant » sans date ni lieu."""
    import copy

    from .models import Name

    t = copy.deepcopy(tree)
    living = living_ids(t, today)
    for pid in living:
        p = t.personnes[pid]
        surname = p.nom_principal.nom
        p.noms = [Name(prenoms="Vivant", nom=surname)]
        p.evenements = []
        p.citations = []
        p.notes = []
        p.medias = []
        p.extra = []
    for fam in t.familles.values():
        if fam.epoux in living or fam.epouse in living:
            fam.evenements = []
    return t, living


# ============================================================================ sorties réseau

def _tokens(*textes: str) -> set[str]:
    from .normalize.names import basic

    return {t for s in textes for t in basic(s or "").replace("'", " ").replace("-", " ").split() if len(t) > 1}


def living_index(tree: Tree, today: date | None = None) -> list[dict]:
    """Vivants de l'arbre réduits à ce qui sert au rapprochement : noms, prénoms, intervalle de naissance."""
    out = []
    for pid, p in tree.personnes.items():
        st = is_living(tree, p, today)
        if not st["vivant"]:
            continue
        noms = [_tokens(n.nom) for n in p.noms if _tokens(n.nom)]
        prenoms = _tokens(*(n.prenoms for n in p.noms))
        if noms and prenoms:
            out.append({"id": pid, "noms": noms, "prenoms": prenoms,
                        "naissance": st.get("naissance_intervalle")})
    return out


def _compatible(naissance: list[int] | None, ne_vers: str) -> bool:
    """La date de naissance demandée peut-elle désigner ce vivant ? (sans date de part ou d'autre : oui)."""
    y = _years(ne_vers) if ne_vers else None
    if not y or not naissance:
        return True
    return y[0] <= naissance[1] + 2 and y[1] >= naissance[0] - 2


def _names_match(person: dict, mots: set[str]) -> bool:
    if not any(nom <= mots for nom in person["noms"]):
        return False
    reste = mots - set().union(*person["noms"])
    return bool(person["prenoms"] & reste)


def external_guard(tree: Tree, personne: str = "", nom: str = "", prenom: str = "", ne_vers: str = "",
                   texte: str = "", today: date | None = None, index: list[dict] | None = None) -> dict | None:
    """Politique unique des sorties réseau (RGPD) : refus (dict) ou None si la requête peut partir.

    - identifiant fourni : il doit exister dans l'arbre et désigner une personne non présumée vivante ;
    - noms ou texte libre : refus s'ils désignent un vivant de l'arbre (nom et prénom présents), sauf naissance
      demandée incompatible avec la sienne, ou requête portant sur la personne décédée désignée par l'identifiant.
    """
    cible = None
    if personne:
        if personne not in tree.personnes:
            return {"refus": f"Identifiant inconnu dans l'arbre : {personne}. Aucune donnée n'est envoyée à un "
                             "service externe ; vérifier l'identifiant (arbre_recherche)."}
        st = is_living(tree, tree.personnes[personne], today)
        if st["vivant"]:
            return {"refus": f"{personne} est présumé(e) vivant(e) ({st['raison']}) : aucune donnée n'est envoyée "
                             "à un service externe (RGPD). Marquer _VIVANT N si la personne est décédée."}
        p = tree.personnes[personne]
        cible = {"noms": [_tokens(n.nom) for n in p.noms if _tokens(n.nom)],
                 "prenoms": _tokens(*(n.prenoms for n in p.noms))}
    mots = _tokens(nom, prenom, texte)
    if not mots:
        return None
    if cible and cible["noms"] and _names_match(cible, mots):
        return None
    for v in living_index(tree, today) if index is None else index:
        if _names_match(v, mots) and _compatible(v["naissance"], ne_vers):
            return {"refus": f"La recherche désigne une personne présumée vivante de l'arbre ({v['id']}) : aucune "
                             "donnée n'est envoyée à un service externe (RGPD). Pour un homonyme décédé, préciser "
                             "ne_vers ou l'identifiant de la personne recherchée (personne).",
                    "vivant": v["id"]}
    return None
