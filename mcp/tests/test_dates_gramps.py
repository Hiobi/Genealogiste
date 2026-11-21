"""Dates Gramps (#272) : aucune date lue dans Gramps n'est réécrite autrement sans modification.

Table exhaustive (``dates_gramps.inventaire``, aussi jouée par le banc Gramps Desktop sur 5.2, 6.0 et 6.1) :
Gramps -> modèle -> Gramps en JSON (Gramps Web), en Gramps XML (import / export) et par le mapping avec base ;
GEDCOM 7 -> Gramps -> GEDCOM 7 ; valeur de tri, contrôle de ``Date.set`` et affichage comparés à ceux de la vraie
bibliothèque Gramps 6.0.8 (fixtures/gramps-desktop/dates-gramps-6.0.8.json). Données synthétiques.
"""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest
from dates_gramps import REFUSEES, ecarts, inventaire

from genealogiste_mcp import server
from genealogiste_mcp.export.gramps_xml import avertissements_dates, date_xml, db_to_xml
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom
from genealogiste_mcp.gramps import lecture_xml as lx
from genealogiste_mcp.gramps.mapping import GrampsDb, diff, gramps_to_tree, tree_to_gramps
from genealogiste_mcp.gramps.types import (
    affichage_gramps,
    blank,
    date_acceptee,
    date_from_gramps,
    date_reprise,
    date_to_gramps,
    event_ref,
    valeur_tri,
)
from genealogiste_mcp.normalize.dates import convert, parse_gedcom_date

FIX = Path(__file__).parent / "fixtures"
INVENTAIRE = inventaire()
IDS = [n for n, _ in INVENTAIRE]
REFERENCE = json.loads((FIX / "gramps-desktop" / "dates-gramps-6.0.8.json").read_text(encoding="utf-8"))


def lire_date(element: str) -> dict:
    corps = f'<events><event handle="_e1" change="1" id="E1"><type>Birth</type>{element}</event></events>'
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<database xmlns="http://gramps-project.org/xml/1.7.2/">'
           f'<header><created date="2026-01-01" version="6.0.8"/></header>{corps}</database>')
    return lx.lire_xml(xml.encode()).db.get("Event", "e1")["date"]


def test_inventaire_exhaustif():
    assert len(INVENTAIRE) == len(set(IDS)) > 1200
    assert {d["calendar"] for _, d in INVENTAIRE} == set(range(7))
    assert {d["modifier"] for _, d in INVENTAIRE} == set(range(9))
    assert {d["quality"] for _, d in INVENTAIRE} == {0, 1, 2}
    assert {str(d["newyear"]) for _, d in INVENTAIRE} == {"0", "1", "2", "3", "[4, 15]"}
    assert any(d["dateval"][3] for _, d in INVENTAIRE) and any(d["dateval"][2] < 0 for _, d in INVENTAIRE)


@pytest.mark.parametrize("nom, date", INVENTAIRE, ids=IDS)
def test_gramps_modele_gramps(nom, date):
    """Gramps (JSON, texte vide comme après un import XML ou une saisie dans Gramps Web) -> date du modèle ->
    Gramps : objet identique, texte et valeur de tri compris ; la chaîne survit à arbre.ged (écriture et relecture
    GEDCOM 7)."""
    s = date_from_gramps(date)
    assert ecarts(date, date_to_gramps(s)) == [], s
    assert date_reprise(date)
    tree = read_gedcom("0 HEAD\n1 GEDC\n2 VERS 7.0\n0 @I1@ INDI\n1 NAME A /X/\n1 BIRT\n2 DATE 1\n0 TRLR\n")[0]
    tree.personnes["I1"].evenements[0].date = s
    assert read_gedcom(write_gedcom(tree, 7))[0].personnes["I1"].evenements[0].date == s


