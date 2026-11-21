"""Opérations d'édition de l'arbre (appliquées sur une copie, jamais directement sur disque).

Chaque opération est un dict {"op": "...", ...}. Les créations acceptent "ref": "x" ; les opérations
suivantes de la même proposition peuvent alors désigner l'objet créé par "$x".
"""

from __future__ import annotations

import copy
import re
from datetime import date
from pathlib import PurePosixPath

from .. import ark, billets, etiquettes, objets_interface, taches
from ..models import (
    CONSULTATIONS,
    EVENT_LABELS,
    ROLE_FR,
    ROLE_LABELS,
    ROLES,
    Assertion,
    Association,
    ChildLink,
    Citation,
    Event,
    Family,
    Media,
    Name,
    Person,
    Place,
    Repository,
    Source,
    Tree,
    new_uid,
)
from ..normalize.dates import date_problem, parse_date

MANUAL_STATUSES = ("refute", "contradictoire", "")


class OpError(ValueError):
    pass


class Ctx:
    def __init__(self, tree: Tree, exiger_source: bool = True, media=None, backend: str = "", taches: bool = False):
        self.tree = tree
        self.backend = backend  # « fichier » | « gramps » | "" (inconnu : tests, validation à sec)
        self.taches = taches  # tâches de Gramps Web (GENEALOGISTE_GRAMPS_TACHES, #263)
        self.exiger_source = exiger_source
        self.media = media  # fichier -> référence normalisée (Config.media_reference) ; None : pas de contrôle
        self.refs: dict[str, str] = {}
        self.summary: list[str] = []
        self.sources_cited: set[str] = set()
        self.warnings: list[str] = []
        self.citations_images: list[Citation] = []  # citations à images de la proposition (#246)

    def r(self, value: str | None) -> str:
        if value and isinstance(value, str) and value.startswith("$"):
            key = value[1:]
            if key not in self.refs:
                raise OpError(f"Référence inconnue : {value}")
            return self.refs[key]
        return value or ""


# ---------------------------------------------------------------------------- constructeurs

def _noms_etiquettes(valeur, champ: str) -> list[str]:
    try:
        return etiquettes.liste(valeur, champ)
    except ValueError as exc:
        raise OpError(f"{champ} : {exc}") from exc


def _etiqueter(ctx: Ctx, cible, o: dict, label: str, creation: bool = False, lire=None, ecrire=None) -> bool:
    """Champs « tags » (ajout) et « tags_retrait » d'une opération appliqués aux étiquettes de ``cible`` (#262) ;
    une ligne concise au résumé (« étiquettes I12 : +Blog −ToDo »). Renvoie vrai si un des champs est fourni."""
    if "tags" not in o and "tags_retrait" not in o:
        return False
    ajout = _noms_etiquettes(o.get("tags"), "tags")
    retrait = _noms_etiquettes(o.get("tags_retrait"), "tags_retrait")
    if creation and retrait:
        raise OpError("tags_retrait : rien à retirer sur un objet créé par l'opération")
    if set(ajout) & set(retrait):
        raise OpError(f"étiquette(s) à la fois ajoutée(s) et retirée(s) : {sorted(set(ajout) & set(retrait))}")
    actuelles = lire() if lire else cible.tags
    nouvelles, ajoutees, retirees, absentes = etiquettes.appliquer(actuelles, ajout, retrait)
    if ecrire:
        ecrire(nouvelles)
    else:
        cible.tags = nouvelles
    if ajoutees or retirees:
        ctx.summary.append(etiquettes.ligne(label, ajoutees, retirees))
    for x in absentes:
        ctx.warnings.append(f"{label} : étiquette « {x} » absente, rien à retirer")
    return True


def _date(value: str) -> str:
    if not value:
        return ""
    g = parse_date(value)
    if not g:
        why = date_problem(value)
        if why:
            raise OpError(f"Date impossible : {value!r} — {why}")
        raise OpError(f"Date non reconnue : {value!r} (formats : 12 MAR 1820, ABT 1820, 12 vendémiaire an III…)")
    return g.gedcom(7)


def _ark_of(*values: str) -> ark.Ark | None:
    for v in values:
        a = ark.find(v) if v else None
        if a:
            return a
    return None


def _source_by_ark(tree: Tree, a: ark.Ark) -> str:
    return next((sid for sid, s in sorted(tree.sources.items())
                 if (s.ark and ark.same_resource(s.ark, a.base)) or (s.url and ark.same_resource(s.url, a.base))), "")


def _citation(ctx: Ctx, d: dict) -> Citation:
    d = dict(d)
    if "tags_retrait" in d:
        raise OpError("Citation : tags_retrait sans objet sur une citation créée (étiqueter une citation existante : "
                      "opération etiqueter)")
    d["tags"] = _noms_etiquettes(d.get("tags"), "Citation : tags")
    lier_media = d.pop("lier_media", True)
    if not isinstance(lier_media, bool):
        raise OpError("Citation : lier_media doit valoir true ou false")
    d["source"] = ctx.r(d.get("source"))
    a = _ark_of(d.get("ark", ""), d.get("page", ""))
    if a:  # ARK de l'image ou de la page : normalisé, source et vue déduites
        d["ark"] = a.id
        if not d["source"]:
            d["source"] = _source_by_ark(ctx.tree, a)
            if not d["source"]:
                raise OpError(f"Citation : aucune source pour {a.base} (créer la source d'abord : ajouter_source avec "
                              f"ark={a.base!r})")
        if not d.get("page") and a.vue:
            d["page"] = f"vue {a.vue}"
    if d["source"] not in ctx.tree.sources:
        raise OpError(f"Citation : source inconnue {d['source']!r} (créer la source d'abord)")
    d["medias"] = [ctx.r(m) for m in d.get("medias") or []]
    for m in d["medias"]:
        if m not in ctx.tree.medias:
            raise OpError(f"Citation : média inconnu {m!r} (ajouter_media d'abord, avec ref)")
    for k, allowed in (("type_source", ("originale", "derivee", "composite", "indeterminee")),
                       ("information", ("primaire", "secondaire", "indeterminee")),
                       ("preuve", ("directe", "indirecte", "negative"))):
        if k in d and d[k] not in allowed:
            raise OpError(f"Citation : {k} doit valoir {', '.join(allowed)}")
    if d.get("consultation", "") not in CONSULTATIONS + ("",):
        raise OpError(f"Citation : consultation doit valoir {', '.join(CONSULTATIONS)}")
    d.setdefault("date_consultation", date.today().isoformat())
    ctx.sources_cited.add(d["source"])
    c = Citation.from_dict(d)
    if c.medias and lier_media:
        ctx.citations_images.append(c)
    return c


def _place(v) -> Place | None:
    if not v:
        return None
    if isinstance(v, str):
        return Place(nom=v)
    return Place.from_dict(v)


def _unsourced(ctx: Ctx, d: dict, what: str) -> str:
    """Règle de métier : pas de fait sans source, sauf choix explicite et motivé (« non_source »)."""
    flag, motif = d.pop("non_source", False), d.pop("motif", "")
    if d.get("citations"):
        return ""
    if not ctx.exiger_source:
        return ""
    if not flag:
        raise OpError(f"{what} sans citation : ajouter la source, ou passer non_source=true avec un motif "
                      "(ex. « tradition familiale », « piste Geneanet à vérifier »).")
    if not motif:
        raise OpError(f"{what} non sourcé : motif obligatoire")
    ctx.warnings.append(f"{what} enregistré sans source ({motif})")
    return f"Non sourcé : {motif}"


def _association(ctx: Ctx, d: dict) -> Association:
    d = dict(d)
    role = str(d.get("role", "WITN"))
    key = role.lower().replace("é", "e").replace("è", "e")
    if key in ROLE_FR:
        code, label = ROLE_FR[key]
        d["role"] = code
        d.setdefault("detail", label)
    elif role.upper() in ROLES:
        d["role"] = role.upper()
    else:
        raise OpError(f"Rôle inconnu {role!r} : {', '.join(ROLE_FR)} ou {', '.join(ROLES)}")
    d["personne"] = ctx.r(d.get("personne"))
    if d["personne"] and d["personne"] not in ctx.tree.personnes:
        raise OpError(f"Association : personne inconnue {d['personne']}")
    if not d["personne"] and not d.get("nom"):
        raise OpError("Association : 'personne' (id) ou 'nom' (tel qu'écrit dans l'acte) requis")
    d["citations"] = [_citation(ctx, c) for c in d.get("citations", [])]
    try:
        return Association(**d)
    except TypeError as exc:
        raise OpError(f"Association invalide : {exc}") from exc


