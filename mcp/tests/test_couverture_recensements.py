"""Recensements de population des AD59 (#375) : type REC, analyse du PDF, référentiel, recherche locale, pistes.

``fixtures/ad59-recensements-extrait.pdf`` : pages 1, 20, 33, 54 et 64 du PDF public « Recensements de population,
État de la collection » (relevé du 27 novembre 2026), sans modification. ``ad59-recensements-positive.html``
(Somain, 4 résultats) et ``ad59-recensements-page2.html`` (Buysscheure, page 2 sur 2, 26 résultats) : pages de
résultats relevées le même jour, réduites aux balises lues. Aucune personne n'y figure. Aucun accès réseau.
"""

import hashlib
import json
import re
import runpy
from pathlib import Path

import pytest
import respx

from genealogiste_mcp import couverture_recensements as recensements
from genealogiste_mcp import server
from genealogiste_mcp.fr_sources import next_source_hint
from genealogiste_mcp.sources import registres

ROOT = Path(__file__).resolve().parents[2]
PDF = Path(__file__).parent / "fixtures" / "ad59-recensements-extrait.pdf"
URL = "https://archivesdepartementales.lenord.fr/search/results"
ENTETE = ["COMMUNE", "ANNEE", "COTE", "Mis en ligne", "Salle de lecture"]


@pytest.fixture(scope="module")
def script():
    return runpy.run_path(str(ROOT / "scripts/generer_couverture_recensements_ad59.py"))


@pytest.fixture(scope="module")
def extrait(script):
    return script["generer"](PDF, "2026-11-27")


def _volume(ref: dict, commune: str, cote: str) -> dict:
    return next(v for v in ref["communes"][commune] if v["cote"] == cote)


# ---------------------------------------------------------------------------- analyse du PDF

def test_extrait_reel_du_pdf(extrait):
    assert extrait["lignes"] == extrait["volumes"] == 310 and extrait["lignes_rejetees"] == []
    assert (extrait["en_ligne"], extrait["salle_de_lecture"], extrait["annees_illisibles"]) == (223, 87, 0)
    assert extrait["sha256"] == hashlib.sha256(PDF.read_bytes()).hexdigest()
    assert extrait["source"] == recensements.SOURCE and extrait["document"] == recensements.DOCUMENT
    assert extrait["communes"]["SOMAIN"] == [
        {"debut": 1901, "fin": 1901, "cote": "M 473 063 10 SOMAIN", "acces": "en_ligne"},
        {"debut": 1906, "fin": 1906, "cote": "M 474 572", "acces": "en_ligne"},
        {"debut": 1931, "fin": 1931, "cote": "M 474 5 19 SOMAIN", "acces": "en_ligne"},
        {"debut": 1946, "fin": 1946, "cote": "M 474 7 25 SOMAIN", "acces": "en_ligne"},
        {"debut": 1954, "fin": 1954, "cote": "M 474 8 19 SOMAIN", "acces": "salle_de_lecture"}]
    # la croix de la colonne « Salle de lecture » n'est pas prise pour une mise en ligne
    assert _volume(extrait, "ABANCOURT", "M 474 11 1 ABANCOURT")["acces"] == "salle_de_lecture"
    assert _volume(extrait, "ABANCOURT", "M 474 001")["acces"] == "en_ligne"


def test_cotes_et_libelles_gardes_tels_quels(extrait):
    assert _volume(extrait, "WYLDER", "E DEPOT 004 An8") == {
        "debut": 1799, "fin": 1800, "cote": "E DEPOT 004 An8", "acces": "en_ligne", "annee": "1799-1800"}
    assert _volume(extrait, "WYLDER", "5Z 463 WYLDER 1826")["debut"] == 1826
    mention = _volume(extrait, "ESCAUDOEUVRES", "M 474 7 6 ESCAUDOEUVRES")  # mention gardée, millésime = 1946
    assert (mention["debut"], mention["fin"], mention["annee"]) == (1946, 1946, "1946 avec retombes 1954")
    assert {"Lille : non versé", "LILLE CANTON SUD EST", "LES MOERES"} <= set(extrait["communes"])
    assert _volume(extrait, "LILLE EST", "M 474 6 18a LILLEEST")["debut"] == 1936