@pytest.mark.parametrize("nom, date", INVENTAIRE, ids=IDS)
def test_gramps_xml_modele_gramps_xml(nom, date):
    """Gramps XML -> objets -> modèle -> objets -> Gramps XML : même élément. Seule limite du format lui-même :
    un seul ``dualdated`` pour les deux bouts d'une plage (celui du début), comme l'écrit Gramps."""
    x = date_xml(date)
    if not x:  # date vide porteuse d'un attribut : Gramps XML ne l'écrit pas (Gramps non plus)
        assert not any(date["dateval"][:3]) and nom.startswith("vide")
        return
    lu = lire_date(x)
    attendu = copy.deepcopy(date)
    if date["modifier"] in (4, 5):
        attendu["dateval"][7] = attendu["dateval"][3]
    assert ecarts(attendu, lu) == []
    assert date_xml(date_to_gramps(date_from_gramps(lu))) == x


@pytest.mark.parametrize("nom, date", INVENTAIRE, ids=IDS)
def test_comme_la_bibliotheque_gramps(nom, date):
    """Contrôle de Date.set, valeur de tri et affichage identiques à ceux de Gramps 6.0.8 (le banc Desktop les
    compare aussi à 5.2.4 et 6.1.0-beta2)."""
    ref = REFERENCE[nom]
    vide = not any(date["dateval"][:3]) and date["modifier"] != 6
    assert ref[0] == (not vide and date_acceptee(date))
    if ref[0]:
        assert [valeur_tri(date), affichage_gramps(date)] == ref[1:]


def test_mapping_avec_base_conserve_tout():
    """Gramps Web : une date lue puis réécrite sans modification garde son objet d'origine, quel que soit son texte
    (saisie libre, texte périmé, forme écrite par une version antérieure)."""
    objets, k = [], 0
    for _, d in INVENTAIRE:
        for text in ("", "saisie libre", date_from_gramps(d), "12 MAR 1820"):
            if d["modifier"] == 6:
                text = d["text"]
            k += 1
            ev = blank("Event", f"e{k:05d}", f"E{k}")
            ev["date"] = {**copy.deepcopy(d), "text": text}
            objets.append(ev)
    p = blank("Person", "p1", "I1")
    p["event_ref_list"] = [event_ref(o["handle"], "Primary") for o in objets]
    db = GrampsDb.from_objects([p, *objets])
    tree, _ = gramps_to_tree(db)
    assert [x for x in diff(db, tree_to_gramps(tree, base=db, generated=False)) if x["_class"] == "Event"] == []


# ---------------------------------------------------------------------------- GEDCOM 7 -> Gramps -> GEDCOM 7

CANONIQUES = [
    # GEDCOM 7
    "12 MAR 1850", "MAR 1850", "1850", "ABT 1850", "EST 1850", "CAL 1850", "BEF 1850", "AFT 1850", "FROM 1850",
    "TO 1850", "BET 1850 AND 1860", "FROM 1850 TO 1860", "JULIAN 12 FEB 1721", "FRENCH_R 12 VEND 3",
    "FRENCH_R 4 COMP 3", "HEBREW 10 NSN 5600", "12 MAR 100 BCE", "BET JULIAN 1700 AND JULIAN 1710",
    "vers la Saint-Jean",
    # extensions (docs/gedcom-extensions.md)
    "EST BEF 1850", "CAL FROM 1850 TO 1860", "EST ABT 1850", "CAL BET 1850 AND 1860", "JULIAN 12 FEB 1721/22",
    "JULIAN 1699/00", "_PERSIAN 12 FARVA 1300", "_ISLAMIC 12 MUHAR 1300", "_SWEDISH 12 MAR 1705",
    "12 FEB 1850 (Mar25)", "JULIAN 12 OCT 1721 (4-15)", "EST BEF JULIAN 12 FEB 1721/22 (Sep1)", "12 ? 1850",
    "12 MAR ?", "MAR ?", "BET 1850 AND ?", "JULIAN ?", "BEF ?", "(1850)", "()", "((x))", "(  espaces  )",
    "(vers la Saint-Jean)",
]


@pytest.mark.parametrize("s", CANONIQUES)
def test_gedcom7_gramps_gedcom7(s):
    d = date_to_gramps(s)
    assert date_from_gramps(d) == s
    assert d["text"] == (d["text"] if d["modifier"] == 6 else "")  # forme canonique : texte vide, comme Gramps XML
    x = date_xml(d)
    if x:  # par Gramps XML (Gramps n'écrit pas Date.text) : même date du modèle
        assert date_from_gramps(lire_date(x)) == s


