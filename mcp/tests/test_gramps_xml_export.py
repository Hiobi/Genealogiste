"""Export Gramps XML (#268) : version cible, validité DTD/RNG, écriture complète des objets Gramps, gzip, .gpkg.

Schémas de Gramps copiés dans fixtures/gramps-xml/ (provenance et licence : README.md de ce dossier).
Objets synthétiques couvrant chaque champ du format JSON de Gramps : fixtures/gramps-objets-riches.json
(réutilisable par l'import #269).
"""

from __future__ import annotations

import copy
import gzip
import io
import json
import re
import tarfile
from pathlib import Path

import pytest
from lxml import etree

from genealogiste_mcp import server
from genealogiste_mcp.export import gramps_xml
from genealogiste_mcp.export.gramps_xml import (
    VERSION_XML_DEFAUT,
    Metadonnees,
    db_to_xml,
    to_gramps_xml,
    verifier_version_xml,
)
from genealogiste_mcp.gramps.mapping import GrampsDb
from genealogiste_mcp.gramps.types import tname
from genealogiste_mcp.models import Media

FIX = Path(__file__).parent / "fixtures"
SCHEMAS = FIX / "gramps-xml"
RICHE = FIX / "gramps-objets-riches.json"
NS = {"g172": "http://gramps-project.org/xml/1.7.2/", "g171": "http://gramps-project.org/xml/1.7.1/"}


def _schemas(version: str):
    return (etree.DTD(str(SCHEMAS / version / "grampsxml.dtd")),
            etree.RelaxNG(etree.parse(str(SCHEMAS / version / "grampsxml.rng"))))


def erreurs(xml: str | bytes, version: str) -> list[str]:
    """Erreurs de validation DTD puis RNG (schémas de Gramps de la version)."""
    brut = xml.encode("utf-8") if isinstance(xml, str) else xml
    doc = etree.fromstring(brut, etree.XMLParser(load_dtd=False, resolve_entities=False, no_network=True))
    dtd, rng = _schemas(version)
    out = []
    if not dtd.validate(doc):
        out += [f"DTD l.{e.line} : {e.message}" for e in dtd.error_log]
    if not rng.validate(doc):
        out += [f"RNG l.{e.line} : {e.message}" for e in rng.error_log]
    return out


def riche() -> GrampsDb:
    return GrampsDb.from_objects(json.loads(RICHE.read_text(encoding="utf-8")))


def sans(db: GrampsDb, *, styles_gramps6=False, from_to=False, genre_x=False, citations_eventref=False) -> GrampsDb:
    """Copie de la base privée des contenus que le schéma 1.7.1 strict (ou la DTD) ne décrit pas."""
    db = db.copy()
    if styles_gramps6:
        db.remove("Note", "note0004")
    def dates(o):
        if isinstance(o, dict):
            if o.get("_class") == "Date" and o["modifier"] in (7, 8):
                o["modifier"] = 0
            for v in o.values():
                dates(v)
        elif isinstance(o, list):
            for v in o:
                dates(v)
    if from_to:
        dates(db.objects)
    for p in db.all("Person").values():
        if genre_x and p["gender"] == 3:
            p["gender"] = 2
    for o in [*db.all("Person").values(), *db.all("Family").values()]:
        for r in o["event_ref_list"]:
            if citations_eventref:
                r["citation_list"] = []
    return db


# ------------------------------------------------------------------ version cible, en-tête

def test_version_par_defaut_inchangee():
    assert VERSION_XML_DEFAUT == "1.7.1"
    xml = db_to_xml(riche())
    assert '<!DOCTYPE database PUBLIC "-//Gramps//DTD Gramps XML 1.7.1//EN"\n' \
           '"http://gramps-project.org/xml/1.7.1/grampsxml.dtd">' in xml
    assert '<database xmlns="http://gramps-project.org/xml/1.7.1/">' in xml
    assert re.search(r'<created date="\d{4}-\d\d-\d\d" version="5\.2\.0"/>', xml)
    assert "<researcher/>" in xml  # obligatoire pour le RNG, même vide