@pytest.mark.parametrize("cellules, attendu", [
    (["SOMAIN", "1906", "M 474 572", "X", ""], ("SOMAIN", 1906, 1906, "M 474 572", "en_ligne", None)),
    (["SOMAIN", "1954", "M 474 8 19\nSOMAIN", None, "x"],  # cellule coupée, croix en minuscule
     ("SOMAIN", 1954, 1954, "M 474 8 19 SOMAIN", "salle_de_lecture", None)),
    (["WYLDER", "1798 - 1799", "E DEPOT 004 1798", "X", ""],
     ("WYLDER", 1798, 1799, "E DEPOT 004 1798", "en_ligne", "1798 - 1799")),
    (["Lille : non versé", "1906", "M 474 357", "X", ""],
     ("Lille : non versé", 1906, 1906, "M 474 357", "en_ligne", None)),
    (["SOMAIN", "an VIII", "E DEPOT 1", "X", ""], ("SOMAIN", None, None, "E DEPOT 1", "en_ligne", "an VIII")),
    (["SOMAIN", "1800-1799", "E DEPOT 1", "X", ""], ("SOMAIN", None, None, "E DEPOT 1", "en_ligne", "1800-1799")),
])
def test_lignes(cellules, attendu):
    commune, v, lisible = recensements.analyser_ligne(cellules)
    assert (commune, v["debut"], v["fin"], v["cote"], v["acces"], v.get("annee")) == attendu
    assert lisible is (v["debut"] is not None)


def test_entete_et_ligne_vide_ignorees():
    assert recensements.analyser_ligne(ENTETE) is None
    assert recensements.analyser_ligne(["", None, "", "", ""]) is None


@pytest.mark.parametrize("cellules", [
    ["SOMAIN", "1906", "M 474 572", "X", "X"],   # deux croix
    ["SOMAIN", "1906", "M 474 572", "", ""],     # aucune croix
    ["SOMAIN", "1906", "M 474 572", "oui", ""],  # autre contenu
    ["SOMAIN", "1906", "", "X", ""],
    ["SOMAIN", "", "M 474 572", "X", ""],
    ["SOMAIN", "1906", "M 474 572", "X"],        # colonne d'accès manquante : position de la croix inconnue
    ["SOMAIN 1906 M 474 572 X"],
])
def test_ligne_ambigue_ou_inexploitable_rejetee(cellules):
    with pytest.raises(recensements.EtatCollectionError):
        recensements.analyser_ligne(cellules)


def test_refus_au_dela_des_seuils_d_erreur():
    bonnes = [["SOMAIN", "1906", f"M 474 {i}", "X", ""] for i in range(400)]
    ambigue = ["SOMAIN", "1906", "M 474 1", "X", "X"]
    toleree = recensements.analyser([ENTETE] + bonnes + [ambigue] * 2)  # 2 sur 402 : sous le seuil de 0,5 %
    assert toleree["volumes"] == 400 and [r["ligne"] for r in toleree["lignes_rejetees"]] == [402, 403]
    assert (toleree["en_ligne"], toleree["salle_de_lecture"]) == (400, 0)
    with pytest.raises(recensements.EtatCollectionError, match="3 lignes inexploitables sur 403"):
        recensements.analyser([ENTETE] + bonnes + [ambigue] * 3)
    with pytest.raises(recensements.EtatCollectionError, match="millésime illisible"):
        recensements.analyser([ENTETE] + bonnes + [["SOMAIN", "?", f"E DEPOT {i}", "X", ""] for i in range(5)])
    with pytest.raises(recensements.EtatCollectionError, match="Aucune ligne"):
        recensements.analyser([ENTETE])
    # sans l'en-tête attendu, ou colonnes d'accès permutées : rien ne dit où est « Mis en ligne »
    with pytest.raises(recensements.EtatCollectionError, match="En-tête"):
        recensements.analyser(bonnes)
    with pytest.raises(recensements.EtatCollectionError, match="En-tête"):
        recensements.analyser([["COMMUNE", "ANNEE", "COTE", "Salle de lecture", "Mis en ligne"]] + bonnes)
    doublon = recensements.analyser([ENTETE, bonnes[0], bonnes[0], ENTETE, bonnes[1]])  # en-tête répété ignoré
    assert (doublon["lignes"], doublon["volumes"], doublon["doublons"]) == (3, 2, 1)


