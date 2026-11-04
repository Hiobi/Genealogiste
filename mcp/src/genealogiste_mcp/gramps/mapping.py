"""Correspondance modèle Sosa <-> objets Gramps (format JSON brut de Gramps 6 / Gramps Web).

Module unique utilisé par l'export Gramps XML et par le mode direct (API) :
- :func:`gramps_to_tree` lit une base Gramps (:class:`GrampsDb`) en arbre Sosa ;
- :func:`tree_to_gramps` écrit un arbre Sosa en objets Gramps, **par-dessus** la base lue (``base``) :
  les identifiants (handles) sont réutilisés et tout ce que Sosa ne modélise pas est conservé tel quel
  (adresses, URL, médias d'événements, étiquettes, champs de nom, lieux hiérarchiques…) ;
- :func:`diff` calcule les éléments de transaction (add / update / delete) entre deux bases.

Correspondance (voir docs/gramps-web.md) :
- identifiants : ``gramps_id`` = xref Sosa (I12, F3, S7, R1, O2, N4) ; attribut ``Sosa-UID`` sur personnes,
  familles, événements, ``Sosa-UID noms`` sur la personne (uid des noms dans l'ordre). Un objet créé dans
  l'interface Gramps reçoit un uid dérivé de son handle, non écrit tant qu'il suffit ;
- statut manuel forcé : attribut ``Sosa-Statut`` (« refute | justification ») sur l'événement / la famille,
  ``Sosa-Statut nom N`` sur la personne, ``Sosa-Statut filiation I3`` sur la famille ;
- intervenants (témoins, parrains, officiers…) : attribut structuré ``Sosa-Association``
  « rang | RÔLE | précision | nom | xref », avec ses citations ; s'ils sont dans l'arbre, référence
  d'événement (rôle Witness, Godparent…) sur leur fiche, ou ``personref`` pour un parrain de baptême ;
- citations : page, confiance (QUAY), notes « Transcript » / « Citation », attributs Consulté, Type de
  source, Information, Preuve, Date de consultation ;
- sources : attributs URL, Type de source, Dérivée de ; dépôt et cote en référence de dépôt ;
- lieux : titre « Commune, Département, Pays », code INSEE, coordonnées ; paroisse en attribut d'événement ;
- notes générées (statut de preuve, fiche de preuve, lien de source) : étiquette ``Sosa:auto``,
  recalculées à chaque écriture, ignorées à la lecture ; les notes manuelles ne sont jamais réécrites.

Non mappés (perdus à l'aller-retour, voir ``NON_MAPPES``) : nœuds GEDCOM non interprétés (``extra``).
Normalisations : type de nom BIRTH -> « » (nom de naissance), filiation BIRTH -> « », lieux homonymes
fusionnés (un même nom de lieu = un objet Gramps).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field

from ..citations import INFOS, PREUVES, VU
from ..citations import TYPES as SOURCE_TYPE_LABELS
from ..models import (
    FAM_EVENTS,
    INDI_EVENTS,
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
from .types import (
    attribute,
    blank,
    blank_date,
    blank_name,
    date_from_gramps,
    date_to_gramps,
    event_ref,
    gtype,
    surname,
    tname,
)

NON_MAPPES = ["extra (nœuds GEDCOM non interprétés de chaque objet)", "Tree.header_extra",
              "Tree.extra_records"]

SOSA_AUTO = "Sosa:auto"
A_UID, A_UID_NOMS, A_STATUT, A_ASSO, A_VIVANT = "Sosa-UID", "Sosa-UID noms", "Sosa-Statut", "Sosa-Association", \
    "Sosa-Vivant"
A_STATUT_NOM, A_STATUT_FIL = "Sosa-Statut nom ", "Sosa-Statut filiation "
A_PRECISION, A_PAROISSE, A_CAUSE, A_AGE = "Précision", "Paroisse", "Cause", "Age"
CIT_ATTRS = ("Consulté", "Type de source", "Information", "Preuve", "Date de consultation", "QUAY")
SRC_ATTRS = ("URL", "Type de source", "Dérivée de")
STATUS_TAG = "Preuve : "
# Gabarits des notes générées par Sosa (export GEDCOM/GeneWeb, ancien export Gramps) : reconnues comme
# générées même sans étiquette Sosa:auto, puis adoptées (étiquetées et réécrites en place) au lieu d'être doublées.
GENERATED_NOTE = re.compile(r"^(?:(?:⛔|🟡|🟢|✅|⚠️|⚠|❌) Preuve : |Filiation de .+ : |"
                            r"Fiche de preuve \(plugin genealogiste\)|Lien : https?://)")


def looks_generated(text: str) -> bool:
    return bool(GENERATED_NOTE.match(text or ""))
EVEN_DEFAULT = "Événement"

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
CODES = {v: k for k, v in TYPES.items()}
NAME_TYPES = {"": "Birth Name", "BIRTH": "Birth Name", "MARRIED": "Married Name", "AKA": "Also Known As"}
NAME_CODES = {"Birth Name": "", "Married Name": "MARRIED", "Also Known As": "AKA"}
PEDI = {"": "Birth", "BIRTH": "Birth", "ADOPTED": "Adopted", "FOSTER": "Foster"}
PEDI_CODES = {"Birth": "", "Adopted": "ADOPTED", "Foster": "FOSTER"}
GENDER = {"F": 0, "M": 1, "U": 2, "X": 3}
GENDER_CODES = {v: k for k, v in GENDER.items()}
# Rôles standard de Gramps (EventRoleType) ; les autres deviennent des rôles personnalisés en français
EVENT_ROLES = {"WITN": "Witness", "CLERGY": "Clergy", "OFFICIATOR": "Celebrant"}
ROLE_CODES = {"Witness": "WITN", "Clergy": "CLERGY", "Celebrant": "OFFICIATOR", "Godparent": "GODP",
              "Friend": "FRIEND", "Neighbor": "NGHBR", "Father": "FATH", "Mother": "MOTH", "Parent": "PARENT",
              "Child": "CHIL", "Multiple birth": "MULTIPLE"}
STATUS_COLORS = {"confirme": "#2e7d32", "probable": "#689f38", "hypothese": "#f9a825",
                 "contradictoire": "#ef6c00", "refute": "#c62828", "non_source": "#757575"}
AUTO_COLOR = "#607d8b"
_NS = uuid.UUID("5f0e8f9e-9a51-4d1c-9d43-7d2b8f4c0a11")
_REV_VU = {v: k for k, v in VU.items()}
_REV_TYPES = {v: k for k, v in SOURCE_TYPE_LABELS.items()}
_REV_INFOS = {v: k for k, v in INFOS.items()}
_REV_PREUVES = {v: k for k, v in PREUVES.items()}
ORDER = ("Tag", "Repository", "Source", "Place", "Note", "Media", "Citation", "Event", "Person", "Family")


# ============================================================================ base Gramps en mémoire

@dataclass
class GrampsDb:
    """Objets Gramps bruts par classe puis handle (+ ce que la lecture a représenté dans Sosa)."""
    objects: dict[str, dict[str, dict]] = field(default_factory=lambda: {c: {} for c in ORDER})

    def get(self, cls: str, handle: str | None) -> dict | None:
        return self.objects.get(cls, {}).get(handle) if handle else None

    def put(self, obj: dict) -> None:
        self.objects.setdefault(obj["_class"], {})[obj["handle"]] = obj

    def remove(self, cls: str, handle: str) -> None:
        self.objects.get(cls, {}).pop(handle, None)

    def all(self, cls: str) -> dict[str, dict]:
        return self.objects.get(cls, {})

    def count(self) -> dict[str, int]:
        return {c: len(v) for c, v in self.objects.items() if v}

    def copy(self) -> GrampsDb:
        return GrampsDb(copy.deepcopy(self.objects))

    def to_json(self) -> dict:
        return self.objects

    @classmethod
    def from_objects(cls, objs) -> GrampsDb:
        db = cls()
        for o in objs:
            db.put(o)
        return db


def det_handle(*parts: str) -> str:
    """Handle déterministe (objets créés par Sosa) : stable d'un calcul à l'autre."""
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]


def derived_uid(*parts: str) -> str:
    return str(uuid.uuid5(_NS, "\x1f".join(parts)))


def _color12(c: str) -> str:
    c = c.lstrip("#")
    return "#" + "".join(c[i:i + 2] * 2 for i in (0, 2, 4)) if len(c) == 6 else "#" + c


def _attrs(obj: dict) -> list[dict]:
    return obj.get("attribute_list") or []


def _attr(obj: dict, typ: str) -> dict | None:
    return next((a for a in _attrs(obj) if tname(a.get("type")) == typ), None)


def _attr_value(obj: dict, typ: str) -> str:
    a = _attr(obj, typ)
    return (a or {}).get("value", "") or ""


def _statut_read(value: str) -> Assertion | None:
    if not value:
        return None
    st, _, just = value.partition(" | ")
    return Assertion(statut=st.strip(), justification=just.strip())


def _statut_write(a: Assertion | None) -> str:
    return f"{a.statut} | {a.justification}" if a and a.statut else ""


def _clean(s: str) -> str:
    return (s or "").replace(" | ", " ¦ ").replace("\n", " ")


def asso_value(rang: int, a: Association, with_name: bool = True, with_ref: bool = False) -> str:
    return " | ".join([str(rang), a.role, _clean(a.detail), _clean(a.nom) if with_name else "",
                       a.personne if with_ref else ""])


def asso_parse(value: str) -> tuple[int, str, str, str, str]:
    parts = [p.strip() for p in (value or "").split(" | ")] + ["", "", "", "", ""]
    try:
        rang = int(parts[0])
    except ValueError:
        rang = 10_000
    role = parts[1] if parts[1] in ROLES else "OTHER"
    return rang, role, parts[2], parts[3], parts[4]


def event_role(a: Association) -> str:
    """Rôle Gramps d'un intervenant : standard si possible, sinon le libellé français (« Parrain »)."""
    d = (a.detail or "").lower()
    if a.role in EVENT_ROLES:
        return EVENT_ROLES[a.role]
    if "déclarant" in d or "declarant" in d:
        return "Informant"
    if a.role == "GODP" and not a.detail:
        return "Godparent"
    if a.detail:
        return a.detail.split(",")[0].strip()
    return ROLE_LABELS.get(a.role, a.role)