def test_version_172():
    xml = db_to_xml(riche(), "1.7.2")
    assert '"-//Gramps//DTD Gramps XML 1.7.2//EN"\n"http://gramps-project.org/xml/1.7.2/grampsxml.dtd"' in xml
    assert '<database xmlns="http://gramps-project.org/xml/1.7.2/">' in xml  # NS URI : http, sans www
    assert "https://gramps" not in xml and "www.gramps" not in xml
    assert re.search(r'<created date="[^"]+" version="6\.0\.0"/>', xml)


@pytest.mark.parametrize("v", ["1.8.0", "1.7", "1.7.3", "2.0.0", "", "1.7.1 "])
def test_version_inconnue_refusee(v):
    with pytest.raises(ValueError) as exc:
        verifier_version_xml(v)
    if v == "1.8.0":
        assert "pas encore publié" in str(exc.value)
    with pytest.raises(ValueError):
        db_to_xml(riche(), v)


def test_contenu_identique_entre_versions():
    """1.7.1 et 1.7.2 ne diffèrent que par l'étiquette (comme Gramps 5.2, qui écrit du contenu 1.7.2 en 1.7.1)."""
    a, b = db_to_xml(riche(), "1.7.1"), db_to_xml(riche(), "1.7.2")
    corps = lambda x: x.split("</header>", 1)[1]  # noqa: E731
    assert corps(a) == corps(b)


# ------------------------------------------------------------------ validité DTD et RNG

def test_riche_valide_172():
    assert erreurs(db_to_xml(sans(riche(), styles_gramps6=True), "1.7.2"), "1.7.2") == []


def test_riche_valide_171_strict_hors_ecarts_documentes():
    db = sans(riche(), styles_gramps6=True, from_to=True, genre_x=True, citations_eventref=True)
    assert erreurs(db_to_xml(db, "1.7.1"), "1.7.1") == []


def test_ecarts_171_documentes():
    """Ce que Gramps 5.2 écrit lui-même sous l'étiquette 1.7.1 (et que 5.2, 6.0, 6.1 importent) : citations de
    référence d'événement, modificateurs from/to, genre X. Seuls écarts au schéma 1.7.1 strict."""
    errs = [e for e in erreurs(db_to_xml(sans(riche(), styles_gramps6=True), "1.7.1"), "1.7.1")
            if e.startswith("DTD")]  # (le RNG enchaîne des erreurs en cascade après la première)
    assert errs
    for e in errs:
        assert ("citationref" in e or "Value \"from\"" in e or "Value \"to\"" in e or "dateval" in e
                or "gender" in e or "eventref" in e), e


def test_styles_gramps6_hors_dtd():
    """Barré et indice (Gramps 6) : écrits comme Gramps le fait, seul écart au DTD 1.7.2."""
    xml = db_to_xml(riche(), "1.7.2")
    assert '<style name="strikethrough">' in xml and '<style name="subscript">' in xml
    errs = [e for e in erreurs(xml, "1.7.2") if e.startswith("DTD")]
    assert errs and all("style" in e or "strikethrough" in e or "subscript" in e for e in errs), errs


@pytest.mark.parametrize("ged", ["famille.ged", "legacy551.ged", "geneweb7_gwb2ged.ged"])
@pytest.mark.parametrize("version", ["1.7.1", "1.7.2"])
def test_exports_des_fixtures_valides(ged, version):
    from genealogiste_mcp.gedcom.mapping import read_gedcom

    tree = read_gedcom((FIX / ged).read_text(encoding="utf-8"))[0]
    xml = to_gramps_xml(tree, version_xml=version)
    errs = erreurs(xml, version)
    if version == "1.7.1":  # écarts documentés seulement
        errs = [e for e in errs if "citationref" not in e and "eventref" not in e]
    assert errs == []


# ------------------------------------------------------------------ complétude : rien ne manque

