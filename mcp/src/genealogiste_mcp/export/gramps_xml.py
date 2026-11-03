"""Export Gramps XML (format 1.7.1, non compressé — importable par Gramps / Gramps Web).

Les objets viennent du module de correspondance unique (:mod:`genealogiste_mcp.gramps.mapping`), le même
que celui du mode direct (API Gramps Web) : ce fichier ne fait que sérialiser en XML. Rien du travail de
recherche ne s'y perd (contrairement à l'import GEDCOM de Gramps, qui ignore les extensions `_…`, les
ASSO d'événement et les sous-structures de OCCU/RESI) : URL et type des sources, classification des
citations, témoins et parrains, statut de preuve (notes et étiquettes « Sosa:auto »), lieux.
"""

from __future__ import annotations

from datetime import date
from xml.sax.saxutils import escape, quoteattr

from ..gramps.mapping import GrampsDb, tree_to_gramps_stats
from ..gramps.types import tname
from ..models import Tree

CFORMAT = {1: "Julian", 2: "Hebrew", 3: "French Republican", 4: "Persian", 5: "Islamic", 6: "Swedish"}
MODS = {1: "before", 2: "after", 3: "about", 7: "from", 8: "to"}
QUALS = {1: "estimated", 2: "calculated"}
GENDERS = {0: "F", 1: "M", 2: "U", 3: "X"}


def _h(handle: str) -> str:
    return quoteattr("_" + handle)


def _val(d: int, m: int, y: int) -> str:
    return f"{y:04d}" + (f"-{m:02d}" if m else "") + (f"-{d:02d}" if m and d else "")


def date_xml(dt: dict | None) -> str:
    if not dt:
        return ""
    mod, val = dt.get("modifier", 0), list(dt.get("dateval") or [0, 0, 0, False])
    if mod == 6:
        return f"<datestr val={quoteattr(dt.get('text', ''))}/>" if dt.get("text") else ""
    if not any(val[:3]):
        return ""
    extra = ""
    if dt.get("quality") in QUALS:
        extra += f' quality="{QUALS[dt["quality"]]}"'
    if dt.get("calendar") in CFORMAT:
        extra += f' cformat="{CFORMAT[dt["calendar"]]}"'
    if mod in (4, 5) and len(val) >= 7:
        tag = "daterange" if mod == 4 else "datespan"
        return f'<{tag} start="{_val(*val[:3])}" stop="{_val(*val[4:7])}"{extra}/>'
    typ = f' type="{MODS[mod]}"' if mod in MODS else ""
    return f'<dateval val="{_val(*val[:3])}"{typ}{extra}/>'


def _refs(tag: str, handles: list[str] | None) -> str:
    return "".join(f"<{tag} hlink={_h(h)}/>" for h in handles or [])


def _attr(a: dict, tag: str = "attribute") -> str:
    inner = _refs("citationref", a.get("citation_list")) + _refs("noteref", a.get("note_list"))
    head = f"<{tag} type={quoteattr(tname(a.get('type')))} value={quoteattr(a.get('value') or '')}"
    return head + (f">{inner}</{tag}>" if inner else "/>")


def _text(tag: str, value: str) -> str:
    return f"<{tag}>{escape(value)}</{tag}>" if value else ""


def _common_tail(o: dict) -> str:
    return _refs("tagref", o.get("tag_list"))


def _name(n: dict, alt: bool) -> str:
    out = [f'<name type={quoteattr(tname(n.get("type")) or "Birth Name")}' + (' alt="1"' if alt else "") + ">",
           _text("first", n.get("first_name", "")), _text("call", n.get("call", ""))]
    for s in n.get("surname_list") or []:
        attrs = ""
        if s.get("prefix"):
            attrs += f" prefix={quoteattr(s['prefix'])}"
        if not s.get("primary", True):
            attrs += ' prim="0"'
        out.append(f"<surname{attrs}>{escape(s.get('surname', ''))}</surname>")
    out += [_text("suffix", n.get("suffix", "")), _text("title", n.get("title", "")), _text("nick", n.get("nick", "")),
            _text("familynick", n.get("famnick", "")), date_xml(n.get("date")),
            _refs("noteref", n.get("note_list")), _refs("citationref", n.get("citation_list")), "</name>"]
    return "".join(out)


def _eventref(r: dict) -> str:
    inner = "".join(_attr(a) for a in r.get("attribute_list") or []) + _refs("noteref", r.get("note_list")) + \
        _refs("citationref", r.get("citation_list"))
    return f"<eventref hlink={_h(r['ref'])} role={quoteattr(tname(r.get('role')) or 'Primary')}>{inner}</eventref>"


