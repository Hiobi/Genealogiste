"""Import Gramps XML / .gpkg de Gramps Desktop (#269) : lecteur symétrique de l'export (mêmes tables SPEC_*),
aller-retour sans perte, versions, gzip, paquet, XML et tar hostiles, import complet par l'outil (modes, marqueurs
Genealogiste-* et Sosa-*, privé, médias en zone d'attente, pertes listées).

Fixtures : fixtures/gramps-objets-riches.json (objets synthétiques couvrant chaque champ) et
fixtures/gramps-desktop/ (arbre FICTIF écrit par la vraie bibliothèque Gramps 5.2, 6.0, 6.1 : provenance dans le
README de ce dossier). L'arbre d'exemple de Gramps n'est jamais copié dans le dépôt : le test qui l'utilise
s'ignore s'il est absent (téléchargé par make test-gramps-desktop, ou GENEALOGISTE_TEST_GRAMPS_EXEMPLE).
"""

from __future__ import annotations

import copy
import gzip
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.export.gramps_xml import compresser, db_to_xml, paquet_gpkg, to_gramps_xml
from genealogiste_mcp.gedcom.mapping import read_gedcom
from genealogiste_mcp.gramps import lecture_xml as lx
from genealogiste_mcp.gramps.lecture_xml import LectureGrampsError
from genealogiste_mcp.gramps.mapping import GrampsDb, tree_to_gramps_stats

FIX = Path(__file__).parent / "fixtures"
RICHE = FIX / "gramps-objets-riches.json"
DESKTOP = FIX / "gramps-desktop"
VERSIONS = {"5.2": "1.7.1", "6.0": "1.7.2", "6.1": "1.7.2"}
COMMIT_EXEMPLE = "2153e4fa4b0e4ddf7542f1c064c7820bc345a482"
_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "genealogiste" / "gramps-desktop"
EXEMPLES = [Path(p) for p in os.environ.get("GENEALOGISTE_TEST_GRAMPS_EXEMPLE", "").split(os.pathsep) if p] or [
    _CACHE / "exemple" / COMMIT_EXEMPLE / n for n in ("data.gramps", "example.gramps")]

ENTETE = ('<?xml version="1.0" encoding="UTF-8"?>\n<database xmlns="http://gramps-project.org/xml/{v}/">'
          '<header><created date="2026-01-01" version="6.0.0"/></header>{corps}</database>')


def doc(corps: str = "", v: str = "1.7.2") -> bytes:
    return ENTETE.format(v=v, corps=corps).encode()


def riche() -> GrampsDb:
    return GrampsDb.from_objects(json.loads(RICHE.read_text(encoding="utf-8")))


def normaliser(o, cls: str = ""):
    """Champs que le XML ne porte pas (Gramps les recalcule) : Date.sortval, Date.format, Date.text hors date
    texte ; vignette, complete (comme le banc Desktop)."""
    if isinstance(o, dict):
        c = o.get("_class", cls)
        return {k: normaliser(v, c) for k, v in o.items()
                if k not in ("thumb", "complete") and not (c == "Date" and k in ("sortval", "format"))
                and not (c == "Date" and k == "text" and o.get("modifier") != 6)}
    if isinstance(o, list):
        return [normaliser(x, cls) for x in o]
    return o


# ---------------------------------------------------------------------------- lecteur et aller-retour

def test_riche_chaque_champ_relu():
    """Chaque objet de gramps-objets-riches.json est relu à l'identique, sauf ce que Gramps reconstruit lui-même
    (index de naissance / décès : première référence Birth / Death de rôle Primary ; ordre que l'export a dû
    changer pour que Gramps retrouve la naissance retenue)."""
    db = riche()
    lu = lx.lire_xml(db_to_xml(db).encode()).db
    assert lu.count() == db.count()
    for cls in ("Tag", "Note", "Repository", "Source", "Citation", "Place", "Media", "Event", "Family", "Person"):
        for h, o in db.all(cls).items():
            a, b = normaliser(o), normaliser(lu.get(cls, h))
            if cls == "Person":
                for x in (a, b):
                    del x["birth_ref_index"], x["death_ref_index"]
                    x["event_ref_list"].sort(key=lambda r: r["ref"])
            assert a == b, f"{cls} {h}"
    # reconstruits comme Gramps
    for p in lu.all("Person").values():
        refs = p["event_ref_list"]
        for cle, typ in (("birth_ref_index", 12), ("death_ref_index", 13)):
            ok = [i for i, r in enumerate(refs) if r["role"]["value"] == 1
                  and lu.get("Event", r["ref"])["type"]["value"] == typ]
            assert p[cle] == (ok[0] if ok else -1)


