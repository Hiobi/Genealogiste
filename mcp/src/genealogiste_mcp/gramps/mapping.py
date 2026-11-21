"""Correspondance modèle Genealogiste <-> objets Gramps (format JSON brut de Gramps 6 / Gramps Web).

Module unique utilisé par l'export Gramps XML et par le mode direct (API) :
- :func:`gramps_to_tree` lit une base Gramps (:class:`GrampsDb`) en arbre Genealogiste ;
- :func:`tree_to_gramps` écrit un arbre Genealogiste en objets Gramps, **par-dessus** la base lue (``base``) :
  les identifiants (handles) sont réutilisés et tout ce que Genealogiste ne modélise pas est conservé tel quel
  (adresses, URL, médias d'événements, étiquettes, champs de nom, lieux hiérarchiques…) ;
- :func:`diff` calcule les éléments de transaction (add / update / delete) entre deux bases.

Correspondance (voir docs/gramps-web.md) :
- marqueurs (#182, module ``marqueurs``) : noms logiques ``Genealogiste-*`` / ``Genealogiste:auto`` ci-dessous ; la
  forme historique ``Sosa-*`` / ``Sosa:auto`` est toujours lue (la nouvelle prime si un objet porte les deux).
  Écriture : un attribut ou l'étiquette existants gardent leur forme tant que leur valeur ne change pas ; un
  attribut nouveau ou modifié prend la forme ``forme`` (GENEALOGISTE_MARQUEURS) ; migration explicite par
  :func:`migrer_marqueurs` ;
- identifiants : ``gramps_id`` = xref Genealogiste (I12, F3, S7, R1, O2, N4) ; attribut ``Genealogiste-UID`` sur
  personnes, familles, événements, ``Genealogiste-UID noms`` sur la personne (uid des noms dans l'ordre). Un objet créé dans
  l'interface Gramps reçoit un uid dérivé de son handle, non écrit tant qu'il suffit ;
- statut manuel forcé : attribut ``Genealogiste-Statut`` (« refute | justification ») sur l'événement / la famille,
  ``Genealogiste-Statut nom N`` sur la personne, ``Genealogiste-Statut filiation I3`` sur la famille ;
- intervenants (témoins, parrains, officiers…) : attribut structuré ``Genealogiste-Association``
  « rang | RÔLE | précision | nom | xref », avec ses citations ; s'ils sont dans l'arbre, référence
  d'événement (rôle Witness, Godparent…) sur leur fiche, ou ``personref`` pour un parrain de baptême ;
- citations : page, confiance (QUAY), notes « Transcript » / « Citation », attributs Consulté, Type de
  source, Information, Preuve, Date de consultation ;
- sources : attributs URL, Type de source, Dérivée de ; dépôt et cote en référence de dépôt ;
- lieux : titre « Commune, Département, Pays », code INSEE, coordonnées ; paroisse en attribut d'événement ;
- notes générées (statut de preuve, fiche de preuve, lien de source) : étiquette ``Genealogiste:auto``,
  recalculées à chaque écriture, ignorées à la lecture ; les notes manuelles ne sont jamais réécrites ;
- étiquettes (#262) : ``tag_list`` (handles) <-> ``tags`` (noms) des personnes, familles, événements, citations,
  sources, dépôts, médias et notes partagées. Écriture par-dessus l'état lu : handles et ordre conservés, étiquettes
  gérées (``Genealogiste:auto``, « Preuve : … ») et handles sans objet Tag intacts ; étiquette inconnue créée dans la
  même transaction (couleur par défaut de Gramps, priorité suivante) ; nom en double dans la base : la première
  dans l'ordre de priorité est réutilisée, jamais de fusion ; un retrait ne supprime jamais l'objet Tag. Les
  étiquettes des lieux et des notes « en ligne » restent côté Gramps (conservées tant que l'objet est inchangé) ;
- types (#273) : un type personnalisé dont la chaîne est un libellé non ambigu d'un type standard (« Baptême »,
  « Témoin », « Âge ») est lu comme ce type (:func:`types.tcanon`) sans que l'objet change ; un objet nouveau ou
  dont le type change reçoit le type standard quand il existe (rôles Father… Officiator de Gramps 6.0 compris) ;
  normalisation explicite par :func:`normaliser_types`, détection par :func:`types_en_doublon`.

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

from .. import marqueurs
from ..billets import BLOG
from ..citations import INFOS, PREUVES, VU
from ..citations import TYPES as SOURCE_TYPE_LABELS
from ..etiquettes import geree
from ..etiquettes import ligne as ligne_etiquettes
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
from ..normalize.places import DEPARTEMENTS
from ..statuts import COULEURS
from .texte import ajuster, cible_interne, decrire, lien_interne, plages_valides
from .texte import tag as lien_tag
from .types import (
    MOD_COMPOSES,
    attribute,
    blank,
    blank_date,
    blank_name,
    candidats,
    cle_libelle,
    date_from_gramps,
    date_to_gramps,
    est_personnalise,
    event_ref,
    gtype,
    gtype_ecrit,
    surname,
    tcanon,
    tname,
    type_standard,
    valeur_tri,
)
from .types import TYPES as GRAMPS_TYPES

NON_MAPPES = ["extra (nœuds GEDCOM non interprétés de chaque objet)", "Tree.header_extra",
              "Tree.extra_records"]

# Noms logiques (forme genealogiste) ; la forme écrite est choisie par marqueurs.ecrit(nom, forme).
SOSA_AUTO = AUTO_TAG = marqueurs.AUTO[marqueurs.GENEALOGISTE]  # SOSA_AUTO : nom historique de la constante
A_UID, A_UID_NOMS, A_STATUT, A_ASSO, A_VIVANT = "Genealogiste-UID", "Genealogiste-UID noms", "Genealogiste-Statut", \
    "Genealogiste-Association", "Genealogiste-Vivant"
A_STATUT_NOM, A_STATUT_FIL = "Genealogiste-Statut nom ", "Genealogiste-Statut filiation "
A_PRECISION, A_PAROISSE, A_CAUSE, A_AGE = "Précision", "Paroisse", "Cause", "Age"
A_FICHIER = "Genealogiste-Fichier"  # chemin du fichier local (medias/…) ; le chemin Gramps est attribué par le serveur
CIT_ATTRS = ("Consulté", "Type de source", "Information", "Preuve", "Date de consultation", "QUAY", "ARK")
SRC_ATTRS = ("URL", "ARK", "Type de source", "Dérivée de")
STATUS_TAG = "Preuve : "
# Gabarits des notes générées par Genealogiste (export GEDCOM/GeneWeb, ancien export Gramps) : reconnues comme
# générées même sans étiquette Genealogiste:auto (ou Sosa:auto), puis adoptées (étiquetées et réécrites en place) au lieu d'être doublées.
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
# Rôle du modèle -> rôle standard de Gramps (EventRoleType ; Father… Officiator : Gramps ≥ 6.0, #273). Les autres
# (HUSB, WIFE, SPOU, OTHER) deviennent des rôles personnalisés : précision, sinon libellé français (ROLE_LABELS).
EVENT_ROLES = {"WITN": "Witness", "CLERGY": "Clergy", "OFFICIATOR": "Officiator", "GODP": "Godparent",
               "FATH": "Father", "MOTH": "Mother", "PARENT": "Parent", "CHIL": "Child", "MULTIPLE": "Multiple birth",
               "FRIEND": "Friend", "NGHBR": "Neighbor"}
# Rôle standard de Gramps (après reconnaissance des libellés) -> rôle du modèle ; Celebrant : écrit avant #273
ROLE_CODES = {"Witness": "WITN", "Clergy": "CLERGY", "Celebrant": "OFFICIATOR", "Officiator": "OFFICIATOR",
              "Godparent": "GODP", "Friend": "FRIEND", "Neighbor": "NGHBR", "Father": "FATH", "Mother": "MOTH",
              "Parent": "PARENT", "Child": "CHIL", "Multiple birth": "MULTIPLE"}
STATUS_COLORS = COULEURS
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
    """Objets Gramps bruts par classe puis handle (+ ce que la lecture a représenté dans Genealogiste)."""
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
    """Handle déterministe (objets créés par Genealogiste) : stable d'un calcul à l'autre."""
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]


def derived_uid(*parts: str) -> str:
    return str(uuid.uuid5(_NS, "\x1f".join(parts)))


def _color12(c: str) -> str:
    c = c.lstrip("#")
    return "#" + "".join(c[i:i + 2] * 2 for i in (0, 2, 4)) if len(c) == 6 else "#" + c


def _attrs(obj: dict) -> list[dict]:
    return obj.get("attribute_list") or []


def _atype(a: dict) -> str:
    """Nom logique du type d'un attribut (forme historique Sosa-* ramenée à Genealogiste-* ; libellé d'un type
    standard, « Âge », ramené à ce type, #273)."""
    return marqueurs.canon(tcanon(a.get("type")))


def _attr(obj: dict, typ: str) -> dict | None:
    """Attribut de nom logique ``typ`` ; sous les deux formes, la nouvelle prime (l'écart est signalé par
    :func:`incoherences_marqueurs`)."""
    found = [a for a in _attrs(obj) if _atype(a) == typ]
    return next((a for a in found if marqueurs.forme_de(tname(a.get("type"))) != marqueurs.SOSA), None) or \
        next(iter(found), None)


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
    """Rôle Gramps d'un intervenant nouveau ou modifié : standard quand il existe (#273), sinon la précision ou le
    libellé français (personnalisé) ; une précision qui est le libellé d'un rôle standard donne ce rôle."""
    d = (a.detail or "").lower()
    if a.role in EVENT_ROLES:
        return EVENT_ROLES[a.role]
    if "déclarant" in d or "declarant" in d:
        return "Informant"
    nom = a.detail.split(",")[0].strip() if a.detail else ROLE_LABELS.get(a.role, a.role)
    return type_standard("EventRoleType", nom) or nom


def role_guess(role: str) -> tuple[str, str]:
    """Rôle Gramps lu (chaîne XML du type standard, libellés reconnus compris : :func:`tcanon`) -> (rôle
    Genealogiste, précision)."""
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


# Régions administratives actuelles (2016) : reconnues seulement si elles figurent déjà dans le nom du lieu.
REGIONS = {"Auvergne-Rhône-Alpes", "Bourgogne-Franche-Comté", "Bretagne", "Centre-Val de Loire", "Corse", "Grand Est",
           "Hauts-de-France", "Île-de-France", "Normandie", "Nouvelle-Aquitaine", "Occitanie", "Pays de la Loire",
           "Provence-Alpes-Côte d'Azur", "Guadeloupe", "Martinique", "Guyane", "La Réunion", "Mayotte"}
COUNTRIES = {"France", "Belgique", "Suisse", "Italie", "Espagne", "Allemagne", "Luxembourg", "Pays-Bas",
             "Royaume-Uni", "Algérie", "Maroc", "Tunisie", "Canada", "États-Unis", "Pologne", "Portugal"}


def place_levels(nom: str) -> list[str]:
    """Niveaux d'un nom de lieu « Commune, Département, Pays » ; [] si la forme n'est pas canonique (espaces,
    niveau vide) : le lieu reste alors à plat pour que le nom relu soit identique."""
    parts = [x.strip() for x in (nom or "").split(",")]
    return parts if len(parts) > 1 and all(parts) and ", ".join(parts) == nom else []


def level_type(parts: list[str], i: int) -> str:
    """Type Gramps d'un niveau : pays (dernier niveau connu), département français, région, sinon commune."""
    name, last = parts[i], i == len(parts) - 1
    if last and (name in COUNTRIES or len(parts) > 2):
        return "Country"
    if name in DEPARTEMENTS.values() and (parts[-1] == "France" or last):
        return "Department"
    if name in REGIONS and parts[-1] == "France":
        return "Region"
    return "City" if i == 0 else "Unknown"


