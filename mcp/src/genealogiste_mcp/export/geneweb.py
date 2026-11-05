"""Export GEDCOM 5.5.1 taillé pour GeneWeb (ged2gwb) : le travail de preuve devient visible dans GeneWeb.

Ce que fait ged2gwb (vérifié dans son code source, bin/ged2gwb/ged2gwb.ml) et ce qu'on en tire :
- source d'un événement = TITL (+ TEXT) de l'enregistrement SOUR pointé, PAGE ignorée ; un SOUR
  « en ligne » (texte) est repris tel quel -> on écrit la citation complète mise en forme en texte ;
- NOTE d'un événement -> note de l'événement -> on y met le statut de preuve, les contradictions, la
  prochaine source et les témoins seulement nommés ;
- `2 ASSO @I..@ / 3 TYPE INDI / 3 RELA Witness|GODP|Civil officer|Religious officer|Informant|Attending|
  Mentioned|Other` sous un événement -> témoins de l'événement (personnes ou familles) ;
- `1 ASSO @I..@ / 2 TYPE INDI / 2 RELA GODF|GODM` sur l'individu -> parrain / marraine ;
- NOTE de l'individu -> notes de la personne -> fiche de preuve synthétique.
Les extensions `_…` sont omises (ged2gwb les ignore, ou les verse en notes avec -uin).
"""

from __future__ import annotations

from ..citations import format_citation
from ..evidence import assess_person
from ..gedcom.core import Node, serialize
from ..gedcom.mapping import godparent_rela, rela_of
from ..models import EVENT_LABELS, UNIQUE_EVENTS, Association, Event, Tree
from ..normalize.dates import parse_gedcom_date
from ..statuts import ICONS, LABELS, RANG_VERSION

RANK = RANG_VERSION


def split_versions(events: list[Event], facts: dict) -> tuple[list[Event], dict[str, list[str]]]:
    """GeneWeb ne garde qu'une naissance/un décès… : on exporte la version la mieux prouvée et on décrit
    les versions concurrentes dans sa note (rien n'est perdu, rien n'est mis au même rang)."""
    keep, extra_notes, by_type = [], {}, {}
    for e in events:
        if e.type in UNIQUE_EVENTS:
            by_type.setdefault(e.type, []).append(e)
        else:
            keep.append(e)
    for evs in by_type.values():
        def key(ev):
            f = facts.get(ev.uid) or {}
            return (RANK.get(f.get("statut", "non_source"), 4), -f.get("points", 0))
        evs = sorted(evs, key=key)
        best = evs[0]
        keep.append(best)
        for other in evs[1:]:
            f = facts.get(other.uid) or {}
            src = " ; ".join(c["reference"] for g in f.get("groupes", []) for c in g["citations"]) or "sans source"
            extra_notes.setdefault(best.uid, []).append(
                f"Version concurrente : {other.date or '?'} {other.lieu.nom if other.lieu else ''} — "
                f"{LABELS.get(f.get('statut', 'non_source'))} ({src})".replace("  ", " "))
    order = {id(e): i for i, e in enumerate(events)}
    keep.sort(key=lambda e: order[id(e)])
    return keep, extra_notes


ICON = ICONS


def _date(v: str) -> str:
    g = parse_gedcom_date(v) if v else None
    return g.gedcom(5) if g else v


def _proof_line(f: dict | None) -> str:
    if not f:
        return ""
    s = (f"{ICON[f['statut']]} Preuve : {LABELS[f['statut']]} — {f['sources_independantes']} source(s) "
         f"indépendante(s), {f['points']:g} pt")
    if f.get("contradictions"):
        s += "\nContradiction : " + " ; ".join(f["contradictions"])
    if f.get("justification_manuelle"):
        s += "\nDécision : " + f["justification_manuelle"]
    if f.get("actes_a_voir"):
        s += "\nActe(s) cité(s) mais non vu(s) : " + " ; ".join(f["actes_a_voir"])
    nxt = f.get("prochaine_source") or []
    if nxt:
        s += f"\nÀ consulter : {nxt[0]['source']} [{nxt[0]['cote_typique']}]"
    return s