def role_guess(role: str) -> tuple[str, str]:
    """Rôle Gramps saisi dans l'interface -> (rôle Sosa, précision)."""
    if role in ROLE_CODES:
        return ROLE_CODES[role], ""
    if role == "Informant":
        return "OTHER", "Déclarant"
    low = role.lower()
    if "parrain" in low or "marraine" in low:
        return "GODP", role
    if "témoin" in low or "temoin" in low:
        return "WITN", role
    return "OTHER", role


def _cit_key(c: Citation) -> str:
    d = asdict(c)
    d.pop("extra", None)
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


def _same_list(base: list, new: list) -> list:
    """Même contenu dans un autre ordre : on garde l'ordre de la base (pas de modification parasite)."""
    if len(base) != len(new):
        return new
    key = lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False)  # noqa: E731
    return base if sorted(map(key, base)) == sorted(map(key, new)) else new


# ============================================================================ lecture : Gramps -> Sosa

@dataclass
class ReadInfo:
    """Index produit par la lecture, réutilisé par l'écriture."""
    represented: set[tuple[str, str]] = field(default_factory=set)
    handles: dict[tuple[str, str], str] = field(default_factory=dict)  # (classe, id Sosa ou uid) -> handle
    event_owner: dict[str, str] = field(default_factory=dict)  # handle d'événement -> id du propriétaire
    auto_tag: str = ""


