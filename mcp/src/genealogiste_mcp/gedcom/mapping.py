"""Conversion GEDCOM (5.5.1 / 7) <-> modèle interne, sérialisation déterministe.

Principe : tout ce qui est interprété est mappé sur le modèle ; tout le reste (sous-structures
inconnues d'un événement, d'un nom, d'une citation, d'un lieu, d'un enregistrement) est conservé tel quel
dans `extra` et réécrit à l'identique : un aller-retour ne perd rien.
"""

from __future__ import annotations

from ..models import (
    EVENT_LABELS,
    FAM_EVENTS,
    INDI_EVENTS,
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
from ..normalize.dates import parse_gedcom_date
from .core import Node, parse_lines, serialize, strip_xref

EXT_DOC = "https://github.com/Hiobi/Genealogiste/blob/main/docs/gedcom-extensions.md"
EXTENSIONS = ["_STAT", "_TYPE", "_INFO", "_PREUVE", "_CONSULT", "_VU", "_ORIG", "_URL", "_SOUR", "_VIVANT",
              "_PAROISSE", "_SIGLE", "_ARK", "_RESN"]
RESN_TAGS = ("RESN", "_RESN")


def is_private(value: str) -> bool:
    """RESN « PRIVACY » ou « CONFIDENTIAL » (liste séparée par des virgules en GEDCOM 7)."""
    return any(x.strip().upper() in ("PRIVACY", "CONFIDENTIAL") for x in (value or "").split(","))


def _private_in(n: Node) -> bool:
    return any(c.tag in RESN_TAGS and is_private(c.value) for c in n.children)


def _not_private(c: Node) -> bool:
    return not (c.tag in RESN_TAGS and is_private(c.value))
INSEE_EXID = "http://id.insee.fr/geo/commune"

# RELA (GEDCOM 5.5.1, vocabulaire GeneWeb) <-> ROLE GEDCOM 7 + détail français
RELA_IN = {
    "witness": ("WITN", ""), "temoin": ("WITN", ""), "témoin": ("WITN", ""),
    "godp": ("GODP", ""), "godf": ("GODP", "Parrain"), "godfather": ("GODP", "Parrain"),
    "godm": ("GODP", "Marraine"), "godmother": ("GODP", "Marraine"),
    "parrain": ("GODP", "Parrain"), "marraine": ("GODP", "Marraine"),
    "civil officer": ("OFFICIATOR", "Officier d'état civil"), "registry officer": ("OFFICIATOR", "Officier d'état civil"),
    "officer": ("OFFICIATOR", "Officier d'état civil"),
    "religious officer": ("CLERGY", "Ecclésiastique"), "officiating priest": ("CLERGY", "Prêtre officiant"),
    "informant": ("OTHER", "Déclarant"), "attending": ("OTHER", "Présent"), "mentioned": ("OTHER", "Mentionné"),
    "other": ("OTHER", ""),
}


def rela_of(a: Association) -> str:
    """Valeur RELA comprise par GeneWeb (ged2gwb) pour une association d'événement."""
    d = (a.detail or "").lower()
    if a.role == "GODP":
        return "GODP"
    if a.role == "WITN":
        return "Witness"
    if a.role == "OFFICIATOR":
        return "Civil officer"
    if a.role == "CLERGY":
        return "Religious officer"
    if "déclarant" in d or "declarant" in d:
        return "Informant"
    if "présent" in d or "present" in d:
        return "Attending"
    if "mentionn" in d:
        return "Mentioned"
    return "Other"


def godparent_rela(a: Association) -> str:
    d = (a.detail or "").lower()
    return "GODM" if "marraine" in d else "GODF" if "parrain" in d else "GODP"


# ============================================================================ lecture

class _Reader:
    def __init__(self, tree: Tree, version: int):
        self.tree = tree
        self.version = version
        self.inline: dict[str, str] = {}

    # -- utilitaires --------------------------------------------------------
    def date(self, value: str) -> str:
        if not value:
            return ""
        if self.version >= 7:
            return value
        g = parse_gedcom_date(value)
        return g.gedcom(7) if g else value

    def inline_source(self, text: str) -> str:
        """SOUR sans pointeur (5.5.1 « SOUR texte ») -> enregistrement source créé une fois."""
        key = text.strip()
        if key not in self.inline:
            sid = self.tree.next_id("sources")
            self.tree.sources[sid] = Source(id=sid, titre=key[:250], note=key if len(key) > 250 else "")
            self.inline[key] = sid
        return self.inline[key]

    @staticmethod
    def statut(n: Node) -> Assertion | None:
        s = n.first("_STAT")
        if not s:
            return None
        return Assertion(statut=s.value, justification=s.val("NOTE"))

    # -- structures ---------------------------------------------------------
    def citation(self, n: Node) -> Citation:
        v = n.value.strip()
        if v.startswith("@") and v.endswith("@"):
            src = strip_xref(v)
        else:
            src = self.inline_source(v or "(source sans titre)")
        data = n.first("DATA")
        quay = n.val("QUAY")
        known = {"PAGE", "DATA", "QUAY", "_TYPE", "_INFO", "_PREUVE", "_CONSULT", "_VU", "_ARK", "NOTE", "CONT",
                 "CONC"}
        medias = [strip_xref(x.value) for x in n.all("OBJE") if x.value.strip().startswith("@")]
        if medias:
            known = known | {"OBJE"}
        extra = [c.to_dict() for c in n.children if c.tag not in known and _not_private(c)]
        if data:
            others = [c for c in data.children if c.tag != "TEXT"]
            if others:
                extra.append(Node("DATA", data.value, children=others).to_dict())
        return Citation(
            source=src, page=n.val("PAGE"), texte=data.val("TEXT") if data else "",
            qualite=int(quay) if quay.isdigit() else None,
            type_source=n.val("_TYPE", "indeterminee"), information=n.val("_INFO", "indeterminee"),
            preuve=n.val("_PREUVE", "directe"), date_consultation=n.val("_CONSULT"),
            note="\n".join(x.value for x in n.all("NOTE")), consultation=n.val("_VU"), ark=n.val("_ARK"),
            medias=medias, extra=extra, prive=_private_in(n),
        )

    def place(self, n: Node | None) -> Place | None:
        if n is None:
            return None
        p = Place(nom=n.value)
        for c in n.children:
            if c.tag == "EXID" and (c.val("TYPE") in (INSEE_EXID, "")) and not p.code_insee:
                p.code_insee = c.value
            elif c.tag == "_INSEE":
                p.code_insee = c.value
            elif c.tag == "MAP":
                def coord(v: str) -> float | None:
                    if not v:
                        return None
                    sign = -1 if v[0] in "SW" else 1
                    try:
                        return sign * float(v.lstrip("NSEW"))
                    except ValueError:
                        return None
                p.latitude, p.longitude = coord(c.val("LATI")), coord(c.val("LONG"))
            elif c.tag == "_PAROISSE":
                p.paroisse = c.value
            else:
                p.extra.append(c.to_dict())
        return p

    def association(self, n: Node, level: str) -> Association | None:
        target = strip_xref(n.value)
        typ = n.val("TYPE").upper()
        if typ and typ != "INDI":
            return None  # ASSO vers une famille (renvoi GeneWeb) : conservé brut par l'appelant
        a = Association(personne="" if target in ("", "VOID") else target)
        known = {"TYPE", "RELA", "ROLE", "PHRASE", "SOUR", "NOTE", "_NOM"}
        if n.first("ROLE"):  # GEDCOM 7
            role = n.first("ROLE")
            a.role = role.value.upper() if role.value.upper() in ROLES else "OTHER"
            a.detail = role.val("PHRASE")
            a.nom = n.val("PHRASE")
        else:  # 5.5.1 / GeneWeb
            rela = n.val("RELA").strip()
            role, detail = RELA_IN.get(rela.lower(), ("OTHER", rela))
            a.role, a.detail = role, n.val("NOTE") or detail
            a.nom = n.val("_NOM")
        a.citations = [self.citation(c) for c in n.all("SOUR")]
        a.extra = [c.to_dict() for c in n.children if c.tag not in known]
        if not a.personne and not a.nom:
            return None
        return a

    def event(self, n: Node) -> Event:
        known = {"DATE", "PLAC", "TYPE", "AGE", "CAUS", "NOTE", "SOUR", "UID", "_UID", "_STAT", "ASSO"}
        assos, extra = [], []
        for c in n.children:
            if c.tag == "ASSO":
                a = self.association(c, "event")
                if a:
                    assos.append(a)
                else:
                    extra.append(c.to_dict())
            elif c.tag not in known and _not_private(c):
                extra.append(c.to_dict())
        return Event(
            type=n.tag, date=self.date(n.val("DATE")), lieu=self.place(n.first("PLAC")),
            valeur=n.value if n.value != "Y" else "", type_detail=n.val("TYPE"), age=n.val("AGE"),
            cause=n.val("CAUS"), note="\n".join(x.value for x in n.all("NOTE")),
            citations=[self.citation(c) for c in n.all("SOUR")], associations=assos,
            uid=n.val("UID") or n.val("_UID") or new_uid(), statut_manuel=self.statut(n), extra=extra,
            prive=_private_in(n),
        )

    def name(self, n: Node) -> Name:
        given, surname = n.val("GIVN"), n.val("SURN")
        v = n.value
        if "/" in v:
            given = given or v.split("/")[0].strip()
            surname = surname or (v.split("/")[1].strip() if v.count("/") >= 2 else "")
        elif not (given or surname):
            given = v.strip()
        known = {"GIVN", "SURN", "NICK", "TYPE", "SOUR", "_STAT", "_UID"}
        return Name(
            prenoms=given, nom=surname, surnom=n.val("NICK"), type=n.val("TYPE"),
            citations=[self.citation(c) for c in n.all("SOUR")], statut_manuel=self.statut(n),
            extra=[c.to_dict() for c in n.children if c.tag not in known],
        )


def read_gedcom(text: str) -> tuple[Tree, dict]:
    """Renvoie (arbre, informations) — version détectée, nombre d'éléments, avertissements."""
    roots = parse_lines(text)
    tree = Tree()
    version = 7
    warnings: list[str] = []
    pedi: dict[tuple[str, str], str] = {}
    for r in roots:
        if r.tag == "HEAD":
            gedc = r.first("GEDC")
            v = gedc.val("VERS") if gedc else ""
            version = 7 if v.startswith("7") else 5
    rd = _Reader(tree, version)
    # les enregistrements SOUR d'abord, pour que les sources « en ligne » ne prennent pas leurs numéros
    for r in roots:
        if r.tag == "SOUR" and r.xref:
            repo = r.first("REPO")
            tree.sources[r.xref] = Source(
                id=r.xref, titre=r.val("TITL"), auteur=r.val("AUTH"), publication=r.val("PUBL"),
                depot=(strip_xref(repo.value) if repo and strip_xref(repo.value) != "VOID" else ""),
                cote=repo.val("CALN") if repo else "",
                url=r.val("_URL") or r.val("WWW"), ark=r.val("_ARK"),
                type_source=r.val("_TYPE", "indeterminee"),
                original=strip_xref(r.val("_ORIG")),
                note="\n".join(x.value for x in r.all("NOTE")),
                extra=[c.to_dict() for c in r.children
                       if c.tag not in ("TITL", "AUTH", "PUBL", "REPO", "_URL", "WWW", "_ARK", "_TYPE", "_ORIG",
                                        "NOTE") and _not_private(c)],
                prive=_private_in(r),
            )
    for r in roots:
        tag = r.tag
        if tag in ("HEAD", "TRLR", "SOUR"):
            continue
        if tag == "INDI":
            p = Person(id=r.xref, uid=r.val("UID") or r.val("_UID") or new_uid(), prive=_private_in(r))
            for c in r.children:
                if c.tag == "NAME":
                    p.noms.append(rd.name(c))
                elif c.tag == "SEX":
                    p.sexe = c.value or "U"
                elif c.tag in INDI_EVENTS:
                    p.evenements.append(rd.event(c))
                elif c.tag == "FAMC":
                    fid = strip_xref(c.value)
                    p.famc.append(fid)
                    if c.val("PEDI"):
                        pedi[(fid, p.id)] = c.val("PEDI")
                elif c.tag == "FAMS":
                    p.fams.append(strip_xref(c.value))
                elif c.tag == "SOUR":
                    p.citations.append(rd.citation(c))
                elif c.tag == "ASSO":
                    a = rd.association(c, "indi")
                    if a:
                        p.associations.append(a)
                    else:
                        p.extra.append(c.to_dict())
                elif c.tag == "OBJE":
                    if strip_xref(c.value):
                        p.medias.append(strip_xref(c.value))
                    elif c.first("FILE"):  # OBJE « en ligne » (5.5.1) -> enregistrement média
                        mid = tree.next_id("medias")
                        fn = c.first("FILE")
                        tree.medias[mid] = Media(id=mid, fichier=fn.value, format=fn.val("FORM") or c.val("FORM"),
                                                 titre=fn.val("TITL") or c.val("TITL"))
                        p.medias.append(mid)
                elif c.tag == "NOTE":
                    p.notes.append(c.value)
                elif c.tag == "SNOTE":
                    p.notes.append("@" + strip_xref(c.value) + "@")
                elif c.tag == "_VIVANT":
                    p.vivant = c.value
                elif c.tag in ("UID", "_UID") or not _not_private(c):
                    continue
                else:
                    p.extra.append(c.to_dict())
            tree.personnes[p.id] = p
        elif tag == "FAM":
            f = Family(id=r.xref, uid=r.val("UID") or r.val("_UID") or new_uid(), statut_manuel=rd.statut(r),
                       prive=_private_in(r))
            for c in r.children:
                if c.tag == "HUSB":
                    f.epoux = strip_xref(c.value)
                elif c.tag == "WIFE":
                    f.epouse = strip_xref(c.value)
                elif c.tag == "CHIL":
                    f.enfants.append(ChildLink(
                        enfant=strip_xref(c.value),
                        citations=[rd.citation(s) for s in c.all("_SOUR")],
                        statut_manuel=rd.statut(c),
                    ))
                elif c.tag in FAM_EVENTS:
                    f.evenements.append(rd.event(c))
                elif c.tag == "SOUR":
                    f.citations.append(rd.citation(c))
                elif c.tag == "NOTE":
                    f.notes.append(c.value)
                elif c.tag in ("UID", "_UID", "_STAT") or not _not_private(c):
                    continue
                else:
                    f.extra.append(c.to_dict())
            tree.familles[f.id] = f
        elif tag == "REPO":
            tree.depots[r.xref] = Repository(id=r.xref, nom=r.val("NAME"), sigle=r.val("_SIGLE"),
                                             adresse=r.val("ADDR"), url=r.val("WWW"))
        elif tag == "OBJE":
            fn = r.first("FILE")
            tree.medias[r.xref] = Media(
                id=r.xref, fichier=fn.value if fn else "", format=(fn.val("FORM") if fn else "") or r.val("FORM"),
                titre=(fn.val("TITL") if fn else "") or r.val("TITL"),
                citations=[rd.citation(c) for c in r.all("SOUR")], prive=_private_in(r),
            )
        elif tag in ("SNOTE", "NOTE") and r.xref:
            tree.notes[r.xref] = r.value
            if _private_in(r):
                tree.notes_privees.add(r.xref)
        else:
            tree.extra_records.append(r.to_dict())
            warnings.append(f"Enregistrement {tag} conservé sans interprétation")
    for fam in tree.familles.values():
        for link in fam.enfants:
            link.filiation = pedi.get((fam.id, link.enfant), "")
    n_fam_witnesses = _family_witnesses(tree)
    if n_fam_witnesses:
        warnings.append(f"{n_fam_witnesses} témoin(s) d'union (ASSO vers une famille, GeneWeb) rattaché(s) à "
                        "l'événement de la famille")
    if rd.inline:
        warnings.append(f"{len(rd.inline)} source(s) sans enregistrement (texte libre) converties en sources")
    n_assos = sum(len(p.associations) + sum(len(e.associations) for e in p.evenements)
                  for p in tree.personnes.values()) + sum(len(e.associations) for f in tree.familles.values()
                                                          for e in f.evenements)
    info = {
        "version_source": "7.0" if version >= 7 else "5.5.x",
        "personnes": len(tree.personnes),
        "familles": len(tree.familles),
        "sources": len(tree.sources),
        "associations": n_assos,
        "avertissements": warnings,
    }
    return tree, info


def _family_witnesses(tree: Tree) -> int:
    """GeneWeb exporte « X est témoin du mariage de F » sous X : `1 ASSO @F@ / 2 TYPE FAM / 2 RELA witness`.
    Invalide en GEDCOM 7 (ASSO pointe une personne) : on le rattache à l'événement de la famille (mariage,
    sinon premier événement) comme association de X. Sans événement, le nœud reste brut dans `extra`."""
    moved = 0
    for p in tree.personnes.values():
        keep = []
        for x in p.extra:
            node = Node.from_dict(x)
            fam = tree.familles.get(strip_xref(node.value)) if node.tag == "ASSO" else None
            if not fam or node.val("TYPE").upper() != "FAM" or not fam.evenements:
                keep.append(x)
                continue
            ev = next((e for e in fam.evenements if e.type == "MARR"), fam.evenements[0])
            rela = node.val("RELA").strip()
            role, detail = RELA_IN.get(rela.lower(), ("OTHER", rela))
            if not any(a.personne == p.id and a.role == role for a in ev.associations):
                ev.associations.append(Association(personne=p.id, role=role, detail=node.val("NOTE") or detail))
            moved += 1  # doublon d'un ASSO déjà présent sous l'événement : simplement retiré
        p.extra = keep
    return moved


# ============================================================================ écriture

def _num_key(xref: str) -> tuple:
    digits = "".join(ch for ch in xref if ch.isdigit())
    return (xref.rstrip("0123456789"), int(digits) if digits else 0, xref)


def _extra(parent: Node, extra: list) -> None:
    for x in extra:
        parent.children.append(Node.from_dict(x))


def _w_citation(parent: Node, c: Citation, tag: str = "SOUR") -> None:
    n = parent.add(tag, f"@{c.source}@")
    n.add_if("PAGE", c.page)
    data_extra = [x for x in c.extra if x.get("tag") == "DATA"]
    if c.texte or data_extra:
        d = n.add("DATA")
        for x in data_extra:
            d.children += [Node.from_dict(ch) for ch in x.get("children", [])]
        d.add_if("TEXT", c.texte)
    if c.qualite is not None:
        n.add("QUAY", str(c.qualite))
    if c.type_source and c.type_source != "indeterminee":
        n.add("_TYPE", c.type_source)
    if c.information and c.information != "indeterminee":
        n.add("_INFO", c.information)
    if c.preuve and c.preuve != "directe":
        n.add("_PREUVE", c.preuve)
    n.add_if("_VU", c.consultation)
    n.add_if("_CONSULT", c.date_consultation)
    n.add_if("_ARK", c.ark)
    for m in c.medias:
        n.add("OBJE", f"@{m}@")
    n.add_if("NOTE", c.note)
    if c.prive:
        n.add("_RESN", "PRIVACY")
    _extra(n, [x for x in c.extra if x.get("tag") != "DATA"])


def _w_statut(parent: Node, a: Assertion | None) -> None:
    if a and a.statut:
        s = parent.add("_STAT", a.statut)
        s.add_if("NOTE", a.justification)


def _w_date(value: str, version: int) -> str:
    if version >= 7 or not value:
        return value
    g = parse_gedcom_date(value)
    return g.gedcom(5) if g else value


def _w_association(parent: Node, a: Association, version: int, level: int) -> str | None:
    """Écrit un ASSO ; renvoie un texte de note si l'association ne peut être un ASSO (5.5.1 sans pointeur)."""
    if version >= 7:
        n = parent.add("ASSO", f"@{a.personne}@" if a.personne else "@VOID@")
        n.add_if("PHRASE", a.nom)
        role = n.add("ROLE", a.role if a.role in ROLES else "OTHER")
        role.add_if("PHRASE", a.detail)
        for c in a.citations:
            _w_citation(n, c)
        _extra(n, a.extra)
        return None
    if not a.personne:
        return a.libelle()
    n = parent.add("ASSO", f"@{a.personne}@")
    n.add("TYPE", "INDI")
    n.add("RELA", godparent_rela(a) if level == 1 and a.role == "GODP" else rela_of(a))
    n.add_if("NOTE", a.detail)
    for c in a.citations:
        _w_citation(n, c)
    _extra(n, a.extra)
    return None


def _w_place(parent: Node, pl: Place, version: int) -> None:
    p = parent.add("PLAC", pl.nom)
    if pl.latitude is not None and pl.longitude is not None:
        mp = p.add("MAP")
        mp.add("LATI", ("N" if pl.latitude >= 0 else "S") + f"{abs(pl.latitude):.6f}")
        mp.add("LONG", ("E" if pl.longitude >= 0 else "W") + f"{abs(pl.longitude):.6f}")
    if pl.code_insee:
        if version >= 7:
            p.add("EXID", pl.code_insee).add("TYPE", INSEE_EXID)
        else:
            p.add("_INSEE", pl.code_insee)
    p.add_if("_PAROISSE", pl.paroisse)
    _extra(p, pl.extra)


def _w_event(parent: Node, e: Event, version: int) -> None:
    value = e.valeur
    if not value and e.type in ("BIRT", "DEAT", "MARR", "CHR", "BURI") and not (e.date or e.lieu):
        value = "Y"
    n = parent.add(e.type, value)
    n.add_if("TYPE", e.type_detail)
    n.add_if("DATE", _w_date(e.date, version))
    if e.lieu and (e.lieu.nom or e.lieu.code_insee):
        _w_place(n, e.lieu, version)
    n.add_if("AGE", e.age)
    n.add_if("CAUS", e.cause)
    notes = [e.note] if e.note else []
    for a in e.associations:
        txt = _w_association(n, a, version, 2)
        if txt:
            notes.append(txt)
    if notes:
        n.add("NOTE", "\n".join(notes))
    for c in e.citations:
        _w_citation(n, c)
    _w_statut(n, e.statut_manuel)
    if e.prive:
        n.add("RESN", "PRIVACY")
    _extra(n, e.extra)
    n.add("UID" if version >= 7 else "_UID", e.uid)


def _header(version: int) -> Node:
    h = Node("HEAD")
    gedc = h.add("GEDC")
    if version >= 7:
        gedc.add("VERS", "7.0")
        schma = h.add("SCHMA")
        for t in EXTENSIONS:
            schma.add("TAG", f"{t} {EXT_DOC}#{t.lower()}")
    else:
        gedc.add("VERS", "5.5.1")
        gedc.add("FORM", "LINEAGE-LINKED")
        h.add("CHAR", "UTF-8")
    src = h.add("SOUR", "GENEALOGISTE")
    src.add("NAME", "Plugin Claude Code genealogiste")
    src.add("VERS", "0.2.0")
    h.add("LANG", "fr" if version >= 7 else "French")
    return h


def to_nodes(tree: Tree, version: int = 7) -> list[Node]:
    nodes = [_header(version)]
    pedi: dict[tuple[str, str], str] = {}
    for fam in tree.familles.values():
        for link in fam.enfants:
            if link.filiation:
                pedi[(fam.id, link.enfant)] = link.filiation
    for pid in sorted(tree.personnes, key=_num_key):
        p = tree.personnes[pid]
        r = Node("INDI", xref=p.id)
        for nm in p.noms:
            n = r.add("NAME", f"{nm.prenoms} /{nm.nom}/".strip())
            n.add_if("TYPE", nm.type)
            n.add_if("GIVN", nm.prenoms)
            n.add_if("SURN", nm.nom)
            n.add_if("NICK", nm.surnom)
            for c in nm.citations:
                _w_citation(n, c)
            _w_statut(n, nm.statut_manuel)
            _extra(n, nm.extra)
        sex = p.sexe if version >= 7 or p.sexe in ("M", "F", "U") else "U"
        r.add("SEX", sex)
        for e in p.evenements:
            _w_event(r, e, version)
        for fid in p.famc:
            n = r.add("FAMC", f"@{fid}@")
            n.add_if("PEDI", pedi.get((fid, p.id), ""))
        for fid in p.fams:
            r.add("FAMS", f"@{fid}@")
        notes = list(p.notes)
        for a in p.associations:
            txt = _w_association(r, a, version, 1)
            if txt:
                notes.append(txt)
        for c in p.citations:
            _w_citation(r, c)
        for m in p.medias:
            if m:
                r.add("OBJE", f"@{m}@")
        for note in notes:
            if note.startswith("@") and note.endswith("@"):
                r.add("SNOTE" if version >= 7 else "NOTE", note)
            else:
                r.add("NOTE", note)
        r.add_if("_VIVANT", p.vivant)
        if p.prive:
            r.add("RESN", "PRIVACY")
        _extra(r, p.extra)
        r.add("UID" if version >= 7 else "_UID", p.uid)
        nodes.append(r)
    for fid in sorted(tree.familles, key=_num_key):
        f = tree.familles[fid]
        r = Node("FAM", xref=f.id)
        if f.epoux:
            r.add("HUSB", f"@{f.epoux}@")
        if f.epouse:
            r.add("WIFE", f"@{f.epouse}@")
        for link in f.enfants:
            n = r.add("CHIL", f"@{link.enfant}@")
            for c in link.citations:
                _w_citation(n, c, "_SOUR")
            _w_statut(n, link.statut_manuel)
        for e in f.evenements:
            _w_event(r, e, version)
        for c in f.citations:
            _w_citation(r, c)
        for note in f.notes:
            r.add("NOTE", note)
        _w_statut(r, f.statut_manuel)
        if f.prive:
            r.add("RESN", "PRIVACY")
        _extra(r, f.extra)
        r.add("UID" if version >= 7 else "_UID", f.uid)
        nodes.append(r)
    for sid in sorted(tree.sources, key=_num_key):
        s = tree.sources[sid]
        r = Node("SOUR", xref=s.id)
        r.add_if("AUTH", s.auteur)
        r.add_if("TITL", s.titre)
        r.add_if("PUBL", s.publication)
        if s.depot:
            rp = r.add("REPO", f"@{s.depot}@")
            rp.add_if("CALN", s.cote)
        elif s.cote:
            r.add("REPO", "@VOID@" if version >= 7 else "").add("CALN", s.cote)
        r.add_if("_URL", s.url)
        r.add_if("_ARK", s.ark)
        if s.type_source and s.type_source != "indeterminee":
            r.add("_TYPE", s.type_source)
        if s.original:
            r.add("_ORIG", f"@{s.original}@")
        r.add_if("NOTE", s.note)
        if s.prive:
            r.add("_RESN", "PRIVACY")
        _extra(r, s.extra)
        nodes.append(r)
    for rid in sorted(tree.depots, key=_num_key):
        d = tree.depots[rid]
        r = Node("REPO", xref=d.id)
        r.add("NAME", d.nom or "(dépôt)")
        r.add_if("ADDR", d.adresse)
        r.add_if("WWW", d.url)
        r.add_if("_SIGLE", d.sigle)
        nodes.append(r)
    for mid in sorted(tree.medias, key=_num_key):
        m = tree.medias[mid]
        r = Node("OBJE", xref=m.id)
        fn = r.add("FILE", m.fichier)
        fn.add("FORM", m.format or _guess_form(m.fichier))
        fn.add_if("TITL", m.titre)
        for c in m.citations:
            _w_citation(r, c)
        if m.prive:
            r.add("RESN", "PRIVACY")
        nodes.append(r)
    for nid in sorted(tree.notes, key=_num_key):
        sn = Node("SNOTE" if version >= 7 else "NOTE", tree.notes[nid], nid)
        if nid in tree.notes_privees:
            sn.add("_RESN", "PRIVACY")
        nodes.append(sn)
    for x in tree.extra_records:
        nodes.append(Node.from_dict(x))
    nodes.append(Node("TRLR"))
    return nodes


def _guess_form(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "pdf": "application/pdf",
            "tif": "image/tiff", "tiff": "image/tiff", "txt": "text/plain"}.get(ext, "application/octet-stream")


def write_gedcom(tree: Tree, version: int = 7) -> str:
    return serialize(to_nodes(tree, version), version)


def load(text: str) -> Tree:
    return read_gedcom(text)[0]


__all__ = ["read_gedcom", "write_gedcom", "load", "EVENT_LABELS", "rela_of", "godparent_rela"]