def test_croix_recoupees_avec_leur_position(script, monkeypatch):
    """Un tableau dont la croix glisse d'une colonne (cellules décalées) ne correspond plus aux positions lues."""
    import pdfplumber
    origine = pdfplumber.page.Page.extract_tables

    def decalees(page, *args, **kwargs):
        tableaux = origine(page, *args, **kwargs)
        for tableau in tableaux:
            for ligne in tableau:
                if ligne[4] == "X":
                    ligne[3], ligne[4] = "X", ""
                    return tableaux
        return tableaux
    monkeypatch.setattr(pdfplumber.page.Page, "extract_tables", decalees)
    with pytest.raises(recensements.EtatCollectionError, match="Page 1 : .* colonne d'accès ambiguë"):
        script["lignes_du_pdf"](PDF)
    monkeypatch.setattr(pdfplumber.page.Page, "extract_tables", lambda *_a, **_k: [])
    with pytest.raises(recensements.EtatCollectionError, match="Page 1 sans tableau"):
        script["lignes_du_pdf"](PDF)


def test_script_ecrit_un_json_stable_sans_reseau(script, extrait, tmp_path, capsys):
    sortie = tmp_path / "ad59_recensements.json"
    assert script["main"]([str(PDF), "--releve", "2026-11-27", "--sortie", str(sortie)]) == 0
    assert json.loads(sortie.read_text(encoding="utf-8")) == extrait
    assert sortie.read_text(encoding="utf-8") == recensements.serialiser(extrait)
    assert script["main"]([str(PDF), "--releve", "2026-11-27", "--sortie", str(sortie), "--check"]) == 0
    assert script["main"]([str(PDF), "--releve", "2026-11-28", "--sortie", str(sortie), "--check"]) == 1
    assert "310 lignes" in capsys.readouterr().out


def test_telechargement_refuse_hors_de_l_hote_officiel(script, tmp_path):
    with pytest.raises(SystemExit, match="Source refusée"):
        script["telecharger"]("https://exemple.invalid/media/etat.pdf", tmp_path / "x.pdf")
    with pytest.raises(SystemExit, match="Source refusée"):
        script["telecharger"](recensements.DOCUMENT.replace("https://", "http://"), tmp_path / "x.pdf")
    with pytest.raises(SystemExit, match="existe déjà"):
        script["telecharger"](recensements.DOCUMENT, PDF)


# ---------------------------------------------------------------------------- référentiel livré

def test_referentiel_livre_coherent_avec_l_extrait(extrait):
    ref = recensements.referentiel()
    assert ref["service"] == "AD59" and ref["source"] == recensements.SOURCE
    assert re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", ref["releve_le"])
    assert ref["lignes"] == ref["volumes"] + ref["doublons"] + len(ref["lignes_rejetees"])
    assert ref["volumes"] == sum(len(v) for v in ref["communes"].values()) > 3_000
    assert ref["volumes"] == ref["en_ligne"] + ref["salle_de_lecture"]
    assert len(ref["lignes_rejetees"]) <= recensements.SEUIL_REJETS * ref["lignes"]
    assert recensements.PATH.read_text(encoding="utf-8") == recensements.serialiser(ref)
    for commune, volumes in extrait["communes"].items():  # l'extrait de test est bien une partie du référentiel
        assert all(v in ref["communes"][commune] for v in volumes), commune