def _mime(path: str) -> str:
    import mimetypes
    return mimetypes.guess_type(path)[0] or ""


def _cit_key(c: Citation) -> str:
    """Contenu d'une citation pour la réutiliser ; les étiquettes n'en font pas partie (mises à jour en place)."""
    d = asdict(c)
    d.pop("extra", None)
    d.pop("tags", None)
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


def _same_list(base: list, new: list) -> list:
    """Même contenu dans un autre ordre : on garde l'ordre de la base (pas de modification parasite)."""
    if len(base) != len(new):
        return new
    key = lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False)  # noqa: E731
    return base if sorted(map(key, base)) == sorted(map(key, new)) else new


# ============================================================================ lecture : Gramps -> Genealogiste

def auto_tags(db: GrampsDb) -> set[str]:
    """Handles des étiquettes des notes générées, sous les deux formes (Genealogiste:auto, Sosa:auto)."""
    return {h for h, tg in db.all("Tag").items() if marqueurs.canon(tg.get("name") or "") == AUTO_TAG}


def _attr_lists(o, out: list | None = None) -> list[list[dict]]:
    """Toutes les listes d'attributs d'un objet Gramps, y compris dans ses références (event_ref_list…)."""
    out = [] if out is None else out
    if isinstance(o, dict):
        if isinstance(o.get("attribute_list"), list):
            out.append(o["attribute_list"])
        for k, v in o.items():
            if k != "attribute_list":
                _attr_lists(v, out)
    elif isinstance(o, list):
        for v in o:
            _attr_lists(v, out)
    return out


def _label_obj(cls: str, o: dict) -> str:
    return f"{cls} {o.get('gramps_id') or o.get('handle')}"


def _migrer_liste(attrs: list[dict]) -> tuple[list[dict], list[str]]:
    """(liste migrée, incohérences) : ancienne forme renommée en place (valeur, citations, confidentialité et
    position conservées) ; doublon identique de la nouvelle forme retiré ; valeur divergente laissée intacte."""
    out, incoherences = [], []
    nouveaux = [a for a in attrs if marqueurs.forme_de(tname(a.get("type"))) == marqueurs.GENEALOGISTE]
    for a in attrs:
        nom = tname(a.get("type"))
        if marqueurs.forme_de(nom) != marqueurs.SOSA or nom == marqueurs.AUTO[marqueurs.SOSA]:
            out.append(a)
            continue
        typ = marqueurs.canon(nom)
        freres = [n for n in nouveaux if _atype(n) == typ]
        same = [n for n in freres if n.get("value") == a.get("value")
                and (n.get("citation_list") or []) == (a.get("citation_list") or [])]
        if same:
            continue  # doublon identique : la nouvelle forme suffit
        if freres and (typ not in marqueurs.MULTIPLES or any(n.get("value") == a.get("value") for n in freres)):
            incoherences.append(f"{nom} = {a.get('value')!r} ≠ {typ} = "
                                f"{' / '.join(repr(n.get('value')) for n in freres)}")
            out.append(a)
            continue
        out.append({**a, "type": gtype(a["type"].get("_class", "AttributeType") if isinstance(a.get("type"), dict)
                                       else "AttributeType", typ)})
    return out, incoherences


def migrer_marqueurs(db: GrampsDb) -> tuple[list[dict], list[str]]:
    """Migration explicite des marqueurs vers la forme genealogiste (#182) : (éléments de transaction,
    incohérences). Handles, gramps_id, valeurs et associations inchangés ; aucun objet créé. Étiquette
    ``Sosa:auto`` renommée en place (même handle) ; si ``Genealogiste:auto`` existe déjà, les objets sont
    réétiquetés et l'ancienne étiquette, devenue inutilisée, supprimée. Idempotente."""
    items: list[dict] = []
    incoherences: list[str] = []
    tags = db.all("Tag")
    ancien = next((h for h, t in tags.items() if t.get("name") == marqueurs.AUTO[marqueurs.SOSA]), "")
    neuf = next((h for h, t in tags.items() if t.get("name") == AUTO_TAG), "")
    for cls in ORDER:
        if cls == "Tag":
            continue
        for h, o in db.all(cls).items():
            new = copy.deepcopy(o)
            for lst in _attr_lists(new):
                migre, inc = _migrer_liste(lst)
                lst[:] = migre
                incoherences += [f"{_label_obj(cls, o)} : {x}" for x in inc]
            if ancien and neuf and ancien in (new.get("tag_list") or []):
                new["tag_list"] = list(dict.fromkeys(neuf if x == ancien else x for x in new["tag_list"]))
            if _strip_change(new) != _strip_change(o):
                items.append({"type": "update", "_class": cls, "handle": h, "old": o, "new": new})
    if ancien and not neuf:
        tg = tags[ancien]
        items.insert(0, {"type": "update", "_class": "Tag", "handle": ancien, "old": tg,
                         "new": {**copy.deepcopy(tg), "name": AUTO_TAG}})
    elif ancien:
        items.append({"type": "delete", "_class": "Tag", "handle": ancien, "old": tags[ancien], "new": None})
    return items, incoherences


# ============================================================================ types personnalisés (#273)

# Classes dont un type personnalisé peut doublonner un type standard (StyledTextTagType n'est jamais saisi)
CLASSES_TYPES = tuple(sorted(c for c in GRAMPS_TYPES if c != "StyledTextTagType"))


def _types_perso(o, out: list) -> None:
    """Types personnalisés (dicts) d'un objet Gramps, sous-objets compris, dans l'ordre."""
    if isinstance(o, dict):
        if o.get("_class") in GRAMPS_TYPES:
            if est_personnalise(o) and o["_class"] in CLASSES_TYPES:
                out.append(o)
            return
        for v in o.values():
            _types_perso(v, out)
    elif isinstance(o, list):
        for v in o:
            _types_perso(v, out)


def _classes(classes: list[str] | None) -> set[str]:
    if not classes:
        return set(CLASSES_TYPES)
    inconnues = sorted(set(classes) - set(CLASSES_TYPES))
    if inconnues:
        raise ValueError(f"Classe de type inconnue : {', '.join(inconnues)} (classes : {', '.join(CLASSES_TYPES)}).")
    return set(classes)


def _libelle_fr(cls: str, xml: str) -> str:
    from .types import REFERENTIEL
    fr = REFERENTIEL["classes"][cls]["types"][xml]["fr"]
    return fr[max(fr, key=lambda v: tuple(map(int, v.split("."))))]


def types_en_doublon(db: GrampsDb, classes: list[str] | None = None) -> dict:
    """Types personnalisés dont la chaîne est le libellé d'un type standard de leur classe (#273) : {doublons :
    [{classe, chaine, standard, libelle, objets, occurrences}], ambigus : [{classe, chaine, candidats, objets,
    occurrences}]} ; ``objets`` = objets de premier niveau qui les portent, ``occurrences`` = nombre de types."""
    voulues = _classes(classes)
    compte: dict[tuple[str, str], list] = {}
    for cls in ORDER:
        for h, o in db.all(cls).items():
            found: list[dict] = []
            _types_perso(o, found)
            for t in found:
                if t["_class"] in voulues and candidats(t["_class"], t.get("string") or ""):
                    c = compte.setdefault((t["_class"], t.get("string") or ""), [set(), 0])
                    c[0].add((cls, h))
                    c[1] += 1
    doublons, ambigus = [], []
    for (cls, s), (objs, n) in sorted(compte.items()):
        cand = candidats(cls, s)
        if len(cand) == 1:
            doublons.append({"classe": cls, "chaine": s, "standard": cand[0], "libelle": _libelle_fr(cls, cand[0]),
                             "objets": len(objs), "occurrences": n})
        else:
            ambigus.append({"classe": cls, "chaine": s, "candidats": cand, "objets": len(objs), "occurrences": n})
    return {"doublons": doublons, "ambigus": ambigus}


def normaliser_types(db: GrampsDb, classes: list[str] | None = None) -> tuple[list[dict], dict]:
    """Normalisation explicite (#273) : chaque type personnalisé qui désigne sans ambiguïté un type standard
    devient ce type standard, en place. Seul le type change (handles, gramps_id, valeurs, citations, positions
    inchangés) ; aucun objet créé ni supprimé ; les cas ambigus sont listés, jamais tranchés. Idempotente.
    Renvoie (éléments de transaction, {par_classe : {classe : {chaîne : {standard, objets, occurrences}}},
    ambigus})."""
    voulues = _classes(classes)
    items: list[dict] = []
    for cls in ORDER:
        for h, o in db.all(cls).items():
            new = copy.deepcopy(o)
            found: list[dict] = []
            _types_perso(new, found)
            for t in found:
                std = type_standard(t["_class"], t.get("string") or "") if t["_class"] in voulues else None
                if std is not None:
                    t.update(gtype(t["_class"], std))
            if _strip_change(new) != _strip_change(o):
                items.append({"type": "update", "_class": cls, "handle": h, "old": o, "new": new})
    d = types_en_doublon(db, classes)
    par_classe: dict[str, dict] = {}
    for x in d["doublons"]:
        par_classe.setdefault(x["classe"], {})[x["chaine"]] = {"standard": x["standard"], "objets": x["objets"],
                                                               "occurrences": x["occurrences"]}
    return items, {"par_classe": par_classe, "ambigus": d["ambigus"]}


@dataclass
class ReadInfo:
    """Index produit par la lecture, réutilisé par l'écriture."""
    represented: set[tuple[str, str]] = field(default_factory=set)
    handles: dict[tuple[str, str], str] = field(default_factory=dict)  # (classe, id Genealogiste ou uid) -> handle
    event_owner: dict[str, str] = field(default_factory=dict)  # handle d'événement -> id du propriétaire
    auto_tag: str = ""


