"""Hypothèques des AD59, sous-série 4 Q (#378) : indicateurs, tables alphabétiques et répertoires des formalités.

Fixtures : les trois formulaires et des pages de résultats publics relevés le 27 novembre 2026, réduits aux
balises lues (volumes publics ; les plages alphabétiques des titres sont des intitulés de volumes, pas des
personnes). Aucun réseau."""

from datetime import date

import httpx
import pytest
import respx

from genealogiste_mcp import archives, fr_sources, server
from genealogiste_mcp.fr_sources import communicability, next_source_hint
from genealogiste_mcp.sources import registres
from genealogiste_mcp.types_documents import SERIES

HOTE = "https://archivesdepartementales.lenord.fr"
URL = f"{HOTE}/search/results"
INDICATEUR, TABLES, REPERTOIRES = (registres.FORMULAIRES_HYP[c] for c in ("indicateur", "tables", "repertoires"))
FORMULAIRES = {INDICATEUR: "indicateur", TABLES: "tables", REPERTOIRES: "repertoires"}
BASE = {"sort": "referencecode_asc", "mode": "list", "facet_media": "image"}
LIEU = "0-controlledAccessGeographicName[]"
PAGE = f"{HOTE}/page/tables-et-repertoires-des-hypotheques"
BUREAUX = ["Avesnes", "Cambrai", "Douai", "Dunkerque", "Hazebrouck", "Lille", "Valenciennes"]


def _formulaires(fixtures, remplacer=None):
    """Les trois formulaires relevés ; ``remplacer`` : (ancien, nouveau) appliqué à chacun (vocabulaire fictif)."""
    routes = {}
    for uuid, categorie in FORMULAIRES.items():
        texte = (fixtures / f"ad59-hypotheques-formulaire-{categorie}.html").read_text()
        if remplacer:
            assert remplacer[0] in texte
            texte = texte.replace(*remplacer)
        routes[categorie] = respx.get(f"{HOTE}/search/form/{uuid}").respond(200, text=texte)
    return routes


def _resultats(fixtures, **pages):
    """Une page de résultats par catégorie (nom de fixture sans préfixe), choisie d'après le formulaire demandé."""
    def repondre(request):
        categorie = FORMULAIRES[request.url.params["formUuid"]]
        return httpx.Response(200, text=(fixtures / f"ad59-hypotheques-{pages[categorie]}.html").read_text())
    return respx.get(URL).mock(side_effect=repondre)


def _requetes(route):
    return {FORMULAIRES[c.request.url.params["formUuid"]]: dict(c.request.url.params) for c in route.calls}


# ---------------------------------------------------------------------------- formulaires

def test_formulaires_releves_un_seul_champ_le_bureau(fixtures):
    for categorie in FORMULAIRES.values():
        parser = registres._HTML()
        texte = (fixtures / f"ad59-hypotheques-formulaire-{categorie}.html").read_text()
        parser.feed(texte)
        f = registres.mnesys.lire_formulaire(parser.racine.trouver())
        assert f == {"commune": "0-controlledAccessGeographicName", "communes": BUREAUX, "date": None, "debut": None,
                     "fin": None, "typologies": {}}, categorie
        assert 'for="0-controlledAccessGeographicName">Bureau</label>' in texte
        assert 'value="referencecode_asc" name="sort"' in texte
    # ni « Lille 2 » ni « Lille (avant 1900) » ne sont des valeurs de bureau : ce sont des libellés de titres
    assert not [b for b in BUREAUX if b.startswith("Lille ")]


# ---------------------------------------------------------------------------- lecture des titres (fonctions pures)

