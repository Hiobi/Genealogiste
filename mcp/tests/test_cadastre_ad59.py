"""Plans du cadastre des AD59 (#379) : cadastre dit du Consulat (P 30) et cadastre dit napoléonien (P 31).

Fixtures : les deux formulaires et des pages de résultats publics relevés le 27 novembre 2026, réduits aux
balises lues (lots de plans publics, non nominatifs). Aucun réseau."""

import httpx
import pytest
import respx

from genealogiste_mcp import archives, couverture_3e, server
from genealogiste_mcp.fr_sources import communicability, next_source_hint
from genealogiste_mcp.sources import registres
from genealogiste_mcp.types_documents import SERIES

HOTE = "https://archivesdepartementales.lenord.fr"
URL = f"{HOTE}/search/results"
CONSULAIRE, NAPOLEONIEN = (registres.FORMULAIRES_CAD[c] for c in ("consulaire", "napoleonien"))
FORMULAIRES = {CONSULAIRE: "consulaire", NAPOLEONIEN: "napoleonien"}
BASE = {"sort": "referencecode_asc", "mode": "list", "facet_media": "image"}
LIEU = "0-controlledAccessGeographicName[]"
PAGE = f"{HOTE}/page/plans-du-cadastre-du-consulat-et-napoleonien"


def _formulaires(fixtures, remplacer=None):
    """Les deux formulaires relevés ; ``remplacer`` : (ancien, nouveau) appliqué à chacun (vocabulaire fictif)."""
    routes = {}
    for uuid, categorie in FORMULAIRES.items():
        texte = (fixtures / f"ad59-cadastre-formulaire-{categorie}.html").read_text()
        if remplacer:
            assert remplacer[0] in texte
            texte = texte.replace(*remplacer)
        routes[categorie] = respx.get(f"{HOTE}/search/form/{uuid}").respond(200, text=texte)
    return routes


def _resultats(fixtures, **pages):
    """Une page de résultats par catégorie (nom de fixture sans préfixe), choisie d'après le formulaire demandé."""
    def repondre(request):
        categorie = FORMULAIRES[request.url.params["formUuid"]]
        return httpx.Response(200, text=(fixtures / f"ad59-cadastre-{categorie}-{pages[categorie]}.html").read_text())
    return respx.get(URL).mock(side_effect=repondre)


def _requetes(route):
    return {FORMULAIRES[c.request.url.params["formUuid"]]: dict(c.request.url.params) for c in route.calls}


def _vocabulaire(fixtures, categorie):
    parser = registres._HTML()
    parser.feed((fixtures / f"ad59-cadastre-formulaire-{categorie}.html").read_text())
    return registres.mnesys.lire_formulaire(parser.racine.trouver())


# ---------------------------------------------------------------------------- formulaires

def test_formulaires_releves_un_seul_champ_la_commune(fixtures):
    tailles = {}
    for categorie in FORMULAIRES.values():
        f = _vocabulaire(fixtures, categorie)
        texte = (fixtures / f"ad59-cadastre-formulaire-{categorie}.html").read_text()
        assert {k: v for k, v in f.items() if k != "communes"} == {
            "commune": "0-controlledAccessGeographicName", "date": None, "debut": None, "fin": None,
            "typologies": {}}, categorie
        assert 'for="0-controlledAccessGeographicName">Commune</label>' in texte
        assert 'value="relevance" name="sort"' in texte  # tri par défaut du formulaire : la pertinence
        tailles[categorie] = len(f["communes"])
    assert tailles == {"consulaire": 395, "napoleonien": 650}
    # deux vocabulaires distincts : anciens noms et communes réunies n'y figurent pas de la même façon
    cons, nap = (set(_vocabulaire(fixtures, c)["communes"]) for c in ("consulaire", "napoleonien"))
    assert {"SAINT-REMY-MAL-BATI", "WARNETON-BAS", "BOURBOURG (VILLE)"} <= cons - nap
    assert {"SAINT-REMY-DU-NORD", "WARNETON", "FIVES", "LILLE", "ESTAIRES"} <= nap - cons


# ---------------------------------------------------------------------------- CAD : les deux cadastres

