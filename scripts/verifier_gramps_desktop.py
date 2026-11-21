"""Compatibilité Gramps Desktop sans interface : export Gramps XML de Genealogiste lu par Gramps 5.2, 6.0, 6.1.

Pour chaque version déclarée dans `compatibilite-gramps.json` (`gramps_desktop`), un environnement Python isolé
est créé dans un cache (jamais dans `mcp/.venv` ni `uv.lock`) : `gramps` depuis PyPI, ou depuis les sources
Git épinglées par commit (6.1, absente de PyPI). Les arbres synthétiques du dépôt (`mcp/tests/fixtures/*.ged`)
sont exportés sous chaque forme de `CAS` (Gramps XML 1.7.1 et 1.7.2, `.gramps` gzip, paquet `.gpkg` avec
médias), puis la sonde `sonde_gramps_desktop.py`, lancée dans l'environnement isolé, les importe et les
réexporte. Invariants vérifiés pour chaque cas et chaque version :

- fichier valide au DTD et au RNG livrés avec la bibliothèque (`data/grampsxml.dtd`, `.rng`), étiquette du
  fichier ramenée à celle du schéma : le contenu écrit sous l'étiquette 1.7.1 suit déjà 1.7.2, comme celui de
  Gramps 5.2 (le schéma 1.7.1 strict est vérifié par les tests unitaires) ;
- refus par les versions de `refus_attendu` (1.7.2 dans Gramps 5.2) ;
- import sans erreur ni avertissement de Gramps (sauf ceux que le cas admet : chemin de base des médias d'un
  `.gpkg`) ;
- médias : chaque fichier empaqueté est retrouvé par Gramps après import ;
- mêmes objets que l'export, classe par classe (personnes, familles, événements, sources, citations, lieux,
  notes, dépôts, médias, étiquettes) : mêmes nombres et mêmes handles ;
- réexport par Gramps (aller-retour) : mêmes nombres et mêmes handles.

Points d'extension : ajouter un `Cas` à `CAS` (autre forme de fichier ; `refus_attendu` pour une version qui
doit refuser le fichier), et un contrôle à `CONTROLES` (ex. relire le réexport de Gramps avec l'import
Genealogiste, #269).

Usage (depuis la racine) : make test-gramps-desktop [GRAMPS_DESKTOP=6.0] [GI=systeme] [PYTHON=/usr/bin/python3]
"""

from __future__ import annotations

import argparse
import copy
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRICE = ROOT / "compatibilite-gramps.json"
SONDE = ROOT / "scripts" / "sonde_gramps_desktop.py"
FIXTURES = ROOT / "mcp" / "tests" / "fixtures"
ARBRES = ("famille.ged", "legacy551.ged", "geneweb7_gwb2ged.ged")
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "genealogiste" / "gramps-desktop"

# élément Gramps XML d'un objet primaire -> classe Gramps
ELEMENTS = {"person": "Person", "family": "Family", "event": "Event", "source": "Source", "citation": "Citation",
            "placeobj": "Place", "note": "Note", "repository": "Repository", "object": "Media", "tag": "Tag"}
CLASSES = tuple(ELEMENTS.values())


def charger_matrice(chemin: Path = MATRICE) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))


def handle_gramps(attribut: str) -> str:
    """Handle tel que Gramps le stocke : l'importeur XML retire tous les « _ » (`importxml.inaugurate`)."""
    return attribut.replace("_", "")


def lire_xml(chemin: Path) -> bytes:
    """Contenu XML d'un fichier remis à Gramps : `.gramps` (gzip ou non) ou `data.gramps` d'un paquet `.gpkg`
    (reconnu au contenu : le réexport de Gramps garde le nom du fichier importé)."""
    brut = chemin.read_bytes()
    if brut[:2] == b"\x1f\x8b":
        brut = gzip.decompress(brut)
    if tarfile.is_tarfile(io.BytesIO(brut)):
        with tarfile.open(fileobj=io.BytesIO(brut)) as tar:
            brut = tar.extractfile("data.gramps").read()
        brut = gzip.decompress(brut) if brut[:2] == b"\x1f\x8b" else brut
    return brut


def valider_schemas(brut: bytes, schemas: dict[str, str]) -> list[str]:
    """Validation DTD puis RNG contre les schémas d'une bibliothèque Gramps, l'étiquette du fichier (espace de
    noms) ramenée à celle du schéma. lxml : groupe dev de mcp/."""
    from lxml import etree

    dtd_brut = Path(schemas["dtd"]).read_bytes()
    cible = re.search(rb'xmlns CDATA #FIXED "(http://gramps-project.org/xml/[0-9.]+/)"', dtd_brut).group(1)
    brut = re.sub(rb'xmlns="http://gramps-project.org/xml/[0-9.]+/"', b'xmlns="' + cible + b'"', brut, count=1)
    doc = etree.fromstring(brut, etree.XMLParser(load_dtd=False, resolve_entities=False, no_network=True))
    ecarts = []
    dtd = etree.DTD(io.BytesIO(dtd_brut))
    if not dtd.validate(doc):
        ecarts += [f"DTD {cible.decode()} l.{e.line} : {e.message}" for e in list(dtd.error_log)[:5]]
    rng = etree.RelaxNG(etree.parse(schemas["rng"]))
    if not rng.validate(doc):
        ecarts += [f"RNG l.{e.line} : {e.message}" for e in list(rng.error_log)[:3]]
    return ecarts


def inventaire_xml(chemin: Path) -> dict[str, list[str]]:
    """Handles des objets primaires d'un fichier Gramps XML (gzip ou non, ou paquet .gpkg), par classe Gramps."""
    racine = ET.fromstring(lire_xml(chemin))
    trouves: dict[str, list[str]] = {cls: [] for cls in CLASSES}
    for section in racine:
        for objet in section:
            nom = objet.tag.rsplit("}", 1)[-1]
            if nom in ELEMENTS and "handle" in objet.attrib:
                trouves[ELEMENTS[nom]].append(handle_gramps(objet.attrib["handle"]))
    return {cls: sorted(h) for cls, h in trouves.items()}


def comparer(attendu: dict[str, list[str]], obtenu: dict[str, list[str]], contexte: str) -> list[str]:
    ecarts = []
    for cls in CLASSES:
        a, o = set(attendu.get(cls, [])), set(obtenu.get(cls, []))
        if len(attendu.get(cls, [])) != len(obtenu.get(cls, [])) or a != o:
            ecarts.append(f"{contexte} : {cls} attendu {len(a)}, obtenu {len(o)} "
                          f"(manquants {sorted(a - o)[:3]}, en trop {sorted(o - a)[:3]})")
    return ecarts


# --- cas : forme du fichier remis à Gramps ---------------------------------------------------------------

@dataclass(frozen=True)
class Cas:
    nom: str
    description: str
    produire: Callable[[object, Path], Path]  # (Tree, dossier) -> fichier écrit
    refus_attendu: frozenset[str] = field(default_factory=frozenset)  # versions Gramps qui doivent refuser
    enrichir: Callable[[object, Path], object] | None = None  # (Tree, dossier) -> arbre exporté (copie)
    avertissements_admis: tuple[str, ...] = ()  # débuts d'avertissements Gramps attendus pour ce cas
    arbres: tuple[str, ...] = ()  # arbres du dépôt auxquels le cas s'applique (défaut : tous)
    # écart au schéma de la bibliothèque admis pour ce cas, par version : (motif, remplacement) appliqués au fichier
    # avant validation, tout le reste étant validé strictement
    schema_admis: dict[str, tuple[tuple[bytes, bytes], ...]] = field(default_factory=dict)
    # retouche de la base Gramps exportée (objets attendus compris) : ce qu'une base Gramps Web contient et que le
    # modèle n'écrit pas (types personnalisés saisis en français, #273)
    retoucher: Callable[[object], None] | None = None


def produire_xml(version_xml: str, compresse: bool = False) -> Callable[[object, Path], Path]:
    def produire(tree, dossier: Path) -> Path:
        from genealogiste_mcp.export.gramps_xml import compresser, to_gramps_xml

        chemin = dossier / "genealogiste.gramps"
        xml = to_gramps_xml(tree, version_xml=version_xml)
        if compresse:
            chemin.write_bytes(compresser(xml))
        else:
            chemin.write_text(xml, encoding="utf-8")
        return chemin
    return produire


MEDIA_TEST = "medias/acte de décès é.jpg"


def avec_media(tree, dossier: Path):
    """Copie de l'arbre avec un média local (nom accentué, sous-dossier) rattaché à la première personne."""
    from genealogiste_mcp.models import Media

    tree = copy.deepcopy(tree)
    (dossier / "racine" / "medias").mkdir(parents=True)
    (dossier / "racine" / MEDIA_TEST).write_bytes(b"\xff\xd8\xff\xe0 image fictive")
    mid = "O" + str(len(tree.medias) + 900)
    tree.medias[mid] = Media(id=mid, fichier=MEDIA_TEST, titre="Acte fictif")
    tree.personnes[sorted(tree.personnes)[0]].medias.append(mid)
    return tree


def produire_gpkg(tree, dossier: Path) -> Path:
    from genealogiste_mcp.export.gramps_xml import paquet_gpkg
    from genealogiste_mcp.gramps.mapping import tree_to_gramps_stats

    db, _ = tree_to_gramps_stats(tree, None, False)
    brut, bilan = paquet_gpkg(db, (dossier / "racine",))
    if bilan["manquants"]:
        raise SystemExit(f"paquet incomplet : {bilan['manquants']}")
    chemin = dossier / "genealogiste.gpkg"
    chemin.write_bytes(brut)
    return chemin


TESTS = ROOT / "mcp" / "tests"


def inventaire_dates() -> list[tuple[str, dict]]:
    """Inventaire des formes de date Gramps (#272, mcp/tests/dates_gramps.py)."""
    sys.path.insert(0, str(TESTS))
    try:
        import dates_gramps
    finally:
        sys.path.remove(str(TESTS))
    return dates_gramps.inventaire()