# ---------------------------------------------------------------------------- recherche locale

def test_somain_cote_et_mode_d_acces():
    r = recensements.chercher("Somain", 1906)
    assert r["statut"] == "connu" and r["communes"] == ["SOMAIN"] and r["periode"] == [1906, 1906]
    assert [(v["cote"], v["acces"], v["message"]) for v in r["volumes"]] == [
        ("M 474 572", "en_ligne", "en ligne selon l'état de la collection")]
    assert r["millesimes_connus"] == {"en_ligne": [1901, 1906, 1931, 1946], "salle_de_lecture": [1954]}
    salle = recensements.chercher("SOMAIN", 1954)
    assert [(v["cote"], v["acces"]) for v in salle["volumes"]] == [("M 474 8 19 SOMAIN", "salle_de_lecture")]
    assert "salle de lecture seulement" in salle["volumes"][0]["message"] and "75 ans" in salle["volumes"][0]["message"]
    assert "dont 1 en salle de lecture seulement, pas en ligne (M 474 8 19 SOMAIN)" in salle["message"]
    assert [v["debut"] for v in recensements.chercher("somain", 1900, 1950)["volumes"]] == [1901, 1906, 1931, 1946]


def test_millesime_absent_inconnu_du_referentiel_jamais_inexistant():
    r = recensements.chercher("Somain", 1911)
    assert r["statut"] == "inconnu_du_referentiel" and r["volumes"] == [] and r["commune_connue"] is True
    assert "millésimes connus pour la commune : 1901, 1906, 1931, 1946 (en ligne) ; 1954 (salle de lecture)" \
        in r["message"]
    fictive = recensements.chercher("Commune-Fictive", 1906)
    assert fictive["commune_connue"] is False and "commune absente du référentiel sous ce nom" in fictive["message"]
    for constat in (r, fictive):
        assert "inconnu du référentiel" in constat["message"] and "inexistant" not in constat["message"]
        assert "ne prouve pas que le recensement n'existe pas" in constat["message"]
        assert "75 ans" in constat["limite"]
        # Socface : lien guidé et consigne manuelle, sans automatisation
        assert constat["recherche_nominative"]["recherche"] == "https://francearchives.gouv.fr/fr/basedenoms"
        assert "aucune interrogation automatique" in constat["recherche_nominative"]["consigne"]


@pytest.mark.parametrize("commune, libelles", [
    ("Le Cateau-Cambrésis", ["LE CATEAU CAMBRESIS"]),
    ("Saint-Vaast-en-Cambrésis", ["SAINT VAAST EN CAMBRESIS"]),
    ("St André", ["SAINT ANDRE"]),
    ("Condé-sur-l'Escaut", ["CONDE SUR L'ESCAUT"]),
    ("La Chapelle-d'Armentières", ["LA CHAPELLE D'ARMENTIERES", "CHAPELLE D'ARMENTIERES"]),
    ("Bourbourg", ["BOURBOURG", "BOURBOURG Campagne"]),
    ("Marchiennes", ["MARCHIENNES-Campagne", "MARCHIENNES-Ville"]),
    ("Croix", ["CROIX (Lille)", "CROIX (Lille) (1)", "CROIX (Lille) (2)", "CROIX (Lille) (Tome1)",
               "CROIX (Lille) (Tome2)"]),  # « CROIX CALUYAU (Avesnes) » est une autre commune
])
def test_commune_tolerante_et_libelles_de_quartier(commune, libelles):
    assert list(recensements.libelles(commune)) == libelles