@pytest.mark.parametrize("titre,bureau,periode,plage", [
    ("Cambrai (serie secondaire) : 4Q 64 / 070 (Feugere - Fons)", "Cambrai (serie secondaire)", None,
     {"texte": "Feugere - Fons", "debut": "FEUGERE", "fin": "FONS"}),
    ("Cambrai : 4Q 63 / 001 (ABADEAU - CRETE)", "Cambrai", None,
     {"texte": "ABADEAU - CRETE", "debut": "ABADEAU", "fin": "CRETE"}),
    ("Lille 2 (1901-1955) : 4Q 84 / 045 (De Fay - Degarnier)", "Lille 2 (1901-1955)", [1901, 1955],
     {"texte": "De Fay - Degarnier", "debut": "DEFAY", "fin": "DEGARNIER"}),
    # séparateurs relevés tels quels : « Baillez- -Basquin », casse irrégulière « briatte - Bricout »
    ("Cambrai (serie secondaire) : 4Q 64 / 003 (Baillez- -Basquin)", "Cambrai (serie secondaire)", None,
     {"texte": "Baillez- -Basquin", "debut": "BAILLEZ", "fin": "BASQUIN"}),
    ("Cambrai (serie secondaire) : 4Q 64 / 017 (briatte - Bricout)", "Cambrai (serie secondaire)", None,
     {"texte": "briatte - Bricout", "debut": "BRIATTE", "fin": "BRICOUT"}),
    # accents et trait d'union d'un nom composé : le nom n'est pas coupé
    ("Douai : 4Q 99 / 001 (Saint-Aubert - Sénéchal)", "Douai", None,
     {"texte": "Saint-Aubert - Sénéchal", "debut": "SAINTAUBERT", "fin": "SENECHAL"}),
    # absence de plage : indicateur de Lille avant 1900, répertoires
    ("Lille (avant 1900) : 4Q 79 / 002", "Lille (avant 1900)", [None, 1899], None),
    ("Avesnes : 4Q 62 / 433", "Avesnes", None, None),
    # parenthèse qui n'est pas une plage : rendue telle quelle, sans bornes
    ("Lille (1) : 4Q 80 / 001 ((unique) Sociétés)", "Lille (1)", None,
     {"texte": "(unique) Sociétés", "debut": None, "fin": None}),
    ("Douai : 4Q 99 / 002 (A - B - C)", "Douai", None, {"texte": "A - B - C", "debut": None, "fin": None}),
    ("Titre sans structure", None, None, None),
    ("", None, None, None),
])
def test_titre_bureau_periode_et_plage(titre, bureau, periode, plage):
    assert registres.titre_hypotheques(titre) == {"bureau_titre": bureau, "periode_titre": periode,
                                                  "plage_alphabetique": plage}


@pytest.mark.parametrize("prefixe,attendu", [
    ("F", True), ("f", True), ("Fe", True), ("FO", True), ("Feugère", True), ("Fons", True), ("Fi", True),
    ("Feu", True), ("Fet", False), ("Fonta", False), ("Fou", False), ("E", False), ("G", False),
    ("", None), ("  ", None), ("'-", None),
])
def test_plage_couvre_une_initiale_ou_un_prefixe(prefixe, attendu):
    plage = registres.titre_hypotheques("Cambrai (serie secondaire) : 4Q 64 / 070 (Feugere - Fons)")[
        "plage_alphabetique"]
    assert registres.plage_couvre(plage, prefixe) is attendu


def test_plage_couvre_sans_plage_lisible():
    assert registres.plage_couvre(None, "F") is None
    assert registres.plage_couvre({"texte": "(unique) Sociétés", "debut": None, "fin": None}, "S") is None
    # particule : « De Fay - Degarnier » couvre « Defrance » et « de Flandre », pas « Dehaene »
    plage = registres.titre_hypotheques("Lille 2 (1901-1955) : 4Q 84 / 045 (De Fay - Degarnier)")["plage_alphabetique"]
    assert registres.plage_couvre(plage, "Defrance") is True and registres.plage_couvre(plage, "de Fl") is True
    assert registres.plage_couvre(plage, "Deh") is False and registres.plage_couvre(plage, "D") is True


def test_volumes_couvrant_sur_des_listes_relevees(fixtures):
    def lire(nom, page=1):
        lus, _, _ = registres._lire((fixtures / f"ad59-hypotheques-{nom}.html").read_text(), page, contexte=True)
        return [{**r, **registres.titre_hypotheques(r["titre"])} for r in lus]

    def cotes(volumes):
        return [v["cote"] for v in volumes]

    cambrai = lire("indicateur-cambrai")
    assert cotes(registres.volumes_couvrant(cambrai, "D")) == ["4Q 63 / 002"]  # CRETEAU - FOURNIEZ
    assert cotes(registres.volumes_couvrant(cambrai, "Fournier")) == ["4Q 63 / 002"]
    assert cotes(registres.volumes_couvrant(cambrai, "Fo")) == ["4Q 63 / 002", "4Q 63 / 003"]  # borne partagée
    assert cotes(registres.volumes_couvrant(cambrai, "L")) == ["4Q 63 / 003", "4Q 63 / 004"]
    # deux séries parallèles relevées à Valenciennes (003-005 puis 006-007) : chaque volume est jugé seul
    valenciennes = lire("indicateur-valenciennes")
    assert cotes(registres.volumes_couvrant(valenciennes, "La")) == ["4Q 86 / 003", "4Q 86 / 007"]
    assert cotes(registres.volumes_couvrant(valenciennes, "B")) == ["4Q 86 / 006"]
    # plages qui se chevauchent dans les tables (« Baurin - Benit » puis « Benicourt - Besnard ») : les deux sont rendues
    tables = lire("tables-cambrai")
    assert cotes(registres.volumes_couvrant(tables, "Beni")) == ["4Q 64 / 005", "4Q 64 / 006"]
    assert cotes(registres.volumes_couvrant(tables, "Boniface")) == ["4Q 64 / 009", "4Q 64 / 010"]
    assert registres.volumes_couvrant(tables, "Z") == []  # hors de cette page : ne conclut rien pour les suivantes
    # répertoires et volumes sans plage : jamais rendus, ni couverts ni exclus
    assert registres.volumes_couvrant(lire("repertoires-avesnes"), "A") == []
    assert all(v["plage_alphabetique"] for v in registres.volumes_couvrant(lire("indicateur-lille"), "S"))