def _event(ctx: Ctx, d: dict) -> Event:
    d = dict(d)
    t = d.get("type", "").upper()
    if t not in EVENT_LABELS:
        raise OpError(f"Type d'événement inconnu : {t!r}")
    d["type"] = t
    mention = _unsourced(ctx, d, f"Événement {t}")
    if mention:
        d["note"] = (d.get("note", "") + "\n" + mention).strip()
    d["date"] = _date(d.get("date", ""))
    d["lieu"] = _place(d.get("lieu"))
    d["citations"] = [_citation(ctx, c) for c in d.get("citations", [])]
    d["associations"] = [_association(ctx, a) for a in d.get("associations", [])]
    if "statut_manuel" in d and d["statut_manuel"]:
        d["statut_manuel"] = Assertion.from_dict(d["statut_manuel"])
    d.pop("uid", None)
    if "medias" in d:
        raise OpError("Événement : médias à lier par ajouter_media / modifier_media (lier_a : uid de l'événement)")
    if "tags_retrait" in d:
        raise OpError("Événement : tags_retrait sans objet sur un événement créé (modifier_evenement ou etiqueter)")
    d["tags"] = _noms_etiquettes(d.get("tags"), "Événement : tags")
    try:
        return Event(**{k: v for k, v in d.items()})
    except TypeError as exc:
        raise OpError(f"Événement invalide : {exc}") from exc


def _name(ctx: Ctx, d: dict) -> Name:
    d = dict(d)
    d["citations"] = [_citation(ctx, c) for c in d.get("citations", [])]
    d.pop("uid", None)
    try:
        return Name(**d)
    except TypeError as exc:
        raise OpError(f"Nom invalide : {exc}") from exc


def _owner(ctx: Ctx, oid: str) -> Person | Family:
    oid = ctx.r(oid)
    if oid in ctx.tree.personnes:
        return ctx.tree.personnes[oid]
    if oid in ctx.tree.familles:
        return ctx.tree.familles[oid]
    raise OpError(f"Cible inconnue : {oid}")


def _find_event(ctx: Ctx, uid: str) -> tuple[Person | Family, Event]:
    found = ctx.tree.find_event(uid)
    if not found:
        raise OpError(f"Événement inconnu : {uid}")
    return found


# ---------------------------------------------------------------------------- opérations

def op_ajouter_personne(ctx: Ctx, o: dict) -> None:
    pid = ctx.tree.next_id("personnes")
    sexe = o.get("sexe", "U").upper()
    if sexe not in ("M", "F", "U", "X"):
        raise OpError("sexe : M, F, U ou X")
    p = Person(id=pid, sexe=sexe, vivant=o.get("vivant", ""))
    p.noms = [_name(ctx, n) for n in o.get("noms", [])]
    if not p.noms:
        raise OpError("ajouter_personne : au moins un nom requis")
    p.evenements = [_event(ctx, e) for e in o.get("evenements", [])]
    p.citations = [_citation(ctx, c) for c in o.get("citations", [])]
    p.notes = list(o.get("notes", []))
    ctx.tree.personnes[pid] = p
    if o.get("ref"):
        ctx.refs[o["ref"]] = pid
    ctx.summary.append(f"Ajout de {p.label()}")
    _etiqueter(ctx, p, o, pid, creation=True)


def op_modifier_personne(ctx: Ctx, o: dict) -> None:
    p = ctx.tree.person(ctx.r(o["id"]))
    if "sexe" in o:
        p.sexe = o["sexe"].upper()
    if "vivant" in o:
        p.vivant = o["vivant"]
    if "noms" in o:
        p.noms = [_name(ctx, n) for n in o["noms"]]
    for n in o.get("notes_ajout", []):
        p.notes.append(n)
    ctx.summary.append(f"Modification de {p.label()}")
    _etiqueter(ctx, p, o, p.id)


def op_supprimer_personne(ctx: Ctx, o: dict) -> None:
    pid = ctx.r(o["id"])
    p = ctx.tree.person(pid)
    for fam in ctx.tree.familles.values():
        if fam.epoux == pid:
            fam.epoux = ""
        if fam.epouse == pid:
            fam.epouse = ""
        fam.enfants = [c for c in fam.enfants if c.enfant != pid]
    for a in _all_associations(ctx.tree):
        if a.personne == pid:
            a.personne, a.nom = "", a.nom or p.nom_principal.complet
    del ctx.tree.personnes[pid]
    ctx.summary.append(f"Suppression de {p.label()}")


def op_ajouter_nom(ctx: Ctx, o: dict) -> None:
    p = ctx.tree.person(ctx.r(o["id"]))
    n = _name(ctx, o["nom"])
    p.noms.append(n)
    ctx.summary.append(f"{p.label()} : nom ajouté « {n.complet} »")


def op_ajouter_evenement(ctx: Ctx, o: dict) -> None:
    owner = _owner(ctx, o["cible"])
    e = _event(ctx, o["evenement"])
    owner.evenements.append(e)
    if o.get("ref"):
        ctx.refs[o["ref"]] = e.uid
    ctx.summary.append(f"{owner.id} : {EVENT_LABELS[e.type]} {e.date} {e.lieu.nom if e.lieu else ''}".strip())


def op_modifier_evenement(ctx: Ctx, o: dict) -> None:
    owner, e = _find_event(ctx, ctx.r(o["uid"]))
    champs = dict(o.get("champs", {}))
    before = f"{e.date} {e.lieu.nom if e.lieu else ''}".strip()
    if "date" in champs:
        e.date = _date(champs.pop("date"))
    if "lieu" in champs:
        e.lieu = _place(champs.pop("lieu"))
    for k in ("valeur", "type_detail", "age", "cause", "note"):
        if k in champs:
            setattr(e, k, champs.pop(k))
    if champs:
        raise OpError(f"modifier_evenement : champs non modifiables {sorted(champs)}"
                      + (" (étiquettes : tags / tags_retrait au niveau de l'opération)" if "tags" in champs else ""))
    for c in o.get("citations_ajout", []):
        e.citations.append(_citation(ctx, c))
    after = f"{e.date} {e.lieu.nom if e.lieu else ''}".strip()
    if o.get("champs") or o.get("citations_ajout") or ("tags" not in o and "tags_retrait" not in o):
        ctx.summary.append(f"{owner.id} : {EVENT_LABELS[e.type]} modifié ({before} → {after})")
    _etiqueter(ctx, e, o, f"{owner.id} {EVENT_LABELS[e.type]}")


def op_supprimer_evenement(ctx: Ctx, o: dict) -> None:
    owner, e = _find_event(ctx, ctx.r(o["uid"]))
    owner.evenements = [x for x in owner.evenements if x.uid != e.uid]
    ctx.summary.append(f"{owner.id} : {EVENT_LABELS[e.type]} {e.date} supprimé")


def op_ajouter_famille(ctx: Ctx, o: dict) -> None:
    fid = ctx.tree.next_id("familles")
    f = Family(id=fid, epoux=ctx.r(o.get("epoux")), epouse=ctx.r(o.get("epouse")))
    for role in (f.epoux, f.epouse):
        if role:
            ctx.tree.person(role).fams.append(fid)
    f.evenements = [_event(ctx, e) for e in o.get("evenements", [])]
    f.citations = [_citation(ctx, c) for c in o.get("citations", [])]
    _etiqueter(ctx, f, o, fid, creation=True)
    ctx.tree.familles[fid] = f
    if o.get("ref"):
        ctx.refs[o["ref"]] = fid
    for ch in o.get("enfants", []):
        ch = {"enfant": ch} if isinstance(ch, str) else ch
        op_lier_enfant(ctx, {"famille": fid, **ch})
    ctx.summary.append(f"Ajout de la famille {fid} ({f.epoux or '?'} × {f.epouse or '?'})")


def op_lier_enfant(ctx: Ctx, o: dict) -> None:
    fam = ctx.tree.family(ctx.r(o["famille"]))
    cid = ctx.r(o["enfant"])
    child = ctx.tree.person(cid)
    if fam.child(cid):
        raise OpError(f"{cid} est déjà enfant de {fam.id}")
    o = dict(o)
    mention = _unsourced(ctx, o, f"Filiation {cid}/{fam.id}")
    if mention:
        child.notes.append(f"Filiation avec {fam.id} — {mention}")
    link = ChildLink(enfant=cid, filiation=o.get("filiation", ""),
                     citations=[_citation(ctx, c) for c in o.get("citations", [])])
    fam.enfants.append(link)
    if fam.id not in child.famc:
        child.famc.append(fam.id)
    ctx.summary.append(f"Filiation : {child.label()} enfant de {fam.id}")


