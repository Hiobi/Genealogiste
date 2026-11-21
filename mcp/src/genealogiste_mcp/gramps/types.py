"""Format JSON des objets Gramps (Gramps 6 / Gramps Web) : types, dates, gabarits, normalisation.

Deux représentations coexistent côté Gramps Web :
- le format « brut » (``object_to_dict`` de Gramps) : classes ``_class``, types ``{"_class", "value",
  "string"}`` ; c'est celui des transactions (``/api/transactions/``), dont le champ ``old`` est comparé
  à la base pour détecter les conflits ;
- le format « simplifié » des lectures (``GET /api/people/``) : types en chaîne anglaise (« Birth »),
  pas de ``_class``, ``father_handle`` vide en "" et propriété calculée ``Date.year``.

Tout le plugin travaille en format brut ; :func:`to_raw` convertit une lecture (portage de
``fix_object_dict`` de gramps-web-api). Les tables de types sont extraites de Gramps 6.0
(``_DATAMAP`` : chaîne XML anglaise -> valeur entière) ; ``(personnalisé, défaut, table)``.
"""

from __future__ import annotations

import copy
import functools
import json
import unicodedata
from pathlib import Path
from typing import Any

from ..normalize.calendriers import SDN, YMD
from ..normalize.dates import (
    CALENDRIERS,
    MONTHS,
    DatePoint,
    GenDate,
    analyser_gedcom,
    coupure,
    nouvel_an_texte,
    parse_gedcom_date,
)