class _Reader:
    def __init__(self, db: GrampsDb):
        self.db = db
        self.t = Tree()
        self.info = ReadInfo()
        self.auto_tag = next((h for h, tg in db.all("Tag").items() if tg.get("name") == SOSA_AUTO), "")
        self.info.auto_tag = self.auto_tag
        self.status_tags = {h for h, tg in db.all("Tag").items() if (tg.get("name") or "").startswith(STATUS_TAG)}
        self.ids: dict[tuple[str, str], str] = {}
        prefixes = {"Person": "I", "Family": "F", "Source": "S", "Repository": "R", "Media": "O"}
        for cls, pre in prefixes.items():
            for h, o in db.all(cls).items():
                xid = o.get("gramps_id") or f"{pre}{h}"
                self.ids[(cls, h)] = xid
                self.info.handles[(cls, xid)] = h
        self.places: dict[str, Place | None] = {}

    def rep(self, cls: str, h: str) -> None:
        self.info.represented.add((cls, h))

    def xid(self, cls: str, h: str | None) -> str:
        return self.ids.get((cls, h or ""), "")

    # ------------------------------------------------------------------ notes, citations, lieux
    def is_auto(self, note: dict) -> bool:
        if self.auto_tag and self.auto_tag in (note.get("tag_list") or []):
            return True
        return looks_generated(self.note_text(note))

    def note(self, h: str) -> dict | None:
        n = self.db.get("Note", h)
        if n is not None:
            self.rep("Note", h)
        return n

    @staticmethod
    def note_text(n: dict) -> str:
        return ((n.get("text") or {}).get("string")) or ""

    def notes(self, handles: list[str], inline: tuple[str, ...]) -> tuple[list[str], list[str]]:
        """-> (textes des notes « en ligne » du type attendu, renvois @Nx@ vers les notes partagées)."""
        texts, shared = [], []
        for h in handles or []:
            n = self.note(h)
            if n is None or self.is_auto(n):
                continue
            if tname(n.get("type")) in inline:
                texts.append(self.note_text(n))
            else:
                key = n.get("gramps_id") or h
                self.t.notes[key] = self.note_text(n)
                shared.append(f"@{key}@")
        return texts, shared

    def single_note(self, handles: list[str]) -> str:
        """Champ texte unique (note d'événement, de source) : toutes les notes manuelles, jointes."""
        out = []
        for h in handles or []:
            n = self.note(h)
            if n is not None and not self.is_auto(n):
                out.append(self.note_text(n))
        return "\n\n".join(out)

    def citation(self, h: str) -> Citation | None:
        c = self.db.get("Citation", h)
        if c is None:
            return None
        self.rep("Citation", h)
        texte, note = [], []
        for nh in c.get("note_list") or []:
            n = self.note(nh)
            if n is None or self.is_auto(n):
                continue
            (texte if tname(n.get("type")) == "Transcript" else note).append(self.note_text(n))
        conf = c.get("confidence", 2)
        quay = _attr_value(c, "QUAY")
        qualite = int(quay) if quay.isdigit() else (None if conf == 2 else min(int(conf), 3))
        return Citation(
            source=self.xid("Source", c.get("source_handle")) or (c.get("source_handle") or ""),
            page=c.get("page") or "", texte="\n\n".join(texte), qualite=qualite,
            type_source=_REV_TYPES.get(_attr_value(c, "Type de source"), "indeterminee"),
            information=_REV_INFOS.get(_attr_value(c, "Information"), "indeterminee"),
            preuve=_REV_PREUVES.get(_attr_value(c, "Preuve"), "directe"),
            date_consultation=_attr_value(c, "Date de consultation"), note="\n\n".join(note),
            consultation=_REV_VU.get(_attr_value(c, "Consulté"), _attr_value(c, "Consulté")))

    def citations(self, handles: list[str]) -> list[Citation]:
        return [c for c in (self.citation(h) for h in handles or []) if c]

    def place_name(self, p: dict, depth: int = 0) -> str:
        if p.get("title"):
            return p["title"]
        name = (p.get("name") or {}).get("value", "")
        refs = p.get("placeref_list") or []
        if refs and depth < 8:
            parent = self.db.get("Place", refs[0].get("ref"))
            if parent:
                up = self.place_name(parent, depth + 1)
                return f"{name}, {up}" if name else up
        return name

    def place(self, h: str) -> Place | None:
        if not h:
            return None
        if h not in self.places:
            p = self.db.get("Place", h)
            if p is None:
                self.places[h] = None
            else:
                def num(v):
                    try:
                        return float(v) if v not in (None, "") else None
                    except (TypeError, ValueError):
                        return None
                self.places[h] = Place(nom=self.place_name(p), code_insee=p.get("code") or "",
                                       latitude=num(p.get("lat")), longitude=num(p.get("long")))
        pl = self.places[h]
        return copy.deepcopy(pl) if pl else None

    # ------------------------------------------------------------------ événements
    def event(self, h: str, owner: str, owner_cls: str, ref: dict) -> Event | None:
        ev = self.db.get("Event", h)
        if ev is None:
            return None
        self.rep("Event", h)
        typ = tname(ev.get("type"))
        code = CODES.get(typ, "EVEN")
        allowed = INDI_EVENTS if owner_cls == "Person" else FAM_EVENTS
        detail = ""
        if code not in allowed or code == "EVEN":
            code, detail = "EVEN", ("" if typ == EVEN_DEFAULT else typ)
        else:
            detail = _attr_value(ev, A_PRECISION)
        uid = _attr_value(ev, A_UID)
        first_owner = self.info.event_owner.setdefault(h, owner)
        if not uid:
            uid = derived_uid(h) if first_owner == owner else derived_uid(h, owner)
        elif first_owner != owner:
            uid = derived_uid(h, owner)
        self.info.handles[("Event", uid)] = h
        lieu = self.place(ev.get("place") or "")
        if lieu:
            lieu.paroisse = _attr_value(ev, A_PAROISSE)
        e = Event(type=code, date=date_from_gramps(ev.get("date")), lieu=lieu, valeur=ev.get("description") or "",
                  type_detail=detail, age=_attr_value(ref, A_AGE), cause=_attr_value(ev, A_CAUSE),
                  note=self.single_note(ev.get("note_list")), citations=self.citations(ev.get("citation_list")), uid=uid,
                  statut_manuel=_statut_read(_attr_value(ev, A_STATUT)))
        named = []
        for a in _attrs(ev):
            if tname(a.get("type")) == A_ASSO:
                rang, role, det, nom, _ = asso_parse(a.get("value", ""))
                named.append((rang, Association(personne="", nom=nom, role=role, detail=det,
                                                citations=self.citations(a.get("citation_list")))))
        self._assos[h] = named
        return e

    # ------------------------------------------------------------------ lecture complète
    def read(self) -> tuple[Tree, ReadInfo]:
        db, t = self.db, self.t
        self._assos: dict[str, list] = {}
        owned: dict[str, Event] = {}  # handle -> événement (premier propriétaire)
        witnesses: list[tuple[str, str, dict]] = []  # (handle d'événement, pid, eventref)
        persons = sorted(db.all("Person").items(), key=lambda kv: self.xid("Person", kv[0]))
        for h, p in persons:
            pid = self.xid("Person", h)
            self.rep("Person", h)
            names = [p.get("primary_name") or blank_name()] + list(p.get("alternate_names") or [])
            uids = _attr_value(p, A_UID_NOMS).split()
            noms = []
            for i, n in enumerate(names):
                if i == 0 and not (n.get("first_name") or n.get("surname_list") or n.get("nick")) \
                        and not p.get("alternate_names") and not n.get("citation_list"):
                    continue
                st = _attr_value(p, f"{A_STATUT_NOM}{i}")
                noms.append(Name(
                    prenoms=n.get("first_name") or "",
                    nom=" ".join(x for s in n.get("surname_list") or [] for x in (s.get("prefix"), s.get("surname")) if x),
                    surnom=n.get("nick") or "", type=NAME_CODES.get(tname(n.get("type")), tname(n.get("type"))),
                    citations=self.citations(n.get("citation_list")),
                    uid=uids[i] if i < len(uids) else derived_uid(h, "nom", str(i)),
                    statut_manuel=_statut_read(st)))
            person = Person(id=pid, noms=noms, sexe=GENDER_CODES.get(p.get("gender", 2), "U"),
                            uid=_attr_value(p, A_UID) or derived_uid(h), vivant=_attr_value(p, A_VIVANT))
            self.info.handles[("PersonUID", person.uid)] = h
            for ref in p.get("event_ref_list") or []:
                role = tname(ref.get("role"))
                eh = ref.get("ref")
                if role == "Primary":
                    e = self.event(eh, pid, "Person", ref)
                    if e:
                        person.evenements.append(e)
                        owned.setdefault(eh, e)
                else:
                    witnesses.append((eh, pid, ref))
            person.famc = [x for x in (self.xid("Family", f) for f in p.get("parent_family_list") or []) if x]
            person.fams = [x for x in (self.xid("Family", f) for f in p.get("family_list") or []) if x]
            person.citations = self.citations(p.get("citation_list"))
            person.medias = [x for x in (self.xid("Media", m.get("ref")) for m in p.get("media_list") or []) if x]
            texts, shared = self.notes(p.get("note_list"), ("Person Note",))
            person.notes = texts + shared
            assos, linked = [], set()
            for a in _attrs(p):
                if tname(a.get("type")) == A_ASSO:
                    rang, role, det, nom, xref = asso_parse(a.get("value", ""))
                    assos.append((rang, Association(personne=xref, nom=nom, role=role, detail=det,
                                                    citations=self.citations(a.get("citation_list")))))
                    if xref:
                        linked.add(xref)
            for pr in p.get("person_ref_list") or []:
                xref = self.xid("Person", pr.get("ref"))
                if xref and xref not in linked:
                    role, det = role_guess(pr.get("rel") or "")
                    assos.append((10_000, Association(personne=xref, role=role, detail=det,
                                                      citations=self.citations(pr.get("citation_list")))))
            person.associations = [a for _, a in sorted(assos, key=lambda x: x[0])]
            t.personnes[pid] = person
        for h, f in sorted(db.all("Family").items(), key=lambda kv: self.xid("Family", kv[0])):
            fid = self.xid("Family", h)
            self.rep("Family", h)
            fam = Family(id=fid, epoux=self.xid("Person", f.get("father_handle")),
                         epouse=self.xid("Person", f.get("mother_handle")),
                         uid=_attr_value(f, A_UID) or derived_uid(h),
                         statut_manuel=_statut_read(_attr_value(f, A_STATUT)))
            for cr in f.get("child_ref_list") or []:
                cid = self.xid("Person", cr.get("ref"))
                if not cid:
                    continue
                frel, mrel = tname(cr.get("frel")), tname(cr.get("mrel"))
                rel = frel if frel != "Birth" else mrel
                fam.enfants.append(ChildLink(enfant=cid, filiation=PEDI_CODES.get(rel, rel.upper()),
                                             citations=self.citations(cr.get("citation_list")),
                                             statut_manuel=_statut_read(_attr_value(f, f"{A_STATUT_FIL}{cid}"))))
            for ref in f.get("event_ref_list") or []:
                if tname(ref.get("role")) in ("Family", "Primary"):
                    e = self.event(ref.get("ref"), fid, "Family", ref)
                    if e:
                        fam.evenements.append(e)
                        owned.setdefault(ref.get("ref"), e)
            fam.citations = self.citations(f.get("citation_list"))
            texts, shared = self.notes(f.get("note_list"), ("Family Note",))
            fam.notes = texts + shared
            t.familles[fid] = fam
        # intervenants : attributs (nommés) + références d'événement des personnes de l'arbre
        for eh, e in owned.items():
            e.associations = [a for _, a in self._assos.get(eh, [])]
        ranked: dict[str, list] = {eh: list(self._assos.get(eh, [])) for eh in owned}
        for eh, pid, ref in witnesses:
            if eh not in owned:
                continue
            val = _attr_value(ref, A_ASSO)
            if val:
                rang, role, det, _, _ = asso_parse(val)
            else:
                rang, (role, det) = 10_000, role_guess(tname(ref.get("role")))
            ranked[eh].append((rang, Association(personne=pid, role=role, detail=det,
                                                 citations=self.citations(ref.get("citation_list")))))
        for eh, items in ranked.items():
            owned[eh].associations = [a for _, a in sorted(items, key=lambda x: x[0])]
        for h, s in sorted(db.all("Source").items(), key=lambda kv: self.xid("Source", kv[0])):
            sid = self.xid("Source", h)
            self.rep("Source", h)
            repo = (s.get("reporef_list") or [{}])[0]
            orig = _attr_value(s, "Dérivée de").split(" — ")[0].strip()
            t.sources[sid] = Source(
                id=sid, titre=s.get("title") or "", auteur=s.get("author") or "", publication=s.get("pubinfo") or "",
                depot=self.xid("Repository", repo.get("ref")), cote=repo.get("call_number") or "",
                url=_attr_value(s, "URL"), type_source=_REV_TYPES.get(_attr_value(s, "Type de source"), "indeterminee"),
                original=orig, note=self.single_note(s.get("note_list")))
        for h, r in sorted(db.all("Repository").items(), key=lambda kv: self.xid("Repository", kv[0])):
            rid = self.xid("Repository", h)
            self.rep("Repository", h)
            sigle = ""
            for nh in r.get("note_list") or []:
                n = self.note(nh)
                if n and self.note_text(n).startswith("Sigle : "):
                    sigle = self.note_text(n)[len("Sigle : "):].strip()
            name = r.get("name") or ""
            addr = (r.get("address_list") or [{}])[0]
            url = (r.get("urls") or [{}])[0]
            t.depots[rid] = Repository(id=rid, nom="" if name == sigle else name, sigle=sigle,
                                       adresse=addr.get("street") or "", url=url.get("path") or "")
        for h, m in sorted(db.all("Media").items(), key=lambda kv: self.xid("Media", kv[0])):
            mid = self.xid("Media", h)
            self.rep("Media", h)
            t.medias[mid] = Media(id=mid, fichier=m.get("path") or "", format=m.get("mime") or "",
                                  titre=m.get("desc") or "", citations=self.citations(m.get("citation_list")))
        # notes partagées non référencées (enregistrements NOTE du GEDCOM)
        referenced = {nh for cls in ORDER for o in db.all(cls).values() for nh in _note_refs(o)}
        for h, n in db.all("Note").items():
            if h in referenced or self.is_auto(n) or tname(n.get("type")) != "General" or not n.get("gramps_id"):
                continue
            self.rep("Note", h)
            t.notes[n["gramps_id"]] = self.note_text(n)
        for key, h in [((c, n.get("gramps_id")), hh) for c in ("Note",) for hh, n in db.all(c).items()]:
            if key[1]:
                self.info.handles[key] = h
        return t, self.info