def op_delier_enfant(ctx: Ctx, o: dict) -> None:
    fam = ctx.tree.family(ctx.r(o["famille"]))
    cid = ctx.r(o["enfant"])
    fam.enfants = [c for c in fam.enfants if c.enfant != cid]
    p = ctx.tree.person(cid)
    p.famc = [f for f in p.famc if f != fam.id]
    ctx.summary.append(f"Filiation retirée : {cid} / {fam.id}")


def op_lier_conjoint(ctx: Ctx, o: dict) -> None:
    fam = ctx.tree.family(ctx.r(o["famille"]))
    pid = ctx.r(o["personne"])
    p = ctx.tree.person(pid)
    role = o.get("role") or ("epoux" if p.sexe == "M" else "epouse")
    if role not in ("epoux", "epouse"):
        raise OpError("role : epoux ou epouse")
    old = getattr(fam, role)
    if old and old in ctx.tree.personnes:
        ctx.tree.personnes[old].fams = [f for f in ctx.tree.personnes[old].fams if f != fam.id]
    setattr(fam, role, pid)
    if fam.id not in p.fams:
        p.fams.append(fam.id)
    ctx.summary.append(f"{fam.id} : {role} = {p.label()}")


def _depot_for(ctx: Ctx, a: ark.Ark) -> str:
    """Dépôt du service qui a attribué l'ARK (créé s'il n'existe pas)."""
    svc = a.service
    if not svc:
        return ""
    rid = next((rid for rid, r in sorted(ctx.tree.depots.items()) if r.sigle == svc["code"]), "")
    if not rid:
        rid = ctx.tree.next_id("depots")
        ctx.tree.depots[rid] = Repository(id=rid, nom=svc["nom"], sigle=svc["code"], url=svc.get("hote", ""))
        ctx.summary.append(f"Dépôt {rid} : {svc['nom']} (déduit de l'ARK {a.naan})")
    return rid


def op_ajouter_source(ctx: Ctx, o: dict) -> None:
    d = {k: v for k, v in o.items() if k not in ("op", "ref", "tags", "tags_retrait")}
    a = _ark_of(d.get("ark", ""), d.get("url", ""))
    if a:
        same = _source_by_ark(ctx.tree, a)
        if same:  # dédoublonnage : une ressource ARK = une source
            if o.get("ref"):
                ctx.refs[o["ref"]] = same
            ctx.sources_cited.add(same)
            ctx.warnings.append(f"Source {same} réutilisée : même ARK ({a.base}) que « {ctx.tree.sources[same].titre} ».")
            ctx.summary.append(f"Source {same} réutilisée (même ARK {a.base})")
            if "tags_retrait" in o:
                raise OpError("tags_retrait : rien à retirer sur une source ajoutée (modifier_source ou etiqueter)")
            _etiqueter(ctx, ctx.tree.sources[same], o, same)
            return
        d["ark"] = a.base
        if not d.get("url"):
            d["url"] = ark.Ark(a.naan, a.nom, "", a.hote).url()
        if not d.get("depot"):
            d["depot"] = _depot_for(ctx, a)
    if "medias" in d:
        raise OpError("ajouter_source : médias à lier par ajouter_media / modifier_media (lier_a : S…)")
    sid = ctx.tree.next_id("sources")
    d["depot"] = ctx.r(d.get("depot"))
    d["original"] = ctx.r(d.get("original"))
    if d["depot"] and d["depot"] not in ctx.tree.depots:
        raise OpError(f"Dépôt inconnu : {d['depot']}")
    if d["original"] and d["original"] not in ctx.tree.sources:
        raise OpError(f"Source originale inconnue : {d['original']}")
    if not d.get("titre"):
        raise OpError("ajouter_source : titre requis")
    s = Source.from_dict({"id": sid, **d})
    ctx.tree.sources[sid] = s
    if o.get("ref"):
        ctx.refs[o["ref"]] = sid
    ctx.sources_cited.add(sid)
    ctx.summary.append(f"Source {sid} : {s.titre}" + (f" (cote {s.cote})" if s.cote else ""))
    _etiqueter(ctx, s, o, sid, creation=True)
    if billets.est_billet(s) and "prive" not in o:  # #261 : billet créé par le plugin, jamais public par défaut
        s.prive = True
    if ctx.taches and taches.TODO in s.tags:  # #263 : tâche créée comme le fait l'interface, privée par défaut
        s.tache = {"statut": taches.STATUT_DEFAUT, "priorite": taches.PRIORITE_DEFAUT}
        if "prive" not in o:
            s.prive = True


BILLET_CHAMPS = ("op", "ref", "titre", "auteur", "texte", "medias", "prive", "tags")


def op_ajouter_billet(ctx: Ctx, o: dict) -> None:
    """Billet du blog de Gramps Web (#261) : source étiquetée Blog (titre, auteur), corps en première note,
    médias dans l'ordre donné (le premier sert d'aperçu), privé sauf « prive: false »."""
    if ctx.backend == "fichier":
        raise OpError("le blog est une page de Gramps Web : billet refusé en backend fichier (GEDCOM). Passer en "
                      "GENEALOGISTE_BACKEND=gramps, ou créer une simple source étiquetée (ajouter_source, "
                      "tags: [\"Blog\"]), sans effet hors de Gramps Web")
    inconnus = sorted(set(o) - set(BILLET_CHAMPS))
    if inconnus:
        raise OpError(f"champs inconnus {inconnus} (acceptés : {', '.join(BILLET_CHAMPS[2:])})")
    titre, texte = o.get("titre"), o.get("texte")
    if not isinstance(titre, str) or not titre.strip():
        raise OpError("titre requis (titre de la source, titre du billet)")
    if not isinstance(texte, str) or not texte.strip():
        raise OpError("texte requis (corps du billet : première note de la source)")
    prive = o.get("prive", True)
    if not isinstance(prive, bool):
        raise OpError("prive : true (défaut) ou false")
    medias = o.get("medias") or []
    if not isinstance(medias, list):
        raise OpError("medias : liste d'identifiants O… ou de $ref d'ajouter_media (le premier sert d'aperçu)")
    ids = []
    for m in medias:
        mid = ctx.r(m)
        if mid not in ctx.tree.medias:
            raise OpError(f"média inconnu : {m}")
        if mid in ids:
            raise OpError(f"média {mid} donné deux fois")
        ids.append(mid)
    sid = ctx.tree.next_id("sources")
    s = Source(id=sid, titre=titre, auteur=o.get("auteur") or "", note=texte, prive=prive, medias=ids)
    ctx.tree.sources[sid] = s
    if o.get("ref"):
        ctx.refs[o["ref"]] = sid
    images = (f" ; aperçu {ids[0]}" + (f", galerie {', '.join(ids)}" if len(ids) > 1 else "")) if ids \
        else " ; sans image"
    ctx.summary.append(f"Billet {sid} : {titre}" + (f", par {s.auteur}" if s.auteur else "") + images)
    _etiqueter(ctx, s, {"tags": [billets.BLOG, *_noms_etiquettes(o.get("tags"), "tags")]}, sid, creation=True)


TACHE_CHAMPS = ("op", "ref", "titre", "description", "statut", "priorite", "prive", "tags", "personnes", "enquete",
                "element")
MODIFIER_TACHE_CHAMPS = ("op", "id", "titre", "description", "statut", "priorite", "prive", "tags", "tags_retrait")


def _tache_permise(ctx: Ctx) -> None:
    if ctx.backend == "fichier":
        raise OpError("les tâches sont une page de Gramps Web : refusé en backend fichier (GEDCOM). Passer en "
                      "GENEALOGISTE_BACKEND=gramps avec GENEALOGISTE_GRAMPS_TACHES=true")
    if not ctx.taches:
        raise OpError(taches.DESACTIVE)


def _champ_tache(fn, valeur):
    try:
        return fn(valeur)
    except taches.TacheError as exc:
        raise OpError(str(exc)) from exc


def _avec_suffixe(ctx: Ctx, texte: str, suffixe: str) -> str:
    """Texte + lignes ajoutées en fin ; la mise en forme Markdown du texte (#279, indexée par le texte) suit."""
    if not suffixe:
        return texte
    out = f"{texte}\n\n{suffixe}" if texte else suffixe
    if texte in ctx.tree.styles:
        ctx.tree.styles[out] = ctx.tree.styles[texte]
    return out