def avec_dates(tree, dossier: Path):
    """Copie de l'arbre avec une personne fictive portant un événement par forme de date de l'inventaire #272
    écrite en Gramps XML (les dates vides porteuses d'un attribut, que Gramps XML n'écrit pas, en sont exclues) :
    date du modèle = ``date_from_gramps`` de la forme ; l'export la reconvertit par ``date_to_gramps``."""
    from genealogiste_mcp.export.gramps_xml import date_xml
    from genealogiste_mcp.gramps.types import date_from_gramps
    from genealogiste_mcp.models import Event, Name, Person

    tree = copy.deepcopy(tree)
    p = Person(id="IDATES272", noms=[Name(prenoms="Formes", nom="DATES")], uid="personne-dates-272")
    for nom, d in inventaire_dates():
        if date_xml(d):
            p.evenements.append(Event(type="EVEN", type_detail=f"Forme {nom}", date=date_from_gramps(d),
                                      uid=f"forme-{nom}"))
    tree.personnes[p.id] = p
    return tree


# --- types (#273) : rôles ajoutés par Gramps 6.0 et types personnalisés saisis en français ----------------

ROLES_TYPES = ("FATH", "MOTH", "PARENT", "CHIL", "MULTIPLE", "FRIEND", "NGHBR", "OFFICIATOR", "WITN", "GODP")
ROLES_60 = ("Father", "Mother", "Parent", "Child", "Multiple birth", "Friend", "Neighbor", "Officiator")
TYPES_FRANCAIS = (("EventType", "Baptême"), ("EventType", "Recensement"), ("EventRoleType", "Témoin"),
                  ("AttributeType", "Âge"), ("PlaceType", "Paroisse"))


def avec_types(tree, dossier: Path):
    """Copie de l'arbre avec une personne fictive dont le baptême a dix intervenants de l'arbre, un par rôle du
    modèle ayant un type standard (les huit de Gramps 6.0, témoin, parrain), et un recensement."""
    from genealogiste_mcp.models import Association, Event, Name, Person

    tree = copy.deepcopy(tree)
    p = Person(id="ITYPES273", noms=[Name(prenoms="Types", nom="ROLES")], uid="personne-types-273")
    p.evenements = [Event(type="BAPM", uid="bapteme-types-273", associations=[
        Association(personne=f"ITYPES273R{i}", role=r) for i, r in enumerate(ROLES_TYPES)]),
        Event(type="CENS", uid="recensement-types-273")]
    tree.personnes[p.id] = p
    for i, r in enumerate(ROLES_TYPES):
        tree.personnes[f"ITYPES273R{i}"] = Person(id=f"ITYPES273R{i}", noms=[Name(prenoms=f"Intervenant {r}",
                                                                                 nom="ROLES")], uid=f"role-273-{i}")
    return tree


def types_francais(db) -> None:
    """Types personnalisés en français, comme dans une base Gramps Web saisie par un francophone : baptême
    « Baptême » (attribut de référence « Âge ») dans une paroisse « Paroisse », recensement « Recensement », témoin
    « Témoin » (rôle personnalisé)."""
    from genealogiste_mcp.gramps.types import TYPES, attribute, blank, tname

    def perso(cls: str, s: str) -> dict:
        return {"_class": cls, "value": TYPES[cls][0], "string": s}
    lieu = blank("Place", "lieutypes273", "PTYPES273")
    lieu.update(title="Saint-Exemple", place_type=perso("PlaceType", "Paroisse"))
    lieu["name"]["value"] = "Saint-Exemple"
    db.put(lieu)
    p = next(o for o in db.all("Person").values() if o["gramps_id"] == "ITYPES273")
    for r in p["event_ref_list"]:
        ev = db.get("Event", r["ref"])
        if tname(ev["type"]) == "Baptism":
            ev.update(type=perso("EventType", "Baptême"), place="lieutypes273")
            r["attribute_list"].append({**attribute("Age", "2 jours"), "type": perso("AttributeType", "Âge")})
        elif tname(ev["type"]) == "Census":
            ev["type"] = perso("EventType", "Recensement")
    for o in db.all("Person").values():
        for r in o["event_ref_list"]:
            if o["gramps_id"].startswith("ITYPES273R") and tname(r["role"]) == "Witness":
                r["role"] = perso("EventRoleType", "Témoin")


def produire_types(tree, dossier: Path) -> Path:
    from genealogiste_mcp.export.gramps_xml import db_to_xml
    from genealogiste_mcp.gramps.mapping import tree_to_gramps_stats

    db, _ = tree_to_gramps_stats(tree, None, False)
    types_francais(db)
    chemin = dossier / "genealogiste.gramps"
    chemin.write_text(db_to_xml(db, "1.7.1"), encoding="utf-8")
    return chemin


# --- lieux datés (#277) : nom d'époque à la date de l'événement (PlaceDisplay.display_event) ----------------

# (lieu, année de l'événement) -> nom affiché attendu, d'après la règle amont (get_location_list) et les dates
# posées par dater_lieux depuis l'extrait COG des tests (mcp/tests/fixtures/cog)
LIEUX_AFFICHES = {
    ("Charleville-Mézières", 1950): "Charleville, Ardennes, France",
    ("Charleville-Mézières", 1980): "Charleville-Mézières, Ardennes, France",
    ("Charleville-Mézières", 2020): "Charleville-Mézières, Ardennes, France",
    ("Boulogne-Billancourt", 1950): "Boulogne-Billancourt, Seine, France",
    ("Boulogne-Billancourt", 1980): "Boulogne-Billancourt, Hauts-de-Seine, France",
    ("Meythet", 1980): "Meythet, Haute-Savoie, France",
    ("Meythet", 2020): "Meythet, Annecy, Haute-Savoie, France",
    ("Valserhône", 1950): "Bellegarde, Ain, France",
    ("Valserhône", 1980): "Bellegarde-sur-Valserine, Ain, France",
    ("Valserhône", 2020): "Valserhône, Ain, France",
    ("Mézières", 1950): "Mézières, Ardennes, France",
    ("Rochefort", 1950): "Rochefort, Charente-Maritime, France",
}


def _module_test(nom: str):
    sys.path.insert(0, str(TESTS))
    try:
        return __import__(nom)
    finally:
        sys.path.remove(str(TESTS))


def avec_lieux(tree, dossier: Path):
    """Copie de l'arbre avec une personne fictive : un événement en 1950, 1980 et 2020 dans chaque commune de
    test_gramps_lieux_dates (fusion, commune nouvelle, changement de département, commune déléguée)."""
    return _module_test("test_gramps_lieux_dates").arbre_lieux(tree)


def dater(db) -> None:
    """Noms et rattachements datés par dater_lieux, chronologies de l'extrait COG des tests (sans réseau)."""
    from genealogiste_mcp.gramps.mapping import dater_lieux, est_commune
    from genealogiste_mcp.sources.geo import IndexCog

    t = _module_test("test_gramps_lieux_dates")
    index = IndexCog(t.lire("communes.csv"), t.lire("mouvements.csv"))
    items, _ = dater_lieux(db, {p["code"]: index.chronologie(p["code"]) for p in db.all("Place").values()
                                if est_commune(p)})
    for it in items:
        db.put(it["new"])


def produire_lieux(tree, dossier: Path) -> Path:
    from genealogiste_mcp.export.gramps_xml import db_to_xml
    from genealogiste_mcp.gramps.mapping import tree_to_gramps_stats

    db, _ = tree_to_gramps_stats(tree, None, False)
    dater(db)
    chemin = dossier / "genealogiste.gramps"
    chemin.write_text(db_to_xml(db, "1.7.1"), encoding="utf-8")
    return chemin


def controle_lieux(cas: Cas, version: str, attendu: dict, rapport: dict) -> list[str]:
    """#277 : nom affiché par la bibliothèque (PlaceDisplay.display_event, et nom du lieu seul par
    get_location_list) à la date de chaque événement de la personne de test : nom d'époque avant le changement,
    nom actuel après ; noms et rattachements datés relus par Genealogiste depuis le réexport sans changer le nom
    relu."""
    if cas.nom != "lieux":
        return []
    objets = attendu[MODELE]
    lieux = {o["handle"]: o["name"]["value"] for o in objets if o["_class"] == "Place"}
    vus = rapport.get("lieux_affiches") or {}
    ecarts, n = [], 0
    for o in objets:
        if o["_class"] != "Event" or not o.get("place"):
            continue
        cle = (lieux.get(o["place"]), o["date"]["dateval"][2])
        if cle not in LIEUX_AFFICHES:
            continue
        n += 1
        obtenu = vus.get(handle_gramps(o["handle"]))
        if obtenu is None or obtenu[0] != LIEUX_AFFICHES[cle] or obtenu[1] != LIEUX_AFFICHES[cle].split(", ")[0]:
            ecarts.append(f"lieu {cle[0]} en {cle[1]} : affiché {obtenu}, attendu {LIEUX_AFFICHES[cle]!r}")
    if n != len(LIEUX_AFFICHES):
        ecarts.append(f"{n} événements contrôlés sur {len(LIEUX_AFFICHES)}")
    print(f"   {version} : {n} événements, nom de lieu affiché par PlaceDisplay.display_event à la date de "
          f"l'événement : {n - len(ecarts)} conformes (ex. Charleville-Mézières 1950 -> "
          f"{next((v[0] for h, v in vus.items() if v[0].startswith('Charleville,')), '?')!r})", flush=True)
    if "reexport" in rapport:
        from genealogiste_mcp.gramps.lecture_xml import lire_xml
        from genealogiste_mcp.gramps.mapping import GrampsDb, gramps_to_tree

        relu = lire_xml(Path(rapport["reexport"]).read_bytes()).db
        ch = next((p for p in relu.all("Place").values() if p["name"]["value"] == "Charleville-Mézières"), None)
        if ch is None or [a["value"] for a in ch["alt_names"]] != ["Charleville"]:
            ecarts.append("noms datés de Charleville-Mézières absents du réexport de Gramps")
        def noms(db) -> list:
            t = gramps_to_tree(db)[0]
            return sorted((e.uid, e.lieu.nom) for p in t.personnes.values() for e in p.evenements if e.lieu)
        if noms(relu) != noms(GrampsDb.from_objects(objets)):
            ecarts.append("nom de lieu relu par Genealogiste changé après réexport par Gramps")
    return ecarts


