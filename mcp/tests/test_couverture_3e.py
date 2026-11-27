"""Classeur 3 E des AD59 (#374) : analyse du PDF, référentiel, recherche locale et ajout à archives_registres.

``fixtures/ad59-classeur-3e-extrait.pdf`` : pages 1, 4, 11, 74 et 166 du PDF public « classeur-3e-janvier-2026 »
(relevé du 27 novembre 2026), sans modification ; aucune personne n'y figure. Aucun accès réseau.
"""

import hashlib
import json
import re
import runpy
from pathlib import Path

import pytest
import respx

from genealogiste_mcp import couverture_3e, server
from genealogiste_mcp.fr_sources import next_source_hint
from genealogiste_mcp.sources import registres

ROOT = Path(__file__).resolve().parents[2]
PDF = Path(__file__).parent / "fixtures" / "ad59-classeur-3e-extrait.pdf"
URL = "https://archivesdepartementales.lenord.fr/search/results"


@pytest.fixture(scope="module")
def script():
    return runpy.run_path(str(ROOT / "scripts/generer_couverture_3e_ad59.py"))


@pytest.fixture(scope="module")
def extrait(script):
    return script["generer"](PDF, "2026-11-27")


def _volume(ref: dict, commune: str, cote: str) -> dict:
    return next(v for v in ref["communes"][commune] if v["cote"] == cote)


# ---------------------------------------------------------------------------- analyse du PDF

def test_extrait_reel_du_pdf(extrait):
    assert extrait["lignes"] == 454 and extrait["lignes_rejetees"] == []  # 5 pages de 91 lignes, un en-tête
    assert extrait["volumes"] + extrait["doublons"] == extrait["lignes"]
    assert extrait["sha256"] == hashlib.sha256(PDF.read_bytes()).hexdigest()
    assert extrait["source"] == couverture_3e.SOURCE and extrait["releve_le"] == "2026-11-27"
    assert _volume(extrait, "ABSCON", "3 E 4142") == {
        "cote": "3 E 4142", "types": "N", "debut": 1921, "fin": 1933, "en_ligne": False, "mise_en_ligne_prevue": 2034}
    assert _volume(extrait, "ABANCOURT", "3 E 6330") == {
        "cote": "3 E 6330", "types": "NMD", "debut": 1893, "fin": 1902, "en_ligne": True, "mise_en_ligne_prevue": None}
    assert _volume(extrait, "SOMAIN", "3 E 6298")["mise_en_ligne_prevue"] == 2031
    # communes à plusieurs mots, avec trait d'union ou espace, telles que le classeur les écrit
    assert {"ALLENNES-LES-MARAIS", "ARMBOUTS CAPPEL", "ARMBOUTS-CAPPEL"} <= set(extrait["communes"])


def test_cote_a_espaces_et_cellule_tronquee(extrait):
    assert _volume(extrait, "ANNOEULLIN", "3 E ANNOEULLIN 02/02")["types"] == "BMS"
    tronquee = _volume(extrait, "BAISIEUX", "J 1694")  # cellule coupée par le PDF : parenthèse jamais fermée
    assert tronquee["types"].startswith("B (sauf 1732") and not tronquee["types"].endswith(")")
    assert (tronquee["debut"], tronquee["fin"]) == (1613, 1786)
    assert couverture_3e.actes(tronquee["types"]) == {"B"}


def test_borne_illisible_gardee_sans_etre_devinee(extrait):
    v = _volume(extrait, "GRAVELINES", "3 E GRAVELINES 24")
    assert (v["debut"], v["fin"], v["dates"]) == (1882, None, "1882 / 182")
    assert extrait["bornes_incompletes"] == 1


@pytest.mark.parametrize("cellules, attendu", [
    (["ALLENNES LES\nMARAIS", "3 E\n14356", "NMD", "1922 / 1932", ">", "2033"],  # ligne coupée en deux
     ("ALLENNES LES MARAIS", "3 E 14356", 1922, 1932, False, 2033, None)),
    (["ABSCON", "3 E 4142", "N", "1921 /", "> 2034"],  # date de fin absente, statut dans une seule cellule
     ("ABSCON", "3 E 4142", 1921, None, False, 2034, "1921 /")),
    (["Solre-le-Château", "3 E 1", "N M D", "1938-07-15 / /1938-12-31", "Mis en ligne", ""],
     ("SOLRE-LE-CHATEAU", "3 E 1", 1938, 1938, True, None, "1938-07-15 / /1938-12-31")),
    (["DENAIN", "3 E 20885", "D", "30/12/1944 / 1945", "Mis en ligne", None],
     ("DENAIN", "3 E 20885", 1944, 1945, True, None, "30/12/1944 / 1945")),
    (["ROUBAIX", "3 E 21283", "N", "17167 / 17295", ">", "2048"],  # numéros de série de tableur : non interprétés
     ("ROUBAIX", "3 E 21283", None, None, False, 2048, "17167 / 17295")),
    (["LIGNY", "3 E 7066", "NMD", "1919 / 1914", "Mis en ligne", ""],  # fin antérieure au début : écartée
     ("LIGNY", "3 E 7066", 1919, None, True, None, "1919 / 1914")),
])
def test_lignes_irregulieres(cellules, attendu):
    commune, v, complet = couverture_3e.analyser_ligne(cellules)
    assert (commune, v["cote"], v["debut"], v["fin"], v["en_ligne"], v["mise_en_ligne_prevue"],
            v.get("dates")) == attendu
    assert complet is (v["debut"] is not None and v["fin"] is not None)