def op_ajouter_tache(ctx: Ctx, o: dict) -> None:
    """Tâche de Gramps Web (#263) : source étiquetée ToDo (titre), attributs Priority et Status (défaut 5 et Open,
    comme l'interface), description en première note (type To Do, étiquetée ToDo), privée sauf « prive: false ».
    ``personnes`` : identifiants des personnes concernées, nommées dans la description (l'interface ne relie pas
    une tâche à d'autres objets) ; ``enquete`` + ``element`` : référence de l'élément d'enquête d'origine."""
    _tache_permise(ctx)
    inconnus = sorted(set(o) - set(TACHE_CHAMPS))
    if inconnus:
        raise OpError(f"champs inconnus {inconnus} (acceptés : {', '.join(TACHE_CHAMPS[2:])})")
    titre, description = o.get("titre"), o.get("description") or ""
    if not isinstance(titre, str) or not titre.strip():
        raise OpError("titre requis (titre de la tâche)")
    if not isinstance(description, str):
        raise OpError("description : texte (première note de la tâche)")
    prive = o.get("prive", True)
    if not isinstance(prive, bool):
        raise OpError("prive : true (défaut) ou false")
    statut = _champ_tache(taches.statut, o["statut"]) if "statut" in o else taches.STATUT_DEFAUT
    priorite = _champ_tache(taches.priorite, o["priorite"]) if "priorite" in o else taches.PRIORITE_DEFAUT
    personnes = o.get("personnes") or []
    if not isinstance(personnes, list):
        raise OpError("personnes : liste d'identifiants (I…)")
    ids = [ctx.r(p) for p in personnes]
    for pid in ids:
        if pid not in ctx.tree.personnes:
            raise OpError(f"personne inconnue : {pid}")
    enquete, element = o.get("enquete") or "", o.get("element") or ""
    if bool(enquete) != bool(element):
        raise OpError("enquete et element vont ensemble (ex. enquete: \"deces-jean-martin\", element: \"t1\")")
    if enquete and not taches.reference(taches.ligne_reference(enquete, element)):
        raise OpError("element : t1, t2… (tâche manuelle) ou p1, p2… (piste) ; enquete : identifiant d'enquête")
    lignes = []
    if ids:
        lignes.append("Personnes concernées : " + ", ".join(
            f"{ctx.tree.personnes[p].nom_principal.complet} ({p})" for p in dict.fromkeys(ids)))
    if enquete:
        lignes.append(taches.ligne_reference(enquete, element))
    texte = _avec_suffixe(ctx, description.strip(), "\n".join(lignes))
    sid = ctx.tree.next_id("sources")
    s = Source(id=sid, titre=titre.strip(), note=texte, prive=prive,
               tache={"statut": statut, "priorite": priorite})
    ctx.tree.sources[sid] = s
    if o.get("ref"):
        ctx.refs[o["ref"]] = sid
    ctx.summary.append(f"Tâche {sid} : {s.titre}" + (f" (enquête {enquete}, {element})" if enquete else ""))
    _etiqueter(ctx, s, {"tags": [taches.TODO, *_noms_etiquettes(o.get("tags"), "tags")]}, sid, creation=True)


def op_modifier_tache(ctx: Ctx, o: dict) -> None:
    """Statut, priorité, titre, description ou confidentialité d'une tâche existante (#263). ``description``
    remplace le texte de la tâche ; la ligne de référence d'enquête éventuelle est gardée."""
    _tache_permise(ctx)
    inconnus = sorted(set(o) - set(MODIFIER_TACHE_CHAMPS))
    if inconnus:
        raise OpError(f"champs inconnus {inconnus} (acceptés : {', '.join(MODIFIER_TACHE_CHAMPS[2:])})")
    sid = ctx.r(o["id"])
    s = ctx.tree.sources.get(sid)
    if s is None:
        raise OpError(f"Source inconnue : {sid}")
    if not taches.est_tache(s):
        raise OpError(f"{sid} n'est pas une tâche (source sans l'étiquette ToDo) : etiqueter pour en faire une")
    avant = dict(s.tache)
    if "statut" in o:
        s.tache["statut"] = _champ_tache(taches.statut, o["statut"])
    if "priorite" in o:
        s.tache["priorite"] = _champ_tache(taches.priorite, o["priorite"])
    if "titre" in o:
        if not isinstance(o["titre"], str) or not o["titre"].strip():
            raise OpError("titre : texte non vide")
        s.titre = o["titre"].strip()
    if "description" in o:
        if not isinstance(o["description"], str):
            raise OpError("description : texte")
        ref = taches.reference(s.note)
        s.note = _avec_suffixe(ctx, o["description"].strip(), taches.ligne_reference(*ref) if ref else "")
    if "prive" in o:
        if not isinstance(o["prive"], bool):
            raise OpError("prive : true ou false")
        s.prive = o["prive"]
    changes = [f"{k} {avant.get(k) or '∅'} → {s.tache[k]}" for k in ("statut", "priorite")
               if avant.get(k, "") != s.tache.get(k, "")]
    ctx.summary.append(f"Tâche {sid} modifiée" + (f" : {', '.join(changes)}" if changes else ""))
    _etiqueter(ctx, s, o, sid)


def op_modifier_source(ctx: Ctx, o: dict) -> None:
    sid = ctx.r(o["id"])
    s = ctx.tree.sources.get(sid)
    if not s:
        raise OpError(f"Source inconnue : {sid}")
    for k, v in o.get("champs", {}).items():
        if k in ("id", "extra", "medias", "tags") or not hasattr(s, k):
            raise OpError(f"modifier_source : champ {k!r} invalide"
                          + (" (lier un média : ajouter_media / modifier_media, lier_a)" if k == "medias" else "")
                          + (" (étiquettes : tags / tags_retrait au niveau de l'opération)" if k == "tags" else ""))
        setattr(s, k, ctx.r(v) if k in ("depot", "original") else v)
    if o.get("champs"):
        ctx.summary.append(f"Source {sid} modifiée")
    if not _etiqueter(ctx, s, o, sid) and not o.get("champs"):
        ctx.summary.append(f"Source {sid} modifiée")


def op_ajouter_depot(ctx: Ctx, o: dict) -> None:
    rid = ctx.tree.next_id("depots")
    ctx.tree.depots[rid] = Repository(id=rid, nom=o.get("nom", ""), sigle=o.get("sigle", ""),
                                      adresse=o.get("adresse", ""), url=o.get("url", ""))
    if o.get("ref"):
        ctx.refs[o["ref"]] = rid
    ctx.summary.append(f"Dépôt {rid} : {o.get('nom', '')}")
    _etiqueter(ctx, ctx.tree.depots[rid], o, rid, creation=True)


def _liste_citations(ctx: Ctx, cible: dict) -> tuple[list[Citation], str]:
    """Liste de citations visée par cible (ajouter_citation, supprimer_citation) et son libellé."""
    t = cible.get("type")
    if t == "evenement":
        owner, e = _find_event(ctx, ctx.r(cible["uid"]))
        return e.citations, f"{owner.id} {EVENT_LABELS[e.type]}"
    if t == "nom":
        p = ctx.tree.person(ctx.r(cible["id"]))
        idx = int(cible.get("index", 0))
        if not 0 <= idx < len(p.noms):
            raise OpError(f"{p.id} : nom d'index {idx} inexistant")
        return p.noms[idx].citations, f"{p.id} nom"
    if t == "filiation":
        fam = ctx.tree.family(ctx.r(cible["famille"]))
        link = fam.child(ctx.r(cible["enfant"]))
        if not link:
            raise OpError("filiation inexistante")
        return link.citations, f"filiation {link.enfant}/{fam.id}"
    if t in ("personne", "famille", "media"):
        oid = ctx.r(cible["id"])
        coll = {"personne": ctx.tree.personnes, "famille": ctx.tree.familles, "media": ctx.tree.medias}[t]
        if oid not in coll:
            raise OpError(f"{t} inconnu(e) : {oid}")
        return coll[oid].citations, f"{t} {oid}"
    raise OpError("cible.type : evenement | nom | filiation | personne | famille | media")


def op_ajouter_citation(ctx: Ctx, o: dict) -> None:
    c = _citation(ctx, o["citation"])
    liste, what = _liste_citations(ctx, o["cible"])
    liste.append(c)
    ctx.summary.append(f"Citation {c.source} ({c.page}) sur {what}")