@pytest.mark.parametrize("s, canonique", [
    ("abt 1850", "ABT 1850"), ("INT 1850 (vers Pâques)", "1850"), ("1850 (texte)", "1850"),
    ("12 FEB 1721/22", "JULIAN 12 FEB 1721/22"),  # double datation : Gramps la range en julien (Date.set)
    ("@#DJULIAN@ 1 JAN 1700", "JULIAN 1 JAN 1700"),
])
def test_orthographe_d_origine_gardee_dans_text(s, canonique):
    """Une date non canonique garde sa chaîne dans ``text`` (Gramps Web) ; en Gramps XML, qui n'écrit pas
    ``text``, elle revient sous sa forme canonique."""
    d = date_to_gramps(s)
    assert d["text"] == s and date_from_gramps(d) == s
    assert date_from_gramps(lire_date(date_xml(d))) == canonique


def test_date_modifiee_dans_gramps_reconstruite():
    d = date_to_gramps("abt 1850")
    d["dateval"] = [0, 0, 1851, False]  # modifiée dans l'interface, texte périmé
    assert date_from_gramps(d) == "ABT 1851"


@pytest.mark.parametrize("s", ["31 FEB 1850", "FRENCH_R 7 COMP 3", "_ISLAMIC 31 DHUAH 1300", "HEBREW 30 TVT 5600",
                               "BET JULIAN 1700 AND 1710"])
def test_date_que_gramps_refuse_reste_texte(s):
    assert date_to_gramps(s)["modifier"] == 6 and date_to_gramps(s)["text"] == s


@pytest.mark.parametrize("element", sorted(REFUSEES))
def test_lecture_xml_forme_refusee_comme_gramps(element):
    """Gramps refuse la valeur (DateError) et garde l'élément XML comme date textuelle (importxml)."""
    d = lire_date(element)
    assert d["modifier"] == 6 and d["text"] == element and not date_acceptee({**d, "modifier": 0})


def test_lecture_xml_double_datation_rangee_en_julien():
    d = lire_date('<dateval val="1722-02-12" dualdated="1"/>')
    assert d["calendar"] == 1 and d["dateval"] == [12, 2, 1722, True]


def test_pertes_import_dates():
    """Import Gramps XML : les formes reprises ne sont pas comptées perdues ; une forme non représentable l'est."""
    from genealogiste_mcp.gramps.lecture_xml import pertes

    objets = []
    for k, (_, d) in enumerate(INVENTAIRE):
        ev = blank("Event", f"e{k:05d}", f"E{k}")
        ev["date"] = copy.deepcopy(d)
        objets.append(ev)
    p = blank("Person", "p1", "I1")
    p["event_ref_list"] = [event_ref(o["handle"], "Primary") for o in objets]

    def bilan(db):
        relu = read_gedcom(write_gedcom(gramps_to_tree(db)[0]))[0]
        return pertes(db, tree_to_gramps(relu, generated=False))
    assert not any("date" in k for k in bilan(GrampsDb.from_objects([p, *objets])))
    objets[0]["date"] = {**date_to_gramps("12 MAR 1850"), "dateval": [12, 3, 0, True]}  # double datation sans année
    assert bilan(GrampsDb.from_objects([p, *objets])).get("Event.date[forme non reprise]") == 1


# ---------------------------------------------------------------------------- GEDCOM 5.5.1 et 7, fixtures

@pytest.mark.parametrize("brut, modele", [
    ("12 FEB 1721/22", "12 FEB 1721/22"), ("@#DHEBREW@ 10 NSN 5600", "HEBREW 10 NSN 5600"),
    ("100 B.C.", "100 BCE"), ("INT 1850 (vers Pâques)", "1850 (vers Pâques)"), ("(texte libre)", "(texte libre)"),
    ("@#DFRENCH R@ 4 COMP 3", "FRENCH_R 4 COMP 3"),
])
def test_lecture_gedcom_551_alignee_sur_gramps(brut, modele):
    g = read_gedcom(f"0 HEAD\n1 GEDC\n2 VERS 5.5.1\n0 @I1@ INDI\n1 NAME A /X/\n1 BIRT\n2 DATE {brut}\n0 TRLR\n")[0]
    assert g.personnes["I1"].evenements[0].date == modele
    out = write_gedcom(g, 5)
    assert f"2 DATE {brut}\n" in out or brut == "INT 1850 (vers Pâques)" and "2 DATE INT 1850 (vers Pâques)\n" in out