TYPES: dict[str, tuple[int, int, dict[str, int]]] = {
    'EventType': (0, 12, {'Unknown': -1,
         'Custom': 0,
         'Adopted': 11,
         'Birth': 12,
         'Death': 13,
         'Adult Christening': 14,
         'Baptism': 15,
         'Bar Mitzvah': 16,
         'Bas Mitzvah': 17,
         'Blessing': 18,
         'Burial': 19,
         'Cause Of Death': 20,
         'Census': 21,
         'Christening': 22,
         'Confirmation': 23,
         'Cremation': 24,
         'Degree': 25,
         'Education': 26,
         'Elected': 27,
         'Emigration': 28,
         'First Communion': 29,
         'Immigration': 30,
         'Graduation': 31,
         'Medical Information': 32,
         'Military Service': 33,
         'Naturalization': 34,
         'Nobility Title': 35,
         'Number of Marriages': 36,
         'Occupation': 37,
         'Ordination': 38,
         'Probate': 39,
         'Property': 40,
         'Religion': 41,
         'Residence': 42,
         'Retirement': 43,
         'Will': 44,
         'Marriage': 1,
         'Marriage Settlement': 2,
         'Marriage License': 3,
         'Marriage Contract': 4,
         'Marriage Banns': 5,
         'Engagement': 6,
         'Divorce': 7,
         'Divorce Filing': 8,
         'Annulment': 9,
         'Alternate Marriage': 10,
         'Stillbirth': 45}),
    'EventRoleType': (0, 1, {'Unknown': -1,
         'Custom': 0,
         'Primary': 1,
         'Clergy': 2,
         'Celebrant': 3,
         'Aide': 4,
         'Bride': 5,
         'Groom': 6,
         'Witness': 7,
         'Family': 8,
         'Informant': 9,
         'Godparent': 10,
         'Father': 11,
         'Mother': 12,
         'Parent': 13,
         'Child': 14,
         'Multiple birth': 15,
         'Friend': 16,
         'Neighbor': 17,
         'Officiator': 18}),
    'NameType': (0, 2, {'Unknown': -1, 'Custom': 0, 'Also Known As': 1, 'Birth Name': 2, 'Married Name': 3}),
    'NameOriginType': (0, 1, {'Unknown ': -1,
         'Custom': 0,
         '': 1,
         'Inherited': 2,
         'Given': 3,
         'Taken': 4,
         'Patronymic': 5,
         'Matronymic': 6,
         'Feudal': 7,
         'Pseudonym': 8,
         'Patrilineal': 9,
         'Matrilineal': 10,
         'Occupation': 11,
         'Location': 12}),
    'FamilyRelType': (4, 0, {'Married': 0, 'Unmarried': 1, 'Civil Union': 2, 'Unknown': 3, 'Custom': 4}),
    'ChildRefType': (7, 1, {'None': 0,
         'Birth': 1,
         'Adopted': 2,
         'Stepchild': 3,
         'Sponsored': 4,
         'Foster': 5,
         'Unknown': 6,
         'Custom': 7}),
    'AttributeType': (0, 3, {'Unknown': -1,
         'Custom': 0,
         'Caste': 1,
         'Description': 2,
         'Identification Number': 3,
         'National Origin': 4,
         'Number of Children': 5,
         'Social Security Number': 6,
         'Nickname': 7,
         'Cause': 8,
         'Agency': 9,
         'Age': 10,
         'Father Age': 11,
         'Mother Age': 12,
         'Witness': 13,
         'Time': 14,
         'Occupation': 15}),
    'SrcAttributeType': (0, -1, {'Unknown': -1, 'Custom': 0}),
    'NoteType': (0, 1, {'Unknown': -1,
         'Custom': 0,
         'General': 1,
         'Research': 2,
         'Analysis': 27,
         'Transcript': 3,
         'Source text': 21,
         'Citation': 22,
         'Report': 23,
         'Html code': 24,
         'To Do': 25,
         'Link': 26,
         'Person Note': 4,
         'Name Note': 20,
         'Attribute Note': 5,
         'Address Note': 6,
         'Association Note': 7,
         'LDS Note': 8,
         'Family Note': 9,
         'Event Note': 10,
         'Event Reference Note': 11,
         'Source Note': 12,
         'Source Reference Note': 13,
         'Place Note': 14,
         'Repository Note': 15,
         'Repository Reference Note': 16,
         'Media Note': 17,
         'Media Reference Note': 18,
         'Child Reference Note': 19}),
    'PlaceType': (0, -1, {'Unknown': -1,
         'Custom': 0,
         'Country': 1,
         'State': 2,
         'County': 3,
         'City': 4,
         'Parish': 5,
         'Locality': 6,
         'Street': 7,
         'Province': 8,
         'Region': 9,
         'Department': 10,
         'Neighborhood': 11,
         'District': 12,
         'Borough': 13,
         'Municipality': 14,
         'Town': 15,
         'Village': 16,
         'Hamlet': 17,
         'Farm': 18,
         'Building': 19,
         'Number': 20}),
    'RepositoryType': (0, 1, {'Unknown': -1,
         'Custom': 0,
         'Library': 1,
         'Cemetery': 2,
         'Church': 3,
         'Archive': 4,
         'Album': 5,
         'Web site': 6,
         'Bookstore': 7,
         'Collection': 8,
         'Safe': 9}),
    'SourceMediaType': (0, 2, {'Unknown': -1,
         'Custom': 0,
         'Audio': 1,
         'Book': 2,
         'Card': 3,
         'Electronic': 4,
         'Fiche': 5,
         'Film': 6,
         'Magazine': 7,
         'Manuscript': 8,
         'Map': 9,
         'Newspaper': 10,
         'Photo': 11,
         'Tombstone': 12,
         'Video': 13}),
    'UrlType': (0, -1, {'Unknown': -1, 'Custom': 0, 'E-mail': 1, 'Web Home': 2, 'Web Search': 3, 'FTP': 4}),
    'StyledTextTagType': (-1, -1, {'bold': 0,
         'italic': 1,
         'underline': 2,
         'fontface': 3,
         'fontsize': 4,
         'fontcolor': 5,
         'highlight': 6,
         'superscript': 7,
         'link': 8,
         'strikethrough': 9,
         'subscript': 10}),
}
_NAMES = {cls: {v: k for k, v in table.items()} for cls, (_, _, table) in TYPES.items()}

# Objets de premier niveau : classe Gramps -> point d'accès de l'API
CLASSES = {"Person": "people", "Family": "families", "Event": "events", "Place": "places",
           "Citation": "citations", "Source": "sources", "Repository": "repositories", "Media": "media",
           "Note": "notes", "Tag": "tags"}


