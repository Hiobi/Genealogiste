"""Opérations d'édition de l'arbre (appliquées sur une copie, jamais directement sur disque).

Chaque opération est un dict {"op": "...", ...}. Les créations acceptent "ref": "x" ; les opérations
suivantes de la même proposition peuvent alors désigner l'objet créé par "$x".
"""

from __future__ import annotations

import copy
from datetime import date

from .. import ark
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
)
from ..normalize.dates import parse_date

MANUAL_STATUSES = ("refute", "contradictoire", "")


class OpError(ValueError):
    pass


class Ctx:
    def __init__(self, tree: Tree, exiger_source: bool = True):
        self.tree = tree
        self.exiger_source = exiger_source
        self.refs: dict[str, str] = {}
        self.summary: list[str] = []
        self.sources_cited: set[str] = set()
        self.warnings: list[str] = []

    def r(self, value: str | None) -> str:
        if value and isinstance(value, str) and value.startswith("$"):
            key = value[1:]
            if key not in self.refs:
                raise OpError(f"Référence inconnue : {value}")
            return self.refs[key]
        return value or ""


# ---------------------------------------------------------------------------- constructeurs

def _date(value: str) -> str:
    if not value:
        return ""
    g = parse_date(value)
    if not g:
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
    for k, allowed in (("type_source", ("originale", "derivee", "composite", "indeterminee")),
                       ("information", ("primaire", "secondaire", "indeterminee")),
                       ("preuve", ("directe", "indirecte", "negative"))):
        if k in d and d[k] not in allowed:
            raise OpError(f"Citation : {k} doit valoir {', '.join(allowed)}")
    if d.get("consultation", "") not in CONSULTATIONS + ("",):
        raise OpError(f"Citation : consultation doit valoir {', '.join(CONSULTATIONS)}")
    d.setdefault("date_consultation", date.today().isoformat())
    ctx.sources_cited.add(d["source"])
    return Citation.from_dict(d)


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
        raise OpError(f"modifier_evenement : champs non modifiables {sorted(champs)}")
    for c in o.get("citations_ajout", []):
        e.citations.append(_citation(ctx, c))
    after = f"{e.date} {e.lieu.nom if e.lieu else ''}".strip()
    ctx.summary.append(f"{owner.id} : {EVENT_LABELS[e.type]} modifié ({before} → {after})")


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
    d = {k: v for k, v in o.items() if k not in ("op", "ref")}
    a = _ark_of(d.get("ark", ""), d.get("url", ""))
    if a:
        same = _source_by_ark(ctx.tree, a)
        if same:  # dédoublonnage : une ressource ARK = une source
            if o.get("ref"):
                ctx.refs[o["ref"]] = same
            ctx.sources_cited.add(same)
            ctx.warnings.append(f"Source {same} réutilisée : même ARK ({a.base}) que « {ctx.tree.sources[same].titre} ».")
            ctx.summary.append(f"Source {same} réutilisée (même ARK {a.base})")
            return
        d["ark"] = a.base
        if not d.get("url"):
            d["url"] = ark.Ark(a.naan, a.nom, "", a.hote).url()
        if not d.get("depot"):
            d["depot"] = _depot_for(ctx, a)
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


def op_modifier_source(ctx: Ctx, o: dict) -> None:
    sid = ctx.r(o["id"])
    s = ctx.tree.sources.get(sid)
    if not s:
        raise OpError(f"Source inconnue : {sid}")
    for k, v in o.get("champs", {}).items():
        if k in ("id", "extra") or not hasattr(s, k):
            raise OpError(f"modifier_source : champ {k!r} invalide")
        setattr(s, k, ctx.r(v) if k in ("depot", "original") else v)
    ctx.summary.append(f"Source {sid} modifiée")


def op_ajouter_depot(ctx: Ctx, o: dict) -> None:
    rid = ctx.tree.next_id("depots")
    ctx.tree.depots[rid] = Repository(id=rid, nom=o.get("nom", ""), sigle=o.get("sigle", ""),
                                      adresse=o.get("adresse", ""), url=o.get("url", ""))
    if o.get("ref"):
        ctx.refs[o["ref"]] = rid
    ctx.summary.append(f"Dépôt {rid} : {o.get('nom', '')}")


def op_ajouter_citation(ctx: Ctx, o: dict) -> None:
    cible = o["cible"]
    c = _citation(ctx, o["citation"])
    t = cible.get("type")
    if t == "evenement":
        owner, e = _find_event(ctx, ctx.r(cible["uid"]))
        e.citations.append(c)
        what = f"{owner.id} {EVENT_LABELS[e.type]}"
    elif t == "nom":
        p = ctx.tree.person(ctx.r(cible["id"]))
        idx = int(cible.get("index", 0))
        p.noms[idx].citations.append(c)
        what = f"{p.id} nom"
    elif t == "filiation":
        fam = ctx.tree.family(ctx.r(cible["famille"]))
        link = fam.child(ctx.r(cible["enfant"]))
        if not link:
            raise OpError("filiation inexistante")
        link.citations.append(c)
        what = f"filiation {link.enfant}/{fam.id}"
    elif t in ("personne", "famille", "media"):
        oid = ctx.r(cible["id"])
        coll = {"personne": ctx.tree.personnes, "famille": ctx.tree.familles, "media": ctx.tree.medias}[t]
        if oid not in coll:
            raise OpError(f"{t} inconnu(e) : {oid}")
        coll[oid].citations.append(c)
        what = f"{t} {oid}"
    else:
        raise OpError("cible.type : evenement | nom | filiation | personne | famille | media")
    ctx.summary.append(f"Citation {c.source} ({c.page}) sur {what}")


