"""Lecture Gramps XML 1.7.1 / 1.7.2 (« .gramps » brut ou gzip, paquet « .gpkg ») en objets Gramps JSON (#269).

Lecteur symétrique de :func:`genealogiste_mcp.export.gramps_xml.db_to_xml` : il parcourt les MÊMES tables
(``SECTIONS``, ``SPEC_*``, :class:`Champ` et ``Conv.lire``), sans seconde table de correspondance. Le résultat est
une :class:`GrampsDb` que :func:`gramps_to_tree` (module de correspondance unique) convertit en arbre Genealogiste.
Aller-retour : ``db_to_xml(lire_xml(x).db, version, meta)`` redonne ``x`` (après normalisation documentée dans
docs/gramps.md : mise en forme, ordre des attributs, date de ``<created>``).

Reconstruit comme Gramps à l'import (ce que le XML ne contient pas) : ``birth_ref_index`` / ``death_ref_index``
(première référence d'événement Birth / Death de rôle Primary, ``importxml.start_eventref``), ``Date.sortval``
(``Date._calc_sort_value`` et ``_adjust_newyear``, calendriers de ``gcalendar.py``), valeur de style typée
(taille de police : entier).

Sûreté (docs/securite.md) : analyseur expat de la bibliothèque standard, sans DTD interne, sans déclaration
d'entité (ni interne, ni externe, ni paramètre : refus avant toute expansion), sans résolution réseau ; taille du
XML décompressé bornée ; espace de noms étranger, préfixe ou élément / attribut inconnu du schéma : refus explicite
(rien n'est ignoré en silence). Versions acceptées : 1.7.1 et 1.7.2 ; toute autre (dont 1.8.0) est refusée.

Paquet ``.gpkg`` : tar (gzip) lu sans extraction automatique ; membres vérifiés AVANT toute écriture (fichiers
réguliers seulement, noms relatifs sans ``..`` ni composant caché, tailles et nombre bornés, un seul
``data.gramps``) ; les médias sont extraits dans une zone d'attente neuve fournie par l'appelant, jamais ailleurs.
"""

from __future__ import annotations

import gzip
import io
import math
import re
import shutil
import tarfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from xml.parsers import expat

from ..export import gramps_xml as gx
from .mapping import A_FICHIER, GrampsDb
from .types import TYPES, blank, blank_date, blank_name, gtype, surname, tname

# ============================================================================ limites

TAILLE_MAX_XML = 512 * 1024 * 1024  # XML décompressé (l'arbre d'exemple de Gramps : 2,8 Mo)
TAILLE_MAX_MEMBRE = 2 * 1024 * 1024 * 1024  # un fichier de média d'un paquet
TAILLE_MAX_PAQUET = 8 * 1024 * 1024 * 1024  # somme des membres d'un paquet
MEMBRES_MAX = 100_000
VERSIONS_LUES = ("1.7.1", "1.7.2")
_NS = re.compile(r"^https?://gramps-project\.org/xml/(\d+\.\d+\.\d+)/$")


class LectureGrampsError(ValueError):
    """Fichier Gramps refusé : message explicite pour l'utilisateur."""


# ============================================================================ décompression et format

def _gunzip_borne(brut: bytes, limite: int = TAILLE_MAX_XML) -> bytes:
    """Décompression gzip bornée (bombe de décompression refusée sans tout décompresser)."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(brut, limite + 1)
    if len(out) > limite or d.unconsumed_tail:
        raise LectureGrampsError(f"Fichier décompressé trop volumineux (plus de {limite // 2**20} Mio).")
    if not d.eof:
        raise LectureGrampsError("Fichier gzip tronqué ou illisible.")
    return out


def _est_tar(debut: bytes) -> bool:
    return len(debut) >= 262 and debut[257:262] == b"ustar"


def detecter(chemin: Path) -> str:
    """Format par le CONTENU, jamais par l'extension : ``gpkg`` (tar, gzip ou non), ``gramps`` (XML Gramps, gzip
    ou non) ou ``gedcom`` (tout le reste, laissé au lecteur GEDCOM)."""
    with chemin.open("rb") as f:
        debut = f.read(4096)
    if debut[:2] == b"\x1f\x8b":
        try:
            with gzip.open(chemin, "rb") as g:
                debut = g.read(4096)
        except (OSError, EOFError, zlib.error) as exc:
            raise LectureGrampsError(f"Fichier gzip illisible : {exc}") from exc
    if _est_tar(debut):
        return "gpkg"
    tete = debut.lstrip(b"\xef\xbb\xbf \t\r\n")
    if tete.startswith(b"<"):
        return "gramps"
    return "gedcom"


# ============================================================================ analyse XML sûre

@dataclass
class Noeud:
    tag: str
    attrib: dict[str, str]
    enfants: list[Noeud] = field(default_factory=list)
    texte: list[str] = field(default_factory=list)
    ligne: int = 0

    @property
    def text(self) -> str:
        return "".join(self.texte)


def analyser(brut: bytes) -> Noeud:
    """Arbre d'éléments d'un document XML, analysé par expat avec les protections de defusedxml : DTD interne,
    déclaration d'entité (générale, paramètre, non analysée) et entité externe refusées ; aucune ressource lue.
    Les espaces de noms ne sont pas interprétés : ``xmlns`` est un attribut ordinaire, contrôlé par l'appelant."""
    if len(brut) > TAILLE_MAX_XML:
        raise LectureGrampsError(f"XML trop volumineux (plus de {TAILLE_MAX_XML // 2**20} Mio).")
    p = expat.ParserCreate()
    p.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    p.buffer_text = True
    racine: list[Noeud] = []
    pile: list[Noeud] = []

    def refus(motif: str):
        def h(*_a):
            raise LectureGrampsError(f"XML refusé : {motif} (ligne {p.CurrentLineNumber}).")
        return h

    def doctype(nom, _sys, _pub, sous_ensemble):
        if sous_ensemble:
            raise LectureGrampsError("XML refusé : DTD interne (déclarations dans le DOCTYPE) non admise.")
        if nom != "database":
            raise LectureGrampsError(f"XML refusé : DOCTYPE {nom!r}, pas un fichier Gramps (database).")

    def debut(tag, attrs):
        n = Noeud(tag, attrs, ligne=p.CurrentLineNumber)
        (pile[-1].enfants if pile else racine).append(n)
        pile.append(n)

    def fin(_tag):
        pile.pop()

    def texte(data):
        if pile:
            pile[-1].texte.append(data)

    p.StartDoctypeDeclHandler = doctype
    p.EntityDeclHandler = refus("déclaration d'entité")
    p.UnparsedEntityDeclHandler = refus("entité non analysée")
    p.ExternalEntityRefHandler = refus("entité externe")
    p.NotationDeclHandler = refus("déclaration de notation")
    p.StartElementHandler = debut
    p.EndElementHandler = fin
    p.CharacterDataHandler = texte
    try:
        p.Parse(brut, True)
    except expat.ExpatError as exc:
        raise LectureGrampsError(f"XML mal formé : {exc}") from exc
    return racine[0]


