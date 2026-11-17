"""Accès spécifiques : priorité, provenance, absence et repli sans qualification implicite."""
from copy import deepcopy

import pytest

from genealogiste_mcp import archives
from genealogiste_mcp.acces_archives import selectionner, valider


def service():
    return {"code": "AD59", "nom": "Fictif", "type": "autre", "site": "https://archives.example",
            "resolution_image": {"type": "visualizer_api"},
            "visionneuse_acces": {"famille": "editeur_ad", "iiif": False, "editeur": "naoned",
                                   "par_type": {"matricule": {"famille": "iiif_natif", "iiif": True,
                                   "reference": "https://archives.example/matricules", "releve_le": "2026-11-17"}}}}


def test_priorite_alias_et_repli_sans_fusion():
    s = service()
    avant = deepcopy(s)
    specifique = selectionner(s, "matricules")
    assert specifique["origine"] == "document" and specifique["document"] == "matricule"
    assert specifique["acces"]["iiif"] is True and "editeur" not in specifique["acces"]
    assert selectionner(s, "naissance")["origine"] == "service"
    assert selectionner(s)["acces"]["editeur"] == "naoned"
    assert s == avant and valider(s["visionneuse_acces"]) == []


def test_forme_specifique_seule():
    s = service()
    s["visionneuse_acces"] = {"par_type": s["visionneuse_acces"]["par_type"]}
    assert valider(s["visionneuse_acces"]) == []
    assert selectionner(s, "matricule")["origine"] == "document"
    assert selectionner(s, "naissance")["origine"] == "inconnu"
    assert selectionner(s)["acces"] is None


@pytest.mark.parametrize("invalide", [None, [], "iiif", {}, {"famille": "inconnue"},
    {"famille": "iiif_natif", "iiif": 1}, {"famille": "iiif_natif", "reference": "ftp://archives.example"},
    {"famille": "iiif_natif", "reference": "https://user:pass@archives.example", "releve_le": "2026-11-17"}])
def test_acces_malforme_signale_sans_crash_ni_repli(invalide, monkeypatch):
    s = service()
    s["visionneuse_acces"]["par_type"]["matricule"] = invalide
    monkeypatch.setattr(archives, "services", lambda: (s,))
    assert archives.validate()
    assert selectionner(s, "matricule")["origine"] == "inconnu"
    assert selectionner(s, "matricule")["acces"] is None
    assert archives.view(s, "matricule")["telechargement"]["etat"] == "a_qualifier_pour_ce_type"


@pytest.mark.parametrize("invalide", [[], "x", None, {"par_type": []}, {"par_type": {}},
    {"famille": "iiif_natif", "iiif": 0}, {"par_type": {"matricules": {}}}])
def test_racine_invalide_ne_plante_pas(invalide, monkeypatch):
    s = service()
    s["visionneuse_acces"] = invalide
    monkeypatch.setattr(archives, "services", lambda: (s,))
    assert archives.validate()
    assert selectionner(s, "matricule")["origine"] == "inconnu"


def test_override_ne_transmet_pas_recette_ni_adaptateur(monkeypatch):
    s = service()
    s["recette"] = {"source": "https://archives.example/autre"}
    monkeypatch.setattr(archives, "recette", lambda code: {"resultat": "ok"})
    vue = archives.view(s, "matricules")
    assert vue["telechargement"]["etat"] == "a_qualifier_pour_ce_type"
    assert vue["telechargement"]["applicable_au_type"] is None
    assert vue["couverture_technique"]["capacites"]["navigation"] == "inconnu"
    assert vue["couverture_technique"]["niveau"] == 0
    assert vue["couverture_technique"]["mesures"] == {}


def test_renvoi_fonds_reste_prioritaire_sur_lien_visionneuse():
    s = service()
    s["couvertures"] = {"matricule": [{"etat": "autre_service", "reference": "https://archives.example/source",
                                      "lien": "https://autre.example/registre"}]}
    assert archives.view(s, "matricule", 1850)["lien"] == "https://autre.example/registre"


def test_donnees_existantes_valides_et_acces_typé_source():
    assert archives.validate() == []
    vue = archives.service(code="AD59", document="tables_decennales")
    assert vue["visionneuse_pour_la_demande"]["origine"] == "document"
    assert "ark:/33518/q0km71zxrv5s" in vue["visionneuse_pour_la_demande"]["acces"]["reference"]


def test_meme_editeur_conserve_adaptateur_et_recette(monkeypatch):
    s = service()
    s["recette"] = {"source": "https://archives.example/tables", "document": "matricule"}
    s["visionneuse_acces"]["par_type"]["matricule"].update(famille="editeur_ad", editeur="naoned", iiif=False)
    monkeypatch.setattr(archives, "recette", lambda code: {"resultat": "ok"})
    vue = archives.view(s, "matricule")
    assert vue["visionneuse_pour_la_demande"]["origine"] == "document"
    assert vue["telechargement"]["etat"] == "automatique"
    assert "applicable_au_type" not in vue["telechargement"]


@pytest.mark.parametrize("generique", [{"famille": "visionneuse_maison"}, None])
def test_editeur_general_inconnu_ecarte_adaptateur(generique):
    s = service()
    par_type = s["visionneuse_acces"]["par_type"]
    par_type["matricule"].update(famille="visionneuse_maison")
    s["visionneuse_acces"] = {**(generique or {}), "par_type": par_type}
    assert archives.view(s, "matricule")["telechargement"]["etat"] == "a_qualifier_pour_ce_type"


def test_ad59_tables_decennales_sans_regression():
    vue = archives.service(code="AD59", document="tables_decennales")
    assert vue["visionneuse_pour_la_demande"]["origine"] == "document"
    assert vue["telechargement"]["etat"] == "automatique"
    assert vue["couverture_technique"]["niveau"] >= 3