@respx.mock
def test_cad_deux_cadastres_commune_cote_et_ark_reels(app, fixtures):
    formulaires = _formulaires(fixtures)
    route = _resultats(fixtures, consulaire="marly", napoleonien="marly")
    res = server.archives_registres("AD59", "Marly", 1800, "CAD", annee_fin=1900)
    assert "erreur" not in res, res
    assert all(f.call_count == 1 for f in formulaires.values()) and route.call_count == 2
    assert _requetes(route) == {c: {"formUuid": u, **BASE, LIEU: "MARLY", "page": "1"}
                                for u, c in FORMULAIRES.items()}
    assert "1800" not in "".join(str(c.request.url) for c in respx.calls)  # aucune date envoyée
    # tri par date (#391) : le lot sans date d'abord, puis 1826 avant 1896 (le service les rend dans l'autre ordre)
    assert res["resultats"] == [
        {"titre": "MARLY / 222", "cote": "P 30 / 222", "ark": "ark:/33518/hl2s6p8q4ntv",
         "url": f"{HOTE}/ark:/33518/hl2s6p8q4ntv", "bornes": None, "nb_vues": 4,
         "contexte": "Les plans du cadastre du Consulat", "categorie": "consulaire", "annee_titre": None,
         "couvre_periode": None, "position_periode": None,
         "planche_contact": 'archives_planche(source="ark:/33518/hl2s6p8q4ntv", de=1, a=4)'},
        # deux levées sous la même cote : deux lots, deux ARK
        {"titre": "MARLY - 1826", "cote": "P 31 / 602", "ark": "ark:/33518/3rmlnv49tfpg",
         "url": f"{HOTE}/ark:/33518/3rmlnv49tfpg", "bornes": [1826, 1826], "nb_vues": 5,
         "contexte": "P31 - Cadastre napoléonien", "categorie": "napoleonien", "annee_titre": 1826,
         "couvre_periode": True, "position_periode": "contemporain",
         "planche_contact": 'archives_planche(source="ark:/33518/3rmlnv49tfpg", de=1, a=5)'},
        # 11 vues : pas de planche proposée
        {"titre": "MARLY - 1896", "cote": "P 31 / 602", "ark": "ark:/33518/4rxhtvclgbsp",
         "url": f"{HOTE}/ark:/33518/4rxhtvclgbsp", "bornes": [1896, 1896], "nb_vues": 11,
         "contexte": "P31 - Cadastre napoléonien", "categorie": "napoleonien", "annee_titre": 1896,
         "couvre_periode": True, "position_periode": "contemporain"}]
    assert res["total"] == 3 and res["nb_renvoyes"] == 3 and res["page_suivante"] is None and res["fin"] is True
    assert res["commune_service"] == "MARLY" and res["registres_hors_periode"] == 0
    c = res["cadastre"]
    assert c["releve_le"] == "2026-11-27" and c["reference"] == PAGE
    assert "Consulat" in c["periode_annoncee"] and "début du XXe siècle" in c["periode_annoncee"]
    assert "non nominatifs" in c["lecture"] and "Matrices cadastrales" in c["non_couvert"]
    assert "geo_historique" in c["piste_lieu"] and "dates_hors_periode" not in c
    assert c["consulaire"] == {"formulaire": CONSULAIRE, "interroge": True, "commune": "MARLY", "total": 1,
                               "page_suivante": None, "nb_communes": 395}
    assert c["napoleonien"] == {"formulaire": NAPOLEONIEN, "interroge": True, "commune": "MARLY", "total": 2,
                                "page_suivante": None, "nb_communes": 650}
    assert c["communicabilite"]["type_document"] == "cadastre" and c["communicabilite"]["delai_annees"] == 0
    assert "non vérifiée auprès du service" in c["communicabilite"]["non_verifie"]
    # ni hypothèques, ni matricules, ni enregistrement, ni classeur 3 E, ni recensements, ni avertissement sans motif
    assert not {"hypotheques", "matricules", "successions", "fiches_deces", "classeur_3e",
                "couverture_recensements", "avertissement_communicabilite", "recherche_negative"} & set(res)
    assert app.journal.entries()[-1]["statut"] == "positif"


