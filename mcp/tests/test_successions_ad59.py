"""Enregistrement des AD59 (#377) : tables des successions et absences (SUCC, 3 Q) et fiches décès (FD, W).

Fixtures : formulaires et pages de résultats publics relevés le 27 novembre 2026, réduits aux balises lues
(volumes publics, aucune personne). Aucun réseau."""

from datetime import date

import pytest
import respx

from genealogiste_mcp import archives, server
from genealogiste_mcp.fr_sources import communicability, next_source_hint
from genealogiste_mcp.sources import registres
from genealogiste_mcp.types_documents import SERIES

HOTE = "https://archivesdepartementales.lenord.fr"
URL = f"{HOTE}/search/results"
TABLES, FICHES = registres.FORMULAIRES_ENREGISTREMENT["SUCC"], registres.FORMULAIRES_ENREGISTREMENT["FD"]
BASE = {"mode": "list", "facet_media": "image"}
LIEU = "0-controlledAccessGeographicName[]"
PAGE = f"{HOTE}/page/tables-des-successions-et-absences-fiches-deces"


def _formulaire(fixtures, type_acte="SUCC", texte=None):
    uuid, nom = (TABLES, "ad59-successions-formulaire.html") if type_acte == "SUCC" else (
        FICHES, "ad59-fiches-deces-formulaire.html")
    return respx.get(f"{HOTE}/search/form/{uuid}").respond(200, text=texte or (fixtures / nom).read_text())


def _resultats(fixtures, nom):
    return respx.get(URL).respond(200, text=nom if nom.lstrip().startswith("<") else (fixtures / nom).read_text())


def _requete(route, i=-1):
    return dict(route.calls[i].request.url.params)


# ---------------------------------------------------------------------------- formulaires

def test_formulaires_releves_champs_et_bureaux(fixtures):
    def lire(nom):
        parser = registres._HTML()
        parser.feed((fixtures / nom).read_text())
        return registres.mnesys.lire_formulaire(parser.racine.trouver())

    tables = lire("ad59-successions-formulaire.html")
    assert (tables["commune"], tables["date"], tables["debut"], tables["fin"]) == (
        "0-controlledAccessGeographicName", "2-date", "1-date_begin", "1-date_end")
    assert len(tables["communes"]) == 56 and tables["typologies"] == {}
    assert {"STEENVOORDE", "LILLE", "LILLE (1er bureau)", "ROUBAIX (Ville)", "VALENCIENNES (Canton Est)"} <= set(
        tables["communes"])
    fiches = lire("ad59-fiches-deces-formulaire.html")
    assert (fiches["commune"], fiches["date"], fiches["debut"], fiches["fin"]) == (
        "0-controlledAccessGeographicName", "1-date", None, None)
    assert len(fiches["communes"]) == 28 and fiches["typologies"] == {}
    assert {"LILLE (Centre)", "AVESNES", "DOUAI (Nord-Ouest-Est)"} <= set(fiches["communes"])
    assert "LILLE" not in fiches["communes"]  # les deux vocabulaires diffèrent : aucun n'est recopié dans le code
    assert "Année précise entre 1969 et 1975 (facultatif)" in (
        fixtures / "ad59-fiches-deces-formulaire.html").read_text()


# ---------------------------------------------------------------------------- SUCC (tables, 3 Q)