class _Reader:
    def __init__(self, db: GrampsDb):
        self.db = db
        self.t = Tree()
        self.info = ReadInfo()
        autos = auto_tags(db)
        self.auto_tags = autos
        self.auto_tag = next((h for h in autos if db.get("Tag", h).get("name") == AUTO_TAG), next(iter(autos), ""))
        self.info.auto_tag = self.auto_tag
        self.status_tags = {h for h, tg in db.all("Tag").items() if (tg.get("name") or "").startswith(STATUS_TAG)}
        # étiquettes de l'utilisateur (#262) : handle -> nom ; les étiquettes gérées restent hors du modèle
        self.tag_names = {h: tg["name"] for h, tg in db.all("Tag").items()
                          if tg.get("name") and not geree(tg["name"])}
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

    def tags(self, obj: dict) -> list[str]:
        """Noms des étiquettes de l'utilisateur d'un objet (ordre de tag_list, sans doublon de nom)."""
        return list(dict.fromkeys(self.tag_names[h] for h in obj.get("tag_list") or [] if h in self.tag_names))

    def xid(self, cls: str, h: str | None) -> str:
        return self.ids.get((cls, h or ""), "")

    # ------------------------------------------------------------------ notes, citations, lieux
    def is_auto(self, note: dict) -> bool:
        if self.auto_tags & set(note.get("tag_list") or []):
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
            if n is None or self.is_auto(n) or n.get("private"):  # privée : gardée dans Gramps, jamais publiée
                continue
            if tcanon(n.get("type")) in inline:
                texts.append(self.note_text(n))
            else:
                key = n.get("gramps_id") or h
                self.t.notes[key] = self.note_text(n)
                if self.tags(n):
                    self.t.notes_tags[key] = self.tags(n)
                shared.append(f"@{key}@")
        return texts, shared

    def single_note(self, handles: list[str], corps: str = "") -> str:
        """Champ texte unique (note d'événement, de source) : toutes les notes manuelles, jointes ; ``corps`` : note
        privée gardée quand même (corps d'un billet privé, :meth:`corps_billet`)."""
        out = []
        for h in handles or []:
            n = self.note(h)
            if n is not None and not self.is_auto(n) and (not n.get("private") or h == corps):
                out.append(self.note_text(n))
        return "\n\n".join(out)

    def corps_billet(self, s: dict | None) -> str:
        """Handle du corps d'un billet privé (#261) : première note non générée d'une source étiquetée Blog et
        privée. Il reste dans le modèle même privé (sa confidentialité suit celle de la source) ; le corps privé
        d'un billet public reste, lui, hors du modèle comme toute note privée."""
        if not s or not s.get("private") or BLOG not in self.tags(s):
            return ""
        for h in s.get("note_list") or []:
            n = self.db.get("Note", h)
            if n is not None and not self.is_auto(n):
                return h
        return ""

    def citation(self, h: str) -> Citation | None:
        c = self.db.get("Citation", h)
        if c is None:
            return None
        self.rep("Citation", h)
        texte, note = [], []
        for nh in c.get("note_list") or []:
            n = self.note(nh)
            if n is None or self.is_auto(n) or n.get("private"):
                continue
            (texte if tcanon(n.get("type")) == "Transcript" else note).append(self.note_text(n))
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
            consultation=_REV_VU.get(_attr_value(c, "Consulté"), _attr_value(c, "Consulté")),
            ark=_attr_value(c, "ARK"),
            medias=[x for x in (self.xid("Media", r.get("ref")) for r in c.get("media_list") or []) if x],
            prive=bool(c.get("private")), tags=self.tags(c))

    def media_ids(self, obj: dict) -> list[str]:
        """Médias liés (media_list) d'une personne, famille, source ou d'un événement : identifiants O…."""
        return [x for x in (self.xid("Media", m.get("ref")) for m in obj.get("media_list") or []) if x]

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
        typ = tcanon(ev.get("type"))  # « Baptême » personnalisé : Baptism (#273)
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
                  statut_manuel=_statut_read(_attr_value(ev, A_STATUT)), prive=bool(ev.get("private")),
                  medias=self.media_ids(ev), tags=self.tags(ev))
        named = []
        for a in _attrs(ev):
            if _atype(a) == A_ASSO:
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
                    surnom=n.get("nick") or "", type=NAME_CODES.get(tcanon(n.get("type")), tcanon(n.get("type"))),
                    citations=self.citations(n.get("citation_list")),
                    uid=uids[i] if i < len(uids) else derived_uid(h, "nom", str(i)),
                    statut_manuel=_statut_read(st)))
            person = Person(id=pid, noms=noms, sexe=GENDER_CODES.get(p.get("gender", 2), "U"),
                            uid=_attr_value(p, A_UID) or derived_uid(h), vivant=_attr_value(p, A_VIVANT),
                            prive=bool(p.get("private")), tags=self.tags(p))
            self.info.handles[("PersonUID", person.uid)] = h
            for ref in p.get("event_ref_list") or []:
                role = tcanon(ref.get("role"))
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
            person.medias = self.media_ids(p)
            texts, shared = self.notes(p.get("note_list"), ("Person Note",))
            person.notes = texts + shared
            assos, linked = [], set()
            for a in _attrs(p):
                if _atype(a) == A_ASSO:
                    rang, role, det, nom, xref = asso_parse(a.get("value", ""))
                    assos.append((rang, Association(personne=xref, nom=nom, role=role, detail=det,
                                                    citations=self.citations(a.get("citation_list")))))
                    if xref:
                        linked.add(xref)
            for pr in p.get("person_ref_list") or []:
                xref = self.xid("Person", pr.get("ref"))
                if xref and xref not in linked:
                    role, det = role_guess(pr.get("rel") or "")  # PersonRef.rel : texte libre, pas un type
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
                         statut_manuel=_statut_read(_attr_value(f, A_STATUT)), prive=bool(f.get("private")),
                         tags=self.tags(f))
            for cr in f.get("child_ref_list") or []:
                cid = self.xid("Person", cr.get("ref"))
                if not cid:
                    continue
                frel, mrel = tcanon(cr.get("frel")), tcanon(cr.get("mrel"))
                rel = frel if frel != "Birth" else mrel
                fam.enfants.append(ChildLink(enfant=cid, filiation=PEDI_CODES.get(rel, rel.upper()),
                                             citations=self.citations(cr.get("citation_list")),
                                             statut_manuel=_statut_read(_attr_value(f, f"{A_STATUT_FIL}{cid}"))))
            for ref in f.get("event_ref_list") or []:
                if tcanon(ref.get("role")) in ("Family", "Primary"):
                    e = self.event(ref.get("ref"), fid, "Family", ref)
                    if e:
                        fam.evenements.append(e)
                        owned.setdefault(ref.get("ref"), e)
            fam.citations = self.citations(f.get("citation_list"))
            fam.medias = self.media_ids(f)
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
                rang, (role, det) = 10_000, role_guess(tcanon(ref.get("role")))
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
                url=_attr_value(s, "URL"), ark=_attr_value(s, "ARK"), type_source=_REV_TYPES.get(_attr_value(s, "Type de source"), "indeterminee"),
                original=orig, note=self.single_note(s.get("note_list"), self.corps_billet(s)),
                prive=bool(s.get("private")),
                medias=self.media_ids(s), tags=self.tags(s))
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
                                       adresse=addr.get("street") or "", url=url.get("path") or "",
                                       tags=self.tags(r))
        for h, m in sorted(db.all("Media").items(), key=lambda kv: self.xid("Media", kv[0])):
            mid = self.xid("Media", h)
            self.rep("Media", h)
            t.medias[mid] = Media(id=mid, fichier=_attr_value(m, A_FICHIER) or m.get("path") or "",
                                  format=m.get("mime") or "",
                                  titre=m.get("desc") or "", citations=self.citations(m.get("citation_list")),
                                  prive=bool(m.get("private")), tags=self.tags(m))
        # notes partagées non référencées (enregistrements NOTE du GEDCOM)
        referenced = {nh for cls in ORDER for o in db.all(cls).values() for nh in _note_refs(o)}
        for h, n in db.all("Note").items():
            if h in referenced or self.is_auto(n) or tcanon(n.get("type")) != "General" or not n.get("gramps_id"):
                continue
            self.rep("Note", h)
            t.notes[n["gramps_id"]] = self.note_text(n)
            if self.tags(n):
                t.notes_tags[n["gramps_id"]] = self.tags(n)
            if n.get("private"):
                t.notes_privees.add(n["gramps_id"])
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


# ============================================================================ écriture : Genealogiste -> Gramps

def _lignes(texte: str) -> list[tuple[int, str]]:
    """(début, ligne) de chaque ligne d'un texte (positions en points de code)."""
    out, pos = [], 0
    for ligne in texte.split("\n"):
        out.append((pos, ligne))
        pos += len(ligne) + 1
    return out


def _liens_fiche(texte: str, pid: str, facts: list[dict]) -> list[tuple]:
    """Plages de la fiche de preuve d'une personne (#279) : « réf. I12 » -> la personne ; libellé de chaque fait
    (« Naissance 1850 ») -> son événement (propriétaire : la personne ou la famille), « Filiation » -> la famille."""
    lignes = _lignes(texte)
    pos, l0 = lignes[0]
    out = [(pos + len(l0) - len(pid), pos + len(l0), ("Person", pid))] if l0.endswith(" " + pid) else []
    faits = [f for f in facts if f["fait"] != "nom"]
    for (pos, ligne), f in zip(lignes[1:], faits, strict=False):
        if " " not in ligne or " : " not in ligne:
            break
        a, b = pos + ligne.index(" ") + 1, pos + ligne.rindex(" : ")
        if f.get("uid"):
            out.append((a, b, ("Event", f.get("famille") or pid, f["uid"])))
        elif f["fait"] == "filiation":
            out.append((a, b, ("Family", f["famille"])))
    return out


def _liens_evenement(texte: str, tree: Tree, event: Event | None) -> list[tuple]:
    """Plages du statut de preuve d'un événement (#279) : chaque acte cité mais non vu de la ligne « Acte(s) cité(s)
    mais non vu(s) : … » -> titre de la source vers la source, cote/page vers la citation (titre vers la citation
    si la citation n'a pas de page)."""
    from ..citations import format_citation

    if event is None:
        return []
    prefixe = "Acte(s) cité(s) mais non vu(s) : "
    ligne = next(((p, ligne) for p, ligne in _lignes(texte) if ligne.startswith(prefixe)), None)
    if ligne is None:
        return []
    pos = ligne[0] + len(prefixe)
    out = []
    for idx, c in enumerate(event.citations):
        if c.consultation != "non_vu":
            continue
        item = format_citation(tree, c, False)
        if texte[pos:pos + len(item)] != item:
            return out  # gabarit inattendu : pas de lien hasardeux
        src = tree.sources.get(c.source)
        titre = (src.titre or f"source {src.id}") if src else ""
        t0 = item.find(titre) if titre else -1
        p0 = item.find(c.page, t0 + len(titre) if t0 >= 0 else 0) if c.page else -1
        if t0 >= 0 and p0 >= 0:
            out.append((pos + t0, pos + t0 + len(titre), ("Source", c.source)))
            out.append((pos + p0, pos + p0 + len(c.page), ("Citation", idx)))
        elif t0 >= 0:
            out.append((pos + t0, pos + t0 + len(titre), ("Citation", idx)))
        elif p0 >= 0:
            out.append((pos + p0, pos + p0 + len(c.page), ("Citation", idx)))
        pos += len(item) + 3
    return out


def proof_data(tree: Tree, strict: bool = False, liens: bool = False) -> dict:
    """Notes et étiquettes générées (statut de preuve) : {clé : [(type, texte)]}, {uid : statut}. ``liens`` (#279) :
    chaque note devient (type, texte, plages) où les plages ``(début, fin, cible)`` désignent les objets cités par
    le texte (cible en clés Genealogiste, résolue en handles par l'écriture) ; le texte est inchangé."""
    from ..evidence import LABELS, assess_person
    from ..export.geneweb import ICON, _proof_line, proof_summary

    notes: dict[tuple[str, str], list[tuple]] = {}
    status: dict[str, str] = {}
    best: dict[tuple[str, str], str] = {}
    filiations: dict[str, list[str]] = {}
    fil_liens: dict[str, list[tuple]] = {}
    evenements = {e.uid: e for o in (*tree.personnes.values(), *tree.familles.values()) for e in o.evenements} \
        if liens else {}
    for pid in sorted(tree.personnes):
        facts = assess_person(tree, pid, strict)
        for f in facts:
            if f.get("uid") and f.get("statut"):
                if f["uid"] not in status:
                    status[f["uid"]] = f["statut"]
                    line = _proof_line(f)
                    if line:
                        notes.setdefault(("Event", f["uid"]), []).append(
                            ("Research", line, _liens_evenement(line, tree, evenements.get(f["uid"])))
                            if liens else ("Research", line))
            if f["fait"] == "filiation":
                nom = tree.personnes[pid].nom_principal.complet
                lignes = filiations.setdefault(f["famille"], [])
                debut = sum(len(x) + 1 for x in lignes) + len("Filiation de ")
                fil_liens.setdefault(f["famille"], []).append((debut, debut + len(nom), ("Person", pid)))
                lignes.append(f"Filiation de {nom} : {ICON[f['statut']]} {LABELS[f['statut']]}")
        fiche = proof_summary(pid, facts)
        notes[("Person", pid)] = [("Research", fiche, _liens_fiche(fiche, pid, facts)) if liens
                                  else ("Research", fiche)]
        from ..statuts import RANG_VERSION as RANK
        for typ in ("BIRT", "DEAT"):
            cands = [(RANK.get(f.get("statut", "non_source"), 4), -f.get("points", 0), i, f["uid"])
                     for i, f in enumerate(facts) if f["fait"] == typ and not f.get("famille") and f.get("uid")]
            if cands:
                best[(pid, typ)] = min(cands)[3]
    for fid, lines in filiations.items():
        notes[("Family", fid)] = [("Research", "\n".join(lines), [x for x in fil_liens[fid] if x[1] > x[0]])
                                  if liens else ("Research", "\n".join(lines))]
    return {"notes": notes, "status": status, "best": best}


