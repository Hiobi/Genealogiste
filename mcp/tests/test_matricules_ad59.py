"""Registres matricules des AD59 (#376) : type RM, tables et fiches des états signalétiques (série 1 R), classe.

Fixtures : formulaires et pages de résultats publics relevés le 27 novembre 2026, réduits aux balises lues
(registres publics, aucune personne). Aucun réseau."""

import httpx
import pytest
import respx

from genealogiste_mcp import archives, server
from genealogiste_mcp.fr_sources import classe_recrutement, communicability, next_source_hint
from genealogiste_mcp.sources import registres
from genealogiste_mcp.types_documents import SERIES

HOTE = "https://archivesdepartementales.lenord.fr"
URL = f"{HOTE}/search/results"
TABLES, FICHES = registres.FORMULAIRES_RM["tables"], registres.FORMULAIRES_RM["fiches"]
BUREAUX = ["AVESNES", "CAMBRAI", "DUNKERQUE", "LILLE", "VALENCIENNES", "VALENCIENNES-DOUAI"]
BASE = {"sort": "date_asc", "mode": "list", "facet_media": "image"}


def _formulaires(fixtures, tables="ad59-matricules-formulaire-tables.html",
                 fiches="ad59-matricules-formulaire-fiches.html"):
    lire = lambda nom: nom if nom.lstrip().startswith("<") else (fixtures / nom).read_text()  # noqa: E731
    return (respx.get(f"{HOTE}/search/form/{TABLES}").respond(200, text=lire(tables)),
            respx.get(f"{HOTE}/search/form/{FICHES}").respond(200, text=lire(fiches)))


def _resultats(fixtures, tables=None, fiches=None):
    """Une page par formulaire, choisie d'après formUuid ; un formulaire sans page prévue fait échouer le test."""
    pages = {TABLES: tables, FICHES: fiches}

    def repondre(request):
        nom = pages[request.url.params["formUuid"]]
        assert nom, f"formulaire interrogé à tort : {request.url}"
        return httpx.Response(200, text=(fixtures / nom).read_text())

    return respx.get(URL).mock(side_effect=repondre)


def _requetes(route):
    return {c.request.url.params["formUuid"]: dict(c.request.url.params) for c in route.calls}


# ---------------------------------------------------------------------------- classe

def test_classe_depuis_l_annee_de_naissance():
    assert classe_recrutement(1870) == 1890 and classe_recrutement(1847) == 1867
    for refus in (0, -3, 9980, "1870", 1870.0, True, None):
        with pytest.raises(ValueError):
            classe_recrutement(refus)


# ---------------------------------------------------------------------------- formulaires

def test_formulaires_releves_champs_et_bureaux(fixtures):
    def lire(nom):
        parser = registres._HTML()
        parser.feed((fixtures / nom).read_text())
        return registres.mnesys.lire_formulaire(parser.racine.trouver())

    tables = lire("ad59-matricules-formulaire-tables.html")
    assert (tables["commune"], tables["date"], tables["debut"], tables["fin"]) == (
        "0-controlledAccessGeographicName", "2-date", "1-date_begin", "1-date_end")
    assert tables["communes"] == [*BUREAUX, "VOIR TOUS BUREAUX [1931-1940]"] and tables["typologies"] == {}
    fiches = lire("ad59-matricules-formulaire-fiches.html")
    assert (fiches["commune"], fiches["date"], fiches["debut"], fiches["fin"]) == (
        "0-controlledAccessGeographicName", "1-date", None, None)
    assert fiches["communes"] == BUREAUX and fiches["typologies"] == {}
    # le libellé relevé borne les classes en ligne ; il est cité tel quel dans les messages
    assert "entre 1867 et 1923 / Valenciennes-Douai à partir de 1908" in (
        fixtures / "ad59-matricules-formulaire-fiches.html").read_text()


# ---------------------------------------------------------------------------- archives_registres (AD59, RM)