# DTD et RNG de Gramps 5.2 et 6.0 : dateval type sans from/to (ajoutés par 6.1), que leur code lit et écrit pourtant
# (MOD_FROM / MOD_TO depuis 5.2) ; validés comme « about », seul écart admis
# --- notes stylées et liens internes (#279) ----------------------------------------------------------------

TEXTE_STYLE = "Gras italique souligné Serif 14 rouge surligné x² H₂O barré lien personne famille 🟡 é⚠️ fin"
NOTE_STYLEE = "notestylee279"
# styles absents du DTD et du RNG livrés (5.2 à 6.1) mais écrits et relus par Gramps (StyledTextTagType) : seul écart
# admis à la validation, ramené à « bold » avant validation
STYLES_HORS_SCHEMA = ((rb'<style name="(?:strikethrough|subscript)"', b'<style name="bold"'),)


def notes_stylees(db) -> None:
    """Notes de preuve recalculées avec liens internes (GENEALOGISTE_GRAMPS_NOTES_LIENS) et une note manuelle de
    personne portant les onze styles de Gramps, dont deux liens internes (personne, famille) et un lien externe."""
    from genealogiste_mcp.gramps.mapping import gramps_to_tree, tree_to_gramps
    from genealogiste_mcp.gramps.texte import tag
    from genealogiste_mcp.gramps.types import blank, gtype

    lie = tree_to_gramps(gramps_to_tree(db)[0], base=db, liens=True, recalcul=True)
    for n in lie.all("Note").values():
        db.put(n)
    jean = next(o for o in db.all("Person").values() if o["gramps_id"] == "I1")
    fam = next(iter(sorted(db.all("Family"))))

    def r(mot):
        i = TEXTE_STYLE.index(mot)
        return [[i, i + len(mot)]]
    n = blank("Note", NOTE_STYLEE, "N279")
    n["type"] = gtype("NoteType", "Person Note")
    n["text"] = {"_class": "StyledText", "string": TEXTE_STYLE, "tags": [
        tag("bold", r("Gras") + r("🟡 é⚠️")), tag("italic", r("italique")), tag("underline", r("souligné")),
        tag("fontface", r("Serif"), "Serif"), tag("fontsize", r("14"), 14), tag("fontcolor", r("rouge"), "#ff0000"),
        tag("highlight", r("surligné"), "#ffff00"), tag("superscript", r("²")), tag("subscript", r("₂")),
        tag("strikethrough", r("barré")), tag("link", r("lien"), "https://exemple.org/page_(a)"),
        tag("link", r("personne"), f"gramps://Person/handle/{jean['handle']}"),
        tag("link", r("famille"), f"gramps://Family/handle/{fam}")]}
    db.put(n)
    jean["note_list"].append(NOTE_STYLEE)


def produire_notes(tree, dossier: Path) -> Path:
    from genealogiste_mcp.export.gramps_xml import db_to_xml
    from genealogiste_mcp.gramps.mapping import tree_to_gramps_stats

    db, _ = tree_to_gramps_stats(tree, None, False)
    notes_stylees(db)
    chemin = dossier / "genealogiste.gramps"
    chemin.write_text(db_to_xml(db, "1.7.1"), encoding="utf-8")
    return chemin


def styles_xml(chemin: Path) -> dict[str, list[tuple]]:
    """Styles de chaque note d'un fichier Gramps XML : handle -> [(nom, valeur, début, fin)] triés, et texte."""
    racine = ET.fromstring(lire_xml(chemin))
    out = {}
    for note in racine.iter():
        if note.tag.rsplit("}", 1)[-1] != "note" or "handle" not in note.attrib:
            continue
        texte = next((c.text or "" for c in note if c.tag.rsplit("}", 1)[-1] == "text"), "")
        styles = sorted((s.attrib["name"], s.attrib.get("value"), int(g.attrib["start"]), int(g.attrib["end"]))
                        for s in note if s.tag.rsplit("}", 1)[-1] == "style" for g in s)
        out[handle_gramps(note.attrib["handle"])] = (texte, styles)
    return out


def controle_notes(cas: Cas, version: str, attendu: dict, rapport: dict) -> list[str]:
    """#279 : réexport de Gramps : chaque note garde texte et styles (onze noms, valeurs, plages en points de code),
    chaque lien interne gramps:// vise un objet présent sous le même handle."""
    if cas.nom != "notes":
        return []
    if "reexport" not in rapport:
        return ["réexport absent"]
    from genealogiste_mcp.gramps.texte import cible_interne

    relus = styles_xml(Path(rapport["reexport"]))
    handles = {cls: set(hs) for cls, hs in inventaire_xml(Path(rapport["reexport"])).items()}
    ecarts, liens, noms = [], 0, set()
    for o in attendu[MODELE]:
        if o["_class"] != "Note":
            continue
        h = handle_gramps(o["handle"])
        voulu = (o["text"]["string"], sorted((tname_xml(t["name"]), None if t["value"] is None else str(t["value"]), a, b)
                                             for t in o["text"]["tags"] for a, b in t["ranges"]))
        if relus.get(h) != voulu:
            ecarts.append(f"note {h} : attendu {voulu}, relu {relus.get(h)}")
            continue
        for nom, valeur, _, _ in voulu[1]:
            noms.add(nom)
            c = cible_interne(valeur)
            if c:
                liens += 1
                if handle_gramps(c[2]) not in handles.get(c[0], set()):
                    ecarts.append(f"note {h} : lien {valeur} vers un objet absent")
    print(f"   {version} : {liens} liens internes résolus, styles relus : {', '.join(sorted(noms))}", flush=True)
    if len(noms) != 11:
        ecarts.append(f"styles relus {sorted(noms)} : onze attendus")
    return ecarts[:10]


def tname_xml(t) -> str:
    from genealogiste_mcp.gramps.types import tname
    return tname(t)


RACINE_REFERENCE = "I3"  # racine Sosa du cas « reference » (famille.ged)
HANDLE_REFERENCE: dict[str, str] = {}  # handle écrit dans `home` (Gramps complète « I3 » par des zéros : I0003, I00003)


def produire_reference(tree, dossier: Path) -> Path:
    """Export réel avec racine Sosa : le même chemin que arbre_exporter (personne_reference puis db_to_xml)."""
    from genealogiste_mcp.export.gramps_xml import Metadonnees, db_to_xml, personne_reference
    from genealogiste_mcp.gramps.mapping import tree_to_gramps_stats

    db, _ = tree_to_gramps_stats(tree, None, False)
    handle, motif = personne_reference(db, RACINE_REFERENCE)
    if not handle:
        raise SystemExit(f"racine {RACINE_REFERENCE} absente de l'export : {motif}")
    HANDLE_REFERENCE[RACINE_REFERENCE] = handle
    chemin = dossier / "genealogiste.gramps"
    chemin.write_text(db_to_xml(db, "1.7.1", Metadonnees(personne_reference=handle)), encoding="utf-8")
    return chemin


def controle_reference(cas: Cas, version: str, attendu: dict, rapport: dict) -> list[str]:
    """#274 : la personne de référence appliquée par l'import de Gramps (``db.get_default_person()``) est celle du
    fichier exporté avec racine Sosa ; sans racine, rien n'est inventé ; le réexport de Gramps garde ``home``."""
    ref = rapport.get("personne_reference")
    if cas.nom != "reference":
        return [f"personne de référence {ref['gramps_id']} inventée par l'export sans racine"] if ref else []
    if not ref:
        return ["aucune personne de référence après l'import d'un fichier portant <people home>"]
    # le handle est la preuve ; le gramps_id n'est qu'une écriture du même numéro (zéros ajoutés par Gramps)
    ecarts = [] if ref["handle"] == HANDLE_REFERENCE.get(RACINE_REFERENCE) else [
        f"personne de référence {ref['handle']} au lieu de {HANDLE_REFERENCE.get(RACINE_REFERENCE)}"]
    if int(ref["gramps_id"][1:] or -1) != int(RACINE_REFERENCE[1:]) or ref["gramps_id"][0] != RACINE_REFERENCE[0]:
        ecarts.append(f"identifiant {ref['gramps_id']} : autre numéro que {RACINE_REFERENCE}")
    if ref["handle"] not in rapport["handles"]["Person"]:
        ecarts.append("personne de référence hors des personnes importées")
    if "reexport" in rapport:
        m = re.search(rb'<people[^>]* home="_?([^"]+)"', lire_xml(Path(rapport["reexport"])))
        if not m or m[1].decode() != ref["handle"]:
            ecarts.append(f"réexport de Gramps : home {m and m[1].decode()!r} au lieu de {ref['handle']!r}")
    print(f"   {version} : personne de référence {ref['gramps_id']} (racine Sosa {RACINE_REFERENCE}), "
          f"handle {ref['handle']}", flush=True)
    return ecarts


FROM_TO_HORS_SCHEMA = ((rb'(<dateval [^>]*type=")(?:from|to)"', rb'\1about"'),)