class _Writer:
    def __init__(self, tree: Tree, base: GrampsDb | None, strict: bool, generated: bool,
                 only: set[tuple[str, str]] | None = None, forme: str = marqueurs.GENEALOGISTE,
                 liens: bool = False, recalcul: bool = False):
        self.forme = forme  # forme écrite des marqueurs nouveaux ou modifiés (#182)
        # #279 : liens internes gramps:// dans les notes générées (GENEALOGISTE_GRAMPS_NOTES_LIENS) ; ``recalcul`` :
        # gramps_recalculer_notes, seul à faire passer une note inchangée d'une forme (avec / sans liens) à l'autre
        self.liens, self.recalcul = liens, recalcul
        self.liens_en_attente: list[tuple[str, str, list[tuple]]] = []  # (note, porteur, plages) résolues à la fin
        self.cit_evt: dict[str, list[str]] = {}  # handle d'événement -> citations dans l'ordre du modèle
        self.avis: list[str] = []  # mises en forme retirées ou refusées (jamais de perte silencieuse)
        self.styled: list[str] = []  # notes mises en forme depuis du Markdown (liens internes à vérifier)
        self.partagees: set[str] | None = None  # handles des notes partagées du modèle (calculés une fois)
        self.t = tree
        self.base = base or GrampsDb()
        self.strict = strict
        base_tree, self.info = gramps_to_tree(self.base) if base is not None else (Tree(), ReadInfo())
        # intervenants lus de chaque événement de la base : (propriétaire, uid) -> associations (#273 : références
        # saisies dans l'interface réécrites telles quelles tant qu'elles ne changent pas)
        self.assos_base = {(o.id, e.uid): [a.to_dict() for a in e.associations]
                           for o in [*base_tree.personnes.values(), *base_tree.familles.values()] for e in o.evenements}
        self.sources_base = base_tree.sources  # billets créés ou modifiés (#261)
        self.reader = _Reader(self.base)  # lecture unitaire (comparaisons « même contenu »)
        self.reader._assos = {}
        self.out = GrampsDb()
        self.gen = proof_data(tree, strict, liens) if generated else {"notes": {}, "status": {}, "best": {}}
        self.generated = generated
        self.only = only  # None : toutes les notes générées recalculées ; sinon seulement ces objets (cls, clé)
        self.place_by_name: dict[str, str] = {}
        for h in self.base.all("Place"):
            nm = self.reader.place_name(self.base.all("Place")[h])
            self.place_by_name.setdefault(nm, h)
        self.tags_by_name = {tg.get("name"): h for h, tg in self.base.all("Tag").items()}
        # étiquettes de l'utilisateur (#262) : un nom -> la première dans l'ordre de priorité (doublons jamais fusionnés)
        self.user_tags: dict[str, str] = {}
        for h, tg in sorted(self.base.all("Tag").items(), key=lambda kv: (kv[1].get("priority") or 0, kv[0])):
            if tg.get("name") and not geree(tg["name"]):
                self.user_tags.setdefault(tg["name"], h)
        self.next_priority = max([(tg.get("priority") or 0) for tg in self.base.all("Tag").values()] or [-1]) + 1
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
        if name == AUTO_TAG:  # étiquette existante réutilisée quelle que soit sa forme (migration explicite)
            h = self.tags_by_name.get(AUTO_TAG) or self.tags_by_name.get(marqueurs.AUTO[marqueurs.SOSA])
            name = name if h else marqueurs.ecrit(name, self.forme)
        else:
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

    def user_tag(self, name: str) -> str:
        """Handle de l'étiquette de l'utilisateur ``name`` : existante (couleur, priorité intactes), sinon créée dans
        la même transaction (handle déterministe, couleur par défaut de Gramps, priorité suivante)."""
        h = self.user_tags.get(name)
        if h:
            if h not in self.out.all("Tag") and self.base.get("Tag", h):
                self.out.put(copy.deepcopy(self.base.get("Tag", h)))
            return h
        h = det_handle("Tag", name)
        while self.base.get("Tag", h) or self.out.get("Tag", h):  # handle pris (autre nom) : jamais réécrit
            h = det_handle("Tag", name, h)
        tg = blank("Tag", h)
        tg.update(name=name, priority=self.next_priority)
        self.next_priority += 1
        self.user_tags[name] = h
        self.out.put(tg)
        return h

    def tag_list(self, base_list: list[str] | None, names: list[str]) -> list[str]:
        """tag_list écrit par-dessus l'état lu : handles et ordre conservés, étiquettes gérées et handles sans objet
        Tag intacts ; étiquette retirée -> handle retiré (l'objet Tag reste) ; étiquette ajoutée -> en fin de liste."""
        base_list = list(base_list or [])
        keep, present = [], set()
        for h in base_list:
            tg = self.base.get("Tag", h)
            name = (tg or {}).get("name") or ""
            if tg is None or not name or geree(name):
                keep.append(h)
            elif name in names:
                keep.append(h)
                present.add(name)
        for name in names:
            if name not in present:
                keep.append(self.user_tag(name))
                present.add(name)
        return _same_list(base_list, keep)

    def written(self, a: dict, forme: str | None = None) -> dict:
        """Attribut (type logique) dans la forme écrite."""
        nom = marqueurs.ecrit(tname(a.get("type")), forme or self.forme)
        return a if nom == tname(a.get("type")) else {**a, "type": gtype(a["type"].get("_class", "AttributeType"),
                                                                            nom)}

    def set_attrs(self, obj: dict, owned, desired: list[dict]) -> None:
        """Remplace les attributs gérés par Genealogiste (``owned(type logique)``), conserve les autres et l'ordre.
        Un attribut inchangé garde sa forme (sosa ou genealogiste). Un attribut à valeur unique porté sous les deux
        formes : l'ancienne forme est laissée intacte (migration : doublon retiré ou incohérence signalée), la
        nouvelle est mise à jour."""
        base = obj.get("attribute_list") or []
        keep, pending = [], list(desired)
        formes: dict[str, set[str]] = {}
        for a in base:
            formes.setdefault(_atype(a), set()).add(marqueurs.forme_de(tname(a.get("type"))))
        doubles = {t for t, f in formes.items() if t not in marqueurs.MULTIPLES
                   and {marqueurs.SOSA, marqueurs.GENEALOGISTE} <= f}
        for a in base:
            typ = _atype(a)
            if not owned(typ) or (typ in doubles and marqueurs.forme_de(tname(a.get("type"))) == marqueurs.SOSA):
                keep.append(a)
                continue
            same = next((d for d in pending if tname(d.get("type")) == typ and d.get("value") == a.get("value")
                         and d.get("citation_list", []) == a.get("citation_list", [])), None)
            if same is not None:
                pending.remove(same)
                keep.append(a)
        pending = [self.written(d, marqueurs.GENEALOGISTE if tname(d.get("type")) in doubles else None)
                   for d in pending]
        obj["attribute_list"] = _same_list(base, keep + pending)

    def media_refs(self, obj: dict, ids: list[str]) -> None:
        """media_list d'une personne, famille, source ou d'un événement : références existantes conservées (cadrage,
        citations)."""
        base_media = {m.get("ref"): m for m in obj.get("media_list") or []}
        medias = []
        for mid in ids:
            if mid in self.t.medias:
                mh = self.handle("Media", mid)
                medias.append(copy.deepcopy(base_media.get(mh)) or {
                    "_class": "MediaRef", "private": False, "citation_list": [], "note_list": [],
                    "ref": mh, "attribute_list": [], "rect": None})
        obj["media_list"] = _same_list(obj.get("media_list") or [], medias)

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
                bc = self.base.get("Citation", h)
                if h not in self.out.all("Citation"):
                    self.out.put(copy.deepcopy(bc))
                    for nh in bc.get("note_list") or []:
                        if self.base.get("Note", nh) and nh not in self.out.all("Note"):
                            self.out.put(copy.deepcopy(self.base.get("Note", nh)))
                    self.stats["citations"] += 1
                self.out.get("Citation", h)["tag_list"] = self.tag_list(bc.get("tag_list"), c.tags)
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
        obj["private"] = c.prive
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
                ("QUAY", str(c.qualite) if c.qualite == 2 else ""), ("ARK", c.ark)]
        obj["attribute_list"] = [attribute(k, v, src=True) for k, v in vals if v]
        obj["media_list"] = [{"_class": "MediaRef", "private": False, "citation_list": [], "note_list": [],
                              "ref": self.handle("Media", mid), "attribute_list": [], "rect": None}
                             for mid in c.medias if mid in self.t.medias]
        obj["tag_list"] = self.tag_list([], c.tags)
        return obj

    def markdown_styles(self, text: str) -> list[dict] | None:
        """Mise en forme Markdown de la proposition (#279) pour ce texte de note : texte converti tel quel, ou contenu
        une seule fois dans la note (texte complété par l'opération, par ex. mention « Non sourcé : … »)."""
        if text in self.t.styles:
            return copy.deepcopy(self.t.styles[text])
        for cle in sorted(self.t.styles, key=len, reverse=True):
            if cle and text.count(cle) == 1:
                d = text.index(cle)
                return [dict(t, ranges=[[a + d, b + d] for a, b in t["ranges"]]) for t in copy.deepcopy(
                    self.t.styles[cle])]
        return None

    def styles(self, text: str, h: str) -> list[dict]:
        """Mise en forme d'une note créée ou réécrite : celle du Markdown de la proposition, sinon aucune ; ses liens
        internes sont vérifiés à la fin (:meth:`resolve_links`)."""
        tags = self.markdown_styles(text)
        if tags is None:
            return []
        self.styled.append(h)
        return tags

    def plain_note(self, text: str, typ: str, key: str) -> str:
        h = det_handle("Note", key, typ, text)
        n = self.start("Note", h)
        n["text"] = {"_class": "StyledText", "string": text, "tags": self.styles(text, h)}
        n["type"] = gtype("NoteType", typ)
        self.out.put(n)
        self.stats["notes"] += 1
        return h

    def rewrite_note(self, h: str, text: str) -> str:
        """Note existante dont le texte change (#279) : même handle, étiquettes, type et confidentialité."""
        n = self.start("Note", h)
        self.restyle(n, text)
        self.out.put(n)
        self.stats["notes"] += 1
        return h

    def restyle(self, n: dict, text: str) -> None:
        """Nouveau texte d'une note existante : mise en forme de la proposition (Markdown) si elle en a une, sinon
        styles gardés sur le préfixe et le suffixe communs inchangés, les autres retirés et signalés."""
        h = n["handle"]
        old = (n.get("text") or {})
        if self.markdown_styles(text) is not None:
            tags, retires = self.styles(text, h), []
        else:
            tags, retires = ajuster(old.get("string") or "", copy.deepcopy(old.get("tags") or []), text)
        if retires:
            self.avis.append(f"Note {n.get('gramps_id') or h} réécrite : mise en forme retirée (plage modifiée) : "
                             + " ; ".join(retires))
        n["text"] = {**old, "_class": "StyledText", "string": text, "tags": tags}

    def notes(self, texts: list[str], base_handles: list[str] | None, typ: str, owner: str,
              auto: list[tuple] | None = None, url: str = "", keep: bool = False) -> list[str]:
        """Notes d'un objet : manuelles réutilisées à l'identique, partagées (@N1@), générées (Genealogiste:auto).
        Une note manuelle dont le texte change garde son handle (#279 : celles qui ne retrouvent pas leur texte
        sont réécrites dans l'ordre, voir :meth:`rewrite_note`)."""
        base_handles = list(base_handles or [])
        if self.generated:  # note de preuve venue d'un GEDCOM : régénérée, jamais doublée en note manuelle (#15)
            texts = [t for t in texts if not looks_generated(t)]
        avail, auto_avail, privees = [], [], []
        for h in base_handles:
            n = self.base.get("Note", h)
            if n is None:
                continue
            if n.get("private") and not self.reader.is_auto(n):  # hors modèle : conservée telle quelle
                privees.append(h)
                if h not in self.out.all("Note"):
                    self.out.put(copy.deepcopy(n))
            elif self.reader.is_auto(n):
                auto_avail.append(h)
            else:
                avail.append((h, self.reader.note_text(n)))
        hits: dict[int, str] = {}
        for i, text in enumerate(texts):
            if text.startswith("@") and text.endswith("@") and len(text) > 2:
                continue
            hit = next((x for x in avail if x[1] == text), None)
            if hit:
                avail.remove(hit)
                hits[i] = hit[0]
        out = list(privees)
        if self.partagees is None:
            self.partagees = {self.handle("Note", k) for k in self.t.notes}
        libres = [h for h, _ in avail if h not in self.partagees]  # notes en ligne à réécrire, jamais une partagée
        for i, text in enumerate(texts):
            if text.startswith("@") and text.endswith("@") and len(text) > 2:
                key = text.strip("@")
                if key in self.t.notes:
                    out.append(self.shared_note(key))
                continue
            if i in hits:
                if hits[i] not in self.out.all("Note"):
                    self.out.put(copy.deepcopy(self.base.get("Note", hits[i])))
                    self.stats["notes"] += 1
                out.append(hits[i])
            elif libres:
                out.append(self.rewrite_note(libres.pop(0), text))
            else:
                out.append(self.plain_note(text, typ, f"{owner}:{i}"))
        if keep:  # notes générées non recalculées : conservées à l'identique (#16)
            for h in auto_avail:
                if h not in self.out.all("Note"):
                    self.out.put(copy.deepcopy(self.base.get("Note", h)))
                out.append(h)
            auto_avail = []
        for i, (atype, text, *plages) in enumerate(auto or []):
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
            self.liens_en_attente.append((h, owner, plages[0] if plages else []))
            out.append(h)
        return _same_list(base_handles, out)

    def single(self, text: str, base_handles: list[str] | None, typ: str, owner: str,
               auto: list[tuple] | None = None, url: str = "", keep: bool = False, corps: str = "") -> list[str]:
        """Champ texte unique : la base est gardée telle quelle si son texte est inchangé. Sinon (#279) les notes
        manuelles dont le texte reste en tête ou en queue du champ (séparateur « \\n\\n ») sont gardées, la première
        des autres reçoit le texte du milieu (handle, étiquettes et type gardés), les suivantes sont retirées.
        ``corps`` : note privée comptée comme manuelle (corps d'un billet privé, #261)."""
        if self.generated and looks_generated(text):  # note de preuve venue d'un GEDCOM (#15)
            text = ""
        manual = [h for h in base_handles or [] if self.base.get("Note", h)
                  and not self.reader.is_auto(self.base.get("Note", h))
                  and (not self.base.get("Note", h).get("private") or h == corps)]
        if manual and self.reader.single_note(manual, corps) == text:
            for h in manual:
                if h not in self.out.all("Note"):
                    self.out.put(copy.deepcopy(self.base.get("Note", h)))
            autos = [h for h in base_handles or [] if h not in manual]
            return _same_list(list(base_handles or []), manual + self.notes([], autos, typ, owner, auto, url, keep))
        if not manual:
            return self.notes([text] if text else [], base_handles, typ, owner, auto, url, keep)
        if not text:  # notes manuelles retirées (le corps privé d'un billet aussi : il est dans le modèle)
            return self.notes([], [h for h in base_handles or [] if h not in manual], typ, owner, auto, url, keep)
        textes = [self.reader.note_text(self.base.get("Note", h)) for h in manual]
        tete, pos = 0, 0
        while tete < len(manual) and text.startswith(textes[tete] + "\n\n", pos):
            pos += len(textes[tete]) + 2
            tete += 1
        reste, queue = text[pos:], 0
        while queue < len(manual) - tete and reste.endswith("\n\n" + textes[len(manual) - 1 - queue]):
            reste = reste[:-len(textes[len(manual) - 1 - queue]) - 2]
            queue += 1
        milieu = manual[tete:len(manual) - queue]
        garde = manual[:tete] + manual[len(manual) - queue:]
        for h in garde:
            if h not in self.out.all("Note"):
                self.out.put(copy.deepcopy(self.base.get("Note", h)))
        if milieu:
            centre = [self.rewrite_note(milieu[0], reste)] if reste else []
        else:
            centre = [self.plain_note(reste, typ, f"{owner}:0")] if reste else []
        autres = [h for h in base_handles or [] if h not in manual]
        return _same_list(list(base_handles or []), manual[:tete] + centre + manual[len(manual) - queue:]
                          + self.notes([], autres, typ, owner, auto, url, keep))

    def billet(self, s: Source, base_src: dict | None, corps: str, note_list: list[str]) -> list[str]:
        """Billet créé ou modifié (#261) : corps (première note du champ ``note``) en tête de ``note_list`` (la page
        Blog de Gramps Web affiche la première note), notes générées (lien de la source) en dernier ; corps et notes
        générées privés comme la source ; corps créé étiqueté Blog, comme le fait l'interface. Les autres notes
        privées (hors du modèle) gardent leur confidentialité et leur texte."""
        autos_tags = auto_tags(self.base) | auto_tags(self.out)
        base_list = (base_src or {}).get("note_list") or []
        cachees = {h for h in base_list if h != corps and (n := self.base.get("Note", h)) and n.get("private")
                   and not self.reader.is_auto(n)}

        def auto(h: str) -> bool:
            n = self.out.get("Note", h) or {}
            return bool(autos_tags & set(n.get("tag_list") or [])) or looks_generated(self.reader.note_text(n))

        autos = [h for h in note_list if auto(h)]
        manuelles = [h for h in note_list if h not in autos]
        tete = next((h for h in manuelles if h not in cachees), "") if s.note else ""
        ordre = ([tete] if tete else []) + [h for h in manuelles if h != tete] + autos
        for h in ([tete] if tete else []) + autos:
            n = self.out.get("Note", h)
            if n is not None and bool(n.get("private")) != s.prive:
                n["private"] = s.prive
        if tete and not self.base.get("Note", tete):
            n = self.out.get("Note", tete)
            n["tag_list"] = self.tag_list(n.get("tag_list"), [BLOG])
        if base_src is not None and ordre != note_list:
            self.avis.append(f"Billet {s.id} : corps remis en première note de la source (la page Blog de Gramps Web "
                             "affiche la première note), notes générées après.")
        return ordre

    def shared_note(self, key: str) -> str:
        h = self.handle("Note", key)
        if h not in self.out.all("Note"):
            n = self.start("Note", h, key)
            if not self.base.get("Note", h):
                n["text"] = {"_class": "StyledText", "string": self.t.notes[key], "tags": self.styles(self.t.notes[key], h)}
            elif self.reader.note_text(n) != self.t.notes[key]:
                self.restyle(n, self.t.notes[key])
            n["private"] = key in self.t.notes_privees
            n["tag_list"] = self.tag_list(n.get("tag_list"), self.t.notes_tags.get(key, []))
            self.out.put(n)
            self.stats["notes"] += 1
        return h

    def resolve_links(self) -> None:
        """Liens internes des notes générées (#279), une fois tous les objets écrits : un lien ne vise jamais un objet
        absent. Une note dont le texte change, nouvelle, ou un recalcul (gramps_recalculer_notes) prennent la forme
        voulue par GENEALOGISTE_GRAMPS_NOTES_LIENS ; une note inchangée garde sa forme (activer ou désactiver
        l'option ne réécrit rien sans recalcul)."""
        for nh, owner, plages in self.liens_en_attente:
            n = self.out.get("Note", nh)
            base = self.base.get("Note", nh)
            texte = n["text"]["string"]
            internes = [t for t in ((base or {}).get("text") or {}).get("tags") or []
                        if tname(t.get("name")) == "link" and cible_interne(t.get("value"))]
            if self.recalcul or base is None or self.reader.note_text(base) != texte:
                liee = self.liens
            else:
                liee = bool(internes)
            if not liee:
                continue
            voulus: dict[str, list[list[int]]] = {}
            if self.liens:
                for a, b, cible in plages:
                    h = self.link_target(cible, owner)
                    if h and 0 <= a < b <= len(texte):
                        voulus.setdefault(lien_interne(h[0], h[1]), []).append([a, b])
            else:  # option désactivée, note inchangée : liens existants gardés jusqu'au recalcul, s'ils visent un objet
                for t in internes:
                    cls, prop, val = cible_interne(t["value"])
                    if prop == "handle" and self.out.get(cls, val) and plages_valides(texte, [t]):
                        voulus.setdefault(t["value"], []).extend(t.get("ranges") or [])
            liens = sorted((lien_tag("link", sorted(r), v) for v, r in voulus.items()),
                           key=lambda t: (t["ranges"][0], t["value"]))
            n["text"]["tags"] = n["text"]["tags"] + liens
        ids = {}
        for nh in dict.fromkeys(self.styled):
            n = self.out.get("Note", nh)
            garde = []
            for t in n["text"]["tags"]:
                c = cible_interne(t.get("value")) if tname(t.get("name")) == "link" else None
                if c and c[1] == "gramps_id" and c[0] not in ids:
                    ids[c[0]] = {o.get("gramps_id") for o in self.out.all(c[0]).values()}
                if c and not (self.out.get(c[0], c[2]) if c[1] == "handle" else c[2] in ids[c[0]]):
                    self.avis.append(f"Note {n.get('gramps_id') or nh} : lien interne {t['value']} retiré (aucun objet "
                                     f"{c[0]} {c[2]} dans l'arbre) : " + decrire(t, n["text"]["string"]))
                else:
                    garde.append(t)
            n["text"]["tags"] = garde

    def link_target(self, cible: tuple, owner: str) -> tuple[str, str] | None:
        """(classe, handle) d'une cible de :func:`proof_data`, si l'objet est écrit."""
        cls = cible[0]
        if cls == "Event":
            h = self.ev_handle.get((cible[1], cible[2]))
        elif cls == "Citation":
            hs = self.cit_evt.get(owner) or []
            h = hs[cible[1]] if cible[1] < len(hs) else None
        else:
            h = self.handle(cls, cible[1])
        return (cls, h) if h and self.out.get(cls, h) else None

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
            parts = place_levels(pl.nom)
            if len(parts) > 1:  # hiérarchie Gramps : commune → département → … → pays (#11)
                obj["title"] = ""
                obj["name"]["value"] = parts[0]
                obj["place_type"] = gtype("PlaceType", level_type(parts, 0))
                obj["placeref_list"] = [{"_class": "PlaceRef", "ref": self.parent_place(parts[1:]),
                                         "date": blank_date()}]
            else:
                obj["title"] = pl.nom
                obj["name"]["value"] = pl.nom.split(",")[0].strip()
        # compléter sans écraser : code INSEE, coordonnées
        if pl.code_insee and not obj.get("code"):
            obj["code"] = pl.code_insee
        if pl.latitude is not None and pl.longitude is not None and not obj.get("lat"):
            obj["lat"], obj["long"] = str(pl.latitude), str(pl.longitude)
        self.out.put(obj)
        return h

    def parent_place(self, parts: list[str]) -> str:
        """Lieu englobant (département, pays…) : réutilisé s'il existe déjà sous ce nom complet, sinon créé."""
        full = ", ".join(parts)
        h = self.place_by_name.get(full)
        if h and (self.out.get("Place", h) or self.base.get("Place", h)):
            if not self.out.get("Place", h):
                self.out.put(copy.deepcopy(self.base.get("Place", h)))
            return h
        h = h or det_handle("Place", full)
        self.place_by_name[full] = h
        obj = blank("Place", h, f"P{h[:6]}")
        obj["name"]["value"] = parts[0]
        obj["place_type"] = gtype("PlaceType", level_type(parts, 0))
        dep = next((c for c, n in DEPARTEMENTS.items() if n == parts[0]), "")
        if dep and len(parts) > 1 and parts[-1] == "France":
            obj["code"] = dep
        if len(parts) > 1:
            obj["placeref_list"] = [{"_class": "PlaceRef", "ref": self.parent_place(parts[1:]), "date": blank_date()}]
        self.out.put(obj)
        return h

    def structure_places(self) -> None:
        """Lieux à plat de la base (titre « Commune, Département, Pays », sans lieu englobant) rattachés à une
        hiérarchie ; le nom lu reste identique (aller-retour)."""
        for h, p in sorted(self.base.all("Place").items()):
            title = p.get("title") or ""
            parts = place_levels(title)
            if len(parts) < 2 or p.get("placeref_list"):
                continue
            obj = copy.deepcopy(self.out.get("Place", h) or p)
            obj["title"] = ""
            obj["name"] = dict(obj.get("name") or blank("Place", h)["name"], value=parts[0])
            if tcanon(obj.get("place_type")) in ("", "Unknown", "City"):
                obj["place_type"] = gtype("PlaceType", level_type(parts, 0))
            obj["placeref_list"] = [{"_class": "PlaceRef", "ref": self.parent_place(parts[1:]), "date": blank_date()}]
            self.out.put(obj)

    # ------------------------------------------------------------------ événements
    def event(self, e: Event, owner: str, owner_cls: str) -> str:
        h = self.info.handles.get(("Event", e.uid)) or det_handle("Event", e.uid)
        obj = self.start("Event", h)
        obj["private"] = e.prive
        base_e = None
        if self.base.get("Event", h):
            base_e = self.reader.event(h, owner, owner_cls, {})
        if base_e is None or (base_e.type, base_e.type_detail) != (e.type, e.type_detail):
            name = TYPES.get(e.type) or e.type_detail or EVEN_DEFAULT
            obj["type"] = gtype_ecrit("EventType", name)  # standard quand il existe (#273)
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
        base_asso = {a.get("value"): a for a in _attrs(obj) if _atype(a) == A_ASSO}
        for rang, a in enumerate(e.associations, 1):
            if a.personne and a.personne in self.t.personnes:
                self.links.append((a.personne, h, rang, a, owner, e))
                self.stats["temoins_lies"] += 1
            elif a.nom or a.personne:
                val = asso_value(rang, a)
                prev = base_asso.get(val)
                desired.append(attribute(A_ASSO, val, self.citations(
                    a.citations, (prev or {}).get("citation_list"), f"{h}:asso:{rang}")))
                self.stats["temoins_nommes"] += 1
        self.set_attrs(obj, lambda t: t in (A_UID, A_STATUT, A_CAUSE, A_PAROISSE, A_PRECISION, A_ASSO), desired)
        self.cit_evt[h] = self.citations(e.citations, obj.get("citation_list"), h)
        obj["citation_list"] = _same_list(obj.get("citation_list") or [], self.cit_evt[h])
        self.media_refs(obj, e.medias)
        regen = self.regen("Event", e.uid)
        obj["note_list"] = self.single(e.note, obj.get("note_list"), "Event Note", h, self.auto("Event", e.uid),
                                       keep=not regen)
        tags = [x for x in self.tag_list(obj.get("tag_list"), e.tags) if not regen or x not in self.reader.status_tags]
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

    def ref_with(self, base_refs: list[dict], handle: str, role: str, attrs: list[dict] | None, cits: list[str],
                 prev: dict | None | bool = False) -> dict:
        """Référence d'événement par-dessus celle de la base : ``prev`` donnée (ou None : nouvelle), sinon cherchée
        par rôle (libellés reconnus : « Principal » = Primary, #273) ; rôle de la base conservé. ``attrs`` None :
        attributs de la base gardés tels quels."""
        if prev is False:
            prev = next((r for r in base_refs if r.get("ref") == handle and tcanon(r.get("role")) == role), None)
        ref = copy.deepcopy(prev) if prev else event_ref(handle, role)
        if attrs is None:
            ref["citation_list"] = _same_list(ref.get("citation_list") or [], cits)
            return ref
        owned = {A_AGE, A_ASSO}
        keep = [a for a in ref.get("attribute_list") or [] if _atype(a) not in owned]
        old_owned = [a for a in ref.get("attribute_list") or [] if _atype(a) in owned]
        new_owned = [self.written(a) for a in attrs]
        if [(_atype(a), a["value"]) for a in old_owned] == [(_atype(a), a["value"]) for a in new_owned]:
            new_owned = old_owned
        ref["attribute_list"] = keep + new_owned
        ref["citation_list"] = _same_list(ref.get("citation_list") or [], cits)
        return ref

    # ------------------------------------------------------------------ construction
    def build(self) -> GrampsDb:
        t, base, out = self.t, self.base, self.out
        self.links: list[tuple[str, str, int, Association, str]] = []
        # objets de la base non représentés dans Genealogiste : conservés tels quels (lieux, notes isolées…)
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
            obj["private"] = p.prive
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
            obj["private"] = f.prive
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
                frel, mrel = tcanon(cr["frel"]), tcanon(cr["mrel"])
                lu = frel if frel != "Birth" else mrel
                if PEDI_CODES.get(lu, lu.upper()) != (link.filiation if link.filiation != "BIRTH" else ""):
                    rel = PEDI.get(link.filiation, link.filiation.capitalize())
                    cr["frel"] = cr["mrel"] = gtype_ecrit("ChildRefType", rel)
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
            self.media_refs(obj, f.medias)
            obj["note_list"] = self.notes(f.notes, obj.get("note_list"), "Family Note", h, self.auto("Family", fid),
                                          keep=not self.regen("Family", fid))
            obj["tag_list"] = self.tag_list(obj.get("tag_list"), f.tags)
            fams[fid] = obj
            self.stats["familles"] += 1
        # personnes : noms, références (propres, témoins), associations, notes
        witness_refs: dict[str, list[dict]] = {}
        used: set[int] = set()
        for pid_w, eh, rang, a, owner, ev in self.links:
            base_refs = people[pid_w].get("event_ref_list") or []
            asso = asso_value(rang, a, with_name=False)
            prev = next((r for r in base_refs if r.get("ref") == eh and _attr_value(r, A_ASSO)
                         and asso_parse(_attr_value(r, A_ASSO))[0] == rang), None)
            # référence saisie dans l'interface (sans attribut structuré), relue comme cette association, dans un
            # événement aux intervenants inchangés : gardée telle quelle (rôle personnalisé d'origine, #273)
            plain = None
            if self.assos_base.get((owner, ev.uid)) == [x.to_dict() for x in ev.associations]:
                plain = next((r for r in base_refs if r.get("ref") == eh and id(r) not in used
                              and not _attr_value(r, A_ASSO)
                              and role_guess(tcanon(r.get("role"))) == (a.role, a.detail)), None)
            if plain is not None:
                used.add(id(plain))
                cits = self.citations(a.citations, plain.get("citation_list"), f"{eh}:lien:{rang}")
                ref = self.ref_with(base_refs, eh, "", None, cits, prev=plain)
            elif prev is not None and _attr_value(prev, A_ASSO) == asso:  # association inchangée : rôle conservé
                cits = self.citations(a.citations, prev.get("citation_list"), f"{eh}:lien:{rang}")
                ref = self.ref_with(base_refs, eh, "", [attribute(A_ASSO, asso)], cits, prev=prev)
            else:
                role = event_role(a)
                cits = self.citations(a.citations, (prev or {}).get("citation_list"), f"{eh}:lien:{rang}")
                ref = self.ref_with(base_refs, eh, role, [attribute(A_ASSO, asso)], cits)
            witness_refs.setdefault(pid_w, []).append(ref)
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
                cur_type = NAME_CODES.get(tcanon(nb.get("type")), tcanon(nb.get("type")))
                if cur_type != (n.type if n.type != "BIRTH" else ""):
                    nb["type"] = gtype_ecrit("NameType", NAME_TYPES.get(n.type, n.type or "Birth Name"))
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
            self.media_refs(obj, p.medias)
            # associations de niveau individu (parrains…) : attribut structuré + personref navigable
            base_attr = {a.get("value"): a for a in _attrs(obj) if _atype(a) == A_ASSO}
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
            obj["tag_list"] = self.tag_list(obj.get("tag_list"), p.tags)
            out.put(obj)
            self.stats["personnes"] += 1
        for obj in fams.values():
            out.put(obj)
        for sid in sorted(t.sources):
            s = t.sources[sid]
            h = self.handle("Source", sid)
            obj = self.start("Source", h, sid)
            obj.update(title=s.titre, author=s.auteur, pubinfo=s.publication, private=s.prive)
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
                ("URL", s.url), ("ARK", s.ark)) if v]
            self.set_attrs(obj, lambda x: x in SRC_ATTRS, desired)
            self.media_refs(obj, s.medias)
            regen = self.regen("Source", sid)
            auto = [("Source Note", f"Lien : {s.url}")] if s.url and regen else None
            if s.url:
                self.stats["sources_url"] += 1
            base_src = self.base.get("Source", h)
            corps = self.reader.corps_billet(base_src)
            obj["note_list"] = self.single(s.note, obj.get("note_list"), "Source Note", h, auto, url=s.url,
                                           keep=not regen, corps=corps)
            obj["tag_list"] = self.tag_list(obj.get("tag_list"), s.tags)
            avant = self.sources_base.get(sid)
            if BLOG in s.tags and (base_src is None or avant is None or avant.to_dict() != s.to_dict()):
                obj["note_list"] = self.billet(s, base_src, corps, obj["note_list"])
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
            obj["tag_list"] = self.tag_list(obj.get("tag_list"), r.tags)
            out.put(obj)
        for mid in sorted(t.medias):
            m = t.medias[mid]
            h = self.handle("Media", mid)
            obj = self.start("Media", h, mid)
            obj["private"] = m.prive
            base = self.base.get("Media", h)
            if not (base and base.get("checksum")):  # fichier pas encore reçu par le serveur
                obj.update(path=m.fichier, mime=m.format or _mime(m.fichier))
            elif m.format != (base.get("mime") or ""):  # fichier reçu : chemin et somme du serveur conservés (#193)
                obj["mime"] = m.format or _mime(m.fichier)  # (nouveau contenu : renvoyé après la transaction)
            obj["desc"] = m.titre
            self.set_attrs(obj, lambda x: x == A_FICHIER, [attribute(A_FICHIER, m.fichier)] if m.fichier else [])
            obj["citation_list"] = _same_list(obj.get("citation_list") or [],
                                              self.citations(m.citations, obj.get("citation_list"), h))
            obj["tag_list"] = self.tag_list(obj.get("tag_list"), m.tags)
            out.put(obj)
        for key in sorted(t.notes):
            self.shared_note(key)
        self.resolve_links()
        return out

    def ref_index(self, p: Person, refs: list[dict], typ: str) -> int:
        uid = self.gen["best"].get((p.id, typ)) or next((e.uid for e in p.evenements if e.type == typ), None)
        want = self.ev_handle.get((p.id, uid)) if uid else None
        return next((i for i, r in enumerate(refs) if want and r.get("ref") == want
                     and tcanon(r.get("role")) == "Primary"), -1)