def test_riche_aller_retour_octet_pour_octet_et_styles():
    db = riche()
    xml = db_to_xml(db)
    lecture = lx.lire_xml(xml.encode())
    assert db_to_xml(lecture.db, lecture.version_xml, lecture.meta) == xml
    note = lecture.db.get("Note", "note0001")["text"]["tags"]
    taille = next(t for t in note if t["name"]["value"] == 4)
    assert taille["value"] == 14 and isinstance(taille["value"], int)  # taille de police : entier, comme Gramps
    assert lecture.version_xml == "1.7.1" and lecture.format == "gramps"


@pytest.mark.parametrize("ged", ["famille.ged", "legacy551.ged", "geneweb7_gwb2ged.ged"])
@pytest.mark.parametrize("version", ["1.7.1", "1.7.2"])
def test_export_de_chaque_fixture_relu_sans_perte(ged, version):
    tree = read_gedcom((FIX / ged).read_text(encoding="utf-8"))[0]
    db, _ = tree_to_gramps_stats(tree, None, False)
    xml = db_to_xml(db, version)
    lecture = lx.lire_xml(compresser(xml))
    assert lecture.format == "gramps-gzip" and lecture.version_xml == version
    assert db_to_xml(lecture.db, version) == xml
    assert {c: sorted(lecture.db.all(c)) for c in lecture.db.count()} == {c: sorted(db.all(c)) for c in db.count()}


def test_metadonnees_relues():
    xml = doc('<name-formats><format number="-1" name="N" fmt_str="SURNAME" active="1"/></name-formats>'
              '<people home="_p1"><person handle="_p1" change="1" id="I1"><gender>M</gender><name type="Birth Name"/>'
              '</person></people>'
              '<bookmarks><bookmark target="person" hlink="_p1"/></bookmarks>'
              '<namemaps><map type="group_as" key="Dupond" value="Dupont"/></namemaps>')
    xml = xml.replace(b"</header>", b"<researcher><resname>Chercheur fictif</resname></researcher>"
                                    b"<mediapath>medias</mediapath></header>")
    lu = lx.lire_xml(xml)
    m = lu.meta
    assert m.chercheur == {"resname": "Chercheur fictif"} and m.mediapath == "medias"
    assert m.personne_reference == "p1" and m.signets == [("person", "p1")]
    assert m.formats_noms == [(-1, "N", "SURNAME", True)] and m.regroupements == [("Dupond", "Dupont")]
    assert lx.comparer_xml(xml, db_to_xml(lu.db, "1.7.2", m).encode()) == []


def test_comparer_xml_normalisation_documentee():
    a = doc('<people><person handle="_a" change="1" id="I1"><gender>M</gender></person>'
            '<person handle="_b" change="1" id="I2"><gender>F</gender></person></people>')
    b = a.replace(b'<person handle="_a" change="1" id="I1"><gender>M</gender></person>', b"").replace(
        b"</people>", b'<person id="I1" change="1" handle="_a">\n  <gender>M</gender>\n</person></people>')
    b = b.replace(b'date="2026-01-01" version="6.0.0"', b'date="2030-01-01" version="6.1.0"')
    assert lx.comparer_xml(a, b) == []  # ordre des objets et des attributs, mise en forme, <created>
    assert lx.comparer_xml(a, a.replace(b"<gender>M</gender>", b"<gender>F</gender>"))
    note = doc('<notes><note handle="_n" change="1" id="N1" type="General"><text>a </text></note></notes>')
    assert lx.comparer_xml(note, note.replace(b"<text>a </text>", b"<text>a</text>"))  # espaces du texte : comptés


@pytest.mark.skipif(not all(p.is_file() for p in EXEMPLES),
                    reason="arbre d'exemple de Gramps absent (make test-gramps-desktop le télécharge)")
