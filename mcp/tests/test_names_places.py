import pytest

from genealogiste_mcp.normalize.names import (
    given_similarity,
    normalize_given,
    normalize_name,
    phonetic_fr,
    split_dit,
    strip_particles,
    surname_similarity,
)
from genealogiste_mcp.normalize.places import normalize_place, place_similarity


@pytest.mark.parametrize("a,b", [
    ("Lefebvre", "Lefèvre"), ("Thibault", "Thibaut"), ("Dupont", "Dupond"), ("Renaud", "Renault"),
    ("Rousseau", "Roussot"), ("Faucher", "Fauchez"),
])
def test_spelling_variants(a, b):
    assert surname_similarity(a, b)["score"] >= 0.9


def test_different_names():
    assert surname_similarity("Durand", "Bernard")["score"] < 0.8


def test_latin_given_names():
    assert normalize_given("Joannes") == ["jean"]
    assert normalize_given("Petrus") == ["pierre"]
    assert normalize_given("Joannes Baptista") == ["jean", "baptiste"]
    assert given_similarity("Joannem", "Jean")["score"] == 1.0
    assert given_similarity("Jehan", "Jean")["score"] == 1.0


def test_usual_given_name_subset():
    assert given_similarity("Jean Pierre", "Pierre")["score"] >= 0.9


def test_dit_and_particles():
    assert split_dit("MARTIN dit LAFLEUR") == ("MARTIN", ["LAFLEUR"])
    assert strip_particles("de la Fontaine") == ("fontaine", "de la")
    assert surname_similarity("MARTIN dit LAFLEUR", "Lafleur")["score"] == 1.0
    n = normalize_name("Jean /MARTIN dit LAFLEUR/")
    assert n["nom"] == "MARTIN" and n["dit"] == ["LAFLEUR"]


def test_latin_surname():
    assert surname_similarity("Martinus", "Martin")["score"] >= 0.9


def test_phonetic_key_stable():
    assert phonetic_fr("Lefebvre") == phonetic_fr("Lefèvre")


def test_place_normalization():
    p = normalize_place("St Jean d'Angély (17)")
    assert p["commune"] == "Saint Jean d'Angély" and p["departement_code"] == "17"
    assert normalize_place("Rochefort, Charente-Inférieure, France")["departement_code"] == "17"
    assert place_similarity("Paroisse de Saint-Pierre", "St Pierre")["score"] == 1.0
    assert place_similarity("Rochefort (17)", "Rochefort (73)")["score"] < 0.5