def test_lille_ses_cantons_et_libelles_rendus():
    r = recensements.chercher("Lille", 1936)
    assert len(r["volumes"]) == 9 and {v["commune"] for v in r["volumes"]} >= {"LILLE EST", "LILLE SUD EXTRA MUROS"}
    assert "Lille : non versé" in recensements.libelles("Lille")
    assert recensements.libelles("Neuville") == ("LA NEUVILLE",)  # article facultatif, pas « NEUVILLE EN FERRAIN »
    assert recensements.libelles("Saint") == () and recensements.libelles("") == ()


def test_recensements_proches_d_une_annee():
    proches = recensements.pour_fait(1908, "Somain")
    assert [(v["debut"], v["cote"], v["position"]) for v in proches] == [
        (1906, "M 474 572", "avant"), (1931, "M 474 5 19 SOMAIN", "apres")]
    assert [(v["debut"], v["position"]) for v in recensements.pour_fait(1906, "Somain")] == [
        (1901, "avant"), (1906, "annee"), (1931, "apres")]
    assert [(v["debut"], v["position"]) for v in recensements.pour_fait(1908, "Somain", avant=False)] == [
        (1931, "apres")]
    assert recensements.pour_fait(None, "Somain") == [] and recensements.pour_fait(1906, "Commune-Fictive") == []


# ---------------------------------------------------------------------------- archives_registres (AD59, REC)

@respx.mock
def test_archives_registres_rec_somain_1906(app, fixtures):
    route = respx.get(URL).respond(200, text=(fixtures / "ad59-recensements-positive.html").read_text())
    res = server.archives_registres("AD59", "Somain", 1906, "REC")
    assert route.call_count == 1 and "erreur" not in res, res
    assert dict(route.calls[0].request.url.params) == {
        "formUuid": registres.FORMULAIRE_REC, "sort": "date_asc", "mode": "list", "facet_media": "image",
        "0-controlledAccessGeographicName[]": "SOMAIN", "page": "1"}  # ni date ni typologie envoyées
    assert res["resultats"] == [{
        "titre": "SOMAIN", "cote": "M 474 / 572", "ark": "ark:/33518/h2tprnqlw3dj",
        "url": "https://archivesdepartementales.lenord.fr/ark:/33518/h2tprnqlw3dj", "bornes": [1906, 1906],
        "nb_vues": 225, "couvre_periode": True}]
    assert res["total"] == 4 and res["registres_hors_periode"] == 3 and res["fin"] is True
    assert res["periode"] == [1906, 1906] and res["requete"]["type_acte"] == "REC"
    # tout est en ligne pour ce millésime : aucun constat ajouté, pas de négatif
    assert "couverture_recensements" not in res and "recherche_negative" not in res and "classeur_3e" not in res
    assert len(app.journal.entries(statut="positif")) == 1


@respx.mock
def test_rec_intervalle_et_cotes_telles_qu_affichees(app, fixtures):
    respx.get(URL).respond(200, text=(fixtures / "ad59-recensements-positive.html").read_text())
    res = registres.rechercher(app.sctx, "AD59", "SOMAIN", 1900, "rec", annee_fin=1940)
    assert [(r["cote"], r["bornes"], r["nb_vues"]) for r in res["resultats"]] == [
        ("M473 063 / 10 SOMAIN", [1901, 1901], 5), ("M 474 / 572", [1906, 1906], 225),
        ("M474 5 / 19 SOMAIN", [1931, 1931], 197)]
    assert res["registres_hors_periode"] == 1 and "couverture_recensements" not in res