@respx.mock
def test_succ_intervalle_bureau_cote_et_ark_reels(app, fixtures):
    formulaire = _formulaire(fixtures)
    route = _resultats(fixtures, "ad59-successions-intervalle.html")
    res = server.archives_registres("AD59", "Steenvoorde", 1791, "SUCC", annee_fin=1803)
    assert "erreur" not in res, res
    assert formulaire.call_count == 1 and route.call_count == 1
    assert _requete(route) == {"formUuid": TABLES, "sort": "date_asc", **BASE, LIEU: "STEENVOORDE",
                               "1-date_begin": "1791", "1-date_end": "1803", "page": "1"}
    assert res["resultats"] == [
        {"titre": "STEENVOORDE / 3Q - 516 / 1 [1791 - An 12]", "cote": "3Q - 516 / 1",
         "ark": "ark:/33518/5hnwpt8xqz67", "url": f"{HOTE}/ark:/33518/5hnwpt8xqz67", "bornes": [1791, 1803],
         "nb_vues": 70, "contexte": "Tables des successions et absences (cote 3Q)"},
        {"titre": "STEENVOORDE / 3Q - 516 / 2 [An 12 - 1811]", "cote": "3Q - 516 / 2",
         "ark": "ark:/33518/jqwc3pfb0285", "url": f"{HOTE}/ark:/33518/jqwc3pfb0285", "bornes": [1803, 1811],
         "nb_vues": 74, "contexte": "Tables des successions et absences (cote 3Q)"}]
    assert res["total"] == res["nb_renvoyes"] == 2 and res["page"] == 1
    assert res["page_suivante"] is None and res["fin"] is True and res["periode"] == [1791, 1803]
    assert res["commune_service"] == "STEENVOORDE"
    s = res["successions"]
    assert s["releve_le"] == "2026-11-27" and s["formulaire"] == TABLES and s["bureau"] == "STEENVOORDE"
    assert s["autres_bureaux"] == [] and s["reference"] == PAGE
    assert "1791-1968" in s["periode_annoncee"] and "contenu des vues n'est pas lu" in s["lecture"]
    # ni fiches décès, ni classeur 3 E, ni recensements, ni matricules, ni filtre local
    assert not {"fiches_deces", "avertissement_communicabilite", "classeur_3e", "couverture_recensements",
                "matricules", "registres_hors_periode", "recherche_negative"} & set(res)
    assert all("communicable_a_partir_de" not in r for r in res["resultats"])
    assert "ne prouve pas la présence" in res["avertissement"]
    assert len(app.journal.entries()) == 1 and app.journal.entries()[0]["statut"] == "positif"


@respx.mock
def test_succ_annee_seule_envoyee_comme_intervalle(app, fixtures):
    # comme pour SUCC ailleurs : la période d'abord, même pour une année (volume pluriannuel 1791-An 12)
    _formulaire(fixtures)
    route = _resultats(fixtures, "ad59-successions-annee.html")
    res = registres.rechercher(app.sctx, "ad59", "steenvoorde", 1800, "succ", personne="I42")
    assert "erreur" not in res, res
    q = _requete(route)
    assert q["1-date_begin"] == q["1-date_end"] == "1800" and "2-date" not in q
    assert [(r["cote"], r["bornes"]) for r in res["resultats"]] == [("3Q - 516 / 1", [1791, 1803])]
    assert "I42" not in "".join(str(c.request.url) for c in respx.calls)
    assert app.journal.entries()[0]["personne"] == "I42"


@respx.mock
def test_succ_page_2_reelle_et_bureaux_de_meme_nom(app, fixtures):
    _formulaire(fixtures)
    route = _resultats(fixtures, "ad59-successions-page2.html")
    res = server.archives_registres("AD59", "Lille", 1791, "SUCC", page=2, annee_fin=1969)
    assert "erreur" not in res, res
    assert _requete(route)[LIEU] == "LILLE" and _requete(route)["page"] == "2"
    assert len(res["resultats"]) == 20 and res["total"] == 67
    assert res["page"] == 2 and res["page_suivante"] == 3 and res["fin"] is False
    assert res["resultats"][0]["titre"] == "LILLE / 3Q - 338 / 29 [01/10/1841 - 15/07/1842]"
    assert (res["resultats"][0]["cote"], res["resultats"][0]["bornes"], res["resultats"][0]["nb_vues"]) == (
        "3Q - 338 / 29", [1841, 1842], 184)
    # « Lille » désigne la valeur sans qualificatif ; les bureaux homonymes sont signalés, pas interrogés
    assert res["successions"]["bureau"] == "LILLE"
    assert res["successions"]["autres_bureaux"] == ["LILLE (1er bureau)", "LILLE (2e bureau)", "LILLE (3e bureau)"]
    assert route.call_count == 1  # aucune autre page lue d'office


@respx.mock
def test_succ_page_hors_bornes_est_une_erreur(app, fixtures):
    # le service redirige une page inexistante vers la première (observé) : rien n'est conclu
    _formulaire(fixtures)
    _resultats(fixtures, "ad59-successions-intervalle.html")
    res = registres.rechercher(app.sctx, "AD59", "Steenvoorde", 1791, "SUCC", page=2, annee_fin=1803)
    assert "erreur" in res and "resultats" not in res and "recherche_negative" not in res
    assert len(app.journal.entries(statut="erreur")) == 1


