"""Export Gramps XML 1.7.1 / 1.7.2 (« .gramps », brut ou gzip) et paquet « .gpkg » (XML + médias).

Les objets viennent du module de correspondance unique (:mod:`genealogiste_mcp.gramps.mapping`), le même
que celui du mode direct (API Gramps Web) : ce fichier ne fait que sérialiser en XML. Rien du travail de
recherche ne s'y perd (contrairement à l'import GEDCOM de Gramps, qui ignore les extensions `_…`, les
ASSO d'événement et les sous-structures de OCCU/RESI) : URL et type des sources, classification des
citations, témoins et parrains, statut de preuve (notes et étiquettes « Genealogiste:auto », ou « Sosa:auto » avec
GENEALOGISTE_MARQUEURS=sosa), lieux.

Écriture complète (#268) : tout ce que contient un objet Gramps JSON est écrit, y compris ce que Genealogiste ne
modélise pas (étiquettes, ``priv`` à chaque niveau, noms alternatifs et références datées des lieux, adresses,
URL, texte stylé, attributs, rectangles…), selon les tables déclaratives ``SPEC_*`` ci-dessous : une entrée
:class:`Champ` = un champ JSON <-> un attribut ou un élément XML, dans l'ordre du DTD. Un lecteur symétrique
(import, #269) parcourt les mêmes tables. Seuls restent hors du fichier, comme chez Gramps : ``Date.text`` (sauf
date texte) et ``Date.sortval`` (recalculés), ``birth_ref_index`` / ``death_ref_index`` (déduits de l'ordre des
références d'événement, voir :func:`_refs_evenements`).

Versions (étiquette ``xmlns`` et DOCTYPE) : 1.7.1 par défaut, seule lue par Gramps 5.2, 6.0 et 6.1 ; 1.7.2 pour
Gramps ≥ 6.0 (refusée par 5.2). Le contenu est le même : comme Gramps 5.2 lui-même sous l'étiquette 1.7.1, il
peut contenir ce que le schéma 1.7.1 strict ne décrit pas mais que 5.2 lit (citations des références
d'événement, genre X, modificateurs ``from``/``to``). Espace de noms : toujours ``http://gramps-project.org/xml/<v>/``
(« NS URI » de Gramps 6.1, jamais l'URL https du site). 1.8.0 (objets ADN) n'est pas publié : refusé.
"""

from __future__ import annotations

import gzip
import io
import re
import tarfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from ..chemins import CheminAmbigu, CheminRefuse, localiser
from ..gramps.mapping import A_FICHIER, GrampsDb, tree_to_gramps_stats
from ..gramps.types import TYPES, gtype, tname
from ..models import Tree
from .chemins_medias import ABSOLU_WINDOWS, nom_fichier, sensible

# ============================================================================ versions

# version XML -> version de Gramps déclarée dans <created version> (obligatoire : Gramps refuse un fichier sans)
VERSIONS_XML = {"1.7.1": "5.2.0", "1.7.2": "6.0.0"}
VERSION_XML_DEFAUT = "1.7.1"
NS_URI = "http://gramps-project.org/"  # URL_NS de Gramps 6.1 : identifiant d'espace de noms, pas une adresse


def verifier_version_xml(version: str) -> str:
    """Version XML cible ; ValueError si inconnue (1.8.0 : pas encore publiée par Gramps)."""
    if version in VERSIONS_XML:
        return version
    if version == "1.8.0":
        raise ValueError("version_xml 1.8.0 (objets ADN, branche master de Gramps) : pas encore publié par Gramps. "
                         "Valeurs possibles : 1.7.1 (Gramps 5.2, 6.0, 6.1) ou 1.7.2 (Gramps 6.0, 6.1).")
    raise ValueError(f"version_xml inconnue : {version!r}. Valeurs possibles : "
                     "1.7.1 (Gramps 5.2, 6.0, 6.1) ou 1.7.2 (Gramps 6.0, 6.1).")


# ============================================================================ échappement

# Caractères interdits en XML 1.0, retirés comme le fait Gramps (strip_dict de exportxml.py)
_INTERDITS = dict.fromkeys([*range(9), 11, 12, *range(14, 32)])
_TEXTE = {**_INTERDITS, ord("&"): "&amp;", ord("<"): "&lt;", ord(">"): "&gt;", ord("\r"): "&#13;"}
_ATTR = {**_TEXTE, ord('"'): "&quot;", ord("\n"): "&#10;", ord("\t"): "&#9;"}


def _txt(v: Any) -> str:
    """Contenu d'élément : retour chariot gardé (&#13;), aucun espace retiré (aller-retour exact)."""
    return str(v).translate(_TEXTE)


def _att(v: Any) -> str:
    """Valeur d'attribut entre guillemets doubles (sauts de ligne et tabulations protégés)."""
    return str(v).translate(_ATTR)


# ============================================================================ conversions champ JSON <-> XML

@dataclass(frozen=True)
class Conv:
    """Conversion d'une valeur JSON : ``ecrire`` donne la chaîne XML (None : omise), ``lire`` l'inverse."""
    ecrire: Callable[[Any], str | None]
    lire: Callable[[str], Any]


def _type_conv(cls: str, toujours: bool = False, sauf_defaut: bool = False) -> Conv:
    """Type Gramps (chaîne XML anglaise ou personnalisée). ``sauf_defaut`` : omis s'il vaut le défaut du type
    (filiation « Birth »), ``toujours`` : écrit même vide."""
    defaut = TYPES[cls][1]

    def ecrire(v):
        if sauf_defaut and isinstance(v, dict) and v.get("value") == defaut:
            return None
        s = tname(v)
        return s if s or toujours else None
    return Conv(ecrire, lambda s: gtype(cls, s))