# Champs du JSON de Gramps sans représentation dans Gramps XML (aucune version) : recalculés par Gramps à
# l'import, ou propres au format JSON. Toute autre valeur doit se retrouver dans le fichier.
NON_REPRESENTES = {
    ("Date", "sortval"),           # recalculé à l'import
    ("Date", "text"),              # écrit seulement pour une date texte (modifier 6) : <datestr val>
    ("Date", "format"),            # Gramps Web
    ("Person", "birth_ref_index"), ("Person", "death_ref_index"),  # déduits de l'ordre des eventref
    ("Media", "thumb"), ("Family", "complete"),
}


def _feuilles(obj, chemin=()):
    if isinstance(obj, dict):
        cls = obj.get("_class", "")
        if cls.endswith("Type") and "value" in obj:  # type Gramps : sa chaîne XML
            yield chemin, cls, "type", tname(obj)
            return
        for k, v in obj.items():
            if k == "_class":
                continue
            if (cls, k) in NON_REPRESENTES and not (cls == "Date" and k == "text" and obj.get("modifier") == 6):
                continue
            if isinstance(v, (dict, list)):
                yield from _feuilles(v, (*chemin, k))
            else:
                yield (*chemin, k), cls, k, v
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                yield from _feuilles(v, (*chemin, i))
            else:
                yield (*chemin, i), "", str(i), v


def test_riche_rien_ne_manque():
    """Chaque valeur non vide des objets Gramps figure dans le XML (handles préfixés de « _ »)."""
    db = riche()
    xml = db_to_xml(db, "1.7.2")
    vals = set()  # valeurs d'attributs et textes, entités résolues
    for el in etree.fromstring(xml.encode()).iter():
        vals.update(el.attrib.values())
        if el.text:
            vals.add(el.text)
    manquants = []
    for cls_name in db.objects:
        for o in db.all(cls_name).values():
            for chemin, cls, k, v in _feuilles(o):
                if v in (None, "", False, 0) or k == "_class" or (cls == "Date" and k in ("calendar", "modifier",
                                                                                          "quality", "newyear")):
                    continue
                if cls == "Date" or chemin[-2:-1] == ("dateval",) or "dateval" in chemin:
                    continue  # dates : vérifiées par test_dates
                if k in ("private", "primary", "sort_as", "display_as", "format", "gender", "status", "type") \
                        and cls not in ("",) and not isinstance(v, str):
                    continue  # codés (priv="1", prim, sort, display, format, genre, statut LDS) : tests dédiés
                attendu = ("_" + v) if isinstance(v, str) and re.fullmatch(r"[a-z]{4}\d{4}|tag\d{4}", v) else str(v)
                if attendu not in vals and not any(attendu in x for x in vals):
                    manquants.append((cls_name, o["handle"], chemin, v))
    assert manquants == []


def test_marques_privees_toutes_ecrites():
    db = riche()
    xml = db_to_xml(db)

    def compte(o):
        if isinstance(o, dict):
            return (1 if o.get("private") else 0) + sum(compte(v) for v in o.values())
        if isinstance(o, list):
            return sum(compte(v) for v in o)
        return 0
    assert xml.count('priv="1"') == sum(compte(o) for c in db.objects for o in db.all(c).values())


def _el(xml: str, tag: str, handle: str) -> str:
    m = re.search(rf'<{tag} handle="_{handle}".*?</{tag}>', xml, re.S)
    assert m, (tag, handle)
    return m.group(0)