@pytest.mark.parametrize("chemin", EXEMPLES, ids=lambda p: p.name)
def test_arbre_exemple_de_gramps_aller_retour_sans_perte(chemin):
    """Critère de l'issue : Gramps XML -> Genealogiste -> Gramps XML sans perte sur l'arbre d'exemple."""
    lu = lx.lire_fichier(chemin)
    assert lu.version_xml == "1.7.2" and lu.db.count()["Person"] >= 60
    assert lx.comparer_xml(chemin.read_bytes(), db_to_xml(lu.db, lu.version_xml, lu.meta).encode()) == []


# ---------------------------------------------------------------------------- dates et valeur de tri

def test_dates_relues():
    corps = ('<events><event handle="_e{i}" change="1" id="E{i}"><type>Birth</type>{d}</event></events>')
    cas = {
        '<dateval val="1750-03-12"/>': ([12, 3, 1750, False], 0, 0),
        '<dateval val="1750" type="about" quality="estimated"/>': ([0, 0, 1750, False], 3, 0),
        '<dateval val="1700-02-11" cformat="Julian" dualdated="1" newyear="Mar25"/>': ([11, 2, 1700, True], 0, 1),
        '<dateval val="????-??-05"/>': ([5, 0, 0, False], 0, 0),
        '<daterange start="1668" stop="1790"/>': ([0, 0, 1668, False, 0, 0, 1790, False], 4, 0),
        '<datespan start="1780-01" stop=""/>': ([0, 1, 1780, False, 0, 0, 0, False], 5, 0),
        '<dateval val="1800" type="to"/>': ([0, 0, 1800, False], 8, 0),
        '<dateval val="-0044-03-15"/>': ([15, 3, -44, False], 0, 0),
    }
    for i, (d, (val, mod, cal)) in enumerate(cas.items()):
        ev = lx.lire_xml(doc(corps.format(i=i, d=d))).db.get("Event", f"e{i}")
        assert (ev["date"]["dateval"], ev["date"]["modifier"], ev["date"]["calendar"]) == (val, mod, cal), d
    texte = lx.lire_xml(doc(corps.format(i=9, d='<datestr val="vers la Saint-Jean"/>'))).db.get("Event", "e9")
    assert texte["date"]["modifier"] == 6 and texte["date"]["text"] == "vers la Saint-Jean"
    assert texte["date"]["sortval"] == 0
    ny = lx.lire_xml(doc(corps.format(i=8, d='<dateval val="1700-04-01" newyear="4-15"/>'))).db.get("Event", "e8")
    assert ny["date"]["newyear"] == [4, 15]
    with pytest.raises(LectureGrampsError, match="Calendrier"):
        lx.lire_xml(doc(corps.format(i=1, d='<dateval val="1750" cformat="Martien"/>')))
    with pytest.raises(LectureGrampsError, match="Date illisible"):
        lx.lire_xml(doc(corps.format(i=1, d='<dateval val="17a0"/>')))


def test_valeur_de_tri_comme_gramps():
    """202 dates des sept calendriers (avec nouvel an) dont Gramps 6.0.8 a calculé la valeur de tri
    (fixtures/gramps-desktop/valeurs-tri-gramps-6.0.8.json)."""
    table = json.loads((DESKTOP / "valeurs-tri-gramps-6.0.8.json").read_text(encoding="utf-8"))
    assert len(table) == 202 and {c[0] for c in table} == set(range(7))
    for cal, d, m, y, ny, attendu in table:
        assert lx.valeur_tri({"calendar": cal, "modifier": 0, "dateval": [d, m, y, False], "newyear": ny}) \
            == attendu, (cal, d, m, y, ny)


# ---------------------------------------------------------------------------- versions et refus explicites

@pytest.mark.parametrize("xmlns, motif", [
    ("http://gramps-project.org/xml/1.8.0/", "1.8.0"),
    ("http://gramps-project.org/xml/1.6.0/", "non pris en charge"),
    ("http://gramps-project.org/xml/2.0.0/", "non pris en charge"),
    ("http://www.gramps-project.org/xml/1.7.2/", "Espace de noms"),
    ("http://exemple.example/xml/1.7.2/", "Espace de noms"),
    ("", "Espace de noms"),
])
def test_version_ou_espace_de_noms_refuses(xmlns, motif):
    xml = doc().replace(b'xmlns="http://gramps-project.org/xml/1.7.2/"', f'xmlns="{xmlns}"'.encode())
    with pytest.raises(LectureGrampsError, match=motif):
        lx.lire_xml(xml)


