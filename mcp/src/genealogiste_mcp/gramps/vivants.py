"""Personnes vivantes dans Gramps Web : drapeau « privé » posé ou retiré par proposition (#264).

Gramps Web ne masque PAS les vivants : seul le drapeau ``private`` protège, et seulement des comptes sans le droit
``ViewPrivate`` (rôle Invité, 0 ; Membre et plus voient tout). Ce que le filtre du privé masque réellement
(gramps-web-api ``api/access/sanitize.py`` et ``db.py`` depuis 3.25 ; avant, ``gramps/gen/proxy/private.py``) :

- un objet principal privé (personne, famille, événement, citation, source, média, note) est introuvable : listes,
  lecture par handle ou ``gramps_id``, recherche, rétroliens ;
- dans un objet visible, les références vers un objet invisible sont retirées (``father_handle``/``mother_handle``
  vidés, enfant retiré de ``child_ref_list``, références d'événement, de média, de citation, de note retirées) et
  les sous-objets privés (nom, attribut, référence…) supprimés ;
- un objet principal NON privé reste visible même si tous ceux qui le référencent sont privés : l'événement de
  naissance d'une personne privée, sa note, sa citation, son média restent listés (date, lieu, texte, image).

D'où le périmètre du marquage d'un vivant (:func:`perimetre`) : la personne ; les familles dont tous les conjoints
sont masqués ; les événements dont tous les « propriétaires » (rôle Principal ou Famille) sont masqués ; puis les
citations, sources, médias et notes dont TOUS les objets référents sont masqués. Les sous-objets de la personne
(noms, attributs, références) n'ont pas à être marqués : la personne privée est masquée en entier. Un objet partagé
avec un objet qui reste visible n'est jamais rendu privé : il est listé (``partages``) avec la raison.

Trace : le journal local ``gramps-transactions.jsonl`` enregistre, pour chaque transaction acceptée, les objets dont
le plugin a posé le privé « parce que vivant » (``protection``) et ceux dont il l'a retiré (``retrait_protection``).
Aucun attribut n'est écrit dans Gramps. Sans ce journal, aucun retrait n'est proposé (privé gardé)."""

from __future__ import annotations

import re
from collections import defaultdict

from .types import tcanon

# Références vers les objets principaux, mêmes tables que gramps-web-api (api/access/sanitize.py).
LISTES_HANDLES = {"note_list": "Note", "citation_list": "Citation", "family_list": "Family",
                  "parent_family_list": "Family"}
LISTES_REFS = {"event_ref_list": "Event", "child_ref_list": "Person", "person_ref_list": "Person",
               "media_list": "Media", "reporef_list": "Repository", "placeref_list": "Place"}
CHAMPS = {"father_handle": "Person", "mother_handle": "Person", "source_handle": "Source", "famc": "Family"}
ROLES_PROPRIETAIRES = ("Primary", "Family")
CLASSES = ("Person", "Family", "Event", "Citation", "Source", "Media", "Note")
ORDRE = {c: i for i, c in enumerate(CLASSES)}
INTERFACE = ("Blog", "ToDo")  # sources étiquetées : billets (#261) et tâches (#263)

Cle = tuple[str, str]


def liens(obj: dict):
    """(classe cible, handle, rôle, via un sous-objet privé) de chaque référence d'un objet principal."""
    def walk(x, prive: bool):
        if isinstance(x, list):
            for y in x:
                yield from walk(y, prive)
            return
        if not isinstance(x, dict):
            return
        prive = prive or (x is not obj and bool(x.get("private")))
        for k, v in x.items():
            if k in LISTES_HANDLES and isinstance(v, list):
                for h in v:
                    if isinstance(h, str) and h:
                        yield LISTES_HANDLES[k], h, "", prive
            elif k in CHAMPS:
                if isinstance(v, str) and v:
                    yield CHAMPS[k], v, "", prive
            elif k in LISTES_REFS and isinstance(v, list):
                for r in v:
                    if not isinstance(r, dict):
                        continue
                    rp = prive or bool(r.get("private"))
                    if isinstance(r.get("ref"), str) and r["ref"]:
                        role = tcanon(r.get("role")) if k == "event_ref_list" else ""
                        yield LISTES_REFS[k], r["ref"], role, rp
                    yield from walk({kk: vv for kk, vv in r.items() if kk != "ref"}, rp)
            elif isinstance(v, (dict, list)):
                yield from walk(v, prive)
    yield from walk(obj, False)