# ---------------------------------------------------------------------------- HYP : les trois catégories

@respx.mock
def test_hyp_trois_categories_bureau_cote_et_ark_reels(app, fixtures):
    formulaires = _formulaires(fixtures)
    route = _resultats(fixtures, indicateur="indicateur-cambrai", tables="tables-cambrai",
                       repertoires="repertoires-avesnes")
    res = server.archives_registres("AD59", "Cambrai", 1850, "HYP")
    assert "erreur" not in res, res
    assert all(f.call_count == 1 for f in formulaires.values()) and route.call_count == 3
    assert _requetes(route) == {c: {"formUuid": u, **BASE, LIEU: "Cambrai", "page": "1"}
                                for u, c in FORMULAIRES.items()}
    assert "1850" not in "".join(str(c.request.url) for c in respx.calls)  # aucune date envoyée
    assert [r["categorie"] for r in res["resultats"]] == ["indicateur"] * 5 + ["tables"] * 20 + ["repertoires"] * 20
    assert res["resultats"][0] == {
        "titre": "Cambrai : 4Q 63 / 001 (ABADEAU - CRETE)", "cote": "4Q 63 / 001", "ark": "ark:/33518/jv3qf19tskbh",
        "url": f"{HOTE}/ark:/33518/jv3qf19tskbh", "bornes": None, "nb_vues": 202,
        "contexte": "Tableau indicateur (cote 4Q)", "categorie": "indicateur", "bureau_titre": "Cambrai",
        "periode_titre": None, "plage_alphabetique": {"texte": "ABADEAU - CRETE", "debut": "ABADEAU", "fin": "CRETE"},
        "couvre_periode": None}
    table = res["resultats"][5]
    assert (table["titre"], table["cote"], table["ark"], table["nb_vues"], table["contexte"]) == (
        "Cambrai (serie secondaire) : 4Q 64 / 002 (Ai - Bailleux)", "4Q 64 / 002", "ark:/33518/7rqw24jctvkd", 198,
        "Tables alphabétiques du répertoire (cote 4Q)")
    assert table["bureau_titre"] == "Cambrai (serie secondaire)" and table["plage_alphabetique"]["fin"] == "BAILLEUX"
    repertoire = res["resultats"][25]
    assert (repertoire["titre"], repertoire["cote"], repertoire["ark"], repertoire["contexte"]) == (
        "Avesnes : 4Q 62 / 001", "4Q 62 / 001", "ark:/33518/0tm75kcjfnsv",
        "Répertoires des formalités hypothécaires (cote 4Q)")
    assert repertoire["plage_alphabetique"] is None
    assert res["total"] == 5 + 345 + 570 and res["nb_renvoyes"] == 45
    assert res["page"] == 1 and res["page_suivante"] == 2 and res["fin"] is False and res["periode"] == [1850, 1850]
    assert res["commune_service"] == "Cambrai" and res["registres_hors_periode"] == 0
    h = res["hypotheques"]
    assert h["releve_le"] == "2026-11-27" and h["reference"] == PAGE
    assert "indicateur" in h["methode"] and "numéro de case" in h["methode"] and "salle de lecture" in h["methode"]
    assert "1955" in h["periode_annoncee"] and "sans jamais transmettre ce nom" in h["lecture"]
    assert h["indicateur"] == {"formulaire": INDICATEUR, "interroge": True, "bureau": "Cambrai",
                               "autres_bureaux": [], "total": 5, "page_suivante": None, "bureaux": BUREAUX}
    assert (h["tables"]["total"], h["tables"]["page_suivante"]) == (345, 2)
    assert (h["repertoires"]["total"], h["repertoires"]["page_suivante"]) == (570, 2)
    assert h["bureaux_titres"] == ["Avesnes", "Cambrai", "Cambrai (serie secondaire)"]  # la fixture mêle deux bureaux
    assert h["communicabilite"]["type_document"] == "hypotheques" and h["communicabilite"]["delai_annees"] == 0
    assert h["communicabilite"]["volumes_non_communicables"] == 0
    assert "non vérifiée auprès du service" in h["communicabilite"]["non_verifie"]
    # ni matricules, ni enregistrement, ni classeur 3 E, ni recensements, ni avertissement sans motif
    assert not {"matricules", "successions", "fiches_deces", "classeur_3e", "couverture_recensements",
                "avertissement_communicabilite", "recherche_negative"} & set(res)
    assert app.journal.entries()[-1]["statut"] == "positif"


