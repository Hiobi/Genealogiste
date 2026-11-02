"""Export Gramps XML (format 1.7.1, non compressé — importable par Gramps / Gramps Web)."""

from __future__ import annotations

from datetime import date
from xml.sax.saxutils import escape, quoteattr

from ..models import Citation, Event, Tree
from ..normalize.dates import parse_date

TYPES = {
    "BIRT": "Birth", "CHR": "Christening", "BAPM": "Baptism", "DEAT": "Death", "BURI": "Burial",
    "CREM": "Cremation", "OCCU": "Occupation", "RESI": "Residence", "CENS": "Census", "EDUC": "Education",
    "EMIG": "Emigration", "IMMI": "Immigration", "NATU": "Naturalization", "PROB": "Probate", "WILL": "Will",
    "GRAD": "Graduation", "RETI": "Retirement", "CONF": "Confirmation", "FCOM": "First Communion",
    "ORDN": "Ordination", "TITL": "Nobility Title", "RELI": "Religion", "NATI": "Nationality",
    "DSCR": "Description", "PROP": "Property", "MILI": "Military Service", "MARR": "Marriage",
    "MARB": "Marriage Banns", "MARC": "Marriage Contract", "MARL": "Marriage License",
    "MARS": "Marriage Settlement", "DIV": "Divorce", "DIVF": "Divorce Filing", "ENGA": "Engagement",
    "ANUL": "Annulment", "EVEN": "Custom",
}
CAL = {"JULIAN": "Julian", "FRENCH_R": "French Republican"}
QUAL = {"ABT": "about", "CAL": "calculated", "EST": "estimated", "BEF": "before", "AFT": "after"}


def _pt(p) -> str:
    return f"{p.year:04d}" + (f"-{p.month:02d}" if p.month else "") + (f"-{p.day:02d}" if p.day else "")


def _date_xml(value: str) -> str:
    g = parse_date(value) if value else None
    if not g:
        return f"<datestr val={quoteattr(value)}/>" if value else ""
    cal = f" cformat={quoteattr(CAL[g.start.calendar])}" if g.start.calendar in CAL else ""
    if g.qualifier in ("BET", "FROMTO") and g.end:
        tag = "daterange" if g.qualifier == "BET" else "datespan"
        return f"<{tag} start={quoteattr(_pt(g.start))} stop={quoteattr(_pt(g.end))}{cal}/>"
    typ = f" type={quoteattr(QUAL[g.qualifier])}" if g.qualifier in QUAL else ""
    return f"<dateval val={quoteattr(_pt(g.start))}{typ}{cal}/>"


