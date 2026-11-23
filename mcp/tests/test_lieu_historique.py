"""#287 : lieu_historique, géographie historique d'un lieu à une date, niveau par niveau.

Réponses réelles réduites rejouées par respx (aucun accès réseau) : tests/fixtures/contexte/reponses/<service>/
(MANIFESTE.json : URL, date, statut). COG : extrait des fichiers publics (reponses/COG-INSEE et fixtures/cog)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from genealogiste_mcp import server
from genealogiste_mcp.contexte import lieux

REP = Path(__file__).parent / "fixtures" / "contexte" / "reponses"
COG = Path(__file__).parent / "fixtures" / "cog"
CODE = "62133"  # Billy-Montigny, cas témoin (code obtenu par geo_commune le 2026-11-23)


def _csv(*chemins: Path) -> str:
    lignes = [p.read_text(encoding="utf-8").splitlines() for p in chemins]
    return "\n".join([lignes[0][0], *(x for f in lignes for x in f[1:])]) + "\n"


def _csw(request: httpx.Request) -> httpx.Response:
    ident = parse_qs(urlsplit(str(request.url)).query)["ID"][0]
    return httpx.Response(200, text=(REP / "IGN-GEOPLATEFORME" / f"csw_{ident}.xml").read_text(encoding="utf-8"))


@pytest.fixture
def routes(app):
    with respx.mock(assert_all_called=False) as r:
        r.get(app.config.cog_communes_url).respond(200, text=_csv(REP / "COG-INSEE" / "v_commune_depuis_1943.csv",
                                                                  COG / "communes.csv"))
        r.get(app.config.cog_mvt_url).respond(200, text=_csv(REP / "COG-INSEE" / "v_mvt_commune_2024.csv",
                                                             COG / "mouvements.csv"))
        r.get(f"https://geo.api.gouv.fr/communes/{CODE}").respond(
            200, json=json.loads((REP / "API-GEO" / "communes_62133.json").read_text()))
        r.get(f"{lieux.MELODI}/catalog/{lieux.JEU_POPULATION}").respond(
            200, json=json.loads((REP / "INSEE-MELODI" / "catalog_DS_POPULATIONS_HISTORIQUES.json").read_text()))
        r.get(f"{lieux.MELODI}/data/{lieux.JEU_POPULATION}", params={"GEO": f"2025-COM-{CODE}"}).respond(
            200, json=json.loads((REP / "INSEE-MELODI" / "data_DS_POPULATIONS_HISTORIQUES_GEO_2025-COM-62133.json")
                                 .read_text()))
        r.get(lieux.WMTS, params={"REQUEST": "GetCapabilities"}).respond(
            200, text=(REP / "IGN-GEOPLATEFORME" / "GetCapabilities.xml").read_text(encoding="utf-8"))
        r.get("https://data.geopf.fr/csw").mock(side_effect=_csw)
        r.get(lieux.SPARQL).respond(200, json=json.loads((REP / "WIKIDATA" / "sparql_P374_62133.json").read_text()))
        yield r


def _niveau(res: dict, nom: str) -> dict:
    return next(n for n in res["niveaux"] if n["niveau"] == nom)


def _chaque_niveau_source_et_periode(res: dict) -> None:
    for n in [*res["niveaux"], res["population"]]:
        assert {"source", "periode_de_validite", "valeur"} <= set(n), n
        if n["valeur"] == lieux.INCONNU:
            assert n["source"] is None and n["periode_de_validite"] is None and n["statut"] == "à établir", n
            assert n["consultation"], n
        else:
            assert n["source"] and n["periode_de_validite"], n


def test_cas_temoin_1906_avant_le_cog(app, routes):
    res = server.lieu_historique("Billy-Montigny, Pas-de-Calais", "1906")
    _chaque_niveau_source_et_periode(res)
    assert res["commune"]["code_insee"] == CODE and res["pays"]["code"] == "FR"
    for niveau in ("nom", "departement", "canton", "arrondissement", "district", "province", "generalite",
                   "bailliage_ou_senechaussee", "diocese"):
        assert _niveau(res, niveau)["valeur"] == "inconnu", niveau
    assert res["population"]["valeur"] == "inconnu" and "1968" in res["population"]["motif"]
    fiche = res["consultation"][0]
    assert fiche["url"] == "http://cassini.ehess.fr/cassini/fr/html/fiche.php?select_resultat=29186"
    assert "Q772803" in fiche["trouve_par"]
    assert any(c["url"] == lieux.LIENS["nakala_cassini"] for c in res["consultation"])
    # 1906 : aucune carte contemporaine ; la plus proche avant (état-major 1820-1866), la plus proche après (1950)
    retenues = {c["couche"]: c for c in res["cartes"]["retenues"]}
    assert set(retenues) == {"GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR40", "GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN50.1950",
                             "ORTHOIMAGERY.ORTHOPHOTOS.1950-1965"}
    em = retenues["GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR40"]
    assert em["periode_de_validite"]["debut"] == "1820" and em["periode_de_validite"]["fin"] == "1866"
    q = parse_qs(urlsplit(em["lien"]).query)
    assert q["LAYER"] == ["GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR40"] and q["TILEMATRIXSET"] == ["PM_6_15"]
    assert q["TILEMATRIX"] == ["14"] and q["REQUEST"] == ["GetTile"] and q["FORMAT"] == ["image/jpeg"]
    # tuile du centre de la commune (2.9068 E, 50.4152 N) au niveau 14, recalculée par la formule de tuilage
    # « slippy map » (x = (lon + 180) / 360 · 2^z ; y = (1 - asinh(tan(lat)) / π) / 2 · 2^z)
    assert (int(q["TILECOL"][0]), int(q["TILEROW"][0])) == (8324, 5527)
    autres = {c["couche"]: c["motif"] for c in res["cartes"]["autres"]}
    assert "emprise" in autres["GEOGRAPHICALGRIDSYSTEMS.ETATMAJOR10"]  # environs de Paris seulement
    assert res["cartes"]["source"]["conditions"].endswith("https://cartes.gouv.fr/cgu")
    assert not any("Billy" in str(c.request.url) for c in routes.calls)  # seul le code INSEE part


def test_depuis_1943_et_population_melodi(app, routes):
    res = server.lieu_historique(CODE, "1975")
    _chaque_niveau_source_et_periode(res)
    nom = _niveau(res, "nom")
    assert nom["valeur"] == "Billy-Montigny" and nom["periode_de_validite"]["debut"] == "1943-01-01"
    assert "au moins depuis 1943" in nom["periode_de_validite"]["note"]
    assert nom["source"]["service"] == "COG INSEE"
    assert _niveau(res, "departement")["valeur"] == "Pas-de-Calais (62)"
    assert _niveau(res, "rattachement_communal")["valeur"].startswith("aucun")
    pop = res["population"]
    assert (pop["valeur"], pop["annee"], pop["mesure"]) == (8834, 1975, "PSDC")
    assert pop["source"]["service"] == "INSEE-MELODI" and "2025-01-01" in pop["source"]["geographie"]
    assert pop["source"]["titre"] == "Populations municipales de 1968 à 2023"
    assert _niveau(res, "canton")["valeur"] == "inconnu"  # jamais déduit, même après 1943
    assert [c["couche"] for c in res["cartes"]["retenues"]] == ["ORTHOIMAGERY.ORTHOPHOTOS.1950-1965"]


def test_population_annee_la_plus_proche_avant_la_date(app, routes):
    pop = server.lieu_historique(CODE, "12 MAR 2001")["population"]
    assert (pop["valeur"], pop["annee"], pop["ecart_annees"]) == (8396, 1999, 2)


def test_carte_de_cassini_periode_lue_dans_la_fiche_csw(app, routes):
    res = server.lieu_historique("Billy-Montigny, Pas-de-Calais", "vers 1780")
    retenues = {c["couche"]: c for c in res["cartes"]["retenues"]}
    assert set(retenues) == {"AN-IGNF_GEOGRAPHICALGRIDSYSTEMS.CASSINI", "BNF-IGNF_GEOGRAPHICALGRIDSYSTEMS.CASSINI"}
    for c in retenues.values():
        assert c["motif"] == "contemporaine de la date"
        assert (c["periode_de_validite"]["debut"], c["periode_de_validite"]["fin"]) == ("1756", "1815")
        assert "CSW" in c["periode_de_validite"]["lue_dans"]
    assert _niveau(res, "province")["valeur"] == "inconnu"


def test_hors_de_france_sans_requete(app, routes):
    res = server.lieu_historique("Charleroi, Hainaut, Belgique", "1900")
    assert res["hors_perimetre"] is True and res["pays"]["code"] == "BE" and "niveaux" not in res
    assert not routes.calls


def test_pays_inconnu_sans_requete(app, routes):
    res = server.lieu_historique("Billy", "1900")
    assert res["pays_inconnu"] is True and "département" in res["consigne"]
    assert not routes.calls


def test_homonymes_listes_sans_choix(app, routes):
    res = server.lieu_historique("Billy, France", "1950")
    assert res["homonymie"] is True and "niveaux" not in res
    assert [c["code_insee"] for c in res["candidats"]] == ["03029", "14074", "41016"]
    hotes = {urlsplit(str(c.request.url)).hostname for c in routes.calls}
    assert hotes == {"www.insee.fr"}  # COG seulement : aucune autre requête tant que le lieu est ambigu


def test_commune_deleguee_apres_fusion(app, routes):
    app.config.contexte_services = ()  # Melodi, Géoplateforme et Wikidata désactivés : aucune requête
    res = server.lieu_historique("Billy, Calvados", "2020")
    _chaque_niveau_source_et_periode(res)
    ex = _niveau(res, "existence")
    assert ex["periode_de_validite"]["debut"] == "2017-01-01"
    assert {m["apres"] for m in ex["mouvements"]} == {"Valambray (14005)", "Billy (14074)"}
    assert _niveau(res, "rattachement_communal")["valeur"] == "commune déléguée de Valambray (14005)"
    assert res["population"]["valeur"] == "inconnu" and "désactivé" in res["population"]["motif"]
    assert res["cartes"]["retenues"] == [] and "désactivé" in res["cartes"]["erreur"]
    assert {urlsplit(str(c.request.url)).hostname for c in routes.calls} == {"www.insee.fr"}
    avant = server.lieu_historique("Billy, Calvados", "2000")
    assert _niveau(avant, "nom")["valeur"] == "Billy"


def test_changement_de_departement_date(app, routes):
    app.config.contexte_services = ()
    routes.get("https://geo.api.gouv.fr/communes/92012").respond(404)
    seine = server.lieu_historique("92012", "1960")
    assert _niveau(seine, "departement")["valeur"] == "Seine (75)"
    assert _niveau(seine, "departement")["periode_de_validite"]["fin"] == "1968-01-01"
    hds = server.lieu_historique("Boulogne-Billancourt, Hauts-de-Seine", "1970")
    assert _niveau(hds, "departement")["valeur"] == "Hauts-de-Seine (92)"
    assert hds["requetes"]["geo"] == "erreur"  # centre indisponible : cartes sans lien, rien d'inventé


def test_intervalle_a_cheval_sur_1943_reste_inconnu(app, routes):
    app.config.contexte_services = ()
    res = server.lieu_historique(CODE, "BET 1940 AND 1950")
    assert _niveau(res, "nom")["valeur"] == "inconnu" and "1943" in _niveau(res, "nom")["motif"]


def test_hors_ligne_aucune_requete_de_contexte(app, routes):
    server.lieu_historique(CODE, "1975")  # remplit le cache (COG, API Géo, services de contexte)
    n = len(routes.calls)
    app.config.offline = True
    res = server.lieu_historique(CODE, "1975")
    assert "hors ligne" in res["population"]["motif"] and "hors ligne" in res["cartes"]["erreur"]
    assert res["requetes"]["wikidata"].startswith("non interrogé")
    assert len(routes.calls) == n


def test_entrees_invalides(app):
    assert "erreur" in server.lieu_historique("", "1900")
    assert "erreur" in server.lieu_historique("Billy-Montigny, Pas-de-Calais", "pas une date")


def test_commune_absente_du_cog(app, routes):
    res = server.lieu_historique("Montigny-en-Gohelle-sur-Rien, Pas-de-Calais", "1850")
    assert res["commune"] is None and _niveau(res, "commune")["valeur"] == "inconnu"
    assert res["population"]["valeur"] == "inconnu"
    assert all(c["lien"] is None for c in res["cartes"]["retenues"])  # pas de coordonnées : pas de lien