# ============================================================================ gabarits des sous-objets

def _ref(cls: str, **kw) -> dict:
    return {"_class": cls, "private": False, "citation_list": [], "note_list": [], **kw}


GABARITS: dict[int, Callable[[], dict]] = {
    id(gx.SPEC_ATTRIBUT): lambda: {"_class": "Attribute", "private": False, "citation_list": [], "note_list": [],
                                   "type": gtype("AttributeType", ""), "value": ""},
    id(gx.SPEC_ATTRIBUT_SOURCE): lambda: {"_class": "SrcAttribute", "private": False,
                                          "type": gtype("SrcAttributeType", ""), "value": ""},
    id(gx.SPEC_URL): lambda: {"_class": "Url", "private": False, "path": "", "desc": "",
                              "type": gtype("UrlType", "")},
    id(gx.SPEC_ADRESSE): lambda: _ref("Address", date=blank_date(), street="", locality="", city="", county="",
                                      state="", country="", postal="", phone=""),
    id(gx.SPEC_OBJREF): lambda: _ref("MediaRef", attribute_list=[], ref="", rect=None),
    id(gx.SPEC_EVENTREF): lambda: _ref("EventRef", attribute_list=[], ref="", role=gtype("EventRoleType", "")),
    id(gx.SPEC_CHILDREF): lambda: _ref("ChildRef", ref="", frel=gtype("ChildRefType", "Birth"),
                                       mrel=gtype("ChildRefType", "Birth")),
    id(gx.SPEC_PERSONREF): lambda: _ref("PersonRef", ref="", rel=""),
    id(gx.SPEC_PATRONYME): lambda: surname(""),
    id(gx.SPEC_NOM): lambda: {**blank_name(), "type": gtype("NameType", "")},
    id(gx.SPEC_LDS): lambda: {"_class": "LdsOrd", "citation_list": [], "note_list": [], "date": blank_date(),
                              "type": 0, "place": "", "famc": None, "temple": "", "status": 0, "private": False},
    id(gx.SPEC_NOM_LIEU): lambda: {"_class": "PlaceName", "value": "", "date": blank_date(), "lang": ""},
    id(gx.SPEC_PLACEREF): lambda: {"_class": "PlaceRef", "ref": "", "date": blank_date()},
    id(gx.SPEC_LOCALISATION): lambda: {"_class": "Location", **dict.fromkeys(gx._LOCALISATION, "")},
    id(gx.SPEC_REPOREF): lambda: {"_class": "RepoRef", "note_list": [], "ref": "", "call_number": "",
                                  "media_type": gtype("SourceMediaType", ""), "private": False},
    id(gx.SPEC_STYLE): lambda: {"_class": "StyledTextTag", "name": gtype("StyledTextTagType", ""), "value": None,
                                "ranges": []},
}

# valeur typée d'un style de note (StyledTextTagType.STYLE_TYPE de Gramps) : taille de police entière
_STYLE_ENTIER = {4}  # FONTSIZE


def _gabarit(spec: gx.Spec, cls: str | None = None) -> dict:
    if cls:  # objet primaire : gabarit complet de types.blank (mêmes clés qu'object_to_dict)
        o = blank(cls, "")
        if cls == "Note":
            o["type"] = gtype("NoteType", "")
        return o
    return GABARITS[id(spec)]()


# ============================================================================ dates

_CAL = {v: k for k, v in gx.CALENDRIERS.items()}
_MOD = {v: k for k, v in gx.MODIFICATEURS.items()}
_QUAL = {v: k for k, v in gx.QUALITES.items()}
_NY = {v: k for k, v in gx.NOUVEL_AN.items()}
_ELEMENTS_DATE = ("dateval", "daterange", "datespan", "datestr")


def _point(s: str, n: Noeud) -> list:
    """« AAAA-MM-JJ » de Gramps (????, ?? : inconnus ; année négative) -> [jour, mois, année]."""
    signe = 1
    if s.startswith("-"):
        signe, s = -1, s[1:]
    parties = s.split("-") if s else []
    if len(parties) > 3:
        raise LectureGrampsError(f"Date illisible {s!r} (ligne {n.ligne}).")

    def num(i: int) -> int:
        if i >= len(parties) or set(parties[i]) <= {"?"}:
            return 0
        if not parties[i].isdigit():
            raise LectureGrampsError(f"Date illisible {s!r} (ligne {n.ligne}).")
        return int(parties[i])
    return [num(2), num(1), num(0) * signe]


def _nouvel_an(v: str, n: Noeud) -> Any:
    if v in _NY:
        return _NY[v]
    if v.isdigit():
        return int(v)
    m = re.fullmatch(r"(\d+)-(\d+)", v)
    if m:
        return [int(m[1]), int(m[2])]
    raise LectureGrampsError(f"Nouvel an inconnu {v!r} (ligne {n.ligne}).")


_ATTRS_DATE = {"dateval": {"val", "type", "quality", "cformat", "dualdated", "newyear"},
               "daterange": {"start", "stop", "quality", "cformat", "dualdated", "newyear"},
               "datespan": {"start", "stop", "quality", "cformat", "dualdated", "newyear"},
               "datestr": {"val"}}


def lire_date(n: Noeud) -> dict:
    """Élément de date -> Date JSON (inverse exact de :func:`gx.date_xml`), sortval recalculée comme Gramps."""
    _verifier_attrs(n, _ATTRS_DATE[n.tag])
    d = blank_date()
    a = n.attrib
    if n.tag == "datestr":
        d.update(modifier=6, text=a.get("val", ""))
        return d
    if "cformat" in a:
        if a["cformat"] not in _CAL:
            raise LectureGrampsError(f"Calendrier inconnu {a['cformat']!r} (ligne {n.ligne}).")
        d["calendar"] = _CAL[a["cformat"]]
    if "quality" in a:
        d["quality"] = _QUAL.get(a["quality"], 0)
    slash = a.get("dualdated") == "1"
    if "newyear" in a:
        d["newyear"] = _nouvel_an(a["newyear"], n)
    if n.tag == "dateval":
        if a.get("type") is not None:
            if a["type"] not in _MOD:
                raise LectureGrampsError(f"Modificateur de date inconnu {a['type']!r} (ligne {n.ligne}).")
            d["modifier"] = _MOD[a["type"]]
        d["dateval"] = [*_point(a.get("val", ""), n), slash]
    else:
        d["modifier"] = 4 if n.tag == "daterange" else 5
        d["dateval"] = [*_point(a.get("start", ""), n), slash, *_point(a.get("stop", ""), n), slash]
    d["sortval"] = valeur_tri(d)
    return d