def _choisir_citation(ctx: Ctx, liste: list[Citation], what: str, o: dict, op: str) -> int:
    """Position de la citation désignée par source (+ page) et index parmi celles qui correspondent."""
    sid = ctx.r(o.get("source"))
    if not sid:
        raise OpError(f"{op} : source requise (S…)")
    candidates = [i for i, c in enumerate(liste) if c.source == sid and ("page" not in o or c.page == o["page"])]
    if not candidates:
        presentes = [f"{c.source} ({c.page})" for c in liste] or ["aucune"]
        raise OpError(f"{op} : aucune citation {sid}"
                      + (f" ({o['page']})" if "page" in o else "") + f" sur {what} ; présentes : {', '.join(presentes)}")
    if "index" in o:
        k = int(o["index"])
        if not 0 <= k < len(candidates):
            raise OpError(f"{op} : index {k} hors des {len(candidates)} citation(s) correspondantes")
    elif len(candidates) > 1:
        raise OpError(f"{op} : {len(candidates)} citations {sid} sur {what} "
                      f"(pages : {', '.join(repr(liste[i].page) for i in candidates)}) ; préciser page ou index")
    else:
        k = 0
    return candidates[k]


def op_supprimer_citation(ctx: Ctx, o: dict) -> None:
    """Retire une citation précise (#248) : source (+ page) ; index parmi les citations qui correspondent si
    plusieurs. Les médias de la citation restent dans l'arbre."""
    liste, what = _liste_citations(ctx, o["cible"])
    c = liste.pop(_choisir_citation(ctx, liste, what, o, "supprimer_citation"))
    ctx.summary.append(f"Citation {c.source} ({c.page}) retirée de {what}")
    if not liste:
        ctx.warnings.append(f"{what} n'a plus aucune citation.")


def _toutes_listes_citations(tree: Tree):
    """(libellé du porteur, liste de citations) pour chaque liste de citations de l'arbre."""
    for p in tree.personnes.values():
        yield p.id, p.citations
        for i, n in enumerate(p.noms):
            yield f"{p.id} nom" + (f" {i}" if i else ""), n.citations
        for a in p.associations:
            yield f"{p.id} association", a.citations
        for e in p.evenements:
            yield f"{p.id} {EVENT_LABELS.get(e.type, e.type)}", e.citations
            for a in e.associations:
                yield f"{p.id} {EVENT_LABELS.get(e.type, e.type)} association", a.citations
    for f in tree.familles.values():
        yield f.id, f.citations
        for e in f.evenements:
            yield f"{f.id} {EVENT_LABELS.get(e.type, e.type)}", e.citations
            for a in e.associations:
                yield f"{f.id} {EVENT_LABELS.get(e.type, e.type)} association", a.citations
        for link in f.enfants:
            yield f"filiation {link.enfant}/{f.id}", link.citations
    for m in tree.medias.values():
        yield f"média {m.id}", m.citations


def _source_existante(ctx: Ctx, cle: str, op: str) -> str:
    sid = ctx.r(cle)
    if sid not in ctx.tree.sources:
        raise OpError(f"{op} : source inconnue {sid!r}")
    return sid


def op_supprimer_source(ctx: Ctx, o: dict) -> None:
    """Supprime une source (#248). Refus si elle est encore citée, sauf cascade: true (chaque citation retirée
    est listée avec son porteur). Médias de la source détachés, jamais supprimés."""
    sid = _source_existante(ctx, o.get("id"), "supprimer_source")
    derivees = sorted(x.id for x in ctx.tree.sources.values() if x.original == sid and x.id != sid)
    if derivees:
        raise OpError(f"supprimer_source : {sid} est la source originale de {', '.join(derivees)} "
                      "(modifier_source champs.original d'abord)")
    porteurs = [(label, liste) for label, liste in _toutes_listes_citations(ctx.tree)
                if any(c.source == sid for c in liste)]
    if porteurs and not o.get("cascade"):
        noms = [label for label, _ in porteurs]
        raise OpError(f"supprimer_source : {sid} est encore citée par {len(noms)} objet(s) ({', '.join(noms[:20])}"
                      + (", …" if len(noms) > 20 else "") + ") ; cascade: true pour retirer ces citations, "
                      "ou fusionner_sources vers la bonne source")
    for label, liste in porteurs:
        retirees = [c for c in liste if c.source == sid]
        liste[:] = [c for c in liste if c.source != sid]
        for c in retirees:
            ctx.summary.append(f"Citation {sid} ({c.page}) retirée de {label}")
        if not liste:
            ctx.warnings.append(f"{label} n'a plus aucune citation.")
    s = ctx.tree.sources.pop(sid)
    detaches = f" ; médias détachés (conservés) : {', '.join(s.medias)}" if s.medias else ""
    ctx.summary.append(f"Suppression de la source {sid} : {s.titre}{detaches}")


def op_fusionner_sources(ctx: Ctx, o: dict) -> None:
    """Source doublon fondue dans la bonne (#248) : citations réécrites de « de » vers « vers », citations
    devenues identiques (même source et page) sur un même porteur dédoublonnées (médias réunis), médias de la
    source reportés, puis doublon supprimé."""
    de = _source_existante(ctx, o.get("de"), "fusionner_sources")
    vers = _source_existante(ctx, o.get("vers"), "fusionner_sources")
    if de == vers:
        raise OpError("fusionner_sources : « de » et « vers » désignent la même source")
    reecrites, fondues = 0, []
    for label, liste in _toutes_listes_citations(ctx.tree):
        if not any(c.source == de for c in liste):
            continue
        gardees: list[Citation] = []
        for c in liste:
            if c.source == de:
                c.source = vers
                reecrites += 1
            double = next((g for g in gardees if g.source == vers and c.source == vers and g.page == c.page), None)
            if double is None:
                gardees.append(c)
                continue
            for m in c.medias:
                if m not in double.medias:
                    double.medias.append(m)
            double.tags += [x for x in c.tags if x not in double.tags]
            for k in ("texte", "note", "ark"):
                if not getattr(double, k) and getattr(c, k):
                    setattr(double, k, getattr(c, k))
            fondues.append(label)
        liste[:] = gardees
    cible = ctx.tree.sources[vers]
    for x in ctx.tree.sources.values():
        if x.original == de:
            x.original = vers if x.id != vers else ""
    for m in ctx.tree.sources[de].medias:
        if m not in cible.medias:
            cible.medias.append(m)
    cible.tags += [x for x in ctx.tree.sources[de].tags if x not in cible.tags]
    s = ctx.tree.sources.pop(de)
    ctx.sources_cited.add(vers)
    ctx.summary.append(f"Fusion de la source {de} ({s.titre}) dans {vers} ({cible.titre}) : {reecrites} citation(s) "
                       "réécrite(s)" + (f", doublon(s) fondu(s) sur {', '.join(dict.fromkeys(fondues))}" if fondues
                                         else "") + f" ; source {de} supprimée")


def op_ajouter_media(ctx: Ctx, o: dict) -> None:
    fichier = o["fichier"]
    if ctx.media is not None:
        try:
            fichier = ctx.media(fichier)
        except ValueError as exc:
            raise OpError(str(exc)) from exc
    mid = ctx.tree.next_id("medias")
    m = Media(id=mid, fichier=fichier, format=o.get("format", ""), titre=o.get("titre", ""),
              citations=[_citation(ctx, c) for c in o.get("citations", [])])
    ctx.tree.medias[mid] = m
    liens = _lier_media(ctx, mid, o.get("lier_a") or [], "ajouter_media")
    if o.get("ref"):
        ctx.refs[o["ref"]] = mid
    lie = f" (liée à {', '.join(liens)})" if liens else ""
    ctx.summary.append(f"Média {mid} : {m.titre or m.fichier}{lie}")
    _etiqueter(ctx, m, o, mid, creation=True)


MEDIA_CHAMPS = ("fichier", "titre", "format")


