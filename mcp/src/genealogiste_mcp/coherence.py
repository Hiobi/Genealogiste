"""Contrôles de cohérence biologique et chronologique."""

from __future__ import annotations

from . import marqueurs
from .models import Event, Family, Person, Tree
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
    issues += marqueurs_en_double_personne(p)  # #311
    return issues


# ---------------------------------------------------------------------------- marqueurs en double (#311)

CORRECTION_DOUBLONS = ("correction par proposition, jamais automatique : marquer_vivant (valeur à garder) ou "
                       "dedoublonner_marqueurs (garde la valeur lue) dans arbre_proposer, puis accord explicite")


def _valeur_lue(nom: str, porteur, nom_obj=None) -> str:
    if nom == marqueurs.VIVANT:
        return porteur.vivant
    if nom == "Genealogiste-UID":
        return getattr(nom_obj or porteur, "uid", "")
    if nom == marqueurs.STATUT:
        a = (nom_obj or porteur).statut_manuel
        return a.statut if a else ""
    return ""


_REGLES = {marqueurs.VIVANT: " (la plus protectrice)", marqueurs.STATUT: " (la plus grave)",
           "Genealogiste-UID": " (la première)"}


def _issues_doublons(label: str, extra: list, porteur_type: str, porteur, pid: str, nom_obj=None, **kw) -> list[dict]:
    """Une alerte par marqueur en double de ``extra`` : ``vivant_contradictoire`` (Genealogiste-Vivant de valeurs
    différentes), sinon ``marqueur_en_double``."""
    par_nom: dict[str, list[str]] = {}
    for x in marqueurs.doublons(extra, porteur_type):
        par_nom.setdefault(marqueurs.nom_doublon(x), []).append(x.get("value", ""))
    out = []
    for nom, vals in par_nom.items():
        lu = _valeur_lue(nom, porteur, nom_obj)
        lu_txt = f"valeur lue {lu!r}{_REGLES[nom]}" if nom in _REGLES else "une seule valeur lue"
        msg = (f"{label} : {nom} en double ({lu_txt} ; autre(s) : {', '.join(repr(v) for v in vals)}), laissé tel "
               f"quel ; {CORRECTION_DOUBLONS}")
        code = "vivant_contradictoire" if nom == marqueurs.VIVANT and any(v != lu for v in vals) \
            else "marqueur_en_double"
        out.append(_issue("alerte", code, msg, pid, marqueur=nom, **kw))
    return out


def marqueurs_en_double_personne(p: Person) -> list[dict]:
    """Marqueurs à valeur unique en double d'une personne, de ses noms et de ses événements (fusion native de Gramps,
    synchro, GEDCOM d'un autre outil) : signalés, jamais corrigés ici."""
    out = _issues_doublons(p.id, p.extra, "personne", p, p.id)
    for i, n in enumerate(p.noms):
        out += _issues_doublons(f"{p.id} nom {i}", n.extra, "nom", p, p.id, nom_obj=n)
    for e in p.evenements:
        out += _issues_doublons(f"{p.id} {e.type} {e.date}".strip(), e.extra, "evenement", e, p.id, nom_obj=e,
                                evenement=e.uid)
    return out


def marqueurs_en_double_famille(f: Family) -> list[dict]:
    out = _issues_doublons(f.id, f.extra, "famille", f, "", nom_obj=f, famille=f.id)
    for e in f.evenements:
        out += _issues_doublons(f"{f.id} {e.type} {e.date}".strip(), e.extra, "evenement", e, "", nom_obj=e,
                                famille=f.id, evenement=e.uid)
    return out


def marqueurs_en_double(tree: Tree) -> list[dict]:
    out = []
    for pid in sorted(tree.personnes):
        out += marqueurs_en_double_personne(tree.personnes[pid])
    for fid in sorted(tree.familles):
        out += marqueurs_en_double_famille(tree.familles[fid])
    return out


def lignes_doublons(avant: Tree, apres: Tree) -> list[str]:
    """Lignes de diff : marqueurs en double retirés ou ajoutés par une proposition (objet par objet)."""
    def etat(t: Tree) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for p in t.personnes.values():
            for x in (*marqueurs.doublons(p.extra, "personne"),
                      *(y for n in p.noms for y in marqueurs.doublons(n.extra, "nom"))):
                out.setdefault(p.id, []).append(f"{marqueurs.nom_doublon(x)} {x.get('value', '')!r}")
            for e in p.evenements:
                for x in marqueurs.doublons(e.extra, "evenement"):
                    out.setdefault(f"{p.id} {e.type}", []).append(f"{marqueurs.nom_doublon(x)} {x.get('value', '')!r}")
        for f in t.familles.values():
            for x in marqueurs.doublons(f.extra, "famille"):
                out.setdefault(f.id, []).append(f"{marqueurs.nom_doublon(x)} {x.get('value', '')!r}")
            for e in f.evenements:
                for x in marqueurs.doublons(e.extra, "evenement"):
                    out.setdefault(f"{f.id} {e.type}", []).append(f"{marqueurs.nom_doublon(x)} {x.get('value', '')!r}")
        return out
    a, b = etat(avant), etat(apres)
    lignes = []
    for k in sorted(set(a) | set(b)):
        retires = [v for v in a.get(k, []) if v not in b.get(k, [])]
        ajoutes = [v for v in b.get(k, []) if v not in a.get(k, [])]
        if retires:
            lignes.append(f"marqueurs en double {k} : retiré(s) {', '.join(retires)}")
        if ajoutes:
            lignes.append(f"marqueurs en double {k} : ajouté(s) {', '.join(ajoutes)}")
    return lignes


def check_tree(tree: Tree) -> list[dict]:
    issues = []
    for pid in sorted(tree.personnes):
        issues += check_person(tree, pid)
    for fid in sorted(tree.familles):
        issues += marqueurs_en_double_famille(tree.familles[fid])
    from .tree.integrite import dangling, duplicate_event_uids, parent_cycles

    for cyc in parent_cycles(tree):
        what = (f"{cyc[0]} est son propre parent" if len(cyc) == 1
                else "cycle de parenté : " + " → ".join(cyc + [cyc[0]]))
        issues.append(_issue("erreur", "cycle_parente", what, cyc[0]))
    for d in duplicate_event_uids(tree):
        issues.append(_issue("erreur", "uid_duplique", d, ""))
    for d in dangling(tree):  # références cassées
        issues.append(_issue("erreur", "reference_cassee", d, d.split(" ")[0]))
    return issues
