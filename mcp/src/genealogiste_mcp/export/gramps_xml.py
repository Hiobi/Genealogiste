"""Export Gramps XML (format 1.7.1, non compressé — importable par Gramps / Gramps Web).

Format natif de Gramps : rien du travail de recherche ne doit s'y perdre (contrairement à l'import GEDCOM
de Gramps, qui ignore les extensions `_…`, les ASSO d'événement et les sous-structures de OCCU/RESI).
- sources : URL en note cliquable, type (originale/dérivée/composite) et source d'origine en attributs ;
- citations : page, qualité, transcription et note en notes, classification (vu, information, preuve,
  date de consultation) en attributs ;
- événements : âge, cause, paroisse en attributs, statut de preuve en note de recherche et en étiquette,
  témoins/parrains/officiers de l'arbre en références d'événement avec leur rôle, témoins seulement
  nommés en note ;
- parrains/marraines de niveau individu en associations (personref) ;
- notes des personnes, familles, sources et notes partagées ; fiche de preuve en note de recherche ;
- lieux avec coordonnées et code INSEE ; filiations adoptives/nourricières ; médias.
"""

from __future__ import annotations

from datetime import date
from xml.sax.saxutils import escape, quoteattr

from ..citations import INFOS, PREUVES, VU
from ..citations import TYPES as SOURCE_TYPE_LABELS
from ..evidence import LABELS, assess_person
from ..models import ROLE_LABELS, UNIQUE_EVENTS, Association, Citation, Event, Tree
from ..normalize.dates import parse_date
from .geneweb import ICON, RANK, _proof_line, proof_summary

TYPES = {
    "BIRT": "Birth", "CHR": "Christening", "BAPM": "Baptism", "DEAT": "Death", "BURI": "Burial",
    "CREM": "Cremation", "OCCU": "Occupation", "RESI": "Residence", "CENS": "Census", "EDUC": "Education",
    "EMIG": "Emigration", "IMMI": "Immigration", "NATU": "Naturalization", "PROB": "Probate", "WILL": "Will",
    "GRAD": "Graduation", "RETI": "Retirement", "CONF": "Confirmation", "FCOM": "First Communion",
    "ORDN": "Ordination", "TITL": "Nobility Title", "RELI": "Religion", "NATI": "Nationality",
    "DSCR": "Description", "PROP": "Property", "MILI": "Military Service", "MARR": "Marriage",
    "MARB": "Marriage Banns", "MARC": "Marriage Contract", "MARL": "Marriage License",
    "MARS": "Marriage Settlement", "DIV": "Divorce", "DIVF": "Divorce Filing", "ENGA": "Engagement",
    "ANUL": "Annulment",
}
CAL = {"JULIAN": "Julian", "FRENCH_R": "French Republican"}
QUAL = {"ABT": "about", "CAL": "calculated", "EST": "estimated", "BEF": "before", "AFT": "after"}
NAME_TYPES = {"BIRTH": "Birth Name", "MARRIED": "Married Name", "AKA": "Also Known As"}
PEDI = {"BIRTH": "Birth", "ADOPTED": "Adopted", "FOSTER": "Foster", "SEALING": "Sealed"}
# Rôles standard de Gramps (EventRoleType) ; les autres deviennent des rôles personnalisés en français
EVENT_ROLES = {"WITN": "Witness", "CLERGY": "Clergy", "OFFICIATOR": "Celebrant"}
STATUS_COLORS = {"confirme": "#2e7d32", "probable": "#689f38", "hypothese": "#f9a825",
                 "contradictoire": "#ef6c00", "refute": "#c62828", "non_source": "#757575"}


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


def _attr(tag: str, typ: str, value: str) -> str:
    return f"<{tag} type={quoteattr(typ)} value={quoteattr(value)}/>" if value else ""