def tree_to_gramps(tree: Tree, base: GrampsDb | None = None, strict: bool = False,
                   generated: bool = True, only: set[tuple[str, str]] | None = None,
                   structure: bool = False, forme: str = marqueurs.GENEALOGISTE, liens: bool = False,
                   recalcul: bool = False, avis: list[str] | None = None) -> GrampsDb:
    """Arbre Genealogiste -> base Gramps (par-dessus ``base`` si fournie). ``generated`` : notes générées
    (Genealogiste:auto) ; ``forme`` : forme écrite des marqueurs nouveaux ou modifiés (#182) ; ``only`` :
    les recalculer seulement pour ces objets (cls, clé Genealogiste), celles des autres sont conservées telles quelles ;
    ``structure`` : rattacher aussi les lieux à plat de la base à une hiérarchie ; ``liens`` : liens internes
    gramps:// dans les notes générées (#279) ; ``recalcul`` : recalcul explicite des notes (seul à changer la forme
    d'une note générée inchangée) ; ``avis`` : reçoit les mises en forme retirées (texte modifié, lien invalide)."""
    w = _Writer(tree, base, strict, generated, only, forme, liens, recalcul)
    out = w.build()
    if avis is not None:
        avis.extend(w.avis)
    if structure:
        w.structure_places()
    return out


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
    """Élément de transaction qui ne porte que sur des notes ou étiquettes de preuve générées. ``auto_tags`` :
    handles des étiquettes gérées (:func:`etiquettes_gerees`) ; une étiquette de l'utilisateur posée ou retirée
    n'est jamais « de preuve seule »."""
    cls = item["_class"]
    obj = item.get("new") or item.get("old") or {}
    if cls == "Note":
        return bool(auto_tags & set(obj.get("tag_list") or [])) or looks_generated(
            ((obj.get("text") or {}).get("string")) or "")
    if cls == "Tag":
        name = obj.get("name") or ""
        return marqueurs.canon(name) == AUTO_TAG or name.startswith(STATUS_TAG)
    if item["type"] != "update":
        return False
    old, new = _strip_change(item["old"]), _strip_change(item["new"])
    keys = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
    if "tag_list" in keys and not set(old.get("tag_list") or []) ^ set(new.get("tag_list") or []) <= auto_tags:
        return False  # étiquette de l'utilisateur posée ou retirée (#262) : vraie modification
    return bool(keys) and keys <= {"note_list", "tag_list"}