@respx.mock
def test_annee_n_ecarte_aucun_plan_et_situe_chaque_lot(app, fixtures):
    # #391 : un plan vaut pour les décennies qui suivent sa levée ; la date situe un lot, elle ne l'écarte plus
    _formulaires(fixtures)
    route = _resultats(fixtures, napoleonien="estaires")  # commune absente du cadastre du Consulat
    res = server.archives_registres("AD59", "Estaires", 1808, "CAD", annee_fin=1820)
    # trois lots (cotes P 31 / 035, 035_1, 035_2), triés par date et non par cote ; celui de 1889 reste rendu
    assert [(r["cote"], r["annee_titre"], r["bornes"], r["nb_vues"]) for r in res["resultats"]] == [
        ("P 31 / 035_1", 1808, [1808, 1808], 2), ("P 31 / 035_2", 1816, [1816, 1816], 37),
        ("P 31 / 035", 1889, [1889, 1889], 15)]
    assert [(r["couvre_periode"], r["position_periode"]) for r in res["resultats"]] == [
        (True, "contemporain"), (True, "contemporain"), (False, "posterieur")]
    assert res["total"] == 3 and res["nb_renvoyes"] == 3 and res["registres_hors_periode"] == 0
    # indication conservée, sans effet sur resultats
    assert res["cadastre"]["dates_hors_periode"] == [1889] and "recherche_negative" not in res
    assert "planche_contact" in res["resultats"][0] and "planche_contact" not in res["resultats"][1]
    cons = res["cadastre"]["consulaire"]
    assert cons["interroge"] is False and cons["commune"] is None and cons["total"] is None
    assert "ESTAIRES » absente du vocabulaire de ce formulaire" in cons["message"]
    # aucun plan ne recoupe 1850 : les trois lots sont rendus, les plans antérieurs (à consulter) d'abord
    res = server.archives_registres("AD59", "Estaires", 1850, "CAD")
    assert [(r["cote"], r["annee_titre"], r["couvre_periode"], r["position_periode"]) for r in res["resultats"]] == [
        ("P 31 / 035_1", 1808, False, "anterieur"), ("P 31 / 035_2", 1816, False, "anterieur"),
        ("P 31 / 035", 1889, False, "posterieur")]
    assert res["total"] == 3 and res["nb_renvoyes"] == 3 and res["registres_hors_periode"] == 0
    assert res["cadastre"]["dates_hors_periode"] == [1808, 1816, 1889] and "recherche_negative" not in res
    assert app.journal.entries()[-1]["statut"] == "positif"
    assert "position_periode" in res["cadastre"]["lecture"] and "écarté sur sa date" in res["cadastre"]["lecture"]
    # la période n'est pas envoyée : la seconde demande (autre année) est servie par le cache, sans requête
    assert route.call_count == 1 and all(set(c.request.url.params) == {"formUuid", *BASE, LIEU, "page"}
                                         for c in route.calls)


def test_position_periode_bornes_incluses():
    assert registres._position(None, [1850, 1850]) is None
    assert [registres._position(a, [1820, 1830]) for a in (1819, 1820, 1830, 1831)] == [
        "anterieur", "contemporain", "contemporain", "posterieur"]
    # bornes sur plusieurs années : contemporain dès qu'elles recoupent la période
    assert registres._position([1800, 1820], [1820, 1830]) == "contemporain"
    assert registres._position([1800, 1819], [1820, 1830]) == "anterieur"
    assert registres._position([1831, 1840], [1820, 1830]) == "posterieur"