def test_entete_et_ligne_vide_ignorees():
    assert couverture_3e.analyser_ligne(["COMMUNE", "COTE", "TYPES d'ACTES", "DATE", "Mis en ligne", ""]) is None
    assert couverture_3e.analyser_ligne(["", None, "", "", "", ""]) is None


@pytest.mark.parametrize("cellules", [
    ["SOMAIN", "3 E 6298", "N", "1926 / 1930", "Bientôt", ""],
    ["SOMAIN", "3 E 6298", "N", "1926 / 1930", ">", "31"],
    ["SOMAIN", "", "N", "1926 / 1930", "Mis en ligne", ""],
    ["SOMAIN 3 E 6298 N 1926 / 1930 > 2031"],
])
def test_ligne_inexploitable_rejetee(cellules):
    with pytest.raises(couverture_3e.ClasseurError):
        couverture_3e.analyser_ligne(cellules)


def test_refus_au_dela_du_seuil_d_erreurs():
    bonne = ["SOMAIN", "3 E {}", "N", "1926 / 1930", ">", "2031"]
    bonnes = [[c.format(i) for c in bonne] for i in range(400)]
    mauvaise = ["SOMAIN", "3 E 1", "N", "1926 / 1930", "statut inconnu", ""]
    toleree = couverture_3e.analyser(bonnes + [mauvaise] * 2)  # 2 sur 402 : sous le seuil de 0,5 %
    assert toleree["volumes"] == 400 and [r["ligne"] for r in toleree["lignes_rejetees"]] == [401, 402]
    with pytest.raises(couverture_3e.ClasseurError, match="3 lignes inexploitables sur 403"):
        couverture_3e.analyser(bonnes + [mauvaise] * 3)
    with pytest.raises(couverture_3e.ClasseurError, match="bornes illisibles"):
        couverture_3e.analyser(bonnes + [["SOMAIN", f"3 E 9{i}", "N", "? / ?", ">", "2031"] for i in range(5)])
    with pytest.raises(couverture_3e.ClasseurError, match="Aucune ligne"):
        couverture_3e.analyser([["COMMUNE", "COTE", "TYPES", "DATES", "Mis en ligne", ""]])


def test_script_ecrit_un_json_stable_sans_reseau(script, extrait, tmp_path, capsys):
    sortie = tmp_path / "ad59_3e.json"
    assert script["main"]([str(PDF), "--releve", "2026-11-27", "--sortie", str(sortie)]) == 0
    assert json.loads(sortie.read_text(encoding="utf-8")) == extrait
    assert sortie.read_text(encoding="utf-8") == couverture_3e.serialiser(extrait)
    assert script["main"]([str(PDF), "--releve", "2026-11-27", "--sortie", str(sortie), "--check"]) == 0
    assert script["main"]([str(PDF), "--releve", "2026-11-28", "--sortie", str(sortie), "--check"]) == 1
    assert "454 lignes" in capsys.readouterr().out


def test_telechargement_refuse_hors_de_l_hote_officiel(script, tmp_path):
    with pytest.raises(SystemExit, match="Source refusée"):
        script["telecharger"]("https://exemple.invalid/document/classeur.pdf", tmp_path / "x.pdf")
    with pytest.raises(SystemExit, match="existe déjà"):
        script["telecharger"](couverture_3e.SOURCE, PDF)


# ---------------------------------------------------------------------------- référentiel livré

def test_referentiel_livre_coherent_avec_l_extrait(extrait):
    ref = couverture_3e.referentiel()
    assert ref["service"] == "AD59" and ref["source"] == couverture_3e.SOURCE
    assert re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", ref["releve_le"])
    assert ref["lignes"] == ref["volumes"] + ref["doublons"] + len(ref["lignes_rejetees"])
    assert ref["volumes"] == sum(len(v) for v in ref["communes"].values()) > 10_000
    assert len(ref["lignes_rejetees"]) <= couverture_3e.SEUIL_REJETS * ref["lignes"]
    assert couverture_3e.PATH.read_text(encoding="utf-8") == couverture_3e.serialiser(ref)
    for commune, volumes in extrait["communes"].items():  # l'extrait de test est bien une partie du référentiel
        assert commune == couverture_3e.cle_commune(commune)
        assert all(v in ref["communes"][commune] for v in volumes), commune