@respx.mock
def test_hyp_page_2_reelle_et_categories_sans_page(app, fixtures):
    # indicateur de Lille : 23 volumes, page 2 sur 2 relevée ; les autres catégories rendent ici leur première page
    # (ce que fait le service pour une page inexistante sur d'autres formulaires) : rien n'est conclu pour elles
    _formulaires(fixtures)
    route = _resultats(fixtures, indicateur="indicateur-lille-page2", tables="tables-cambrai",
                       repertoires="repertoires-avesnes")
    res = server.archives_registres("AD59", "Lille", 1920, "HYP", page=2)
    assert "erreur" not in res, res
    assert {q["page"] for q in _requetes(route).values()} == {"2"} and route.call_count == 3
    assert [(r["categorie"], r["cote"], r["plage_alphabetique"]["texte"]) for r in res["resultats"]] == [
        ("indicateur", "4Q 83 / 013", "SOMMILLE - VANDEMERGEL"),
        ("indicateur", "4Q 83 / 014", "VANDEMERGELE - VETRAY"), ("indicateur", "4Q 83 / 015", "VETREZ - ZYWIOL")]
    assert res["total"] == 23 and res["page"] == 2 and res["page_suivante"] is None and res["fin"] is True
    h = res["hypotheques"]
    assert h["indicateur"]["total"] == 23 and h["bureaux_titres"] == ["Lille (2)"]
    for categorie in ("tables", "repertoires"):
        assert h[categorie]["interroge"] is True and h[categorie]["total"] is None
        assert "Aucune page 2 lue pour cette catégorie" in h[categorie]["message"]


@respx.mock
def test_hyp_aucune_categorie_ne_rend_la_page_demandee(app, fixtures):
    _formulaires(fixtures)
    _resultats(fixtures, indicateur="indicateur-cambrai", tables="tables-cambrai", repertoires="repertoires-avesnes")
    res = registres.rechercher(app.sctx, "AD59", "Cambrai", 1850, "HYP", page=40)
    assert "erreur" in res and "resultats" not in res and "recherche_negative" not in res
    assert len(app.journal.entries(statut="erreur")) == 1


# ---------------------------------------------------------------------------- HYPI, HYPT, HYPR : une catégorie

@respx.mock
def test_hypi_une_seule_categorie_et_libelles_de_bureau_des_titres(app, fixtures):
    formulaires = _formulaires(fixtures)
    route = _resultats(fixtures, indicateur="indicateur-lille")
    res = registres.rechercher(app.sctx, "ad59", "lille", 1850, "hypi", personne="I42")
    assert "erreur" not in res, res
    assert formulaires["indicateur"].call_count == 1 and route.call_count == 1
    assert not formulaires["tables"].called and not formulaires["repertoires"].called
    assert _requetes(route) == {"indicateur": {"formUuid": INDICATEUR, **BASE, LIEU: "Lille", "page": "1"}}
    assert len(res["resultats"]) == 20 and res["total"] == 23 and res["page_suivante"] == 2
    # le vocabulaire n'a que « Lille » ; les subdivisions ne se lisent que dans les titres
    h = res["hypotheques"]
    assert h["indicateur"]["bureau"] == "Lille" and h["indicateur"]["autres_bureaux"] == []
    assert h["bureaux_titres"] == ["Lille (1)", "Lille (2)", "Lille (avant 1900)"]
    assert "tables" not in h and "repertoires" not in h
    avant, societes = res["resultats"][0], res["resultats"][6]
    assert (avant["bureau_titre"], avant["periode_titre"], avant["plage_alphabetique"], avant["couvre_periode"]) == (
        "Lille (avant 1900)", [None, 1899], None, True)
    assert avant["communicable_a_partir_de"] == 1899
    assert societes["titre"] == "Lille (1) : 4Q 80 / 001 ((unique) Sociétés)"
    assert societes["plage_alphabetique"] == {"texte": "(unique) Sociétés", "debut": None, "fin": None}
    assert societes["couvre_periode"] is None and "communicable_a_partir_de" not in societes
    # la cible locale n'est jamais envoyée, elle est journalisée
    assert "I42" not in "".join(str(c.request.url) for c in respx.calls)
    assert app.journal.entries()[0]["personne"] == "I42"