def index_references(db) -> dict[Cle, list[tuple[Cle, str, bool]]]:
    """Rétroliens : objet cible -> [(objet référent, rôle, via un sous-objet privé)]."""
    idx: dict[Cle, list[tuple[Cle, str, bool]]] = defaultdict(list)
    for cls in CLASSES + ("Place", "Repository"):
        for h, o in db.all(cls).items():
            for tcls, th, role, prive in liens(o):
                idx[(tcls, th)].append(((cls, h), role, prive))
    return idx


def gid(db, cle: Cle) -> str:
    o = db.get(*cle) or {}
    return o.get("gramps_id") or cle[1]


def _interface(db, h: str) -> bool:
    s = db.get("Source", h) or {}
    noms = {(db.get("Tag", t) or {}).get("name") for t in s.get("tag_list") or []}
    return bool(noms & set(INTERFACE))


def perimetre(db, cibles: dict[str, str], billets: bool = True, vivants: dict[str, str] | None = None) -> dict:
    """Objets à rendre privés pour masquer les personnes ``cibles`` (handle -> gramps_id, présumées vivantes).

    Renvoie ``poser`` ({(classe, handle): [personnes ou objet d'interface motivant]}), ``partages`` (objets liés
    laissés visibles, avec la raison) et ``masques`` (références d'objets restés visibles retirées par Gramps).
    ``billets`` : les médias et notes dont le seul référent est un billet ou une tâche privés (#261, #263) sont
    inclus (motif « billet S… »). ``vivants`` (handle -> gramps_id, toutes les personnes présumées vivantes) : ne
    déclenche rien, complète seulement les motifs d'un objet commun à plusieurs vivants (famille, événement), pour
    qu'un retrait au décès de l'un ne démasque pas l'autre."""
    vivants = vivants or {}
    idx = index_references(db)
    prive = {(c, h) for c in CLASSES for h, o in db.all(c).items() if o.get("private")}
    motifs: dict[Cle, set[str]] = {("Person", h): {g} for h, g in cibles.items() if db.get("Person", h)}
    if billets:
        for h, s in db.all("Source").items():
            if s.get("private") and _interface(db, h):
                motifs.setdefault(("Source", h), set()).add(f"billet ou tâche {s.get('gramps_id') or h}")
    poser: dict[Cle, set[str]] = {}
    for cle in list(motifs):
        if cle not in prive:
            poser[cle] = set(motifs[cle])

    def masque(cle: Cle) -> bool:
        return cle in prive or cle in poser

    def referents(cle: Cle):
        return idx.get(cle, [])

    def visibles(cle: Cle) -> list[Cle]:
        return sorted({r for r, _, via in referents(cle) if not via and not masque(r)})

    def motif_de(cle: Cle) -> set[str]:
        out: set[str] = set()
        for r, _, _ in referents(cle):
            out |= motifs.get(r, set())
        return out

    def marquer(cle: Cle, m: set[str]) -> bool:
        motifs.setdefault(cle, set()).update(m)
        if cle in prive or cle in poser:
            return False
        poser[cle] = set(m)
        return True

    partages: dict[Cle, str] = {}
    masques: dict[Cle, str] = {}
    change = True
    while change:
        change = False
        for h, f in db.all("Family").items():
            cle = ("Family", h)
            conjoints = [("Person", x) for x in (f.get("father_handle"), f.get("mother_handle")) if x]
            m = set().union(*(motifs.get(c, set()) for c in conjoints)) if conjoints else set()
            if not m:
                continue
            if all(masque(c) for c in conjoints):
                m = m | {vivants[c[1]] for c in conjoints if c[1] in vivants}
                if marquer(cle, m):
                    change = True
                enfants = [r.get("ref") for r in f.get("child_ref_list") or [] if r.get("ref")]
                vus = [gid(db, ("Person", c)) for c in enfants if not masque(("Person", c))]
                if vus:
                    masques[cle] = f"filiation masquée pour {', '.join(vus)} (enfant(s) restant visible(s))"
            else:
                autres = [gid(db, c) for c in conjoints if not masque(c)]
                partages[cle] = (f"famille partagée avec {', '.join(autres)} (non masqué) : famille et événements "
                                 "familiaux restent visibles, le vivant n'y figure plus (référence retirée par Gramps)")
        for h in db.all("Event"):
            cle = ("Event", h)
            refs = referents(cle)
            proprietaires = {r for r, role, _ in refs if role in ROLES_PROPRIETAIRES or r[0] == "Family"}
            m = set().union(*(motifs.get(r, set()) for r in proprietaires)) if proprietaires else set()
            if not m:  # aucun propriétaire masqué : un vivant seulement témoin, masqué avec sa personne
                continue
            vus = sorted({r for r in proprietaires if not masque(r)})
            if vus:
                partages[cle] = f"événement partagé avec {', '.join(gid(db, r) for r in vus)} (non masqué)"
                continue
            m = m | {vivants[r[1]] for r in proprietaires if r[0] == "Person" and r[1] in vivants}
            if marquer(cle, m):
                change = True
            temoins = sorted({gid(db, r) for r, role, via in refs if r not in proprietaires and not via
                              and not masque(r)})
            if temoins:
                masques[cle] = f"participation (témoin, parrain…) de {', '.join(temoins)} masquée"
        for cls in ("Citation", "Source", "Media", "Note"):
            for h in db.all(cls):
                cle = (cls, h)
                if cle in poser or cle in prive:
                    continue
                m = motif_de(cle)
                if not m:
                    continue
                if cls == "Source" and _interface(db, h):
                    continue
                vus = visibles(cle)
                if vus:
                    partages[cle] = ("partagé avec " + ", ".join(f"{c[0]} {gid(db, c)}" for c in vus[:3])
                                     + (f" et {len(vus) - 3} autre(s)" if len(vus) > 3 else "") + " (non masqué)")
                    continue
                if marquer(cle, m):
                    partages.pop(cle, None)
                    change = True
    for cle in poser:
        partages.pop(cle, None)
    return {"poser": {k: sorted(v) for k, v in poser.items()},
            "partages": {k: v for k, v in partages.items() if k not in prive},
            "masques": masques}