CAS: list[Cas] = [
    Cas("xml-1.7.1", "Gramps XML 1.7.1 non compressé (défaut d'arbre_exporter, format gramps)", produire_xml("1.7.1")),
    Cas("xml-1.7.2", "Gramps XML 1.7.2 non compressé (version_xml=1.7.2) : refusé par Gramps 5.2",
        produire_xml("1.7.2"), refus_attendu=frozenset({"5.2"})),
    Cas("gramps-gzip", "Gramps XML 1.7.1 compressé gzip (compresse=True)", produire_xml("1.7.1", True)),
    Cas("gpkg", "paquet .gpkg : data.gramps (1.7.1, gzip) + un média local", produire_gpkg, enrichir=avec_media,
        avertissements_admis=("Base path for relative media set",)),
    Cas("dates", "Gramps XML 1.7.1 : un événement par forme de date de l'inventaire #272 (mcp/tests/dates_gramps.py)",
        produire_xml("1.7.1"), enrichir=avec_dates, arbres=("famille.ged",),
        schema_admis={"5.2": FROM_TO_HORS_SCHEMA, "6.0": FROM_TO_HORS_SCHEMA}),
    Cas("types", "Gramps XML 1.7.1 : les huit rôles d'événement de Gramps 6.0 (lus comme personnalisés par 5.2) et "
        "des types personnalisés saisis en français (#273)", produire_types, enrichir=avec_types,
        arbres=("famille.ged",), retoucher=types_francais),
    Cas("lieux", "Gramps XML 1.7.1 : noms et rattachements datés des communes (#277) ; nom d'époque affiché à la "
        "date de l'événement", produire_lieux, enrichir=avec_lieux, arbres=("famille.ged",), retoucher=dater),
    Cas("reference", "Gramps XML 1.7.1 exporté avec la racine Sosa I3 : <people home> appliqué par l'import (#274)",
        produire_reference, arbres=("famille.ged",)),
    Cas("notes", "Gramps XML 1.7.1 : notes de preuve avec liens internes et note manuelle aux onze styles (#279)",
        produire_notes, arbres=("famille.ged",), retoucher=notes_stylees,
        schema_admis={v: STYLES_HORS_SCHEMA for v in ("5.2", "6.0", "6.1")}),
]


@dataclass
class Resultat:
    version: str
    arbre: str
    cas: str
    ok: bool
    detail: str
    nombres: dict[str, int] = field(default_factory=dict)


# Contrôle supplémentaire sur un fichier importé : (cas, version, attendu, rapport de la sonde) -> écarts.
Controle = Callable[[Cas, str, dict[str, list[str]], dict], list[str]]


def controle_reexport(cas: Cas, version: str, attendu: dict[str, list[str]], rapport: dict) -> list[str]:
    if "reexport" not in rapport:
        return ["réexport absent"]
    return comparer(attendu, inventaire_xml(Path(rapport["reexport"])), "réexport Gramps")


def controle_medias(cas: Cas, version: str, attendu: dict[str, list[str]], rapport: dict) -> list[str]:
    """Médias d'un paquet : chaque fichier empaqueté est retrouvé par Gramps à son chemin relatif."""
    if cas.enrichir is not avec_media:
        return []
    trouves = {m["chemin"] for m in rapport.get("medias", []) if m["fichier"]}
    return [] if MEDIA_TEST in trouves else [f"média {MEDIA_TEST} introuvable après import : {rapport.get('medias')}"]


MODELE = "_objets"  # clé de `attendu` : objets Gramps JSON du modèle exporté (comparés champ par champ)

# Écarts propres à Gramps, sans perte de contenu exporté : identifiants renumérotés selon les préférences de
# l'arbre cible (I7 -> I0007), date de modification 0 remplacée par celle du fichier, champs calculés à l'import
# (somme de contrôle, valeur de tri, texte d'une date non textuelle), champs JSON hors XML ou propres à une
# version (vignette, complete, familysearch_sync de 6.1).
IGNORES = {"gramps_id", "thumb", "complete", "familysearch_sync", "sortval"}


def _normaliser(o, cls: str = ""):
    if isinstance(o, dict):
        c = o.get("_class", cls)
        out = {}
        for k, v in o.items():
            if k in IGNORES or (c == "Date" and k == "format") or (c == "Date" and k == "text"
                                                                  and o.get("modifier") != 6):
                continue
            out[k] = _normaliser(v, c)
        return out
    if isinstance(o, (list, tuple)):
        return [_normaliser(x, cls) for x in o]
    return o


def _ecarts(a, b, chemin: str):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:  # clés de l'objet exporté ; celles que Gramps ajoute sont sans objet
            if k not in b:
                yield f"{chemin}.{k} absent après import"
            elif not (k in ("change", "checksum") and not a[k]):
                yield from _ecarts(a[k], b[k], f"{chemin}.{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            yield from _ecarts(x, y, f"{chemin}[{i}]")
    elif a != b:
        yield f"{chemin} : exporté {a!r}, importé {b!r}"


def controle_champs(cas: Cas, version: str, attendu: dict, rapport: dict) -> list[str]:
    """Gramps ≥ 6.0 : chaque objet importé est identique, champ par champ, à l'objet Gramps exporté."""
    if "objets" not in rapport:
        return []  # Gramps 5.2 : pas de format JSON
    importes = {o["handle"]: o for o in rapport["objets"]}
    ecarts = []
    for o in attendu.get(MODELE, []):
        h = handle_gramps(o["handle"])
        if o["_class"] == "Event" and o.get("date"):  # écarts connus de Gramps sur les dates (#272)
            o = {**o, "date": date_attendue(o["date"], version, ("import",))}
        if h in importes:
            ecarts += list(_ecarts(_normaliser({**o, "handle": h}), _normaliser(importes[h]), f"{o['_class']}:{h}"))
    return ecarts[:10]


# --- environnements isolés ------------------------------------------------------------------------------

def _run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True, **kw)


def environnement(entree: dict, cache: Path, python: str, gi_systeme: bool) -> tuple[Path, dict[str, str]]:
    """Crée (ou réutilise) l'environnement d'une version ; renvoie l'interpréteur et les variables à ajouter."""
    version = entree["version"]
    dossier = cache / f"gramps-{version}"
    venv = dossier / "venv"
    exe = venv / "bin" / "python"
    signature = json.dumps({"entree": entree, "python": python, "gi_systeme": gi_systeme}, sort_keys=True)
    marqueur = dossier / "installe.json"
    if not (marqueur.exists() and marqueur.read_text(encoding="utf-8") == signature and exe.exists()):
        shutil.rmtree(dossier, ignore_errors=True)
        dossier.mkdir(parents=True)
        _run(["uv", "venv", "--quiet", "--python", python, *(["--system-site-packages"] if gi_systeme else []),
              str(venv)])
        if "pypi" in entree:
            _run(["uv", "pip", "install", "--quiet", "--python", str(exe), entree["pypi"]])
        else:
            depot = entree["git"]
            src = dossier / "src"
            _run(["git", "init", "--quiet", str(src)])
            _run(["git", "-C", str(src), "fetch", "--quiet", "--depth", "1", depot["depot"], depot["commit"]])
            _run(["git", "-C", str(src), "-c", "advice.detachedHead=false", "checkout", "--quiet", "FETCH_HEAD"])
            tete = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], check=True, capture_output=True,
                                  text=True).stdout.strip()
            if tete != depot["commit"]:
                raise SystemExit(f"Gramps {version} : commit {tete} au lieu de {depot['commit']}")
            if entree.get("dependances"):
                _run(["uv", "pip", "install", "--quiet", "--python", str(exe), *entree["dependances"]])
            # lancement depuis les sources sans compilation des traductions (msgfmt) : ressources = data/
            (dossier / "share").mkdir()
            (dossier / "share" / "gramps").symlink_to(src / "data", target_is_directory=True)
        marqueur.write_text(signature, encoding="utf-8")
    env: dict[str, str] = {}
    if "git" in entree:
        env = {"PYTHONPATH": str(dossier / "src"), "GRAMPS_RESOURCES": str(dossier / "share")}
    return exe, env


# --- exécution ------------------------------------------------------------------------------------------

def preparer_cas(travail: Path) -> list[tuple[str, Cas, Path, dict[str, list[str]]]]:
    """Fichiers à importer et objets attendus (handles du modèle Gramps produit par Genealogiste)."""
    from genealogiste_mcp.gedcom.mapping import read_gedcom
    from genealogiste_mcp.gramps.mapping import tree_to_gramps_stats

    lots = []
    for arbre in ARBRES:
        origine = read_gedcom((FIXTURES / arbre).read_text(encoding="utf-8"))[0]
        for cas in CAS:
            if cas.arbres and arbre not in cas.arbres:
                continue
            dossier = travail / "entrees" / cas.nom / Path(arbre).stem
            dossier.mkdir(parents=True)
            tree = cas.enrichir(origine, dossier) if cas.enrichir else origine
            db, _ = tree_to_gramps_stats(tree, None, False)
            if cas.retoucher:
                cas.retoucher(db)
            attendu = {cls: sorted(handle_gramps(h) for h in db.all(cls)) for cls in CLASSES}
            attendu[MODELE] = [o for cls in CLASSES for o in db.all(cls).values()]  # objets JSON exportés
            fichier = cas.produire(tree, dossier)
            cible = dossier / f"{Path(arbre).stem}{''.join(fichier.suffixes)}"
            fichier.rename(cible)
            ecarts = comparer(attendu, inventaire_xml(cible), f"export {cas.nom}")
            if ecarts:  # l'export lui-même ne contient pas le modèle : inutile d'interroger Gramps
                raise SystemExit("\n".join(ecarts))
            lots.append((arbre, cas, cible, attendu))
    return lots


# --- sens inverse (#269) : ce que Gramps écrit, relu par l'import de Genealogiste ------------------------

# Champs JSON absents du XML (Gramps les ajoute ou les calcule sans les écrire) : seuls écarts admis entre un objet
# importé par Gramps et le même objet relu par Genealogiste ; gramps_id, change et Date.sortval sont comparés.
IGNORES_LECTURE = {"thumb", "complete", "familysearch_sync"}