@respx.mock
def test_rm_classe_et_bureau_tables_puis_fiches(app, fixtures):
    f_tables, f_fiches = _formulaires(fixtures)
    route = _resultats(fixtures, "ad59-matricules-tables-bureau.html", "ad59-matricules-fiches-bureau.html")
    res = server.archives_registres("AD59", "Avesnes", 1890, "RM")
    assert "erreur" not in res, res
    assert f_tables.call_count == f_fiches.call_count == 1 and route.call_count == 2
    assert _requetes(route) == {
        TABLES: {"formUuid": TABLES, **BASE, "0-controlledAccessGeographicName[]": "AVESNES", "2-date": "1890",
                 "page": "1"},
        FICHES: {"formUuid": FICHES, **BASE, "0-controlledAccessGeographicName[]": "AVESNES", "1-date": "1890",
                 "page": "1"}}
    assert res["resultats"][0] == {
        "titre": "1890 : AVESNES", "cote": "1R 02249", "ark": "ark:/33518/50hrtbnjdvcq",
        "url": f"{HOTE}/ark:/33518/50hrtbnjdvcq", "bornes": [1890, 1890], "nb_vues": 79,
        "contexte": "Tables des registres militaires", "categorie": "tables"}
    assert [(r["categorie"], r["titre"], r["cote"], r["nb_vues"]) for r in res["resultats"][1:]] == [
        ("fiches", "Volume 1", "1R 2244", 569), ("fiches", "Volume 2", "1R 2245", 565),
        ("fiches", "Volume 5", "1R 2248", 147), ("fiches", "Volume 3", "1R 2246", 577),
        ("fiches", "Volume 4", "1R 2247", 561)]
    assert {r["contexte"] for r in res["resultats"][1:]} == {"Registres numérisés des matricules militaires (Avesnes)"}
    assert res["total"] == res["nb_renvoyes"] == 6 and res["page"] == 1
    assert res["page_suivante"] is None and res["fin"] is True and res["periode"] == [1890, 1890]
    assert res["requete"] == {"service": "AD59", "commune": "AVESNES", "annee": 1890, "type_acte": "RM", "page": 1,
                              "annee_fin": 0}
    m = res["matricules"]
    assert m["releve_le"] == "2026-11-27" and "contenu des vues n'est pas lu" in m["lecture"]
    assert m["tables"] == {"formulaire": TABLES, "interroge": True, "bureau": "AVESNES", "total": 1,
                           "page_suivante": None, "bureaux": [*BUREAUX, "VOIR TOUS BUREAUX [1931-1940]"]}
    assert m["fiches"] == {"formulaire": FICHES, "interroge": True, "bureau": "AVESNES", "total": 5,
                           "page_suivante": None, "bureaux": BUREAUX}
    # ni classeur 3 E, ni recensements, ni filtre local : ce ne sont pas des registres d'état civil
    assert not {"classeur_3e", "couverture_recensements", "registres_hors_periode", "recherche_negative"} & set(res)
    assert "ne prouve pas la présence" in res["avertissement"]
    assert len(app.journal.entries()) == 1 and app.journal.entries()[0]["statut"] == "positif"


@respx.mock
def test_rm_sans_bureau_et_page_suivante_explicite(app, fixtures):
    _formulaires(fixtures)
    route = _resultats(fixtures, "ad59-matricules-tables-classe.html", "ad59-matricules-fiches-classe.html")
    res = registres.rechercher(app.sctx, "ad59", "", 1890, "rm", personne="I42")
    assert "erreur" not in res, res
    assert all("0-controlledAccessGeographicName[]" not in q for q in _requetes(route).values())
    tables = [r for r in res["resultats"] if r["categorie"] == "tables"]
    assert [(r["titre"], r["cote"]) for r in tables] == [
        ("1890 : LILLE", "1R 02273"), ("1890 : DUNKERQUE", "1R 02261"), ("1890 : CAMBRAI", "1R 02255"),
        ("1890 : AVESNES", "1R 02249"), ("1890 : VALENCIENNES", "1R 02278")]
    assert res["resultats"][:5] == tables and len(res["resultats"]) == 25  # 5 tables, 20 des 30 volumes
    assert res["total"] == 35 and res["page_suivante"] == 2 and res["fin"] is False
    assert res["matricules"]["tables"]["page_suivante"] is None and res["matricules"]["fiches"]["page_suivante"] == 2
    assert res["matricules"]["tables"]["bureau"] is None and res["matricules"]["fiches"]["total"] == 30
    assert route.call_count == 2  # une page par formulaire, aucune page suivante lue d'office
    assert "I42" not in "".join(str(c.request.url) for c in respx.calls)
    assert app.journal.entries()[0]["personne"] == "I42"