def op_modifier_media(ctx: Ctx, o: dict) -> None:
    """Fichier (même contrôle qu'ajouter_media), titre, format d'un média existant ; citations ajoutées (#193)."""
    mid = ctx.r(o["id"])
    m = ctx.tree.medias.get(mid)
    if not m:
        raise OpError(f"Média inconnu : {mid}")
    champs = dict(o.get("champs") or {})
    if "date" in champs:
        raise OpError("modifier_media : champ « date » non pris en charge (un média GEDCOM 7 OBJE ne porte pas de "
                      "date) ; dater l'acte dans sa citation ou dans l'événement qu'il prouve")
    inconnus = sorted(set(champs) - set(MEDIA_CHAMPS))
    if inconnus:
        raise OpError(f"modifier_media : champs non modifiables {inconnus} (modifiables : {', '.join(MEDIA_CHAMPS)})"
                      + (" ; étiquettes : tags / tags_retrait au niveau de l'opération" if "tags" in inconnus else ""))
    citations = o.get("citations_ajout") or []
    lier_a = o.get("lier_a") or []
    if not champs and not citations and not lier_a and not o.get("tags") and not o.get("tags_retrait"):
        raise OpError("modifier_media : rien à modifier (champs, citations_ajout, lier_a, tags ou tags_retrait)")
    changes = []
    if "fichier" in champs:
        fichier = champs["fichier"]
        if not fichier or not isinstance(fichier, str):
            raise OpError("modifier_media : fichier vide")
        if ctx.media is not None:
            try:
                fichier = ctx.media(fichier)
            except ValueError as exc:
                raise OpError(str(exc)) from exc
        if fichier != m.fichier:
            changes.append(f"fichier {m.fichier or '(aucun)'} → {fichier}")
            if "format" not in champs and _suffixe(fichier) != _suffixe(m.fichier):
                m.format = ""  # format déduit de la nouvelle extension à l'écriture (GEDCOM FORM, mime Gramps)
            m.fichier = fichier
    for k in ("titre", "format"):
        if k in champs and champs[k] != getattr(m, k):
            changes.append(f"{k} « {getattr(m, k)} » → « {champs[k]} »")
            setattr(m, k, champs[k])
    for c in citations:
        m.citations.append(_citation(ctx, c))
    if citations:
        changes.append(f"{len(citations)} citation(s) ajoutée(s)")
    liens = _lier_media(ctx, mid, lier_a, "modifier_media", seulement_nouveaux=True)
    if liens:
        changes.append(f"liée à {', '.join(liens)}")
    if changes or champs or citations or lier_a:
        ctx.summary.append(f"Média {mid} modifié : " + ("; ".join(changes) or "inchangé"))
    _etiqueter(ctx, m, o, mid)


def _suffixe(fichier: str) -> str:
    return PurePosixPath(fichier).suffix.lower()


_UID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _lier_media(ctx: Ctx, mid: str, idents: list, op: str, seulement_nouveaux: bool = False) -> list[str]:
    """Lie le média aux cibles de lier_a (sans doublon) ; renvoie leurs libellés pour le résumé (les cibles déjà
    liées avant l'opération sont omises si seulement_nouveaux)."""
    out = []
    for ident in idents:
        owner, label = _media_owner(ctx, ident, op)
        if mid in owner.medias or _obje_conserve(owner, mid):
            if not seulement_nouveaux and label not in out:
                out.append(label)
            continue
        owner.medias.append(mid)
        out.append(label)
    return out


def _obje_conserve(owner, mid: str) -> bool:
    """OBJE vers ce média conservé tel quel dans les extensions (pointeur avec CROP / TITL, GEDCOM) : le lien
    existe déjà, lier_a n'en ajoute pas un second."""
    return any(x.get("tag") == "OBJE" and (x.get("value") or "").strip() == f"@{mid}@"
               for x in getattr(owner, "extra", None) or [] if isinstance(x, dict))


def _media_owner(ctx: Ctx, ident: str, op: str) -> tuple[Person | Family | Source | Event, str]:
    """Cible de lier_a et son libellé : personne (I…), famille (F…), source (S…) ou événement (uid), y compris
    créés plus tôt dans la proposition ($ref)."""
    oid = ctx.r(ident)
    if oid in ctx.tree.personnes:
        return ctx.tree.personnes[oid], oid
    if oid in ctx.tree.familles:
        return ctx.tree.familles[oid], oid
    if oid in ctx.tree.sources:
        return ctx.tree.sources[oid], oid
    if isinstance(oid, str):
        found = ctx.tree.find_event(oid)
        if found:
            owner, e = found
            return e, f"{owner.id} {EVENT_LABELS.get(e.type, e.type)}"
        for prefix, kind in (("I", "personne inconnue"), ("F", "famille inconnue"), ("S", "source inconnue")):
            if oid[:1] == prefix and oid[1:].isdigit():
                raise OpError(f"{op} : lier_a, {kind} : {oid}")
        if _UID.match(oid):
            raise OpError(f"{op} : lier_a, événement inconnu : {oid}")
    raise OpError(f"{op} : lier_a accepte des personnes I…, familles F…, sources S… et événements (uid) "
                  f"({oid!r} non pris en charge)")


def _all_associations(tree: Tree):
    for p in tree.personnes.values():
        yield from p.associations
        for e in p.evenements:
            yield from e.associations
    for f in tree.familles.values():
        for e in f.evenements:
            yield from e.associations


def op_ajouter_association(ctx: Ctx, o: dict) -> None:
    """Témoin, parrain, déclarant… sur un événement (« evenement »: uid) ou une personne (« personne »: id)."""
    a = _association(ctx, o["association"])
    if o.get("evenement"):
        owner, e = _find_event(ctx, ctx.r(o["evenement"]))
        e.associations.append(a)
        where = f"{owner.id} {EVENT_LABELS[e.type]} {e.date}"
    elif o.get("personne"):
        p = ctx.tree.person(ctx.r(o["personne"]))
        p.associations.append(a)
        where = p.label()
    else:
        raise OpError("ajouter_association : 'evenement' (uid) ou 'personne' (id) requis")
    who = ctx.tree.personnes[a.personne].label() if a.personne else a.nom
    ctx.summary.append(f"{a.detail or ROLE_LABELS.get(a.role, a.role)} : {who} — {where}")


def op_supprimer_association(ctx: Ctx, o: dict) -> None:
    idx = int(o.get("index", 0))
    if o.get("evenement"):
        _, e = _find_event(ctx, ctx.r(o["evenement"]))
        lst = e.associations
    else:
        lst = ctx.tree.person(ctx.r(o["personne"])).associations
    if not 0 <= idx < len(lst):
        raise OpError("supprimer_association : index invalide")
    a = lst.pop(idx)
    ctx.summary.append(f"Association retirée : {a.libelle()}")


def _same_event(a: Event, b: Event) -> bool:
    return a.type == b.type and a.date == b.date and (a.lieu.nom if a.lieu else "") == (b.lieu.nom if b.lieu else "")


# Ordre de protection pour la fusion : forcé vivant > déduit > forcé décédé.
_PROTECTION = {"Y": 0, "": 1, "N": 2}
_GRAVITE_STATUT = {"refute": 0, "contradictoire": 1}


def _merge_event(twin: Event, e: Event) -> list[str]:
    """Fusion champ par champ de deux événements jugés identiques ; renvoie les conflits (#43)."""
    conflits = []
    twin.citations += [c for c in e.citations if c not in twin.citations]
    twin.associations += [a for a in e.associations if a not in twin.associations]
    twin.medias += [m for m in e.medias if m not in twin.medias]
    if e.note and e.note not in twin.note:
        twin.note = f"{twin.note}\n{e.note}".strip()
    for champ in ("cause", "age", "valeur", "type_detail"):
        a, b = getattr(twin, champ), getattr(e, champ)
        if b and not a:
            setattr(twin, champ, b)
        elif a and b and a != b:
            twin.note = f"{twin.note}\n{champ} (fiche absorbée) : {b}".strip()
            conflits.append(f"{e.type} {e.date} : {champ} « {a} » conservé, « {b} » reporté en note")
    sa, sb = twin.statut_manuel, e.statut_manuel
    if sb and sb.statut and not (sa and sa.statut):
        twin.statut_manuel = sb
    elif sa and sb and sa.statut and sb.statut and sa.statut != sb.statut:
        grave = min((sa, sb), key=lambda x: _GRAVITE_STATUT.get(x.statut, 9))
        conflits.append(f"{e.type} {e.date} : statut {sa.statut} / {sb.statut} → {grave.statut} retenu")
        twin.statut_manuel = Assertion(statut=grave.statut,
                                       justification=" ; ".join(x for x in (sa.justification, sb.justification) if x))
    twin.prive = twin.prive or e.prive
    twin.extra += [x for x in e.extra if x not in twin.extra]
    twin.tags += [x for x in e.tags if x not in twin.tags]
    return conflits


