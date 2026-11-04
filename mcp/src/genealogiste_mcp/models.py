"""Modèle interne commun : personne, famille, événement, lieu, source, citation, média.

Chaque assertion (nom, événement, filiation) porte ses citations ; le statut de preuve est calculé
(voir evidence.py) et peut être forcé manuellement (réfuté / contradictoire) avec justification.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import Any

INDI_EVENTS = {
    "BIRT": "naissance", "CHR": "baptême", "BAPM": "baptême", "DEAT": "décès", "BURI": "inhumation",
    "CREM": "crémation", "OCCU": "profession", "RESI": "résidence", "CENS": "recensement", "EDUC": "éducation",
    "EMIG": "émigration", "IMMI": "immigration", "NATU": "naturalisation", "PROB": "succession",
    "WILL": "testament", "GRAD": "diplôme", "RETI": "retraite", "CONF": "confirmation",
    "FCOM": "première communion", "ORDN": "ordination", "TITL": "titre", "RELI": "religion",
    "NATI": "nationalité", "DSCR": "description", "PROP": "propriété", "EVEN": "événement", "MILI": "service militaire",
}
FAM_EVENTS = {
    "MARR": "mariage", "MARB": "publication des bans", "MARC": "contrat de mariage", "MARL": "licence de mariage",
    "MARS": "convention de mariage", "DIV": "divorce", "DIVF": "demande de divorce", "ENGA": "fiançailles",
    "ANUL": "annulation", "EVEN": "événement", "CENS": "recensement", "RESI": "résidence",
}
EVENT_LABELS = {**INDI_EVENTS, **FAM_EVENTS}
# Événements « uniques » : plusieurs valeurs incompatibles => contradiction
UNIQUE_EVENTS = {"BIRT", "DEAT", "BURI", "CREM", "CHR", "BAPM"}

SOURCE_TYPES = ("originale", "derivee", "composite")
# Ce qui a réellement été consulté : on ne cite pas un acte qu'on n'a pas vu
CONSULTATIONS = ("original", "image", "transcription", "index", "non_vu")
# Rôles GEDCOM 7 (ROLE) ; le détail français va dans « detail » (PHRASE)
ROLES = ("WITN", "GODP", "CLERGY", "OFFICIATOR", "FATH", "MOTH", "PARENT", "HUSB", "WIFE", "SPOU", "CHIL",
         "FRIEND", "NGHBR", "MULTIPLE", "OTHER")
ROLE_FR = {
    "temoin": ("WITN", "Témoin"), "parrain": ("GODP", "Parrain"), "marraine": ("GODP", "Marraine"),
    "declarant": ("OTHER", "Déclarant"), "officier": ("OFFICIATOR", "Officier d'état civil"),
    "maire": ("OFFICIATOR", "Maire"), "pretre": ("CLERGY", "Prêtre"), "cure": ("CLERGY", "Curé"),
    "vicaire": ("CLERGY", "Vicaire"), "notaire": ("OFFICIATOR", "Notaire"), "voisin": ("NGHBR", "Voisin"),
    "ami": ("FRIEND", "Ami"), "mentionne": ("OTHER", "Mentionné"), "present": ("OTHER", "Présent"),
}
ROLE_LABELS = {"WITN": "Témoin", "GODP": "Parrain/marraine", "CLERGY": "Ecclésiastique",
               "OFFICIATOR": "Officiant", "FATH": "Père", "MOTH": "Mère", "PARENT": "Parent", "HUSB": "Époux",
               "WIFE": "Épouse", "SPOU": "Conjoint", "CHIL": "Enfant", "FRIEND": "Ami", "NGHBR": "Voisin",
               "MULTIPLE": "Plusieurs", "OTHER": "Autre"}
INFO_TYPES = ("primaire", "secondaire", "indeterminee")
EVIDENCE_TYPES = ("directe", "indirecte", "negative")
STATUTS = ("confirme", "probable", "hypothese", "contradictoire", "refute", "non_source")


def new_uid() -> str:
    return str(uuid.uuid4())


class _Base:
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None):
        if data is None:
            return None
        names = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            v = data[f.name]
            sub = _NESTED.get((cls.__name__, f.name))
            if sub and v is not None:
                v = [sub.from_dict(x) for x in v] if isinstance(v, list) else sub.from_dict(v)
            kwargs[f.name] = v
        unknown = set(data) - names
        if unknown:
            raise ValueError(f"{cls.__name__} : champs inconnus {sorted(unknown)}")
        return cls(**kwargs)


@dataclass
class Citation(_Base):
    source: str  # xref de la source (S1)
    page: str = ""  # où dans la source : folio, n° d'acte, vue, URL précise
    texte: str = ""  # transcription / extrait
    qualite: int | None = None  # QUAY GEDCOM 0-3
    type_source: str = "indeterminee"  # originale | derivee | composite (ou indeterminee)
    information: str = "indeterminee"  # primaire | secondaire | indeterminee
    preuve: str = "directe"  # directe | indirecte | negative
    date_consultation: str = ""
    note: str = ""
    consultation: str = ""  # original | image | transcription | index | non_vu ("" = non précisé)
    ark: str = ""  # identifiant pérenne de l'image ou de la page (ark:/NAAN/nom/qualificatif)
    medias: list[str] = field(default_factory=list)  # images de l'acte (xref O1…) qui fondent la citation
    extra: list = field(default_factory=list)


@dataclass
class Association(_Base):
    """Témoin, parrain/marraine, déclarant, officier… cité dans un acte (GEDCOM ASSO)."""
    personne: str = ""  # xref d'une personne de l'arbre, ou "" si seulement nommée dans l'acte
    nom: str = ""  # nom tel qu'écrit dans l'acte (obligatoire si personne vide)
    role: str = "WITN"  # rôle GEDCOM 7 (ROLES)
    detail: str = ""  # précision en français : « Parrain, oncle paternel, 45 ans, tonnelier »
    citations: list[Citation] = field(default_factory=list)
    extra: list = field(default_factory=list)

    def libelle(self) -> str:
        base = self.detail or ROLE_LABELS.get(self.role, self.role)
        return f"{base} : {self.nom or self.personne}"


@dataclass
class Assertion(_Base):
    """Statut manuel optionnel (refute, contradictoire...) avec justification."""
    statut: str = ""
    justification: str = ""


@dataclass
class Place(_Base):
    nom: str = ""  # « Commune, Département, Pays »
    code_insee: str = ""
    latitude: float | None = None
    longitude: float | None = None
    paroisse: str = ""
    extra: list = field(default_factory=list)


@dataclass
class Event(_Base):
    type: str  # BIRT, DEAT, MARR...
    date: str = ""  # date GEDCOM 7
    lieu: Place | None = None
    valeur: str = ""  # OCCU : intitulé, EVEN : type, RESI : adresse...
    type_detail: str = ""  # TYPE GEDCOM (EVEN)
    age: str = ""
    cause: str = ""
    note: str = ""
    citations: list[Citation] = field(default_factory=list)
    associations: list[Association] = field(default_factory=list)
    uid: str = field(default_factory=new_uid)
    statut_manuel: Assertion | None = None
    extra: list = field(default_factory=list)


@dataclass
class Name(_Base):
    prenoms: str = ""
    nom: str = ""
    surnom: str = ""  # NICK, « dit »
    type: str = ""  # BIRTH, AKA, MARRIED...
    citations: list[Citation] = field(default_factory=list)
    uid: str = field(default_factory=new_uid)
    statut_manuel: Assertion | None = None
    extra: list = field(default_factory=list)

    @property
    def complet(self) -> str:
        s = f"{self.prenoms} {self.nom.upper()}".strip()
        if self.surnom:
            s += f" dit {self.surnom}"
        return s


@dataclass
class ChildLink(_Base):
    enfant: str
    filiation: str = ""  # PEDI : BIRTH, ADOPTED, FOSTER...
    citations: list[Citation] = field(default_factory=list)
    statut_manuel: Assertion | None = None


@dataclass
class Person(_Base):
    id: str
    noms: list[Name] = field(default_factory=list)
    sexe: str = "U"  # M | F | X | U
    evenements: list[Event] = field(default_factory=list)
    famc: list[str] = field(default_factory=list)
    fams: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)  # citations générales
    associations: list[Association] = field(default_factory=list)  # ASSO de niveau individu (parrains…)
    medias: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    vivant: str = ""  # "" = déduit | "Y" | "N" (forçage manuel)
    uid: str = field(default_factory=new_uid)
    extra: list = field(default_factory=list)  # nœuds GEDCOM non interprétés (préservés)

    @property
    def nom_principal(self) -> Name:
        return self.noms[0] if self.noms else Name()

    def events(self, *types: str) -> list[Event]:
        return [e for e in self.evenements if e.type in types]

    def event_by_uid(self, uid: str) -> Event | None:
        return next((e for e in self.evenements if e.uid == uid), None)

    def label(self) -> str:
        return f"{self.nom_principal.complet or '(sans nom)'} [{self.id}]"


@dataclass
class Family(_Base):
    id: str
    epoux: str = ""  # HUSB
    epouse: str = ""  # WIFE
    enfants: list[ChildLink] = field(default_factory=list)
    evenements: list[Event] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)  # preuve de l'union
    notes: list[str] = field(default_factory=list)
    uid: str = field(default_factory=new_uid)
    statut_manuel: Assertion | None = None
    extra: list = field(default_factory=list)

    def child(self, pid: str) -> ChildLink | None:
        return next((c for c in self.enfants if c.enfant == pid), None)

    def event_by_uid(self, uid: str) -> Event | None:
        return next((e for e in self.evenements if e.uid == uid), None)


@dataclass
class Repository(_Base):
    id: str
    nom: str = ""
    sigle: str = ""  # AD17, AN, SHD…
    adresse: str = ""
    url: str = ""


@dataclass
class Source(_Base):
    id: str
    titre: str = ""
    auteur: str = ""
    publication: str = ""
    depot: str = ""  # xref REPO
    cote: str = ""  # CALN
    url: str = ""
    ark: str = ""  # identifiant pérenne de la ressource (ark:/NAAN/nom), clé de dédoublonnage
    type_source: str = "indeterminee"  # originale | derivee | composite
    original: str = ""  # xref de la source originale dont celle-ci dérive (indépendance)
    note: str = ""
    extra: list = field(default_factory=list)


@dataclass
class Media(_Base):
    id: str
    fichier: str = ""
    format: str = ""
    titre: str = ""
    citations: list[Citation] = field(default_factory=list)


_NESTED = {
    ("Event", "lieu"): Place, ("Event", "citations"): Citation, ("Event", "statut_manuel"): Assertion,
    ("Event", "associations"): Association, ("Person", "associations"): Association,
    ("Association", "citations"): Citation,
    ("Name", "citations"): Citation, ("Name", "statut_manuel"): Assertion,
    ("ChildLink", "citations"): Citation, ("ChildLink", "statut_manuel"): Assertion,
    ("Person", "noms"): Name, ("Person", "evenements"): Event, ("Person", "citations"): Citation,
    ("Family", "enfants"): ChildLink, ("Family", "evenements"): Event, ("Family", "citations"): Citation,
    ("Family", "statut_manuel"): Assertion, ("Media", "citations"): Citation,
}


@dataclass
class Tree:
    personnes: dict[str, Person] = field(default_factory=dict)
    familles: dict[str, Family] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    depots: dict[str, Repository] = field(default_factory=dict)
    medias: dict[str, Media] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)  # enregistrements NOTE/SNOTE partagés
    header_extra: list = field(default_factory=list)
    extra_records: list = field(default_factory=list)

    _PREFIX = {"personnes": "I", "familles": "F", "sources": "S", "depots": "R", "medias": "O", "notes": "N"}

    def next_id(self, kind: str) -> str:
        prefix = self._PREFIX[kind]
        coll = getattr(self, kind)
        n = 1
        nums = [int(k[len(prefix):]) for k in coll if k.startswith(prefix) and k[len(prefix):].isdigit()]
        if nums:
            n = max(nums) + 1
        return f"{prefix}{n}"

    def person(self, pid: str) -> Person:
        if pid not in self.personnes:
            raise KeyError(f"Personne inconnue : {pid}")
        return self.personnes[pid]

    def family(self, fid: str) -> Family:
        if fid not in self.familles:
            raise KeyError(f"Famille inconnue : {fid}")
        return self.familles[fid]

    def parents(self, pid: str) -> list[tuple[Family, ChildLink]]:
        out = []
        for fid in self.person(pid).famc:
            fam = self.familles.get(fid)
            if fam and fam.child(pid):
                out.append((fam, fam.child(pid)))
        return out

    def father_mother(self, pid: str) -> tuple[str | None, str | None]:
        for fam, link in self.parents(pid):
            if link.filiation in ("", "BIRTH"):
                return fam.epoux or None, fam.epouse or None
        return None, None

    def spouses_families(self, pid: str) -> list[Family]:
        return [self.familles[f] for f in self.person(pid).fams if f in self.familles]

    def children(self, pid: str) -> list[str]:
        out = []
        for fam in self.spouses_families(pid):
            out += [c.enfant for c in fam.enfants]
        return out

    def find_event(self, uid: str) -> tuple[Person | Family, Event] | None:
        for p in self.personnes.values():
            e = p.event_by_uid(uid)
            if e:
                return p, e
        for f in self.familles.values():
            e = f.event_by_uid(uid)
            if e:
                return f, e
        return None