def event_role(a: Association) -> str:
    """Rôle Gramps d'un intervenant : standard si possible, sinon le libellé français (« Parrain »)."""
    d = (a.detail or "").lower()
    if a.role in EVENT_ROLES:
        return EVENT_ROLES[a.role]
    if "déclarant" in d or "declarant" in d:
        return "Informant"
    if a.detail:
        return a.detail.split(",")[0].strip()
    return ROLE_LABELS.get(a.role, a.role)


def _best_first(events: list[Event], facts: dict) -> list[Event]:
    """Gramps retient la première naissance/le premier décès : la version la mieux prouvée passe devant."""
    def key(ie):
        i, e = ie
        if e.type not in UNIQUE_EVENTS:
            return (i, 0, 0)
        f = facts.get(e.uid) or {}
        first = min(j for j, x in enumerate(events) if x.type == e.type)
        return (first, RANK.get(f.get("statut", "non_source"), 4), -f.get("points", 0))
    return [e for _, e in sorted(enumerate(events), key=key)]


class _Builder:
    def __init__(self, tree: Tree, strict: bool):
        self.t = tree
        self.strict = strict
        self.places: dict[str, tuple[str, object]] = {}
        self.events: list[str] = []
        self.citations: list[str] = []
        self.notes: list[str] = []
        self.tags: dict[str, str] = {}
        self.shared_notes: dict[str, str] = {}
        # pid -> [(handle d'événement, rôle, handle de note ou "")] : témoins, parrains… membres de l'arbre
        self.roles: dict[str, list[tuple[str, str, str]]] = {}
        self.stats = {"personnes": 0, "familles": 0, "evenements": 0, "citations": 0, "notes": 0,
                      "temoins_lies": 0, "temoins_nommes": 0, "associations": 0, "sources_url": 0}

    # ------------------------------------------------------------------ objets secondaires
    def note(self, text: str, typ: str = "General", url: str = "") -> str:
        h = f"_n{len(self.notes) + 1}"
        style = ""
        if url and url in text:
            start = text.index(url)
            style = (f'<style name="link" value={quoteattr(url)}>'
                     f'<range start="{start}" end="{start + len(url)}"/></style>')
        self.notes.append(f'<note handle="{h}" id="N{len(self.notes) + 1:04d}" type={quoteattr(typ)}>'
                          f"<text>{escape(text)}</text>{style}</note>")
        self.stats["notes"] += 1
        return h

    def noteref(self, text: str, typ: str = "General", url: str = "") -> str:
        return f'<noteref hlink="{self.note(text, typ, url)}"/>' if text else ""

    def note_value(self, value: str) -> str:
        """Note de personne/famille : texte libre, ou renvoi @N1@ vers une note partagée."""
        if value.startswith("@") and value.endswith("@"):
            key = value.strip("@")
            if key in self.t.notes:
                if key not in self.shared_notes:
                    self.shared_notes[key] = self.note(self.t.notes[key])
                return f'<noteref hlink="{self.shared_notes[key]}"/>'
            return ""
        return self.noteref(value)

    def tag(self, statut: str) -> str:
        if statut not in self.tags:
            self.tags[statut] = f"_t{len(self.tags) + 1}"
        return f'<tagref hlink="{self.tags[statut]}"/>'

    def cit(self, c: Citation) -> str:
        h = f"_c{len(self.citations) + 1}"
        conf = {0: 0, 1: 1, 2: 2, 3: 3}.get(c.qualite, 2)
        stype = c.type_source if c.type_source != "indeterminee" else ""
        parts = [f'<citation handle="{h}" id="C{len(self.citations) + 1:04d}">',
                 f"<page>{escape(c.page)}</page>" if c.page else "", f"<confidence>{conf}</confidence>",
                 self.noteref(c.texte, "Transcript"), self.noteref(c.note, "Citation"),
                 _attr("srcattribute", "Consulté", VU.get(c.consultation, c.consultation)),
                 _attr("srcattribute", "Type de source", SOURCE_TYPE_LABELS.get(stype, "")),
                 _attr("srcattribute", "Information", INFOS.get(c.information, "")),
                 _attr("srcattribute", "Preuve", PREUVES.get(c.preuve, "")),
                 _attr("srcattribute", "Date de consultation", c.date_consultation),
                 f'<sourceref hlink="_{c.source}"/></citation>']
        self.citations.append("".join(parts))
        self.stats["citations"] += 1
        return f'<citationref hlink="{h}"/>'

    def place(self, e: Event) -> str:
        pl = e.lieu
        if not (pl and pl.nom):
            return ""
        if pl.nom not in self.places:
            self.places[pl.nom] = (f"_p{len(self.places) + 1}", pl)
        else:  # garder les coordonnées / le code INSEE d'une occurrence qui les porte
            h, known = self.places[pl.nom]
            if (known.latitude is None and pl.latitude is not None) or (not known.code_insee and pl.code_insee):
                self.places[pl.nom] = (h, pl)
        return f'<place hlink="{self.places[pl.nom][0]}"/>'

    # ------------------------------------------------------------------ événements
    def event(self, e: Event, fact: dict | None) -> tuple[str, str]:
        """Écrit l'événement ; renvoie (handle, attributs de la référence principale : âge)."""
        h = f"_e{len(self.events) + 1}"
        typ = TYPES.get(e.type) or e.type_detail or e.valeur or "Custom"
        desc = e.valeur if e.type != "EVEN" else (e.valeur if e.valeur != typ else "")
        if e.type != "EVEN" and e.type_detail:
            desc = f"{desc} ({e.type_detail})" if desc else e.type_detail
        notes = [self.noteref(_proof_line(fact), "Research") if fact else "", self.noteref(e.note, "Event Note")]
        named = []
        cites = list(e.citations)
        for a in e.associations:
            if a.personne and a.personne in self.t.personnes:
                role = event_role(a)
                extra = a.detail if a.detail and a.detail != role else ""
                self.roles.setdefault(a.personne, []).append((h, role, extra))
                self.stats["temoins_lies"] += 1
            elif a.nom:
                named.append(a.libelle())
                self.stats["temoins_nommes"] += 1
            cites += [c for c in a.citations if (c.source, c.page) not in {(x.source, x.page) for x in cites}]
        if named:
            notes.append(self.noteref("Témoins et intervenants : " + " ; ".join(named), "Event Note"))
        parts = [f'<event handle="{h}" id="E{len(self.events) + 1:04d}"><type>{escape(typ)}</type>',
                 _date_xml(e.date), self.place(e),
                 f"<description>{escape(desc)}</description>" if desc else "",
                 _attr("attribute", "Cause", e.cause),
                 _attr("attribute", "Paroisse", e.lieu.paroisse if e.lieu else ""),
                 *notes, *(self.cit(c) for c in cites),
                 self.tag(fact["statut"]) if fact and fact.get("statut") else "", "</event>"]
        self.events.append("".join(parts))
        self.stats["evenements"] += 1
        return h, _attr("attribute", "Age", e.age)

    # ------------------------------------------------------------------ construction
    def build(self) -> str:
        t = self.t
        people_parts: dict[str, list[str]] = {}
        fam_xml = []
        # familles d'abord : leurs événements peuvent nommer des témoins (références à poser sur les personnes)
        for fid in sorted(t.familles):
            f = t.familles[fid]
            facts = {}
            for spouse in (f.epoux, f.epouse):
                if spouse in t.personnes:
                    facts.update({x["uid"]: x for x in assess_person(t, spouse, self.strict)
                                  if x.get("famille") == fid and x.get("uid")})
                    break
            rel = "Married" if any(e.type == "MARR" for e in f.evenements) else "Unknown"
            lines = [f'<family handle="_{fid}" id="{fid}"><rel type="{rel}"/>']
            if f.epoux:
                lines.append(f'<father hlink="_{f.epoux}"/>')
            if f.epouse:
                lines.append(f'<mother hlink="_{f.epouse}"/>')
            for e in _best_first(f.evenements, facts):
                h, _ = self.event(e, facts.get(e.uid))
                lines.append(f'<eventref hlink="{h}" role="Family"/>')
            filiations = []
            for link in f.enfants:
                rel_attr = f' mrel="{PEDI[link.filiation]}" frel="{PEDI[link.filiation]}"' \
                    if link.filiation in PEDI and link.filiation != "BIRTH" else ""
                lines.append(f'<childref hlink="_{link.enfant}"{rel_attr}>'
                             + "".join(self.cit(c) for c in link.citations) + "</childref>")
                if link.enfant in t.personnes:
                    fact = next((x for x in assess_person(t, link.enfant, self.strict)
                                 if x["fait"] == "filiation" and x.get("famille") == fid), None)
                    if fact:
                        filiations.append(f"Filiation de {t.personnes[link.enfant].nom_principal.complet} : "
                                          f"{ICON[fact['statut']]} {LABELS[fact['statut']]}")
            if filiations:
                lines.append(self.noteref("\n".join(filiations), "Research"))
            lines += [self.note_value(n) for n in f.notes]
            lines += [self.cit(c) for c in f.citations]
            lines.append("</family>")
            fam_xml.append("".join(lines))
            self.stats["familles"] += 1
        for pid in sorted(t.personnes):
            p = t.personnes[pid]
            facts = assess_person(t, pid, self.strict)
            by_uid = {f["uid"]: f for f in facts if f.get("uid")}
            lines = [f"<gender>{p.sexe if p.sexe in 'MF' else 'U'}</gender>"]
            for i, n in enumerate(p.noms):
                ntype = NAME_TYPES.get(n.type.upper(), "Birth Name" if i == 0 else "Also Known As")
                alt = ' alt="1"' if i else ""
                lines.append(f'<name type="{ntype}"{alt}><first>{escape(n.prenoms)}</first>'
                             f"<surname>{escape(n.nom)}</surname>"
                             + (f"<nick>{escape(n.surnom)}</nick>" if n.surnom else "")
                             + "".join(self.cit(c) for c in n.citations) + "</name>")
            for e in _best_first(p.evenements, by_uid):
                h, age = self.event(e, by_uid.get(e.uid))
                lines.append(f'<eventref hlink="{h}" role="Primary">{age}</eventref>')
            people_parts[pid] = lines
            # suite écrite après le passage sur tous les événements (rôles de témoin)
            tail = [f'<objref hlink="_{m}"/>' for m in p.medias if m in t.medias]
            tail += [f'<childof hlink="_{f}"/>' for f in p.famc]
            tail += [f'<parentin hlink="_{f}"/>' for f in p.fams]
            named = []
            for a in p.associations:
                if a.personne and a.personne in t.personnes:
                    rel = a.detail or ROLE_LABELS.get(a.role, a.role)
                    tail.append(f'<personref hlink="_{a.personne}" rel={quoteattr(rel)}>'
                                + "".join(self.cit(c) for c in a.citations) + "</personref>")
                    self.stats["associations"] += 1
                elif a.nom:
                    named.append(a.libelle())
            tail.append(self.noteref(proof_summary(pid, facts), "Research"))
            if named:
                tail.append(self.noteref("Associations : " + " ; ".join(named), "Person Note"))
            tail += [self.note_value(n) for n in p.notes]
            tail += [self.cit(c) for c in p.citations]
            people_parts[pid].append(("TAIL", tail))
            self.stats["personnes"] += 1
        people_xml = []
        for pid in sorted(t.personnes):
            head = [x for x in people_parts[pid] if not isinstance(x, tuple)]
            tail = next(x[1] for x in people_parts[pid] if isinstance(x, tuple))
            witness = []
            for h, role, extra in self.roles.get(pid, []):
                witness.append(f'<eventref hlink="{h}" role={quoteattr(role)}>'
                               + self.noteref(extra, "Event Reference Note") + "</eventref>")
            people_xml.append(f'<person handle="_{pid}" id="{pid}">' + "".join(head + witness + tail) + "</person>")
        src_xml = []
        for sid in sorted(t.sources):
            s = t.sources[sid]
            x = [f'<source handle="_{sid}" id="{sid}"><stitle>{escape(s.titre)}</stitle>']
            if s.auteur:
                x.append(f"<sauthor>{escape(s.auteur)}</sauthor>")
            if s.publication:
                x.append(f"<spubinfo>{escape(s.publication)}</spubinfo>")
            if s.url:
                x.append(self.noteref(f"Lien : {s.url}", "Source Note", s.url))
                self.stats["sources_url"] += 1
            x.append(self.noteref(s.note, "Source Note"))
            x.append(_attr("srcattribute", "Type de source", SOURCE_TYPE_LABELS.get(s.type_source, "")))
            if s.original:
                orig = t.sources.get(s.original)
                x.append(_attr("srcattribute", "Dérivée de", f"{s.original} — {orig.titre}" if orig else s.original))
            if s.url:
                x.append(_attr("srcattribute", "URL", s.url))
            if s.depot:
                x.append(f'<reporef hlink="_{s.depot}" callno={quoteattr(s.cote)} medium="Book"/>')
            src_xml.append("".join(x) + "</source>")
        pl_xml = []
        for name, (h, pl) in self.places.items():
            x = (f'<placeobj handle="{h}" id="P{h[2:]}" type="City"><ptitle>{escape(name)}</ptitle>'
                 f"<pname value={quoteattr(name.split(',')[0].strip())}/>")
            if pl.code_insee:
                x += f"<code>{escape(pl.code_insee)}</code>"
            if pl.latitude is not None and pl.longitude is not None:
                x += f'<coord long="{pl.longitude}" lat="{pl.latitude}"/>'
            pl_xml.append(x + "</placeobj>")
        obj_xml = []
        for mid in sorted(t.medias):
            m = t.medias[mid]
            obj_xml.append(f'<object handle="_{mid}" id="{mid}"><file src={quoteattr(m.fichier)} '
                           f"mime={quoteattr(m.format or '')} description={quoteattr(m.titre or m.fichier)}/>"
                           + "".join(self.cit(c) for c in m.citations) + "</object>")
        repo_xml = []
        for rid, r in sorted(t.depots.items()):
            x = f'<repository handle="_{rid}" id="{rid}"><rname>{escape(r.nom or r.sigle)}</rname><type>Archive</type>'
            if r.adresse:
                x += f"<address><street>{escape(r.adresse)}</street></address>"
            if r.url:
                x += f'<url href={quoteattr(r.url)} type="Web Home"/>'
            if r.sigle and r.nom:
                x += self.noteref(f"Sigle : {r.sigle}")
            repo_xml.append(x + "</repository>")
        tag_xml = [f'<tag handle="{h}" name={quoteattr("Preuve : " + LABELS.get(s, s))} '
                   f'color="{STATUS_COLORS.get(s, "#000000")}" priority="{i}"/>'
                   for i, (s, h) in enumerate(self.tags.items())]
        out = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<!DOCTYPE database PUBLIC "-//Gramps//DTD Gramps XML 1.7.1//EN" '
            '"http://gramps-project.org/xml/1.7.1/grampsxml.dtd">',
            '<database xmlns="http://gramps-project.org/xml/1.7.1/">',
            f'<header><created date="{date.today().isoformat()}" version="5.2.0"/></header>',
        ]
        for tag, items in (("tags", tag_xml), ("events", self.events), ("people", people_xml),
                           ("families", fam_xml), ("citations", self.citations), ("sources", src_xml),
                           ("places", pl_xml), ("objects", obj_xml), ("repositories", repo_xml),
                           ("notes", self.notes)):
            if items:
                out.append(f"<{tag}>")
                out += items
                out.append(f"</{tag}>")
        out.append("</database>")
        return "\n".join(out) + "\n"


def to_gramps_xml(tree: Tree, strict: bool = False) -> str:
    return _Builder(tree, strict).build()


def to_gramps_xml_stats(tree: Tree, strict: bool = False) -> tuple[str, dict]:
    b = _Builder(tree, strict)
    return b.build(), b.stats