@respx.mock
def test_succ_negatif_non_concluant_et_cache(app, fixtures):
    _formulaire(fixtures)
    route = _resultats(fixtures, "ad59-successions-negative.html")
    for cached in (False, True):
        res = server.archives_registres("AD59", "Steenvoorde", 1200, "SUCC")
        assert "erreur" not in res, res
        assert res["resultats"] == [] and res["total"] == 0 and res["fin"] is True
        assert res["depuis_cache"] is cached
        negatif = res["recherche_negative"]
        assert "ne prouve ni l'absence d'un décès ni celle d'une succession" in negatif
        assert "1791-1968" in negatif and "bureau" in negatif and "annee_fin" in negatif
        assert "classeur_3e" not in res and res["successions"]["bureau"] == "STEENVOORDE"
        assert app.journal.entries()[-1]["statut"] == "negatif"
    assert route.call_count == 1 and len(app.journal.entries()) == 2


@respx.mock
def test_succ_bureau_inconnu_ou_ambigu_refuse_avant_toute_recherche(app, fixtures):
    _formulaire(fixtures)
    route = respx.get(URL).respond(500)
    # une commune du ressort n'est pas un bureau : le vocabulaire lu est rendu, rien n'est deviné
    res = server.archives_registres("AD59", "Somain", 1850, "SUCC")
    assert "Bureau de l'enregistrement « SOMAIN » absente du vocabulaire" in res["erreur"]
    assert "pas la commune du décès" in res["erreur"]
    assert "Bureaux proposés par le formulaire : ARLEUX, ARMENTIERES, AVESNES" in res["erreur"]
    assert "MARCHIENNES" in res["erreur"] and "WORMHOUT." in res["erreur"]
    # vocabulaire réel : quatre « VALENCIENNES (…) », aucun sans qualificatif
    res = server.archives_registres("AD59", "Valenciennes", 1850, "SUCC")
    assert "ambiguë" in res["erreur"] and "Bureaux proposés" not in res["erreur"]
    for valeur in ("VALENCIENNES (Canton Est)", "VALENCIENNES (Canton)", "VALENCIENNES (Ville et Canton Sud)",
                   "VALENCIENNES (Ville)"):
        assert valeur in res["erreur"]
    assert not route.called and len(app.journal.entries(statut="erreur")) == 2


@respx.mock
def test_succ_valeur_exacte_du_vocabulaire_malgre_la_casse(app, fixtures):
    _formulaire(fixtures)
    route = _resultats(fixtures, "ad59-successions-negative.html")
    res = server.archives_registres("AD59", "Valenciennes (Ville)", 1850, "SUCC")
    assert "erreur" not in res, res
    assert _requete(route)[LIEU] == "VALENCIENNES (Ville)" and res["commune_service"] == "VALENCIENNES (Ville)"
    assert res["successions"]["autres_bureaux"] == [
        "VALENCIENNES (Canton Est)", "VALENCIENNES (Canton)", "VALENCIENNES (Ville et Canton Sud)"]


@respx.mock
def test_succ_formulaire_change_ou_recherche_en_panne(app, fixtures):
    sans_periode = (fixtures / "ad59-successions-formulaire.html").read_text().replace('name="1-date_end"', "")
    _formulaire(fixtures, texte=sans_periode)
    route = respx.get(URL).respond(503)
    res = registres.rechercher(app.sctx, "AD59", "Steenvoorde", 1800, "SUCC")
    assert "non reconnu" in res["erreur"] and not route.called
    respx.get(f"{HOTE}/search/form/{FICHES}").respond(200, text=(fixtures / "ad59-fiches-deces-formulaire.html")
                                                     .read_text())
    res = registres.rechercher(app.sctx, "AD59", "Avesnes", 1970, "FD")
    assert "resultats" not in res and "recherche_negative" not in res and route.call_count == 1  # une tentative
    assert len(app.journal.entries(statut="erreur")) == 2


# ---------------------------------------------------------------------------- FD (fiches décès, W)