def test_dates():
    xml = db_to_xml(riche())
    assert '<dateval val="1700-03-03" quality="calculated" cformat="Julian" dualdated="1" newyear="Mar25"/>' in xml
    assert '<dateval val="1750-07-14" type="about" quality="estimated"/>' in xml
    assert '<dateval val="1790-??-05"/>' in xml                       # jour gardé quand le mois est inconnu
    assert '<datespan start="1720" stop="" cformat="Julian" newyear="Mar1"/>' in xml  # fin vide
    assert '<dateval val="1760" type="from"/>' in xml
    assert '<dateval val="1770-01" type="to" newyear="3-25"/>' in xml
    assert '<daterange start="1790-01-01" stop="1791-12-31" quality="calculated"/>' in xml
    assert '<datestr val="le jour de la Saint-Martin"/>' in xml
    assert '<dateval val="0008-05-10" cformat="French Republican"/>' in xml
    assert '<daterange start="1668" stop="1790"/>' in xml                # date de placeref
    assert '<dateval val="-050"/>' in xml                                  # année négative, comme Gramps
    assert "le jour de la Saint-Martin" in _el(xml, "event", "even0006")


def test_noms_et_patronymes():
    p = _el(db_to_xml(riche()), "person", "pers0001")
    assert '<name type="Birth Name" sort="1" display="2">' in p
    assert '<surname prefix="de" connector="-" derivation="Patrilineal">Dupont</surname>' in p
    assert '<surname prim="0" derivation="Origine perso">Martin</surname>' in p
    for frag in ("<first>Jean Baptiste</first>", "<call>Jean</call>", "<suffix>fils</suffix>",
                 "<title>sieur</title>", "<nick>Janot</nick>", "<familynick>les Dupont</familynick>",
                 "<group>DUPONT</group>", '<name alt="1" type="Also Known As" priv="1">',
                 '<name alt="1" type="Nom de religion"/>'):
        assert frag in p, frag
    assert '<gender>X</gender>' in _el(db_to_xml(riche()), "person", "pers0003")


def test_lieux_noms_alternatifs_et_hierarchie_datee():
    pl = _el(db_to_xml(riche()), "placeobj", "plac0002")
    assert pl.index("<ptitle>") < pl.index("<code>") < pl.index("<pname")  # ordre du DTD
    assert '<pname value="Lille" lang="fr"><dateval val="1800" type="after"/></pname>' in pl
    assert '<pname value="Rijsel" lang="nl"><dateval val="1668" type="before"/></pname>' in pl
    assert '<pname value="Insula" lang="la"/>' in pl and "<pname value=\"L'Isle\"/>" in pl
    assert '<placeref hlink="_plac0001"><daterange start="1668" stop="1790"/></placeref>' in pl
    assert '<placeref hlink="_plac0003"/>' in pl
    assert ('<location street="Grand-Place" locality="Vieux-Lille" city="Lille" parish="Saint-Étienne" '
            'county="Nord" state="Hauts-de-France" country="France" postal="59000" phone="+33 3 20 00 00 00"/>') in pl
    assert '<location parish="Saint-Maurice"/>' in pl
    assert 'priv="1"' in pl and '<coord long="3.0573" lat="50.6292"/>' in pl
    assert '<coord long="" lat="45.1"/>' in _el(db_to_xml(riche()), "placeobj", "plac0003")
    assert 'type="Province historique"' in _el(db_to_xml(riche()), "placeobj", "plac0003")