def _normaliser_lecture(o, cls: str = ""):
    if isinstance(o, dict):
        c = o.get("_class", cls)
        return {k: _normaliser_lecture(v, c) for k, v in o.items()
                if k not in IGNORES_LECTURE and not (c == "Date" and k == "format")
                and not (c == "Date" and k == "text" and o.get("modifier") != 6)}
    if isinstance(o, (list, tuple)):
        return [_normaliser_lecture(x, cls) for x in o]
    return o


def _ecarts_stricts(a, b, chemin: str, ecrit_par_gramps: bool = False):
    """Écarts dans les deux sens (clé manquante d'un côté ou de l'autre, valeur, longueur de liste).

    ``ecrit_par_gramps`` : ``b`` a traversé l'écriture XML de Gramps (réexport), qui perd de son côté : espaces de
    début et de fin des valeurs écrites par ``fix`` (attributs, champs de nom…) ; somme de contrôle d'un média
    calculée par Gramps quand le fichier est trouvé. Ces deux écarts-là sont admis, et seulement eux."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in b or k not in a:
                yield f"{chemin}.{k} {'absent après lecture' if k not in b else 'en trop'}"
            elif not (ecrit_par_gramps and k == "checksum" and not (a[k] and b[k])):
                yield from _ecarts_stricts(a[k], b[k], f"{chemin}.{k}", ecrit_par_gramps)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield f"{chemin} : {len(a)} éléments, {len(b)} relus"
        else:
            for i, (x, y) in enumerate(zip(a, b, strict=True)):
                yield from _ecarts_stricts(x, y, f"{chemin}[{i}]", ecrit_par_gramps)
    elif a != b and not (ecrit_par_gramps and isinstance(a, str) and isinstance(b, str) and a.strip() == b):
        yield f"{chemin} : Gramps {a!r}, Genealogiste {b!r}"


def comparer_objets(reference: list[dict], db, contexte: str, ecrit_par_gramps: bool = False,
                    ignorer: frozenset[str] = frozenset()) -> list[str]:
    """Objets Gramps (object_to_dict) comparés champ par champ, dans les deux sens, à la base relue par
    Genealogiste (GrampsDb) ; ``ecrit_par_gramps`` : voir :func:`_ecarts_stricts` ; ``ignorer`` : clés de premier
    niveau hors comparaison (gramps_id que Gramps renumérote à l'import selon ses préférences)."""
    ecarts = []
    vus: dict[str, set[str]] = {cls: set() for cls in CLASSES}
    for o in reference:
        cls, h = o["_class"], o["handle"]
        vus[cls].add(h)
        g = db.get(cls, h)
        if g is None:
            ecarts.append(f"{contexte} : {cls}:{h} absent")
            continue
        a, b = ({k: v for k, v in x.items() if k not in ignorer} for x in (o, g))
        ecarts += [f"{contexte} : {e}" for e in _ecarts_stricts(_normaliser_lecture(a), _normaliser_lecture(b),
                                                                f"{cls}:{h}", ecrit_par_gramps)]
    for cls in CLASSES:
        en_trop = set(db.all(cls)) - vus[cls]
        if en_trop:
            ecarts.append(f"{contexte} : {cls} en trop {sorted(en_trop)[:3]}")
    return ecarts[:10]


def _handles(db) -> dict[str, list[str]]:
    return {cls: sorted(db.all(cls)) for cls in CLASSES}


def controle_lecture(cas: Cas, version: str, attendu: dict, rapport: dict) -> list[str]:
    """Sens inverse : le réexport de Gramps relu par Genealogiste (aller-retour XML sans perte, objets identiques
    champ par champ à ceux de Gramps en 6.x, mêmes handles en 5.2), puis réécrit en 1.7.1 pour le cycle complet
    (réimport par Gramps, voir ``verifier_version``)."""
    from genealogiste_mcp.export.gramps_xml import db_to_xml
    from genealogiste_mcp.gramps.lecture_xml import LectureGrampsError, comparer_xml
    from genealogiste_mcp.gramps.lecture_xml import lire_xml as lire

    if "reexport" not in rapport:
        return []
    chemin = Path(rapport["reexport"])
    brut = chemin.read_bytes()
    try:
        lu = lire(brut)
    except LectureGrampsError as exc:
        return [f"lecture Genealogiste du réexport refusée : {exc}"]
    ecarts = [f"aller-retour XML : {e}" for e in comparer_xml(brut, db_to_xml(lu.db, lu.version_xml, lu.meta)
                                                              .encode())]
    if "objets" in rapport:  # objets importés par Gramps, puis réécrits par Gramps : voir _ecarts_stricts
        ecarts += comparer_objets(rapport["objets"], lu.db, "lecture Genealogiste", ecrit_par_gramps=True)
    else:
        ecarts += comparer(rapport["handles"], _handles(lu.db), "lecture Genealogiste")
    cycle = chemin.with_name(f"{chemin.name.split('.')[0]}-cycle.gramps")
    cycle.write_text(db_to_xml(lu.db, "1.7.1", lu.meta), encoding="utf-8")
    rapport["cycle"] = str(cycle)
    return ecarts


# Écarts connus de Gramps sur les dates (#272), par version : (motif, forme concernée, date que Gramps en fait).
# Gramps 5.2 ne lit pas une année négative dans daterange / datespan (importxml, corrigé en 6.0) : Date.set refuse
# la valeur et l'import garde l'élément XML comme date textuelle. Signalé par l'export (avertissements_dates).
def _negatif_compose(d: dict) -> bool:
    return d.get("modifier") in (4, 5) and any(y < 0 for y in list(d.get("dateval") or [])[2:7:4])


def _texte_xml(d: dict) -> dict:
    from genealogiste_mcp.export.gramps_xml import date_xml
    from genealogiste_mcp.gramps.types import blank_date

    return {**blank_date(), "modifier": 6, "text": date_xml(d)}


def _double_partielle(d: dict) -> bool:
    v = list(d.get("dateval") or [])
    return d.get("modifier") in (4, 5) and len(v) >= 8 and bool(v[3]) != bool(v[7])


def _double_unique(d: dict) -> dict:
    v = list(d["dateval"])
    return {**d, "dateval": v[:7] + [v[3]]}


def _espaces(d: dict) -> bool:
    return d.get("modifier") == 6 and (d.get("text") or "") != (d.get("text") or "").strip()


# « * » : toutes les versions (limites du format Gramps XML lui-même, pas de la correspondance). Étape : « import »
# (ce que Gramps fait du fichier exporté) ou « écriture » (ce que son réexport perd en plus).
EcartDate = tuple[str, str, Callable[[dict], bool], Callable[[dict], dict]]
ECARTS_DATES: dict[str, list[EcartDate]] = {
    "*": [("double datation d'un seul bout d'une plage : un seul attribut dualdated en XML (celui du début)",
           "import", _double_partielle, _double_unique),
          ("texte d'une date textuelle : espaces de bord retirés par l'écriture XML de Gramps",
           "écriture", _espaces, lambda d: {**d, "text": d["text"].strip()})],
    "5.2": [("année négative dans une plage ou un intervalle : date textuelle portant l'élément XML",
             "import", _negatif_compose, _texte_xml),
            ("date textuelle au texte vide : absente du réexport de Gramps 5.2 (date vide)",
             "écriture", lambda d: d.get("modifier") == 6 and not d.get("text"), lambda d: _date_vide())],
}


def _date_vide() -> dict:
    from genealogiste_mcp.gramps.types import blank_date

    return blank_date()


def date_attendue(d: dict, version: str, etapes: tuple[str, ...] = ("import", "écriture"),
                  connus: dict | None = None) -> dict:
    """Date que Gramps ``version`` rend d'une date exportée, écarts connus (``ECARTS_DATES``) appliqués."""
    for motif, etape, concerne, transforme in ECARTS_DATES["*"] + ECARTS_DATES.get(version, []):
        if etape in etapes and concerne(d):
            d = transforme(d)
            if connus is not None:
                connus[motif] = connus.get(motif, 0) + 1
    return d
CHAMPS_DATE = ("calendar", "modifier", "quality", "dateval", "newyear")


def ecarts_date(a: dict, b: dict) -> list[str]:
    """Écarts entre deux dates Gramps sur ce que le Gramps XML porte (texte d'une date non textuelle exclu)."""
    def norm(d: dict, k: str):
        v = d.get(k)
        if k == "dateval":
            v = list(v or [])[:8 if d.get("modifier") in (4, 5) else 4]
        if k == "newyear":
            v = list(v) if isinstance(v, (list, tuple)) else v or 0
        return v
    out = [f"{k} {norm(a, k)!r} -> {norm(b, k)!r}" for k in CHAMPS_DATE if norm(a, k) != norm(b, k)]
    if 6 in (a.get("modifier"), b.get("modifier")) and (a.get("text") or "") != (b.get("text") or ""):
        out.append(f"text {a.get('text')!r} -> {b.get('text')!r}")
    return out


def controle_dates(cas: Cas, version: str, attendu: dict, rapport: dict) -> list[str]:
    """Dates d'événement (#272) : Gramps -> modèle -> Gramps sans écart. Chaque date exportée revient du réexport de
    Gramps, relue par Genealogiste, identique (ou transformée comme ``ECARTS_DATES`` le prévoit, jamais tolérée en
    bloc) ; elle repasse par le modèle à l'identique (``date_reprise``) et redonne la même date GEDCOM 7 ; en 6.x,
    la valeur de tri calculée par Gramps est celle de Genealogiste."""
    from genealogiste_mcp.gramps.lecture_xml import LectureGrampsError
    from genealogiste_mcp.gramps.lecture_xml import lire_xml as lire
    from genealogiste_mcp.gramps.types import date_from_gramps, date_reprise, valeur_tri

    if "reexport" not in rapport:
        return []
    try:
        relu = lire(Path(rapport["reexport"]).read_bytes()).db
    except LectureGrampsError as exc:
        return [f"dates : réexport illisible ({exc})"]
    importes = {o["handle"]: o["date"] for o in rapport.get("objets", []) if o["_class"] == "Event"}
    ecarts, connus, n = [], {}, 0
    for o in attendu.get(MODELE, []):
        if o["_class"] != "Event":
            continue
        h = handle_gramps(o["handle"])
        d = date_attendue(o["date"], version, connus=connus)
        r = relu.get("Event", h)
        if r is None:
            continue
        n += 1
        r = r["date"]
        e = ecarts_date(d, r)
        if not date_reprise(r):
            e.append("non reprise par le modèle")
        elif date_from_gramps(r) != date_from_gramps(d):
            e.append(f"GEDCOM 7 {date_from_gramps(d)!r} -> {date_from_gramps(r)!r}")
        if h in importes and importes[h].get("sortval") != valeur_tri(d):
            e.append(f"sortval Gramps {importes[h].get('sortval')} / Genealogiste {valeur_tri(d)}")
        if e:
            ecarts.append(f"date {h} ({o.get('gramps_id')}) : {' ; '.join(e)}")
    if cas.nom == "dates":
        print(f"   {version} : {n} dates relues après réexport par Gramps, {len(ecarts)} en écart ; écarts connus : "
              + (" ; ".join(f"{m} ({k})" for m, k in connus.items()) or "aucun"), flush=True)
    return ecarts[:10]


def controle_types(cas: Cas, version: str, attendu: dict, rapport: dict) -> list[str]:
    """#273 : ce que la bibliothèque fait des types (rôles de 6.0 standard en 6.x, personnalisés en 5.2 ; libellés
    français toujours personnalisés), puis import par Genealogiste du réexport de Gramps : types GEDCOM attendus,
    rôles des intervenants, et aucune perte comptée à cause d'un libellé."""
    if cas.nom != "types":
        return []
    from genealogiste_mcp.gramps.lecture_xml import importer

    vus = {(c, s): perso for c, s, perso in rapport.get("types", [])}
    ecarts = [f"{c} « {s} » : {'absent' if (c, s) not in vus else 'standard'} après import, personnalisé attendu"
              for c, s in TYPES_FRANCAIS if vus.get((c, s)) is not True]
    perso_60 = version == "5.2"  # 5.2 ne connaît pas ces rôles : set_from_xml_str en fait des personnalisés
    ecarts += [f"rôle {r} : personnalisé={vus.get(('EventRoleType', r))}, attendu {perso_60}"
               for r in ROLES_60 if vus.get(("EventRoleType", r)) is not perso_60]
    print(f"   {version} : rôles de Gramps 6.0 lus comme types {'PERSONNALISÉS' if perso_60 else 'standard'} ; "
          f"libellés français gardés personnalisés", flush=True)
    if "reexport" not in rapport:
        return ecarts + ["réexport absent"]
    with tempfile.TemporaryDirectory(prefix="types273-") as tmp:
        tree, info, _ = importer(Path(rapport["reexport"]), Path(tmp), "banc")
    p = next((x for x in tree.personnes.values() if x.nom_principal.nom == "ROLES" and x.nom_principal.prenoms
              == "Types"), None)
    if p is None:
        return ecarts + ["personne ITYPES273 absente après import Genealogiste"]
    types = sorted(e.type for e in p.evenements)
    if types != ["BAPM", "CENS"]:
        ecarts.append(f"types GEDCOM {types}, attendu BAPM et CENS")
    bapteme = next((e for e in p.evenements if e.type == "BAPM"), None)
    if bapteme is not None:
        roles = [a.role for a in bapteme.associations]
        if roles != list(ROLES_TYPES):
            ecarts.append(f"rôles relus {roles}")
        if bapteme.age != "2 jours":
            ecarts.append(f"âge (attribut « Âge ») relu {bapteme.age!r}")
    pertes = [k for k in info["non_repris"] if "Âge" in k or "[Age]" in k or "role" in k or k.endswith(".type")]
    return ecarts + ([f"pertes dues aux types : {pertes}"] if pertes else [])


CONTROLES: list[Controle] = [controle_reexport, controle_medias, controle_champs, controle_lecture, controle_dates,
                             controle_types, controle_lieux, controle_notes,
                             controle_reference]


def comparer_cycle(premier: dict, second: dict, contexte: str, ecrit_par_gramps: bool = True) -> list[str]:
    """Second import par Gramps (du fichier réécrit par Genealogiste) identique au premier : handles, et en 6.x
    chaque objet champ par champ (date de modification et identifiants compris). ``ecrit_par_gramps`` : le
    fichier réécrit vient d'un réexport de Gramps (voir :func:`_ecarts_stricts`)."""
    if not second.get("importe"):
        return [f"{contexte} : réimport refusé {second.get('erreurs')}"]
    ecarts = second["erreurs"] + [f"{contexte} avertissement : {a}" for a in second["avertissements"]]
    ecarts += comparer(premier["handles"], second["handles"], contexte)
    if "objets" in premier:
        index = {o["handle"]: o for o in second.get("objets", [])}
        for o in premier["objets"]:
            h = o["handle"]
            if h in index:
                ecarts += [f"{contexte} : {e}" for e in _ecarts_stricts(
                    _normaliser_lecture(o), _normaliser_lecture(index[h]), f"{o['_class']}:{h}", ecrit_par_gramps)]
    return ecarts[:10]


# --- environnement d'exécution de la sonde ---------------------------------------------------------------

def lancer_sonde(exe: Path, env_sup: dict, sortie: Path, fichiers: list[Path], reexporter: bool = True,
                 generer: Path | None = None, dates: Path | None = None) -> tuple[dict | None, str]:
    """Lance la sonde dans l'environnement isolé ; renvoie (rapport, erreur)."""
    sortie.mkdir(parents=True, exist_ok=True)
    rapport_json = sortie / "rapport.json"
    maison = sortie / "home"  # import .gpkg : médias extraits sous le dossier d'images de l'utilisateur
    (maison / "Pictures").mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **env_sup, "GRAMPSHOME": str(maison), "HOME": str(maison),
           "XDG_PICTURES_DIR": str(maison), "XDG_CONFIG_HOME": str(maison / ".config"),
           "XDG_DATA_HOME": str(maison / ".local" / "share"), "LANGUAGE": "en", "LC_ALL": "C.UTF-8"}
    # Gramps développe « {GRAMPS_RESOURCES} » du <mediapath> de son arbre d'exemple avec l'environnement (KeyError
    # sinon) ; la bibliothèque installée ne retient cette variable que si elle désigne ses propres ressources.
    env.setdefault("GRAMPS_RESOURCES", str(exe.parent.parent / "share"))
    cmd = [str(exe), "-P", str(SONDE), "--rapport", str(rapport_json)]
    if reexporter:
        (sortie / "reexport").mkdir(exist_ok=True)
        cmd += ["--reexporter", str(sortie / "reexport")]
    if generer is not None:
        generer.mkdir(parents=True, exist_ok=True)
        cmd += ["--generer", str(generer)]
    if dates is not None:
        cmd += ["--dates", str(dates)]
    proc = subprocess.run([*cmd, *map(str, fichiers)], env=env, capture_output=True, text=True)
    if proc.returncode or not rapport_json.exists():
        return None, "sonde en échec : " + " / ".join((proc.stderr or proc.stdout).strip().splitlines()[-5:])
    return json.loads(rapport_json.read_text(encoding="utf-8")), ""