@respx.mock
def test_date_du_titre_seulement_informative(app, fixtures):
    # Lille : le champ Date du service est illisible (« B12) ») ; l'année du titre renseigne mais ne filtre pas
    _formulaires(fixtures)
    _resultats(fixtures, napoleonien="lille")
    res = server.archives_registres("AD59", "Lille", 1820, "CAD")
    assert len(res["resultats"]) == 9 and res["registres_hors_periode"] == 0
    assert {(r["annee_titre"], r["bornes"], r["couvre_periode"]) for r in res["resultats"]} == {(1881, None, None)}
    # #391 : à défaut de date du service, l'année du titre situe le lot ; même année partout : ordre des cotes gardé
    assert {r["position_periode"] for r in res["resultats"]} == {"posterieur"}
    assert "dates_hors_periode" not in res["cadastre"] and "recherche_negative" not in res
    assert [r["cote"] for r in res["resultats"]] == sorted(r["cote"] for r in res["resultats"])
    assert res["resultats"][0]["titre"] == "LILLE - 1881 (TA-B12)" and res["resultats"][0]["cote"] == "P 31 / 243"
    # une cote partagée par plusieurs lots (P 31 / 246 : trois ARK)
    assert [r["nb_vues"] for r in res["resultats"] if r["cote"] == "P 31 / 246"] == [42, 6, 22]
    assert len({r["ark"] for r in res["resultats"]}) == 9
    # un seul lot de 2 à 9 vues
    assert [r["nb_vues"] for r in res["resultats"] if "planche_contact" in r] == [6]


# ---------------------------------------------------------------------------- communes réunies, noms anciens

def test_noms_lies_du_classeur_3e_fonction_pure(fixtures):
    cons, nap = (_vocabulaire(fixtures, c)["communes"] for c in ("consulaire", "napoleonien"))
    lie = couverture_3e.noms_lies
    assert lie("Fives", nap) == [{"valeur": "LILLE", "lien": "nom actuel", "d_apres": "LILLE (FIVES)"}]
    assert lie("Lille", nap) == [{"valeur": "FIVES", "lien": "ancien nom ou lieu rattaché",
                                  "d_apres": "LILLE (FIVES)"}]
    assert lie("Saint-Remy-du-Nord", cons) == [{"valeur": "SAINT-REMY-MAL-BATI",
                                                "lien": "ancien nom ou lieu rattaché",
                                                "d_apres": "SAINT-REMY-DU-NORD (ANC. MAL BATI)"}]
    assert [n["valeur"] for n in lie("Saint-Remy-Mal-Bâti", nap)] == ["SAINT-REMY-DU-NORD"]
    assert [n["valeur"] for n in lie("Warneton", cons)] == ["WARNETON-BAS", "WARNETON-SUD"]
    assert [n["valeur"] for n in lie("Wallers-en-Fagne", nap)] == ["TRELON", "WALLERS-TRELON"]
    # rien pour une commune sans parenthèse au classeur, un article (« BASSEE (LA) ») ou une demande vide
    assert lie("Marly", nap) == lie("La Bassée", nap) == lie("", nap) == lie("Fives", cons) == []
    # la terminaison seule ne suffit pas : « Monchaux-sur-Ecaillon » n'est pas « CAPELLE (SUR-ECAILLON) »
    assert lie("Monchaux-sur-Ecaillon", nap) == [] and [n["valeur"] for n in lie("Capelle-sur-Ecaillon", nap)] == [
        "CAPELLE"]


@respx.mock
def test_commune_reunie_fives_et_lille(app, fixtures):
    # Fives : plan de 1825 sous son nom d'alors ; le classeur 3 E local la rattache à Lille (« LILLE (FIVES) »)
    _formulaires(fixtures)
    route = _resultats(fixtures, napoleonien="fives")
    res = server.archives_registres("AD59", "Fives", 1825, "CAD")
    assert [(r["titre"], r["cote"], r["ark"], r["nb_vues"]) for r in res["resultats"]] == [
        ("FIVES - 1825", "P 31 / 212_2", "ark:/33518/x7qkc2jmwz3n", 2)]
    assert route.call_count == 1 and res["commune_service"] == "FIVES"
    assert res["cadastre"]["napoleonien"]["noms_lies"] == [
        {"valeur": "LILLE", "lien": "nom actuel", "d_apres": "LILLE (FIVES)"}]
    assert "noms_lies" not in res["cadastre"]["consulaire"]  # ni Fives ni Lille au cadastre du Consulat
    # dans l'autre sens : Lille renvoie vers Fives, sans requête supplémentaire
    _resultats(fixtures, napoleonien="lille")
    res = server.archives_registres("AD59", "Lille", 1881, "CAD")
    assert res["cadastre"]["napoleonien"]["noms_lies"] == [
        {"valeur": "FIVES", "lien": "ancien nom ou lieu rattaché", "d_apres": "LILLE (FIVES)"}]
    assert {str(c.request.url.host) for c in respx.calls} == {"archivesdepartementales.lenord.fr"}