def test_references_media_note_format_lds():
    xml = db_to_xml(riche())
    ev = _el(xml, "event", "even0001")
    assert ('<objref hlink="_medi0001" priv="1"><region corner1_x="10" corner1_y="20" corner2_x="30" '
            'corner2_y="40"/>') in ev
    assert '<objref hlink="_medi0001"/>' in _el(xml, "citation", "cita0001")  # sans rectangle
    assert ('<objref hlink="_medi0001"><region corner1_x="0" corner1_y="0" corner2_x="50" corner2_y="50"/>'
            '</objref>') in _el(xml, "person", "pers0001")
    n1 = _el(xml, "note", "note0001")
    assert 'format="1"' in n1 and 'type="Research"' in n1
    assert '<style name="fontsize" value="14"><range start="17" end="23"/><range start="26" end="33"/></style>' in n1
    assert '<text>Gras puis lien' in n1
    assert '<text></text>' in _el(xml, "note", "note0003")  # texte vide : élément requis par le DTD
    p = _el(xml, "person", "pers0001")
    assert ('<lds_ord type="baptism" priv="1"><dateval val="1990-01-01"/><temple val="PARIS"/>'
            '<place hlink="_plac0002"/><status val="Completed"/><sealed_to hlink="_fami0001"/>') in p
    assert '<lds_ord type="sealed_to_parents"/>' in p
    assert '<lds_ord type="sealed_to_spouse"><temple val="LONDON"/><status val="Submitted"/></lds_ord>' in _el(xml, "family", "fami0001")
    o = _el(xml, "object", "medi0001")
    assert ('<file src="medias/acte de naissance.jpg" mime="image/jpeg" '
            'checksum="0123456789abcdef0123456789abcdef" description="Acte &lt;n°1&gt;"/>') in o
    assert '<datestr val="vers la Saint-Jean 1750"/>' in o
    assert '<file src="" mime="" description=""/>' in _el(xml, "object", "medi0002")
    f = _el(xml, "family", "fami0001")
    assert '<childref hlink="_pers0003" priv="1" mrel="Recueilli" frel="Adopted">' in f
    assert '<childref hlink="_pers0004"/>' in f
    assert '<rel type="Union libre"/>' in _el(xml, "family", "fami0002")
    s = _el(xml, "source", "srce0001")
    assert '<reporef hlink="_repo0001" priv="1" callno="5 Mi 1 R 2" medium="Film"><noteref hlink="_note0002"/>' in s
    assert '<reporef hlink="_repo0002" medium="Microfiche perso"/>' in s
    assert '<stitle></stitle>' in _el(xml, "source", "srce0002")  # titre toujours écrit, comme Gramps
    r = _el(xml, "repository", "repo0001")
    assert '<url priv="1" href="https://depot.example" type="Web Home" description="Site du dépôt"/>' in r
    assert '<url href="ftp://f.example/"/>' in r  # type vide : omis, comme Gramps
    assert '<tag handle="_tag0001" change="1700000001" name="Étiquette &lt;1&gt; &amp; &quot;guillemets&quot;" ' \
           'color="#ffff00000000" priority="0"/>' in xml
    assert '<personref hlink="_pers0004" rel=""/>' in _el(xml, "person", "pers0001")


def test_attribut_change_partout():
    xml = db_to_xml(riche())
    for tag in ("person", "family", "event", "citation", "source", "placeobj", "object", "repository", "note",
                "tag"):
        for m in re.finditer(rf"<{tag} [^>]*>", xml):
            assert ' change="' in m.group(0), m.group(0)
    assert 'change="1700000801"' in _el(xml, "person", "pers0001")


def test_ordre_des_evenements_minimal():
    """Gramps déduit naissance/décès retenus de l'ordre des références : ordre conservé tant que Gramps
    retrouve les mêmes, référence retenue placée en tête sinon."""
    xml = db_to_xml(riche())
    ordre = lambda h: re.findall(r'<eventref hlink="_(\w+)"', _el(xml, "person", h))  # noqa: E731
    assert ordre("pers0001") == ["even0001", "even0002", "even0003", "even0004", "even0005"]
    assert ordre("pers0002") == ["even0006", "even0007"]
    assert ordre("pers0003") == ["even0009", "even0001", "even0011"]  # 2e naissance retenue : en tête


def test_echappement_et_caracteres_interdits():
    db = riche()
    n = db.get("Note", "note0002")
    n["text"]["string"] = "a\x01b\x0bc\rd\ne\tf  "
    db.get("Event", "even0001")["description"] = "ligne 1\nligne 2\r"
    xml = db_to_xml(db)
    assert "<text>abc&#13;d\ne\tf  </text>" in xml           # \r gardé, caractères de contrôle retirés
    etree.fromstring(xml.encode())
    assert "ligne 1\nligne 2&#13;</description>" in xml