@respx.mock
def test_fd_annee_precise_avertissement_de_communicabilite(app, fixtures):
    formulaire = _formulaire(fixtures, "FD")
    route = _resultats(fixtures, "ad59-fiches-deces-positive.html")
    res = server.archives_registres("AD59", "Lille (Centre)", 1969, "FD")
    assert "erreur" not in res, res
    assert formulaire.call_count == 1 and route.call_count == 1
    assert _requete(route) == {"formUuid": FICHES, "sort": "referencecode_asc", **BASE, LIEU: "LILLE (Centre)",
                               "1-date": "1969", "page": "1"}
    assert [(r["titre"], r["cote"], r["nb_vues"]) for r in res["resultats"]] == [
        ("LILLE (Centre) [1969] A - C", "2571 W 01", 302), ("LILLE (Centre) [1969] D", "2571 W 02", 304),
        ("LILLE (Centre) [1969] E - K", "2571 W 03", 276), ("LILLE (Centre) [1969] L - M", "2571 W 04", 296),
        ("LILLE (Centre) [1969] N - S", "2571 W 05", 246), ("LILLE (Centre) [1969] T - Z", "2571 W 06", 206)]
    assert res["resultats"][3] == {
        "titre": "LILLE (Centre) [1969] L - M", "cote": "2571 W 04", "ark": "ark:/33518/qkwfpghmn457",
        "url": f"{HOTE}/ark:/33518/qkwfpghmn457", "bornes": [1969, 1969], "nb_vues": 296,
        "contexte": "Fiches Décès (W) : Accès aux fiches de + de 50 ans…", "communicable_a_partir_de": 2020}
    assert res["total"] == 6 and res["fin"] is True and res["commune_service"] == "LILLE (Centre)"
    f = res["fiches_deces"]
    assert f["formulaire"] == FICHES and f["bureau"] == "LILLE (Centre)" and f["periode_annoncee"] == "1969 à 1975"
    assert f["autres_bureaux"] == ["LILLE (Est)", "LILLE (Haubourdin)", "LILLE (Nord)", "LILLE (Ouest)",
                                   "LILLE (Seclin)"]
    assert "numéro de la déclaration de succession" in f["lecture"] and "n'est pas lu" in f["lecture"]
    # communicabilité : délai affirmé par le service, sourcé, jamais « librement communicable »
    c = f["communicabilite"]
    assert c["type_document"] == "vie_privee" and c["delai_annees"] == 50 and c["source"] == PAGE
    assert c["releve_le"] == "2026-11-27" and c["fiches_ecartees"] == 0
    assert c["periode_demandee_communicable_a_partir_de"] == 2020 and c["periode_demandee_communicable"] is True
    assert "plus de 50 ans" in c["selon_le_service"] and "non vérifié" in c["non_verifie"]
    assert "ni l'article applicable" in c["non_verifie"]
    avertissement = res["avertissement_communicabilite"]
    assert "ne pas les tenir pour librement communicables" in avertissement
    assert "n'a pas été vérifié par le plugin" in avertissement and "héritiers encore vivants" in avertissement
    assert "écarté" not in avertissement
    assert "librement communicable" not in str(res).replace("pour librement communicables", "")
    assert not {"successions", "classeur_3e", "registres_hors_periode", "recherche_negative"} & set(res)
    assert app.journal.entries()[0]["statut"] == "positif"


@respx.mock
def test_fd_fiche_de_moins_de_50_ans_ecartee(app, fixtures):
    # page synthétique : le service ne publie pas de fiche récente ; si une réponse en contenait, elle serait écartée
    recent = str(date.today().year - 10)
    page = (fixtures / "ad59-fiches-deces-positive.html").read_text().replace(
        "<p><span>1969</span></p>", f"<p><span>{recent}</span></p>", 2)
    _formulaire(fixtures, "FD")
    _resultats(fixtures, page)
    res = server.archives_registres("AD59", "Lille (Centre)", int(recent), "FD")
    assert "erreur" not in res, res
    assert len(res["resultats"]) == 4 and all(r["bornes"] == [1969, 1969] for r in res["resultats"])
    c = res["fiches_deces"]["communicabilite"]
    assert c["fiches_ecartees"] == 2 and c["periode_demandee_communicable"] is False
    assert c["periode_demandee_communicable_a_partir_de"] == int(recent) + 51
    assert "2 résultat(s) de moins de 50 ans écarté(s)" in res["avertissement_communicabilite"]
    assert recent not in str(res["resultats"])


@respx.mock
def test_fd_intervalle_filtre_localement(app, fixtures):
    _formulaire(fixtures, "FD")
    route = _resultats(fixtures, "ad59-fiches-deces-positive.html")
    res = server.archives_registres("AD59", "Lille (Centre)", 1968, "FD", annee_fin=1969)
    assert "erreur" not in res, res
    assert "1-date" not in _requete(route) and _requete(route)[LIEU] == "LILLE (Centre)"  # aucune date envoyée
    assert len(res["resultats"]) == 6 and res["registres_hors_periode"] == 0
    assert all(r["couvre_periode"] is True for r in res["resultats"])
    res = server.archives_registres("AD59", "Lille (Centre)", 1970, "FD", annee_fin=1972)
    assert res["resultats"] == [] and res["registres_hors_periode"] == 6
    assert "Aucun volume de fiches décès de cette page ne couvre 1970-1972" in res["recherche_negative"]
    assert "ni l'absence d'un décès ni celle d'une succession" in res["recherche_negative"]
    assert "avertissement_communicabilite" in res and route.call_count == 1  # même page, lue en cache