@respx.mock
def test_nom_ancien_absent_d_un_formulaire_aide_sans_reseau(app, fixtures):
    # Saint-Remy-du-Nord : connu du napoléonien ; le cadastre du Consulat le classe sous son ancien nom
    _formulaires(fixtures)
    route = _resultats(fixtures, napoleonien="negative")
    res = server.archives_registres("AD59", "Saint-Remy-du-Nord", 1810, "CAD")
    assert route.call_count == 1 and res["resultats"] == []
    cons = res["cadastre"]["consulaire"]
    assert cons["interroge"] is False and cons["noms_lies"][0]["valeur"] == "SAINT-REMY-MAL-BATI"
    assert ("essayer sous l'ancien nom ou lieu rattaché SAINT-REMY-MAL-BATI (« SAINT-REMY-DU-NORD (ANC. MAL BATI) »)"
            in cons["message"])
    assert "Aucun plan du cadastre renvoyé" in res["recherche_negative"] and "noms_lies" in res["recherche_negative"]
    # l'ancien nom, lui, est interrogé au Consulat et renvoie vers le nom actuel pour le napoléonien
    route = _resultats(fixtures, consulaire="saint-remy-mal-bati")
    res = server.archives_registres("AD59", "Saint-Remy-Mal-Bâti", 1810, "CAD")
    assert [(r["titre"], r["cote"], r["categorie"]) for r in res["resultats"]] == [
        ("SAINT-REMY-MAL-BATI / 324", "P 30 / 324", "consulaire")]
    assert route.call_count == 2 and dict(route.calls.last.request.url.params) == {
        "formUuid": CONSULAIRE, **BASE, LIEU: "SAINT-REMY-MAL-BATI", "page": "1"}
    nap = res["cadastre"]["napoleonien"]
    assert nap["interroge"] is False and "essayer sous le nom actuel SAINT-REMY-DU-NORD" in nap["message"]


# ---------------------------------------------------------------------------- commune inconnue, ambiguë

@respx.mock
def test_commune_inconnue_refusee_avant_toute_recherche(app, fixtures):
    formulaires = _formulaires(fixtures)
    recherche = respx.get(URL).respond(200, text="aucune recherche attendue")
    res = server.archives_registres("AD59", "Villeneuve-d'Ascq", 1820, "CAD")
    assert "Aucun des deux formulaires du cadastre AD59 ne connaît cette commune" in res["erreur"]
    assert "VILLENEUVE-D'ASCQ » absente du vocabulaire de ce formulaire" in res["erreur"]
    assert "geo_historique" in res["erreur"] and "lieu_historique" in res["erreur"]
    assert not recherche.called and all(f.call_count == 1 for f in formulaires.values())
    # valeurs proches du vocabulaire : « Marchiennes » n'est pas une valeur, ses subdivisions le sont
    res = server.archives_registres("AD59", "Marchiennes", 1820, "CAD")
    for valeur in ("MARCHIENNES Campagne", "MARCHIENNES Ville", "MARCHIENNES Ville + Campagne"):
        assert valeur in res["erreur"]
    # ancien nom inconnu des deux formulaires : les valeurs liées par le classeur 3 E sont proposées
    res = server.archives_registres("AD59", "Wallers-en-Fagne", 1820, "CAD")
    assert "essayer sous l'ancien nom ou lieu rattaché TRELON (« WALLERS-EN-FAGNE (ANC. TRELON) »)" in res["erreur"]
    assert "WALLERS-TRELON" in res["erreur"]
    assert not recherche.called and len(app.journal.entries(statut="erreur")) == 3