@respx.mock
def test_rm_page_2_reelle_des_fiches(app, fixtures):
    # les tables n'ont qu'une page : la page 1 rendue à la place de la page 2 ne conclut rien pour elles
    _formulaires(fixtures)
    _resultats(fixtures, "ad59-matricules-tables-classe.html", "ad59-matricules-fiches-classe-page2.html")
    res = server.archives_registres("AD59", "", 1890, "RM", page=2)
    assert "erreur" not in res, res
    assert len(res["resultats"]) == 10 and {r["categorie"] for r in res["resultats"]} == {"fiches"}
    assert res["resultats"][0]["titre"] == "Volume 8 (3501-4000)" and res["resultats"][0]["cote"] == "1R 2269"
    assert res["resultats"][0]["contexte"] == "Registres numérisés des matricules militaires (Lille)"
    assert res["total"] == 30 and res["page"] == 2 and res["page_suivante"] is None and res["fin"] is True
    tables = res["matricules"]["tables"]
    assert tables["interroge"] is True and tables["total"] is None
    assert tables["message"].startswith("Aucune page 2 lue pour cette catégorie") and "message" not in res[
        "matricules"]["fiches"]


@respx.mock
def test_rm_page_hors_bornes_des_deux_formulaires_est_une_erreur(app, fixtures):
    _formulaires(fixtures)
    _resultats(fixtures, "ad59-matricules-tables-bureau.html", "ad59-matricules-fiches-bureau.html")
    res = registres.rechercher(app.sctx, "AD59", "Avesnes", 1890, "RM", page=2)
    assert "erreur" in res and "recherche_negative" not in res
    assert len(app.journal.entries(statut="erreur")) == 1


@respx.mock
def test_rm_intervalle_n_interroge_que_les_tables(app, fixtures):
    _formulaires(fixtures)
    route = _resultats(fixtures, "ad59-matricules-tables-intervalle.html")  # les fiches ne doivent pas être lues
    res = server.archives_registres("AD59", "Avesnes", 1889, "RM", annee_fin=1891)
    assert "erreur" not in res, res
    assert _requetes(route) == {TABLES: {
        "formUuid": TABLES, **BASE, "0-controlledAccessGeographicName[]": "AVESNES", "1-date_begin": "1889",
        "1-date_end": "1891", "page": "1"}}
    assert [(r["titre"], r["cote"], r["bornes"], r["categorie"]) for r in res["resultats"]] == [
        ("1889 : AVESNES", "1R 02213", [1889, 1889], "tables"), ("1890 : AVESNES", "1R 02249", [1890, 1890], "tables"),
        ("1891 : AVESNES", "1R 02283", [1891, 1891], "tables")]
    assert res["total"] == 3 and res["periode"] == [1889, 1891]
    fiches = res["matricules"]["fiches"]
    assert fiches["interroge"] is False and fiches["total"] is None and fiches["bureau"] == "AVESNES"
    assert "non interrogé pour un intervalle" in fiches["message"] and "annee_fin=0" in fiches["message"]


@respx.mock
def test_rm_negatif_des_deux_formulaires_non_concluant_et_cache(app, fixtures):
    _formulaires(fixtures)
    route = _resultats(fixtures, "ad59-matricules-tables-negative.html", "ad59-matricules-fiches-negative.html")
    for cached in (False, True):
        res = server.archives_registres("AD59", "Avesnes", 1200, "RM")
        assert "erreur" not in res, res
        assert res["resultats"] == [] and res["total"] == 0 and res["fin"] is True
        assert res["depuis_cache"] is cached
        assert "ne prouve ni l'absence du registre ni celle de la personne" in res["recherche_negative"]
        m = res["matricules"]
        assert m["tables"]["total"] == m["fiches"]["total"] == 0
        assert "ne prouve pas l'absence" in m["tables"]["message"] and "sans bureau" in m["tables"]["message"]
        assert "classes 1867 à 1923, Valenciennes-Douai à partir de 1908" in m["fiches"]["message"]
        assert "classeur_3e" not in res
        assert app.journal.entries()[-1]["statut"] == "negatif"
    assert route.call_count == 2 and len(app.journal.entries()) == 2


@respx.mock
def test_rm_classe_hors_des_fiches_garde_les_tables(app, fixtures):
    _formulaires(fixtures)
    _resultats(fixtures, "ad59-matricules-tables-bureau.html", "ad59-matricules-fiches-negative.html")
    res = registres.rechercher(app.sctx, "AD59", "AVESNES", 1890, "RM")
    assert [r["categorie"] for r in res["resultats"]] == ["tables"] and "recherche_negative" not in res
    assert res["matricules"]["fiches"]["total"] == 0 and "ne prouve pas" in res["matricules"]["fiches"]["message"]