@respx.mock
def test_hypt_periode_du_titre_filtree_localement(app, fixtures):
    _formulaires(fixtures)
    route = _resultats(fixtures, tables="tables-lille-page32")
    # 1850 : les six volumes « Lille 2 (1901-1955) » de la dernière page sont hors période
    res = server.archives_registres("AD59", "Lille", 1850, "HYPT", page=32)
    assert "erreur" not in res, res
    assert _requetes(route)["tables"]["page"] == "32"
    assert res["resultats"] == [] and res["registres_hors_periode"] == 6 and res["total"] == 626
    assert res["page_suivante"] is None
    negatif = res["recherche_negative"]
    assert "ne couvre 1850-1850 d'après la période portée par son titre (6 hors période)" in negatif
    assert "ne prouve ni l'absence du registre ni celle d'une formalité" in negatif and "1955" in negatif
    # 1890-1910 : la période recoupe 1901-1955, les volumes sont rendus
    res = server.archives_registres("AD59", "Lille", 1890, "HYPT", page=32, annee_fin=1910)
    assert [r["cote"] for r in res["resultats"]] == [f"4Q 84 / {n}" for n in range(197, 203)]
    assert all(r["periode_titre"] == [1901, 1955] and r["couvre_periode"] is True for r in res["resultats"])
    assert res["resultats"][0]["plage_alphabetique"] == {"texte": "Vissault - Vrau", "debut": "VISSAULT", "fin": "VRAU"}
    assert res["hypotheques"]["bureaux_titres"] == ["Lille 2 (1901-1955)"] and "recherche_negative" not in res
    assert registres.volumes_couvrant(res["resultats"], "W")[0]["cote"] == "4Q 84 / 198"  # Vrauman - Wasquehal
    # 1950 : « avant 1900 » est écarté sur la première page
    _resultats(fixtures, tables="tables-lille")
    res = server.archives_registres("AD59", "Lille", 1950, "HYPT")
    assert res["resultats"] == [] and res["registres_hors_periode"] == 20 and res["page_suivante"] == 2
    assert "voir page_suivante" in res["recherche_negative"]


@respx.mock
def test_hypr_repertoires_sans_plage(app, fixtures):
    formulaires = _formulaires(fixtures)
    route = _resultats(fixtures, repertoires="repertoires-avesnes")
    res = server.archives_registres("AD59", "Avesnes", 1850, "HYPR")
    assert "erreur" not in res, res
    assert route.call_count == 1 and not formulaires["indicateur"].called and not formulaires["tables"].called
    assert len(res["resultats"]) == 20 and res["total"] == 570 and res["page_suivante"] == 2
    assert all(r["categorie"] == "repertoires" and r["plage_alphabetique"] is None and r["periode_titre"] is None
               and r["bornes"] is None for r in res["resultats"])
    assert res["resultats"][-1]["cote"] == "4Q 62 / 020" and res["resultats"][-1]["nb_vues"] == 101


# ---------------------------------------------------------------------------- bureau

@respx.mock
def test_bureau_inconnu_refuse_avant_toute_recherche(app, fixtures):
    _formulaires(fixtures)
    route = respx.get(URL).respond(500)
    # une commune n'est pas un bureau ; « Lille 2 » est un libellé de titre, pas une valeur du vocabulaire
    for bureau, forme in (("Somain", "SOMAIN"), ("Lille 2", "LILLE 2"), ("Lille (avant 1900)", "LILLE (AVANT 1900)")):
        res = server.archives_registres("AD59", bureau, 1850, "HYP")
        assert f"Bureau des hypothèques « {forme} » absente du vocabulaire" in res["erreur"], res
        assert "pas la commune du bien" in res["erreur"]
        assert ("Bureaux des hypothèques proposés par le formulaire : Avesnes, Cambrai, Douai, Dunkerque, "
                "Hazebrouck, Lille, Valenciennes.") in res["erreur"]
        assert "n'est pas une valeur de bureau" in res["erreur"]
    assert not route.called and len(app.journal.entries(statut="erreur")) == 3


@respx.mock
def test_bureaux_homonymes_d_un_vocabulaire_qui_changerait(app, fixtures):
    # vocabulaire fictif (le relevé n'a que « Lille ») : mêmes règles que SUCC si le service distinguait ses bureaux
    _formulaires(fixtures, remplacer=("&quot;Lille&quot;", "&quot;Lille&quot;,&quot;Lille 2&quot;,"
                                                           "&quot;Lille (1er bureau)&quot;"))
    route = _resultats(fixtures, indicateur="negative")
    res = server.archives_registres("AD59", "Lille", 1850, "HYPI")
    assert "erreur" not in res, res
    assert _requetes(route)["indicateur"][LIEU] == "Lille" and res["commune_service"] == "Lille"
    # « Lille » désigne la valeur sans qualificatif ; « Lille 2 » est un autre nom, non signalé
    assert res["hypotheques"]["indicateur"]["autres_bureaux"] == ["Lille (1er bureau)"]
    res = server.archives_registres("AD59", "lille 2", 1850, "HYPI")
    assert _requetes(route)["indicateur"][LIEU] == "Lille 2"
    assert res["hypotheques"]["indicateur"]["autres_bureaux"] == []
    res = server.archives_registres("AD59", "Lille (1er bureau)", 1850, "HYPI")
    assert _requetes(route)["indicateur"][LIEU] == "Lille (1er bureau)"
    assert res["hypotheques"]["indicateur"]["autres_bureaux"] == ["Lille"]