class _Builder:
    def __init__(self, tree: Tree, strict: bool, temoins_en_personnes: bool):
        self.tree = tree
        self.strict = strict
        self.temoins_en_personnes = temoins_en_personnes
        self.extra_indis: list[Node] = []
        self.named: dict[str, str] = {}
        self.stats = {"personnes": 0, "familles": 0, "citations": 0, "temoins_lies": 0, "temoins_nommes": 0,
                      "parrains": 0, "temoins_crees": 0}

    def witness_person(self, a: Association) -> str:
        """Témoin seulement nommé dans l'acte -> fiche minimale dans GeneWeb (option)."""
        key = a.nom.strip()
        if key not in self.named:
            xid = f"T{len(self.named) + 1}"
            self.named[key] = xid
            parts = key.split()
            surname = next((p for p in parts if p.isupper() and len(p) > 1), parts[-1] if parts else "")
            given = " ".join(p for p in parts if p != surname)
            ind = Node("INDI", xref=xid)
            ind.add("NAME", f"{given} /{surname}/".strip())
            ind.add("NOTE", f"Personne citée comme {a.detail or 'témoin'} ; identité non établie "
                            "(fiche créée pour l'affichage des témoins, ne pas rattacher sans preuve).")
            self.extra_indis.append(ind)
            self.stats["temoins_crees"] += 1
        return self.named[key]

    def event(self, parent: Node, e: Event, fact: dict | None, versions: list[str] | None = None) -> None:
        value = e.valeur
        n = parent.add(e.type, value or ("Y" if not (e.date or e.lieu) and e.type in ("BIRT", "DEAT", "MARR") else ""))
        n.add_if("TYPE", e.type_detail)
        n.add_if("DATE", _date(e.date))
        if e.lieu and e.lieu.nom:
            n.add("PLAC", e.lieu.nom)
        n.add_if("AGE", e.age)
        n.add_if("CAUS", e.cause)
        notes = [x for x in (_proof_line(fact), *(versions or []), e.note) if x]
        named = []
        for a in e.associations:
            if a.personne and a.personne in self.tree.personnes:
                self._asso(n, a.personne, rela_of(a), 2)
                self.stats["temoins_lies"] += 1
            elif a.nom and self.temoins_en_personnes:
                self._asso(n, self.witness_person(a), rela_of(a), 2)
                self.stats["temoins_lies"] += 1
            elif a.nom:
                named.append(a.libelle())
                self.stats["temoins_nommes"] += 1
        if named:
            notes.append("Témoins et intervenants : " + " ; ".join(named))
        if notes:
            n.add("NOTE", "\n".join(notes))
        for c in e.citations:
            n.add("SOUR", format_citation(self.tree, c))
            self.stats["citations"] += 1
        for x in e.extra:
            if not x.get("tag", "").startswith("_"):
                n.children.append(Node.from_dict(x))

    @staticmethod
    def _asso(parent: Node, xref: str, rela: str, level: int) -> None:
        a = parent.add("ASSO", f"@{xref}@")
        a.add("TYPE", "INDI")
        a.add("RELA", rela)

    def build(self) -> list[Node]:
        t = self.tree
        head = Node("HEAD")
        head.add("SOUR", "GENEALOGISTE").add("NAME", "Plugin Claude Code genealogiste (export GeneWeb)")
        g = head.add("GEDC")
        g.add("VERS", "5.5.1")
        g.add("FORM", "LINEAGE-LINKED")
        head.add("CHAR", "UTF-8")
        head.add("LANG", "French")
        nodes = [head]
        for pid in sorted(t.personnes, key=lambda x: (len(x), x)):
            p = t.personnes[pid]
            facts = assess_person(t, pid, self.strict)
            by_uid = {f["uid"]: f for f in facts if f.get("uid")}
            r = Node("INDI", xref=pid)
            for nm in p.noms:
                n = r.add("NAME", f"{nm.prenoms} /{nm.nom}/".strip())
                n.add_if("GIVN", nm.prenoms)
                n.add_if("SURN", nm.nom)
                n.add_if("NICK", nm.surnom)
            r.add("SEX", p.sexe if p.sexe in ("M", "F") else "U")
            events, versions = split_versions(p.evenements, by_uid)
            for e in events:
                self.event(r, e, by_uid.get(e.uid), versions.get(e.uid))
            for a in p.associations:
                if a.role == "GODP" and (a.personne in t.personnes or (a.nom and self.temoins_en_personnes)):
                    xref = a.personne if a.personne in t.personnes else self.witness_person(a)
                    self._asso(r, xref, godparent_rela(a), 1)
                    self.stats["parrains"] += 1
            for f in p.famc:
                r.add("FAMC", f"@{f}@")
            for f in p.fams:
                r.add("FAMS", f"@{f}@")
            for c in p.citations:
                r.add("SOUR", format_citation(t, c))
                self.stats["citations"] += 1
            r.add("NOTE", self.person_note(pid, facts))
            for note in p.notes:
                text = t.notes.get(note.strip("@"), "") if note.startswith("@") else note
                if text:
                    r.add("NOTE", text)
            nodes.append(r)
            self.stats["personnes"] += 1
        for fid in sorted(t.familles, key=lambda x: (len(x), x)):
            f = t.familles[fid]
            r = Node("FAM", xref=fid)
            if f.epoux:
                r.add("HUSB", f"@{f.epoux}@")
            if f.epouse:
                r.add("WIFE", f"@{f.epouse}@")
            for link in f.enfants:
                r.add("CHIL", f"@{link.enfant}@")
            facts = {}
            for spouse in (f.epoux, f.epouse):
                if spouse in t.personnes:
                    facts.update({x["uid"]: x for x in assess_person(t, spouse, self.strict)
                                  if x.get("famille") == fid and x.get("uid")})
                    break
            events, versions = split_versions(f.evenements, facts)
            for e in events:
                self.event(r, e, facts.get(e.uid), versions.get(e.uid))
            for c in f.citations:
                r.add("SOUR", format_citation(t, c))
                self.stats["citations"] += 1
            filiations = []
            for link in f.enfants:
                if link.enfant not in t.personnes:
                    continue
                fact = next((x for x in assess_person(t, link.enfant, self.strict)
                             if x["fait"] == "filiation" and x.get("famille") == fid), None)
                if fact:
                    refs = [c["reference"] for g_ in fact["groupes"] for c in g_["citations"]]
                    filiations.append(f"Filiation de {t.personnes[link.enfant].nom_principal.complet} : "
                                      f"{ICON[fact['statut']]} {LABELS[fact['statut']]}"
                                      + (f" — {' ; '.join(refs)}" if refs else ""))
            notes = filiations + [n for n in f.notes]
            if notes:
                r.add("NOTE", "\n".join(notes))
            nodes.append(r)
            self.stats["familles"] += 1
        nodes += self.extra_indis
        nodes.append(Node("TRLR"))
        return nodes

    def person_note(self, pid: str, facts: list[dict]) -> str:
        return proof_summary(pid, facts)


