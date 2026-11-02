"""Contrôles de cohérence biologique et chronologique."""

from __future__ import annotations

from .models import Event, Person, Tree
from .normalize.dates import YEAR_DAYS, GenDate, age_interval, birth_from_age, compare, parse_age, parse_date

LIMITS = {
    "mere_min": 12, "mere_max": 55, "mere_alerte": 48,
    "pere_min": 14, "pere_max": 85, "pere_alerte": 70,
    "mariage_min": 12, "vie_max": 110, "vie_alerte": 100,
    "intervalle_naissances_jours": 270,
}


def _d(e: Event | None) -> GenDate | None:
    return parse_date(e.date) if e and e.date else None


def _first(p: Person, *types: str) -> Event | None:
    for t in types:
        for e in p.events(t):
            if e.date and parse_date(e.date):
                return e
    return None


def _issue(level: str, code: str, msg: str, pid: str, **kw) -> dict:
    return {"niveau": level, "code": code, "message": msg, "personne": pid, **kw}


def check_person(tree: Tree, pid: str) -> list[dict]:
    p = tree.person(pid)
    issues: list[dict] = []
    birth_e = _first(p, "BIRT", "CHR", "BAPM")
    death_e = _first(p, "DEAT", "BURI")
    birth, death = _d(birth_e), _d(death_e)
    label = p.label()

    # Naissance / baptême / décès / inhumation
    b, c = _d(_first(p, "BIRT")), _d(_first(p, "CHR", "BAPM"))
    if b and c and c.interval[1] < b.interval[0]:
        issues.append(_issue("erreur", "bapteme_avant_naissance", f"{label} : baptême avant la naissance", pid))
    d, bu = _d(_first(p, "DEAT")), _d(_first(p, "BURI"))
    if d and bu and bu.interval[1] < d.interval[0]:
        issues.append(_issue("erreur", "inhumation_avant_deces", f"{label} : inhumation avant le décès", pid))
    if birth and death:
        if death.interval[1] < birth.interval[0]:
            issues.append(_issue("erreur", "deces_avant_naissance", f"{label} : décès avant la naissance", pid))
        else:
            amin, amax = age_interval(birth, death)
            if amin > LIMITS["vie_max"]:
                issues.append(_issue("erreur", "longevite", f"{label} : âge au décès ≥ {amin:.0f} ans", pid))
            elif amin > LIMITS["vie_alerte"]:
                issues.append(_issue("alerte", "longevite", f"{label} : centenaire ({amin:.0f} ans) — à vérifier", pid))

    # Âges déclarés vs naissance enregistrée
    if birth:
        for e in p.evenements:
            parsed = parse_age(e.age) if e.age else None
            ed = _d(e)
            if parsed and ed:
                calc = birth_from_age(ed, *parsed)
                cmp = compare(calc, birth, tolerance_years=0)
                if not cmp["compatible"]:
                    issues.append(_issue(
                        "alerte", "age_declare",
                        f"{label} : âge déclaré {e.age} au {e.type} ({e.date}) ⇒ naissance {calc.texte()}, "
                        f"incompatible avec {birth_e.date}", pid, evenement=e.uid))

    # Parents
    for fam, link in tree.parents(pid):
        if link.filiation not in ("", "BIRTH"):
            continue
        for role, par_id in (("mere", fam.epouse), ("pere", fam.epoux)):
            if not par_id or par_id not in tree.personnes:
                continue
            par = tree.personnes[par_id]
            pb = _d(_first(par, "BIRT", "CHR", "BAPM"))
            pd_e = _first(par, "DEAT", "BURI")
            pd = _d(pd_e)
            if birth and pb:
                amin, amax = age_interval(pb, birth)
                lo, hi, warn = LIMITS[f"{role}_min"], LIMITS[f"{role}_max"], LIMITS[f"{role}_alerte"]
                if amax < lo:
                    issues.append(_issue("erreur", f"age_{role}", f"{par.label()} aurait au plus {amax:.0f} ans à la naissance de {label}", pid))
                elif amin > hi:
                    issues.append(_issue("erreur", f"age_{role}", f"{par.label()} aurait au moins {amin:.0f} ans à la naissance de {label}", pid))
                elif amin > warn:
                    issues.append(_issue("alerte", f"age_{role}", f"{par.label()} a {amin:.0f}–{amax:.0f} ans à la naissance de {label}", pid))
            if birth and pd:
                margin = 0 if role == "mere" else int(0.8 * YEAR_DAYS)  # posthume possible pour le père (~9 mois)
                if birth.interval[0] > pd.interval[1] + margin:
                    issues.append(_issue("erreur", f"naissance_apres_deces_{role}",
                                         f"{label} naît après le décès de {par.label()} ({pd_e.date})", pid))
    # Mariages
    for fam in tree.spouses_families(pid):
        for e in fam.evenements:
            if e.type != "MARR":
                continue
            md = _d(e)
            if not md:
                continue
            if birth:
                amin, amax = age_interval(birth, md)
                if amax < LIMITS["mariage_min"]:
                    issues.append(_issue("erreur", "mariage_precoce", f"{label} : mariage à moins de {LIMITS['mariage_min']} ans", pid))
            if death and md.interval[0] > death.interval[1]:
                issues.append(_issue("erreur", "mariage_apres_deces", f"{label} : mariage après le décès", pid))
    # Intervalles entre naissances des enfants d'une même mère
    if p.sexe == "F":
        births = []
        for fam in tree.spouses_families(pid):
            for link in fam.enfants:
                ch = tree.personnes.get(link.enfant)
                cb = _d(_first(ch, "BIRT", "CHR", "BAPM")) if ch else None
                if cb and cb.is_exact_day:
                    births.append((cb.interval[0], ch))
        births.sort(key=lambda x: x[0])
        for (j1, c1), (j2, c2) in zip(births, births[1:], strict=False):
            gap = j2 - j1
            if 2 < gap < LIMITS["intervalle_naissances_jours"]:
                issues.append(_issue("alerte", "intervalle_naissances",
                                     f"{c1.label()} et {c2.label()} : {gap} jours d'écart (même mère {label})", pid))
    return issues


def check_tree(tree: Tree) -> list[dict]:
    issues = []
    for pid in sorted(tree.personnes):
        issues += check_person(tree, pid)
    # références cassées
    for fam in tree.familles.values():
        for ref in [fam.epoux, fam.epouse] + [c.enfant for c in fam.enfants]:
            if ref and ref not in tree.personnes:
                issues.append(_issue("erreur", "reference_cassee", f"{fam.id} référence {ref} inexistant", ref))
    return issues