# ---------------------------------------------------------------------------- recherche locale

def test_somain_1926_cote_et_statut():
    r = couverture_3e.chercher("Somain", 1926, 0, "N")
    assert r["statut"] == "connu" and r["communes"] == ["SOMAIN"] and r["periode"] == [1926, 1926]
    assert [(v["cote"], v["types"], v["debut"], v["fin"], v["en_ligne"], v["mise_en_ligne_prevue"], v["statut"])
            for v in r["volumes"]] == [("3 E 6298", "N", 1926, 1930, False, 2031, "mise_en_ligne_prevue")]
    assert r["volumes"][0]["message"] == "pas en ligne avant 2031 ; consultation en salle de lecture"
    assert [v["cote"] for v in couverture_3e.chercher("SOMAIN", 1926, 0, "M")["volumes"]] == ["3 E 6301"]
    toutes = couverture_3e.chercher("somain", 1926)["volumes"]
    assert {v["cote"] for v in toutes} == {"3 E 6298", "3 E 6301", "3 E 6304"}
    assert next(v for v in toutes if v["cote"] == "3 E 6301")["message"] == "en ligne selon le classeur"


@pytest.mark.parametrize("commune, libelles", [
    ("Allennes les Marais", ["ALLENNES-LES-MARAIS"]),
    ("ALLENNES-LES-MARAIS", ["ALLENNES-LES-MARAIS"]),
    ("Armbouts-Cappel", ["ARMBOUTS CAPPEL", "ARMBOUTS-CAPPEL"]),
    ("La Bassée", ["BASSEE (LA)"]),
    ("Le Cateau-Cambrésis", ["CATEAU-CAMBRESIS (LE)"]),
    ("Solre-le-Château", ["SOLRE-LE-CHATEAU"]),
    ("St-Waast-la-Vallée", ["SAINT-WAAST (-LA-VALLEE)"]),
    ("Bruay-sur-l'Escaut", ["BRUAY-SUR-L'ESCAUT"]),
])
def test_commune_tolerante_aux_tirets_espaces_et_accents(commune, libelles):
    r = couverture_3e.chercher(commune, 1900, 1948)
    assert r["communes"] == libelles and r["commune_connue"] and r["volumes"]


def test_intervalle_et_borne_illisible_a_verifier():
    r = couverture_3e.chercher("Somain", 1921, 1930, "N")
    assert [v["cote"] for v in r["volumes"]] == ["3 E 6297", "3 E 6298"]
    assert "dont 1 pas encore en ligne (3 E 6298 : pas en ligne avant 2031" in r["message"]
    g = couverture_3e.chercher("Gravelines", 1890, 0, "N")["volumes"]
    assert [(v["cote"], v["recoupe_periode"]) for v in g if v["recoupe_periode"] is None] == [
        ("3 E GRAVELINES 24", None)]


def test_hors_couverture_inconnu_du_classeur_jamais_inexistant():
    for commune, connue in (("Somain", True), ("Commune-Fictive", False)):
        r = couverture_3e.chercher(commune, 1650)
        assert r["statut"] == "inconnu_du_classeur" and r["volumes"] == [] and r["commune_connue"] is connue
        assert "inconnu du classeur" in r["message"] and "ne prouve pas que le registre n'existe pas" in r["message"]
        assert "inexistant" not in r["message"]
    assert "commune absente du classeur" in couverture_3e.chercher("Commune-Fictive", 1650)["message"]


def test_lettres_d_actes():
    assert couverture_3e.actes("N(an7) M(an9) D(an7)") == set("NMD")
    assert couverture_3e.actes("NMD + TD") == set("NMD") and couverture_3e.actes("N M D") == set("NMD")
    assert couverture_3e.actes("MD (sauf D1914)") == set("MD") and couverture_3e.actes("BMS") == set("BMS")
    assert couverture_3e.actes("PM") == set() and couverture_3e.actes("T") == set()


# ---------------------------------------------------------------------------- archives_registres (AD59)

