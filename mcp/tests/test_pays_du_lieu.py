"""Pays du lieu (#283) : une seule résolution, réutilisée par toutes les pistes ; aucune série d'archives
départementales françaises pour un lieu hors de France ; pays inconnu dit, jamais présumé français."""

from __future__ import annotations

import pytest

from genealogiste_mcp import archives, server
from genealogiste_mcp.export.fiche import fiche_markdown
from genealogiste_mcp.fr_sources import next_source_hint
from genealogiste_mcp.gedcom.mapping import read_gedcom
from genealogiste_mcp.models import Place
from genealogiste_mcp.normalize.pays import pays_du_lieu
from genealogiste_mcp.types_documents import SERIES

CHARLEROI_US = "Charleroi, Washington, Pennsylvania, États-Unis"
CHARLEROI_BE = "Charleroi, Hainaut, Belgique"
COTES_AD = ("série E", "4 E", "3 Q", "série U", "série M", "série R")


def _sans_cote_ad(sources: list[dict]) -> None:
    for s in sources:
        assert s["cote_typique"] not in SERIES.values(), s
        assert not any(c in s["cote_typique"] for c in COTES_AD), s


# ---------------------------------------------------------------------------- résolution

@pytest.mark.parametrize("lieu,code,nom", [
    (CHARLEROI_US, "US", "États-Unis"),
    ("Charleroi, Washington County, Pennsylvania, USA", "US", "États-Unis"),
    ("Charleroi, PA, United States of America", "US", "États-Unis"),
    (CHARLEROI_BE, "BE", "Belgique"),
    ("Charleroi, Hainaut, Belgium", "BE", "Belgique"),
    ("Delémont, Jura, Suisse", "CH", "Suisse"),
    ("Paris, Lamar, Texas, U.S.A.", "US", "États-Unis"),
])
def test_pays_etranger_par_libelle(lieu, code, nom):
    p = pays_du_lieu(lieu)
    assert (p["code"], p["nom"], p["provenance"], p["france"]) == (code, nom, "libelle", False)


@pytest.mark.parametrize("lieu,detail", [
    ("Fenain, Nord", "Nord"),  # cas courant : pas de pays saisi
    ("Fenain, Nord, France", "France"),
    ("Somain (59)", "59"),
    ("Rochefort, Charente-Inférieure", "Charente-Inférieure"),  # ancien nom de département
    ("Charleroi, Nord", "Nord"),  # commune homonyme : le département décide, pas le nom de la commune
])
def test_france_par_libelle(lieu, detail):
    p = pays_du_lieu(lieu)
    assert (p["code"], p["nom"], p["provenance"], p["france"]) == ("FR", "France", "libelle", True)
    assert detail in p["detail"]


@pytest.mark.parametrize("lieu", ["Pointe-à-Pitre, Guadeloupe", "Saint-Denis, La Réunion",
                                  "Fort-de-France, Martinique, France", "Cayenne, Guyane"])
def test_dom_vaut_france(lieu):
    p = pays_du_lieu(lieu)
    assert p["code"] == "FR" and p["france"] is True


@pytest.mark.parametrize("lieu", ["Charleroi", "Fenain", "Saint-Jean-d'Angély", "Charleroi, Washington",
                                  "Charleroi, Washington, Pennsylvania", ""])
def test_pays_inconnu_jamais_presume_francais(lieu):
    p = pays_du_lieu(lieu)
    assert (p["code"], p["provenance"], p["france"]) == ("", "inconnu", None)
    assert p["nom"] == ""


def test_code_insee_vaut_france_et_prime_sur_le_libelle():
    p = pays_du_lieu(Place(nom="Rochefort", code_insee="17299"))
    assert (p["code"], p["provenance"], p["france"]) == ("FR", "code_insee", True)
    dom = pays_du_lieu(Place(nom="Les Abymes", code_insee="97101"))
    assert dom["code"] == "FR" and dom["provenance"] == "code_insee"
    corse = pays_du_lieu({"nom": "Ajaccio", "code_insee": "2A004"})
    assert corse["code"] == "FR"


def test_code_cog_pays_etranger():
    p = pays_du_lieu(Place(nom="Charleroi", code_insee="99131"))
    assert (p["code"], p["nom"], p["provenance"], p["france"]) == ("BE", "Belgique", "code_insee", False)
    inconnu = pays_du_lieu(Place(nom="Quelque part", code_insee="99999"))
    assert inconnu["provenance"] == "code_insee" and inconnu["france"] is False and inconnu["code"] == ""


