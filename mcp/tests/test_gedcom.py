from genealogiste_mcp.gedcom.core import parse_lines
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom


def test_roundtrip_is_stable(famille_text):
    tree, info = read_gedcom(famille_text)
    assert info["personnes"] == 8 and info["familles"] == 3 and info["sources"] == 4
    out = write_gedcom(tree)
    assert write_gedcom(read_gedcom(out)[0]) == out


def test_citation_classification_preserved(tree):
    birth = tree.personnes["I1"].events("BIRT")[0]
    c = birth.citations[0]
    assert (c.source, c.type_source, c.information, c.qualite) == ("S1", "originale", "primaire", 3)
    assert birth.citations[2].preuve == "indirecte"
    assert tree.sources["S2"].original == "S1"
    assert tree.sources["S1"].cote == "2 E 299"
    assert birth.lieu.code_insee == "17299"


def test_filiation_citations(tree):
    link = tree.familles["F1"].child("I3")
    assert link.citations and link.citations[0].source == "S1"


def test_republican_date_kept(tree):
    assert tree.personnes["I6"].events("BIRT")[0].date == "FRENCH_R 12 VEND 3"


def test_import_551(fixtures):
    tree, info = read_gedcom((fixtures / "legacy551.ged").read_text())
    assert info["version_source"] == "5.5.x"
    p = tree.personnes["P1"]
    assert p.events("BIRT")[0].date == "JULIAN 1 JAN 1700"
    assert p.events("DEAT")[0].date == "FRENCH_R 4 COMP 3"
    assert p.notes[0] == "Première ligne\nseconde ligne suite"
    assert tree.familles["FA"].epoux == "P1"


def test_export_551(tree):
    out = write_gedcom(tree, 5)
    assert "2 VERS 5.5.1" in out and "@#DFRENCH R@ 12 VEND 3" in out
    assert "SCHMA" not in out and "_UID" in out
    # relu sans perte
    t2 = read_gedcom(out)[0]
    assert t2.personnes["I6"].events("BIRT")[0].date == "FRENCH_R 12 VEND 3"


def test_cont_lines():
    nodes = parse_lines("0 @N1@ SNOTE ligne1\n1 CONT ligne2\n0 TRLR\n")
    assert nodes[0].value == "ligne1\nligne2"


def test_unknown_tags_preserved():
    text = "0 HEAD\n1 GEDC\n2 VERS 7.0\n0 @I1@ INDI\n1 NAME A /B/\n1 _PERSO valeur\n2 _SOUS x\n0 TRLR\n"
    out = write_gedcom(read_gedcom(text)[0])
    assert "1 _PERSO valeur\n2 _SOUS x" in out