@respx.mock
def test_archives_registres_somain_1926_absent_en_ligne_mais_connu(app, fixtures):
    route = respx.get(URL).respond(200, text=(fixtures / "ad59-recherche-negative.html").read_text())
    res = server.archives_registres("AD59", "Somain", 1926, "N")
    assert route.call_count == 1 and "erreur" not in res, res
    # comportement et clés d'avant #374 inchangés
    assert res["resultats"] == [] and res["total"] == 0 and res["service"] == "AD59" and res["fin"] is True
    assert res["recherche_negative"].startswith("Aucun registre renvoyé pour cette recherche")
    c = res["classeur_3e"]
    assert c["statut"] == "connu" and c["releve_le"] == couverture_3e.referentiel()["releve_le"]
    assert [(v["cote"], v["message"]) for v in c["volumes"]] == [
        ("3 E 6298", "pas en ligne avant 2031 ; consultation en salle de lecture")]
    assert "Absent en ligne ne veut pas dire inexistant" in c["message"]
    assert len(app.journal.entries(statut="negatif")) == 1
    assert "SOMAIN" in str(route.calls[0].request.url) and "6298" not in str(route.calls[0].request.url)


@respx.mock
def test_archives_registres_vide_alors_que_le_classeur_dit_en_ligne(app, fixtures):
    respx.get(URL).respond(200, text=(fixtures / "ad59-recherche-negative.html").read_text())
    c = registres.rechercher(app.sctx, "AD59", "Somain", 1925, "N")["classeur_3e"]
    assert [(v["cote"], v["message"]) for v in c["volumes"]] == [
        ("3 E 6297", "en ligne selon le classeur mais absent de la recherche")]
    assert "absent(s) de la recherche" in c["message"]


@respx.mock
def test_archives_registres_vide_et_inconnu_du_classeur(app, fixtures):
    respx.get(URL).respond(200, text=(fixtures / "ad59-recherche-negative.html").read_text())
    c = registres.rechercher(app.sctx, "AD59", "Somain", 1650)["classeur_3e"]
    assert c["statut"] == "inconnu_du_classeur" and c["volumes"] == []
    assert "ne prouve pas que le registre n'existe pas" in c["message"]


@respx.mock
def test_archives_registres_positif_signale_le_volume_hors_ligne(app, fixtures):
    respx.get(URL).respond(200, text=(fixtures / "ad59-recherche-positive.html").read_text())
    res = registres.rechercher(app.sctx, "AD59", "Somain", 1921, "N", annee_fin=1930)
    assert len(res["resultats"]) == 1 and "recherche_negative" not in res
    messages = {v["cote"]: v["message"] for v in res["classeur_3e"]["volumes"]}
    assert messages["3 E 6298"] == "pas en ligne avant 2031 ; consultation en salle de lecture"
    assert messages["3 E 6297"].startswith("en ligne selon le classeur ; cote non reconnue")


@respx.mock
def test_archives_registres_positif_sans_volume_hors_ligne_inchange(app, fixtures):
    respx.get(URL).respond(200, text=(fixtures / "ad59-recherche-positive.html").read_text())
    assert "classeur_3e" not in registres.rechercher(app.sctx, "AD59", "Commune-Fictive", 1860)
    assert "classeur_3e" not in registres.rechercher(app.sctx, "AD59", "Somain", 1925, "N")


@respx.mock
def test_tables_decennales_sans_classeur(app, fixtures):
    respx.get(URL).respond(200, text=(fixtures / "ad59-recherche-negative.html").read_text())
    assert "classeur_3e" not in registres.rechercher(app.sctx, "AD59", "Somain", 1926, "TD")


@respx.mock
def test_referentiel_illisible_ne_casse_pas_la_recherche(app, fixtures, monkeypatch):
    def illisible(*_a, **_k):
        raise OSError("référentiel absent")
    monkeypatch.setattr(couverture_3e, "pour_recherche", illisible)
    respx.get(URL).respond(200, text=(fixtures / "ad59-recherche-negative.html").read_text())
    res = registres.rechercher(app.sctx, "AD59", "Somain", 1926, "N")
    assert "erreur" not in res and "classeur_3e" not in res and "recherche_negative" in res


# ---------------------------------------------------------------------------- prochaine_source

def test_prochaine_source_cite_la_cote_3e_dans_le_nord(app):
    pistes = server.prochaine_source("BIRT", "1926", "Somain (59)")
    assert pistes[0]["source"] == "Acte de naissance de Somain (59)"
    assert [(v["cote"], v["mise_en_ligne_prevue"]) for v in pistes[0]["classeur_3e"]] == [("3 E 6298", 2031)]
    assert all("classeur_3e" not in p for p in pistes[1:])
    sans = next_source_hint("BIRT", "1926", "")
    assert [p["cote_typique"] for p in pistes] == [p["cote_typique"] for p in sans]  # pistes et cotes inchangées
    # ajout réservé au Nord, à une année et à une commune connues du classeur
    for lieu, date in (("Somain", "1926"), ("Arras (62)", "1926"), ("Somain (59)", ""), ("Somain (59)", "1650")):
        assert all("classeur_3e" not in p for p in next_source_hint("BIRT", date, lieu)), (lieu, date)
    assert "classeur_3e" in server.cotes_a_consulter("DEAT", "1926", "Somain (59)")["sources"][0]