@respx.mock
def test_valeur_exacte_et_commune_ambigue(app, fixtures):
    _formulaires(fixtures)
    route = _resultats(fixtures, consulaire="negative", napoleonien="negative")
    # « Bourbourg » : une seule valeur au napoléonien, deux au Consulat (ambiguë : listées, non interrogée)
    res = server.archives_registres("AD59", "Bourbourg", 1820, "CAD")
    assert _requetes(route) == {"napoleonien": {"formUuid": NAPOLEONIEN, **BASE, LIEU: "BOURBOURG (CAMPAGNE)",
                                                "page": "1"}}
    cons = res["cadastre"]["consulaire"]
    assert cons["interroge"] is False and "ambiguë dans le vocabulaire de ce formulaire" in cons["message"]
    assert "BOURBOURG (CAMPAGNE)" in cons["message"] and "BOURBOURG (VILLE)" in cons["message"]
    # la valeur exacte lève l'ambiguïté, malgré la casse et les accents
    res = server.archives_registres("AD59", "Bourbourg (ville)", 1820, "CAD")
    assert res["cadastre"]["consulaire"]["commune"] == "BOURBOURG (VILLE)"
    assert res["cadastre"]["napoleonien"]["interroge"] is False and res["commune_service"] == "BOURBOURG (VILLE)"
    # article inversé et apostrophe du vocabulaire (« BASSEE (LA) », « CONDE-SUR-L ESCAUT »)
    res = server.archives_registres("AD59", "La Bassée", 1820, "CAD")
    assert {res["cadastre"][c]["commune"] for c in FORMULAIRES.values()} == {"BASSEE (LA)"}
    res = server.archives_registres("AD59", "Condé-sur-l'Escaut", 1820, "CAD")
    assert res["cadastre"]["napoleonien"]["commune"] == "CONDE-SUR-L ESCAUT"
    assert res["cadastre"]["consulaire"]["commune"] is None


# ---------------------------------------------------------------------------- négatif, pagination, pannes

@respx.mock
def test_negatif_non_concluant_et_cache(app, fixtures):
    _formulaires(fixtures)
    route = _resultats(fixtures, consulaire="negative", napoleonien="negative")
    res = server.archives_registres("AD59", "Marly", 1820, "CAD")
    assert res["resultats"] == [] and res["total"] == 0 and res["registres_hors_periode"] == 0
    assert "Aucun plan du cadastre renvoyé pour cette commune" in res["recherche_negative"]
    assert "ne prouve pas qu'aucun plan n'existe" in res["recherche_negative"]
    for categorie in FORMULAIRES.values():
        assert res["cadastre"][categorie]["total"] == 0 and "ne prouve pas" in res["cadastre"][categorie]["message"]
    assert app.journal.entries()[-1]["statut"] == "negatif"
    assert server.archives_registres("AD59", "Marly", 1820, "CAD")["depuis_cache"] is True and route.call_count == 2


@respx.mock
def test_page_au_dela_de_la_derniere(app, fixtures):
    # relevé : page=2 d'une liste d'une page est redirigée vers la première ; rien n'est conclu
    _formulaires(fixtures)
    route = _resultats(fixtures, consulaire="marly", napoleonien="marly")
    res = server.archives_registres("AD59", "Marly", 1820, "CAD", page=2)
    assert "erreur" in res and "Page retournée incohérente" in res["erreur"]
    assert {q["page"] for q in _requetes(route).values()} == {"2"}


@respx.mock
def test_formulaire_change_ou_recherche_en_panne(app, fixtures):
    _formulaires(fixtures, remplacer=("0-controlledAccessGeographicName", "0-autreChamp"))
    recherche = respx.get(URL).respond(200, text="aucune recherche attendue")
    res = server.archives_registres("AD59", "Marly", 1820, "CAD")
    assert "non reconnu (commune absente)" in res["erreur"] and not recherche.called
    respx.clear()
    server.cache_purger("tout")
    _formulaires(fixtures)
    respx.get(URL).respond(503)
    assert "erreur" in server.archives_registres("AD59", "Marly", 1820, "CAD")


# ---------------------------------------------------------------------------- refus

@respx.mock
def test_cad_refuse_pour_un_autre_service_sans_requete(app):
    for service in ("AD58", "AD25"):
        res = server.archives_registres(service, "Nevers", 1820, "CAD")
        assert "CAD (plans du cadastre) : disponible pour AD59 seulement" in res["erreur"]
        assert "n'est pas relevé" in res["erreur"]
    res = server.archives_registres("AD99", "Nevers", 1820, "CAD")  # service sans recherche de registres
    assert "non disponible pour AD99" in res["erreur"]
    assert len(respx.calls) == 0 and len(app.journal.entries(statut="erreur")) == 3