def op_fusionner_personnes(ctx: Ctx, o: dict) -> None:
    keep_id, gone_id = ctx.r(o["conserver"]), ctx.r(o["absorber"])
    if keep_id == gone_id:
        raise OpError("Fusion d'une personne avec elle-même")
    keep, gone = ctx.tree.person(keep_id), ctx.tree.person(gone_id)
    if keep.sexe in ("M", "F") and gone.sexe in ("M", "F") and keep.sexe != gone.sexe and not o.get("forcer"):
        raise OpError("Sexes différents : fusion refusée (forcer=true pour passer outre, avec justification)")
    if not o.get("justification"):
        raise OpError("fusionner_personnes : justification obligatoire")
    for n in gone.noms:
        if all(n.complet != k.complet for k in keep.noms):
            keep.noms.append(n)
        else:
            target = next(k for k in keep.noms if k.complet == n.complet)
            target.citations += n.citations
    conflits: list[str] = []
    for e in gone.evenements:
        twin = next((k for k in keep.evenements if _same_event(k, e)), None)
        if twin:
            conflits += _merge_event(twin, e)
        else:
            keep.evenements.append(e)
    # protection : la plus restrictive est retenue en attendant une décision explicite (#43)
    if keep.vivant != gone.vivant:
        retenu = min((keep.vivant, gone.vivant), key=lambda v: _PROTECTION[v])
        conflits.append(f"vivant : {keep_id}={keep.vivant or 'déduit'}, {gone_id}={gone.vivant or 'déduit'} → "
                        f"{retenu or 'déduit'} retenu (le plus protecteur ; à confirmer par marquer_vivant)")
        keep.vivant = retenu
    if gone.prive and not keep.prive:
        conflits.append(f"privé : {gone_id} marqué privé → fiche fusionnée marquée privée")
    keep.prive = keep.prive or gone.prive
    keep.extra += [x for x in gone.extra if x not in keep.extra]
    keep.tags += [x for x in gone.tags if x not in keep.tags]
    keep.citations += gone.citations
    keep.associations += gone.associations
    for a in _all_associations(ctx.tree):
        if a.personne == gone_id:
            a.personne = keep_id
    keep.notes += gone.notes + [f"Fusion de {gone.label()} : {o['justification']}"]
    keep.medias += [m for m in gone.medias if m not in keep.medias]
    if keep.sexe == "U":
        keep.sexe = gone.sexe
    for fam in ctx.tree.familles.values():
        if fam.epoux == gone_id:
            fam.epoux = keep_id
        if fam.epouse == gone_id:
            fam.epouse = keep_id
        for link in fam.enfants:
            if link.enfant == gone_id:
                if fam.child(keep_id) and fam.child(keep_id) is not link:
                    fam.child(keep_id).citations += link.citations
                    link.enfant = "__supprime__"
                else:
                    link.enfant = keep_id
        fam.enfants = [c for c in fam.enfants if c.enfant != "__supprime__"]
    keep.famc = list(dict.fromkeys(keep.famc + gone.famc))
    keep.fams = list(dict.fromkeys(keep.fams + gone.fams))
    del ctx.tree.personnes[gone_id]
    ctx.summary.append(f"Fusion : {gone_id} absorbé dans {keep.label()} — {o['justification']}")
    ctx.summary += [f"Fusion, conflit résolu : {c}" for c in conflits]


def op_scinder_personne(ctx: Ctx, o: dict) -> None:
    src = ctx.tree.person(ctx.r(o["id"]))
    if not o.get("justification"):
        raise OpError("scinder_personne : justification obligatoire")
    nid = ctx.tree.next_id("personnes")
    new = Person(id=nid, sexe=o.get("sexe", src.sexe))
    new.noms = [_name(ctx, n) for n in o.get("noms", [])] or [copy.deepcopy(src.nom_principal)]
    move = set(o.get("evenements", []))
    new.evenements = [e for e in src.evenements if e.uid in move]
    src.evenements = [e for e in src.evenements if e.uid not in move]
    if len(new.evenements) != len(move):
        raise OpError("scinder_personne : événement(s) introuvable(s) chez la personne source")
    for fid in o.get("familles_parents", []):
        fid = ctx.r(fid)
        fam = ctx.tree.family(fid)
        link = fam.child(src.id)
        if not link:
            raise OpError(f"{src.id} n'est pas enfant de {fid}")
        link.enfant = nid
        src.famc.remove(fid)
        new.famc.append(fid)
    for fid in o.get("familles_conjoint", []):
        fid = ctx.r(fid)
        fam = ctx.tree.family(fid)
        if fam.epoux == src.id:
            fam.epoux = nid
        elif fam.epouse == src.id:
            fam.epouse = nid
        else:
            raise OpError(f"{src.id} n'est pas conjoint dans {fid}")
        src.fams.remove(fid)
        new.fams.append(fid)
    new.notes.append(f"Scindé de {src.label()} : {o['justification']}")
    src.notes.append(f"Scission vers {nid} : {o['justification']}")
    ctx.tree.personnes[nid] = new
    if o.get("ref"):
        ctx.refs[o["ref"]] = nid
    ctx.summary.append(f"Scission : {new.label()} créé à partir de {src.id} — {o['justification']}")


def op_definir_statut(ctx: Ctx, o: dict) -> None:
    statut = o.get("statut", "")
    if statut not in MANUAL_STATUSES:
        raise OpError("Statut manuel : 'refute', 'contradictoire' ou '' (effacer). "
                      "Les statuts confirmé/probable/hypothèse sont calculés à partir des sources.")
    if statut and not o.get("justification"):
        raise OpError("definir_statut : justification obligatoire")
    a = Assertion(statut=statut, justification=o.get("justification", "")) if statut else None
    cible = o["cible"]
    t = cible.get("type")
    if t == "evenement":
        owner, e = _find_event(ctx, ctx.r(cible["uid"]))
        e.statut_manuel = a
        what = f"{owner.id} {EVENT_LABELS[e.type]} {e.date}"
    elif t == "nom":
        p = ctx.tree.person(ctx.r(cible["id"]))
        p.noms[int(cible.get("index", 0))].statut_manuel = a
        what = f"{p.id} nom"
    elif t == "filiation":
        fam = ctx.tree.family(ctx.r(cible["famille"]))
        link = fam.child(ctx.r(cible["enfant"]))
        if not link:
            raise OpError("filiation inexistante")
        link.statut_manuel = a
        what = f"filiation {link.enfant}/{fam.id}"
    else:
        raise OpError("cible.type : evenement | nom | filiation")
    ctx.summary.append(f"Statut {statut or '(calculé)'} pour {what}" + (f" — {a.justification}" if a else ""))


ETIQUETER_CIBLES = ("personne", "famille", "evenement", "source", "depot", "media", "note", "citation")


def op_etiqueter(ctx: Ctx, o: dict) -> None:
    """Étiquettes d'un objet existant (#262) : cible = {type, id | uid} ; citation : {type: citation, porteur:
    <cible d'ajouter_citation>, source, page?, index?}. Champs tags (ajout) et tags_retrait."""
    cible = o.get("cible") or {}
    t = cible.get("type")
    if not o.get("tags") and not o.get("tags_retrait"):
        raise OpError("etiqueter : tags ou tags_retrait requis")
    if t == "evenement":
        owner, e = _find_event(ctx, ctx.r(cible.get("uid")))
        _etiqueter(ctx, e, o, f"{owner.id} {EVENT_LABELS[e.type]}")
    elif t == "citation":
        if not isinstance(cible.get("porteur"), dict):
            raise OpError("etiqueter : cible.porteur requis pour une citation (même forme que la cible "
                          "d'ajouter_citation)")
        liste, what = _liste_citations(ctx, cible["porteur"])
        c = liste[_choisir_citation(ctx, liste, what, cible, "etiqueter")]
        _etiqueter(ctx, c, o, f"citation {c.source}" + (f" ({c.page})" if c.page else "") + f" sur {what}")
    elif t == "note":
        nid = ctx.r(cible.get("id"))
        if nid not in ctx.tree.notes:
            raise OpError(f"etiqueter : note partagée inconnue {nid!r}")

        def ecrire(tags: list[str]) -> None:
            if tags:
                ctx.tree.notes_tags[nid] = tags
            else:
                ctx.tree.notes_tags.pop(nid, None)

        _etiqueter(ctx, None, o, nid, lire=lambda: list(ctx.tree.notes_tags.get(nid, [])), ecrire=ecrire)
    elif t in ETIQUETER_CIBLES:
        oid = ctx.r(cible.get("id"))
        coll = {"personne": ctx.tree.personnes, "famille": ctx.tree.familles, "source": ctx.tree.sources,
                "depot": ctx.tree.depots, "media": ctx.tree.medias}[t]
        if oid not in coll:
            raise OpError(f"etiqueter : {t} inconnu(e) : {oid!r}")
        _etiqueter(ctx, coll[oid], o, oid)
    else:
        raise OpError(f"etiqueter : cible.type parmi {', '.join(ETIQUETER_CIBLES)}")


def op_marquer_vivant(ctx: Ctx, o: dict) -> None:
    p = ctx.tree.person(ctx.r(o["id"]))
    v = o.get("vivant", "")
    if v not in ("Y", "N", ""):
        raise OpError("vivant : Y, N ou ''")
    p.vivant = v
    ctx.summary.append(f"{p.label()} : vivant={v or 'déduit'}")