def _note_refs(obj, out: list | None = None) -> list[str]:
    """Toutes les notes référencées par un objet (y compris dans ses sous-objets)."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "note_list":
                out += v or []
            elif isinstance(v, (dict, list)):
                _note_refs(v, out)
    elif isinstance(obj, list):
        for x in obj:
            _note_refs(x, out)
    return out


def references(obj, out: set | None = None) -> set[str]:
    """Handles référencés par un objet (pour ne jamais supprimer un objet encore utilisé)."""
    out = set() if out is None else out
    keys = {"ref", "source_handle", "place", "father_handle", "mother_handle"}
    lists = {"note_list", "citation_list", "tag_list", "family_list", "parent_family_list"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str) and v:
                out.add(v)
            elif k in lists and isinstance(v, list):
                out.update(x for x in v if isinstance(x, str))
            elif isinstance(v, (dict, list)):
                references(v, out)
    elif isinstance(obj, list):
        for x in obj:
            references(x, out)
    return out


def gramps_to_tree(db: GrampsDb) -> tuple[Tree, ReadInfo]:
    return _Reader(db).read()


# ============================================================================ écriture : Sosa -> Gramps

def proof_data(tree: Tree, strict: bool = False) -> dict:
    """Notes et étiquettes générées (statut de preuve) : {clé : [(type, texte)]}, {uid : statut}."""
    from ..evidence import LABELS, assess_person
    from ..export.geneweb import ICON, _proof_line, proof_summary

    notes: dict[tuple[str, str], list[tuple[str, str]]] = {}
    status: dict[str, str] = {}
    best: dict[tuple[str, str], str] = {}
    filiations: dict[str, list[str]] = {}
    for pid in sorted(tree.personnes):
        facts = assess_person(tree, pid, strict)
        for f in facts:
            if f.get("uid") and f.get("statut"):
                if f["uid"] not in status:
                    status[f["uid"]] = f["statut"]
                    line = _proof_line(f)
                    if line:
                        notes.setdefault(("Event", f["uid"]), []).append(("Research", line))
            if f["fait"] == "filiation":
                filiations.setdefault(f["famille"], []).append(
                    f"Filiation de {tree.personnes[pid].nom_principal.complet} : {ICON[f['statut']]} "
                    f"{LABELS[f['statut']]}")
        notes[("Person", pid)] = [("Research", proof_summary(pid, facts))]
        from ..export.geneweb import RANK
        for typ in ("BIRT", "DEAT"):
            cands = [(RANK.get(f.get("statut", "non_source"), 4), -f.get("points", 0), i, f["uid"])
                     for i, f in enumerate(facts) if f["fait"] == typ and not f.get("famille") and f.get("uid")]
            if cands:
                best[(pid, typ)] = min(cands)[3]
    for fid, lines in filiations.items():
        notes[("Family", fid)] = [("Research", "\n".join(lines))]
    return {"notes": notes, "status": status, "best": best}


class _Writer:
    def __init__(self, tree: Tree, base: GrampsDb | None, strict: bool, generated: bool,
                 only: set[tuple[str, str]] | None = None):
        self.t = tree
        self.base = base or GrampsDb()
        self.strict = strict
        _, self.info = gramps_to_tree(self.base) if base is not None else (None, ReadInfo())
        self.reader = _Reader(self.base)  # lecture unitaire (comparaisons « même contenu »)
        self.reader._assos = {}
        self.out = GrampsDb()
        self.gen = proof_data(tree, strict) if generated else {"notes": {}, "status": {}, "best": {}}
        self.generated = generated
        self.only = only  # None : toutes les notes générées recalculées ; sinon seulement ces objets (cls, clé)
        self.place_by_name: dict[str, str] = {}
        for h in self.base.all("Place"):
            nm = self.reader.place_name(self.base.all("Place")[h])
            self.place_by_name.setdefault(nm, h)
        self.tags_by_name = {tg.get("name"): h for h, tg in self.base.all("Tag").items()}
        self.used_tags: set[str] = set()
        self.event_content: dict[str, str] = {}
        self.stats = {"personnes": 0, "familles": 0, "evenements": 0, "citations": 0, "notes": 0,
                      "temoins_lies": 0, "temoins_nommes": 0, "associations": 0, "sources_url": 0}

    # ------------------------------------------------------------------ utilitaires
    def regen(self, cls: str, key: str) -> bool:
        """Notes et étiquettes de preuve de cet objet recalculées ? Sinon celles de la base sont gardées telles quelles."""
        return self.generated and (self.only is None or (cls, key) in self.only)

    def auto(self, cls: str, key: str) -> list[tuple[str, str]] | None:
        return self.gen["notes"].get((cls, key)) if self.regen(cls, key) else None

    def handle(self, cls: str, key: str) -> str:
        return self.info.handles.get((cls, key)) or det_handle(cls, key)

    def start(self, cls: str, h: str, gid: str | None = None) -> dict:
        b = self.base.get(cls, h)
        obj = copy.deepcopy(b) if b else blank(cls, h, gid)
        if gid is not None and "gramps_id" in obj:
            obj["gramps_id"] = gid
        return obj

    def tag(self, name: str, color: str, priority: int) -> str:
        h = self.tags_by_name.get(name)
        if not h:
            h = det_handle("Tag", name)
            self.tags_by_name[name] = h
        if h not in self.out.all("Tag"):
            tg = self.start("Tag", h)
            if not self.base.get("Tag", h):
                tg.update(name=name, color=_color12(color), priority=priority)
            self.out.put(tg)
        return h

    def set_attrs(self, obj: dict, owned, desired: list[dict]) -> None:
        """Remplace les attributs gérés par Sosa (``owned(type)``), conserve les autres et l'ordre."""
        base = obj.get("attribute_list") or []
        keep, pending = [], list(desired)
        for a in base:
            typ = tname(a.get("type"))
            if not owned(typ):
                keep.append(a)
                continue
            same = next((d for d in pending if tname(d.get("type")) == typ and d.get("value") == a.get("value")
                         and d.get("citation_list", []) == a.get("citation_list", [])), None)
            if same is not None:
                pending.remove(same)
                keep.append(a)
        obj["attribute_list"] = _same_list(base, keep + pending)

    def citations(self, cits: list[Citation], base_handles: list[str] | None, owner: str) -> list[str]:
        """Citations d'un emplacement : réutilise une citation de la base de même contenu."""
        avail = []
        for h in base_handles or []:
            c = self.reader.citation(h)
            if c is not None:
                avail.append((h, _cit_key(c)))
        out = []
        for i, c in enumerate(cits):
            key = _cit_key(c)
            hit = next((x for x in avail if x[1] == key), None)
            if hit:
                avail.remove(hit)
                h = hit[0]
                if h not in self.out.all("Citation"):
                    bc = self.base.get("Citation", h)
                    self.out.put(copy.deepcopy(bc))
                    for nh in bc.get("note_list") or []:
                        if self.base.get("Note", nh) and nh not in self.out.all("Note"):
                            self.out.put(copy.deepcopy(self.base.get("Note", nh)))
                    self.stats["citations"] += 1
            else:
                h = det_handle("Citation", owner, str(i), key)
                if h not in self.out.all("Citation"):
                    self.out.put(self.new_citation(h, c, owner))
                    self.stats["citations"] += 1
            out.append(h)
        return out

    def new_citation(self, h: str, c: Citation, owner: str) -> dict:
        obj = blank("Citation", h, None)
        obj["source_handle"] = self.handle("Source", c.source)
        obj["page"] = c.page
        obj["confidence"] = 2 if c.qualite is None else c.qualite
        notes = []
        if c.texte:
            notes.append(self.plain_note(c.texte, "Transcript", f"{h}:t"))
        if c.note:
            notes.append(self.plain_note(c.note, "Citation", f"{h}:n"))
        obj["note_list"] = notes
        stype = c.type_source if c.type_source != "indeterminee" else ""
        vals = [("Consulté", VU.get(c.consultation, c.consultation)),
                ("Type de source", SOURCE_TYPE_LABELS.get(stype, "")),
                ("Information", INFOS.get(c.information, "")), ("Preuve", PREUVES.get(c.preuve, "")),
                ("Date de consultation", c.date_consultation),
                ("QUAY", str(c.qualite) if c.qualite == 2 else "")]
        obj["attribute_list"] = [attribute(k, v, src=True) for k, v in vals if v]
        return obj

    def plain_note(self, text: str, typ: str, key: str) -> str:
        h = det_handle("Note", key, typ, text)
        n = self.start("Note", h)
        n["text"] = {"_class": "StyledText", "string": text, "tags": []}
        n["type"] = gtype("NoteType", typ)
        self.out.put(n)
        self.stats["notes"] += 1
        return h

    def notes(self, texts: list[str], base_handles: list[str] | None, typ: str, owner: str,
              auto: list[tuple[str, str]] | None = None, url: str = "", keep: bool = False) -> list[str]:
        """Notes d'un objet : manuelles réutilisées à l'identique, partagées (@N1@), générées (Sosa:auto)."""
        base_handles = list(base_handles or [])
        if self.generated:  # note de preuve venue d'un GEDCOM : régénérée, jamais doublée en note manuelle (#15)
            texts = [t for t in texts if not looks_generated(t)]
        avail, auto_avail = [], []
        for h in base_handles:
            n = self.base.get("Note", h)
            if n is None:
                continue
            if self.reader.is_auto(n):
                auto_avail.append(h)
            else:
                avail.append((h, self.reader.note_text(n)))
        out = []
        for i, text in enumerate(texts):
            if text.startswith("@") and text.endswith("@") and len(text) > 2:
                key = text.strip("@")
                if key in self.t.notes:
                    out.append(self.shared_note(key))
                continue
            hit = next((x for x in avail if x[1] == text), None)
            if hit:
                avail.remove(hit)
                if hit[0] not in self.out.all("Note"):
                    self.out.put(copy.deepcopy(self.base.get("Note", hit[0])))
                    self.stats["notes"] += 1
                out.append(hit[0])
            else:
                out.append(self.plain_note(text, typ, f"{owner}:{i}"))
        if keep:  # notes générées non recalculées : conservées à l'identique (#16)
            for h in auto_avail:
                if h not in self.out.all("Note"):
                    self.out.put(copy.deepcopy(self.base.get("Note", h)))
                out.append(h)
            auto_avail = []
        for i, (atype, text) in enumerate(auto or []):
            if not text:
                continue
            h = auto_avail.pop(0) if auto_avail else det_handle("Note", "auto", owner, atype, str(i))
            n = self.start("Note", h)
            n["text"] = {"_class": "StyledText", "string": text, "tags": []}
            if url and url in text:
                s = text.index(url)
                n["text"]["tags"] = [{"_class": "StyledTextTag", "name": gtype("StyledTextTagType", "link"),
                                      "value": url, "ranges": [[s, s + len(url)]]}]
            n["type"] = gtype("NoteType", atype)
            n["tag_list"] = [self.tag(SOSA_AUTO, AUTO_COLOR, 0)]
            self.out.put(n)
            self.stats["notes"] += 1
            out.append(h)
        return _same_list(base_handles, out)

    def single(self, text: str, base_handles: list[str] | None, typ: str, owner: str,
               auto: list[tuple[str, str]] | None = None, url: str = "", keep: bool = False) -> list[str]:
        """Champ texte unique : la base est gardée telle quelle si son texte est inchangé."""
        if self.generated and looks_generated(text):  # note de preuve venue d'un GEDCOM (#15)
            text = ""
        manual = [h for h in base_handles or [] if self.base.get("Note", h)
                  and not self.reader.is_auto(self.base.get("Note", h))]
        if manual and self.reader.single_note(manual) == text:
            for h in manual:
                if h not in self.out.all("Note"):
                    self.out.put(copy.deepcopy(self.base.get("Note", h)))
            autos = [h for h in base_handles or [] if h not in manual]
            return _same_list(list(base_handles or []), manual + self.notes([], autos, typ, owner, auto, url, keep))
        return self.notes([text] if text else [], base_handles, typ, owner, auto, url, keep)

    def shared_note(self, key: str) -> str:
        h = self.handle("Note", key)
        if h not in self.out.all("Note"):
            n = self.start("Note", h, key)
            if self.reader.note_text(n) != self.t.notes[key] or not self.base.get("Note", h):
                n["text"] = {"_class": "StyledText", "string": self.t.notes[key], "tags": []}
            self.out.put(n)
            self.stats["notes"] += 1
        return h

    def place(self, pl: Place | None, base_h: str) -> str:
        if not pl or not pl.nom:
            return ""
        if base_h:
            cur = self.reader.place(base_h)
            if cur and cur.nom == pl.nom and cur.code_insee == pl.code_insee and \
                    cur.latitude == pl.latitude and cur.longitude == pl.longitude:
                if base_h not in self.out.all("Place"):
                    self.out.put(copy.deepcopy(self.base.get("Place", base_h)))
                return base_h
        h = self.place_by_name.get(pl.nom) or det_handle("Place", pl.nom)
        self.place_by_name[pl.nom] = h
        obj = self.out.get("Place", h) or self.start("Place", h)
        if not self.base.get("Place", h) and not self.out.get("Place", h):
            obj["gramps_id"] = f"P{h[:6]}"
            obj["title"] = pl.nom
            obj["name"]["value"] = pl.nom.split(",")[0].strip()
        # compléter sans écraser : code INSEE, coordonnées
        if pl.code_insee and not obj.get("code"):
            obj["code"] = pl.code_insee
        if pl.latitude is not None and pl.longitude is not None and not obj.get("lat"):
            obj["lat"], obj["long"] = str(pl.latitude), str(pl.longitude)
        self.out.put(obj)
        return h

    # ------------------------------------------------------------------ événements
    def event(self, e: Event, owner: str, owner_cls: str) -> str:
        h = self.info.handles.get(("Event", e.uid)) or det_handle("Event", e.uid)
        obj = self.start("Event", h)
        base_e = None
        if self.base.get("Event", h):
            base_e = self.reader.event(h, owner, owner_cls, {})
        if base_e is None or (base_e.type, base_e.type_detail) != (e.type, e.type_detail):
            name = TYPES.get(e.type) or e.type_detail or EVEN_DEFAULT
            obj["type"] = gtype("EventType", name)
        if base_e is None or base_e.date != e.date:
            obj["date"] = date_to_gramps(e.date)
        obj["description"] = e.valeur
        obj["place"] = self.place(e.lieu, obj.get("place") or "")
        desired = []
        if e.uid == derived_uid(h, owner) and _attr(obj, A_UID):  # co-propriétaire d'un événement partagé
            desired.append(attribute(A_UID, _attr_value(obj, A_UID)))
        elif e.uid != derived_uid(h) and e.uid != derived_uid(h, owner):
            desired.append(attribute(A_UID, e.uid))
        if _statut_write(e.statut_manuel):
            desired.append(attribute(A_STATUT, _statut_write(e.statut_manuel)))
        if e.cause:
            desired.append(attribute(A_CAUSE, e.cause))
        if e.lieu and e.lieu.paroisse:
            desired.append(attribute(A_PAROISSE, e.lieu.paroisse))
        if e.type != "EVEN" and e.type_detail:
            desired.append(attribute(A_PRECISION, e.type_detail))
        base_asso = {a.get("value"): a for a in _attrs(obj) if tname(a.get("type")) == A_ASSO}
        for rang, a in enumerate(e.associations, 1):
            if a.personne and a.personne in self.t.personnes:
                self.links.append((a.personne, h, rang, a, owner))
                self.stats["temoins_lies"] += 1
            elif a.nom or a.personne:
                val = asso_value(rang, a)
                prev = base_asso.get(val)
                desired.append(attribute(A_ASSO, val, self.citations(
                    a.citations, (prev or {}).get("citation_list"), f"{h}:asso:{rang}")))
                self.stats["temoins_nommes"] += 1
        self.set_attrs(obj, lambda t: t in (A_UID, A_STATUT, A_CAUSE, A_PAROISSE, A_PRECISION, A_ASSO), desired)
        obj["citation_list"] = _same_list(obj.get("citation_list") or [],
                                          self.citations(e.citations, obj.get("citation_list"), h))
        regen = self.regen("Event", e.uid)
        obj["note_list"] = self.single(e.note, obj.get("note_list"), "Event Note", h, self.auto("Event", e.uid),
                                       keep=not regen)
        tags = [x for x in obj.get("tag_list") or [] if not regen or x not in self.reader.status_tags]
        st = self.gen["status"].get(e.uid)
        if st and regen:
            from ..evidence import LABELS
            tags.append(self.tag(STATUS_TAG + LABELS.get(st, st), STATUS_COLORS.get(st, "#000000"),
                                 list(STATUS_COLORS).index(st) + 1 if st in STATUS_COLORS else 9))
        obj["tag_list"] = _same_list(obj.get("tag_list") or [], tags)
        content = json.dumps(obj, sort_keys=True, ensure_ascii=False)
        if h in self.event_content and self.event_content[h] != content:  # événement partagé divergent
            h = det_handle("Event", e.uid, owner)
            obj["handle"] = h
            content = json.dumps(obj, sort_keys=True, ensure_ascii=False)
        self.event_content[h] = content
        self.ev_handle[(owner, e.uid)] = h
        self.out.put(obj)
        self.stats["evenements"] += 1
        return h

    @staticmethod
    def ref_with(base_refs: list[dict], handle: str, role: str, attrs: list[dict], cits: list[str]) -> dict:
        prev = next((r for r in base_refs if r.get("ref") == handle and tname(r.get("role")) == role), None)
        ref = copy.deepcopy(prev) if prev else event_ref(handle, role)
        owned = {A_AGE, A_ASSO}
        keep = [a for a in ref.get("attribute_list") or [] if tname(a.get("type")) not in owned]
        old_owned = [a for a in ref.get("attribute_list") or [] if tname(a.get("type")) in owned]
        new_owned = [a for a in attrs]
        if [(tname(a["type"]), a["value"]) for a in old_owned] == [(tname(a["type"]), a["value"]) for a in new_owned]:
            new_owned = old_owned
        ref["attribute_list"] = keep + new_owned
        ref["citation_list"] = _same_list(ref.get("citation_list") or [], cits)
        return ref

    # ------------------------------------------------------------------ construction
    def build(self) -> GrampsDb:
        t, base, out = self.t, self.base, self.out
        self.links: list[tuple[str, str, int, Association, str]] = []
        # objets de la base non représentés dans Sosa : conservés tels quels (lieux, notes isolées…)
        self.ev_handle: dict[tuple[str, str], str] = {}
        for cls in ORDER:
            for h, o in base.all(cls).items():
                if (cls, h) not in self.info.represented:
                    out.put(copy.deepcopy(o))
        people: dict[str, dict] = {}
        own_refs: dict[str, list[dict]] = {}
        for pid in sorted(t.personnes):
            p = t.personnes[pid]
            h = self.handle("Person", pid)
            obj = self.start("Person", h, pid)
            base_refs = obj.get("event_ref_list") or []
            refs = []
            for e in p.evenements:
                eh = self.event(e, pid, "Person")
                age = [attribute(A_AGE, e.age)] if e.age else []
                refs.append(self.ref_with(base_refs, eh, "Primary", age, []))
            own_refs[pid] = refs
            people[pid] = obj
        fams: dict[str, dict] = {}
        for fid in sorted(t.familles):
            f = t.familles[fid]
            h = self.handle("Family", fid)
            obj = self.start("Family", h, fid)
            obj["father_handle"] = self.handle("Person", f.epoux) if f.epoux in t.personnes else None
            obj["mother_handle"] = self.handle("Person", f.epouse) if f.epouse in t.personnes else None
            base_refs = obj.get("event_ref_list") or []
            refs = []
            for e in f.evenements:
                eh = self.event(e, fid, "Family")
                refs.append(self.ref_with(base_refs, eh, "Family", [], []))
            carried = [r for r in base_refs if ("Event", r.get("ref")) not in self.info.represented]
            obj["event_ref_list"] = _same_list(base_refs, refs + carried)
            if not base.get("Family", h):
                obj["type"] = gtype("FamilyRelType", "Married" if any(e.type == "MARR" for e in f.evenements)
                                    else "Unknown")
            base_children = {c.get("ref"): c for c in obj.get("child_ref_list") or []}
            children = []
            statut_attrs = []
            for link in f.enfants:
                if link.enfant not in t.personnes:
                    continue
                ch = self.handle("Person", link.enfant)
                cr = copy.deepcopy(base_children.get(ch)) or {
                    "_class": "ChildRef", "private": False, "citation_list": [], "note_list": [], "ref": ch,
                    "frel": gtype("ChildRefType", "Birth"), "mrel": gtype("ChildRefType", "Birth")}
                cur = PEDI_CODES.get(tname(cr["frel"]) if tname(cr["frel"]) != "Birth" else tname(cr["mrel"]))
                if cur != (link.filiation if link.filiation != "BIRTH" else ""):
                    rel = PEDI.get(link.filiation, link.filiation.capitalize())
                    cr["frel"] = cr["mrel"] = gtype("ChildRefType", rel)
                cr["citation_list"] = _same_list(cr.get("citation_list") or [], self.citations(
                    link.citations, cr.get("citation_list"), f"{h}:enfant:{link.enfant}"))
                children.append(cr)
                if _statut_write(link.statut_manuel):
                    statut_attrs.append(attribute(f"{A_STATUT_FIL}{link.enfant}", _statut_write(link.statut_manuel)))
            obj["child_ref_list"] = _same_list(obj.get("child_ref_list") or [], children)
            desired = []
            if f.uid != derived_uid(h):
                desired.append(attribute(A_UID, f.uid))
            if _statut_write(f.statut_manuel):
                desired.append(attribute(A_STATUT, _statut_write(f.statut_manuel)))
            self.set_attrs(obj, lambda x: x in (A_UID, A_STATUT) or x.startswith(A_STATUT_FIL), desired + statut_attrs)
            obj["citation_list"] = _same_list(obj.get("citation_list") or [],
                                              self.citations(f.citations, obj.get("citation_list"), h))
            obj["note_list"] = self.notes(f.notes, obj.get("note_list"), "Family Note", h, self.auto("Family", fid),
                                          keep=not self.regen("Family", fid))
            fams[fid] = obj
            self.stats["familles"] += 1
        # personnes : noms, références (propres, témoins), associations, notes
        witness_refs: dict[str, list[dict]] = {}
        for pid_w, eh, rang, a, _owner in self.links:
            base_refs = people[pid_w].get("event_ref_list") or []
            prev = next((r for r in base_refs if r.get("ref") == eh and _attr_value(r, A_ASSO)
                         and asso_parse(_attr_value(r, A_ASSO))[0] == rang), None)
            role = event_role(a)
            cits = self.citations(a.citations, (prev or {}).get("citation_list"), f"{eh}:lien:{rang}")
            witness_refs.setdefault(pid_w, []).append(self.ref_with(
                base_refs, eh, role, [attribute(A_ASSO, asso_value(rang, a, with_name=False))], cits))
        for pid in sorted(t.personnes):
            p, obj = t.personnes[pid], people[pid]
            h = obj["handle"]
            base_obj = base.get("Person", h)
            if base_obj is None or GENDER_CODES.get(base_obj.get("gender", 2), "U") != p.sexe:
                obj["gender"] = GENDER.get(p.sexe, 2)
            names = [obj.get("primary_name") or blank_name()] + list(obj.get("alternate_names") or [])
            new_names = []
            for i, n in enumerate(p.noms or [Name()]):
                nb = copy.deepcopy(names[i]) if i < len(names) else blank_name()
                nb["first_name"] = n.prenoms
                cur = " ".join(x for s in nb.get("surname_list") or [] for x in (s.get("prefix"), s.get("surname")) if x)
                if cur != n.nom:
                    nb["surname_list"] = [surname(n.nom)] if n.nom else []
                nb["nick"] = n.surnom
                cur_type = NAME_CODES.get(tname(nb.get("type")), tname(nb.get("type")))
                if cur_type != (n.type if n.type != "BIRTH" else ""):
                    nb["type"] = gtype("NameType", NAME_TYPES.get(n.type, n.type or "Birth Name"))
                nb["citation_list"] = _same_list(nb.get("citation_list") or [], self.citations(
                    n.citations, nb.get("citation_list"), f"{h}:nom:{i}"))
                new_names.append(nb)
            obj["primary_name"], obj["alternate_names"] = new_names[0], new_names[1:]
            base_refs = obj.get("event_ref_list") or []
            carried = [r for r in base_refs if ("Event", r.get("ref")) not in self.info.represented]
            refs = own_refs[pid] + witness_refs.get(pid, []) + carried
            obj["event_ref_list"] = _same_list(base_refs, refs)
            obj["birth_ref_index"] = self.ref_index(p, obj["event_ref_list"], "BIRT")
            obj["death_ref_index"] = self.ref_index(p, obj["event_ref_list"], "DEAT")
            obj["family_list"] = _same_list(obj.get("family_list") or [],
                                            [self.handle("Family", f) for f in p.fams if f in t.familles])
            obj["parent_family_list"] = _same_list(obj.get("parent_family_list") or [],
                                                   [self.handle("Family", f) for f in p.famc if f in t.familles])
            obj["citation_list"] = _same_list(obj.get("citation_list") or [],
                                              self.citations(p.citations, obj.get("citation_list"), h))
            base_media = {m.get("ref"): m for m in obj.get("media_list") or []}
            medias = []
            for mid in p.medias:
                if mid in t.medias:
                    mh = self.handle("Media", mid)
                    medias.append(copy.deepcopy(base_media.get(mh)) or {
                        "_class": "MediaRef", "private": False, "citation_list": [], "note_list": [],
                        "ref": mh, "attribute_list": [], "rect": None})
            obj["media_list"] = _same_list(obj.get("media_list") or [], medias)
            # associations de niveau individu (parrains…) : attribut structuré + personref navigable
            base_attr = {a.get("value"): a for a in _attrs(obj) if tname(a.get("type")) == A_ASSO}
            desired, prefs = [], []
            base_prefs = obj.get("person_ref_list") or []
            for rang, a in enumerate(p.associations, 1):
                val = asso_value(rang, a, with_ref=bool(a.personne))
                prev = base_attr.get(val)
                cits = self.citations(a.citations, (prev or {}).get("citation_list"), f"{h}:passo:{rang}")
                desired.append(attribute(A_ASSO, val, cits))
                if a.personne in t.personnes:
                    rh = self.handle("Person", a.personne)
                    rel = a.detail or ROLE_LABELS.get(a.role, a.role)
                    pr = next((copy.deepcopy(x) for x in base_prefs if x.get("ref") == rh and x.get("rel") == rel),
                              None) or {"_class": "PersonRef", "private": False, "citation_list": [],
                                        "note_list": [], "ref": rh, "rel": rel}
                    pr["citation_list"] = cits
                    prefs.append(pr)
                    self.stats["associations"] += 1
            obj["person_ref_list"] = _same_list(base_prefs, prefs)
            uids = [n.uid for n in p.noms]
            if any(u != derived_uid(h, "nom", str(i)) for i, u in enumerate(uids)):
                desired.append(attribute(A_UID_NOMS, " ".join(uids)))
            if p.uid != derived_uid(h):
                desired.append(attribute(A_UID, p.uid))
            if p.vivant:
                desired.append(attribute(A_VIVANT, p.vivant))
            for i, n in enumerate(p.noms):
                if _statut_write(n.statut_manuel):
                    desired.append(attribute(f"{A_STATUT_NOM}{i}", _statut_write(n.statut_manuel)))
            self.set_attrs(obj, lambda x: x in (A_UID, A_UID_NOMS, A_ASSO, A_VIVANT) or x.startswith(A_STATUT_NOM),
                           desired)
            obj["note_list"] = self.notes(p.notes, obj.get("note_list"), "Person Note", h, self.auto("Person", pid),
                                          keep=not self.regen("Person", pid))
            out.put(obj)
            self.stats["personnes"] += 1
        for obj in fams.values():
            out.put(obj)
        for sid in sorted(t.sources):
            s = t.sources[sid]
            h = self.handle("Source", sid)
            obj = self.start("Source", h, sid)
            obj.update(title=s.titre, author=s.auteur, pubinfo=s.publication)
            reps = obj.get("reporef_list") or []
            if s.depot and s.depot in t.depots:
                rr = copy.deepcopy(reps[0]) if reps else {
                    "_class": "RepoRef", "private": False, "note_list": [], "ref": None, "call_number": "",
                    "media_type": gtype("SourceMediaType", "Book")}
                rr["ref"], rr["call_number"] = self.handle("Repository", s.depot), s.cote
                reps = [rr] + reps[1:]
            else:
                reps = reps[1:] if reps else []
            obj["reporef_list"] = reps
            desired = [attribute(k, v, src=True) for k, v in (
                ("Type de source", SOURCE_TYPE_LABELS.get(s.type_source, "")),
                ("Dérivée de", (f"{s.original} — {t.sources[s.original].titre}" if s.original in t.sources
                                else s.original) if s.original else ""),
                ("URL", s.url)) if v]
            self.set_attrs(obj, lambda x: x in SRC_ATTRS, desired)
            regen = self.regen("Source", sid)
            auto = [("Source Note", f"Lien : {s.url}")] if s.url and regen else None
            if s.url:
                self.stats["sources_url"] += 1
            obj["note_list"] = self.single(s.note, obj.get("note_list"), "Source Note", h, auto, url=s.url,
                                           keep=not regen)
            out.put(obj)
        for rid in sorted(t.depots):
            r = t.depots[rid]
            h = self.handle("Repository", rid)
            obj = self.start("Repository", h, rid)
            obj["name"] = r.nom or r.sigle
            addr = obj.get("address_list") or []
            if r.adresse:
                a0 = copy.deepcopy(addr[0]) if addr else {
                    "_class": "Address", "private": False, "citation_list": [], "note_list": [],
                    "date": blank_date(), "street": "", "locality": "", "city": "", "county": "",
                    "state": "", "country": "", "postal": "", "phone": ""}
                a0["street"] = r.adresse
                addr = [a0] + addr[1:]
            elif addr and addr[0].get("street"):
                addr = addr[1:]
            obj["address_list"] = addr
            urls = obj.get("urls") or []
            if r.url:
                u0 = copy.deepcopy(urls[0]) if urls else {"_class": "Url", "private": False, "path": "", "desc": "",
                                                          "type": gtype("UrlType", "Web Home")}
                u0["path"] = r.url
                urls = [u0] + urls[1:]
            elif urls:
                urls = urls[1:]
            obj["urls"] = urls
            base_notes = obj.get("note_list") or []
            kept = [n for n in base_notes if not (self.base.get("Note", n) and self.reader.note_text(
                self.base.get("Note", n)).startswith("Sigle : "))]
            for n in kept:
                if self.base.get("Note", n) and n not in out.all("Note"):
                    out.put(copy.deepcopy(self.base.get("Note", n)))
            sig = []
            if r.sigle:
                prev = next((n for n in base_notes if n not in kept and self.reader.note_text(
                    self.base.get("Note", n)) == f"Sigle : {r.sigle}"), None)
                if prev:
                    out.put(copy.deepcopy(self.base.get("Note", prev)))
                    sig = [prev]
                else:
                    sig = [self.plain_note(f"Sigle : {r.sigle}", "Repository Note", h)]
            obj["note_list"] = _same_list(base_notes, kept + sig)
            out.put(obj)
        for mid in sorted(t.medias):
            m = t.medias[mid]
            h = self.handle("Media", mid)
            obj = self.start("Media", h, mid)
            obj.update(path=m.fichier, mime=m.format, desc=m.titre)
            obj["citation_list"] = _same_list(obj.get("citation_list") or [],
                                              self.citations(m.citations, obj.get("citation_list"), h))
            out.put(obj)
        for key in sorted(t.notes):
            self.shared_note(key)
        return out

    def ref_index(self, p: Person, refs: list[dict], typ: str) -> int:
        uid = self.gen["best"].get((p.id, typ)) or next((e.uid for e in p.evenements if e.type == typ), None)
        want = self.ev_handle.get((p.id, uid)) if uid else None
        return next((i for i, r in enumerate(refs) if want and r.get("ref") == want
                     and tname(r.get("role")) == "Primary"), -1)