@respx.mock
def test_rm_bureau_inconnu_refuse_avant_toute_recherche(app, fixtures):
    _formulaires(fixtures)
    route = respx.get(URL).respond(500)
    for saisie, proches in (("Somain", False), ("Douai", True)):
        res = server.archives_registres("AD59", saisie, 1890, "RM")
        assert "Bureau de recrutement «" in res["erreur"] and "absente du vocabulaire" in res["erreur"]
        assert ("VALENCIENNES-DOUAI']" in res["erreur"].split("Bureaux de recrutement proposés")[0]) is proches
        assert "AVESNES, CAMBRAI, DUNKERQUE, LILLE, VALENCIENNES, VALENCIENNES-DOUAI" in res["erreur"]
        assert "facultatif" in res["erreur"]
    assert not route.called and len(app.journal.entries(statut="erreur")) == 2


@respx.mock
def test_rm_bureau_ambigu_liste_les_valeurs(app, fixtures):
    # vocabulaire synthétique : le vocabulaire relevé n'a pas d'homonyme
    ambigu = (fixtures / "ad59-matricules-formulaire-fiches.html").read_text().replace(
        "&quot;LILLE&quot;", "&quot;LILLE (Nord)&quot;,&quot;LILLE (Sud)&quot;")
    assert "LILLE (Sud)" in ambigu
    _formulaires(fixtures, tables=ambigu.replace(FICHES, TABLES), fiches=ambigu)
    route = respx.get(URL).respond(500)
    res = registres.rechercher(app.sctx, "AD59", "Lille", 1890, "RM")
    assert "ambiguë" in res["erreur"] and "LILLE (Nord)" in res["erreur"] and "LILLE (Sud)" in res["erreur"]
    assert not route.called


@respx.mock
def test_rm_valeur_propre_aux_tables_n_interroge_pas_les_fiches(app, fixtures):
    _formulaires(fixtures)
    route = _resultats(fixtures, "ad59-matricules-tables-negative.html")
    res = registres.rechercher(app.sctx, "AD59", "VOIR TOUS BUREAUX [1931-1940]", 1935, "RM")
    assert "erreur" not in res, res
    assert _requetes(route)[TABLES]["0-controlledAccessGeographicName[]"] == "VOIR TOUS BUREAUX [1931-1940]"
    fiches = res["matricules"]["fiches"]
    assert fiches["interroge"] is False and "absente du vocabulaire" in fiches["message"]
    # même valeur avec un intervalle : plus aucun formulaire interrogeable pour les fiches, les tables suffisent
    assert "erreur" not in registres.rechercher(app.sctx, "AD59", "VOIR TOUS BUREAUX [1931-1940]", 1931, "RM",
                                                annee_fin=1940)


@respx.mock
def test_rm_formulaire_change_est_une_erreur_sans_recherche(app, fixtures):
    sans_annee = (fixtures / "ad59-matricules-formulaire-fiches.html").read_text().replace('name="1-date"', "")
    _formulaires(fixtures, fiches=sans_annee)
    route = respx.get(URL).respond(503)
    res = registres.rechercher(app.sctx, "AD59", "Lille", 1890, "RM")
    assert "non reconnu" in res["erreur"] and not route.called
    assert len(app.journal.entries(statut="erreur")) == 1


@respx.mock
def test_rm_recherche_en_panne_une_seule_tentative(app, fixtures):
    _formulaires(fixtures)
    route = respx.get(URL).respond(503)
    res = registres.rechercher(app.sctx, "AD59", "Cambrai", 1891, "RM")
    assert "resultats" not in res and "recherche_negative" not in res
    assert route.call_count == 1  # pas de reprise, et le second formulaire n'est pas interrogé après la panne


@pytest.mark.parametrize("parametres,attendu", [
    ({"type_acte": "RMX"}, "RM (registres matricules) pour AD59"),
    ({"type_acte": "RECX"}, "REC (recensements de population) pour AD59"),
    ({"type_acte": "REC", "commune": ""}, "commune : nom obligatoire (facultatif pour RM)"),
    ({"type_acte": "SUCC"}, "SUCC (tables des successions) pour les services Mnesys"),
    ({"type_acte": "RM", "annee": 0}, "annee"),
    ({"type_acte": "RM", "annee": "1890"}, "annee"),
    ({"type_acte": "RM", "annee_fin": 1880}, "annee_fin"),
    ({"type_acte": "RM", "page": 0}, "page"),
    ({"type_acte": "RM", "commune": "X" * 201}, "commune"),
])
@respx.mock
def test_rec_et_rm_mal_formes_refuses_avant_http(app, parametres, attendu):
    demande = {"service": "AD59", "commune": "Lille", "annee": 1890, **parametres}
    res = registres.rechercher(app.sctx, **demande)
    assert attendu in res["erreur"]
    assert len(respx.calls) == 0 and len(app.journal.entries(statut="erreur")) == 1