def test_hierarchie_gedcom_form():
    ged = """0 HEAD
1 GEDC
2 VERS 7.0
0 @I1@ INDI
1 NAME Jean /MARTIN/
1 DEAT
2 DATE 1946
2 PLAC Charleroi, Washington, Pennsylvania, Nouvelle-Zemble
3 FORM City, County, State, Country
0 TRLR
"""
    t = read_gedcom(ged)[0]
    lieu = t.personnes["I1"].events("DEAT")[0].lieu
    p = pays_du_lieu(lieu)
    # pays hors de la table fermée : la hiérarchie le désigne quand même comme pays
    assert (p["code"], p["nom"], p["provenance"], p["france"]) == ("", "Nouvelle-Zemble", "hierarchie", False)


def test_hierarchie_gramps():
    p = pays_du_lieu({"nom": "Charleroi, Hainaut, België", "pays": "België"})
    assert (p["code"], p["provenance"], p["france"]) == ("BE", "hierarchie", False)
    fr = pays_du_lieu({"nom": "Fenain, Nord, France", "pays": "France"})
    assert (fr["code"], fr["provenance"], fr["france"]) == ("FR", "hierarchie", True)


def test_lecture_gramps_renseigne_le_pays_de_la_hierarchie():
    from genealogiste_mcp.gramps.mapping import GrampsDb, _Reader
    from genealogiste_mcp.gramps.types import gtype

    db = GrampsDb()
    for h, nom, typ, parent in (("P3", "United States", "Country", None), ("P2", "Pennsylvania", "State", "P3"),
                                ("P1", "Charleroi", "City", "P2")):
        db.put({"_class": "Place", "handle": h, "gramps_id": h, "title": "", "name": {"value": nom},
                "placeref_list": [{"ref": parent}] if parent else [], "place_type": gtype("PlaceType", typ)})
    pl = _Reader(db).place("P1")
    assert pl.nom == "Charleroi, Pennsylvania, United States" and pl.pays == "United States"
    p = pays_du_lieu(pl)
    assert (p["code"], p["provenance"]) == ("US", "hierarchie")


def test_api_stable():
    p = pays_du_lieu(CHARLEROI_US)
    assert set(p) == {"code", "nom", "provenance", "france", "detail"}
    assert pays_du_lieu(None)["provenance"] == "inconnu"


# ---------------------------------------------------------------------------- pistes

def test_prochaine_source_charleroi_us_sans_serie_ad(app):
    r = server.prochaine_source("DEAT", "1946", CHARLEROI_US)
    _sans_cote_ad(r)
    assert all(s["pays"] == {"code": "US", "nom": "États-Unis", "provenance": "libelle"} for s in r)
    assert any("source à identifier" in s["cote_typique"] for s in r)
    assert any("Services-archives" in s.get("en_ligne", "") for s in r)
    transcription = next(s for s in r if "ranscription" in s["source"])
    assert "dernier domicile" in transcription["source"] and "consulaire" in transcription["source"]
    assert "sans garantie" in transcription["pourquoi"]


def test_prochaine_source_charleroi_be_sans_serie_ad(app):
    for fait in ("BIRT", "DEAT", "MARR", "FILIATION", "OCCU", "MILI", "EVEN"):
        r = server.prochaine_source(fait, "1900", CHARLEROI_BE)
        _sans_cote_ad(r)
        assert r and r[0]["pays"]["code"] == "BE"


def test_prochaine_source_france_inchangee_hors_mention_du_pays(app):
    r = server.prochaine_source("DEAT", "1885", "Fenain, Nord")
    base = next_source_hint("DEAT", "1885", "")
    assert [s["cote_typique"] for s in r] == [s["cote_typique"] for s in base]
    assert r[0]["source"] == "Acte de décès de Fenain"
    assert r[0]["pays"] == {"code": "FR", "nom": "France", "provenance": "libelle"}
    assert "condition" not in r[0]


def test_prochaine_source_commune_francaise_homonyme(app):
    r = server.prochaine_source("DEAT", "1946", "Charleroi, Nord")
    assert r[0]["cote_typique"] == SERIES["etat_civil"] and r[0]["pays"]["code"] == "FR"


def test_prochaine_source_pays_inconnu_conditionne(app):
    r = server.prochaine_source("DEAT", "1885", "Charleroi")
    ad = [s for s in r if s.get("condition")]
    assert ad and all(s["condition"] == "si le lieu est en France" for s in ad)
    assert all("si le lieu est en France" in s["cote_typique"] for s in ad)
    assert r[0]["pays"] == {"code": "", "nom": "", "provenance": "inconnu"}