@respx.mock
def test_bureau_ambigu_refuse(app, fixtures):
    _formulaires(fixtures, remplacer=("&quot;Lille&quot;", "&quot;Lille (Nord)&quot;,&quot;Lille (Sud)&quot;"))
    route = respx.get(URL).respond(500)
    res = server.archives_registres("AD59", "Lille", 1850, "HYP")
    assert "ambiguë" in res["erreur"] and "Lille (Nord)" in res["erreur"] and "Lille (Sud)" in res["erreur"]
    assert not route.called


@respx.mock
def test_bureau_absent_d_un_seul_formulaire(app, fixtures):
    # vocabulaire fictif : un bureau que seul un formulaire propose n'interroge que lui
    _formulaires(fixtures)
    texte = (fixtures / "ad59-hypotheques-formulaire-tables.html").read_text().replace(
        "&quot;Lille&quot;", "&quot;Lille&quot;,&quot;Roubaix&quot;")
    respx.get(f"{HOTE}/search/form/{TABLES}").respond(200, text=texte)
    route = _resultats(fixtures, tables="negative")
    res = server.archives_registres("AD59", "Roubaix", 1850, "HYP")
    assert "erreur" not in res, res
    assert list(_requetes(route)) == ["tables"] and res["commune_service"] == "Roubaix"
    h = res["hypotheques"]
    assert h["indicateur"]["interroge"] is False and "absente du vocabulaire" in h["indicateur"]["message"]
    assert h["tables"]["interroge"] is True and "Aucun résultat pour ce bureau" in h["tables"]["message"]


# ---------------------------------------------------------------------------- négatif, pannes, refus

@respx.mock
def test_negatif_non_concluant_et_cache(app, fixtures):
    _formulaires(fixtures)
    route = _resultats(fixtures, indicateur="negative", tables="negative", repertoires="negative")
    for cached in (False, True):
        res = server.archives_registres("AD59", "Hazebrouck", 1850, "HYP")
        assert "erreur" not in res, res
        assert res["resultats"] == [] and res["total"] == 0 and res["fin"] is True
        assert res["depuis_cache"] is cached
        negatif = res["recherche_negative"]
        assert "Aucun volume des hypothèques renvoyé pour ce bureau et cette page" in negatif
        assert "ne prouve ni l'absence du registre ni celle d'une formalité" in negatif
        assert "1955" in negatif and "bureau des hypothèques" in negatif
        assert all("Aucun résultat pour ce bureau" in res["hypotheques"][c]["message"] for c in FORMULAIRES.values())
        assert "classeur_3e" not in res and app.journal.entries()[-1]["statut"] == "negatif"
    assert route.call_count == 3 and len(app.journal.entries()) == 2


@respx.mock
def test_formulaire_change_ou_recherche_en_panne(app, fixtures):
    sans_bureau = (fixtures / "ad59-hypotheques-formulaire-indicateur.html").read_text().replace(
        "0-controlledAccessGeographicName", "0-autre")
    respx.get(f"{HOTE}/search/form/{INDICATEUR}").respond(200, text=sans_bureau)
    route = respx.get(URL).respond(503)
    res = registres.rechercher(app.sctx, "AD59", "Lille", 1850, "HYPI")
    assert "non reconnu" in res["erreur"] and not route.called
    _formulaires(fixtures)
    res = registres.rechercher(app.sctx, "AD59", "Lille", 1850, "HYPT")
    assert "resultats" not in res and "recherche_negative" not in res and route.call_count == 1  # une tentative
    assert len(app.journal.entries(statut="erreur")) == 2


@respx.mock
def test_hyp_refuse_pour_un_autre_service_sans_requete(app):
    for service, type_acte in (("AD58", "HYP"), ("AD91", "HYPT"), ("AD25", "HYPI"), ("AD69", "HYPR")):
        res = server.archives_registres(service, "Nevers", 1850, type_acte)
        assert f"{type_acte} (hypothèques, sous-série 4 Q) : disponible pour AD59 seulement" in res["erreur"]
        assert "n'est pas relevé" in res["erreur"]
    res = server.archives_registres("AD99", "Nevers", 1850, "HYP")  # service sans recherche de registres
    assert "non disponible pour AD99" in res["erreur"]
    assert len(respx.calls) == 0 and len(app.journal.entries(statut="erreur")) == 5