def _table(table: dict[int, str], omis: int | None = None) -> Conv:
    inverse = {v: k for k, v in table.items()}
    return Conv(lambda v: None if v == omis else table.get(v, table.get(omis, "")), lambda s: inverse.get(s, omis))


STR = Conv(lambda v: str(v) if v else None, str)                    # omis si vide
STR_TOUJOURS = Conv(lambda v: "" if v is None else str(v), str)    # écrit même vide
PRIV = Conv(lambda v: "1" if v else None, lambda s: s == "1")
INT = Conv(lambda v: str(int(v or 0)), int)
INT_NON_NUL = Conv(lambda v: str(int(v)) if v else None, int)
HANDLE = Conv(lambda v: "_" + v if v else None, lambda s: s[1:] if s.startswith("_") else s)
PRIM = Conv(lambda v: None if v in (True, None) else "0", lambda s: s != "0")
ACTIF = Conv(lambda v: "1" if v else "0", lambda s: s == "1")
VALEUR_STYLE = Conv(lambda v: str(v) if v else None, str)  # valeur de style (taille : entier) ; omise si vide
GENRE = Conv(lambda v: {0: "F", 1: "M", 3: "X"}.get(v, "U"), lambda s: {"F": 0, "M": 1, "X": 3}.get(s, 2))
LDS_TYPE = _table({0: "baptism", 1: "endowment", 2: "sealed_to_parents", 3: "sealed_to_spouse", 4: "confirmation",
                   5: "initiatory"})
LDS_STATUT = _table({0: "", 1: "BIC", 2: "Canceled", 3: "Child", 4: "Cleared", 5: "Completed", 6: "DNS",
                     7: "Infant", 8: "Pre-1970", 9: "Qualified", 10: "DNS/CAN", 11: "Stillborn", 12: "Submitted",
                     13: "Uncleared"}, 0)


# ============================================================================ tables de correspondance

@dataclass(frozen=True)
class Champ:
    """Un champ JSON de Gramps et sa place en XML. ``genre`` :

    - ``attr`` : attribut ``xml`` de l'élément ;
    - ``texte`` : élément enfant ``<xml>valeur</xml>`` (omis si vide, sauf ``toujours``) ;
    - ``val`` : élément enfant vide ``<xml {attr}="valeur"/>`` (``<temple val>``, ``<status val>``, ``<rel type>``) ;
    - ``date`` : date enfant (``dateval``, ``daterange``, ``datespan`` ou ``datestr``, voir :func:`date_xml`) ;
    - ``ref`` / ``refs`` : élément(s) ``<xml hlink="_handle"/>`` ;
    - ``objet`` / ``liste`` : sous-objet(s) selon ``spec`` (``cle`` vide : l'objet lui-même, ex. ``<file>``) ;
    - ``fonction`` : forme particulière écrite par ``fonction(objet, base)`` (coordonnées, rectangle, plages).

    ``extra`` : attributs fixes ajoutés à l'élément (``alt="1"`` des noms alternatifs : un lecteur s'en sert
    pour choisir la clé). ``cle`` peut être pointée (``text.string``)."""
    genre: str
    xml: str
    cle: str = ""
    conv: Conv = STR
    spec: Spec | None = None
    toujours: bool = False
    attr: str = "val"
    extra: str = ""
    fonction: Callable[[dict, GrampsDb | None], str] | None = None
    ordonner: Callable[[dict, list, GrampsDb | None], list] | None = None


@dataclass(frozen=True)
class Spec:
    """Élément XML d'un objet JSON : attributs puis enfants dans l'ordre du DTD ; ``texte`` : clé écrite comme
    contenu (``<surname>``) ; ``vide`` : objet ignoré (lieu alternatif sans aucun champ)."""
    element: str
    attrs: tuple[Champ, ...] = ()
    enfants: tuple[Champ, ...] = ()
    texte: str | None = None
    vide: Callable[[dict], bool] | None = None


def A(xml: str, cle: str, conv: Conv = STR) -> Champ:  # noqa: N802
    return Champ("attr", xml, cle, conv)


def T(xml: str, cle: str | None = None, conv: Conv = STR, toujours: bool = False) -> Champ:  # noqa: N802
    return Champ("texte", xml, xml if cle is None else cle, conv, toujours=toujours)


def R(xml: str, cle: str) -> Champ:  # noqa: N802
    return Champ("refs", xml, cle, HANDLE)


def L(xml: str, cle: str, spec: Spec, **kw) -> Champ:  # noqa: N802
    return Champ("liste", xml, cle, spec=spec, **kw)


DATE = Champ("date", "date", "date")
NOTES, CITATIONS, TAGS = R("noteref", "note_list"), R("citationref", "citation_list"), R("tagref", "tag_list")
HLINK = A("hlink", "ref", HANDLE)
PRIVE = A("priv", "private", PRIV)


def _region(o: dict, _db=None) -> str:
    """Rectangle d'une référence de média, omis s'il couvre toute l'image ou rien (comme Gramps)."""
    rect = o.get("rect")
    if not rect:
        return ""
    x1, y1, x2, y2 = (0 if rect[0] is None else rect[0], 0 if rect[1] is None else rect[1],
                      100 if rect[2] is None else rect[2], 100 if rect[3] is None else rect[3])
    if x1 == y1 == x2 == y2 == 0 or (x1 == y1 == 0 and x2 == y2 == 100):
        return ""
    return f'<region corner1_x="{int(x1)}" corner1_y="{int(y1)}" corner2_x="{int(x2)}" corner2_y="{int(y2)}"/>'