def etiquettes_gerees(db: GrampsDb, items: list[dict] | None = None) -> set[str]:
    """Handles des étiquettes gérées par Genealogiste (notes générées, statut de preuve), y compris celles créées
    par ``items``."""
    tags = dict(db.all("Tag"))
    for it in items or []:
        if it["_class"] == "Tag" and it.get("new"):
            tags[it["handle"]] = it["new"]
    return {h for h, tg in tags.items() if geree(tg.get("name") or "")}


def lignes_etiquettes(db: GrampsDb, items: list[dict]) -> list[str]:
    """Diff concis des étiquettes de l'utilisateur d'une transaction : une ligne par objet (« étiquettes I12 :
    +Blog −ToDo »)."""
    noms = {h: tg.get("name") or "" for h, tg in db.all("Tag").items()}
    for it in items:
        if it["_class"] == "Tag":
            noms[it["handle"]] = (it.get("new") or it.get("old") or {}).get("name") or ""
    out = []
    for it in items:
        if it["_class"] == "Tag":
            continue
        avant = [noms[h] for h in (it.get("old") or {}).get("tag_list") or [] if h in noms and not geree(noms[h])]
        apres = [noms[h] for h in (it.get("new") or {}).get("tag_list") or [] if h in noms and not geree(noms[h])]
        plus = list(dict.fromkeys(x for x in apres if x not in avant))
        moins = list(dict.fromkeys(x for x in avant if x not in apres))
        if plus or moins:
            o = it.get("new") or it.get("old") or {}
            out.append(ligne_etiquettes(o.get("gramps_id") or f"{it['_class']} {it['handle']}", plus, moins))
    return out