def test_versions_acceptees_et_https():
    assert lx.lire_xml(doc(v="1.7.1")).version_xml == "1.7.1"
    xml = doc().replace(b"http://gramps", b"https://gramps")
    assert lx.lire_xml(xml).version_xml == "1.7.2"


@pytest.mark.parametrize("xml, motif", [
    (doc().replace(b' version="6.0.0"', b""), "sans version de Gramps"),
    (doc('<people><person handle="_p" change="1" id="I1"><gender>M</gender><inconnu/></person></people>'),
     "inconnu"),
    (doc('<people><person handle="_p" change="1" id="I1" nouveau="1"/></people>'), "Attribut inconnu"),
    (doc('<dnatests/>'), "Section <dnatests> inconnue"),
    (doc('<people><person handle="_p" change="1" id="I1"/><person handle="_p" change="2" id="I2"/></people>'),
     "en double"),
    (doc('<people><person change="1" id="I1"/></people>'), "sans handle"),
    (doc('<people><person handle="_p" change="1" id="I1">texte égaré</person></people>'), "Texte inattendu"),
    (doc('<events/><tags/>'), "ordre"),
    (doc('<people xmlns:x="urn:x"/>'), "Attribut inconnu"),
    (b'<?xml version="1.0"?><gedcom/>', "racine"),
])
def test_contenu_inconnu_refuse_jamais_ignore(xml, motif):
    with pytest.raises(LectureGrampsError, match=motif):
        lx.lire_xml(xml)


def test_people_default_ignore_comme_gramps_mais_signale():
    lu = lx.lire_xml(doc('<people default="I1"><person handle="_p" change="1" id="I1"/></people>'))
    assert lu.ignores and "default" in lu.ignores[0]


# ---------------------------------------------------------------------------- XML hostile

BOMBE = (b'<?xml version="1.0"?><!DOCTYPE database [<!ENTITY a "aaaaaaaaaa">'
         b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
         b'<database xmlns="http://gramps-project.org/xml/1.7.2/">&c;</database>')


@pytest.mark.parametrize("xml", [
    BOMBE,
    b'<?xml version="1.0"?><!DOCTYPE database [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
    b'<database xmlns="http://gramps-project.org/xml/1.7.2/">&x;</database>',
    b'<?xml version="1.0"?><!DOCTYPE database [<!ENTITY % p SYSTEM "http://exemple.example/x.dtd"> %p;]>'
    b'<database xmlns="http://gramps-project.org/xml/1.7.2/"/>',
    b'<?xml version="1.0"?><!DOCTYPE database SYSTEM "http://exemple.example/x.dtd">'
    b'<database xmlns="http://gramps-project.org/xml/1.7.2/">&inconnue;</database>',
    b'<?xml version="1.0"?><!DOCTYPE autre><database xmlns="http://gramps-project.org/xml/1.7.2/"/>',
    b'<database xmlns="http://gramps-project.org/xml/1.7.2/"><header>',
])
def test_xml_hostile_refuse(xml):
    with pytest.raises(LectureGrampsError):
        lx.lire_xml(xml)


def test_doctype_public_de_gramps_accepte_sans_rien_lire():
    """Le DOCTYPE externe que Gramps écrit est admis : jamais résolu (aucun accès réseau)."""
    xml = (b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE database PUBLIC "-//Gramps//DTD Gramps XML 1.7.2//EN"'
           b'\n"http://gramps-project.org/xml/1.7.2/grampsxml.dtd">\n' + doc().split(b"\n", 1)[1])
    assert lx.lire_xml(xml).version_xml == "1.7.2"