def tree_to_gramps(tree: Tree, base: GrampsDb | None = None, strict: bool = False,
                   generated: bool = True, only: set[tuple[str, str]] | None = None) -> GrampsDb:
    """Arbre Sosa -> base Gramps (par-dessus ``base`` si fournie). ``generated`` : notes Sosa:auto ; ``only`` :
    les recalculer seulement pour ces objets (cls, clé Sosa), celles des autres sont conservées telles quelles."""
    return _Writer(tree, base, strict, generated, only).build()


def touched_keys(before: Tree, after: Tree) -> set[tuple[str, str]]:
    """Objets dont le statut de preuve peut changer : personnes, familles, événements et sources modifiés,
    plus les membres des familles modifiées et les familles des personnes modifiées (filiations)."""
    out: set[tuple[str, str]] = set()

    def changed(a, b) -> bool:
        return a is None or b is None or a.to_dict() != b.to_dict()

    for sid, s in after.sources.items():
        if changed(before.sources.get(sid), s):
            out.add(("Source", sid))
    persons = {pid for pid, p in after.personnes.items() if changed(before.personnes.get(pid), p)}
    families = {fid for fid, f in after.familles.items() if changed(before.familles.get(fid), f)}
    for fid in list(families):
        f = after.familles[fid]
        persons |= {x for x in (f.epoux, f.epouse, *(c.enfant for c in f.enfants)) if x in after.personnes}
    for fid, f in after.familles.items():
        if persons & {f.epoux, f.epouse, *(c.enfant for c in f.enfants)}:
            families.add(fid)
    for pid in persons:
        out.add(("Person", pid))
        out |= {("Event", e.uid) for e in after.personnes[pid].evenements}
    for fid in families:
        out.add(("Family", fid))
        out |= {("Event", e.uid) for e in after.familles[fid].evenements}
    return out


