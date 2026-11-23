"""Contrôles purs de portée d'un élément de contexte (#321) : période de vie, lieux, mention d'échelle."""

from __future__ import annotations

import pytest

from genealogiste_mcp.contexte.modeles import MENTION_TENDANCE, ElementContexte
from genealogiste_mcp.contexte.portee import (
    LieuDeVie,
    Periode,
    controler,
    dans_la_periode,
    dans_les_lieux,
    mention,
)

VIE = Periode(1881, 1906)
LIEUX = [LieuDeVie(commune="Courrières", departement="Pas-de-Calais", region="Nord-Pas-de-Calais", pays="France",
                   pays_naturel="Bassin minier du Nord-Pas-de-Calais"),
         LieuDeVie(commune="Anzin", departement="59", pays="France")]


def el(echelle="commune", lieu="Courrières, Pas-de-Calais", de=1906, a=None) -> ElementContexte:
    portee = {"lieu": lieu, "echelle": echelle, "de": de}
    if a is not None:
        portee["a"] = a
    return ElementContexte.from_dict({
        "enonce": "x", "type": "evenement", "portee": portee,
        "source": {"citation": "c", "identifiant": "hal-01234567", "nature": "secondaire_savante",
                   "consulte_le": "2026-11-23"},
        "rattachement": {"personne": "I1", "niveau": "non_demontre", "justification": ""}})


@pytest.mark.parametrize("de, a, attendu", [
    (1906, None, True), (1881, None, True), (1870, 1871, False), (1907, 1910, False), (1870, 1885, True),
    (1900, 1920, True), (1850, 1950, True), (1880, None, False),
])
def test_dans_la_periode(de, a, attendu):
    assert dans_la_periode(el(de=de, a=a), VIE) is attendu


def test_periode_tuple_et_validation():
    assert dans_la_periode(el(), (1900, 1910))
    with pytest.raises(ValueError):
        Periode(1910, 1900)


@pytest.mark.parametrize("echelle, lieu, attendu", [
    ("commune", "Courrières, Pas-de-Calais", True),
    ("commune", "courrieres", True),
    ("commune", "Lens, Pas-de-Calais", False),
    ("commune", "Anzin (59)", True),
    ("departement", "Pas-de-Calais", True),
    ("departement", "62", True),
    ("departement", "Nord", True),  # Anzin, code 59
    ("departement", "Somme", False),
    ("region", "Nord-Pas-de-Calais", True),
    ("region", "Picardie", False),
    ("pays", "Bassin minier du Nord-Pas-de-Calais", True),
    ("pays", "Boulonnais", False),
    ("nation", "France", True),
    ("nation", "États-Unis", False),
    ("international", "Europe", True),
])
def test_dans_les_lieux(echelle, lieu, attendu):
    assert dans_les_lieux(el(echelle=echelle, lieu=lieu), LIEUX) is attendu


def test_lieu_inconnu_jamais_compatible():
    assert not dans_les_lieux(el(echelle="region", lieu="Nord-Pas-de-Calais"), [LieuDeVie(commune="Anzin")])
    assert not dans_les_lieux(el(), [])


def test_mention_echelle_superieure_a_la_commune():
    assert mention(el()) == ""
    for echelle in ("pays", "departement", "region", "nation", "international"):
        assert mention(el(echelle=echelle, lieu="France")) == MENTION_TENDANCE
    assert MENTION_TENDANCE == "tendance générale, ne prouve rien pour l'individu"


def test_controler():
    assert controler(el(), VIE, LIEUX) == {"retenu": True, "motifs": [], "mention": ""}
    r = controler(el(echelle="commune", lieu="Lens", de=1870, a=1871), VIE, LIEUX)
    assert r["retenu"] is False and len(r["motifs"]) == 2
    assert any("période" in x for x in r["motifs"]) and any("lieu" in x for x in r["motifs"])
    assert controler(el(echelle="nation", lieu="France"), VIE, LIEUX)["mention"] == MENTION_TENDANCE