def to_gramps_xml(tree: Tree) -> str:
    places: dict[str, str] = {}
    events: list[tuple[str, Event]] = []
    citations: list[tuple[str, Citation]] = []

    def cit(c: Citation) -> str:
        h = f"_c{len(citations) + 1}"
        citations.append((h, c))
        return h

    def ev(e: Event) -> str:
        h = f"_e{len(events) + 1}"
        events.append((h, e))
        if e.lieu and e.lieu.nom and e.lieu.nom not in places:
            places[e.lieu.nom] = f"_p{len(places) + 1}"
        return h

    people_xml, fam_xml = [], []
    for pid in sorted(tree.personnes):
        p = tree.personnes[pid]
        lines = [f'<person handle="_{pid}" id="{pid}">', f"<gender>{p.sexe if p.sexe in 'MF' else 'U'}</gender>"]
        for i, n in enumerate(p.noms):
            ntype = "Birth Name" if i == 0 else "Also Known As"
            alt = ' alt="1"' if i else ""
            lines.append(f'<name type="{ntype}"{alt}><first>{escape(n.prenoms)}</first>'
                         f"<surname>{escape(n.nom)}</surname>"
                         + (f"<nick>{escape(n.surnom)}</nick>" if n.surnom else "")
                         + "".join(f'<citationref hlink="{cit(c)}"/>' for c in n.citations) + "</name>")
        for e in p.evenements:
            lines.append(f'<eventref hlink="{ev(e)}" role="Primary"/>')
        for f in p.famc:
            lines.append(f'<childof hlink="_{f}"/>')
        for f in p.fams:
            lines.append(f'<parentin hlink="_{f}"/>')
        for c in p.citations:
            lines.append(f'<citationref hlink="{cit(c)}"/>')
        lines.append("</person>")
        people_xml.append("".join(lines))
    for fid in sorted(tree.familles):
        f = tree.familles[fid]
        rel = "Married" if any(e.type == "MARR" for e in f.evenements) else "Unknown"
        lines = [f'<family handle="_{fid}" id="{fid}"><rel type="{rel}"/>']
        if f.epoux:
            lines.append(f'<father hlink="_{f.epoux}"/>')
        if f.epouse:
            lines.append(f'<mother hlink="_{f.epouse}"/>')
        for e in f.evenements:
            lines.append(f'<eventref hlink="{ev(e)}" role="Family"/>')
        for link in f.enfants:
            lines.append(f'<childref hlink="_{link.enfant}">'
                         + "".join(f'<citationref hlink="{cit(c)}"/>' for c in link.citations) + "</childref>")
        for c in f.citations:
            lines.append(f'<citationref hlink="{cit(c)}"/>')
        lines.append("</family>")
        fam_xml.append("".join(lines))
    ev_xml = []
    for h, e in events:
        parts = [f'<event handle="{h}" id="E{h[2:]}"><type>{TYPES.get(e.type, "Custom")}</type>', _date_xml(e.date)]
        if e.lieu and e.lieu.nom:
            parts.append(f'<place hlink="{places[e.lieu.nom]}"/>')
        desc = e.valeur or e.type_detail
        if desc:
            parts.append(f"<description>{escape(desc)}</description>")
        parts += [f'<citationref hlink="{cit(c)}"/>' for c in e.citations]
        parts.append("</event>")
        ev_xml.append("".join(parts))
    cit_xml = []
    for h, c in citations:
        conf = {0: 0, 1: 1, 2: 2, 3: 3}.get(c.qualite, 2)
        cit_xml.append(f'<citation handle="{h}" id="C{h[2:]}">' + (f"<page>{escape(c.page)}</page>" if c.page else "")
                       + f'<confidence>{conf}</confidence><sourceref hlink="_{c.source}"/></citation>')
    src_xml = []
    for sid in sorted(tree.sources):
        s = tree.sources[sid]
        x = f'<source handle="_{sid}" id="{sid}"><stitle>{escape(s.titre)}</stitle>'
        if s.auteur:
            x += f"<sauthor>{escape(s.auteur)}</sauthor>"
        if s.publication:
            x += f"<spubinfo>{escape(s.publication)}</spubinfo>"
        if s.depot:
            x += f'<reporef hlink="_{s.depot}" callno={quoteattr(s.cote)} medium="Book"/>'
        src_xml.append(x + "</source>")
    pl_xml = [f'<placeobj handle="{h}" id="P{h[2:]}" type="City"><pname value={quoteattr(name.split(",")[0].strip())}/>'
              f"<ptitle>{escape(name)}</ptitle></placeobj>" for name, h in places.items()]
    repo_xml = [f'<repository handle="_{rid}" id="{rid}"><rname>{escape(r.nom)}</rname><type>Archive</type></repository>'
                for rid, r in sorted(tree.depots.items())]
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE database PUBLIC "-//Gramps//DTD Gramps XML 1.7.1//EN" '
        '"http://gramps-project.org/xml/1.7.1/grampsxml.dtd">',
        '<database xmlns="http://gramps-project.org/xml/1.7.1/">',
        f'<header><created date="{date.today().isoformat()}" version="5.2.0"/></header>',
    ]
    for tag, items in (("events", ev_xml), ("people", people_xml), ("families", fam_xml), ("citations", cit_xml),
                       ("sources", src_xml), ("places", pl_xml), ("repositories", repo_xml)):
        if items:
            out.append(f"<{tag}>")
            out += items
            out.append(f"</{tag}>")
    out.append("</database>")
    return "\n".join(out) + "\n"