def verifier_version(entree: dict, lots, travail: Path, cache: Path, python: str, gi_systeme: bool,
                     fixtures: Path | None = None, exemple: bool = True) -> list[Resultat]:
    version = entree["version"]
    print(f"\n== Gramps {version} ({entree.get('pypi') or entree['git']['tag']})", flush=True)
    exe, env_sup = environnement(entree, cache, python, gi_systeme)
    resultats = []
    for cas in CAS:
        entrees = [(arbre, f, att) for arbre, c, f, att in lots if c is cas]
        sortie = travail / f"gramps-{version}" / cas.nom
        rapport, erreur = lancer_sonde(exe, env_sup, sortie, [f for _, f, _ in entrees])
        if rapport is None:
            resultats += [Resultat(version, a, cas.nom, False, erreur) for a, _, _ in entrees]
            continue
        if gi_systeme and entree.get("gi") and rapport["gi"] != "systeme":
            raise SystemExit(f"Gramps {version} : PyGObject système attendu, mode {rapport['gi']}")
        print(f"   gramps {rapport['gramps']}, XML {rapport['xml']}, gi {rapport['gi']}, "
              f"interface d'export {rapport['gui_export']}")
        if not str(rapport["gramps"]).startswith(version):
            raise SystemExit(f"Gramps {version} attendu, {rapport['gramps']} chargé")
        if rapport["xml"] != entree["xml"]:
            raise SystemExit(f"Gramps {version} : XML {rapport['xml']} au lieu de {entree['xml']}")
        cycles = []
        for arbre, fichier, attendu in entrees:
            r = rapport["fichiers"][fichier.name]
            refus = version in cas.refus_attendu
            brut = lire_xml(fichier)
            for motif, remplacement in cas.schema_admis.get(version, ()):
                brut = re.sub(motif, remplacement, brut)
            schema = valider_schemas(brut, rapport["schemas"])
            if refus:
                ecarts = schema + ([] if not r["importe"] else ["import accepté alors qu'un refus est attendu"])
                ecarts += [] if "older version" in " ".join(r["erreurs"]) else [f"refus inattendu : {r['erreurs']}"]
                ok = not ecarts
            elif not r["importe"]:
                ok, ecarts = False, r["erreurs"] or ["import refusé"]
            else:
                ecarts = schema + r["erreurs"] + [f"avertissement : {a}" for a in r["avertissements"]
                                                  if not a.startswith(cas.avertissements_admis or ("\0",))]
                ecarts += comparer(attendu, r["handles"], "import")
                for controle in CONTROLES:
                    ecarts += controle(cas, version, attendu, r)
                ok = not ecarts
                if "cycle" in r:
                    cycles.append((arbre, Path(r["cycle"]), r))
            nombres = {cls: len(h) for cls, h in (r.get("handles") or {}).items() if h}
            detail = ("refus attendu" if refus and ok else "") if ok else " ; ".join(ecarts)
            resultats.append(Resultat(version, arbre, cas.nom, ok, detail, nombres))
        if cycles:  # cycle complet : Gramps -> Genealogiste -> Gramps
            second, erreur = lancer_sonde(exe, env_sup, sortie / "cycle", [f for _, f, _ in cycles], False)
            for arbre, f, premier in cycles:
                ecarts = [erreur] if second is None else comparer_cycle(premier, second["fichiers"][f.name],
                                                                        "réimport")
                resultats.append(Resultat(version, arbre, f"cycle:{cas.nom}", not ecarts, " ; ".join(ecarts),
                                          {cls: len(h) for cls, h in premier["handles"].items() if h}))
    resultats += verifier_generes(entree, exe, env_sup, travail, fixtures)
    resultats += verifier_reference_dates(entree, exe, env_sup, travail, fixtures)
    if exemple:
        resultats += verifier_exemple(entree, exe, env_sup, travail, cache)
    return resultats