NOTES_HORS_MODELE = (
    "{n} note(s) rendue(s) privée(s) : comme toute note privée, Genealogiste les garde intactes dans Gramps mais ne "
    "les lit plus (fiches, notes de recherche, exports) ; visibles dans Gramps Web pour les rôles Membre et plus ; "
    "de nouveau lues après le retrait du privé.")
NON_MASQUABLE = [
    "Lieux, dépôts et étiquettes n'ont pas de drapeau privé utile ici : jamais modifiés (un lieu ne nomme personne).",
    "Famille partagée avec un conjoint non masqué : la famille et ses événements restent visibles, le vivant n'y "
    "figure plus (référence retirée par Gramps) ; l'existence d'une union reste lisible.",
    "Texte d'un objet resté visible (note, description, page de citation, attribut) qui nomme un vivant : listé "
    "dans « residus », jamais réécrit.",
    "Types personnalisés (libellés d'événement, d'attribut…) : collectés sur tous les objets, privés compris, par "
    "Gramps Web (fuite connue, sans nom de personne).",
    "Comptes Membre et plus : voient tout le privé ; seul un compte Invité (rôle 0) est concerné.",
    "Gramps Web antérieur à l'API 3.25.0 (constaté sur 3.13.0) : la recherche plein texte trouve encore une famille "
    "ou un événement visibles partagés avec le vivant en cherchant son nom (le nom n'est pas renvoyé) ; corrigé par "
    "l'index de recherche de l'API 3.25.0 : mettre à jour Gramps Web.",
]


def par_classe(cles) -> dict[str, int]:
    out: dict[str, int] = {}
    for c, _ in cles:
        out[c] = out.get(c, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: ORDRE.get(kv[0], 9)))


def avec_prive(db, cles, valeur: bool = True):
    """Copie de la base où le drapeau ``private`` des objets ``cles`` vaut ``valeur``."""
    out = db.copy()
    for cls, h in cles:
        o = out.get(cls, h)
        if o is not None:
            o["private"] = valeur
    return out


def lignes(db, cles: dict[Cle, list[str]] | set[Cle], verbe: str) -> list[str]:
    """Une ligne par objet : « Event E12 : privé posé (I9) »."""
    out = []
    for cle in sorted(cles, key=lambda c: (ORDRE.get(c[0], 9), gid(db, c))):
        m = cles[cle] if isinstance(cles, dict) else []
        out.append(f"{cle[0]} {gid(db, cle)} : {verbe}" + (f" ({', '.join(m)})" if m else ""))
    return out


