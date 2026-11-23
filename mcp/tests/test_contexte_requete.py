"""Requêtes de contexte construites depuis l'arbre (#321) : lieu, période, métier ; jamais l'identité."""

from __future__ import annotations

from urllib.parse import urlencode

import pytest

from genealogiste_mcp.contexte.portee import LieuDeVie, Periode
from genealogiste_mcp.contexte.requete import RequeteContexte, depuis_personne, residus_identite
from genealogiste_mcp.gedcom.mapping import read_gedcom

GED = """0 HEAD
1 GEDC
2 VERS 7.0
0 @S1@ SOUR
1 TITL État civil
0 @I9@ INDI
1 NAME Louis Émile /LEFEBVRE/
2 NICK Lolo
1 SEX M
1 BIRT
2 DATE 2 FEB 1881
2 PLAC Courrières, Pas-de-Calais, France
2 SOUR @S1@
1 OCCU mineur
2 DATE 1901
2 PLAC Courrières, Pas-de-Calais, France
2 SOUR @S1@
1 RESI
2 DATE 1906
2 PLAC Anzin, Nord, France
2 SOUR @S1@
1 RESI
2 DATE 1925
2 PLAC Scranton, Pennsylvania, USA
2 SOUR @S1@
1 OCCU charpentier
2 DATE 1930
1 DEAT
2 DATE 1946
2 PLAC Scranton, Pennsylvania, USA
1 RESI
2 DATE 1890
2 PLAC Lille, Nord, France
2 SOUR @S1@
3 NOTE réfuté ci-dessous
0 TRLR
"""


@pytest.fixture
def arbre():
    t = read_gedcom(GED)[0]
    # résidence à Lille réfutée : jamais utilisée
    from genealogiste_mcp.models import Assertion
    e = next(e for e in t.person("I9").evenements if e.type == "RESI" and e.date == "1890")
    e.statut_manuel = Assertion("refute", "homonyme")
    return t


def test_depuis_personne_faits_sources_seulement(arbre):
    r = depuis_personne(arbre, "I9")
    assert r.periode == Periode(1881, 1925)  # décès non sourcé : la période s'arrête au dernier fait sourcé
    assert r.metiers == ["mineur"]  # « charpentier » non sourcé
    assert [x.commune for x in r.lieux] == ["Courrières", "Anzin", "Scranton"]
    assert r.lieux[0] == LieuDeVie(commune="Courrières", departement="Pas-de-Calais", pays="France", de=1881, a=1901)
    assert r.lieux[1].departement == "Nord" and (r.lieux[1].de, r.lieux[1].a) == (1906, 1906)
    assert all(x.commune != "Lille" for x in r.lieux)  # fait réfuté écarté


def test_inclure_non_sources(arbre):
    r = depuis_personne(arbre, "I9", sources_seulement=False)
    assert r.periode == Periode(1881, 1946) and r.metiers == ["mineur", "charpentier"]


def test_pays_et_region_injectes(arbre):
    r = depuis_personne(arbre, "I9", pays_du_lieu=lambda lieu: "États-Unis" if "USA" in lieu else "France",
                        region_du_lieu=lambda lieu: "Nord-Pas-de-Calais" if "France" in lieu else "")
    assert r.lieux[2].pays == "États-Unis" and r.lieux[0].region == "Nord-Pas-de-Calais"
    assert r.lieux[2].region == ""


def test_aucune_identite_dans_la_requete(arbre):
    r = depuis_personne(arbre, "I9")
    tout = " ".join(r.termes()) + " " + urlencode(r.parametres(), doseq=True) + " " + repr(r.to_dict())
    assert residus_identite(tout, arbre, "I9") == []
    for interdit in ("Louis", "Émile", "Emile", "LEFEBVRE", "Lefebvre", "Lolo", "I9"):
        assert interdit.lower() not in tout.lower()
    assert set(r.to_dict()) == {"lieux", "periode", "metiers"}


def test_residus_identite_detecte(arbre):
    url = "https://api.example.org/search?q=Lefebvre+Courri%C3%A8res+1906"
    assert residus_identite(url, arbre, "I9") == ["lefebvre"]
    assert residus_identite("q=louis%20emile", arbre, "I9") == ["emile", "louis"]
    assert residus_identite("personne=I9", arbre, "I9") == ["i9"]
    assert residus_identite("q=Courrières mineur 1881-1906", arbre, "I9") == []


def test_termes_et_parametres():
    r = RequeteContexte(lieux=[LieuDeVie(commune="Courrières", departement="Pas-de-Calais", region="",
                                         pays="France", de=1881, a=1906)],
                        periode=Periode(1881, 1906), metiers=["mineur"])
    assert r.termes() == ["Courrières", "Pas-de-Calais", "France", "mineur"]
    assert r.parametres() == {"communes": ["Courrières"], "departements": ["Pas-de-Calais"], "regions": [],
                              "pays_naturels": [], "pays": ["France"], "de": 1881, "a": 1906, "metiers": ["mineur"]}


def test_personne_sans_fait_date(arbre):
    from genealogiste_mcp.models import Person
    arbre.personnes["I10"] = Person(id="I10")
    r = depuis_personne(arbre, "I10")
    assert r.periode is None and r.lieux == [] and r.metiers == []