def gtype(cls: str, name: str) -> dict:
    """Type Gramps brut depuis sa chaîne XML anglaise (ou une chaîne personnalisée)."""
    custom, _, table = TYPES[cls]
    if name in table and table[name] != custom:
        return {"_class": cls, "value": table[name], "string": ""}
    return {"_class": cls, "value": custom, "string": name}


def tname(t: Any) -> str:
    """Chaîne XML anglaise d'un type brut (ou chaîne déjà simplifiée)."""
    if isinstance(t, str):
        return t
    if not isinstance(t, dict):
        return ""
    cls = t.get("_class", "")
    custom = TYPES.get(cls, (0,))[0]
    if t.get("value") == custom or cls not in _NAMES:
        return t.get("string", "")
    return _NAMES[cls].get(t.get("value"), t.get("string", ""))


# ---------------------------------------------------------------------------- libellés (#273)
#
# Référentiel généré depuis les sources de Gramps 5.2, 6.0 et 6.1 (scripts/generer_types_gramps.py) : type standard
# (chaîne XML) -> valeur, version d'apparition, libellés anglais et français par version. Un type PERSONNALISÉ dont la
# chaîne est un libellé d'un type standard de sa classe (comparaison tolérante : casse, accents, espaces,
# apostrophes) est compris comme ce type standard, s'il n'en désigne qu'un seul ; l'objet Gramps n'est jamais modifié
# par la lecture. Écriture : type standard quand il existe (:func:`gtype_ecrit`). Détails : docs/gramps-web.md, « Types
# personnalisés et libellés français ».

REFERENTIEL: dict = json.loads((Path(__file__).parent.parent / "referentiels" / "types_gramps.json")
                               .read_text(encoding="utf-8"))
# Libellés français écrits par Genealogiste avant #273 pour des rôles qui ont un type standard (rôle du modèle sans
# précision : models.ROLE_LABELS) : toujours lus comme ce type standard.
ANCIENS_LIBELLES: dict[str, dict[str, str]] = {
    "EventRoleType": {"Père": "Father", "Mère": "Mother", "Enfant": "Child", "Ami": "Friend", "Voisin": "Neighbor",
                      "Plusieurs": "Multiple birth"},
}
_HORS_CORRESPONDANCE = {"Custom", ""}  # « Personnalisé » et le type vide ne désignent aucun type standard
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "‘": "'", "`": "'", "´": "'"})


def cle_libelle(s: str) -> str:
    """Forme de comparaison d'un libellé : sans casse, accents ni variation d'espaces ou d'apostrophes."""
    s = unicodedata.normalize("NFKD", (s or "").translate(_APOSTROPHES))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.casefold().split())


def _index_libelles() -> dict[str, dict[str, set[str]]]:
    out: dict[str, dict[str, set[str]]] = {}
    for cls, c in REFERENTIEL["classes"].items():
        idx = out.setdefault(cls, {})
        for xml, e in c["types"].items():
            if xml in _HORS_CORRESPONDANCE:
                continue
            for lib in {xml, *e["en"].values(), *e["fr"].values()}:
                if cle_libelle(lib):
                    idx.setdefault(cle_libelle(lib), set()).add(xml)
    for cls, table in ANCIENS_LIBELLES.items():
        for lib, xml in table.items():
            out[cls].setdefault(cle_libelle(lib), set()).add(xml)
    return out


LIBELLES = _index_libelles()


@functools.lru_cache(maxsize=8192)
def _candidats(cls: str, chaine: str) -> tuple[str, ...]:
    return tuple(sorted(LIBELLES.get(cls, {}).get(cle_libelle(chaine), ())))


def candidats(cls: str, chaine: str) -> list[str]:
    """Types standard de la classe dont ``chaine`` est un libellé (tolérant) ; plusieurs : ambigu."""
    return list(_candidats(cls, chaine))


def type_standard(cls: str, chaine: str) -> str | None:
    """Type standard (chaîne XML) que désigne sans ambiguïté la chaîne d'un type personnalisé, sinon None."""
    c = candidats(cls, chaine)
    return c[0] if len(c) == 1 else None