def test_metadonnees_point_d_extension():
    """En-tête et sections hors objets (#274, #276, #282) : rien n'est inventé, tout ce qui est fourni est écrit."""
    meta = Metadonnees(chercheur={"resname": "Chercheur Fictif", "resemail": "fictif@example.org"},
                       mediapath="medias", personne_reference="pers0001",
                       formats_noms=[(1, "Nom, Prénom", "Surname, Given", True)],
                       signets=[("person", "pers0001"), ("place", "plac0002")],
                       regroupements=[("Dupond", "DUPONT")])
    xml = db_to_xml(sans(riche(), styles_gramps6=True), "1.7.2", meta)
    assert ("<researcher><resname>Chercheur Fictif</resname><resemail>fictif@example.org</resemail></researcher>"
            "<mediapath>medias</mediapath>") in xml
    assert '<people home="_pers0001">' in xml
    assert '<name-formats><format number="1" name="Nom, Prénom" fmt_str="Surname, Given" active="1"/>' in xml
    assert '<bookmarks><bookmark target="person" hlink="_pers0001"/>' in xml
    assert '<namemaps><map type="group_as" key="Dupond" value="DUPONT"/></namemaps>' in xml
    assert erreurs(xml, "1.7.2") == []
    nu = db_to_xml(riche())
    assert "<people>" in nu and "bookmarks" not in nu and "namemaps" not in nu and "mediapath" not in nu


def test_reference_inconnue_dans_les_metadonnees_refusee():
    with pytest.raises(ValueError):
        db_to_xml(riche(), meta=Metadonnees(personne_reference="inconnu"))


# ------------------------------------------------------------------ gzip

def test_gzip_deterministe_et_relisible():
    xml = db_to_xml(riche())
    a, b = gramps_xml.compresser(xml), gramps_xml.compresser(xml)
    assert a[:2] == b"\x1f\x8b" and a == b
    assert gzip.decompress(a).decode("utf-8") == xml


# ------------------------------------------------------------------ outil arbre_exporter

def test_arbre_exporter_gramps_non_regression(app_famille, tmp_path):
    out = tmp_path / "x.gramps"
    r = server.arbre_exporter("gramps", str(out))
    assert "erreur" not in r, r
    brut = out.read_bytes()
    assert brut[:2] != b"\x1f\x8b"  # appel existant : XML non compressé
    xml = brut.decode("utf-8")
    assert '<database xmlns="http://gramps-project.org/xml/1.7.1/">' in xml and "Lucas" not in xml
    assert r["version_xml"] == "1.7.1" and r["compresse"] is False and r["octets"] == len(brut)
    assert erreurs(xml, "1.7.1") == [] or all("citationref" in e or "eventref" in e for e in erreurs(xml, "1.7.1"))


def test_arbre_exporter_gramps_compresse_172(app_famille, tmp_path):
    out = tmp_path / "x.gramps"
    r = server.arbre_exporter("gramps", str(out), version_xml="1.7.2", compresse=True)
    assert "erreur" not in r, r
    brut = out.read_bytes()
    assert brut[:2] == b"\x1f\x8b" and r["octets"] == len(brut) and r["compresse"] is True
    xml = gzip.decompress(brut).decode("utf-8")
    assert 'xmlns="http://gramps-project.org/xml/1.7.2/"' in xml and erreurs(xml, "1.7.2") == []
    assert "Lucas" not in xml


@pytest.mark.parametrize("fmt", ["gramps", "gpkg"])
def test_arbre_exporter_version_invalide(app_famille, tmp_path, fmt):
    out = tmp_path / f"x.{fmt}"
    r = server.arbre_exporter(fmt, str(out), version_xml="1.8.0")
    assert "erreur" in r and "1.8.0" in r["erreur"] and not out.exists()


# ------------------------------------------------------------------ paquet .gpkg