def _coord(o: dict, _db=None) -> str:
    lon, lat = o.get("long") or "", o.get("lat") or ""
    return f'<coord long="{_att(lon)}" lat="{_att(lat)}"/>' if lon or lat else ""


def _plages(o: dict, _db=None) -> str:
    return "".join(f'<range start="{int(a)}" end="{int(b)}"/>' for a, b in o.get("ranges") or [])


SPEC_ATTRIBUT = Spec("attribute", (PRIVE, A("type", "type", _type_conv("AttributeType", True)),
                                   A("value", "value", STR_TOUJOURS)), (CITATIONS, NOTES))
SPEC_ATTRIBUT_SOURCE = Spec("srcattribute", (PRIVE, A("type", "type", _type_conv("SrcAttributeType", True)),
                                             A("value", "value", STR_TOUJOURS)))
SPEC_URL = Spec("url", (PRIVE, A("href", "path", STR_TOUJOURS), A("type", "type", _type_conv("UrlType")),
                        A("description", "desc")))
SPEC_ADRESSE = Spec("address", (PRIVE,), (DATE, T("street"), T("locality"), T("city"), T("county"), T("state"),
                                         T("country"), T("postal"), T("phone"), NOTES, CITATIONS))
SPEC_OBJREF = Spec("objref", (HLINK, PRIVE), (Champ("fonction", "region", fonction=_region),
                                              L("attribute", "attribute_list", SPEC_ATTRIBUT), CITATIONS, NOTES))
SPEC_EVENTREF = Spec("eventref", (HLINK, PRIVE, A("role", "role", _type_conv("EventRoleType"))),
                     (L("attribute", "attribute_list", SPEC_ATTRIBUT), NOTES, CITATIONS))
SPEC_CHILDREF = Spec("childref", (HLINK, PRIVE, A("mrel", "mrel", _type_conv("ChildRefType", True, True)),
                                  A("frel", "frel", _type_conv("ChildRefType", True, True))), (CITATIONS, NOTES))
SPEC_PERSONREF = Spec("personref", (HLINK, PRIVE, A("rel", "rel", STR_TOUJOURS)), (CITATIONS, NOTES))
SPEC_PATRONYME = Spec("surname", (A("prefix", "prefix"), A("prim", "primary", PRIM), A("connector", "connector"),
                                  A("derivation", "origintype", _type_conv("NameOriginType"))), texte="surname")
SPEC_NOM = Spec("name", (A("type", "type", _type_conv("NameType")), PRIVE, A("sort", "sort_as", INT_NON_NUL),
                         A("display", "display_as", INT_NON_NUL)),
                (T("first", "first_name"), T("call"), L("surname", "surname_list", SPEC_PATRONYME), T("suffix"),
                 T("title"), T("nick"), T("familynick", "famnick"), T("group", "group_as"), DATE, NOTES, CITATIONS))
SPEC_LDS = Spec("lds_ord", (A("type", "type", LDS_TYPE), PRIVE),
                (DATE, Champ("val", "temple", "temple"), Champ("refs", "place", "place", HANDLE),
                 Champ("val", "status", "status", LDS_STATUT), Champ("refs", "sealed_to", "famc", HANDLE),
                 NOTES, CITATIONS))
SPEC_NOM_LIEU = Spec("pname", (A("value", "value", STR_TOUJOURS), A("lang", "lang")), (DATE,))
SPEC_PLACEREF = Spec("placeref", (HLINK,), (DATE,))
_LOCALISATION = ("street", "locality", "city", "parish", "county", "state", "country", "postal", "phone")
SPEC_LOCALISATION = Spec("location", tuple(A(k, k) for k in _LOCALISATION),
                         vide=lambda o: not any(o.get(k) for k in _LOCALISATION))
SPEC_REPOREF = Spec("reporef", (HLINK, PRIVE, A("callno", "call_number"),
                                A("medium", "media_type", _type_conv("SourceMediaType"))), (NOTES,))
SPEC_STYLE = Spec("style", (A("name", "name", _type_conv("StyledTextTagType", True)), A("value", "value", VALEUR_STYLE)),
                  (Champ("fonction", "range", fonction=_plages),))
SPEC_FICHIER = Spec("file", (A("src", "path", STR_TOUJOURS), A("mime", "mime", STR_TOUJOURS), A("checksum", "checksum"),
                             A("description", "desc", STR_TOUJOURS)))  # description #REQUIRED dans le DTD

PRIMAIRE = (A("handle", "handle", HANDLE), A("change", "change", INT), A("id", "gramps_id", STR_TOUJOURS), PRIVE)
OBJREFS = L("objref", "media_list", SPEC_OBJREF)
ATTRIBUTS = L("attribute", "attribute_list", SPEC_ATTRIBUT)


