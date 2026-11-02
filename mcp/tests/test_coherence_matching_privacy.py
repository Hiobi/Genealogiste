from datetime import date

from genealogiste_mcp.coherence import check_person, check_tree
from genealogiste_mcp.matching import compare_persons, compare_profiles
from genealogiste_mcp.models import Event, Person
from genealogiste_mcp.privacy import is_living, mask_tree


def test_birth_after_mother_death(tree):
    codes = {i["code"] for i in check_tree(tree)}
    assert "naissance_apres_deces_mere" in codes


def test_declared_age_mismatch(tree):
    tree.personnes["I1"].events("DEAT")[0].age = "40y"
    issues = check_person(tree, "I1")
    assert any(i["code"] == "age_declare" for i in issues)


def test_death_before_birth(tree):
    tree.personnes["I4"].evenements.append(Event("DEAT", "1800"))
    assert any(i["code"] == "deces_avant_naissance" for i in check_person(tree, "I4"))


def test_old_mother(tree):
    tree.personnes["I2"].events("BIRT")[0].date = "1790"
    issues = check_person(tree, "I3")
    assert any(i["code"] == "age_mere" for i in issues)


def test_homonyms_different_fathers(tree):
    """Deux Jean MARTIN nés à Rochefort vers 1820-1821, pères différents : homonymes."""
    r = compare_persons(tree, "I1", "I4")
    assert r["verdict"].startswith("homonymes")
    assert "pere différent(e)" in r["contradictions"]
    assert r["score"] <= 35


def test_same_person_high_score():
    a = {"prenoms": "Joannes", "nom": "Martini", "sexe": "M", "naissance": {"date": "12 MAR 1820", "lieu": "Rochefort"},
         "deces": {"date": "1885", "lieu": "Rochefort"}, "pere": {"prenoms": "Jacques", "nom": "Martin"},
         "mere": {"prenoms": "Anne", "nom": "Roy"}}
    b = {"prenoms": "Jean", "nom": "Martin", "sexe": "M", "naissance": {"date": "ABT 1820", "lieu": "Rochefort (17)"},
         "deces": {"date": "4 JAN 1885", "lieu": "Rochefort"}, "pere": {"prenoms": "Jacobus", "nom": "Martin"},
         "mere": {"prenoms": "Anna", "nom": "Roy"}}
    r = compare_profiles(a, b)
    assert r["score"] >= 85 and not r["contradictions"]


def test_sparse_data_never_conclusive():
    r = compare_profiles({"prenoms": "Jean", "nom": "Martin"}, {"prenoms": "Jean", "nom": "Martin"})
    assert r["score"] <= 70
    assert "Jamais de fusion automatique" in r["regle"]


def test_incompatible_birth_dates():
    r = compare_profiles({"prenoms": "Jean", "nom": "Martin", "naissance": {"date": "1820"}},
                         {"prenoms": "Jean", "nom": "Martin", "naissance": {"date": "1835"}})
    assert r["contradictions"] and r["score"] <= 35


def test_living_rules(tree):
    today = date(2026, 11, 2)
    assert is_living(tree, tree.personnes["I9"], today)["vivant"] is True
    assert is_living(tree, tree.personnes["I3"], today)["vivant"] is False
    unknown = Person("I99")
    tree.personnes["I99"] = unknown
    assert is_living(tree, unknown, today)["vivant"] is True  # aucune date : prudence
    unknown.vivant = "N"
    assert is_living(tree, unknown, today)["vivant"] is False


def test_mask_tree(tree):
    masked, living = mask_tree(tree, date(2026, 11, 2))
    assert "I9" in living
    assert masked.personnes["I9"].nom_principal.prenoms == "Vivant"
    assert masked.personnes["I9"].evenements == []
    assert tree.personnes["I9"].evenements  # original intact