def est_personnalise(t: Any) -> bool:
    return isinstance(t, dict) and t.get("_class") in TYPES and t.get("value") == TYPES[t["_class"]][0]


def tcanon(t: Any, cls: str | None = None) -> str:
    """Type tel que le comprend le modèle : chaîne XML du type standard, y compris pour un type personnalisé dont la
    chaîne est un libellé non ambigu de ce type (« Baptême » -> « Baptism ») ; sinon la chaîne personnalisée."""
    name = tname(t)
    cls = t.get("_class") if isinstance(t, dict) else cls
    if not cls or not name or (isinstance(t, dict) and not est_personnalise(t)):
        return name
    if isinstance(t, str) and name in TYPES.get(cls, (0, 0, {}))[2]:
        return name
    return type_standard(cls, name) or name


def gtype_ecrit(cls: str, name: str) -> dict:
    """Type écrit par Genealogiste pour un objet nouveau ou dont le type change : standard quand il existe (libellé
    reconnu compris), personnalisé seulement sinon."""
    std = name if name in TYPES[cls][2] else type_standard(cls, name)
    return gtype(cls, std if std is not None else name)


# ---------------------------------------------------------------------------- gabarits (objets complets)

ID_PREFIX = {"Person": "I", "Family": "F", "Event": "E", "Place": "P", "Citation": "C", "Source": "S",
             "Repository": "R", "Media": "O", "Note": "N"}


def blank_date() -> dict:
    return {"_class": "Date", "format": None, "calendar": 0, "modifier": 0, "quality": 0,
            "dateval": [0, 0, 0, False], "text": "", "sortval": 0, "newyear": 0}


def _base(cls: str, handle: str, gramps_id: str | None = None) -> dict:
    d = {"_class": cls, "handle": handle, "change": 0, "private": False, "tag_list": []}
    if cls != "Tag":  # Gramps exige une chaîne
        d["gramps_id"] = gramps_id or f"{ID_PREFIX.get(cls, 'X')}{handle[:8]}"
    return d


def blank(cls: str, handle: str, gramps_id: str | None = None) -> dict:
    """Objet Gramps de premier niveau vide, complet (mêmes clés que ``object_to_dict``)."""
    d = _base(cls, handle, gramps_id)
    if cls == "Person":
        d.update(citation_list=[], note_list=[], media_list=[], event_ref_list=[], attribute_list=[],
                 address_list=[], urls=[], lds_ord_list=[], primary_name=blank_name(), family_list=[],
                 parent_family_list=[], alternate_names=[], person_ref_list=[], death_ref_index=-1,
                 birth_ref_index=-1, gender=2)
    elif cls == "Family":
        d.update(citation_list=[], note_list=[], media_list=[], event_ref_list=[], attribute_list=[],
                 lds_ord_list=[], father_handle=None, mother_handle=None, child_ref_list=[],
                 type=gtype("FamilyRelType", "Unknown"), complete=0)
    elif cls == "Event":
        d.update(citation_list=[], note_list=[], media_list=[], attribute_list=[], date=blank_date(), place="",
                 type=gtype("EventType", "Birth"), description="")
    elif cls == "Citation":
        d.update(media_list=[], note_list=[], date=blank_date(), source_handle=None, page="", confidence=2,
                 attribute_list=[])
    elif cls == "Source":
        d.update(media_list=[], note_list=[], attribute_list=[], title="", author="", pubinfo="", abbrev="",
                 reporef_list=[])
    elif cls == "Repository":
        d.update(note_list=[], address_list=[], urls=[], type=gtype("RepositoryType", "Archive"), name="")
    elif cls == "Place":
        d.update(citation_list=[], note_list=[], media_list=[], urls=[], long="", lat="", title="",
                 name={"_class": "PlaceName", "date": blank_date(), "value": "", "lang": ""}, alt_names=[],
                 placeref_list=[], place_type=gtype("PlaceType", "City"), code="", alt_loc=[])
    elif cls == "Note":
        d.update(text={"_class": "StyledText", "tags": [], "string": ""}, format=0,
                 type=gtype("NoteType", "General"))
    elif cls == "Media":
        d.update(citation_list=[], note_list=[], date=blank_date(), attribute_list=[], path="", mime="",
                 desc="", checksum="", thumb=None)
    elif cls == "Tag":
        del d["private"], d["tag_list"]
        d.update(name="", color="#000000000000", priority=0)
    else:
        raise ValueError(f"Classe Gramps inconnue : {cls}")
    return d