def test_tailles_bornees(monkeypatch):
    monkeypatch.setattr(lx, "TAILLE_MAX_XML", 200)
    grand = doc("<tags>" + "".join(f'<tag handle="_t{i}" change="1" name="t" color="#0" priority="0"/>'
                                   for i in range(20)) + "</tags>")
    with pytest.raises(LectureGrampsError, match="volumineux"):
        lx.lire_xml(grand)
    with pytest.raises(LectureGrampsError, match="volumineux"):  # bombe gzip : arrêt à la limite
        lx.lire_xml(gzip.compress(grand))
    with pytest.raises(LectureGrampsError, match="tronqué"):
        lx._gunzip_borne(gzip.compress(b"abc")[:-6])


def test_detection_par_le_contenu(tmp_path):
    xml = db_to_xml(riche())
    for nom, brut, attendu in (("a.ged", xml.encode(), "gramps"), ("sans-extension", compresser(xml), "gramps"),
                               ("b.gramps", b"0 HEAD\n1 GEDC\n2 VERS 7.0\n0 TRLR\n", "gedcom"),
                               ("c.xml", (DESKTOP / "gramps-6.0" / "famille.gpkg").read_bytes(), "gpkg")):
        (tmp_path / nom).write_bytes(brut)
        assert lx.detecter(tmp_path / nom) == attendu, nom


# ---------------------------------------------------------------------------- fichiers écrits par Gramps Desktop

@pytest.mark.parametrize("version", sorted(VERSIONS))
def test_fichiers_gramps_desktop_lus(version, tmp_path):
    g = lx.lire_fichier(DESKTOP / f"gramps-{version}" / "famille.gramps")
    assert (g.format, g.version_xml, g.version_gramps[:3]) == ("gramps-gzip", VERSIONS[version], version)
    assert g.db.count()["Person"] == 4 and g.meta.mediapath == "medias"
    zone = tmp_path / "zone"
    p = lx.lire_fichier(DESKTOP / f"gramps-{version}" / "famille.gpkg", zone)
    assert p.format == "gpkg" and p.medias == [{"membre": "actes/acte fictif é.jpg", "taille_octets": 18,
                                                "extrait": True}]
    assert (zone / "actes" / "acte fictif é.jpg").read_bytes().startswith(b"\xff\xd8")
    assert json.dumps(p.db.to_json(), sort_keys=True) == json.dumps(g.db.to_json(), sort_keys=True)
    sans = lx.lire_fichier(DESKTOP / f"gramps-{version}" / "famille.gpkg")  # sans zone : rien d'extrait
    assert sans.zone is None and not sans.medias[0]["extrait"]


@pytest.mark.parametrize("version", sorted(VERSIONS))
def test_marqueurs_genealogiste_et_sosa_reconnus(version, tmp_path):
    """Attributs Genealogiste-* et forme historique Sosa-* / étiquette Sosa:auto, écrits par la vraie bibliothèque
    Gramps : reconnus par gramps_to_tree (correspondance unique)."""
    tree, info, zone = lx.importer(DESKTOP / f"gramps-{version}" / "famille.gramps", tmp_path, "t")
    assert zone is None and not (tmp_path / "imports").exists()
    p = tree.personnes
    assert p["I0001"].uid == "uid-jean-fictif" and p["I0002"].uid == "uid-marie-fictif"  # Genealogiste-UID, Sosa-UID
    assert p["I0002"].prive and not p["I0001"].prive  # drapeau privé de Gramps conservé
    assert p["I0003"].evenements[0].statut_manuel.statut == "contradictoire"  # Sosa-Statut
    fam = tree.familles["F0001"]
    assert fam.enfants[0].statut_manuel.statut == "probable"  # Sosa-Statut filiation I0003
    assert fam.evenements[0].uid == "uid-mariage-fictif"
    assert any(a.personne == "I0004" for a in fam.evenements[0].associations)  # témoin
    assert not any("généré par Genealogiste" in n for n in [*p["I0001"].notes, *tree.notes.values()])  # Sosa:auto
    assert any("Laboureur" in n for n in p["I0001"].notes)
    assert p["I0002"].evenements[0].date and p["I0003"].evenements[0].date  # julien, républicain
    assert info["version_xml"] == VERSIONS[version] and info["personnes"] == 4


