"""Protection des personnes vivantes (RGPD) : présumé vivant tant qu'une naissance il y a moins de 100 ans reste
possible (borne haute de l'intervalle de naissance), sauf décès non réfuté ou marquage manuel."""

from __future__ import annotations

import copy
import re
from dataclasses import fields, is_dataclass
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


def hidden_ids(tree: Tree, today: date | None = None) -> set[str]:
    """Personnes jamais publiées : présumées vivantes ou marquées privées (#37)."""
    return living_ids(tree, today) | {pid for pid, p in tree.personnes.items() if p.prive}


# ============================================================================ publication (#33, #37)

_ACCENTS = {"a": "aàâäáã", "e": "eéèêë", "i": "iîïíì", "o": "oôöóò", "u": "uùûüú", "c": "cç", "y": "yÿ",
            "n": "nñ"}


def _fuzzy(mot: str) -> str:
    from .normalize.names import strip_accents

    out = []
    for ch in mot:
        base = strip_accents(ch).lower()
        if base in _ACCENTS:
            out.append(f"[{_ACCENTS[base]}]")
        elif ch in " -'’":
            out.append(r"[\s\-'’]+")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def identifying_patterns(tree: Tree, ids: set[str]) -> list[re.Pattern]:
    """Chaînes identifiantes des personnes masquées : prénom et nom accolés, dans les deux ordres
    (« Alice Secret », « SECRET Alice », « Alice /Secret/ », « Secret, Alice »), sans accents ni casse."""
    sep = r"[\s/,]+"
    pats = set()
    for pid in ids:
        p = tree.personnes.get(pid)
        for n in p.noms if p else []:
            nom = n.nom.strip()
            if len(nom) < 2:
                continue
            prenoms = {x for x in [n.prenoms.strip(), *n.prenoms.split()] if len(x) > 1}
            for g in prenoms:
                pats.add(rf"(?<!\w)/?{_fuzzy(g)}{sep}{_fuzzy(nom)}/?(?!\w)")
                pats.add(rf"(?<!\w)/?{_fuzzy(nom)}/?{sep}{_fuzzy(g)}(?!\w)")
    return [re.compile(x, re.I) for x in sorted(pats, key=len, reverse=True)]


def residues(text: str, patterns: list[re.Pattern]) -> list[str]:
    """Chaînes identifiantes encore présentes dans un contenu publié (doit être vide)."""
    return sorted({m.group(0) for p in patterns for m in p.finditer(text or "")})


def _scrub(obj, patterns: list[re.Pattern]):
    """Remplace les chaînes identifiantes par « Vivant » dans tous les textes d'un objet (récursif)."""
    if isinstance(obj, str):
        for p in patterns:
            obj = p.sub("Vivant", obj)
        return obj
    if isinstance(obj, list):
        return [_scrub(x, patterns) for x in obj]
    if isinstance(obj, dict):
        return {k: _scrub(v, patterns) for k, v in obj.items()}
    if is_dataclass(obj):
        for f in fields(obj):
            setattr(obj, f.name, _scrub(getattr(obj, f.name), patterns))
    return obj


def _citations(obj) -> list:
    """Toutes les listes de citations d'un objet (noms, événements, associations, filiations)."""
    out = []
    if hasattr(obj, "citations"):
        out.append(obj.citations)
    for attr in ("noms", "evenements", "associations", "enfants"):
        for x in getattr(obj, attr, []) or []:
            out += _citations(x)
    return out