def blank_name() -> dict:
    return {"_class": "Name", "private": False, "surname_list": [], "citation_list": [], "note_list": [],
            "date": blank_date(), "first_name": "", "suffix": "", "title": "", "type": gtype("NameType", "Birth Name"),
            "group_as": "", "sort_as": 0, "display_as": 0, "call": "", "nick": "", "famnick": ""}


def surname(value: str) -> dict:
    return {"_class": "Surname", "surname": value, "prefix": "", "primary": True,
            "origintype": gtype("NameOriginType", ""), "connector": ""}


def attribute(typ: str, value: str, citations: list[str] | None = None, src: bool = False) -> dict:
    if src:
        return {"_class": "SrcAttribute", "private": False, "type": gtype("SrcAttributeType", typ), "value": value}
    return {"_class": "Attribute", "private": False, "type": gtype("AttributeType", typ), "value": value,
            "citation_list": list(citations or []), "note_list": []}


def event_ref(handle: str, role: str, attributes: list[dict] | None = None,
              citations: list[str] | None = None) -> dict:
    return {"_class": "EventRef", "private": False, "citation_list": list(citations or []), "note_list": [],
            "attribute_list": list(attributes or []), "ref": handle, "role": gtype("EventRoleType", role)}


# ---------------------------------------------------------------------------- dates
#
# Correspondance unique date GEDCOM 7 (modèle) <-> Date Gramps (#272), utilisée par le mapping Gramps Web, l'import
# et l'export Gramps XML. Table complète : docs/gramps-web.md, « Dates ». Ce que GEDCOM 7 n'exprime pas (calendriers
# persan, islamique, suédois ; double datation ; nouvel an ; qualité combinée à un qualificatif ; année ou mois
# inconnus) s'écrit avec les extensions de docs/gedcom-extensions.md, « Dates Gramps », relues à l'identique.

CALENDARS = {nom: i for i, nom in enumerate(CALENDRIERS)}
CAL_NAMES = {v: k for k, v in CALENDARS.items()}
MODIFIERS = {None: 0, "BEF": 1, "AFT": 2, "ABT": 3, "BET": 4, "FROMTO": 5, "FROM": 7, "TO": 8}
MOD_NAMES = {v: k for k, v in MODIFIERS.items()}
QUALITIES = {"EST": 1, "CAL": 2}
QUAL_NAMES = {v: k for k, v in QUALITIES.items()}
MOD_TEXTONLY = 6
MOD_COMPOSES = (4, 5)
CAL_NOUVEL_AN = (0, 1, 6)  # calendriers dont Gramps admet un nouvel an décalé (calendar_has_fixed_newyear)