def _liens_internes(note: dict | None) -> set[tuple[str, int, int]]:
    tags = (((note or {}).get("text") or {}).get("tags")) or []
    return {(t["value"], a, b) for t in tags if tname(t.get("name")) == "link" and cible_interne(t.get("value"))
            for a, b in t.get("ranges") or []}


def liens_internes_changes(items: list[dict]) -> dict[str, int]:
    """Bilan des liens internes gramps:// d'une transaction (#279) : notes qui en gagnent, qui en perdent."""
    gagnent = perdent = 0
    for it in items:
        if it["_class"] != "Note":
            continue
        avant, apres = _liens_internes(it.get("old")), _liens_internes(it.get("new"))
        gagnent += bool(apres - avant)
        perdent += bool(avant - apres)
    return {k: v for k, v in (("notes_avec_liens_ajoutes", gagnent), ("notes_avec_liens_retires", perdent)) if v}


def etiquettes_en_double(db: GrampsDb) -> dict[str, list[str]]:
    """Noms d'étiquettes de l'utilisateur portés par plusieurs objets Tag (l'API n'impose pas l'unicité) : nom ->
    handles dans l'ordre de priorité (le premier est celui que Genealogiste réutilise)."""
    par_nom: dict[str, list[str]] = {}
    for h, tg in sorted(db.all("Tag").items(), key=lambda kv: (kv[1].get("priority") or 0, kv[0])):
        if tg.get("name") and not geree(tg["name"]):
            par_nom.setdefault(tg["name"], []).append(h)
    return {n: hs for n, hs in par_nom.items() if len(hs) > 1}


def tree_to_gramps_stats(tree: Tree, base: GrampsDb | None = None, strict: bool = False,
                         generated: bool = True, forme: str = marqueurs.GENEALOGISTE) -> tuple[GrampsDb, dict]:
    w = _Writer(tree, base, strict, generated, forme=forme)
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


# ---------------------------------------------------------------------------- lieux datés (#277)
#
# Règle de Gramps (gramps/gen/utils/location.py, get_location_list et __get_name ; Date.match_exact) : à la date
# de l'événement, le nom affiché est le PREMIER de [nom principal] + noms alternatifs dont la date est vide ou
# « correspond » (même langue que le format d'affichage d'abord), et le lieu englobant est le premier
# rattachement (placeref) dont la date est vide ou correspond. Correspondance stricte : « avant D » vaut pour un
# événement < D, « après D » pour > D, une plage (de… à…, entre… et…) bornes comprises ; date d'événement vide :
# valeur 0, donc seulement « avant ». Un nom principal sans date l'emporte toujours : il est daté « après » la veille
# de son entrée en vigueur ; un nom ancien vaut « avant » la date du changement (début inconnu : le COG commence en
# 1943), un nom intermédiaire du premier au dernier jour de sa période. Aucun jour sans nom ni recouvrement.

COMMUNE_TYPES = {"City", "Town", "Village", "Municipality"}
CODE_INSEE = re.compile(r"^(?:\d{5}|2[AB]\d{3})$")
_MOIS_GEDCOM = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_INF = float("inf")


def est_commune(p: dict) -> bool:
    """Lieu identifié comme commune : code INSEE et type commune (City, Town, Village, Municipality, ou
    personnalisé « Commune », que Gramps n'a pas : lu comme commune, l'objet n'est pas modifié pour autant)."""
    if not CODE_INSEE.match((p.get("code") or "").strip()):
        return False
    t = p.get("place_type")
    return tcanon(t, "PlaceType") in COMMUNE_TYPES or cle_libelle(tname(t)) == "commune"


def _jour(iso: str, delta: int = 0) -> tuple[str, str]:
    """(date GEDCOM, date ISO) du jour ``iso`` décalé de ``delta`` jours."""
    from datetime import date, timedelta
    d = date.fromisoformat(iso) + timedelta(days=delta)
    return f"{d.day} {_MOIS_GEDCOM[d.month - 1]} {d.year}", d.isoformat()


def periode_gramps(debut: str, fin: str | None, premiere: bool) -> tuple[dict, str]:
    """Date Gramps (et texte lisible) d'une période COG [debut, fin[ : « avant fin » pour la première (début
    inconnu), « après la veille de debut » pour la période en cours, sinon plage du premier au dernier jour."""
    if fin is None:
        g, t = _jour(debut, -1)
        return date_to_gramps(f"AFT {g}"), f"après {t}"
    if premiere:
        g, t = _jour(fin)
        return date_to_gramps(f"BEF {g}"), f"avant {t}"
    (g1, t1), (g2, t2) = _jour(debut), _jour(fin, -1)
    return date_to_gramps(f"FROM {g1} TO {g2}"), f"du {t1} au {t2}"


def _vide(d: dict | None) -> bool:
    return not d or (not any((d.get("dateval") or [0, 0, 0])[:3]) and not d.get("modifier") and not d.get("text"))


def _meme_date(a: dict | None, b: dict | None) -> bool:
    return (_vide(a) and _vide(b)) or (not _vide(a) and not _vide(b) and date_from_gramps(a) == date_from_gramps(b))


def intervalle(d: dict | None) -> tuple[float, float] | None:
    """Jours (valeur de tri) d'événement auxquels la date d'un nom ou d'un rattachement correspond selon
    ``Date.match_exact`` de Gramps ; None : jamais (date textuelle, « vers »)."""
    if _vide(d):
        return (-_INF, _INF)
    mod = d.get("modifier", 0)
    s = valeur_tri(d)
    if mod in MOD_COMPOSES:
        return (s, valeur_tri({**d, "dateval": list((d.get("dateval") or [])[4:8]) + [0, 0, 0, False]}))
    return {0: (s, s), 1: (-_INF, s - 1), 8: (-_INF, s - 1), 2: (s + 1, _INF), 7: (s + 1, _INF)}.get(mod)


def _chevauche(a: dict | None, b: dict | None) -> bool:
    ia, ib = intervalle(a), intervalle(b)
    return ia is not None and ib is not None and max(ia[0], ib[0]) <= min(ia[1], ib[1])


def _texte_date(d: dict | None) -> str:
    return date_from_gramps(d) or "sans date"


def _noms_dates(obj: dict, ch: dict) -> tuple[list[str], list[str]]:
    """Noms anciens datés (alt_names) et date du nom principal ; rien n'est modifié en cas de conflit."""
    noms = ch.get("noms") or []
    if len(noms) < 2:
        return [], []
    principal = obj.get("name") or {}
    actuel = noms[-1]["nom"]
    if cle_libelle(principal.get("value", "")) != cle_libelle(actuel):
        return [], [f"nom « {principal.get('value', '')} » différent du nom actuel du COG « {actuel} » : noms non "
                    "datés (vérifier le code INSEE ou le nom du lieu)"]
    lang = principal.get("lang") or ""
    d_princ, t_princ = periode_gramps(noms[-1]["debut"], None, False)
    conflits, changements, ajouts = [], [], []
    dater = _vide(principal.get("date"))
    if not dater and not _meme_date(principal.get("date"), d_princ):
        conflits.append(f"nom principal déjà daté ({_texte_date(principal.get('date'))}), {t_princ} attendu")
    existants = obj.get("alt_names") or []
    for i, n in enumerate(noms[:-1]):
        d, t = periode_gramps(n["debut"], n["fin"], i == 0)
        if any(a.get("value") == n["nom"] and _meme_date(a.get("date"), d) for a in existants):
            continue  # déjà présent : jamais en double
        autres = [a for a in existants if (a.get("lang") or "") == lang
                  and (a.get("value") == n["nom"] or _chevauche(a.get("date"), d))]
        if autres:
            conflits += [f"« {n['nom']} » ({t}) : nom alternatif « {a.get('value')} » ({_texte_date(a.get('date'))}) "
                         "sur la même période, non tranché" for a in autres]
            continue
        ajouts.append({"_class": "PlaceName", "value": n["nom"], "date": d, "lang": lang})
        changements.append(f"+« {n['nom']} » {t}")
    if conflits:
        return [], conflits
    if dater:
        obj["name"] = {**principal, "date": d_princ}
        changements.append(f"nom principal « {actuel} » {t_princ}")
    if ajouts:
        obj["alt_names"] = existants + ajouts
    return changements, []