def op_ajouter_media(ctx: Ctx, o: dict) -> None:
    mid = ctx.tree.next_id("medias")
    m = Media(id=mid, fichier=o["fichier"], format=o.get("format", ""), titre=o.get("titre", ""),
              citations=[_citation(ctx, c) for c in o.get("citations", [])])
    ctx.tree.medias[mid] = m
    for pid in o.get("lier_a", []):
        ctx.tree.person(ctx.r(pid)).medias.append(mid)
    if o.get("ref"):
        ctx.refs[o["ref"]] = mid
    ctx.summary.append(f"Média {mid} : {m.titre or m.fichier}")


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
    for e in gone.evenements:
        twin = next((k for k in keep.evenements if _same_event(k, e)), None)
        if twin:
            twin.citations += [c for c in e.citations if c not in twin.citations]
            twin.associations += [a for a in e.associations if a not in twin.associations]
        else:
            keep.evenements.append(e)
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

    new: Tree = read_gedcom(o["gedcom_texte"])[0]
    if o.get("mode", "remplacer") == "remplacer":
        ctx.tree.__dict__.update(copy.deepcopy(new).__dict__)
        ctx.summary.append(f"Import : arbre remplacé ({len(new.personnes)} personnes)")
        return
    # mode « ajouter » : renumérotation pour éviter les collisions
    mapping: dict[str, str] = {}
    for kind in ("sources", "depots", "medias", "personnes", "familles"):
        for old in getattr(new, kind):
            nid = ctx.tree.next_id(kind)
            getattr(ctx.tree, kind)[nid] = None  # réservation
            mapping[old] = nid
    for kind in ("sources", "depots", "medias", "personnes", "familles"):
        for old, obj in getattr(new, kind).items():
            obj = copy.deepcopy(obj)
            obj.id = mapping[old]
            getattr(ctx.tree, kind)[obj.id] = obj
    for p in (ctx.tree.personnes[mapping[k]] for k in new.personnes):
        p.famc = [mapping.get(f, f) for f in p.famc]
        p.fams = [mapping.get(f, f) for f in p.fams]
        p.medias = [mapping.get(m, m) for m in p.medias]
    for f in (ctx.tree.familles[mapping[k]] for k in new.familles):
        f.epoux = mapping.get(f.epoux, f.epoux)
        f.epouse = mapping.get(f.epouse, f.epouse)
        for c in f.enfants:
            c.enfant = mapping.get(c.enfant, c.enfant)
    for s in (ctx.tree.sources[mapping[k]] for k in new.sources):
        s.depot = mapping.get(s.depot, s.depot)
        s.original = mapping.get(s.original, s.original)

    def remap_cits(cits):
        for c in cits:
            c.source = mapping.get(c.source, c.source)

    def remap_assos(assos):
        for a in assos:
            a.personne = mapping.get(a.personne, a.personne)
            remap_cits(a.citations)

    for k in new.personnes:
        p = ctx.tree.personnes[mapping[k]]
        remap_cits(p.citations)
        remap_assos(p.associations)
        for n in p.noms:
            remap_cits(n.citations)
        for e in p.evenements:
            remap_cits(e.citations)
            remap_assos(e.associations)
    for k in new.familles:
        f = ctx.tree.familles[mapping[k]]
        remap_cits(f.citations)
        for e in f.evenements:
            remap_cits(e.citations)
            remap_assos(e.associations)
        for c in f.enfants:
            remap_cits(c.citations)
    ctx.summary.append(f"Import : {len(new.personnes)} personnes ajoutées (renumérotées) — "
                       "doublons éventuels à traiter par /gen:recoupe puis fusion validée")


OPS = {name[3:]: fn for name, fn in globals().items() if name.startswith("op_")}


def apply_ops(tree: Tree, ops: list[dict], exiger_source: bool = True) -> Ctx:
    """Applique les opérations sur une COPIE de l'arbre ; lève OpError si l'une échoue."""
    ctx = Ctx(copy.deepcopy(tree), exiger_source)
    for i, o in enumerate(ops, 1):
        name = o.get("op")
        if name not in OPS:
            raise OpError(f"Opération {i} inconnue : {name!r}. Disponibles : {', '.join(sorted(OPS))}")
        try:
            OPS[name](ctx, o)
        except OpError as exc:
            raise OpError(f"Opération {i} ({name}) : {exc}") from exc
        except KeyError as exc:
            raise OpError(f"Opération {i} ({name}) : élément ou paramètre manquant {exc}") from exc
    return ctx