def test_pertes_listees_jamais_silencieuses(tmp_path):
    _, info, _ = lx.importer(DESKTOP / "gramps-6.1" / "famille.gramps", tmp_path, "t")
    pertes = info["non_repris"]
    for cle in ("Person.address_list[]", "Person.urls[]", "Note.text.tags[]", "Person.primary_name.suffix",
                "Person.alternate_names.date", "Tag", "Repository.address_list.city", "Métadonnées.mediapath"):
        assert pertes.get(cle, 0) >= 1, cle
    assert "Person" not in pertes and "Family" not in pertes and "Event" not in pertes


def test_pertes_par_chemin_de_champ():
    db = riche()
    assert lx.pertes(db, db) == {}
    moins = db.copy()
    p = moins.get("Person", "pers0001")
    p["address_list"] = p["address_list"][1:]
    p["attribute_list"] = []
    moins.remove("Tag", "tag0002")
    pertes = lx.pertes(db, moins)
    assert pertes["Person.address_list[]"] == 1 and pertes["Tag"] == 1
    assert any(k.startswith("Person.attribute_list[") for k in pertes)


def test_identifiants_vides_invalides_ou_en_double_reattribues():
    db = GrampsDb.from_objects([
        {"_class": "Person", "handle": "a", "gramps_id": "I1"}, {"_class": "Person", "handle": "b", "gramps_id": "I1"},
        {"_class": "Person", "handle": "c", "gramps_id": ""}, {"_class": "Person", "handle": "d", "gramps_id": "I 2@"},
        {"_class": "Person", "handle": "e", "gramps_id": "IX1"}])
    changes = lx.identifiants_importables(db)
    ids = [db.get("Person", h)["gramps_id"] for h in "abcde"]
    assert ids[0] == "I1" and ids[4] == "IX1" and len(set(ids)) == 5 and len(changes) == 3
    assert any("en double" in c for c in changes) and any("invalide" in c for c in changes)


# ---------------------------------------------------------------------------- paquet .gpkg hostile

def _tar(chemin: Path, membres: list[tuple[tarfile.TarInfo, bytes | None]]) -> Path:
    with tarfile.open(chemin, "w:gz") as tar:
        for info, data in membres:
            if data is not None:
                info.size = len(data)
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return chemin


def _membre(nom: str, typ=tarfile.REGTYPE, cible: str = "") -> tarfile.TarInfo:
    i = tarfile.TarInfo(nom)
    i.type = typ
    i.linkname = cible
    return i


DONNEES = compresser(db_to_xml(riche()))


@pytest.mark.parametrize("membre, donnee, motif", [
    (_membre("lien", tarfile.SYMTYPE, "/etc/passwd"), None, "lien symbolique"),
    (_membre("dur", tarfile.LNKTYPE, "data.gramps"), None, "lien physique"),
    (_membre("periph", tarfile.CHRTYPE), None, "fichier spécial"),
    (_membre("fifo", tarfile.FIFOTYPE), None, "fichier spécial"),
    (_membre("../evasion.jpg"), b"x", "dangereux"),
    (_membre("/etc/absolu.jpg"), b"x", "dangereux"),
    (_membre("a/../../b.jpg"), b"x", "dangereux"),
    (_membre(".env"), b"SECRET=1", "dangereux"),
    (_membre("c:/windows.jpg"), b"x", "dangereux"),
    (_membre("dos\\fichier.jpg"), b"x", "dangereux"),
    (_membre("data.gramps"), DONNEES, "en double"),
])
def test_paquet_hostile_refuse_avant_toute_extraction(tmp_path, membre, donnee, motif):
    paquet = _tar(tmp_path / "hostile.gpkg", [(_membre("data.gramps"), DONNEES), (membre, donnee)])
    zone = tmp_path / "zone"
    with pytest.raises(LectureGrampsError, match=motif):
        lx.lire_fichier(paquet, zone)
    assert not zone.exists() and not (tmp_path / "evasion.jpg").exists()