def op_remplacer_arbre(ctx: Ctx, o: dict) -> None:
    """Import complet (GEDCOM) : remplace ou fusionne l'arbre (usage interne par l'import)."""
    from ..gedcom.mapping import read_gedcom
    from .integrite import iter_citations

    new: Tree = read_gedcom(o["gedcom_texte"])[0]
    if o.get("mode", "remplacer") == "remplacer":
        ctx.tree.__dict__.update(copy.deepcopy(new).__dict__)
        ctx.summary.append(f"Import : arbre remplacé ({len(new.personnes)} personnes)")
        return
    # mode « ajouter » : TOUTES les références renumérotées (#40), UID en collision réattribués (#39)
    new = copy.deepcopy(new)
    kinds = ("sources", "depots", "medias", "personnes", "familles", "notes")
    maps: dict[str, dict[str, str]] = {k: {} for k in kinds}
    for kind in kinds:
        for old in getattr(new, kind):
            nid = ctx.tree.next_id(kind)
            getattr(ctx.tree, kind)[nid] = None  # réservation
            maps[kind][old] = nid
    P, F, S, R, M, N = (maps[k] for k in ("personnes", "familles", "sources", "depots", "medias", "notes"))

    def note_ref(n: str) -> str:
        if n.startswith("@") and n.endswith("@") and len(n) > 2:
            return f"@{N.get(n.strip('@'), n.strip('@'))}@"
        return n

    used = {e.uid for x in [*ctx.tree.personnes.values(), *ctx.tree.familles.values()] if x for e in x.evenements}
    used |= {x.uid for x in [*ctx.tree.personnes.values(), *ctx.tree.familles.values()] if x}
    renumbered_uids = 0

    def fresh(obj) -> None:
        nonlocal renumbered_uids
        if obj.uid in used:
            obj.uid = new_uid()
            renumbered_uids += 1
        used.add(obj.uid)

    for p in new.personnes.values():
        p.id = P[p.id]
        p.famc = [F.get(f, f) for f in p.famc]
        p.fams = [F.get(f, f) for f in p.fams]
        p.medias = [M.get(m, m) for m in p.medias]
        p.notes = [note_ref(n) for n in p.notes]
        fresh(p)
        for e in p.evenements:
            fresh(e)
    for f in new.familles.values():
        f.id = F[f.id]
        f.epoux, f.epouse = P.get(f.epoux, f.epoux), P.get(f.epouse, f.epouse)
        for c in f.enfants:
            c.enfant = P.get(c.enfant, c.enfant)
        f.medias = [M.get(m, m) for m in f.medias]
        f.notes = [note_ref(n) for n in f.notes]
        fresh(f)
        for e in f.evenements:
            fresh(e)
    for owner in [*new.personnes.values(), *new.familles.values()]:
        for e in owner.evenements:
            e.medias = [M.get(m, m) for m in e.medias]
    for s in new.sources.values():
        s.id, s.depot, s.original = S[s.id], R.get(s.depot, s.depot), S.get(s.original, s.original)
        s.medias = [M.get(m, m) for m in s.medias]
    for r in new.depots.values():
        r.id = R[r.id]
    for m in new.medias.values():
        m.id = M[m.id]
    for owner in [*new.personnes.values(), *new.familles.values(), *new.medias.values()]:
        for c in iter_citations(owner):
            c.source = S.get(c.source, c.source)
            c.medias = [M.get(m, m) for m in c.medias]
        for a in [*getattr(owner, "associations", []),
                  *(a for e in getattr(owner, "evenements", []) for a in e.associations)]:
            a.personne = P.get(a.personne, a.personne)
    for kind, coll in (("personnes", new.personnes), ("familles", new.familles), ("sources", new.sources),
                       ("depots", new.depots), ("medias", new.medias)):
        for obj in coll.values():
            getattr(ctx.tree, kind)[obj.id] = obj
    for old, text in new.notes.items():
        ctx.tree.notes[N[old]] = text
        if old in new.notes_privees:
            ctx.tree.notes_privees.add(N[old])
        if new.notes_tags.get(old):
            ctx.tree.notes_tags[N[old]] = list(new.notes_tags[old])
    ctx.summary.append(f"Import : {len(new.personnes)} personnes ajoutées (renumérotées"
                       + (f", {renumbered_uids} UID réattribués" if renumbered_uids else "") + ") — "
                       "doublons éventuels à traiter par /gen:recoupe puis fusion validée")


def _lier_images_citees(ctx: Ctx) -> None:
    """Images des citations de la proposition liées aussi à ce qu'elles prouvent (#246) ; lier_media: false sur
    la citation pour s'en tenir au lien fin."""
    if not ctx.citations_images:
        return
    from .liens_medias import cibles

    nouvelles = {id(c) for c in ctx.citations_images}
    for mid, liste in cibles(ctx.tree, lambda c: id(c) in nouvelles).items():
        liens = _lier_media(ctx, mid, liste, "citation", seulement_nouveaux=True)
        if liens:
            ctx.summary.append(f"Média {mid} (image de citation) liée à {', '.join(liens)}")


OPS = {name[3:]: fn for name, fn in globals().items() if name.startswith("op_")}


FORMATS_TEXTE = ("texte", "markdown")
CHAMPS_NOTE = ("note", "texte", "notes", "notes_ajout", "description")  # textes de note (description : tâche, #263)


def _markdown(ctx: Ctx, o: dict) -> dict:
    """``format_texte: "markdown"`` (#279) : les textes de note de l'opération (``note``, ``texte`` de citation,
    ``notes``, ``notes_ajout``, y compris dans les citations, événements et ``champs`` imbriqués) sont convertis
    en texte brut + mise en forme (gras, italique, liens) ; la mise en forme est retenue pour le backend gramps
    (``Tree.styles``). Défaut ``texte`` : rien n'est interprété."""
    fmt = o.get("format_texte", "texte")
    if fmt not in FORMATS_TEXTE:
        raise OpError(f"format_texte {fmt!r} : valeurs possibles {' | '.join(FORMATS_TEXTE)}")
    o = {k: v for k, v in o.items() if k != "format_texte"}
    if fmt == "texte":
        return o
    from ..gramps.texte import depuis_markdown

    def conv(v: str) -> str:
        st = depuis_markdown(v)
        if st["tags"]:
            ctx.tree.styles[st["string"]] = st["tags"]
        return st["string"]

    def walk(x):
        if isinstance(x, dict):
            out = {}
            for k, v in x.items():
                if k in CHAMPS_NOTE and isinstance(v, str):
                    out[k] = conv(v)
                elif k in CHAMPS_NOTE and isinstance(v, list):
                    out[k] = [conv(n) if isinstance(n, str) else walk(n) for n in v]
                else:
                    out[k] = walk(v)
            return out
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x

    return walk(o)


def apply_ops(tree: Tree, ops: list[dict], exiger_source: bool = True, media=None, backend: str = "",
              taches_actives: bool = False) -> Ctx:
    """Applique les opérations sur une COPIE de l'arbre ; lève OpError si l'une échoue. media : résolution des
    fichiers d'ajouter_media (Config.media_reference) ; backend : « fichier » ou « gramps » (billets, #261) ;
    taches_actives : GENEALOGISTE_GRAMPS_TACHES (#263)."""
    ctx = Ctx(copy.deepcopy(tree), exiger_source, media, backend, taches_actives)
    for i, o in enumerate(ops, 1):
        name = o.get("op")
        if name not in OPS:
            raise OpError(f"Opération {i} inconnue : {name!r}. Disponibles : {', '.join(sorted(OPS))}")
        try:
            OPS[name](ctx, _markdown(ctx, o))
        except OpError as exc:
            raise OpError(f"Opération {i} ({name}) : {exc}") from exc
        except KeyError as exc:
            raise OpError(f"Opération {i} ({name}) : élément ou paramètre manquant {exc}") from exc
    _lier_images_citees(ctx)
    from .integrite import introduced

    problems = introduced(tree, ctx.tree)
    if problems:
        raise OpError("Proposition refusée, elle romprait l'intégrité de l'arbre : " + " ; ".join(problems[:10]))
    if ctx.taches:  # #263 : étiquette ToDo posée ou retirée = tâche créée ou défaite
        taches.normaliser(ctx.tree, tree)
    refus, avis, resume = objets_interface.controler(tree, ctx.tree)  # #261, #263 : billets et tâches
    if refus:
        raise OpError(" ; ".join(refus))
    ctx.summary += resume
    ctx.warnings += avis
    return ctx
