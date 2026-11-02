import pytest

from genealogiste_mcp.normalize.dates import (
    birth_from_age,
    compare,
    convert,
    french_to_jdn,
    gregorian_to_jdn,
    jdn_to_french,
    jdn_to_gregorian,
    parse_age,
    parse_date,
)


@pytest.mark.parametrize("text,iso", [
    ("12 vendémiaire an III", "1794-10-03"),
    ("1er vendémiaire an I", "1792-09-22"),
    ("10 frimaire an XII", "1803-12-02"),  # sacre de Napoléon
    ("FRENCH_R 1 NIVO 14", "1805-12-22"),
    ("@#DFRENCH R@ 4 COMP 3", "1795-09-20"),
    ("JULIAN 4 OCT 1582", "1582-10-14"),
    ("12 mars 1820", "1820-03-12"),
    ("12/03/1820", "1820-03-12"),
    ("19201212", "1920-12-12"),
])
def test_conversions(text, iso):
    assert parse_date(text).to_dict()["debut_gregorien"] == iso


def test_sextile_years():
    # an III est sextile : le 6e jour complémentaire existe ; pas en an II
    assert parse_date("FRENCH_R 6 COMP 3") is not None
    assert parse_date("FRENCH_R 6 COMP 2") is None


def test_roundtrip_french():
    for j in range(gregorian_to_jdn(1792, 9, 22), gregorian_to_jdn(1806, 1, 1), 37):
        an, m, d = jdn_to_french(j)
        assert french_to_jdn(an, m, d) == j


def test_jdn_gregorian_roundtrip():
    for y, m, d in [(1600, 2, 29), (1900, 3, 1), (2000, 2, 29), (1792, 9, 22)]:
        assert jdn_to_gregorian(gregorian_to_jdn(y, m, d)) == (y, m, d)


def test_approx_tolerance():
    g = parse_date("vers 1820")
    assert g.gedcom() == "ABT 1820"
    d = g.to_dict()
    assert d["annee_min"] == 1818 and d["annee_max"] == 1822


def test_compare_tolerance():
    a, b = parse_date("1820"), parse_date("1822")
    assert compare(a, b)["compatible"]
    assert not compare(a, parse_date("1825"))["compatible"]
    assert compare(parse_date("ABT 1820"), parse_date("1823"))["compatible"]


def test_gedcom551_output():
    assert parse_date("12 vendémiaire an III").gedcom(5) == "@#DFRENCH R@ 12 VEND 3"
    assert parse_date("BET 1820 AND 1825").gedcom() == "BET 1820 AND 1825"


def test_age_recalculation():
    g = birth_from_age(parse_date("4 JAN 1885"), *parse_age("64 ans"))
    d = g.to_dict()
    assert d["annee_min"] <= 1820 <= d["annee_max"]


def test_parse_age_variants():
    assert parse_age("45y 3m") == (45.0, 3.0, 0.0)
    assert parse_age("45 ans") == (45.0, 0.0, 0.0)
    assert parse_age("3 mois") == (0.0, 3.0, 0.0)


def test_convert_gives_equivalents():
    c = convert("22 SEP 1792")
    assert c["equivalent_republicain"] == "1er vendémiaire an I"
    assert c["jour_semaine"] == "samedi"
    assert c["equivalent_julien"] == "11/09/1792"


def test_unparseable():
    assert parse_date("n'importe quoi") is None
    assert "erreur" in convert("blabla")
