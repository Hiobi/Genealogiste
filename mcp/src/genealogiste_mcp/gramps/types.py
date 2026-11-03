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
from typing import Any

from ..normalize.dates import GenDate, parse_gedcom_date

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

CALENDARS = {"GREGORIAN": 0, "JULIAN": 1, "FRENCH_R": 3}
CAL_NAMES = {v: k for k, v in CALENDARS.items()}
MODIFIERS = {None: 0, "BEF": 1, "AFT": 2, "ABT": 3, "BET": 4, "FROMTO": 5, "FROM": 7, "TO": 8}
MOD_NAMES = {v: k for k, v in MODIFIERS.items()}
QUALITIES = {"EST": 1, "CAL": 2}
MOD_TEXTONLY = 6


def _point(p) -> list:
    return [p.day or 0, p.month or 0, p.year, False]


def date_to_gramps(value: str) -> dict:
    """Date GEDCOM 7 -> Date Gramps. La chaîne GEDCOM est conservée dans ``text`` pour l'aller-retour."""
    d = blank_date()
    if not value:
        return d
    g = parse_gedcom_date(value)
    if not g or g.start.calendar not in CALENDARS or (g.end and g.end.calendar != g.start.calendar):
        d.update(modifier=MOD_TEXTONLY, text=value)
        return d
    q = g.qualifier
    d["calendar"] = CALENDARS[g.start.calendar]
    d["modifier"] = MODIFIERS.get(q, 0) if q not in QUALITIES else 0
    d["quality"] = QUALITIES.get(q, 0)
    d["dateval"] = _point(g.start) + (_point(g.end) if q in ("BET", "FROMTO") and g.end else [])
    d["text"] = value
    d["sortval"] = g.start.bounds()[0]
    return d


def _same(g: GenDate, d: dict) -> bool:
    ref = date_to_gramps(g.original)
    return all(ref[k] == d.get(k) for k in ("calendar", "modifier", "quality", "dateval"))


def date_from_gramps(d: dict | None) -> str:
    """Date Gramps -> date GEDCOM 7 (texte conservé tel quel s'il correspond encore à la date)."""
    if not d:
        return ""
    text = d.get("text") or ""
    mod = d.get("modifier", 0)
    val = list(d.get("dateval") or [0, 0, 0, False])
    if mod == MOD_TEXTONLY:
        return text
    if not any(val[:3]):
        return text if text and not parse_gedcom_date(text) else ""
    if text:
        g = parse_gedcom_date(text)
        if g and _same(g, d):
            return text
    cal = CAL_NAMES.get(d.get("calendar", 0))
    if cal is None:  # calendrier non géré (hébreu, persan…) : texte de Gramps
        return text
    from ..normalize.dates import DatePoint

    def pt(day, month, year):
        return DatePoint(cal, year, month or None, day or None)

    try:
        start = pt(*val[:3])
        start.bounds()
        q = MOD_NAMES.get(mod)
        if d.get("quality") in (1, 2) and q is None:
            q = "EST" if d["quality"] == 1 else "CAL"
        end = pt(*val[4:7]) if q in ("BET", "FROMTO") and len(val) >= 7 else None
        return GenDate("", q, start, end).gedcom(7)
    except (ValueError, IndexError):
        return text


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