def _refs_evenements(p: dict, refs: list, db: GrampsDb | None) -> list:
    """Gramps ne stocke pas birth_ref_index / death_ref_index en XML : à l'import, la première référence d'un
    événement Birth (Death) de rôle Primary devient la naissance (le décès) retenue. L'ordre est conservé tant que
    Gramps retrouve ainsi les mêmes ; sinon la référence retenue passe en tête (seule perte : l'ordre)."""
    if db is None:
        return refs
    devant = []
    for cle, typ in (("birth_ref_index", 12), ("death_ref_index", 13)):
        i = p.get(cle, -1)
        if not 0 <= i < len(refs):
            continue

        def admissible(r, typ=typ):
            ev = db.get("Event", r.get("ref"))
            return bool(ev) and (ev.get("type") or {}).get("value") == typ and (r.get("role") or {}).get("value") == 1
        if not admissible(refs[i]):
            continue  # ni retrouvable par Gramps ni réparable par l'ordre
        if next(j for j, r in enumerate(refs) if admissible(r)) != i:
            devant.append(i)
    return [refs[i] for i in devant] + [r for i, r in enumerate(refs) if i not in devant]


SPEC_ETIQUETTE = Spec("tag", (A("handle", "handle", HANDLE), A("change", "change", INT), A("name", "name", STR_TOUJOURS),
                              A("color", "color", STR_TOUJOURS), A("priority", "priority", INT)))
SPEC_EVENEMENT = Spec("event", PRIMAIRE, (
    T("type", "type", _type_conv("EventType", True), toujours=True), DATE, Champ("refs", "place", "place", HANDLE),
    T("description"), ATTRIBUTS, NOTES, CITATIONS, OBJREFS, TAGS))
SPEC_PERSONNE = Spec("person", PRIMAIRE, (
    T("gender", "gender", GENRE, toujours=True), Champ("objet", "name", "primary_name", spec=SPEC_NOM),
    L("name", "alternate_names", SPEC_NOM, extra=' alt="1"'),
    L("eventref", "event_ref_list", SPEC_EVENTREF, ordonner=_refs_evenements),
    L("lds_ord", "lds_ord_list", SPEC_LDS), OBJREFS, L("address", "address_list", SPEC_ADRESSE), ATTRIBUTS,
    L("url", "urls", SPEC_URL), R("childof", "parent_family_list"), R("parentin", "family_list"),
    L("personref", "person_ref_list", SPEC_PERSONREF), NOTES, CITATIONS, TAGS))
SPEC_FAMILLE = Spec("family", PRIMAIRE, (
    Champ("val", "rel", "type", _type_conv("FamilyRelType"), attr="type"),
    Champ("refs", "father", "father_handle", HANDLE), Champ("refs", "mother", "mother_handle", HANDLE),
    L("eventref", "event_ref_list", SPEC_EVENTREF), L("lds_ord", "lds_ord_list", SPEC_LDS), OBJREFS,
    L("childref", "child_ref_list", SPEC_CHILDREF), ATTRIBUTS, NOTES, CITATIONS, TAGS))
SPEC_CITATION = Spec("citation", PRIMAIRE, (
    DATE, T("page"), T("confidence", "confidence", INT, toujours=True), NOTES, OBJREFS,
    L("srcattribute", "attribute_list", SPEC_ATTRIBUT_SOURCE), Champ("refs", "sourceref", "source_handle", HANDLE),
    TAGS))
SPEC_SOURCE = Spec("source", PRIMAIRE, (
    T("stitle", "title", STR_TOUJOURS, toujours=True), T("sauthor", "author"), T("spubinfo", "pubinfo"),
    T("sabbrev", "abbrev"), NOTES, OBJREFS, L("srcattribute", "attribute_list", SPEC_ATTRIBUT_SOURCE),
    L("reporef", "reporef_list", SPEC_REPOREF), TAGS))
SPEC_LIEU = Spec("placeobj", (*PRIMAIRE, A("type", "place_type", _type_conv("PlaceType", True))), (
    T("ptitle", "title"), T("code"), Champ("objet", "pname", "name", spec=SPEC_NOM_LIEU),
    L("pname", "alt_names", SPEC_NOM_LIEU), Champ("fonction", "coord", fonction=_coord),
    L("placeref", "placeref_list", SPEC_PLACEREF), L("location", "alt_loc", SPEC_LOCALISATION), OBJREFS,
    L("url", "urls", SPEC_URL), NOTES, CITATIONS, TAGS))
SPEC_MEDIA = Spec("object", PRIMAIRE, (Champ("objet", "file", "", spec=SPEC_FICHIER), ATTRIBUTS, NOTES, DATE,
                                       CITATIONS, TAGS))
SPEC_DEPOT = Spec("repository", PRIMAIRE, (
    T("rname", "name", STR_TOUJOURS, toujours=True), T("type", "type", _type_conv("RepositoryType", True), toujours=True),
    L("address", "address_list", SPEC_ADRESSE), L("url", "urls", SPEC_URL), NOTES, TAGS))
SPEC_NOTE = Spec("note", (*PRIMAIRE, A("type", "type", _type_conv("NoteType", True)), A("format", "format", INT_NON_NUL)),
                 (T("text", "text.string", STR_TOUJOURS, toujours=True), L("style", "text.tags", SPEC_STYLE), TAGS))

# Sections de <database>, dans l'ordre du DTD : (élément de section, classe Gramps, table de l'objet)
SECTIONS = (("tags", "Tag", SPEC_ETIQUETTE), ("events", "Event", SPEC_EVENEMENT), ("people", "Person", SPEC_PERSONNE),
            ("families", "Family", SPEC_FAMILLE), ("citations", "Citation", SPEC_CITATION),
            ("sources", "Source", SPEC_SOURCE), ("places", "Place", SPEC_LIEU), ("objects", "Media", SPEC_MEDIA),
            ("repositories", "Repository", SPEC_DEPOT), ("notes", "Note", SPEC_NOTE))