@respx.mock
def test_rec_millesime_absent_negatif_non_concluant(app, fixtures):
    respx.get(URL).respond(200, text=(fixtures / "ad59-recensements-positive.html").read_text())
    res = server.archives_registres("AD59", "Somain", 1911, "REC")
    assert res["resultats"] == [] and res["total"] == 4 and res["registres_hors_periode"] == 4
    assert res["recherche_negative"].startswith("Aucun recensement en ligne de cette page ne couvre 1911-1911")
    assert "ne prouve pas que le recensement n'existe pas" in res["recherche_negative"]
    c = res["couverture_recensements"]
    assert c["statut"] == "inconnu_du_referentiel" and c["volumes"] == [] and c["commune_connue"] is True
    assert c["millesimes_connus"]["en_ligne"] == [1901, 1906, 1931, 1946]
    assert c["releve_le"] == recensements.referentiel()["releve_le"] and c["source"] == recensements.SOURCE
    assert len(app.journal.entries(statut="negatif")) == 1


@respx.mock
def test_rec_recensement_en_salle_de_lecture_seulement(app, fixtures):
    respx.get(URL).respond(200, text=(fixtures / "ad59-recensements-positive.html").read_text())
    res = server.archives_registres("AD59", "Somain", 1954, "REC")
    assert res["resultats"] == [] and "recherche_negative" in res
    c = res["couverture_recensements"]
    assert c["statut"] == "connu" and [(v["cote"], v["acces"]) for v in c["volumes"]] == [
        ("M 474 8 19 SOMAIN", "salle_de_lecture")]
    assert "Pas en ligne ne veut pas dire inexistant" in c["message"]
    # intervalle : résultats en ligne et constat sur le seul volume hors ligne, les autres reconnus par leur cote
    mixte = registres.rechercher(app.sctx, "AD59", "Somain", 1940, "REC", annee_fin=1960)
    assert [r["cote"] for r in mixte["resultats"]] == ["M474 7 / 25 SOMAIN"] and "recherche_negative" not in mixte
    assert {v["cote"]: v["message"].split(" ; ")[0] for v in mixte["couverture_recensements"]["volumes"]} == {
        "M 474 7 25 SOMAIN": "en ligne selon l'état de la collection et présent dans la recherche",
        "M 474 8 19 SOMAIN": "pas en ligne : consultation en salle de lecture seulement selon l'état de la "
                             "collection, sous réserve de communicabilité (75 ans)"}


@respx.mock
def test_rec_reponse_negative_du_service(app, fixtures):
    respx.get(URL).respond(200, text=(fixtures / "ad59-recherche-negative.html").read_text())  # même page que REC
    res = server.archives_registres("AD59", "Somain", 1906, "REC")
    assert res["resultats"] == [] and res["total"] == 0
    assert res["recherche_negative"].startswith("Aucun registre renvoyé pour cette recherche")
    c = res["couverture_recensements"]
    assert [(v["cote"], v["message"]) for v in c["volumes"]] == [
        ("M 474 572", "en ligne selon l'état de la collection mais absent de la recherche")]
    assert "absent(s) de la recherche" in c["message"]
    inconnue = registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1906, "REC")["couverture_recensements"]
    assert inconnue["commune_connue"] is False and inconnue["statut"] == "inconnu_du_referentiel"


@respx.mock
def test_rec_page_2(app, fixtures):
    route = respx.get(URL).respond(200, text=(fixtures / "ad59-recensements-page2.html").read_text())
    res = server.archives_registres("AD59", "Buysscheure", 1936, "REC", page=2)
    assert route.calls[0].request.url.params["page"] == "2" and "erreur" not in res, res
    assert res["total"] == 26 and res["page"] == 2 and res["page_suivante"] is None and res["fin"] is True
    assert [(r["cote"], r["ark"]) for r in res["resultats"]] == [
        ("M474 6 / 05 BUYSSCHEURE", "ark:/33518/jrfmgcv36bwl"), ("E DEPOT / 190 1936", "ark:/33518/2kq5v4dl1ctp")]
    assert res["registres_hors_periode"] == 4 and "couverture_recensements" not in res
    # la page 1 demandée alors que le service rend la page 2 : erreur, jamais un négatif
    assert "erreur" in server.archives_registres("AD59", "Buysscheure", 1936, "REC")


