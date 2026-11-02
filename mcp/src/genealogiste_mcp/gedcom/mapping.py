"""Conversion GEDCOM (5.5.1 / 7) <-> modèle interne, sérialisation déterministe."""

from __future__ import annotations

from ..models import (
    EVENT_LABELS,
    FAM_EVENTS,
    INDI_EVENTS,
    Assertion,
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

EXT_DOC = "https://github.com/hiobi/sosa/blob/main/docs/gedcom-extensions.md"
EXTENSIONS = ["_STAT", "_TYPE", "_INFO", "_PREUVE", "_CONSULT", "_ORIG", "_URL", "_SOUR", "_VIVANT"]
INSEE_EXID = "http://id.insee.fr/geo/commune"


# ============================================================================ lecture

def _citation(n: Node) -> Citation:
    data = n.first("DATA")
    quay = n.val("QUAY")
    return Citation(
        source=strip_xref(n.value),
        page=n.val("PAGE"),
        texte=data.val("TEXT") if data else "",
        qualite=int(quay) if quay.isdigit() else None,
        type_source=n.val("_TYPE", "indeterminee"),
        information=n.val("_INFO", "indeterminee"),
        preuve=n.val("_PREUVE", "directe"),
        date_consultation=n.val("_CONSULT"),
        note=n.val("NOTE"),
    )


def _statut(n: Node) -> Assertion | None:
    s = n.first("_STAT")
    if not s:
        return None
    return Assertion(statut=s.value, justification=s.val("NOTE"))


def _date(value: str, version: int) -> str:
    if not value:
        return ""
    if version >= 7:
        return value
    g = parse_gedcom_date(value)
    return g.gedcom(7) if g else value


def _place(n: Node | None) -> Place | None:
    if n is None:
        return None
    p = Place(nom=n.value)
    for ex in n.all("EXID"):
        if ex.val("TYPE") == INSEE_EXID or not ex.val("TYPE"):
            p.code_insee = ex.value
    mp = n.first("MAP")
    if mp:
        def coord(v: str) -> float | None:
            if not v:
                return None
            sign = -1 if v[0] in "SW" else 1
            try:
                return sign * float(v.lstrip("NSEW"))
            except ValueError:
                return None
        p.latitude, p.longitude = coord(mp.val("LATI")), coord(mp.val("LONG"))
    p.paroisse = n.val("_PAROISSE")
    return p


def _event(n: Node, version: int) -> Event:
    uid = n.val("UID") or n.val("_UID") or new_uid()
    return Event(
        type=n.tag,
        date=_date(n.val("DATE"), version),
        lieu=_place(n.first("PLAC")),
        valeur=n.value if n.value != "Y" else "",
        type_detail=n.val("TYPE"),
        age=n.val("AGE"),
        cause=n.val("CAUS"),
        note="\n".join(x.value for x in n.all("NOTE")),
        citations=[_citation(c) for c in n.all("SOUR")],
        uid=uid,
        statut_manuel=_statut(n),
    )


def _name(n: Node) -> Name:
    given, surname = n.val("GIVN"), n.val("SURN")
    if not (given or surname):
        v = n.value
        if "/" in v:
            given = v.split("/")[0].strip()
            surname = v.split("/")[1].strip() if v.count("/") >= 2 else ""
        else:
            given = v.strip()
    return Name(
        prenoms=given, nom=surname, surnom=n.val("NICK"), type=n.val("TYPE"),
        citations=[_citation(c) for c in n.all("SOUR")],
        uid=n.val("_UID") or new_uid(), statut_manuel=_statut(n),
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
    for r in roots:
        tag = r.tag
        if tag in ("HEAD", "TRLR"):
            continue
        if tag == "INDI":
            p = Person(id=r.xref, uid=r.val("UID") or r.val("_UID") or new_uid())
            for c in r.children:
                if c.tag == "NAME":
                    p.noms.append(_name(c))
                elif c.tag == "SEX":
                    p.sexe = c.value or "U"
                elif c.tag in INDI_EVENTS:
                    p.evenements.append(_event(c, version))
                elif c.tag == "FAMC":
                    fid = strip_xref(c.value)
                    p.famc.append(fid)
                    if c.val("PEDI"):
                        pedi[(fid, p.id)] = c.val("PEDI")
                elif c.tag == "FAMS":
                    p.fams.append(strip_xref(c.value))
                elif c.tag == "SOUR":
                    p.citations.append(_citation(c))
                elif c.tag == "OBJE":
                    p.medias.append(strip_xref(c.value))
                elif c.tag == "NOTE":
                    p.notes.append(c.value)
                elif c.tag == "SNOTE":
                    p.notes.append("@" + strip_xref(c.value) + "@")
                elif c.tag == "_VIVANT":
                    p.vivant = c.value
                elif c.tag in ("UID", "_UID"):
                    continue
                else:
                    p.extra.append(c.to_dict())
            tree.personnes[p.id] = p
        elif tag == "FAM":
            f = Family(id=r.xref, uid=r.val("UID") or r.val("_UID") or new_uid(), statut_manuel=_statut(r))
            for c in r.children:
                if c.tag == "HUSB":
                    f.epoux = strip_xref(c.value)
                elif c.tag == "WIFE":
                    f.epouse = strip_xref(c.value)
                elif c.tag == "CHIL":
                    f.enfants.append(ChildLink(
                        enfant=strip_xref(c.value),
                        citations=[_citation(s) for s in c.all("_SOUR")],
                        statut_manuel=_statut(c),
                    ))
                elif c.tag in FAM_EVENTS:
                    f.evenements.append(_event(c, version))
                elif c.tag == "SOUR":
                    f.citations.append(_citation(c))
                elif c.tag == "NOTE":
                    f.notes.append(c.value)
                elif c.tag in ("UID", "_UID", "_STAT"):
                    continue
                else:
                    f.extra.append(c.to_dict())
            tree.familles[f.id] = f
        elif tag == "SOUR":
            repo = r.first("REPO")
            tree.sources[r.xref] = Source(
                id=r.xref, titre=r.val("TITL"), auteur=r.val("AUTH"), publication=r.val("PUBL"),
                depot=(strip_xref(repo.value) if repo and strip_xref(repo.value) != "VOID" else ""),
                cote=repo.val("CALN") if repo else "",
                url=r.val("_URL") or r.val("WWW"),
                type_source=r.val("_TYPE", "indeterminee"),
                original=strip_xref(r.val("_ORIG")),
                note="\n".join(x.value for x in r.all("NOTE")),
                extra=[c.to_dict() for c in r.children
                       if c.tag not in ("TITL", "AUTH", "PUBL", "REPO", "_URL", "WWW", "_TYPE", "_ORIG", "NOTE")],
            )
        elif tag == "REPO":
            tree.depots[r.xref] = Repository(id=r.xref, nom=r.val("NAME"), adresse=r.val("ADDR"), url=r.val("WWW"))
        elif tag == "OBJE":
            fn = r.first("FILE")
            tree.medias[r.xref] = Media(
                id=r.xref, fichier=fn.value if fn else "", format=(fn.val("FORM") if fn else "") or r.val("FORM"),
                titre=(fn.val("TITL") if fn else "") or r.val("TITL"),
                citations=[_citation(c) for c in r.all("SOUR")],
            )
        elif tag in ("SNOTE", "NOTE") and r.xref:
            tree.notes[r.xref] = r.value
        else:
            tree.extra_records.append(r.to_dict())
            warnings.append(f"Enregistrement {tag} conservé sans interprétation")
    for fam in tree.familles.values():
        for link in fam.enfants:
            link.filiation = pedi.get((fam.id, link.enfant), "")
    info = {
        "version_source": "7.0" if version >= 7 else "5.5.x",
        "personnes": len(tree.personnes),
        "familles": len(tree.familles),
        "sources": len(tree.sources),
        "avertissements": warnings,
    }
    return tree, info


# ============================================================================ écriture

def _num_key(xref: str) -> tuple:
    digits = "".join(ch for ch in xref if ch.isdigit())
    return (xref.rstrip("0123456789"), int(digits) if digits else 0, xref)


def _w_citation(parent: Node, c: Citation, tag: str = "SOUR") -> None:
    n = parent.add(tag, f"@{c.source}@")
    n.add_if("PAGE", c.page)
    if c.texte:
        n.add("DATA").add("TEXT", c.texte)
    if c.qualite is not None:
        n.add("QUAY", str(c.qualite))
    if c.type_source and c.type_source != "indeterminee":
        n.add("_TYPE", c.type_source)
    if c.information and c.information != "indeterminee":
        n.add("_INFO", c.information)
    if c.preuve and c.preuve != "directe":
        n.add("_PREUVE", c.preuve)
    n.add_if("_CONSULT", c.date_consultation)
    n.add_if("NOTE", c.note)


def _w_statut(parent: Node, a: Assertion | None) -> None:
    if a and a.statut:
        s = parent.add("_STAT", a.statut)
        s.add_if("NOTE", a.justification)


def _w_date(value: str, version: int) -> str:
    if version >= 7 or not value:
        return value
    g = parse_gedcom_date(value)
    return g.gedcom(5) if g else value


def _w_event(parent: Node, e: Event, version: int) -> None:
    value = e.valeur
    if not value and e.type in ("BIRT", "DEAT", "MARR", "CHR", "BURI") and not (e.date or e.lieu):
        value = "Y"
    n = parent.add(e.type, value)
    n.add_if("TYPE", e.type_detail)
    n.add_if("DATE", _w_date(e.date, version))
    if e.lieu and (e.lieu.nom or e.lieu.code_insee):
        p = n.add("PLAC", e.lieu.nom)
        if e.lieu.latitude is not None and e.lieu.longitude is not None:
            mp = p.add("MAP")
            mp.add("LATI", ("N" if e.lieu.latitude >= 0 else "S") + f"{abs(e.lieu.latitude):.6f}")
            mp.add("LONG", ("E" if e.lieu.longitude >= 0 else "W") + f"{abs(e.lieu.longitude):.6f}")
        if e.lieu.code_insee:
            if version >= 7:
                p.add("EXID", e.lieu.code_insee).add("TYPE", INSEE_EXID)
            else:
                p.add("_INSEE", e.lieu.code_insee)
        p.add_if("_PAROISSE", e.lieu.paroisse)
    n.add_if("AGE", e.age)
    n.add_if("CAUS", e.cause)
    n.add_if("NOTE", e.note)
    for c in e.citations:
        _w_citation(n, c)
    _w_statut(n, e.statut_manuel)
    n.add("UID" if version >= 7 else "_UID", e.uid)


def _header(version: int, tree: Tree) -> Node:
    h = Node("HEAD")
    gedc = h.add("GEDC")
    if version >= 7:
        gedc.add("VERS", "7.0")
        schma = h.add("SCHMA")
        for t in EXTENSIONS + ["_PAROISSE"]:
            schma.add("TAG", f"{t} {EXT_DOC}#{t.lower()}")
    else:
        gedc.add("VERS", "5.5.1")
        gedc.add("FORM", "LINEAGE-LINKED")
        h.add("CHAR", "UTF-8")
    src = h.add("SOUR", "GENEALOGISTE")
    src.add("NAME", "Plugin Claude Code genealogiste")
    src.add("VERS", "0.1.0")
    h.add("LANG", "fr" if version >= 7 else "French")
    return h


def to_nodes(tree: Tree, version: int = 7) -> list[Node]:
    nodes = [_header(version, tree)]
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
        sex = p.sexe if version >= 7 or p.sexe in ("M", "F", "U") else "U"
        r.add("SEX", sex)
        for e in p.evenements:
            _w_event(r, e, version)
        for fid in p.famc:
            n = r.add("FAMC", f"@{fid}@")
            n.add_if("PEDI", pedi.get((fid, p.id), ""))
        for fid in p.fams:
            r.add("FAMS", f"@{fid}@")
        for c in p.citations:
            _w_citation(r, c)
        for m in p.medias:
            r.add("OBJE", f"@{m}@")
        for note in p.notes:
            if note.startswith("@") and note.endswith("@"):
                r.add("SNOTE" if version >= 7 else "NOTE", note)
            else:
                r.add("NOTE", note)
        r.add_if("_VIVANT", p.vivant)
        for x in p.extra:
            r.children.append(Node.from_dict(x))
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
        for x in f.extra:
            r.children.append(Node.from_dict(x))
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
        if s.type_source and s.type_source != "indeterminee":
            r.add("_TYPE", s.type_source)
        if s.original:
            r.add("_ORIG", f"@{s.original}@")
        r.add_if("NOTE", s.note)
        for x in s.extra:
            r.children.append(Node.from_dict(x))
        nodes.append(r)
    for rid in sorted(tree.depots, key=_num_key):
        d = tree.depots[rid]
        r = Node("REPO", xref=d.id)
        r.add("NAME", d.nom or "(dépôt)")
        r.add_if("ADDR", d.adresse)
        r.add_if("WWW", d.url)
        nodes.append(r)
    for mid in sorted(tree.medias, key=_num_key):
        m = tree.medias[mid]
        r = Node("OBJE", xref=m.id)
        fn = r.add("FILE", m.fichier)
        fn.add("FORM", m.format or _guess_form(m.fichier))
        fn.add_if("TITL", m.titre)
        for c in m.citations:
            _w_citation(r, c)
        nodes.append(r)
    for nid in sorted(tree.notes, key=_num_key):
        nodes.append(Node("SNOTE" if version >= 7 else "NOTE", tree.notes[nid], nid))
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


__all__ = ["read_gedcom", "write_gedcom", "load", "EVENT_LABELS"]