@respx.mock
def test_fd_negatif_garde_l_avertissement(app, fixtures):
    _formulaire(fixtures, "FD")
    _resultats(fixtures, "ad59-fiches-deces-negative.html")
    res = server.archives_registres("AD59", "Avesnes", 1200, "FD")
    assert "erreur" not in res, res
    assert res["resultats"] == [] and res["total"] == 0
    assert "Aucun volume de fiches décès renvoyé" in res["recherche_negative"]
    assert "1969 à 1975" in res["recherche_negative"] and "annee_fin" not in res["recherche_negative"]
    assert "ne pas les tenir pour librement communicables" in res["avertissement_communicabilite"]
    assert res["fiches_deces"]["bureau"] == "AVESNES" and res["fiches_deces"]["autres_bureaux"] == []
    assert app.journal.entries()[0]["statut"] == "negatif"


@respx.mock
def test_fd_bureau_ambigu_ou_inconnu(app, fixtures):
    _formulaire(fixtures, "FD")
    route = respx.get(URL).respond(500)
    res = server.archives_registres("AD59", "Lille", 1969, "FD")  # vocabulaire réel : six « LILLE (…) »
    assert "ambiguë" in res["erreur"] and "LILLE (Centre)" in res["erreur"] and "LILLE (Seclin)" in res["erreur"]
    res = server.archives_registres("AD59", "Steenvoorde", 1969, "FD")  # bureau des tables, absent des fiches
    assert "absente du vocabulaire" in res["erreur"] and "Bureaux proposés par le formulaire : ARMENTIERES" in res[
        "erreur"]
    assert "commune" in server.archives_registres("AD59", "", 1969, "FD")["erreur"]  # bureau obligatoire
    assert "commune" in server.archives_registres("AD59", "", 1850, "SUCC")["erreur"]
    assert not route.called


@respx.mock
def test_fd_refuse_pour_un_autre_service_sans_requete(app):
    for service in ("AD58", "AD91"):
        res = server.archives_registres(service, "Nevers", 1970, "FD")
        assert "FD (fiches décès de l'enregistrement) : disponible pour AD59 seulement" in res["erreur"]
        assert "n'est pas relevé" in res["erreur"]
    assert len(respx.calls) == 0 and len(app.journal.entries(statut="erreur")) == 2


@pytest.mark.parametrize("parametres,attendu", [
    ({"type_acte": "FDX"}, "FD (fiches décès de l'enregistrement) pour AD59"),
    ({"type_acte": "FD", "annee": 0}, "annee"),
    ({"type_acte": "SUCC", "annee_fin": 1700}, "annee_fin"),
    ({"type_acte": "FD", "page": 0}, "page"),
    ({"type_acte": "SUCC", "commune": "X" * 201}, "commune"),
])
@respx.mock
def test_succ_et_fd_mal_formes_refuses_avant_http(app, parametres, attendu):
    demande = {"service": "AD59", "commune": "Lille", "annee": 1850, **parametres}
    res = registres.rechercher(app.sctx, **demande)
    assert attendu in res["erreur"]
    assert len(respx.calls) == 0 and len(app.journal.entries(statut="erreur")) == 1


# ---------------------------------------------------------------------------- non-régression