# ============================================================================ dates

CALENDRIERS = {1: "Julian", 2: "Hebrew", 3: "French Republican", 4: "Persian", 5: "Islamic", 6: "Swedish"}
MODIFICATEURS = {1: "before", 2: "after", 3: "about", 7: "from", 8: "to"}
QUALITES = {1: "estimated", 2: "calculated"}
NOUVEL_AN = {1: "Mar1", 2: "Mar25", 3: "Sep1"}


def _iso(d: int, m: int, y: int) -> str:
    """Date ISO de Gramps (get_iso_date) : année 0 -> ????, mois inconnu avec jour -> -??, vide si rien."""
    s = ("????" if not y else f"{y:04d}") + (f"-{m:02d}" if m else ("-??" if d else "")) + (f"-{d:02d}" if d else "")
    return "" if not s.replace("-", "").replace("?", "") else s


def _nouvel_an(ny: Any) -> str:
    if isinstance(ny, (list, tuple)) and len(ny) == 2:
        return f"{ny[0]}-{ny[1]}"
    return NOUVEL_AN.get(ny, "") if ny else ""


def date_xml(dt: dict | None) -> str:
    """Date Gramps JSON -> élément Gramps XML, exactement comme ``write_date`` de Gramps (5.2 à 6.1) : double
    datation (dualdated), nouvel an, jour sans mois, date composée à un seul bout."""
    if not dt:
        return ""
    mod = dt.get("modifier", 0)
    if mod == 6:
        return f'<datestr val="{_att(dt.get("text") or "")}"/>'
    val = list(dt.get("dateval") or [0, 0, 0, False])
    val += [0, 0, 0, False] * 2
    extra = ""
    if dt.get("quality") in QUALITES:
        extra += f' quality="{QUALITES[dt["quality"]]}"'
    if dt.get("calendar") in CALENDRIERS:
        extra += f' cformat="{CALENDRIERS[dt["calendar"]]}"'
    if mod != 6 and val[3] and val[2]:  # get_slash : année de début non nulle
        extra += ' dualdated="1"'
    ny = _nouvel_an(dt.get("newyear"))
    if ny:
        extra += f' newyear="{_att(ny)}"'
    if mod in (4, 5):
        d1, d2 = _iso(*val[:3]), _iso(*val[4:7])
        if not (d1 or d2):
            return ""
        return f'<{"daterange" if mod == 4 else "datespan"} start="{d1}" stop="{d2}"{extra}/>'
    iso = _iso(*val[:3])
    if not iso:
        return ""
    typ = f' type="{MODIFICATEURS[mod]}"' if mod in MODIFICATEURS else ""
    return f'<dateval val="{iso}"{typ}{extra}/>'


def avertissements_dates(db: GrampsDb, version_xml: str) -> list[str]:
    """Pièges connus de Gramps 5.2 (cible de 1.7.1) sur les dates écrites, signalés à l'export plutôt que laissés
    à un import silencieusement dégradé (#272) : 5.2 ne lit pas une année avant notre ère dans ``daterange`` /
    ``datespan`` (date textuelle). ``dateval val=""``, qui fait échouer l'import de 5.2, n'est jamais écrit (une
    date sans valeur n'est pas écrite, comme chez Gramps)."""
    if version_xml != "1.7.1":
        return []
    ids = sorted(o.get("gramps_id") or o["handle"] for o in db.all("Event").values()
                 if (o.get("date") or {}).get("modifier") in (4, 5)
                 and any(y < 0 for y in list(o["date"].get("dateval") or [])[2:7:4]))
    if not ids:
        return []
    return [f"Gramps 5.2 lit comme date textuelle une plage ou un intervalle avec une année avant notre ère "
            f"({len(ids)} événement(s) : {', '.join(ids[:10])}{' …' if len(ids) > 10 else ''}) ; Gramps 6.0 et 6.1 "
            "les lisent (version_xml 1.7.1 ou 1.7.2)."]


# ============================================================================ écriture générique

def _valeur(o: dict, cle: str) -> Any:
    if not cle:
        return o
    for k in cle.split("."):
        o = (o or {}).get(k) if isinstance(o, dict) else None
    return o


def ecrire_objet(spec: Spec, o: dict, db: GrampsDb | None = None, extra: str = "") -> str:
    """Un objet JSON de Gramps en XML selon sa table."""
    if spec.vide and spec.vide(o):
        return ""
    attrs = extra
    for c in spec.attrs:
        v = c.conv.ecrire(_valeur(o, c.cle))
        if v is not None:
            attrs += f' {c.xml}="{_att(v)}"'
    inner = []
    for c in spec.enfants:
        v = _valeur(o, c.cle)
        if c.genre == "texte":
            s = c.conv.ecrire(v)
            if s is None and c.toujours:
                s = ""
            if s is not None and (s or c.toujours):
                inner.append(f"<{c.xml}>{_txt(s)}</{c.xml}>")
        elif c.genre == "val":
            s = c.conv.ecrire(v)
            if s:
                inner.append(f'<{c.xml} {c.attr}="{_att(s)}"/>')
        elif c.genre == "date":
            inner.append(date_xml(v))
        elif c.genre == "refs":
            for h in (v if isinstance(v, list) else [v]):
                if h:
                    inner.append(f'<{c.xml} hlink="{_att(c.conv.ecrire(h))}"/>')
        elif c.genre == "objet":
            if v:
                inner.append(ecrire_objet(c.spec, v, db, c.extra))
        elif c.genre == "liste":
            items = list(v or [])
            if c.ordonner:
                items = c.ordonner(o, items, db)
            inner += [ecrire_objet(c.spec, x, db, c.extra) for x in items]
        elif c.genre == "fonction":
            inner.append(c.fonction(o, db))
        else:  # pragma: no cover - table mal formée
            raise ValueError(f"genre de champ inconnu : {c.genre}")
    corps = "".join(inner)
    if spec.texte is not None:
        corps = _txt(o.get(spec.texte) or "")
        return f"<{spec.element}{attrs}>{corps}</{spec.element}>"
    return f"<{spec.element}{attrs}>{corps}</{spec.element}>" if corps else f"<{spec.element}{attrs}/>"