@pytest.mark.parametrize("parametres,attendu", [
    ({"type_acte": "CADX"}, "CAD (plans du cadastre du Consulat et napoléonien) pour AD59"),
    ({"commune": ""}, "commune"),
    ({"annee": 0}, "annee"),
    ({"annee_fin": 1700}, "annee_fin"),
    ({"page": 0}, "page"),
    ({"commune": "X" * 201}, "commune"),
])
@respx.mock
def test_cad_mal_forme_refuse_avant_http(app, parametres, attendu):
    demande = {"service": "AD59", "commune": "Marly", "annee": 1820, "type_acte": "CAD", **parametres}
    res = registres.rechercher(app.sctx, **demande)
    assert attendu in res["erreur"]
    assert len(respx.calls) == 0 and len(app.journal.entries(statut="erreur")) == 1


def test_garde_des_vivants_avant_toute_requete(app_famille):
    # un nom de personne vivante glissé dans le champ de la commune est refusé localement, comme pour les autres types
    with respx.mock(assert_all_called=False) as routes:
        route = routes.route().respond(200, text="aucune requête attendue")
        res = server.archives_registres("AD59", "Lucas MARTIN", 1950, "CAD")
    assert "refus" in res and not route.called


# ---------------------------------------------------------------------------- communicabilité, catalogue

def test_type_cadastre_du_catalogue_inchange():
    res = communicability("cadastre", date_document="1808")
    assert res["delai_annees"] == 0 and res["communicable"] is True
    assert res["regle"] == "Cadastre : communicable immédiatement."
    assert SERIES["cadastre"] == "série P, sous-série 3 P (cadastre napoléonien : plans, états de sections, matrices)"


# ---------------------------------------------------------------------------- non-régression

@respx.mock
def test_types_voisins_inchanges(app, fixtures):
    # HYP, SUCC, FD, RM et REC des AD59 gardent leurs formulaires, leur tri et leurs clés
    formulaires = {registres.FORMULAIRES_ENREGISTREMENT["SUCC"]: "ad59-successions-formulaire.html",
                   registres.FORMULAIRES_ENREGISTREMENT["FD"]: "ad59-fiches-deces-formulaire.html",
                   registres.FORMULAIRES_RM["tables"]: "ad59-matricules-formulaire-tables.html",
                   registres.FORMULAIRES_RM["fiches"]: "ad59-matricules-formulaire-fiches.html",
                   registres.FORMULAIRES_HYP["indicateur"]: "ad59-hypotheques-formulaire-indicateur.html"}
    for uuid, nom in formulaires.items():
        respx.get(f"{HOTE}/search/form/{uuid}").respond(200, text=(fixtures / nom).read_text())
    pages = {registres.FORMULAIRES_ENREGISTREMENT["SUCC"]: "ad59-successions-intervalle.html",
             registres.FORMULAIRES_ENREGISTREMENT["FD"]: "ad59-fiches-deces-positive.html",
             registres.FORMULAIRES_RM["tables"]: "ad59-matricules-tables-bureau.html",
             registres.FORMULAIRES_RM["fiches"]: "ad59-matricules-fiches-bureau.html",
             registres.FORMULAIRES_HYP["indicateur"]: "ad59-hypotheques-indicateur-cambrai.html",
             registres.FORMULAIRE_REC: "ad59-recensements-positive.html"}
    route = respx.get(URL).mock(side_effect=lambda request: httpx.Response(
        200, text=(fixtures / pages[request.url.params["formUuid"]]).read_text()))
    nouvelles = {"cadastre", "annee_titre", "planche_contact", "noms_lies", "position_periode"}
    succ = server.archives_registres("AD59", "Steenvoorde", 1791, "SUCC", annee_fin=1803)
    assert [r["cote"] for r in succ["resultats"]] == ["3Q - 516 / 1", "3Q - 516 / 2"]
    assert route.calls[-1].request.url.params["sort"] == "date_asc" and "successions" in succ
    fd = server.archives_registres("AD59", "Lille (Centre)", 1969, "FD")
    assert len(fd["resultats"]) == 6 and "fiches_deces" in fd and "avertissement_communicabilite" in fd
    rm = server.archives_registres("AD59", "Avesnes", 1890, "RM")
    assert {r["categorie"] for r in rm["resultats"]} == {"tables", "fiches"} and "matricules" in rm
    rec = server.archives_registres("AD59", "Somain", 1906, "REC")
    assert [r["cote"] for r in rec["resultats"]] == ["M 474 / 572"] and rec["registres_hors_periode"] == 3
    hyp = server.archives_registres("AD59", "Cambrai", 1850, "HYPI")
    assert [r["cote"] for r in hyp["resultats"]] == [f"4Q 63 / 00{i}" for i in range(1, 6)] and "hypotheques" in hyp
    assert hyp["resultats"][0]["plage_alphabetique"]["debut"] == "ABADEAU"
    for res in (succ, fd, rm, rec, hyp):
        assert "erreur" not in res and not nouvelles & set(res)
        assert all(not nouvelles & set(r) for r in res["resultats"])