def protections_actives(transactions: list[dict]) -> dict[Cle, dict]:
    """Privés posés par le plugin « parce que vivant » et toujours actifs d'après le journal : ni annulés, ni
    retirés depuis. ``transactions`` : entrées fusionnées du journal, dans l'ordre (GrampsBackend.transactions)."""
    effectives = [e for e in transactions if e.get("etat", "envoyee") in ("envoyee", "terminee",
                                                                          "complements_en_echec")]
    annulees = {e.get("annule") for e in effectives if e.get("type") == "annulation"}
    actives: dict[Cle, dict] = {}
    for e in effectives:
        if e.get("type") != "transaction" or e.get("id") in annulees:
            continue
        for x in e.get("retrait_protection") or []:
            actives.pop((x["classe"], x["handle"]), None)
        for x in e.get("protection") or []:
            actives[(x["classe"], x["handle"])] = x
    return actives


def enregistrement(db, poser: dict[Cle, list[str]]) -> list[dict]:
    return [{"classe": c, "handle": h, "gramps_id": gid(db, (c, h)), "motifs": m}
            for (c, h), m in sorted(poser.items())]


def a_retirer(db, actives: dict[Cle, dict], vivants: set[str]) -> dict[Cle, list[str]]:
    """Privés posés par le plugin dont aucune personne motivante n'est plus présumée vivante (``vivants`` :
    gramps_id), encore privés dans la base. Un objet posé pour un billet ou une tâche n'est jamais retiré ici."""
    out = {}
    for cle, x in actives.items():
        o = db.get(*cle)
        if o is None or not o.get("private"):
            continue
        personnes = [m for m in x.get("motifs") or [] if not m.startswith("billet")]
        if not personnes or len(personnes) != len(x.get("motifs") or []):
            continue
        if any(p in vivants for p in personnes):
            continue
        out[cle] = personnes
    return out


def residus(db, tree, cibles: set[str], masques_apres, seulement=None) -> list[dict]:
    """Objets qui restent visibles d'un Invité et dont le texte nomme une personne masquée (prénom et nom accolés,
    même règle que les exports publics) : listés, jamais modifiés. ``masques_apres`` : fonction (classe, handle) ->
    masqué après la proposition ; ``seulement`` : prédicat (classe, objet) limitant l'examen."""
    from .. import privacy

    if not cibles:
        return []
    from ..normalize.names import strip_accents

    def plat(x: str) -> str:
        return re.sub(r"[\s\-'’/,]+", " ", strip_accents(x or "").lower())

    motifs = {pid: privacy.identifying_patterns(tree, {pid}) for pid in sorted(cibles) if pid in tree.personnes}
    noms = {pid: {plat(n.nom).strip() for n in tree.personnes[pid].noms if n.nom.strip()} for pid in motifs}
    out = []
    for cls in CLASSES:
        for h, o in sorted(db.all(cls).items()):
            if masques_apres((cls, h)) or (seulement is not None and not seulement(cls, o)):
                continue
            textes = _textes(o, cls)
            if not textes:
                continue
            tout = plat(" ".join(textes))
            for pid, pats in motifs.items():
                if not any(n in tout for n in noms[pid]):  # filtre rapide sur le patronyme
                    continue
                if any(privacy.residues(t, pats) for t in textes):
                    out.append({"classe": cls, "gramps_id": o.get("gramps_id") or h, "personne": pid,
                                "handle": h})
    return out


def notes_generees(db, tree, cibles: set[str], masques_apres) -> dict[Cle, list[str]]:
    """Notes générées par Genealogiste (étiquette ``Genealogiste:auto`` ou ``Sosa:auto``) restées visibles qui nomment
    une personne masquée (ex. « Filiation de … » sur la famille d'un défunt) : rendues privées avec elle, car elles
    ne parlent que d'elle ; une note saisie par l'utilisateur n'est jamais modifiée (``residus``)."""
    from .mapping import auto_tags

    autos = auto_tags(db)
    if not autos:
        return {}
    out: dict[Cle, list[str]] = {}
    for r in residus(db, tree, cibles, masques_apres,
                     seulement=lambda cls, o: cls == "Note" and bool(autos & set(o.get("tag_list") or []))):
        out.setdefault(("Note", r["handle"]), []).append(r["personne"])
    return {k: sorted(set(v)) for k, v in out.items()}


def _textes(o: dict, cls: str) -> list[str]:
    t: list[str] = []
    if cls == "Note":
        t.append(((o.get("text") or {}).get("string")) or "")
    for k in ("description", "page", "title", "author", "pubinfo", "abbrev", "desc"):
        if isinstance(o.get(k), str):
            t.append(o[k])
    for a in o.get("attribute_list") or []:
        if not a.get("private") and isinstance(a.get("value"), str):
            t.append(a["value"])
    return [x for x in t if x]