# ============================================================================ document complet

CHERCHEUR = ("resname", "resaddr", "reslocality", "rescity", "resstate", "rescountry", "respostal", "resphone",
             "resemail")
CIBLES_SIGNETS = {"person": "Person", "family": "Family", "event": "Event", "source": "Source",
                  "citation": "Citation", "place": "Place", "media": "Media", "repository": "Repository",
                  "note": "Note"}


@dataclass
class Metadonnees:
    """Contenu hors objets (point d'extension) : chercheur et chemin des médias de l'en-tête, personne de
    référence (``<people home>``, #274), formats de noms, signets (#276), regroupements de noms (``<namemaps>``,
    #282). Vide par défaut : rien n'est inventé."""
    chercheur: dict[str, str] = field(default_factory=dict)
    mediapath: str | None = None
    personne_reference: str | None = None
    formats_noms: list[tuple[int, str, str, bool]] = field(default_factory=list)
    signets: list[tuple[str, str]] = field(default_factory=list)  # (cible, handle)
    regroupements: list[tuple[str, str]] = field(default_factory=list)  # (patronyme, regroupé sous)

    def verifier(self, db: GrampsDb) -> None:
        inconnus = set(self.chercheur) - set(CHERCHEUR)
        if inconnus:
            raise ValueError(f"Champs de chercheur inconnus : {sorted(inconnus)}")
        if self.personne_reference and not db.get("Person", self.personne_reference):
            raise ValueError(f"Personne de référence absente de l'export : {self.personne_reference}")
        for cible, h in self.signets:
            if cible not in CIBLES_SIGNETS or not db.get(CIBLES_SIGNETS[cible], h):
                raise ValueError(f"Signet invalide : {cible} {h}")


def personne_reference(db: GrampsDb, racine: str, masquees=frozenset()) -> tuple[str | None, str]:
    """Personne de référence d'un export (#274) : (handle, motif). Le handle est celui de la personne dont le
    ``gramps_id`` est la racine Sosa (``GENEALOGISTE_SOSA_RACINE``) ; ``None`` avec le motif quand rien n'est écrit :
    racine non configurée, masquée par la projection de publication (aucune trace : ni handle ni ``home``) ou absente
    de l'export. Rien n'est inventé : sans racine, pas de ``home``."""
    if not racine:
        return None, "racine Sosa non configurée (GENEALOGISTE_SOSA_RACINE)"
    if racine in masquees:
        return None, "racine Sosa masquée par l'export public (personne vivante ou privée)"
    for p in db.all("Person").values():
        if p.get("gramps_id") == racine:
            return p["handle"], ""
    return None, "racine Sosa absente de l'export"


def _tri(db: GrampsDb, cls: str) -> list[dict]:
    objs = db.all(cls).values()
    if cls == "Tag":
        return sorted(objs, key=lambda t: (t.get("priority", 0), t.get("name", ""), t["handle"]))
    return sorted(objs, key=lambda o: (o.get("gramps_id") or "", o["handle"]))


def db_to_xml(db: GrampsDb, version_xml: str = VERSION_XML_DEFAUT, meta: Metadonnees | None = None) -> str:
    """Base Gramps (objets JSON) -> document Gramps XML complet de la version cible."""
    version = verifier_version_xml(version_xml)
    meta = meta or Metadonnees()
    meta.verifier(db)
    ns = f"{NS_URI}xml/{version}/"
    chercheur = "".join(f"<{k}>{_txt(meta.chercheur[k])}</{k}>" for k in CHERCHEUR if meta.chercheur.get(k))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<!DOCTYPE database PUBLIC "-//Gramps//DTD Gramps XML {version}//EN"\n"{ns}grampsxml.dtd">',
           f'<database xmlns="{ns}">',
           f'<header><created date="{date.today().isoformat()}" version="{VERSIONS_XML[version]}"/>'
           + (f"<researcher>{chercheur}</researcher>" if chercheur else "<researcher/>")
           + (f"<mediapath>{_txt(meta.mediapath)}</mediapath>" if meta.mediapath is not None else "")
           + "</header>"]
    if meta.formats_noms:
        out.append("<name-formats>" + "".join(
            f'<format number="{int(n)}" name="{_att(nom)}" fmt_str="{_att(fmt)}" active="{ACTIF.ecrire(actif)}"/>'
            for n, nom, fmt, actif in meta.formats_noms) + "</name-formats>")
    for section, cls, spec in SECTIONS:
        objs = _tri(db, cls)
        if not objs:
            continue
        home = f' home="_{_att(meta.personne_reference)}"' if cls == "Person" and meta.personne_reference else ""
        out.append(f"<{section}{home}>")
        out.extend(ecrire_objet(spec, o, db) for o in objs)
        out.append(f"</{section}>")
    if meta.signets:
        out.append("<bookmarks>" + "".join(f'<bookmark target="{c}" hlink="_{_att(h)}"/>' for c, h in meta.signets)
                   + "</bookmarks>")
    if meta.regroupements:
        out.append("<namemaps>" + "".join(f'<map type="group_as" key="{_att(k)}" value="{_att(v)}"/>'
                                          for k, v in meta.regroupements) + "</namemaps>")
    out.append("</database>")
    return "\n".join(out) + "\n"