@respx.mock
def test_autre_service_mnesys_inchange(app, monkeypatch):
    hote, uuid = "https://archives.exemple.fr", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    svc = {"code": "AD99", "nom": "Archives fictives", "type": "departementales", "departement": "99", "site": hote,
           "ark_naan": "99999", "recherche_registres": {"formulaires": {"successions": uuid}, "releve_le": "2026-11-18",
                                                        "reference": f"{hote}/search/form/{uuid}"}}
    reel = archives.by_code
    monkeypatch.setattr(archives, "by_code", lambda c: svc if (c or "").upper() == "AD99" else reel(c))
    res = registres.rechercher(app.sctx, "AD99", "Ville-Fictive", 1820, "CAD")
    assert "disponible pour AD59 seulement" in res["erreur"] and len(respx.calls) == 0


def test_documentation_de_l_outil():
    doc = server.archives_registres.__doc__
    assert "AD59 seulement : CAD (plans du cadastre, non nominatifs" in doc
    assert "categorie (consulaire, napoleonien)" in doc and "planche_contact" in doc and "noms_lies" in doc
    assert "matrices, états de sections" in doc


# ---------------------------------------------------------------------------- orientation

def test_piste_cadastre_du_nord_sans_cote_inventee():
    piste = next(p for p in next_source_hint("RESI", "1850", "Estaires (59)") if "cadastre_ad59" in p)
    assert piste["cote_typique"] == SERIES["recensements"]
    aide = piste["cadastre_ad59"]
    assert aide["service"] == "AD59" and aide["releve_le"] == "2026-11-27" and aide["serie"] == SERIES["cadastre"]
    assert 'commune="Estaires"' in aide["recherche"] and 'type_acte="CAD"' in aide["recherche"]
    assert "lieu-dit" in aide["note"] and "non nominatifs" in aide["note"] and "non couverts" in aide["note"]
    assert "P 3" not in str(aide).replace(SERIES["cadastre"], "")  # aucune cote P 30 / P 31 proposée
    # un bien : piste « Actes notariés », à côté des hypothèques, sans les remplacer
    bien = next(p for p in next_source_hint("PROP", "1900", "Lille (59)") if "cadastre_ad59" in p)
    assert bien["source"] == "Actes notariés" and "hypotheques_ad59" in bien
    # ni hors du Nord, ni sans lieu, ni pour un fait sans piste de domicile ou de bien
    for fait, annee, lieu in (("RESI", "1850", "Arras (62)"), ("RESI", "1850", ""), ("BIRT", "1850", "Lille (59)"),
                              ("MARR", "1850", "Lille (59)"), ("DEAT", "1850", "Lille (59)")):
        assert all("cadastre_ad59" not in p for p in next_source_hint(fait, annee, lieu)), (fait, annee, lieu)
    # les autres clés du Nord restent jointes
    assert any("hypotheques_ad59" in p for p in next_source_hint("MARR", "1850", "Somain (59)"))
    assert any("successions_ad59" in p for p in next_source_hint("DEAT", "1850", "Somain (59)"))