def _ordered_refs(p: dict) -> list[dict]:
    """Gramps retient la première naissance/le premier décès : la version retenue passe devant."""
    refs = list(p.get("event_ref_list") or [])
    front = [i for i in (p.get("birth_ref_index", -1), p.get("death_ref_index", -1)) if 0 <= i < len(refs)]
    front = list(dict.fromkeys(front))
    return [refs[i] for i in front] + [r for i, r in enumerate(refs) if i not in front]


def db_to_xml(db: GrampsDb) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<!DOCTYPE database PUBLIC "-//Gramps//DTD Gramps XML 1.7.1//EN" '
           '"http://gramps-project.org/xml/1.7.1/grampsxml.dtd">',
           '<database xmlns="http://gramps-project.org/xml/1.7.1/">',
           f'<header><created date="{date.today().isoformat()}" version="5.2.0"/></header>']

    def section(tag: str, items: list[str]) -> None:
        if items:
            out.append(f"<{tag}>")
            out.extend(items)
            out.append(f"</{tag}>")

    def by_id(cls: str):
        return sorted(db.all(cls).values(), key=lambda o: (o.get("gramps_id") or "", o["handle"]))

    section("tags", [f"<tag handle={_h(t['handle'])} name={quoteattr(t.get('name', ''))} "
                     f"color={quoteattr(t.get('color', '#000000000000'))} priority=\"{t.get('priority', 0)}\"/>"
                     for t in sorted(db.all("Tag").values(), key=lambda t: (t.get("priority", 0), t.get("name", "")))])
    section("events", [
        f"<event handle={_h(e['handle'])} id={quoteattr(e.get('gramps_id') or '')}>"
        + _text("type", tname(e.get("type"))) + date_xml(e.get("date"))
        + (f"<place hlink={_h(e['place'])}/>" if e.get("place") else "")
        + _text("description", e.get("description", ""))
        + "".join(_attr(a) for a in e.get("attribute_list") or []) + _refs("noteref", e.get("note_list"))
        + _refs("citationref", e.get("citation_list")) + _refs("objref", [m["ref"] for m in e.get("media_list") or []])
        + _common_tail(e) + "</event>" for e in by_id("Event")])
    people = []
    for p in by_id("Person"):
        x = [f"<person handle={_h(p['handle'])} id={quoteattr(p.get('gramps_id') or '')}>",
             f"<gender>{GENDERS.get(p.get('gender', 2), 'U')}</gender>", _name(p["primary_name"], False)]
        x += [_name(n, True) for n in p.get("alternate_names") or []]
        x += [_eventref(r) for r in _ordered_refs(p)]
        x += [f"<objref hlink={_h(m['ref'])}/>" for m in p.get("media_list") or []]
        for a in p.get("address_list") or []:
            x.append("<address>" + date_xml(a.get("date")) + _text("street", a.get("street", ""))
                     + _text("city", a.get("city", "")) + _text("country", a.get("country", "")) + "</address>")
        x += [_attr(a) for a in p.get("attribute_list") or []]
        x += [f"<url href={quoteattr(u.get('path', ''))} type={quoteattr(tname(u.get('type')))}/>"
              for u in p.get("urls") or []]
        x += [f"<childof hlink={_h(f)}/>" for f in p.get("parent_family_list") or []]
        x += [f"<parentin hlink={_h(f)}/>" for f in p.get("family_list") or []]
        x += [f"<personref hlink={_h(r['ref'])} rel={quoteattr(r.get('rel', ''))}>"
              + _refs("citationref", r.get("citation_list")) + _refs("noteref", r.get("note_list")) + "</personref>"
              for r in p.get("person_ref_list") or []]
        x += [_refs("noteref", p.get("note_list")), _refs("citationref", p.get("citation_list")), _common_tail(p),
              "</person>"]
        people.append("".join(x))
    section("people", people)
    fams = []
    for f in by_id("Family"):
        x = [f"<family handle={_h(f['handle'])} id={quoteattr(f.get('gramps_id') or '')}>"
             f"<rel type={quoteattr(tname(f.get('type')) or 'Unknown')}/>"]
        if f.get("father_handle"):
            x.append(f"<father hlink={_h(f['father_handle'])}/>")
        if f.get("mother_handle"):
            x.append(f"<mother hlink={_h(f['mother_handle'])}/>")
        x += [_eventref(r) for r in f.get("event_ref_list") or []]
        for c in f.get("child_ref_list") or []:
            rel = ""
            for k in ("mrel", "frel"):
                if tname(c.get(k)) not in ("Birth", ""):
                    rel += f" {k}={quoteattr(tname(c.get(k)))}"
            x.append(f"<childref hlink={_h(c['ref'])}{rel}>" + _refs("citationref", c.get("citation_list"))
                     + _refs("noteref", c.get("note_list")) + "</childref>")
        x += [_attr(a) for a in f.get("attribute_list") or []]
        x += [_refs("noteref", f.get("note_list")), _refs("citationref", f.get("citation_list")), _common_tail(f),
              "</family>"]
        fams.append("".join(x))
    section("families", fams)
    section("citations", [
        f"<citation handle={_h(c['handle'])} id={quoteattr(c.get('gramps_id') or '')}>" + date_xml(c.get("date"))
        + _text("page", c.get("page", "")) + f"<confidence>{c.get('confidence', 2)}</confidence>"
        + _refs("noteref", c.get("note_list")) + _refs("objref", [m["ref"] for m in c.get("media_list") or []])
        + "".join(_attr(a, "srcattribute") for a in c.get("attribute_list") or [])
        + (f"<sourceref hlink={_h(c['source_handle'])}/>" if c.get("source_handle") else "")
        + _common_tail(c) + "</citation>" for c in by_id("Citation")])
    section("sources", [
        f"<source handle={_h(s['handle'])} id={quoteattr(s.get('gramps_id') or '')}>" + _text("stitle", s.get("title", ""))
        + _text("sauthor", s.get("author", "")) + _text("spubinfo", s.get("pubinfo", ""))
        + _text("sabbrev", s.get("abbrev", "")) + _refs("noteref", s.get("note_list"))
        + "".join(_attr(a, "srcattribute") for a in s.get("attribute_list") or [])
        + "".join(f"<reporef hlink={_h(r['ref'])} callno={quoteattr(r.get('call_number', ''))} "
                  f"medium={quoteattr(tname(r.get('media_type')) or 'Book')}/>" for r in s.get("reporef_list") or [])
        + _common_tail(s) + "</source>" for s in by_id("Source")])
    places = []
    for pl in by_id("Place"):
        x = (f"<placeobj handle={_h(pl['handle'])} id={quoteattr(pl.get('gramps_id') or '')} "
             f"type={quoteattr(tname(pl.get('place_type')) or 'Unknown')}>" + _text("ptitle", pl.get("title", ""))
             + f"<pname value={quoteattr((pl.get('name') or {}).get('value', ''))}/>" + _text("code", pl.get("code", "")))
        if pl.get("lat") and pl.get("long"):
            x += f"<coord long={quoteattr(str(pl['long']))} lat={quoteattr(str(pl['lat']))}/>"
        x += "".join(f"<placeref hlink={_h(r['ref'])}/>" for r in pl.get("placeref_list") or [])
        x += _refs("noteref", pl.get("note_list")) + _refs("citationref", pl.get("citation_list")) + _common_tail(pl)
        places.append(x + "</placeobj>")
    section("places", places)
    section("objects", [
        f"<object handle={_h(m['handle'])} id={quoteattr(m.get('gramps_id') or '')}>"
        f"<file src={quoteattr(m.get('path', ''))} mime={quoteattr(m.get('mime', ''))} "
        f"description={quoteattr(m.get('desc') or m.get('path', ''))}/>"
        + _refs("noteref", m.get("note_list")) + _refs("citationref", m.get("citation_list")) + _common_tail(m)
        + "</object>" for m in by_id("Media")])
    repos = []
    for r in by_id("Repository"):
        x = (f"<repository handle={_h(r['handle'])} id={quoteattr(r.get('gramps_id') or '')}>"
             + _text("rname", r.get("name", "")) + _text("type", tname(r.get("type")) or "Archive"))
        for a in r.get("address_list") or []:
            x += "<address>" + _text("street", a.get("street", "")) + _text("city", a.get("city", "")) + "</address>"
        x += "".join(f"<url href={quoteattr(u.get('path', ''))} type={quoteattr(tname(u.get('type')))}/>"
                     for u in r.get("urls") or [])
        repos.append(x + _refs("noteref", r.get("note_list")) + _common_tail(r) + "</repository>")
    section("repositories", repos)
    notes = []
    for n in by_id("Note"):
        text = (n.get("text") or {})
        styles = "".join(
            f"<style name={quoteattr(tname(t.get('name')))}"
            + (f" value={quoteattr(str(t['value']))}" if t.get("value") is not None else "") + ">"
            + "".join(f'<range start="{a}" end="{b}"/>' for a, b in t.get("ranges") or []) + "</style>"
            for t in text.get("tags") or [])
        notes.append(f"<note handle={_h(n['handle'])} id={quoteattr(n.get('gramps_id') or '')} "
                     f"type={quoteattr(tname(n.get('type')) or 'General')}>"
                     f"<text>{escape(text.get('string', ''))}</text>{styles}{_common_tail(n)}</note>")
    section("notes", notes)
    out.append("</database>")
    return "\n".join(out) + "\n"


def to_gramps_xml(tree: Tree, strict: bool = False) -> str:
    return to_gramps_xml_stats(tree, strict)[0]


def to_gramps_xml_stats(tree: Tree, strict: bool = False) -> tuple[str, dict]:
    db, stats = tree_to_gramps_stats(tree, None, strict)
    return db_to_xml(db), stats