@pytest.mark.parametrize("parametres,attendu", [
    ({"type_acte": "HYPX"}, "HYP (hypothèques, sous-série 4 Q"),
    ({"type_acte": "HYP", "commune": ""}, "commune"),
    ({"type_acte": "HYP", "annee": 0}, "annee"),
    ({"type_acte": "HYPT", "annee_fin": 1700}, "annee_fin"),
    ({"type_acte": "HYPR", "page": 0}, "page"),
    ({"type_acte": "HYP", "commune": "X" * 201}, "commune"),
])
@respx.mock
def test_hyp_mal_forme_refuse_avant_http(app, parametres, attendu):
    demande = {"service": "AD59", "commune": "Lille", "annee": 1850, **parametres}
    res = registres.rechercher(app.sctx, **demande)
    assert attendu in res["erreur"]
    assert len(respx.calls) == 0 and len(app.journal.entries(statut="erreur")) == 1


def test_garde_des_vivants_avant_toute_requete(app_famille):
    # un nom de personne vivante glissé dans le champ du bureau est refusé localement, comme pour les autres types
    with respx.mock(assert_all_called=False) as routes:
        route = routes.route().respond(200, text="aucune requête attendue")
        res = server.archives_registres("AD59", "Lucas MARTIN", 1950, "HYP")
    assert "refus" in res and not route.called


# ---------------------------------------------------------------------------- communicabilité

@respx.mock
def test_avertissement_si_un_volume_depasse_la_periode_communicable(app, fixtures, monkeypatch):
    # la règle du catalogue (délai nul) ne déclenche rien ; un délai plus long avertit sans écarter le volume
    _formulaires(fixtures)
    _resultats(fixtures, tables="tables-lille-page32")
    res = server.archives_registres("AD59", "Lille", 1950, "HYPT", page=32)
    assert "avertissement_communicabilite" not in res
    assert {r["communicable_a_partir_de"] for r in res["resultats"]} == {1955}
    monkeypatch.setitem(fr_sources.RULES, "hypotheques", (100, "acte", "Règle fictive de test : 100 ans."))
    res = server.archives_registres("AD59", "Lille", 1950, "HYPT", page=32)
    assert len(res["resultats"]) == 6 and {r["communicable_a_partir_de"] for r in res["resultats"]} == {2056}
    assert "6 volume(s)" in res["avertissement_communicabilite"]
    assert "ne pas les tenir pour librement communicables" in res["avertissement_communicabilite"]
    c = res["hypotheques"]["communicabilite"]
    assert c["volumes_non_communicables"] == 6 and c["delai_annees"] == 100 and c["regle"].startswith("Règle fictive")


def test_communicabilite_du_type_hypotheques_inchangee():
    res = communicability("hypotheques", date_document="1955", today=date(2026, 11, 27))
    assert res["delai_annees"] == 0 and res["communicable"] is True and res["communicable_a_partir_de"] == 1955
    assert res["regle"] == "Publicité foncière : en principe communicable ; vérifier les délais propres au service."
    assert "4 Q" in SERIES["hypotheques"]


# ---------------------------------------------------------------------------- non-régression

@respx.mock
def test_types_voisins_inchanges(app, fixtures):
    # SUCC, FD, RM et REC des AD59 gardent leurs formulaires, leur tri et leurs clés
    respx.get(f"{HOTE}/search/form/{registres.FORMULAIRES_ENREGISTREMENT['SUCC']}").respond(
        200, text=(fixtures / "ad59-successions-formulaire.html").read_text())
    respx.get(f"{HOTE}/search/form/{registres.FORMULAIRES_ENREGISTREMENT['FD']}").respond(
        200, text=(fixtures / "ad59-fiches-deces-formulaire.html").read_text())
    for categorie, nom in (("tables", "ad59-matricules-formulaire-tables.html"),
                           ("fiches", "ad59-matricules-formulaire-fiches.html")):
        respx.get(f"{HOTE}/search/form/{registres.FORMULAIRES_RM[categorie]}").respond(
            200, text=(fixtures / nom).read_text())
    pages = {registres.FORMULAIRES_ENREGISTREMENT["SUCC"]: "ad59-successions-intervalle.html",
             registres.FORMULAIRES_ENREGISTREMENT["FD"]: "ad59-fiches-deces-positive.html",
             registres.FORMULAIRES_RM["tables"]: "ad59-matricules-tables-bureau.html",
             registres.FORMULAIRES_RM["fiches"]: "ad59-matricules-fiches-bureau.html",
             registres.FORMULAIRE_REC: "ad59-recensements-positive.html"}
    route = respx.get(URL).mock(side_effect=lambda request: httpx.Response(
        200, text=(fixtures / pages[request.url.params["formUuid"]]).read_text()))
    nouvelles = {"hypotheques", "bureau_titre", "periode_titre", "plage_alphabetique"}
    succ = server.archives_registres("AD59", "Steenvoorde", 1791, "SUCC", annee_fin=1803)
    assert [r["cote"] for r in succ["resultats"]] == ["3Q - 516 / 1", "3Q - 516 / 2"]
    assert route.calls[-1].request.url.params["sort"] == "date_asc" and "successions" in succ
    fd = server.archives_registres("AD59", "Lille (Centre)", 1969, "FD")
    assert len(fd["resultats"]) == 6 and "fiches_deces" in fd and "avertissement_communicabilite" in fd
    rm = server.archives_registres("AD59", "Avesnes", 1890, "RM")
    assert {r["categorie"] for r in rm["resultats"]} == {"tables", "fiches"} and "matricules" in rm
    rec = server.archives_registres("AD59", "Somain", 1906, "REC")
    assert [r["cote"] for r in rec["resultats"]] == ["M 474 / 572"] and rec["registres_hors_periode"] == 3
    for res in (succ, fd, rm, rec):
        assert "erreur" not in res and not nouvelles & set(res)
        assert all(not nouvelles & set(r) for r in res["resultats"])