@pytest.fixture
def app_medias(app_famille, tmp_path):
    """Arbre famille + médias : défunt (fichier présent), vivant masqué, fichier absent, hors des racines."""
    a = app_famille
    data = a.config.data_dir
    (data / "medias" / "sous dossier").mkdir(parents=True)
    (data / "medias" / "sous dossier" / "acte é.jpg").write_bytes(b"JPEG-defunt")
    (data / "medias" / "vivant.jpg").write_bytes(b"JPEG-vivant")
    (data / "medias" / "absolu.png").write_bytes(b"PNG-absolu")
    dehors = tmp_path / "dehors.jpg"
    dehors.write_bytes(b"secret")
    t = a.store.load()
    t.medias["O1"] = Media(id="O1", fichier="medias/sous dossier/acte é.jpg", titre="Acte du défunt")
    t.medias["O2"] = Media(id="O2", fichier="medias/vivant.jpg", titre="Photo du vivant")
    t.medias["O3"] = Media(id="O3", fichier="medias/absent.jpg", titre="Absent")
    t.medias["O4"] = Media(id="O4", fichier=str(dehors), titre="Hors racines")
    t.medias["O5"] = Media(id="O5", fichier=str((data / "medias" / "absolu.png").resolve()), titre="Absolu")
    t.medias["O6"] = Media(id="O6", fichier="https://archives.example/vue/1.jpg", titre="Distant")
    t.medias["O7"] = Media(id="O7", fichier="../dehors.jpg", titre="Traversée")
    t.personnes["I1"].medias += ["O1", "O3", "O4", "O5", "O6", "O7"]
    t.personnes["I9"].medias.append("O2")  # Lucas, vivant
    a.store.write(t)
    a.store.commit("medias")
    return a


def _lire_gpkg(chemin: Path) -> tuple[dict[str, bytes], list[tarfile.TarInfo]]:
    with tarfile.open(chemin, "r:gz") as tar:
        membres = tar.getmembers()
        return {m.name: tar.extractfile(m).read() for m in membres}, membres


def test_gpkg_structure_et_medias(app_medias, tmp_path):
    out = tmp_path / "arbre.gpkg"
    r = server.arbre_exporter("gpkg", str(out))
    assert "erreur" not in r, r
    assert out.read_bytes()[:2] == b"\x1f\x8b"
    fichiers, membres = _lire_gpkg(out)
    assert set(fichiers) == {"data.gramps", "medias/sous dossier/acte é.jpg", "medias/absolu.png"}
    for m in membres:
        assert m.isfile() and not m.name.startswith("/") and ".." not in Path(m.name).parts
        assert m.uid == m.gid == 0 and m.mtime == 0 and m.uname == m.gname == ""
    assert fichiers["medias/sous dossier/acte é.jpg"] == b"JPEG-defunt"
    assert fichiers["data.gramps"][:2] == b"\x1f\x8b"  # XML interne gzippé, comme Gramps
    xml = gzip.decompress(fichiers["data.gramps"]).decode("utf-8")
    assert 'xmlns="http://gramps-project.org/xml/1.7.1/"' in xml
    assert 'src="medias/sous dossier/acte é.jpg"' in xml and 'src="medias/absolu.png"' in xml  # relatifs
    assert str(app_medias.config.data_dir) not in xml and str(tmp_path) not in xml  # aucun chemin absolu
    assert "vivant.jpg" not in xml and "Lucas" not in xml  # média de la personne masquée : ni décrit ni empaqueté
    med = r["medias"]
    assert med["inclus"] == 2
    assert any("medias/absent.jpg" in x for x in med["manquants"])
    assert any("dehors.jpg" in x and "refus" in x for x in med["manquants"])  # hors racines et traversée
    assert len([x for x in med["manquants"] if "dehors.jpg" in x]) == 2
    assert med["distants"] == ["O6 : https://archives.example/vue/1.jpg"]
    assert r["octets"] == out.stat().st_size and r["format"] == "gpkg"