def test_paquet_sans_donnees_ou_trop_gros(tmp_path, monkeypatch):
    with pytest.raises(LectureGrampsError, match="sans data.gramps"):
        lx.lire_fichier(_tar(tmp_path / "a.gpkg", [(_membre("x.jpg"), b"x")]), tmp_path / "z")
    monkeypatch.setattr(lx, "TAILLE_MAX_MEMBRE", 10)
    with pytest.raises(LectureGrampsError, match="dépasse"):
        lx.lire_fichier(_tar(tmp_path / "b.gpkg", [(_membre("data.gramps"), b"x"), (_membre("g.jpg"), b"y" * 11)]),
                        tmp_path / "z")
    monkeypatch.setattr(lx, "MEMBRES_MAX", 3)
    with pytest.raises(LectureGrampsError, match="membres"):
        lx.lire_fichier(_tar(tmp_path / "c.gpkg", [(_membre(f"m{i}.jpg"), b"x") for i in range(5)]), tmp_path / "z")
    assert not (tmp_path / "z").exists()


def test_paquet_tronque_refuse_et_zone_retiree(tmp_path):
    brut = (DESKTOP / "gramps-6.1" / "famille.gpkg").read_bytes()
    (tmp_path / "t.gpkg").write_bytes(brut[: len(brut) // 2])
    with pytest.raises(LectureGrampsError):
        lx.lire_fichier(tmp_path / "t.gpkg", tmp_path / "zone")
    assert not (tmp_path / "zone").exists()


def test_zone_existante_jamais_ecrasee(tmp_path):
    zone = tmp_path / "zone"
    zone.mkdir()
    with pytest.raises(FileExistsError):
        lx.lire_fichier(DESKTOP / "gramps-6.0" / "famille.gpkg", zone)


def test_paquet_de_genealogiste_relu(tmp_path):
    (tmp_path / "medias").mkdir()
    (tmp_path / "medias" / "acte.jpg").write_bytes(b"\xff\xd8 image")
    db = riche()
    m = db.get("Media", "medi0001")
    m["path"] = "medias/acte.jpg"
    for a in m["attribute_list"]:
        a["value"] = "medias/acte.jpg"
    brut, bilan = paquet_gpkg(db, (tmp_path,))
    assert bilan["inclus"] == 1
    (tmp_path / "p.gpkg").write_bytes(brut)
    lu = lx.lire_fichier(tmp_path / "p.gpkg", tmp_path / "zone")
    assert (tmp_path / "zone" / "medias" / "acte.jpg").read_bytes() == b"\xff\xd8 image"
    assert lu.db.get("Media", "medi0001")["path"] == "medias/acte.jpg"


# ---------------------------------------------------------------------------- import complet par l'outil

def test_outil_import_gramps_remplacer_puis_appliquer(app, tmp_path):
    p = server.arbre_importer_gedcom(str(DESKTOP / "gramps-6.1" / "famille.gramps"), "remplacer")
    assert "erreur" not in p, p
    imp = p["import"]
    assert imp["format"] == "gramps-gzip" and imp["version_xml"] == "1.7.2" and imp["personnes"] == 4
    assert imp["non_repris"] and any("non_repris" in a for a in p["avertissements"])
    assert app.tree().personnes == {}  # rien n'est écrit sans accord
    server.arbre_appliquer(p["jeton"])
    t = app.tree()
    assert sorted(t.personnes) == ["I0001", "I0002", "I0003", "I0004"]  # identifiants Gramps = xref
    assert t.personnes["I0001"].uid == "uid-jean-fictif" and t.personnes["I0002"].prive


def test_outil_import_gramps_ajouter_renumerote(app_famille):
    avant = set(app_famille.tree().personnes)
    p = server.arbre_importer_gedcom(str(DESKTOP / "gramps-5.2" / "famille.gramps"), "ajouter")
    assert "erreur" not in p, p
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    nouveaux = set(t.personnes) - avant
    assert len(nouveaux) == 4 and avant <= set(t.personnes)
    jean = next(x for x in t.personnes.values() if x.nom_principal.prenoms == "Jean" and x.id in nouveaux)
    assert jean.uid == "uid-jean-fictif"


def test_outil_import_gpkg_medias_en_zone_d_attente(app):
    p = server.arbre_importer_gedcom(str(DESKTOP / "gramps-6.0" / "famille.gpkg"), "remplacer")
    assert "erreur" not in p, p
    medias = p["import"]["medias"]
    zone = Path(medias["zone_attente"])
    data = app.config.data_dir
    assert zone.is_relative_to(data / "imports" / "gramps") and zone.is_dir()
    assert medias["fichiers"] == [f"{zone.relative_to(data).as_posix()}/actes/acte fictif é.jpg"]
    assert (data / medias["fichiers"][0]).is_file() and "pieces_proposer" in medias["consigne"]
    assert not app.config.pieces_root.exists() or not any(app.config.pieces_root.rglob("*.jpg"))  # rien au vault
    server.arbre_appliquer(p["jeton"])
    assert app.tree().medias["O0001"].fichier == medias["fichiers"][0]
    assert app.config.media_local(medias["fichiers"][0]).is_file()  # résolu par la règle commune des médias


def test_outil_import_refuse_sans_rien_laisser(app, tmp_path):
    f = tmp_path / "futur.gramps"
    f.write_bytes(doc(v="1.8.0"))
    r = server.arbre_importer_gedcom(str(f), "remplacer")
    assert "1.8.0" in r["erreur"]
    paquet = _tar(tmp_path / "hostile.gpkg", [(_membre("data.gramps"), DONNEES),
                                              (_membre("lien", tarfile.SYMTYPE, "/etc/passwd"), None)])
    r = server.arbre_importer_gedcom(str(paquet), "remplacer")
    assert "lien symbolique" in r["erreur"]
    assert not (app.config.data_dir / "imports").exists() or not any((app.config.data_dir / "imports").rglob("*"))
    assert server.arbre_importer_gedcom(str(f), "fusionner")["erreur"].startswith("mode")


def test_outil_import_gedcom_inchange(app, fixtures):
    p = server.arbre_importer_gedcom(str(fixtures / "legacy551.ged"), "remplacer")
    assert p["import"]["personnes"] == 1 and "format" not in p["import"]


def test_outil_import_export_genealogiste_aller_retour(app_famille, tmp_path):
    """Un export Gramps de Genealogiste réimporté en mode remplacer : l'arbre ne change pas."""
    tree = app_famille.tree()
    f = tmp_path / "export.gramps"
    f.write_bytes(compresser(to_gramps_xml(tree)))
    r = server.arbre_importer_gedcom(str(f), "remplacer")
    assert r.get("erreur") == "La proposition ne modifie rien." or "diff" in r


def test_non_repris_ne_masque_pas_les_marqueurs():
    """Les marqueurs que Genealogiste ajoute (Genealogiste-UID…) sont comptés sous leur type : ils ne compensent
    pas un attribut utilisateur perdu."""
    db = riche()
    apres = copy.deepcopy(db)
    p = apres.get("Person", "pers0001")
    p["attribute_list"] = [{"_class": "Attribute", "private": False, "citation_list": [], "note_list": [],
                            "type": {"_class": "AttributeType", "value": 0, "string": "Genealogiste-UID"},
                            "value": "x"}] * len(p["attribute_list"])
    assert any(k.startswith("Person.attribute_list[") for k in lx.pertes(db, apres))


def test_outil_import_gramps_en_backend_gramps(tmp_path, tree):
    """Backend gramps : même contrat (proposition = transaction Gramps Web, rien n'est envoyé sans accord)."""
    from gramps_fake import URL, FakeGrampsWeb

    from genealogiste_mcp.config import Config
    from genealogiste_mcp.gramps.mapping import tree_to_gramps

    with FakeGrampsWeb() as fake:
        for objs in tree_to_gramps(tree).objects.values():
            for o in objs.values():
                fake.put(o)
        cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend="gramps",
                     gramps_url=URL, gramps_user="sosa", gramps_password="secret", gramps_ttl=0)
        server.set_app(server.App(cfg, sleeper=lambda s: None))
        try:
            avant = len(fake.objects["Person"])
            p = server.arbre_importer_gedcom(str(DESKTOP / "gramps-6.0" / "famille.gramps"), "ajouter")
            assert "transaction_gramps" in p and p["import"]["personnes"] == 4
            assert len(fake.objects["Person"]) == avant
            assert "erreur" not in server.arbre_appliquer(p["jeton"])
            uids = {a["value"] for o in fake.objects["Person"].values() for a in o.get("attribute_list", [])}
            assert len(fake.objects["Person"]) == avant + 4 and "uid-jean-fictif" in uids
        finally:
            server.set_app(None)