# --- dates (#272) : Date.set, valeur de tri et affichage de la bibliothèque, formes refusées --------------

def _xml_refusees() -> tuple[str, list[str]]:
    """Gramps XML 1.7.1 : un événement par forme que Gramps refuse (``dates_gramps.REFUSEES``), élément brut."""
    from genealogiste_mcp.export.gramps_xml import db_to_xml
    from genealogiste_mcp.gramps.mapping import GrampsDb
    from genealogiste_mcp.gramps.types import blank, date_to_gramps

    sys.path.insert(0, str(TESTS))
    try:
        from dates_gramps import REFUSEES
    finally:
        sys.path.remove(str(TESTS))
    objets = []
    for i, _ in enumerate(REFUSEES):
        e = blank("Event", f"refus{i:03d}", f"E{i:04d}")
        e["date"] = date_to_gramps(str(1001 + i))
        objets.append(e)
    xml = db_to_xml(GrampsDb.from_objects(objets), "1.7.1")
    for i, element in enumerate(REFUSEES):
        xml = xml.replace(f'<dateval val="{1001 + i}"/>', element, 1)
    return xml, list(REFUSEES)


def verifier_reference_dates(entree: dict, exe: Path, env_sup: dict, travail: Path, fixtures: Path | None
                             ) -> list[Resultat]:
    """Inventaire #272 soumis à la bibliothèque : chaque forme acceptée ou refusée par ``Date.set`` comme
    ``date_acceptee`` le prévoit (dates vides : refusées par Gramps, admises en JSON par Genealogiste), même valeur
    de tri et même affichage (anglais, ISO) que Genealogiste ; formes refusées (``REFUSEES``) importées par
    Gramps comme Genealogiste les lit (date textuelle portant l'élément XML)."""
    from genealogiste_mcp.gramps.lecture_xml import LectureGrampsError
    from genealogiste_mcp.gramps.lecture_xml import lire_xml as lire
    from genealogiste_mcp.gramps.types import affichage_gramps, date_acceptee, valeur_tri

    version = entree["version"]
    sortie = travail / f"gramps-{version}" / "dates-reference"
    sortie.mkdir(parents=True, exist_ok=True)
    formes = inventaire_dates()
    (sortie / "formes.json").write_text(json.dumps(formes), encoding="utf-8")
    xml, refusees = _xml_refusees()
    fichier = sortie / "refusees.gramps"
    fichier.write_text(xml, encoding="utf-8")
    rapport, erreur = lancer_sonde(exe, env_sup, sortie, [fichier], True, dates=sortie / "formes.json")
    if rapport is None:
        return [Resultat(version, "inventaire", "dates:reference", False, erreur)]
    ecarts = []
    for nom, d in formes:
        r = rapport["dates"][nom]
        vide = not any(list(d["dateval"])[:3]) and not any(list(d["dateval"])[4:7]) and d["modifier"] != 6
        if r["acceptee"] != (not vide and date_acceptee(d)):
            ecarts.append(f"{nom} : acceptée par Gramps {r['acceptee']}, par Genealogiste {not r['acceptee']}")
        elif r["acceptee"]:
            for cle, gramps, nous in (("sortval", r["sortval"], valeur_tri(d)),
                                      ("affichage", r["affichage"], affichage_gramps(d)),
                                      ("valeur", [r["calendar"], r["dateval"]], [d["calendar"], list(d["dateval"])])):
                if gramps != nous:
                    ecarts.append(f"{nom} : {cle} Gramps {gramps!r}, Genealogiste {nous!r}")
    imp = rapport["fichiers"][fichier.name]
    if not imp.get("importe") or "reexport" not in imp:
        ecarts.append(f"formes refusées : import {imp.get('erreurs')}")
    else:
        try:
            gramps, nous = lire(Path(imp["reexport"]).read_bytes()).db, lire(xml.encode()).db
            for h, e in sorted(nous.all("Event").items()):
                g = gramps.get("Event", h)
                ecart = ecarts_date(e["date"], g["date"]) if g else ["absent après import"]
                if ecart or e["date"].get("modifier") != 6:
                    ecarts.append(f"{h} : {' ; '.join(ecart) or 'non textuelle'}")
        except LectureGrampsError as exc:
            ecarts.append(f"formes refusées : réexport illisible ({exc})")
    if fixtures is not None:
        ref = {nom: ([True, r["sortval"], r["affichage"]] if r["acceptee"] else [False])
               for nom, r in rapport["dates"].items()}
        (fixtures / f"dates-gramps-{rapport['gramps']}.json").write_text(
            json.dumps(ref, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    acceptees = sum(1 for r in rapport["dates"].values() if r["acceptee"])
    print(f"   {version} : {len(formes)} formes soumises à Date.set ({acceptees} acceptées), {len(refusees)} formes "
          f"refusées importées ; {len(ecarts)} écart(s)", flush=True)
    return [Resultat(version, "inventaire", "dates:reference", not ecarts, " ; ".join(ecarts[:10]),
                     {"formes": len(formes), "refusees": len(refusees)})]


# --- arbre fictif écrit par la bibliothèque Gramps (fixtures « comme Gramps Desktop ») -------------------

FIXTURES_DESKTOP = FIXTURES / "gramps-desktop"
FORMATS_GENERES = {"famille.gramps": "gramps-gzip", "famille.gpkg": "gpkg"}


def verifier_lecture_genealogiste(chemin: Path, zone: Path) -> list[str]:
    """Import complet par Genealogiste d'un arbre fictif écrit par Gramps : marqueurs Genealogiste-* et forme
    historique Sosa-* / Sosa:auto reconnus, privé conservé, témoin, statuts, médias extraits, pertes listées."""
    from genealogiste_mcp.gramps.lecture_xml import importer

    tree, info, zone_creee = importer(chemin, zone, "banc")
    ecarts = []

    def verifier(cond: bool, motif: str) -> None:
        if not cond:
            ecarts.append(motif)
    p = tree.personnes
    verifier(set(p) == {"I0001", "I0002", "I0003", "I0004"}, f"personnes {sorted(p)}")
    if ecarts:
        return ecarts
    verifier(p["I0001"].uid == "uid-jean-fictif", "Genealogiste-UID non repris")
    verifier(p["I0002"].uid == "uid-marie-fictif", "Sosa-UID (forme historique) non repris")
    verifier(p["I0002"].prive and not p["I0001"].prive, "drapeau privé non conservé")
    naissance = p["I0003"].evenements[0]
    verifier(naissance.statut_manuel is not None and naissance.statut_manuel.statut == "contradictoire",
             "Sosa-Statut d'événement non repris")
    verifier(not any("généré par Genealogiste" in n for n in [*p["I0001"].notes, *tree.notes.values()]),
             "note étiquetée Sosa:auto reprise comme note manuelle")
    verifier(any("Laboureur" in n for n in p["I0001"].notes), "note de personne perdue")
    fam = tree.familles.get("F0001")
    verifier(fam is not None and fam.enfants and fam.enfants[0].statut_manuel is not None
             and fam.enfants[0].statut_manuel.statut == "probable", "Sosa-Statut filiation non repris")
    mariage = fam.evenements[0] if fam and fam.evenements else None
    verifier(mariage is not None and mariage.uid == "uid-mariage-fictif", "UID du mariage non repris")
    verifier(mariage is not None and any(a.personne == "I0004" for a in mariage.associations),
             "témoin du mariage non repris")
    pertes = info["non_repris"]
    for cle in ("Person.address_list[]", "Person.urls[]", "Note.text.tags[]", "Person.primary_name.suffix"):
        verifier(cle in pertes, f"perte non listée : {cle}")
    # #262 : l'étiquette de l'utilisateur est reprise (Sosa:auto reste hors modèle)
    verifier(p["I0001"].tags == ["À vérifier"], f"étiquette non reprise : {p['I0001'].tags}")
    verifier(not any(k == "Tag" or "tag_list" in k for k in pertes), "étiquette comptée comme perdue")
    if FORMATS_GENERES[chemin.name] == "gpkg":
        fichiers = info["medias"]["fichiers"]
        verifier(len(fichiers) == 1 and (zone / fichiers[0]).is_file(), f"média non extrait : {info['medias']}")
        verifier(fichiers and tree.medias["O0001"].fichier == fichiers[0], "chemin du média non relocalisé")
    elif zone_creee is not None:
        ecarts.append("zone d'attente créée pour un .gramps")
    return ecarts


def verifier_generes(entree: dict, exe: Path, env_sup: dict, travail: Path, fixtures: Path | None
                     ) -> list[Resultat]:
    """Arbre fictif construit et exporté par la bibliothèque Gramps (.gramps gzip et .gpkg), lu par
    Genealogiste (objets identiques champ par champ à ceux que Gramps importe, import complet), réécrit puis
    réimporté par Gramps (cycle complet)."""
    from genealogiste_mcp.export.gramps_xml import db_to_xml
    from genealogiste_mcp.gramps.lecture_xml import LectureGrampsError, lire_fichier

    version = entree["version"]
    sortie = travail / f"gramps-{version}" / "generes"
    rapport, erreur = lancer_sonde(exe, env_sup, sortie, [], False, sortie / "fichiers")
    if rapport is None or rapport.get("generation", {}).get("erreurs") or "generes" not in rapport:
        detail = erreur or f"génération : {(rapport or {}).get('generation')}"
        return [Resultat(version, "fictif", "desktop", False, detail)]
    resultats, cycles = [], []
    for nom, fmt in FORMATS_GENERES.items():
        chemin = Path(rapport["generes"][nom])
        r = rapport["fichiers"][nom]
        try:
            lu = lire_fichier(chemin)
        except LectureGrampsError as exc:
            resultats.append(Resultat(version, "fictif", f"desktop:{nom}", False, f"refusé : {exc}"))
            continue
        ecarts = [] if (lu.format, lu.version_xml) == (fmt, entree["xml"]) else \
            [f"format {lu.format} {lu.version_xml}, attendu {fmt} {entree['xml']}"]
        if not r["importe"]:
            ecarts.append(f"Gramps ne relit pas son propre export : {r['erreurs']}")
        elif "objets" in r:
            ecarts += comparer_objets(r["objets"], lu.db, "lecture Genealogiste", ignorer=frozenset({"gramps_id"}))
        else:
            ecarts += comparer(r["handles"], _handles(lu.db), "lecture Genealogiste")
        ecarts += verifier_lecture_genealogiste(chemin, sortie / f"donnees-{nom.replace('.', '-')}")
        cycle = sortie / f"{chemin.stem}-{fmt}-cycle.gramps"
        cycle.write_text(db_to_xml(lu.db, "1.7.1", lu.meta), encoding="utf-8")
        if r["importe"]:
            cycles.append((nom, cycle, r))
        nombres = {cls: n for cls, n in lu.db.count().items() if n}
        resultats.append(Resultat(version, "fictif", f"desktop:{nom}", not ecarts, " ; ".join(ecarts), nombres))
        if fixtures is not None:
            cible = fixtures / f"gramps-{version}"
            cible.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(chemin, cible / nom)
    if cycles:
        second, erreur = lancer_sonde(exe, env_sup, sortie / "cycle", [c for _, c, _ in cycles], False)
        for nom, cycle, premier in cycles:
            ecarts = [erreur] if second is None else comparer_cycle(premier, second["fichiers"][cycle.name],
                                                                    "réimport", ecrit_par_gramps=False)
            resultats.append(Resultat(version, "fictif", f"cycle:desktop:{nom}", not ecarts, " ; ".join(ecarts)))
    return resultats


# --- arbre d'exemple de Gramps (téléchargé, épinglé par commit et empreinte ; jamais copié dans le dépôt) --

EXEMPLE = {
    "depot": "gramps-project/gramps",
    "commit": "2153e4fa4b0e4ddf7542f1c064c7820bc345a482",  # v6.1.0-beta2, comme la bibliothèque 6.1 de la matrice
    "fichiers": {
        "example/gramps/data.gramps": "034411a79f8c2df617e1b09051d1445415792b468baf309957dd330cef6b0c26",
        "example/gramps/example.gramps": "a93c5ebeecb89f0c34ba1606f73089f5c222844fb917fbff15b60adf7bdc3b39",
    },
}


def arbre_exemple(cache: Path) -> dict[str, Path]:
    """Arbres d'exemple de Gramps (GPL du dépôt Gramps, licence propre des données non précisée : jamais
    versionnés ici), téléchargés une fois au commit épinglé et vérifiés par empreinte SHA-256."""
    import hashlib
    import urllib.request

    dossier = cache / "exemple" / EXEMPLE["commit"]
    out = {}
    for rel, empreinte in EXEMPLE["fichiers"].items():
        cible = dossier / Path(rel).name
        if not cible.exists() or hashlib.sha256(cible.read_bytes()).hexdigest() != empreinte:
            url = f"https://raw.githubusercontent.com/{EXEMPLE['depot']}/{EXEMPLE['commit']}/{rel}"
            print(f"  téléchargement {url}", flush=True)
            with urllib.request.urlopen(url, timeout=120) as rep:  # noqa: S310 - URL fixe, épinglée
                brut = rep.read()
            if hashlib.sha256(brut).hexdigest() != empreinte:
                raise SystemExit(f"arbre d'exemple {rel} : empreinte inattendue")
            dossier.mkdir(parents=True, exist_ok=True)
            cible.write_bytes(brut)
        out[cible.name] = cible
    return out


def verifier_exemple(entree: dict, exe: Path, env_sup: dict, travail: Path, cache: Path) -> list[Resultat]:
    """Arbre d'exemple de Gramps (Gramps XML 1.7.2 écrit par Gramps) : relu par Genealogiste, aller-retour XML
    sans perte, objets identiques champ par champ à ceux que Gramps 6.x importe, réécrit en 1.7.1 et réimporté
    par chaque version (cycle complet ; 5.2 ne lit que la réécriture : l'original est en 1.7.2)."""
    from genealogiste_mcp.export.gramps_xml import db_to_xml
    from genealogiste_mcp.gramps.lecture_xml import comparer_xml, lire_fichier

    version = entree["version"]
    sortie = travail / f"gramps-{version}" / "exemple"
    sortie.mkdir(parents=True, exist_ok=True)
    resultats = []
    for nom, chemin in arbre_exemple(cache).items():
        lu = lire_fichier(chemin)
        reecrit = db_to_xml(lu.db, lu.version_xml, lu.meta).encode()
        ecarts = [f"aller-retour XML : {e}" for e in comparer_xml(chemin.read_bytes(), reecrit)]
        cycle = sortie / f"{chemin.stem}-cycle.gramps"
        cycle.write_text(db_to_xml(lu.db, "1.7.1", lu.meta), encoding="utf-8")
        a_importer = [cycle] + ([chemin] if version != "5.2" else [])
        rapport, erreur = lancer_sonde(exe, env_sup, sortie / chemin.stem, a_importer, False)
        if rapport is None:
            resultats.append(Resultat(version, nom, "exemple", False, erreur))
            continue
        r_cycle = rapport["fichiers"][cycle.name]
        if version == "5.2":  # pas de format JSON : mêmes handles
            ecarts += [] if r_cycle.get("importe") else [f"réimport refusé : {r_cycle.get('erreurs')}"]
            ecarts += comparer(_handles(lu.db), r_cycle.get("handles") or {}, "réimport 5.2")
            ecarts += r_cycle["erreurs"] + [f"avertissement : {a}" for a in r_cycle["avertissements"]]
        else:
            r_orig = rapport["fichiers"][chemin.name]
            if not r_orig.get("importe"):
                ecarts.append(f"original refusé par Gramps : {r_orig.get('erreurs')}")
            else:
                ecarts += comparer_objets(r_orig["objets"], lu.db, "lecture Genealogiste",
                                          ignorer=frozenset({"gramps_id"}))
                ecarts += comparer_cycle(r_orig, r_cycle, "réimport de la réécriture", ecrit_par_gramps=False)
        nombres = {cls: n for cls, n in lu.db.count().items() if n}
        resultats.append(Resultat(version, nom, "exemple", not ecarts, " ; ".join(ecarts[:10]), nombres))
    return resultats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--version", action="append", dest="versions",
                        help="version Gramps à vérifier (répétable ; défaut : toutes celles de la matrice)")
    parser.add_argument("--python", default="3.12", help="interpréteur des environnements isolés (uv venv --python)")
    parser.add_argument("--gi", choices=("auto", "systeme"), default="auto",
                        help="systeme : venv --system-site-packages, PyGObject du système exigé pour 5.2 et 6.0")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--rapport", type=Path, help="écrit aussi le résultat en JSON")
    parser.add_argument("--sans-exemple", action="store_true",
                        help="ne pas télécharger ni vérifier l'arbre d'exemple de Gramps")
    parser.add_argument("--fixtures", type=Path, nargs="?", const=FIXTURES_DESKTOP,
                        help="copie les arbres fictifs écrits par Gramps dans ce dossier (défaut : "
                             "mcp/tests/fixtures/gramps-desktop)")
    args = parser.parse_args(argv)

    matrice = charger_matrice()["gramps_desktop"]
    connues = [e["version"] for e in matrice]
    inconnues = set(args.versions or []) - set(connues)
    if inconnues:
        parser.error(f"versions inconnues {sorted(inconnues)} ; matrice : {connues}")
    choisies = [e for e in matrice if not args.versions or e["version"] in args.versions]
    resultats: list[Resultat] = []
    with tempfile.TemporaryDirectory(prefix="genealogiste-gramps-desktop-") as tmp:
        travail = Path(tmp)
        lots = preparer_cas(travail)
        for entree in choisies:
            resultats += verifier_version(entree, lots, travail, args.cache, args.python, args.gi == "systeme",
                                          args.fixtures, not args.sans_exemple)

    print("\n| Gramps | arbre | cas | résultat | objets |\n|---|---|---|---|---|")
    for r in resultats:
        nombres = ", ".join(f"{cls} {n}" for cls, n in r.nombres.items())
        etat = "ok" if r.ok else "ÉCHEC"
        print(f"| {r.version} | {r.arbre} | {r.cas} | {etat}{' : ' + r.detail if r.detail else ''} | {nombres} |")
    if args.rapport:
        args.rapport.write_text(json.dumps([r.__dict__ for r in resultats], ensure_ascii=False, indent=1),
                                encoding="utf-8")
    echecs = [r for r in resultats if not r.ok]
    print(f"\n{len(resultats) - len(echecs)}/{len(resultats)} vérifications réussies")
    return 1 if echecs or not resultats else 0


if __name__ == "__main__":
    sys.exit(main())