def test_double_datation_annee_nouveau_style():
    """1721/22 : février 1722 (année nouveau style, celle que Gramps stocke), non plus 1721."""
    assert convert("12 FEB 1721/22")["debut_gregorien"] == "1722-02-12"


def test_phrase_gedcom7_lue():
    src = ("0 HEAD\n1 GEDC\n2 VERS 7.0\n0 @I1@ INDI\n1 NAME A /X/\n1 BIRT\n2 DATE 1850\n3 PHRASE vers Pâques\n"
           "1 DEAT\n2 DATE\n3 PHRASE après la guerre\n0 TRLR\n")
    ev = read_gedcom(src)[0].personnes["I1"].evenements
    assert [e.date for e in ev] == ["1850 (vers Pâques)", "(après la guerre)"]
    assert parse_gedcom_date(ev[0].date).phrase == "vers Pâques"


@pytest.mark.parametrize("nom", ["famille.ged", "legacy551.ged", "geneweb7_gwb2ged.ged"])
def test_fixtures_dates_inchangees(nom):
    """Aucun diff parasite : les dates d'événement des fixtures sont réécrites à l'identique (seule normalisation,
    déjà faite avant #272 : zéro initial d'un jour en 5.5.1, « 04 JAN » -> « 4 JAN ») ; arbre.ged réécrit
    octet pour octet."""
    src = (FIX / nom).read_text(encoding="utf-8")
    version = 5 if "VERS 5.5" in src else 7

    def dates(texte: str) -> Counter:
        return Counter(re.sub(r"^0(\d) ", r"\1 ", x.split(" DATE ", 1)[1]) for x in texte.splitlines()
                       if re.match(r"^[2-9] DATE ", x))
    out = write_gedcom(read_gedcom(src)[0], version)
    assert dates(src) and dates(out) == dates(src)
    assert write_gedcom(read_gedcom(out)[0], version) == out


# ---------------------------------------------------------------------------- convertir_date, export

def test_convertir_date_sortie_gramps_retrocompatible():
    out = server.convertir_date("vers 1850")
    assert {k: v for k, v in out.items() if k != "gramps"} == convert("vers 1850")
    assert out["gramps"]["xml"] == '<dateval val="1850" type="about"/>'
    assert out["gramps"]["affichage"] == "about 1850"
    assert out["gramps"]["date"]["modifier"] == 3 and out["gramps"]["date"]["sortval"] == 2396759
    ext = server.convertir_date("EST BEF JULIAN 12 FEB 1721/22 (Mar25)")["gramps"]
    assert ext["xml"] == ('<dateval val="1722-02-12" type="before" quality="estimated" cformat="Julian" '
                          'dualdated="1" newyear="Mar25"/>')
    assert ext["affichage"] == "estimated before 1721/2-02-12 (Julian, Mar25)"
    assert "gramps" not in server.convertir_date("31 FEB 1850")


def test_export_1_7_1_signale_les_pieges_de_gramps_5_2():
    e = blank("Event", "e1", "E1")
    e["date"] = date_to_gramps("BET 120 BCE AND 100 BCE")
    db = GrampsDb.from_objects([e, blank("Event", "e2", "E2")])
    assert avertissements_dates(db, "1.7.1") and "E1" in avertissements_dates(db, "1.7.1")[0]
    assert avertissements_dates(db, "1.7.2") == []
    # dateval val="" (fait échouer l'import de 5.2) : jamais écrit
    for _, d in INVENTAIRE:
        assert '<dateval val=""' not in date_xml(d)
    assert '<dateval val=""' not in db_to_xml(GrampsDb.from_objects([{**blank("Event", "e3", "E3"),
                                                             "date": date_to_gramps("BEF ?")}]), "1.7.1")