def proof_only(item: dict, auto_tags: set[str]) -> bool:
    """Élément de transaction qui ne porte que sur des notes ou étiquettes de preuve générées."""
    cls = item["_class"]
    obj = item.get("new") or item.get("old") or {}
    if cls == "Note":
        return bool(auto_tags & set(obj.get("tag_list") or [])) or looks_generated(
            ((obj.get("text") or {}).get("string")) or "")
    if cls == "Tag":
        name = obj.get("name") or ""
        return name == SOSA_AUTO or name.startswith(STATUS_TAG)
    if item["type"] != "update":
        return False
    old, new = _strip_change(item["old"]), _strip_change(item["new"])
    keys = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
    return bool(keys) and keys <= {"note_list", "tag_list"}


def tree_to_gramps_stats(tree: Tree, base: GrampsDb | None = None, strict: bool = False,
                         generated: bool = True) -> tuple[GrampsDb, dict]:
    w = _Writer(tree, base, strict, generated)
    db = w.build()
    return db, w.stats


# ============================================================================ différences -> transaction

def _strip_change(o: dict) -> dict:
    return {k: v for k, v in o.items() if k != "change"}


def diff(base: GrampsDb, new: GrampsDb) -> list[dict]:
    """Éléments de transaction Gramps Web (``old`` = état lu, comparé par le serveur)."""
    _, info = gramps_to_tree(base)
    in_use = set()
    for cls in ORDER:
        for o in new.all(cls).values():
            references(o, in_use)
    adds, updates, deletes = [], [], []
    for cls in ORDER:
        for h, o in new.all(cls).items():
            b = base.get(cls, h)
            if b is None:
                adds.append({"type": "add", "_class": cls, "handle": h, "old": None, "new": o})
            elif _strip_change(b) != _strip_change(o):
                updates.append({"type": "update", "_class": cls, "handle": h, "old": b, "new": o})
        for h, b in base.all(cls).items():
            if h not in new.all(cls) and (cls, h) in info.represented and h not in in_use:
                deletes.append({"type": "delete", "_class": cls, "handle": h, "old": b, "new": None})
    order = {c: i for i, c in enumerate(ORDER)}
    deletes.sort(key=lambda x: -order[x["_class"]])
    return adds + updates + deletes


def apply_items(db: GrampsDb, items: list[dict]) -> GrampsDb:
    """Applique des éléments de transaction (réponse du serveur) à une copie locale."""
    out = db.copy()
    for it in items:
        if it["type"] == "delete":
            out.remove(it["_class"], it["handle"])
        elif it.get("new"):
            out.put(copy.deepcopy(it["new"]))
    return out


def summarize(items: list[dict]) -> dict:
    """Résumé lisible d'une transaction : {classe : {add, update, delete}}."""
    out: dict[str, dict[str, int]] = {}
    for it in items:
        d = out.setdefault(it["_class"], {"add": 0, "update": 0, "delete": 0})
        d[it["type"]] += 1
    return out