# --- valeur de tri : calendriers de Gramps (gramps/gen/lib/gcalendar.py, GPL-2.0-or-later) -----------------

def _gregorien(y: int, m: int, d: int) -> int:
    y += 4801 if y < 0 else 4800
    if m > 2:
        m -= 3
    else:
        m += 9
        y -= 1
    return ((y // 100) * 146097) // 4 + ((y % 100) * 1461) // 4 + (m * 153 + 2) // 5 + d - 32045


def _julien(y: int, m: int, d: int) -> int:
    y += 4801 if y < 0 else 4800
    if m > 2:
        m -= 3
    else:
        m += 9
        y -= 1
    return (y * 1461) // 4 + (m * 153 + 2) // 5 + d - 32083


def _republicain(y: int, m: int, d: int) -> int:
    return (y * 1461) // 4 + (m - 1) * 30 + d + 2375474


def _persan(y: int, m: int, d: int) -> int:
    epbase = y - 474 if y >= 0 else y - 473
    epyear = 474 + epbase % 2820
    v1 = (m - 1) * 31 if m <= 7 else (m - 1) * 30 + 6
    return int(math.ceil(v1 + ((epyear * 682) - 110) // 2816 + (epyear - 1) * 365 + d
                         + (epbase // 2820) * 1029983 + 1948320.5 - 1))


def _islamique(y: int, m: int, d: int) -> int:
    return int(math.ceil((d + math.ceil(29.5 * (m - 1)) + (y - 1) * 354 + math.floor((3 + 11 * y) // 30)
                          + 1948439.5) - 1))


def _suedois(y: int, m: int, d: int) -> int:
    if (1700, 3, 1) <= (y, m, d) <= (1712, 2, 30):
        return _julien(y, m, d) - 1
    return _gregorien(y, m, d) if (1753, 3, 1) <= (y, m, d) else _julien(y, m, d)


_H_JOUR, _H_LUNE = 25920, 29 * 25920 + 13753
_H_CYCLE = _H_LUNE * (12 * 19 + 7)
_H_MOIS_AN = (12, 12, 13, 12, 12, 13, 12, 13, 12, 12, 13, 12, 12, 13, 12, 12, 13, 12, 13)
_H_DECALAGE = (0, 12, 24, 37, 49, 61, 74, 86, 99, 111, 123, 136, 148, 160, 173, 185, 197, 210, 222)


def _tishri1(an_meton: int, jour: int, halakim: int) -> int:
    dow = jour % 7
    bissextile = an_meton in (2, 5, 7, 10, 13, 16, 18)
    precedente = an_meton in (3, 6, 8, 11, 14, 17, 0)
    if halakim >= 18 * 1080 or (not bissextile and dow == 2 and halakim >= 9 * 1080 + 204) \
            or (precedente and dow == 1 and halakim >= 15 * 1080 + 589):
        jour += 1
        dow = (dow + 1) % 7
    return jour + (1 if dow in (3, 5, 0) else 0)


def _molad(cycle: int) -> tuple[int, int]:
    r1 = 31524 + cycle * (_H_CYCLE & 0xFFFF)
    r2 = (r1 >> 16) + cycle * ((_H_CYCLE >> 16) & 0xFFFF)
    d2 = r2 // _H_JOUR
    r2 -= d2 * _H_JOUR
    r1 = (r2 << 16) | (r1 & 0xFFFF)
    d1 = r1 // _H_JOUR
    return (d2 << 16) | d1, r1 - d1 * _H_JOUR


def _debut_annee(y: int) -> tuple[int, int, int, int]:
    an = (y - 1) % 19
    jour, hal = _molad((y - 1) // 19)
    hal += _H_LUNE * _H_DECALAGE[an]
    jour, hal = jour + hal // _H_JOUR, hal % _H_JOUR
    return an, jour, hal, _tishri1(an, jour, hal)


def _hebreu(y: int, m: int, d: int) -> int:
    if m in (1, 2):
        t1 = _debut_annee(y)[3]
        sdn = t1 + d - 1 if m == 1 else t1 + d + 29
    elif m == 3:
        an, jour, hal, t1 = _debut_annee(y)
        hal += _H_LUNE * _H_MOIS_AN[an]
        jour, hal = jour + hal // _H_JOUR, hal % _H_JOUR
        sdn = t1 + d + (59 if _tishri1((an + 1) % 19, jour, hal) - t1 in (355, 385) else 58)
    elif m in (4, 5, 6):
        apres = _debut_annee(y + 1)[3]
        adar = 29 if _H_MOIS_AN[(y - 1) % 19] == 12 else 59
        sdn = apres + d - adar - {4: 237, 5: 208, 6: 178}[m]
    elif 7 <= m <= 13:
        sdn = _debut_annee(y + 1)[3] + d - {7: 207, 8: 178, 9: 148, 10: 119, 11: 89, 12: 60, 13: 30}[m]
    else:
        return 0
    return sdn + 347997


_CALENDRIERS_TRI = (_gregorien, _julien, _hebreu, _republicain, _persan, _islamique, _suedois)


def valeur_tri(d: dict) -> int:
    """``Date.sortval`` comme Gramps : jour julien du premier point (année 0 -> 1, mois et jour 0 -> 1) dans le
    calendrier de la date, décalé d'un an si le nouvel an tombe avant le mois et le jour ; 0 pour une date vide
    ou textuelle."""
    if d.get("modifier") == 6:
        return 0
    jour, mois, an = (list(d.get("dateval") or []) + [0, 0, 0])[:3]
    if an == mois == jour == 0:
        return 0
    conv = _CALENDRIERS_TRI[d.get("calendar", 0)]

    def sdn(y: int) -> int:
        return conv(y if y != 0 else 1, max(mois, 1), max(jour, 1))
    ny = d.get("newyear") or 0
    coupure = {1: (3, 1), 2: (3, 25), 3: (9, 1)}.get(ny) if not isinstance(ny, list) else tuple(ny)
    if coupure and coupure != (0, 0) and (mois, jour) >= coupure:
        return sdn(an - 1)
    return sdn(an)


# ============================================================================ lecture générique (tables SPEC_*)

def _verifier_attrs(n: Noeud, connus: set[str]) -> None:
    inconnus = sorted(set(n.attrib) - connus)
    if inconnus:
        raise LectureGrampsError(f"Attribut inconnu du schéma Gramps sur <{n.tag}> : {', '.join(inconnus)} "
                                 f"(ligne {n.ligne}).")


def _texte_vide(n: Noeud) -> None:
    if n.text.strip():
        raise LectureGrampsError(f"Texte inattendu dans <{n.tag}> (ligne {n.ligne}).")


def _poser(o: dict, cle: str, v: Any) -> None:
    *chemin, fin = cle.split(".")
    for k in chemin:
        o = o.setdefault(k, {})
    o[fin] = v


def _liste(o: dict, cle: str) -> list:
    *chemin, fin = cle.split(".")
    for k in chemin:
        o = o.setdefault(k, {})
    return o.setdefault(fin, [])


def _lire_val(c: gx.Champ, s: str, n: Noeud) -> Any:
    try:
        return c.conv.lire(s)
    except (ValueError, TypeError) as exc:
        raise LectureGrampsError(f"Valeur illisible {s!r} pour {c.xml} (ligne {n.ligne}).") from exc


def _extra(c: gx.Champ) -> dict[str, str]:
    return dict(re.findall(r'(\w+)="([^"]*)"', c.extra))


def _fonction(c: gx.Champ, o: dict, n: Noeud) -> None:
    """Formes particulières écrites par une fonction (rectangle, coordonnées, plages de style)."""
    a = n.attrib
    try:
        if c.xml == "region":
            _verifier_attrs(n, {"corner1_x", "corner1_y", "corner2_x", "corner2_y"})
            o["rect"] = [int(a["corner1_x"]), int(a["corner1_y"]), int(a["corner2_x"]), int(a["corner2_y"])]
        elif c.xml == "coord":
            _verifier_attrs(n, {"long", "lat"})
            o["long"], o["lat"] = a.get("long", ""), a.get("lat", "")
        elif c.xml == "range":
            _verifier_attrs(n, {"start", "end"})
            o.setdefault("ranges", []).append([int(a["start"]), int(a["end"])])
        else:  # pragma: no cover - table mal formée
            raise LectureGrampsError(f"Forme particulière sans lecteur : {c.xml}")
    except (KeyError, ValueError) as exc:
        raise LectureGrampsError(f"<{n.tag}> incomplet ou illisible (ligne {n.ligne}).") from exc


def lire_objet(spec: gx.Spec, n: Noeud, o: dict, ignorer: set[str] | None = None) -> dict:
    """Élément XML -> objet JSON de Gramps selon sa table (inverse de :func:`gx.ecrire_objet`). ``o`` : gabarit
    complet (valeurs par défaut des champs omis à l'écriture)."""
    connus = {c.xml for c in spec.attrs} | (ignorer or set())
    _verifier_attrs(n, connus)
    for c in spec.attrs:
        if c.xml in n.attrib:
            _poser(o, c.cle, _lire_val(c, n.attrib[c.xml], n))
    if spec.texte is not None:
        if n.enfants:
            raise LectureGrampsError(f"<{n.tag}> ne contient que du texte (ligne {n.ligne}).")
        o[spec.texte] = n.text
        return o
    par_tag: dict[str, list[gx.Champ]] = {}
    for c in spec.enfants:
        for t in (_ELEMENTS_DATE if c.genre == "date" else (c.xml,)):
            par_tag.setdefault(t, []).append(c)
    _texte_vide(n)
    objets_vus: set[int] = set()
    for e in n.enfants:
        champs = par_tag.get(e.tag)
        if not champs:
            raise LectureGrampsError(f"Élément <{e.tag}> inconnu dans <{n.tag}> (ligne {e.ligne}) : refusé "
                                     "plutôt qu'ignoré (schéma Gramps XML 1.7.1 / 1.7.2).")
        c = _choisir(champs, e, objets_vus, n)
        if c.genre == "date":
            if e.enfants:
                raise LectureGrampsError(f"<{e.tag}> ne contient rien (ligne {e.ligne}).")
            o[c.cle] = lire_date(e)
        elif c.genre == "texte":
            _verifier_attrs(e, set())
            if e.enfants:
                raise LectureGrampsError(f"<{e.tag}> ne contient que du texte (ligne {e.ligne}).")
            _poser(o, c.cle, _lire_val(c, e.text, e))
        elif c.genre == "val":
            _verifier_attrs(e, {c.attr})
            _texte_vide(e)
            _poser(o, c.cle, _lire_val(c, e.attrib.get(c.attr, ""), e))
        elif c.genre == "refs":
            _verifier_attrs(e, {"hlink"})
            _texte_vide(e)
            if "hlink" not in e.attrib:
                raise LectureGrampsError(f"<{e.tag}> sans hlink (ligne {e.ligne}).")
            h = _lire_val(c, e.attrib["hlink"], e)
            if isinstance(o.get(c.cle), list):
                o[c.cle].append(h)
            else:
                o[c.cle] = h
        elif c.genre == "objet":
            ex = _extra(c)
            if c.cle:
                o[c.cle] = lire_objet(c.spec, e, _gabarit(c.spec), set(ex))
            else:  # l'objet lui-même (<file> du média)
                lire_objet(c.spec, e, o, set(ex))
        elif c.genre == "liste":
            ex = _extra(c)
            _liste(o, c.cle).append(lire_objet(c.spec, e, _gabarit(c.spec), set(ex)))
        elif c.genre == "fonction":
            _texte_vide(e)
            _fonction(c, o, e)
        else:  # pragma: no cover
            raise LectureGrampsError(f"genre de champ inconnu : {c.genre}")
    return o


def _choisir(champs: list[gx.Champ], e: Noeud, vus: set[int], parent: Noeud) -> gx.Champ:
    """Champ d'un élément enfant : un seul candidat en général ; pour <name> et <pname>, l'objet principal puis la
    liste (``alt="1"`` des noms alternatifs ; premier <pname> = nom du lieu, les suivants = noms alternatifs)."""
    if len(champs) == 1:
        c = champs[0]
        if c.genre == "objet":
            if id(c) in vus:
                raise LectureGrampsError(f"<{e.tag}> en double dans <{parent.tag}> (ligne {e.ligne}).")
            vus.add(id(c))
        return c
    for c in champs:
        ex = _extra(c)
        if ex and all(e.attrib.get(k) == v for k, v in ex.items()):
            return c
    objet = next((c for c in champs if c.genre == "objet" and not _extra(c)), None)
    if objet is not None and id(objet) not in vus:
        vus.add(id(objet))
        return objet
    liste = next((c for c in champs if c.genre == "liste" and not _extra(c)), None)
    if liste is not None:
        return liste
    raise LectureGrampsError(f"<{e.tag}> en double dans <{parent.tag}> (ligne {e.ligne}).")


def _index_naissance_deces(db: GrampsDb) -> None:
    """Comme l'importeur de Gramps : première référence d'un événement Birth (Death) de rôle Primary."""
    for p in db.all("Person").values():
        refs = p.get("event_ref_list") or []
        for cle, typ in (("birth_ref_index", 12), ("death_ref_index", 13)):
            p[cle] = next((i for i, r in enumerate(refs)
                           if (r.get("role") or {}).get("value") == 1 and r.get("ref")
                           and ((db.get("Event", r["ref"]) or {}).get("type") or {}).get("value") == typ), -1)


# ============================================================================ document

@dataclass
class Lecture:
    """Résultat de la lecture d'un fichier Gramps."""
    db: GrampsDb
    meta: gx.Metadonnees
    version_xml: str
    version_gramps: str
    date_creation: str
    format: str = "gramps"  # gramps | gramps-gzip | gpkg
    ignores: list[str] = field(default_factory=list)  # attributs que Gramps lui-même ignore (people/@default)
    medias: list[dict] = field(default_factory=list)  # médias extraits d'un paquet
    zone: Path | None = None


_SECTIONS = {s: (cls, spec) for s, cls, spec in gx.SECTIONS}
_ORDRE = ("header", "name-formats", *(s for s, _, _ in gx.SECTIONS), "bookmarks", "namemaps")


def verifier_version(xmlns: str | None) -> str:
    """Version XML d'après l'espace de noms ; refus explicite d'une version non prise en charge."""
    m = _NS.match(xmlns or "")
    if not m:
        raise LectureGrampsError(
            f"Espace de noms {xmlns!r} : pas un fichier Gramps XML (attendu http://gramps-project.org/xml/<version>/).")
    v = m[1]
    if v in VERSIONS_LUES:
        return v
    if v == "1.8.0":
        raise LectureGrampsError("Gramps XML 1.8.0 (objets ADN, branche master de Gramps) : pas encore pris en "
                                 "charge. Exporter depuis Gramps 5.2, 6.0 ou 6.1 (XML 1.7.1 ou 1.7.2).")
    raise LectureGrampsError(f"Gramps XML {v} non pris en charge : versions lues 1.7.1 (Gramps 5.2) et 1.7.2 "
                             "(Gramps 6.0, 6.1). Réexporter le fichier depuis une version récente de Gramps.")


def lire_xml(brut: bytes) -> Lecture:
    """Document Gramps XML (octets, gzip ou non) -> objets Gramps JSON, métadonnées et version."""
    fmt = "gramps"
    if brut[:2] == b"\x1f\x8b":
        brut, fmt = _gunzip_borne(brut), "gramps-gzip"
    racine = analyser(brut)
    if racine.tag != "database":
        raise LectureGrampsError(f"Élément racine <{racine.tag}> : pas un fichier Gramps XML (<database>).")
    _verifier_attrs(racine, {"xmlns"})
    version = verifier_version(racine.attrib.get("xmlns"))
    _texte_vide(racine)
    db, meta, ignores = GrampsDb(), gx.Metadonnees(), []
    cree, version_gramps, rang = "", "", -1
    for sec in racine.enfants:
        if sec.tag not in _ORDRE:
            raise LectureGrampsError(f"Section <{sec.tag}> inconnue (ligne {sec.ligne}) : refusée plutôt qu'ignorée.")
        r = _ORDRE.index(sec.tag)
        if r <= rang:
            raise LectureGrampsError(f"Section <{sec.tag}> en double ou hors de l'ordre du schéma (ligne {sec.ligne}).")
        rang = r
        if sec.tag == "header":
            cree, version_gramps = _entete(sec, meta)
        elif sec.tag == "name-formats":
            _formats(sec, meta)
        elif sec.tag == "bookmarks":
            _signets(sec, meta)
        elif sec.tag == "namemaps":
            _regroupements(sec, meta)
        else:
            cls, spec = _SECTIONS[sec.tag]
            connus = {"home", "default"} if sec.tag == "people" else set()
            _verifier_attrs(sec, connus)
            _texte_vide(sec)
            if sec.tag == "people":
                if "home" in sec.attrib:
                    meta.personne_reference = gx.HANDLE.lire(sec.attrib["home"])
                if "default" in sec.attrib:
                    ignores.append(f"<people default=\"{sec.attrib['default']}\"> (ignoré par Gramps aussi)")
            for e in sec.enfants:
                if e.tag != spec.element:
                    raise LectureGrampsError(f"<{e.tag}> inattendu dans <{sec.tag}> (ligne {e.ligne}).")
                o = lire_objet(spec, e, _gabarit(spec, cls))
                if not o.get("handle"):
                    raise LectureGrampsError(f"<{e.tag}> sans handle (ligne {e.ligne}).")
                if db.get(cls, o["handle"]):
                    raise LectureGrampsError(f"Handle {o['handle']} en double ({cls}, ligne {e.ligne}).")
                db.put(o)
    if not version_gramps:
        raise LectureGrampsError("En-tête sans version de Gramps (<created version>) : fichier refusé, comme par "
                                 "Gramps lui-même.")
    for st in (s for n in db.all("Note").values() for s in n["text"]["tags"]):
        if st["value"] is not None and st["name"].get("value") in _STYLE_ENTIER:
            try:
                st["value"] = int(st["value"])
            except ValueError as exc:
                raise LectureGrampsError(f"Taille de police illisible : {st['value']!r}") from exc
    _index_naissance_deces(db)
    return Lecture(db, meta, version, version_gramps, cree, fmt, ignores)


def _entete(n: Noeud, meta: gx.Metadonnees) -> tuple[str, str]:
    _verifier_attrs(n, set())
    _texte_vide(n)
    cree = version = ""
    for e in n.enfants:
        if e.tag == "created":
            _verifier_attrs(e, {"date", "version"})
            cree, version = e.attrib.get("date", ""), e.attrib.get("version", "")
        elif e.tag == "researcher":
            _verifier_attrs(e, set())
            _texte_vide(e)
            for c in e.enfants:
                if c.tag not in gx.CHERCHEUR or c.enfants:
                    raise LectureGrampsError(f"<{c.tag}> inconnu dans <researcher> (ligne {c.ligne}).")
                _verifier_attrs(c, set())
                meta.chercheur[c.tag] = c.text
        elif e.tag == "mediapath":
            _verifier_attrs(e, set())
            meta.mediapath = e.text
        else:
            raise LectureGrampsError(f"<{e.tag}> inconnu dans l'en-tête (ligne {e.ligne}).")
    return cree, version


def _feuilles(n: Noeud, tag: str, attrs: set[str]) -> list[Noeud]:
    _verifier_attrs(n, set())
    _texte_vide(n)
    for e in n.enfants:
        if e.tag != tag:
            raise LectureGrampsError(f"<{e.tag}> inconnu dans <{n.tag}> (ligne {e.ligne}).")
        _verifier_attrs(e, attrs)
        _texte_vide(e)
    return n.enfants


def _formats(n: Noeud, meta: gx.Metadonnees) -> None:
    for e in _feuilles(n, "format", {"number", "name", "fmt_str", "active"}):
        try:
            meta.formats_noms.append((int(e.attrib["number"]), e.attrib.get("name", ""), e.attrib.get("fmt_str", ""),
                                      gx.ACTIF.lire(e.attrib.get("active", "0"))))
        except (KeyError, ValueError) as exc:
            raise LectureGrampsError(f"<format> illisible (ligne {e.ligne}).") from exc


def _signets(n: Noeud, meta: gx.Metadonnees) -> None:
    for e in _feuilles(n, "bookmark", {"target", "hlink"}):
        meta.signets.append((e.attrib.get("target", ""), gx.HANDLE.lire(e.attrib.get("hlink", ""))))


def _regroupements(n: Noeud, meta: gx.Metadonnees) -> None:
    for e in _feuilles(n, "map", {"type", "key", "value"}):
        if e.attrib.get("type") != "group_as":
            raise LectureGrampsError(f"<map type={e.attrib.get('type')!r}> inconnu (ligne {e.ligne}).")
        meta.regroupements.append((e.attrib.get("key", ""), e.attrib.get("value", "")))


# ============================================================================ aller-retour : comparaison normalisée

_SECTIONS_OBJETS = {s for s, _, _ in gx.SECTIONS}


def _elements_texte() -> set[str]:
    """Éléments dont le texte est une valeur (espaces compris) ; ailleurs, le texte n'est que mise en forme."""
    out, vus, pile = {"mediapath", *gx.CHERCHEUR}, set(), [spec for _, _, spec in gx.SECTIONS]
    while pile:
        spec = pile.pop()
        if id(spec) in vus:
            continue
        vus.add(id(spec))
        if spec.texte is not None:
            out.add(spec.element)
        for c in spec.enfants:
            if c.genre == "texte":
                out.add(c.xml)
            if c.spec is not None:
                pile.append(c.spec)
    return out


_TEXTE_VALEUR = _elements_texte()


def comparer_xml(a: bytes, b: bytes, limite: int = 20) -> list[str]:
    """Écarts entre deux documents Gramps XML après la normalisation de l'aller-retour (docs/gramps.md) : mise en
    forme (espaces entre éléments), ordre des attributs, ordre des objets dans une section (Gramps les trie par
    handle, Genealogiste par identifiant), date de ``<created>``. Tout le reste compte : éléments, attributs,
    valeurs et texte exacts (espaces compris). L'élément ``<created>`` (date et version de Gramps qui a écrit le
    fichier) décrit l'écriture, pas l'arbre : ignoré."""
    ecarts: list[str] = []
    if a[:2] == b"\x1f\x8b":
        a = _gunzip_borne(a)
    if b[:2] == b"\x1f\x8b":
        b = _gunzip_borne(b)

    def cmp(p: Noeud, q: Noeud, chemin: str) -> None:
        if len(ecarts) >= limite:
            return
        ici = f"{chemin}/{p.tag}"
        pa = {} if p.tag == "created" else p.attrib
        qa = {} if q.tag == "created" else q.attrib
        if p.tag != q.tag or pa != qa:
            ecarts.append(f"{ici} (ligne {p.ligne}/{q.ligne}) : <{p.tag} {pa}> != <{q.tag} {qa}>")
            return
        tp, tq = (p.text, q.text) if p.tag in _TEXTE_VALEUR else (p.text.strip(), q.text.strip())
        if tp != tq:
            ecarts.append(f"{ici} (ligne {p.ligne}/{q.ligne}) : texte {tp[:60]!r} != {tq[:60]!r}")
        pe, qe = p.enfants, q.enfants
        if p.tag in _SECTIONS_OBJETS:
            pe, qe = (sorted(x, key=lambda n: n.attrib.get("handle", "")) for x in (pe, qe))
        if [e.tag for e in pe] != [e.tag for e in qe]:
            ecarts.append(f"{ici} (ligne {p.ligne}/{q.ligne}) : enfants {[e.tag for e in pe][:12]} != "
                          f"{[e.tag for e in qe][:12]}")
            return
        for x, y in zip(pe, qe, strict=True):
            cmp(x, y, ici)

    cmp(analyser(a), analyser(b), "")
    return ecarts


# ============================================================================ paquet .gpkg

def _membre_sur(nom: str) -> str:
    """Nom de membre accepté : relatif, sans « .. », « . », composant caché, antislash, NUL ni lecteur."""
    try:
        return gx.nom_archive(nom) if nom != gx.DONNEES_GPKG else nom
    except ValueError as exc:
        raise LectureGrampsError(f"Paquet refusé : membre au nom dangereux {nom!r}.") from exc


def inspecter_gpkg(chemin: Path) -> tuple[list[tarfile.TarInfo], tarfile.TarInfo]:
    """Membres d'un paquet, vérifiés AVANT toute extraction : fichiers réguliers seulement (lien symbolique ou
    physique, périphérique, FIFO : refus), noms sûrs et uniques, tailles et nombre bornés, un seul data.gramps."""
    vus: set[str] = set()
    total = 0
    donnees = None
    fichiers = []
    try:
        with tarfile.open(chemin, "r:*") as tar:
            for n, m in enumerate(tar, 1):  # chaque en-tête vérifié avant de lire (décompresser) la suite
                if n > MEMBRES_MAX:
                    raise LectureGrampsError(f"Paquet refusé : plus de {MEMBRES_MAX} membres.")
                if m.isdir():
                    _membre_sur(m.name.rstrip("/"))
                    continue
                if not m.isreg():
                    genre = "lien symbolique" if m.issym() else "lien physique" if m.islnk() else "fichier spécial"
                    raise LectureGrampsError(f"Paquet refusé : {genre} {m.name!r} (seuls des fichiers réguliers "
                                             "sont admis).")
                nom = _membre_sur(m.name)
                if nom in vus:
                    raise LectureGrampsError(f"Paquet refusé : membre {nom!r} en double.")
                vus.add(nom)
                if m.size > TAILLE_MAX_MEMBRE:
                    raise LectureGrampsError(f"Paquet refusé : {nom!r} dépasse {TAILLE_MAX_MEMBRE // 2**20} Mio.")
                total += m.size
                if total > TAILLE_MAX_PAQUET:
                    raise LectureGrampsError(f"Paquet refusé : contenu total au-delà de "
                                             f"{TAILLE_MAX_PAQUET // 2**30} Gio.")
                if nom == gx.DONNEES_GPKG:
                    donnees = m
                else:
                    fichiers.append(m)
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        raise LectureGrampsError(f"Paquet .gpkg illisible : {exc}") from exc
    if donnees is None:
        raise LectureGrampsError("Paquet .gpkg sans data.gramps : pas un paquet Gramps.")
    return fichiers, donnees


def lire_gpkg(chemin: Path, zone: Path | None) -> Lecture:
    """Paquet Gramps : data.gramps lu en mémoire (borné), médias copiés sous ``zone`` (créée ici, neuve) ; les
    chemins des médias de la base désignent alors leur copie (chemin relatif à ``zone.parent`` préfixé par
    l'appelant). ``zone`` None : lecture seule, rien n'est extrait."""
    fichiers, donnees = inspecter_gpkg(chemin)
    if donnees.size > TAILLE_MAX_XML:
        raise LectureGrampsError(f"data.gramps trop volumineux (plus de {TAILLE_MAX_XML // 2**20} Mio).")
    try:
        return _extraire(chemin, fichiers, donnees, zone)
    except (tarfile.TarError, EOFError, zlib.error) as exc:
        raise LectureGrampsError(f"Paquet .gpkg illisible : {exc}") from exc


def _extraire(chemin: Path, fichiers: list[tarfile.TarInfo], donnees: tarfile.TarInfo, zone: Path | None) -> Lecture:
    with tarfile.open(chemin, "r:*") as tar:
        f = tar.extractfile(donnees)
        lecture = lire_xml(f.read(TAILLE_MAX_XML + 1))
        lecture.format = "gpkg"
        if zone is None or not fichiers:
            lecture.medias = [{"membre": m.name, "taille_octets": m.size, "extrait": False} for m in fichiers]
            return lecture
        zone.mkdir(parents=True, exist_ok=False)  # zone neuve : jamais d'écrasement
        try:
            for m in fichiers:
                cible = zone.joinpath(*PurePosixPath(m.name).parts)
                if not cible.resolve().is_relative_to(zone.resolve()):  # défense en profondeur
                    raise LectureGrampsError(f"Paquet refusé : {m.name!r} sortirait de la zone d'attente.")
                cible.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(m)
                with cible.open("xb") as out:
                    copie = _copier_borne(src, out, m.size)
                if copie != m.size:
                    raise LectureGrampsError(f"Paquet tronqué : {m.name!r}.")
                lecture.medias.append({"membre": m.name, "taille_octets": m.size, "extrait": True})
        except BaseException:
            shutil.rmtree(zone, ignore_errors=True)
            raise
    lecture.zone = zone
    return lecture


def _copier_borne(src: io.BufferedReader, out, taille: int) -> int:
    n = 0
    while chunk := src.read(min(1 << 20, taille + 1 - n)):
        n += len(chunk)
        if n > taille:
            break
        out.write(chunk)
    return n


def relocaliser_medias(db: GrampsDb, membres: set[str], prefixe: str) -> list[str]:
    """Médias de la base dont le chemin désigne un membre extrait : chemin (et attribut Genealogiste-Fichier)
    remplacés par ``prefixe/membre``. Renvoie les médias sans fichier dans le paquet (chemin gardé tel quel)."""
    absents = []
    for m in db.all("Media").values():
        chemin = (m.get("path") or "").lstrip("/")  # Gramps retire le « / » initial des chemins absolus (gpkg)
        if chemin in membres:
            m["path"] = f"{prefixe}/{chemin}"
            for a in m.get("attribute_list") or []:
                if tname(a.get("type")) in (A_FICHIER, "Sosa-Fichier") and a.get("value", "").lstrip("/") == chemin:
                    a["value"] = m["path"]
        elif m.get("path") and "://" not in m["path"]:
            absents.append(f"{m.get('gramps_id') or m['handle']} : {m['path']}")
    return absents


def lire_fichier(chemin: Path, zone: Path | None = None) -> Lecture:
    """Fichier Gramps (format détecté au contenu) -> :class:`Lecture`. Lève :class:`LectureGrampsError`."""
    fmt = detecter(chemin)
    if fmt == "gpkg":
        return lire_gpkg(chemin, zone)
    if fmt != "gramps":
        raise LectureGrampsError("Ni Gramps XML ni paquet .gpkg.")
    taille = chemin.stat().st_size
    if taille > TAILLE_MAX_XML:
        raise LectureGrampsError(f"Fichier trop volumineux (plus de {TAILLE_MAX_XML // 2**20} Mio).")
    return lire_xml(chemin.read_bytes())


# ============================================================================ ce que le modèle ne reprend pas

_SANS_CONTENU = {"_class", "handle", "change", "gramps_id", "sortval", "format", "thumb", "complete",
                 "birth_ref_index", "death_ref_index", "checksum", "familysearch_sync"}


def _vide(v: Any) -> bool:
    return v in (None, "", 0, False, [], {}) or (isinstance(v, dict) and v.get("_class") == "Date"
                                                  and not any((v.get("dateval") or [])[:3]) and not v.get("text")
                                                  and v.get("modifier") != 6)


def compter_contenu(db: GrampsDb, auto: set[str] | None = None) -> dict[str, int]:
    """Valeurs non vides par chemin de champ (``Person.address_list.city``), objets par classe ; attributs
    comptés par type (``Person.attribute_list[Profession]``) ; étiquettes et notes générées par Genealogiste
    (``auto`` : handles d'étiquettes) exclues. Sert à mesurer ce qu'une conversion ne reprend pas."""
    from collections import Counter

    auto = auto or set()
    n: Counter = Counter()

    def visiter(o: Any, chemin: str) -> None:
        if isinstance(o, dict):
            if "_class" in o and o["_class"] in TYPES:  # type Gramps : feuille
                if tname(o):
                    n[chemin] += 1
                return
            if o.get("_class") == "Date":
                if not _vide(o):
                    n[chemin] += 1
                return
            for k, v in o.items():
                if k in _SANS_CONTENU:
                    continue
                if k == "attribute_list" and isinstance(v, list):
                    for a in v:  # attribut : compté par type, puis ce qu'il porte (valeur, citations, notes)
                        p = f"{chemin}.{k}[{tname(a.get('type'))}]"
                        n[p] += 1
                        visiter({x: y for x, y in a.items() if x != "type"}, p)
                    continue
                visiter(v, f"{chemin}.{k}")
        elif isinstance(o, list):
            for x in o:
                if isinstance(x, dict):  # sous-objet : compté, puis ses champs
                    n[chemin + "[]"] += 1
                    visiter(x, chemin)
                elif not _vide(x):  # référence (handle), plage…
                    n[chemin] += 1
        elif not _vide(o):
            n[chemin] += 1

    for cls in ("Tag", "Person", "Family", "Event", "Place", "Citation", "Source", "Repository", "Media", "Note"):
        for h, o in db.all(cls).items():
            if cls == "Tag" and h in auto:
                continue
            if cls == "Note" and auto & set(o.get("tag_list") or []):
                continue
            o = {k: ([t for t in v if t not in auto] if k == "tag_list" else v) for k, v in o.items()}
            n[cls] += 1
            visiter(o, cls)
    return dict(n)


def pertes(source: GrampsDb, apres: GrampsDb, meta: gx.Metadonnees | None = None) -> dict[str, int]:
    """Ce que ``apres`` (la base réécrite depuis l'arbre Genealogiste) ne reprend pas de ``source`` : nombre de
    valeurs en moins, par chemin de champ. Les marqueurs que Genealogiste ajoute ne compensent aucune perte (comptés
    sous leur propre chemin)."""
    from .mapping import auto_tags

    a, b = compter_contenu(source, auto_tags(source)), compter_contenu(apres, auto_tags(apres))
    out = {k: v - b.get(k, 0) for k, v in sorted(a.items()) if v > b.get(k, 0)}
    if meta is not None:
        for nom, v in (("Métadonnées.chercheur", len([x for x in meta.chercheur.values() if x])),
                       ("Métadonnées.mediapath", int(bool(meta.mediapath))),
                       ("Métadonnées.personne_reference", int(bool(meta.personne_reference))),
                       ("Métadonnées.formats_noms", len(meta.formats_noms)),
                       ("Métadonnées.signets", len(meta.signets)),
                       ("Métadonnées.regroupements", len(meta.regroupements))):
            if v:
                out[nom] = v
    return out


# ============================================================================ import dans Genealogiste

_XREF = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,59}$")
_PREFIXES_XREF = {"Person": "I", "Family": "F", "Source": "S", "Repository": "R", "Media": "O", "Note": "N"}


def identifiants_importables(db: GrampsDb) -> list[str]:
    """Les gramps_id deviennent les identifiants (xref) de Genealogiste : un identifiant vide, invalide en xref
    GEDCOM ou en double (Gramps l'admet) reçoit un identifiant libre, signalé ; jamais d'écrasement silencieux."""
    changes = []
    for cls, pre in _PREFIXES_XREF.items():
        objs = sorted(db.all(cls).values(), key=lambda o: (o.get("gramps_id") or "￿", o["handle"]))
        pris = {o.get("gramps_id") for o in objs}
        vus: set[str] = set()
        n = 0
        for o in objs:
            gid = o.get("gramps_id") or ""
            if _XREF.match(gid) and gid not in vus:
                vus.add(gid)
                continue
            motif = "vide" if not gid else "en double" if gid in vus else "invalide"
            while True:
                n += 1
                nouveau = f"{pre}X{n}"
                if nouveau not in pris and nouveau not in vus:
                    break
            vus.add(nouveau)
            changes.append(f"{cls} {gid or o['handle']!r} ({motif}) -> {nouveau}")
            o["gramps_id"] = nouveau
    return changes


def importer(chemin: Path, data_dir: Path, horodatage: str) -> tuple[Any, dict, Path | None]:
    """Prépare l'import d'un fichier Gramps : lecture, médias d'un paquet extraits dans la zone d'attente
    ``<données>/imports/gramps/<nom>-<horodatage>/``, identifiants, conversion par :func:`gramps_to_tree`
    (correspondance unique) et bilan de ce que l'arbre Genealogiste ne reprend pas. Renvoie (arbre, info, zone
    créée ou None). En cas d'erreur, la zone créée est retirée."""
    from ..gedcom.mapping import read_gedcom, write_gedcom
    from .mapping import gramps_to_tree, tree_to_gramps

    base = re.sub(r"[^A-Za-z0-9_.-]+", "-", chemin.stem).strip("-.") or "import"
    racine = data_dir / "imports" / "gramps"
    zone = racine / f"{base[:60]}-{horodatage}"
    i = 1
    while zone.exists():
        i += 1
        zone = racine / f"{base[:60]}-{horodatage}-{i}"
    lecture = lire_fichier(chemin, zone)
    db = lecture.db
    info: dict = {"format": lecture.format, "version_xml": lecture.version_xml,
                  "version_gramps": lecture.version_gramps, "cree_le": lecture.date_creation,
                  "objets_gramps": db.count(), "avertissements": list(lecture.ignores)}
    try:
        if lecture.format == "gpkg":
            extraits = {m["membre"] for m in lecture.medias if m["extrait"]}
            prefixe = zone.relative_to(data_dir).as_posix()
            absents = relocaliser_medias(db, extraits, prefixe) if extraits else []
            info["medias"] = {
                "zone_attente": str(lecture.zone) if lecture.zone else None,
                "fichiers": [f"{prefixe}/{m}" for m in sorted(extraits)],
                "sans_fichier_dans_le_paquet": absents,
                "consigne": ("Médias extraits dans la zone d'attente du répertoire de données ; rien n'est rangé "
                             "dans le vault. Après application de l'import et accord : pieces_proposer(dossier="
                             "<zone_attente>, suivre_medias=true) pour les classer selon la convention (plan, "
                             "pieces_appliquer, puis la proposition modifier_media qui suit)."
                             if extraits else "Aucun fichier de média dans le paquet."),
            }
        else:
            chemins = sorted(m["path"] for m in db.all("Media").values() if m.get("path"))
            info["medias"] = {"chemins_repris": len(chemins),
                              "consigne": "Chemins des médias repris tels quels, fichiers non copiés (relatifs au "
                                          "dossier des médias de Gramps : « mediapath »)."}
        reattribues = identifiants_importables(db)
        if reattribues:
            info["identifiants_reattribues"] = reattribues[:50] + (
                [f"… {len(reattribues) - 50} autre(s)"] if len(reattribues) > 50 else [])
        tree = gramps_to_tree(db)[0]
        relu = read_gedcom(write_gedcom(tree))[0]  # ce qui sera réellement écrit (arbre.ged ou Gramps Web)
        info["non_repris"] = pertes(db, tree_to_gramps(relu, generated=False), lecture.meta)
    except BaseException:
        if lecture.zone is not None:
            shutil.rmtree(lecture.zone, ignore_errors=True)
        raise
    info.update(personnes=len(tree.personnes), familles=len(tree.familles), sources=len(tree.sources))
    return tree, info, lecture.zone