@respx.mock
def test_autre_service_mnesys_inchange(app, fixtures, monkeypatch):
    hote, uuid = "https://archives.exemple.fr", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    svc = {"code": "AD99", "nom": "Archives fictives", "type": "departementales", "departement": "99", "site": hote,
           "ark_naan": "99999", "recherche_registres": {"formulaires": {"successions": uuid}, "releve_le": "2026-11-18",
                                                        "reference": f"{hote}/search/form/{uuid}"}}
    reel = archives.by_code
    monkeypatch.setattr(archives, "by_code", lambda c: svc if (c or "").upper() == "AD99" else reel(c))
    res = registres.rechercher(app.sctx, "AD99", "Ville-Fictive", 1876, "HYP")
    assert "disponible pour AD59 seulement" in res["erreur"] and len(respx.calls) == 0


def test_documentation_de_l_outil():
    doc = server.archives_registres.__doc__
    assert "AD59 seulement : HYP (hypothèques, sous-série 4 Q" in doc and "HYPI, HYPT ou HYPR" in doc
    assert "plage_alphabetique" in doc and "Le nom cherché n'est jamais transmis" in doc
    assert "indicateur, puis table alphabétique (numéro de case), puis" in doc


# ---------------------------------------------------------------------------- orientation

def test_piste_hypotheques_du_nord_sans_cote_ni_bureau_inventes():
    piste = next(p for p in next_source_hint("MARR", "1850", "Somain (59)") if "hypotheques_ad59" in p)
    assert piste["source"] == "Contrat de mariage (notaire)" and piste["cote_typique"] == SERIES["notaires"]
    aide = piste["hypotheques_ad59"]
    assert aide["service"] == "AD59" and aide["releve_le"] == "2026-11-27" and aide["serie"] == SERIES["hypotheques"]
    assert aide["recherche"] == ('archives_registres(service="AD59", commune="<bureau des hypothèques>", '
                                 'annee=1850, type_acte="HYP")')
    assert "indicateur, puis table alphabétique" in aide["methode"] and "répertoire" in aide["methode"]
    assert "dot" in aide["note"] and "vente" in aide["note"] and "pas la commune" in aide["note"]
    assert "Aucune cote n'est proposée" in aide["note"] and "jamais envoyé" in aide["note"]
    # ni cote 4 Q précise ni nom de bureau
    assert "4Q" not in str(aide) and not any(b in str(aide) for b in BUREAUX)
    # un bien ou une vente (fait sans piste propre) : la piste « Actes notariés » la reçoit
    aide = next(p for p in next_source_hint("PROP", "1900", "Lille (59)") if "hypotheques_ad59" in p)
    assert aide["source"] == "Actes notariés" and "annee=1900" in aide["hypotheques_ad59"]["recherche"]
    # filiation : la date du fait n'est pas celle de l'acte, aucune année calculée
    aide = next(p for p in next_source_hint("FILIATION", "1850", "Somain (59)") if "hypotheques_ad59" in p)[
        "hypotheques_ad59"]
    assert "annee=<année de l'acte>" in aide["recherche"]
    # après 1955 : services de la publicité foncière, aucune recherche proposée
    aide = next(p for p in next_source_hint("PROP", "1960", "Lille (59)") if "hypotheques_ad59" in p)[
        "hypotheques_ad59"]
    assert "recherche" not in aide and "publicité foncière" in aide["note"]
    # avant l'an VII, hors du Nord, sans lieu, ou fait sans piste notariale : rien d'ajouté
    for fait, annee, lieu in (("MARR", "1780", "Somain (59)"), ("MARR", "1850", "Nevers (58)"), ("MARR", "1850", ""),
                              ("DEAT", "1850", "Somain (59)"), ("OCCU", "1850", "Somain (59)")):
        assert all("hypotheques_ad59" not in p for p in next_source_hint(fait, annee, lieu)), (fait, annee, lieu)
    # les pistes voisines du Nord gardent leurs clés
    assert any("successions_ad59" in p for p in next_source_hint("DEAT", "1850", "Somain (59)"))
    assert any("matricules_ad59" in p for p in next_source_hint("BIRT", "1870", "Somain (59)"))