@respx.mock
def test_rm_d_un_autre_service_mnesys_inchange(app, fixtures, monkeypatch):
    hote, uuid = "https://archives.exemple.fr", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    svc = {"code": "AD99", "nom": "Archives fictives", "type": "departementales", "departement": "99", "site": hote,
           "ark_naan": "99999", "recherche_registres": {"formulaires": {"matricules": uuid}, "releve_le": "2026-11-18",
                                                        "reference": f"{hote}/search/form/{uuid}"}}
    reel = archives.by_code
    monkeypatch.setattr(archives, "by_code", lambda c: svc if (c or "").upper() == "AD99" else reel(c))
    respx.get(f"{hote}/search/form/{uuid}").respond(
        200, text=(fixtures / "mnesys-formulaire-matricules.html").read_text())
    route = respx.get(f"{hote}/search/results").respond(
        200, text=(fixtures / "mnesys-recherche-positive.html").read_text())
    res = registres.rechercher(app.sctx, "AD99", "", 1880, "RM")
    assert "erreur" not in res, res
    assert dict(route.calls[0].request.url.params) == {
        "formUuid": uuid, **BASE, "0-date[]": "1880",
        "2-controlledAccessPhysicalCharacteristic[]": "Registre matricule", "page": "1"}
    assert route.call_count == 1 and res["commune_service"] is None
    assert "matricules" not in res and all("categorie" not in r and "contexte" not in r for r in res["resultats"])


def test_documentation_de_l_outil():
    doc = server.archives_registres.__doc__
    assert "AD59 (série 1 R)" in doc and "categorie" in doc and "matricules" in doc and "année de naissance + 20" in doc
    assert "AD59" in registres.services_registres()


# ---------------------------------------------------------------------------- pistes et communicabilité

def test_piste_matricule_du_nord_donne_la_classe_sans_cote_inventee():
    piste = next(p for p in next_source_hint("BIRT", "1870", "Somain (59)") if "matricules_ad59" in p)
    assert piste["cote_typique"] == SERIES["matricules"]  # orientation inchangée, aucune cote 1 R ajoutée
    aide = piste["matricules_ad59"]
    assert aide["service"] == "AD59" and aide["classe"] == 1890
    assert aide["recherche"] == 'archives_registres(service="AD59", commune="", annee=1890, type_acte="RM")'
    assert "aucune cote n'est proposée" in aide["note"] and "1R " not in str(aide)
    # date qui n'est pas une naissance : pas de classe calculée
    mili = next(p for p in next_source_hint("MILI", "1914", "Somain (59)") if "matricules_ad59" in p)
    assert "classe" not in mili["matricules_ad59"] and "annee=<classe>" in mili["matricules_ad59"]["recherche"]
    # hors du Nord, sans lieu ou sans piste matricule : rien d'ajouté
    for fait, date, lieu in (("BIRT", "1870", "Nevers (58)"), ("BIRT", "1870", ""), ("MARR", "1890", "Somain (59)"),
                             ("BIRT", "1790", "Somain (59)")):
        assert all("matricules_ad59" not in p for p in next_source_hint(fait, date, lieu)), (fait, date, lieu)


def test_communicabilite_matricule_inchangee():
    # 120 ans après la naissance : la dernière classe des fiches en ligne (1923, nés en 1903) est communicable
    # depuis 2024 ; les tables alphabétiques en ligne au-delà (1928, 1930 observées) ne sont pas ce registre.
    from datetime import date
    res = communicability("matricule", date_naissance=str(classe_recrutement(1923) - 40), today=date(2026, 11, 27))
    assert res["delai_annees"] == 120 and res["communicable_a_partir_de"] == 2024 and res["communicable"] is True
    res = communicability("matricule", date_naissance="1910", today=date(2026, 11, 27))
    assert res["communicable"] is False and res["communicable_a_partir_de"] == 2031