def _val(d: dict) -> list:
    val = list(d.get("dateval") or [0, 0, 0, False])
    return val + [0, 0, 0, False] * ((8 - len(val)) // 4)


def _ny(ny: Any) -> Any:
    """Nouvel an comparable : code entier, ou [mois, jour]."""
    if isinstance(ny, (list, tuple)):
        return list(ny) if tuple(ny) != (0, 0) else 0
    return ny or 0


def valeur_tri(d: dict) -> int:
    """``Date.sortval`` comme Gramps (``_calc_sort_value``, ``_adjust_newyear``) : jour julien du premier point
    (année 0 -> 1, mois et jour 0 -> 1) dans le calendrier de la date, année diminuée d'un si le nouvel an tombe
    avant le mois et le jour ; 0 pour une date vide ou textuelle."""
    if d.get("modifier") == MOD_TEXTONLY:
        return 0
    jour, mois, an = _val(d)[:3]
    if an == mois == jour == 0:
        return 0
    sdn = SDN[d.get("calendar", 0)]
    c = coupure(d.get("newyear") or 0)
    if c and (mois, jour) >= c:
        an -= 1
    return sdn(an if an != 0 else 1, max(mois, 1), max(jour, 1))


def date_acceptee(d: dict) -> bool:
    """La date passe le contrôle de ``Date.set`` de Gramps (sinon DateError : Gramps en fait une date textuelle à
    l'import XML) : constantes connues, nouvel an admis par le calendrier, et chaque point retrouvé à l'identique
    après conversion par son numéro de jour (jour ou mois 0 admis pour 1, année 0 pour 1)."""
    mod, cal = d.get("modifier", 0), d.get("calendar", 0)
    if mod == MOD_TEXTONLY:
        return True
    if mod not in MOD_NAMES or d.get("quality", 0) not in (0, 1, 2) or cal not in CAL_NAMES:
        return False
    ny = _ny(d.get("newyear"))
    if ny and cal not in CAL_NOUVEL_AN:
        return False
    val = _val(d)
    delta = -1 if valeur_tri(d) != valeur_tri({**d, "newyear": 0}) else 0
    points = [(valeur_tri(d), val[:3])]
    if mod in MOD_COMPOSES:
        j, m, a = val[4:7]
        points.append((SDN[cal](a if a != 0 else 1, max(m, 1), max(j, 1)), val[4:7]))
    for sdn, (jour, mois, an) in points:
        ry, rm, rd = YMD[cal](sdn)
        for adj, orig in ((rd, jour), (rm, mois)):
            if adj != orig and not (orig == 0 and adj == 1):
                return False
        if ry - delta != an and not (an == 0 and ry - delta == 1):
            return False
    return True


def _ambigu(t: str) -> bool:
    """Le texte d'une date textuelle serait relu autrement (date vide, date analysable, espaces de bord) :
    il s'écrit alors entre parenthèses."""
    return (t == "" or t != t.strip() or analyser_gedcom(t) is not None
            or (t.startswith("(") and t.endswith(")") and _ambigu(t[1:-1])))


def texte_vers_gedcom(t: str) -> str:
    """Texte d'une date textuelle de Gramps -> date du modèle (entre parenthèses seulement si nécessaire)."""
    return f"({t})" if _ambigu(t) else t


def texte_seul(value: str) -> str | None:
    """Date du modèle écrite comme texte de Gramps entre parenthèses -> ce texte ; None sinon."""
    if value.startswith("(") and value.endswith(")") and _ambigu(value[1:-1]):
        return value[1:-1]
    return None


def _champs(g: GenDate) -> dict | None:
    """Date analysée -> champs Gramps (calendrier, modificateur, qualité, valeur, nouvel an), ou None si Gramps
    ne la représente pas (deux calendriers dans un intervalle, nouvel an dans un calendrier qui l'interdit)."""
    if g is None or g.start.calendar not in CALENDARS or (g.end and g.end.calendar != g.start.calendar):
        return None
    cal, q = CALENDARS[g.start.calendar], g.qualifier
    if g.newyear and cal not in CAL_NOUVEL_AN:
        return None

    def pt(p) -> list:
        return [p.day or 0, p.month or 0, p.year, p.dual]
    out = {"calendar": cal, "modifier": MODIFIERS[q] if q not in QUALITIES else 0,
           "quality": QUALITIES.get(g.quality or (q if q in QUALITIES else None), 0),
           "dateval": pt(g.start) + (pt(g.end) if q in ("BET", "FROMTO") else []),
           "newyear": list(g.newyear) if isinstance(g.newyear, tuple) else g.newyear}
    if out["dateval"][3] and cal != 1:  # Date.set : une date à double datation passe en julien
        out["calendar"] = 1
    return out


def gramps_vers_gedcom(d: dict) -> str | None:
    """Champs d'une date Gramps (non textuelle) -> date du modèle, forme canonique ; None si un champ est hors des
    valeurs de Gramps."""
    cal, mod, qual = CAL_NAMES.get(d.get("calendar", 0)), d.get("modifier", 0), d.get("quality", 0)
    if cal is None or mod not in MOD_NAMES or qual not in (0, 1, 2):
        return None
    val = _val(d)
    mois = MONTHS[cal]

    def pt(jour, m, an, slash) -> DatePoint:
        if not (0 <= m <= len(mois) and 0 <= jour <= 31):
            raise ValueError
        return DatePoint(cal, an, m or None, jour or None, bool(slash) and bool(an))
    try:
        start = pt(*val[:4])
        end = pt(*val[4:8]) if mod in MOD_COMPOSES else None
    except ValueError:
        return None
    q, quality = MOD_NAMES[mod], QUAL_NAMES.get(qual)
    if q is None and quality:
        q, quality = quality, None
    ny = d.get("newyear") or 0
    ny = tuple(ny) if isinstance(ny, (list, tuple)) else ny
    return GenDate("", q, start, end, quality=quality, newyear=ny if coupure(ny) else 0).gedcom(7)


def date_to_gramps(value: str) -> dict:
    """Date du modèle (GEDCOM 7 et extensions) -> Date Gramps. ``text`` ne garde la chaîne que si elle n'est pas la
    forme canonique des champs (orthographe d'origine, phrase) ; une date que Gramps refuserait devient textuelle."""
    d = blank_date()
    if not value:
        return d
    texte = texte_seul(value)
    if texte is not None:
        d.update(modifier=MOD_TEXTONLY, text=texte)
        return d
    champs = _champs(analyser_gedcom(value))
    vide = champs is not None and not any(_val(champs)[:3]) and not any(_val(champs)[4:7])
    if champs is None or not (vide or date_acceptee(champs)):
        d.update(modifier=MOD_TEXTONLY, text=value)
        return d
    d.update(champs)
    d["sortval"] = valeur_tri(d)
    d["text"] = "" if gramps_vers_gedcom(d) == value else value
    return d


def _memes_champs(a: dict, b: dict) -> bool:
    return (all(a.get(k, 0) == b.get(k, 0) for k in ("calendar", "modifier", "quality"))
            and _val(a)[:8 if a.get("modifier") in MOD_COMPOSES else 4]
            == _val(b)[:8 if b.get("modifier") in MOD_COMPOSES else 4]
            and _ny(a.get("newyear")) == _ny(b.get("newyear")))


def date_from_gramps(d: dict | None) -> str:
    """Date Gramps -> date du modèle : texte gardé tel quel s'il correspond encore exactement aux champs, sinon
    forme canonique (extensions comprises) ; date textuelle : son texte, entre parenthèses s'il ressemble à une
    date."""
    if not d:
        return ""
    text = d.get("text") or ""
    mod = d.get("modifier", 0)
    if mod == MOD_TEXTONLY:
        return texte_vers_gedcom(text)
    val = _val(d)
    if not any(val[:3]) and not any(val[4:7]) and not (d.get("calendar") or mod or d.get("quality")
                                                       or _ny(d.get("newyear"))):
        return text if text and not parse_gedcom_date(text) and texte_seul(text) is None else ""
    if text:
        champs = _champs(analyser_gedcom(text))
        if champs is not None and _memes_champs(champs, d):
            return text
    s = gramps_vers_gedcom(d)
    return text if s is None else s


def date_reprise(d: dict) -> bool:
    """La date Gramps revient à l'identique après passage par le modèle, pour tout ce que le Gramps XML porte
    (calendrier, modificateur, qualité, valeur et double datation, nouvel an ; texte d'une date textuelle)."""
    r = date_to_gramps(date_from_gramps(d))
    if d.get("modifier") == MOD_TEXTONLY or r.get("modifier") == MOD_TEXTONLY:
        return r.get("modifier") == d.get("modifier") and (r.get("text") or "") == (d.get("text") or "")
    return _memes_champs(r, d)


def affichage_gramps(d: dict) -> str:
    """Affichage de Gramps (langue anglaise, format ISO par défaut : ``DateDisplay.display_formatted``)."""
    mod = d.get("modifier", 0)
    if mod == MOD_TEXTONLY:
        return d.get("text") or ""
    val = _val(d)
    if not any(val[:3]):
        return ""

    def iso(jour, mois, an, slash) -> str:
        y = abs(an)
        if slash:
            y = f"{y - 1}/{y % (1000 if (y - 1) % 100 == 99 else 100 if (y - 1) % 10 == 9 else 10)}"
        s = str(y) if not (jour or mois) else f"{y}-{mois:02d}" if not jour else f"{y}-{mois:02d}-{jour:02d}"
        return f"{s} B.C.E." if an < 0 else s
    qual = ("", "estimated ", "calculated ")[d.get("quality", 0)]
    extras = [x for x in (("", "Julian", "Hebrew", "French Republican", "Persian", "Islamic", "Swedish")
                          [d.get("calendar", 0)], nouvel_an_texte(_ny(d.get("newyear")))) if x]
    scal = f" ({', '.join(extras)})" if extras else ""
    if mod == 5:
        return f"{qual}from {iso(*val[:4])} to {iso(*val[4:8])}{scal}"
    if mod == 4:
        return f"{qual}between {iso(*val[:4])} and {iso(*val[4:8])}{scal}"
    prefixe = {1: "before ", 2: "after ", 3: "about ", 7: "from ", 8: "to "}.get(mod, "")
    return f"{qual}{prefixe}{iso(*val[:4])}{scal}"


# ---------------------------------------------------------------------------- format simplifié -> brut

_TYPE_KEYS = {"type", "place_type", "media_type", "frel", "mrel"}
_SUB = {"date": "Date", "media_list": "MediaRef", "child_ref_list": "ChildRef", "event_ref_list": "EventRef",
        "address_list": "Address", "urls": "Url", "lds_ord_list": "LdsOrd", "person_ref_list": "PersonRef",
        "surname_list": "Surname", "text": "StyledText", "alt_loc": "Location", "reporef_list": "RepoRef",
        "placeref_list": "PlaceRef", "tags": "StyledTextTag", "alt_names": "PlaceName",
        "primary_name": "Name", "alternate_names": "Name"}
_SRC_ATTR = {"Source", "Citation"}


def _type_class(cls: str, key: str) -> str:
    if cls == "Family":
        return "FamilyRelType"
    if cls == "RepoRef":
        return "SourceMediaType"
    if key in ("frel", "mrel"):
        return "ChildRefType"
    if key == "place_type":
        return "PlaceType"
    if key == "role":
        return "EventRoleType"
    if key == "origintype":
        return "NameOriginType"
    return f"{cls}Type"


def _sub_class(cls: str, key: str) -> str | None:
    if key == "name" and cls == "Place":
        return "PlaceName"
    if key == "name" and cls == "StyledTextTag":
        return "StyledTextTagType"
    if key == "attribute_list":
        return "SrcAttribute" if cls in _SRC_ATTR else "Attribute"
    return _SUB.get(key)


def to_raw(obj: dict, cls: str | None = None) -> dict:
    """Lecture simplifiée de l'API -> format brut (transactions). Idempotent sur un objet déjà brut."""
    cls = cls or obj.get("_class")
    if not cls:
        raise ValueError("classe Gramps non précisée")
    out: dict[str, Any] = {"_class": cls}
    for k, v in obj.items():
        if k in ("_class", "extended", "profile", "backlinks", "formatted"):
            continue
        if cls == "Date" and k == "year":
            continue
        if (k in _TYPE_KEYS or k in ("role", "origintype") or (k == "name" and cls == "StyledTextTag")) \
                and cls not in ("Tag",):
            if isinstance(v, str):
                tc = _type_class(cls, k) if not (k == "name" and cls == "StyledTextTag") else "StyledTextTagType"
                out[k] = gtype(tc, v) if tc in TYPES else v
            else:
                out[k] = copy.deepcopy(v)
        elif k in ("rect", "mother_handle", "father_handle", "famc") and not v:
            out[k] = None
        elif isinstance(v, dict):
            sub = _sub_class(cls, k)
            out[k] = to_raw(v, sub) if sub else copy.deepcopy(v)
        elif isinstance(v, list):
            sub = _sub_class(cls, k)
            out[k] = [to_raw(x, sub) if isinstance(x, dict) and sub else copy.deepcopy(x) for x in v]
        else:
            out[k] = v
    if cls == "Date" and out.get("dateval") is not None:
        out["dateval"] = list(out["dateval"])
    return out