def compresser(xml: str) -> bytes:
    """Gzip déterministe (date nulle), forme native d'un « .gramps » de Gramps Desktop."""
    return gzip.compress(xml.encode("utf-8"), mtime=0)


def to_gramps_xml(tree: Tree, strict: bool = False, forme: str = "genealogiste",
                  version_xml: str = VERSION_XML_DEFAUT) -> str:
    return to_gramps_xml_stats(tree, strict, forme, version_xml)[0]


def to_gramps_xml_stats(tree: Tree, strict: bool = False, forme: str = "genealogiste",
                        version_xml: str = VERSION_XML_DEFAUT) -> tuple[str, dict]:
    verifier_version_xml(version_xml)
    db, stats = tree_to_gramps_stats(tree, None, strict, forme=forme)
    return db_to_xml(db, version_xml), stats


# ============================================================================ paquet .gpkg

DONNEES_GPKG = "data.gramps"  # nom fixe lu par l'import gpkg de Gramps (XMLFILE)


def nom_archive(nom: str) -> str:
    """Nom de membre d'archive sûr : relatif, sans « .. » ni composant caché, distinct de data.gramps."""
    if (not nom or "\\" in nom or "\0" in nom or nom.startswith("/") or ":" in nom.split("/")[0]
            or any(x in ("", ".", "..") or x.startswith(".") for x in nom.split("/")) or nom == DONNEES_GPKG):
        raise ValueError(f"Nom de fichier d'archive refusé : {nom!r}")
    return nom


def _attr(m: dict, typ: str) -> dict | None:
    return next((a for a in m.get("attribute_list") or [] if tname(a.get("type")) == typ), None)


def preparer_gpkg(db: GrampsDb, racines: Iterable[Path]) -> tuple[GrampsDb, dict[str, Path], dict]:
    """Médias locaux d'un paquet : chaque fichier est résolu par la règle commune (chemins.localiser : racines
    autorisées, ni traversée ni lien sortant, ambiguïté refusée) et rangé sous un chemin relatif à sa racine.
    Renvoie une copie de la base où ``path`` (et l'attribut Genealogiste-Fichier) désignent ce chemin relatif,
    les membres {nom dans l'archive: fichier} et le bilan (inclus, manquants avec motif, distants)."""
    racines = tuple(Path(r).resolve() for r in racines if r is not None)
    db = db.copy()
    membres: dict[str, Path] = {}
    bilan: dict = {"inclus": 0, "manquants": [], "distants": []}
    for m in sorted(db.all("Media").values(), key=lambda o: (o.get("gramps_id") or "", o["handle"])):
        a = _attr(m, A_FICHIER)
        local = (a or {}).get("value") or m.get("path") or ""
        ident = m.get("gramps_id") or m["handle"]
        if not local:
            continue
        if "://" in local:
            bilan["distants"].append(f"{ident} : {local}")
            continue
        arc, motif, p = None, "", None
        try:
            p = localiser(racines, local)
        except CheminAmbigu as exc:
            motif = f"ambigu, refusé : {exc}"
        except CheminRefuse:
            motif = "hors des répertoires autorisés (données, médias), refusé"
        if p is not None:
            base = next(r for r in racines if p.is_relative_to(r))
            rel = p.relative_to(base).as_posix()
            try:
                arc = nom_archive(rel)
            except ValueError:
                motif = "nom réservé ou caché, refusé"
            else:
                if not p.is_file():
                    motif = "fichier introuvable"
                elif membres.get(arc, p) != p:  # même chemin relatif sous deux racines, fichiers différents
                    arc = nom_archive(f"racine-{racines.index(base) + 1}/{rel}")
        if motif:
            bilan["manquants"].append(f"{ident} : {local} ({motif})")
            if arc is None:  # rien d'absolu ni de sortant dans le paquet : seul le nom du fichier reste
                arc = PurePosixPath(local.replace("\\", "/")).name
        else:
            membres[arc] = p
        m["path"] = arc
        if a is not None:
            a["value"] = arc
    bilan["inclus"] = len(membres)
    return db, membres, bilan


_ABSOLU_WINDOWS = ABSOLU_WINDOWS


def verifier_chemin_base_medias(chemin: str) -> str:
    """Chemin de base des médias écrit dans ``<mediapath>`` (#280), validé : absolu (POSIX, ``C:\\…`` ou
    ``\\\\serveur\\…``), sans retour à la ligne ni caractère de contrôle, sans composant « .. », sans accolade
    (Gramps applique ``str.format`` au chemin : une accolade fait échouer l'import, ``expand_path``). Un chemin
    relatif est refusé : Gramps le lirait relatif au dossier de la base, pas du vault. Le séparateur final est retiré."""
    if not isinstance(chemin, str) or not chemin.strip():
        raise ValueError("chemin_base_medias vide")
    if chemin != chemin.strip() or any(ord(c) < 32 or ord(c) == 127 for c in chemin):
        raise ValueError("chemin_base_medias : espace en bordure, retour à la ligne ou caractère de contrôle")
    if "{" in chemin or "}" in chemin:
        raise ValueError("chemin_base_medias : accolade refusée (Gramps applique str.format au chemin et refuserait "
                         "l'import ; variables {GRAMPS_RESOURCES}… non écrites)")
    if not (chemin.startswith("/") or _ABSOLU_WINDOWS.match(chemin)):
        raise ValueError(f"chemin_base_medias doit être absolu (/…, C:\\… ou \\\\serveur\\…) : {chemin!r}. C'est le "
                         "dossier où la machine qui ouvrira l'arbre trouve la racine du vault.")
    if ".." in re.split(r"[\\/]+", chemin):
        raise ValueError(f"chemin_base_medias : composant « .. » refusé ({chemin!r})")
    sans_fin = chemin.rstrip("/\\")
    return chemin if not sans_fin or re.fullmatch(r"[A-Za-z]:", sans_fin) else sans_fin  # « / » et « C:\ » restent


