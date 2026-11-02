"""Protection des personnes vivantes (RGPD) : présomption de vie si naissance estimée < 100 ans."""

from __future__ import annotations

from datetime import date

from .models import Person, Tree
from .normalize.dates import YEAR_DAYS, jdn_to_gregorian, parse_date

LIVING_YEARS = 100


def _mid_year(d: str) -> int | None:
    g = parse_date(d) if d else None
    if not g:
        return None
    lo, hi = g.interval
    return jdn_to_gregorian((lo + hi) // 2)[0]


def _min_year(d: str) -> int | None:
    g = parse_date(d) if d else None
    if not g:
        return None
    return jdn_to_gregorian(g.interval[0] + int(0 * YEAR_DAYS))[0]


def estimated_birth_year(tree: Tree, p: Person, _depth: int = 0) -> tuple[int | None, str]:
    for e in p.events("BIRT", "CHR", "BAPM"):
        y = _mid_year(e.date)
        if y:
            return y, f"{e.type} {e.date}"
    for fam in tree.spouses_families(p.id):
        for e in fam.evenements:
            if e.type == "MARR":
                y = _mid_year(e.date)
                if y:
                    return y - 25, f"mariage {e.date} - 25 ans"
        births = []
        for link in fam.enfants:
            c = tree.personnes.get(link.enfant)
            if c:
                for e in c.events("BIRT", "CHR", "BAPM"):
                    y = _mid_year(e.date)
                    if y:
                        births.append(y)
        if births:
            return min(births) - 25, f"naissance du premier enfant connu {min(births)} - 25 ans"
    for e in p.evenements:
        y = _mid_year(e.date)
        if y and e.type not in ("DEAT", "BURI", "CREM"):
            return y - 20, f"{e.type} {e.date} - 20 ans"
    if _depth == 0:
        father, mother = tree.father_mother(p.id)
        for par in (father, mother):
            if par and par in tree.personnes:
                y, why = estimated_birth_year(tree, tree.personnes[par], 1)
                if y:
                    return y + 25, f"parent né vers {y} + 25 ans"
    return None, "aucune date"


def is_living(tree: Tree, p: Person, today: date | None = None) -> dict:
    today = today or date.today()
    if p.vivant == "Y":
        return {"vivant": True, "raison": "marqué vivant manuellement"}
    if p.vivant == "N":
        return {"vivant": False, "raison": "marqué décédé manuellement"}
    if p.events("DEAT", "BURI", "CREM"):
        return {"vivant": False, "raison": "décès/inhumation enregistré"}
    y, why = estimated_birth_year(tree, p)
    if y is None:
        return {"vivant": True, "raison": "aucune date : présumé vivant par prudence"}
    living = today.year - y < LIVING_YEARS
    return {"vivant": living, "raison": f"naissance estimée {y} ({why}) ; seuil {LIVING_YEARS} ans",
            "naissance_estimee": y}


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