def proof_summary(pid: str, facts: list[dict]) -> str:
    """Fiche de preuve synthétique d'une personne (statut par fait, prochaines sources)."""
    lines = ["Fiche de preuve (plugin genealogiste) — réf. " + pid]
    for f in facts:
        if f["fait"] in ("nom",):
            continue
        label = "Filiation" if f["fait"] == "filiation" else EVENT_LABELS.get(f["fait"], f["fait"]).capitalize()
        when = f" {f['date']}" if f.get("date") else ""
        lines.append(f"{ICON[f['statut']]} {label}{when} : {LABELS[f['statut']]}")
    todo, seen = [], set()
    for f in facts:
        if f.get("prochaine_source") and f["fait"] not in seen:
            seen.add(f["fait"])
            todo.append(f)
    if todo:
        lines.append("Prochaines sources :")
        for f in todo[:6]:
            s = f["prochaine_source"][0]
            label = "filiation" if f["fait"] == "filiation" else EVENT_LABELS.get(f["fait"], f["fait"])
            lines.append(f"- {label} : {s['source']} [{s['cote_typique']}]")
    return "\n".join(lines)


def to_geneweb(tree: Tree, strict: bool = False, temoins_en_personnes: bool = False) -> tuple[str, dict]:
    b = _Builder(tree, strict, temoins_en_personnes)
    text = serialize(b.build(), version=5)
    return text, b.stats