def reduire_chemins_absolus(db: GrampsDb) -> tuple[GrampsDb, dict]:
    """Export public : copie de la base où le chemin d'un média, absolu (``/…``, ``~``, ``C:\\…``, UNC) ou sortant
    (``..``), est réduit à son nom de fichier, dans ``path`` (``<file src>``) et dans l'attribut de fichier
    (Genealogiste-Fichier, Sosa-Fichier). Un chemin relatif sans « .. » et une adresse web restent tels quels.
    Renvoie la copie et le bilan ``{nombre, medias}`` (identifiants de médias seulement : jamais un chemin)."""
    db = db.copy()
    reduits: list[str] = []

    for m in sorted(db.all("Media").values(), key=lambda o: (o.get("gramps_id") or "", o["handle"])):
        attrs = [a for a in m.get("attribute_list") or [] if tname(a.get("type")) in (A_FICHIER, "Sosa-Fichier")]
        valeurs = [m.get("path") or "", *[a.get("value") or "" for a in attrs]]
        if not any(sensible(v) for v in valeurs):
            continue
        if sensible(m.get("path") or ""):
            m["path"] = nom_fichier(m["path"])
        for a in attrs:
            v = a.get("value") or ""
            if sensible(v):
                a["value"] = nom_fichier(v)
        reduits.append(m.get("gramps_id") or m["handle"])
    return db, {"nombre": len(reduits), "medias": reduits}


def chemins_relatifs_a_la_base(db: GrampsDb, racines: Iterable[Path], base: Path) -> tuple[GrampsDb, dict]:
    """Copie de la base où le ``path`` de chaque média local, résolu par la règle commune (:func:`localiser`), est
    relatif à ``base`` (racine de l'arborescence des pièces : ce que ``<mediapath>`` désigne côté Desktop) quand le
    fichier s'y trouve ; l'attribut Genealogiste-Fichier suit. Un média hors de la base, introuvable, ambigu ou
    distant garde son chemin tel quel et est listé (identifiants seulement) : rien n'est inventé."""
    base = Path(base).resolve()
    racines = tuple(Path(r).resolve() for r in racines if r is not None)
    db = db.copy()
    bilan: dict = {"relatifs": 0, "distants": 0, "hors_base": [], "introuvables": [], "refuses": []}
    for m in sorted(db.all("Media").values(), key=lambda o: (o.get("gramps_id") or "", o["handle"])):
        a = _attr(m, A_FICHIER)
        local = (a or {}).get("value") or m.get("path") or ""
        ident = m.get("gramps_id") or m["handle"]
        if not local:
            continue
        if "://" in local:
            bilan["distants"] += 1
            continue
        try:
            p = localiser(racines, local)
        except CheminRefuse:  # ambigu, hors des racines
            bilan["refuses"].append(ident)
            continue
        if not p.is_file():
            bilan["introuvables"].append(ident)
            continue
        if not p.is_relative_to(base):
            bilan["hors_base"].append(ident)
            continue
        rel = p.relative_to(base).as_posix()
        m["path"] = rel
        if a is not None:
            a["value"] = rel
        bilan["relatifs"] += 1
    return db, bilan


def _entree(nom: str, taille: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(nom_archive(nom) if nom != DONNEES_GPKG else nom)
    info.size, info.mtime, info.mode, info.type = taille, 0, 0o644, tarfile.REGTYPE
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def ecrire_gpkg(sortie: BinaryIO, xml: str, membres: dict[str, Path]) -> None:
    """Paquet Gramps (tar gzip) déterministe : médias triés par nom puis data.gramps (XML gzippé), date nulle,
    propriétaire 0, droits 644 ; seuls des fichiers réguliers, sous des noms relatifs sûrs."""
    with gzip.GzipFile(filename="", mode="wb", fileobj=sortie, mtime=0) as gz, \
            tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for nom in sorted(membres):
            chemin = membres[nom]
            with chemin.open("rb") as f:
                tar.addfile(_entree(nom, chemin.stat().st_size), f)
        donnees = compresser(xml)
        tar.addfile(_entree(DONNEES_GPKG, len(donnees)), io.BytesIO(donnees))


def paquet_gpkg(db: GrampsDb, racines: Iterable[Path], version_xml: str = VERSION_XML_DEFAUT,
                meta: Metadonnees | None = None) -> tuple[bytes, dict]:
    """Paquet .gpkg complet en mémoire (tests, petits arbres) ; l'outil écrit directement dans un fichier."""
    base, membres, bilan = preparer_gpkg(db, racines)
    buf = io.BytesIO()
    ecrire_gpkg(buf, db_to_xml(base, version_xml, meta), membres)
    return buf.getvalue(), bilan