def test_gpkg_deterministe_et_172(app_medias, tmp_path):
    a = tmp_path / "a.gpkg"
    server.arbre_exporter("gpkg", str(a), version_xml="1.7.2")
    xml = gzip.decompress(_lire_gpkg(a)[0]["data.gramps"]).decode()
    assert 'xmlns="http://gramps-project.org/xml/1.7.2/"' in xml
    racine = tmp_path / "r"
    (racine / "medias").mkdir(parents=True)
    (racine / "medias" / "acte de naissance.jpg").write_bytes(b"x")
    assert gramps_xml.paquet_gpkg(riche(), (racine,)) == gramps_xml.paquet_gpkg(riche(), (racine,))


@pytest.mark.parametrize("fmt", ["gramps", "gpkg"])
def test_garde_fou_lit_les_noms_structures(app_medias, tmp_path, monkeypatch, fmt):
    """Dans Gramps XML, prénom et patronyme sont dans des éléments distincts : le garde-fou les relit à plat."""
    from genealogiste_mcp import privacy
    vraie = privacy.publication
    monkeypatch.setattr(privacy, "publication", lambda t: (t, *vraie(t)[1:]))  # projection défaillante
    out = tmp_path / f"r.{fmt}"
    r = server.arbre_exporter(fmt, str(out))
    assert "erreur" in r and r["occurrences"] and not out.exists()


def test_gpkg_sans_masquage_inclut_le_media_du_vivant(app_medias, tmp_path):
    out = tmp_path / "prive.gpkg"
    r = server.arbre_exporter("gpkg", str(out), masquer_vivants=False)
    assert "medias/vivant.jpg" in _lire_gpkg(out)[0] and r["medias"]["inclus"] == 3


def test_gpkg_lien_symbolique_sortant_refuse(app_medias, tmp_path):
    data = app_medias.config.data_dir
    (data / "medias" / "lien.jpg").symlink_to(tmp_path / "dehors.jpg")
    t = app_medias.store.load()
    t.medias["O8"] = Media(id="O8", fichier="medias/lien.jpg", titre="Lien")
    t.personnes["I1"].medias.append("O8")
    app_medias.store.write(t)
    out = tmp_path / "l.gpkg"
    r = server.arbre_exporter("gpkg", str(out))
    assert "medias/lien.jpg" not in _lire_gpkg(out)[0]
    assert any("lien.jpg" in x for x in r["medias"]["manquants"])
    assert b"secret" not in b"".join(_lire_gpkg(out)[0].values())


def test_gpkg_refuse_si_residu_rien_ecrit(app_medias, tmp_path, monkeypatch):
    from genealogiste_mcp import privacy
    vraie = privacy.publication
    monkeypatch.setattr(privacy, "publication", lambda t: (t, *vraie(t)[1:]))  # projection défaillante
    out = tmp_path / "r.gpkg"
    r = server.arbre_exporter("gpkg", str(out))
    assert "erreur" in r and not out.exists()
    assert not list(tmp_path.glob("r.gpkg*"))  # aucun fichier temporaire laissé


def test_noms_d_archive_surs():
    from genealogiste_mcp.export.gramps_xml import nom_archive

    assert nom_archive("medias/a.jpg") == "medias/a.jpg"
    for mauvais in ("/etc/passwd", "../x", "a/../../x", "", ".", "C:\\x", "data.gramps"):
        with pytest.raises(ValueError):
            nom_archive(mauvais)


def test_paquet_bas_niveau_sans_outil(tmp_path):
    """paquet_gpkg : API utilisée par l'outil, testée sans application (racines explicites)."""
    racine = tmp_path / "r"
    (racine / "medias").mkdir(parents=True)
    (racine / "medias" / "acte de naissance.jpg").write_bytes(b"x")
    db = riche()
    brut, rapport = gramps_xml.paquet_gpkg(db, (racine,), "1.7.2")
    tar = tarfile.open(fileobj=io.BytesIO(brut), mode="r:gz")
    assert sorted(tar.getnames()) == ["data.gramps", "medias/acte de naissance.jpg"]
    assert rapport["inclus"] == 1 and rapport["manquants"] == []
    assert copy.deepcopy(db.get("Media", "medi0001"))["path"] == "medias/acte de naissance.jpg"  # base intacte