@respx.mock
def test_rec_referentiel_illisible_ne_casse_pas_la_recherche(app, fixtures, monkeypatch):
    def illisible(*_a, **_k):
        raise OSError("référentiel absent")
    monkeypatch.setattr(recensements, "pour_recherche", illisible)
    respx.get(URL).respond(200, text=(fixtures / "ad59-recensements-positive.html").read_text())
    res = registres.rechercher(app.sctx, "AD59", "Somain", 1954, "REC")
    assert "erreur" not in res and "couverture_recensements" not in res and "recherche_negative" in res


@respx.mock(assert_all_called=False)
def test_rec_refuse_pour_un_autre_service(app, respx_mock):
    route = respx_mock.route().respond(200, text="aucune requête attendue")
    # #392 : REC ouvert aux services Mnesys qui déclarent un formulaire de recensements (AD58 compris) ; un
    # service sans ce formulaire (AD972, relevé du 28 novembre 2026) reste refusé, sans requête
    res = server.archives_registres("AD972", "Fort-de-France", 1906, "REC")
    assert "Aucun formulaire « recensements »" in res["erreur"]
    assert "AD972" in res["erreur"] and not route.called
    inconnu = server.archives_registres("AD59", "Somain", 1906, "XYZ")
    assert "REC (recensements de population) pour AD59 et les services Mnesys qui le déclarent" in inconnu[
        "erreur"] and not route.called
    assert "REC" in server.archives_registres.__doc__ and "couverture_recensements" in server.archives_registres.__doc__


@respx.mock
def test_autres_types_ad59_sans_constat_de_recensement(app, fixtures):
    respx.get(URL).respond(200, text=(fixtures / "ad59-recherche-negative.html").read_text())
    for type_acte in ("", "N", "TD"):
        assert "couverture_recensements" not in registres.rechercher(app.sctx, "AD59", "Somain", 1954, type_acte)


# ---------------------------------------------------------------------------- prochaine_source, cotes_a_consulter

def test_cotes_a_consulter_cite_la_cote_de_recensement_dans_le_nord(app):
    pistes = server.cotes_a_consulter("CENS", "1906", "Somain (59)")["sources"]
    assert pistes[0]["source"] == "Listes nominatives de recensement"
    assert [(v["cote"], v["acces"], v["position"]) for v in pistes[0]["couverture_recensements"]] == [
        ("M 473 063 10 SOMAIN", "en_ligne", "avant"), ("M 474 572", "en_ligne", "annee"),
        ("M 474 5 19 SOMAIN", "en_ligne", "apres")]
    assert all("couverture_recensements" not in p for p in pistes[1:])
    sans = next_source_hint("CENS", "1906", "")
    assert [p["cote_typique"] for p in pistes] == [p["cote_typique"] for p in sans]  # pistes et cotes inchangées
    # résidence entre deux recensements : celui d'avant et celui d'après ; naissance : après seulement
    resi = next(p for p in next_source_hint("RESI", "1950", "Somain (59)") if "couverture_recensements" in p)
    assert [(v["debut"], v["acces"], v["position"]) for v in resi["couverture_recensements"]] == [
        (1946, "en_ligne", "avant"), (1954, "salle_de_lecture", "apres")]
    naissance = next(p for p in server.prochaine_source("BIRT", "1903", "Somain (59)")
                     if p["source"] == "Listes nominatives de recensement")
    assert [(v["debut"], v["position"]) for v in naissance["couverture_recensements"]] == [(1906, "apres")]


def test_cotes_de_recensement_reservees_au_nord_et_au_referentiel(app):
    for lieu, date in (("Somain", "1906"), ("Arras (62)", "1906"), ("Somain (59)", ""),
                       ("Commune-Fictive (59)", "1906")):
        assert all("couverture_recensements" not in p for p in next_source_hint("CENS", date, lieu)), (lieu, date)
    assert all("couverture_recensements" not in p for p in next_source_hint("MARR", "1906", "Somain (59)"))