@respx.mock
def test_succ_d_un_autre_service_mnesys_inchange(app, fixtures, monkeypatch):
    hote, uuid = "https://archives.exemple.fr", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    svc = {"code": "AD99", "nom": "Archives fictives", "type": "departementales", "departement": "99", "site": hote,
           "ark_naan": "99999", "recherche_registres": {"formulaires": {"successions": uuid}, "releve_le": "2026-11-18",
                                                        "reference": f"{hote}/search/form/{uuid}"}}
    reel = archives.by_code
    monkeypatch.setattr(archives, "by_code", lambda c: svc if (c or "").upper() == "AD99" else reel(c))
    respx.get(f"{hote}/search/form/{uuid}").respond(
        200, text=(fixtures / "mnesys-formulaire-successions.html").read_text())
    route = respx.get(f"{hote}/search/results").respond(
        200, text=(fixtures / "mnesys-recherche-positive.html").read_text())
    res = registres.rechercher(app.sctx, "AD99", "Ville-Fictive", 1876, "SUCC", annee_fin=1882)
    assert "erreur" not in res, res
    assert _requete(route) == {
        "formUuid": uuid, "sort": "date_asc", **BASE, "0-title[]": "Bureau de Ville-Fictive",
        "2-date_begin": "1876", "2-date_end": "1882",
        "1-controlledAccessPhysicalCharacteristic[]": "Table de successions", "page": "1"}
    assert res["commune_service"] == "Bureau de Ville-Fictive"
    assert not {"successions", "fiches_deces", "avertissement_communicabilite"} & set(res)
    assert all("contexte" not in r and "communicable_a_partir_de" not in r for r in res["resultats"])


def test_documentation_de_l_outil():
    doc = server.archives_registres.__doc__
    assert "FD (fiches décès" in doc and "AD59 seulement : FD" in doc and "non vérifié par le plugin" in doc
    assert "AD58, AD59, AD69" in doc and "avertissement_communicabilite" in doc


# ---------------------------------------------------------------------------- pistes et communicabilité

def test_piste_successions_du_nord_sans_cote_inventee():
    piste = next(p for p in next_source_hint("DEAT", "1850", "Somain (59)") if "successions_ad59" in p)
    assert piste["cote_typique"] == SERIES["enregistrement"]  # orientation inchangée
    aide = piste["successions_ad59"]
    assert aide["service"] == "AD59" and aide["releve_le"] == "2026-11-27"
    assert aide["recherche"] == ('archives_registres(service="AD59", commune="<bureau de l\'enregistrement>", '
                                 'annee=1850, type_acte="SUCC")')
    assert "fiches_deces" not in aide and "pas la commune" in aide["note"]
    assert "Aucune cote n'est proposée" in aide["note"] and "3Q" not in str(aide) and " W " not in str(aide)
    # décès de 1969 à 1975 : fiches décès, avec leur avertissement ; pas de table
    aide = next(p for p in next_source_hint("DEAT", "1972", "Lille (59)") if "successions_ad59" in p)[
        "successions_ad59"]
    assert "recherche" not in aide and 'annee=1972, type_acte="FD"' in aide["fiches_deces"]["recherche"]
    assert "ne pas les tenir pour librement communicables" in aide["fiches_deces"]["avertissement"]
    assert "n'a pas été vérifié" in aide["fiches_deces"]["avertissement"]
    # décès postérieur à ce qui est en ligne : aucune recherche proposée
    aide = next(p for p in next_source_hint("DEAT", "1990", "Lille (59)") if "successions_ad59" in p)[
        "successions_ad59"]
    assert "recherche" not in aide and "fiches_deces" not in aide and "aucune recherche proposée" in aide["note"]
    # filiation : la date du fait n'est pas celle du décès du parent, aucune année calculée
    aide = next(p for p in next_source_hint("FILIATION", "1850", "Somain (59)") if "successions_ad59" in p)[
        "successions_ad59"]
    assert "annee=<année du décès>" in aide["recherche"] and "fiches_deces" in aide
    # hors du Nord, sans lieu, ou fait sans piste d'enregistrement : rien d'ajouté
    for fait, annee, lieu in (("DEAT", "1850", "Nevers (58)"), ("DEAT", "1850", ""), ("MARR", "1850", "Somain (59)"),
                              ("DEAT", "1780", "Somain (59)")):
        assert all("successions_ad59" not in p for p in next_source_hint(fait, annee, lieu)), (fait, annee, lieu)


def test_communicabilite_inchangee_pour_les_fiches_deces():
    # aucun type ajouté : le délai de 50 ans affirmé par le service est celui du type existant « vie_privee »
    assert registres.DELAI_FD == 50
    res = communicability("vie_privee", date_document="1975", today=date(2026, 11, 27))
    assert res["delai_annees"] == 50 and res["communicable_a_partir_de"] == 2026 and res["communicable"] is True
    res = communicability("vie_privee", date_document="1976", today=date(2026, 11, 27))
    assert res["communicable"] is False and res["communicable_a_partir_de"] == 2027
    # le type large « enregistrement » ne déduit toujours aucun délai
    assert communicability("enregistrement", "1969", today=date(2026, 11, 27))["communicable"] is None
    assert "erreur" in communicability("fiches_deces", "1969")