def publication(tree: Tree, today: date | None = None) -> tuple[Tree, set[str], dict]:
    """Projection de publication : copie de l'arbre sans aucune donnée identifiante d'un vivant ni d'objet privé.

    - personnes présumées vivantes ou marquées privées : réduites à « Vivant », sans nom, fait, note ni média ;
    - objets partagés (sources, médias, notes) liés à au moins une personne masquée, ou marqués privés : retirés
      avec toutes leurs références (y compris chez les défunts) ; liés seulement à des défunts : conservés ;
    - événements et citations privés, associations désignant une personne masquée : retirés ;
    - enregistrements non interprétés (contenu indécidable) : exclus ;
    - passe sur tous les textes : « Prénom Nom » d'une personne masquée remplacé par « Vivant ».
    Renvoie (arbre publié, personnes masquées, rapport)."""
    from .models import Name

    t = copy.deepcopy(tree)
    hidden = hidden_ids(t, today)
    patterns = identifying_patterns(tree, hidden)
    sources = {s for s, x in t.sources.items() if x.prive}
    medias = {m for m, x in t.medias.items() if x.prive}
    notes = set(t.notes_privees)

    def sensibles(owner) -> None:
        for cits in _citations(owner):
            for c in cits:
                sources.add(c.source)
                medias.update(c.medias)
        medias.update(getattr(owner, "medias", []) or [])
        notes.update(n.strip("@") for n in getattr(owner, "notes", []) or [] if n.startswith("@") and n.endswith("@"))

    for pid in hidden:
        sensibles(t.personnes[pid])
    familles = [f for f in t.familles.values() if f.prive or f.epoux in hidden or f.epouse in hidden]
    for f in familles:
        sensibles(f)
    for f in t.familles.values():
        for link in f.enfants:
            if link.enfant in hidden:
                sensibles(link)
    for cits in (c for m in t.medias.values() for c in [m.citations]):
        for c in cits:
            if c.source in sources:
                medias.update(c.medias)

    # personnes et familles masquées
    for pid in hidden:
        p = t.personnes[pid]
        p.noms = [Name(prenoms="Vivant")]
        p.evenements, p.citations, p.notes, p.medias, p.extra, p.associations = [], [], [], [], [], []
    for f in familles:
        f.evenements, f.citations, f.notes, f.extra, f.statut_manuel = [], [], [], [], None
    for f in t.familles.values():
        for link in f.enfants:
            if link.enfant in hidden:
                link.citations, link.statut_manuel = [], None

    # retrait des objets sensibles et de leurs références, partout
    def garder_cit(c) -> bool:
        if c.prive or c.source in sources:
            return False
        c.medias = [m for m in c.medias if m not in medias]
        return True

    def nettoyer(owner) -> None:
        for attr in ("citations",):
            if hasattr(owner, attr):
                setattr(owner, attr, [c for c in getattr(owner, attr) if garder_cit(c)])
        if hasattr(owner, "associations"):
            owner.associations = [a for a in owner.associations if a.personne not in hidden
                                  and not residues(a.nom, patterns)]
        if hasattr(owner, "evenements"):
            owner.evenements = [e for e in owner.evenements if not e.prive]
        for attr in ("noms", "evenements", "associations", "enfants"):
            for x in getattr(owner, attr, []) or []:
                nettoyer(x)
        if hasattr(owner, "medias") and isinstance(owner.medias, list):
            owner.medias = [m for m in owner.medias if m not in medias]
        if hasattr(owner, "notes") and isinstance(owner.notes, list):
            owner.notes = [n for n in owner.notes if n.strip("@") not in notes or not n.startswith("@")]

    for o in [*t.personnes.values(), *t.familles.values(), *t.medias.values()]:
        nettoyer(o)
    retires = {"sources": sorted(s for s in sources if s in t.sources),
               "medias": sorted(m for m in medias if m in t.medias),
               "notes": sorted(n for n in notes if n in t.notes),
               "enregistrements_non_interpretes": len(t.extra_records)}
    for s in sources:
        t.sources.pop(s, None)
    for m in medias:
        t.medias.pop(m, None)
    for n in notes:
        t.notes.pop(n, None)
    t.notes_privees = set()
    for s in t.sources.values():
        if s.original in sources:
            s.original = ""
    t.extra_records = []
    _scrub(t, patterns)
    return t, hidden, {"masques": sorted(hidden), "retires": retires, "motifs": patterns}


def mask_tree(tree: Tree, today: date | None = None) -> tuple[Tree, set[str]]:
    """Projection de publication (voir ``publication``) : (arbre publié, personnes masquées)."""
    t, hidden, _ = publication(tree, today)
    return t, hidden


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