def test_prochaine_source_sans_lieu_inchangee(app):
    r = server.prochaine_source("BIRT", "1850")
    assert all("pays" not in s and "condition" not in s for s in r)


def test_cotes_a_consulter_charleroi_us(app):
    c = server.cotes_a_consulter("DEAT", "1946", CHARLEROI_US)
    assert c["pays"]["code"] == "US" and c["pays"]["provenance"] == "libelle"
    _sans_cote_ad(c["sources"])
    assert c["series"] == {} and c["service_archives"] is None
    assert "Archives départementales" not in c["service"]
    assert "source à identifier" in c["service"]
    assert "sites_tiers" not in c


def test_cotes_a_consulter_pays_inconnu(app):
    c = server.cotes_a_consulter("DEAT", "1946", "Charleroi")
    assert c["pays"]["provenance"] == "inconnu"
    assert "si le lieu est en France" in c["service"]
    assert "préciser" in c["pays_a_preciser"]


def test_cotes_a_consulter_france_inchange(app):
    c = server.cotes_a_consulter("BIRT", "1926", "Somain (59)")
    assert c["service"] == "Archives départementales du Nord" and c["pays"]["code"] == "FR"
    assert c["series"] == SERIES and "pays_a_preciser" not in c


def test_archives_service_lieu_etranger(app):
    r = server.archives_service(lieu=CHARLEROI_US, document="deces", annee=1946)
    assert r["pays"]["code"] == "US" and "code" not in r and "erreur" not in r
    assert "Services-archives" in r["renvoi"] and "transcription" in r["piste_francaise"].lower()
    # un département homonyme dans un lieu étranger ne désigne pas d'AD française
    assert "code" not in server.archives_service(lieu="Delémont, Jura, Suisse")


def test_archives_service_pays_inconnu_et_france(app):
    r = server.archives_service(lieu="Charleroi")
    assert "erreur" in r and r["pays"]["provenance"] == "inconnu"
    assert server.archives_service(lieu="Somain (59)")["code"] == "AD59"


def test_communicabilite_lieu_etranger(app):
    r = server.communicabilite("deces", "1946", lieu=CHARLEROI_US)
    assert r["pays"]["code"] == "US"
    assert "service_archives" not in r and "si_pas_en_ligne" not in r
    assert r["communicable"] is None and r["communicable_si_transcrit_en_france"] is True
    assert "Code du patrimoine" in r["hors_france"]


def test_communicabilite_france_garde_le_service(app):
    r = server.communicabilite("naissance", "1926", lieu="Somain (59)")
    assert r["pays"]["code"] == "FR" and r["service_archives"]["code"] == "AD59"


def test_liens_recherche_lieu_etranger_sans_ad(app):
    links = server.liens_recherche("MARTIN", "Jean", "1881", "Delémont, Jura, Suisse")["liens"]
    assert not any("Jura" in x["site"] or "Archives départementales" in x["site"] for x in links)


GED_CHARLEROI = """0 HEAD
1 GEDC
2 VERS 7.0
0 @I1@ INDI
1 NAME Louis /DUPONT/
1 SEX M
1 BIRT
2 DATE 1881
2 PLAC Lens, Pas-de-Calais, France
1 DEAT
2 DATE 1946
2 PLAC Charleroi, Washington, Pennsylvania, États-Unis
0 TRLR
"""


def test_fiche_prochaines_sources_lieu_etranger():
    t = read_gedcom(GED_CHARLEROI)[0]
    fiche = fiche_markdown(t, "I1")
    section = fiche.split("## Prochaines sources à consulter")[1]
    deces = next(x for x in section.splitlines() if x.startswith("- décès"))
    assert "série E" not in deces and "4 E" not in deces
    assert "États-Unis" in deces and "libelle" in deces
    naissance = next(x for x in section.splitlines() if x.startswith("- naissance"))
    assert "série E" in naissance and "France" in naissance


def test_arbre_fiche_outil(app):
    t = read_gedcom(GED_CHARLEROI)[0]
    app.store.write(t)
    app.store.commit("charleroi")
    fiche = server.arbre_fiche("I1")
    deces = next(x for x in fiche.splitlines() if x.startswith("- décès"))
    assert "série E" not in deces and "États-Unis" in deces


def test_archives_service_direct_ne_presume_pas(app):
    assert archives.service(lieu=CHARLEROI_BE)["pays"]["code"] == "BE"