def _liens_dates(obj: dict, d0: dict, t0: str, voulus: list[tuple[str, dict, str, str]]) -> tuple[list[str], list[str]]:
    """Rattachements datés : date du premier lien (lieu englobant actuel, qui donne le nom relu) et liens anciens
    ou supplémentaires ``(handle, date, texte, nom)``. Rien n'est modifié en cas de conflit."""
    refs = obj["placeref_list"]
    r0, autres = refs[0], refs[1:]
    conflits, changements, ajouts = [], [], []
    dater = _vide(r0.get("date"))
    if not dater and not _meme_date(r0.get("date"), d0):
        conflits.append(f"rattachement actuel déjà daté ({_texte_date(r0.get('date'))}), {t0} attendu")
    for h, d, t, nom in voulus:
        if any(r.get("ref") == h and _meme_date(r.get("date"), d) for r in autres):
            continue
        ajouts.append({"_class": "PlaceRef", "ref": h, "date": d})
        changements.append(f"rattaché à {nom} {t}")
    for r in autres:
        if any(r.get("ref") == h and _meme_date(r.get("date"), d) for h, d, _, _ in voulus):
            continue
        if any(_chevauche(r.get("date"), d) for d in [d0] + [x[1] for x in voulus]):
            conflits.append(f"rattachement existant ({_texte_date(r.get('date'))}) sur la même période, non tranché")
    if conflits:
        return [], conflits
    if dater:
        refs[0] = {**r0, "date": d0}
        changements.append(f"rattachement actuel {t0}")
    obj["placeref_list"] = refs + ajouts
    return changements, []


def lieu_affiche(get, p: dict | None, sortval: float) -> str:
    """Lieu tel que Gramps l'affiche pour un événement de valeur de tri ``sortval`` (``get_location_list``, format
    par défaut : tous les niveaux, langue vide) ; ``get(handle)`` donne un lieu. « ? » : aucun nom ne correspond."""
    noms, vus = [], set()
    while p is not None and p.get("handle") not in vus:
        vus.add(p.get("handle"))
        ok = [n for n in [p.get("name") or {}, *(p.get("alt_names") or [])]
              if (iv := intervalle(n.get("date"))) is not None and iv[0] <= sortval <= iv[1]]
        noms.append(ok[0].get("value", "") if ok else "?")
        ref = next((r for r in p.get("placeref_list") or []
                    if (iv := intervalle(r.get("date"))) is not None and iv[0] <= sortval <= iv[1]), None)
        p = get(ref.get("ref")) if ref else None
    return ", ".join(noms)


def _impact_non_dates(db: GrampsDb, modifies: dict[str, dict], ajoutes: dict[str, dict]) -> dict[str, list]:
    """Événements de valeur de tri 0 (date vide ; date textuelle, y compris une date invalide importée comme texte :
    ``Date.set_as_text`` et ``_calc_sort_value`` de Gramps) dont le lieu affiché change avec les lieux ``modifies`` :
    lieu modifié (celui de l'événement ou un lieu englobant) -> [(événement, affiché avant, affiché après)]."""
    def avant(h):
        return db.get("Place", h)

    def apres(h):
        return modifies.get(h) or ajoutes.get(h) or db.get("Place", h)
    out: dict[str, list] = {}
    for e in sorted(db.all("Event").values(), key=lambda x: x.get("gramps_id") or x["handle"]):
        lieu = e.get("place")
        if not lieu or valeur_tri(e.get("date") or {}) != 0:
            continue
        a, b = lieu_affiche(avant, avant(lieu), 0), lieu_affiche(apres, apres(lieu), 0)
        if a == b:
            continue
        todo, vus = [lieu], set()
        while todo:  # lieux modifiés de la hiérarchie de l'événement
            h = todo.pop()
            if h in vus:
                continue
            vus.add(h)
            if h in modifies:
                out.setdefault(h, []).append((e.get("gramps_id") or e["handle"], a, b))
            for get in (avant, apres):
                todo += [r.get("ref") for r in (get(h) or {}).get("placeref_list") or []]
    return out


def dater_lieux(db: GrampsDb, chronos: dict[str, dict], ignorer_non_dates: bool = False) -> tuple[list[dict], dict]:
    """Noms et rattachements datés des communes d'une base Gramps d'après leur chronologie COG (``chronos`` : code
    INSEE -> :meth:`sources.geo.IndexCog.chronologie`). Lieu identifié par :func:`est_commune` ; nom relu (titre
    « Commune, Département, Pays ») inchangé : le nom principal et le premier rattachement gardent leur valeur, seule
    leur date est posée. Jamais d'écrasement ni de doublon ; un conflit est listé et le lieu laissé tel quel pour
    ce volet ; aucune fusion de lieux. Effet sur les événements sans date (valeur de tri 0 : nom le plus ancien,
    ancien département) compté par lieu (``evenements_non_dates``, ``avertissement``) ; ``ignorer_non_dates`` :
    ces lieux restent hors de la proposition (``lieux_exclus``). Renvoie (éléments de transaction, rapport)."""
    reader = _Reader(db)
    places = db.all("Place")
    communes = {h: p for h, p in sorted(places.items()) if est_commune(p)}
    par_code: dict[str, list[str]] = {}
    for h, p in communes.items():
        par_code.setdefault(p["code"].strip(), []).append(h)
    ajoutes: dict[str, dict] = {}
    lignes: dict[str, tuple[str, str]] = {}
    rapport: dict = {"lieux": [], "conflits": [], "non_traites": [], "lieux_distincts": []}

    def departement(nom: str, pays: str | None, code: str) -> str:
        for h, p in sorted(places.items()):
            if (p.get("name") or {}).get("value") == nom and tcanon(p.get("place_type"), "PlaceType") == "Department" \
                    and [r.get("ref") for r in p.get("placeref_list") or []][:1] == ([pays] if pays else []):
                return h
        cle = f"{nom}, {reader.place_name(places[pays])}" if pays else nom
        h = det_handle("Place", cle)
        if h not in places and h not in ajoutes:
            o = blank("Place", h, f"P{h[:6]}")
            o["name"]["value"], o["place_type"], o["code"] = nom, gtype("PlaceType", "Department"), code
            if pays:
                o["placeref_list"] = [{"_class": "PlaceRef", "ref": pays, "date": blank_date()}]
            ajoutes[h] = o
        return h

    items = []
    for h, p in communes.items():
        code = p["code"].strip()
        ch = chronos.get(code)
        if not ch:
            continue
        label = f"{p.get('gramps_id') or h} {reader.place_name(p)}"
        obj = copy.deepcopy(p)
        changements, conflits = _noms_dates(obj, ch)
        refs = obj.get("placeref_list") or []
        deps, rats = ch.get("departements") or [], ch.get("rattachements") or []
        if (len(deps) > 1 or rats) and not refs:
            rapport["non_traites"].append(f"{label} : lieu à plat, rattachements datés après gramps_structurer_lieux")
        elif len(deps) > 1:
            parent = places.get(refs[0].get("ref")) or {}
            if cle_libelle((parent.get("name") or {}).get("value", "")) != cle_libelle(deps[-1]["nom"]):
                conflits.append(f"rattaché à « {(parent.get('name') or {}).get('value', '?')} », pas au département "
                                f"actuel « {deps[-1]['nom']} » : rattachements non datés")
            else:
                pays = (parent.get("placeref_list") or [{}])[0].get("ref")
                pays = pays if pays in places else None
                voulus = []
                for i, seg in enumerate(deps[:-1]):
                    d, t = periode_gramps(seg["debut"], seg["fin"], i == 0)
                    voulus.append((departement(seg["nom"], pays, seg["code"]), d, t, seg["nom"]))
                d0, t0 = periode_gramps(deps[-1]["debut"], None, False)
                c, k = _liens_dates(obj, d0, t0, voulus)
                changements += c
                conflits += k
            if rats:
                rapport["non_traites"].append(f"{label} : rattachement à {rats[0]['nom']} ({rats[0]['statut']}) non "
                                              "ajouté en plus d'un changement de département")
        elif rats:
            r = rats[0]
            cibles = [x for x in par_code.get(r["code_insee"], []) if x != h]
            if len(rats) > 1 or r["fin"] is not None:
                rapport["non_traites"].append(
                    f"{label} : " + ", ".join(f"{x['statut']} de {x['nom']} ({x['code_insee']}) du {x['debut']}"
                                              + (f" au {x['fin']}" if x["fin"] else "") for x in rats)
                    + " : non représentable par un seul lien daté, non ajouté")
            elif len(cibles) != 1:
                rapport["non_traites"].append(
                    f"{label} : {r['statut']} de {r['nom']} ({r['code_insee']}) depuis le {r['debut']} : "
                    + ("lieu de cette commune absent de la base" if not cibles else "plusieurs lieux portent ce code")
                    + ", rattachement non ajouté")
            else:
                d0, t0 = periode_gramps(r["debut"], r["debut"], True)  # département seul avant le rattachement
                d, t = periode_gramps(r["debut"], None, False)
                c, k = _liens_dates(obj, d0, t0, [(cibles[0], d, t, f"{r['nom']} ({r['statut']})")])
                changements += c
                conflits += k
        for a in ch.get("absorbees") or []:
            for x in communes:
                q = communes[x]
                if x != h and (q["code"].strip() == a["code_insee"] or (
                        cle_libelle((q.get("name") or {}).get("value", "")) == cle_libelle(a["nom"])
                        and q["code"].strip()[:2] == a["code_insee"][:2])):
                    rapport["lieux_distincts"].append(
                        f"{q.get('gramps_id') or x} {reader.place_name(q)} : {a['nom']} ({a['code_insee']}) réunie à "
                        f"{label} le {a['date']} ({a['type']}) ; lieux gardés distincts, aucune fusion")
        rapport["conflits"] += [f"{label} : {c}" for c in conflits]
        if changements and _strip_change(obj) != _strip_change(p):
            lignes[h] = (label, f"{label} : " + " ; ".join(changements))
            items.append({"type": "update", "_class": "Place", "handle": h, "old": p, "new": obj})
    impact = _impact_non_dates(db, {it["handle"]: it["new"] for it in items}, ajoutes)

    def ligne_impact(h: str) -> str:
        ev = impact[h]
        return (f"{lignes[h][0]} : {len(ev)} événement(s) sans date afficheront « {ev[0][2]} » au lieu de "
                f"« {ev[0][1]} » ({', '.join(x[0] for x in ev[:5])}{', …' if len(ev) > 5 else ''})")
    if ignorer_non_dates:
        rapport["lieux_exclus"] = [ligne_impact(h) for h in impact]
        items = [it for it in items if it["handle"] not in impact]
        impact = _impact_non_dates(db, {it["handle"]: it["new"] for it in items}, ajoutes)
    rapport["lieux"] = [lignes[it["handle"]][1] for it in items]
    rapport["evenements_non_dates"] = [ligne_impact(h) for h in impact]
    n_ev = len({x[0] for v in impact.values() for x in v})
    rapport["nombre_evenements_non_dates"] = n_ev
    if n_ev:
        rapport["avertissement"] = (
            f"{n_ev} événement(s) sans date (vide ou textuelle) sur {len(impact)} lieu(x) afficheront dans Gramps le "
            "nom le plus ancien et l'ancien rattachement au lieu du nom actuel (règle de Gramps : un événement sans "
            "date ne correspond qu'aux noms et rattachements « avant ») ; dater ces événements, ou relancer avec "
            "ignorer_lieux_evenements_non_dates=true pour laisser ces lieux hors de la proposition.")
    utilises = {r.get("ref") for it in items for r in it["new"].get("placeref_list") or []}
    nouveaux = [{"type": "add", "_class": "Place", "handle": h, "old": None, "new": o}
                for h, o in sorted(ajoutes.items()) if h in utilises]
    rapport["lieux"] += [f"{o['gramps_id']} {o['name']['value']} : nouveau lieu (département, code {o['code']})"
                         for o in (x["new"] for x in nouveaux)]
    return nouveaux + items, rapport
