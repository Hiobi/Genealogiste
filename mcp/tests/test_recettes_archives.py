"""#143 (partie hors réseau) : services de recette déclarés au référentiel, enregistrement de la dernière
recette réelle et lecture dans archives_service."""

from __future__ import annotations

import json
from datetime import date

from genealogiste_mcp import archives, server


def test_services_qualifies_ont_une_recette():
    codes = {s["code"] for s in archives.services_recette()}
    assert {"AD59", "BnF"} <= codes
    for s in archives.services_recette():
        assert s["recette"]["source"] and isinstance(s["recette"].get("page", 0), int)
    assert archives.validate() == []


def test_recette_mal_formee_signalee(monkeypatch):
    faux = ({"code": "AD99", "nom": "x", "type": "autre", "recette": {"page": 2}},)
    monkeypatch.setattr(archives, "services", lambda: faux)
    assert any("recette" in e for e in archives.validate())


def test_enregistrer_et_lire_recette(tmp_path, monkeypatch):
    fichier = tmp_path / "recettes.json"
    monkeypatch.setattr(archives, "RECETTES", fichier)
    archives.enregistrer_recette("AD59", "protection", "HTTP 403 Cloudflare", jour=date(2026, 11, 10))
    archives.enregistrer_recette("AD59", "ok", "", jour=date(2026, 11, 15))
    archives.enregistrer_recette("AD59", "echec", "manifeste 404", jour=date(2026, 11, 22))
    r = json.loads(fichier.read_text(encoding="utf-8"))["AD59"]
    assert r == {"dernier_essai": "2026-11-22", "resultat": "echec", "detail": "manifeste 404",
                 "derniere_reussite": "2026-11-15"}
    assert archives.recette("AD59")["derniere_reussite"] == "2026-11-15"


def test_archives_service_expose_la_recette(app, tmp_path, monkeypatch):
    fichier = tmp_path / "recettes.json"
    monkeypatch.setattr(archives, "RECETTES", fichier)
    archives.enregistrer_recette("AD59", "ok", "", jour=date(2026, 11, 15))
    r = server.archives_service(code="AD59")
    vue = r if "recette" in r else r["services"][0]
    assert vue["recette"]["derniere_reussite"] == "2026-11-15"


def test_recette_vps_distincte_des_autres_adresses(tmp_path, monkeypatch):
    monkeypatch.setattr(archives, "RECETTES", tmp_path / "recettes.json")
    archives.enregistrer_recette("AD59", "protection", "hCaptcha", environnement="vps")
    archives.enregistrer_recette("AD59", "ok", environnement="local")
    acces = archives.service(code="AD59")["acces_vps"]
    assert acces["verdict"] == "defi"
    assert acces["detail"] == "hCaptcha"
    assert acces["date_mesure"]
    assert archives.recette("AD59")["mesures"]["local"]["verdict"] == "oui"


def test_acces_vps_inconnu_sans_mesure(tmp_path, monkeypatch):
    monkeypatch.setattr(archives, "RECETTES", tmp_path / "recettes.json")
    archives.enregistrer_recette("AD59", "ok")
    assert archives.service(code="AD59")["acces_vps"]["verdict"] == "inconnu"


def test_adaptateur_sans_recette_signale_non_eprouve():
    eprouve = archives.service(code="AD25")["telechargement"]
    assert eprouve["etat"] == "automatique"
    for code in ("AD37", "AD80", "AD91"):  # adaptateur Naoned sans recette (AD14, AD972 éprouvés le 2026-11-18)
        t = archives.service(code=code)["telechargement"]
        assert t["adaptateur_disponible"] and t["etat"] == "automatique_non_eprouve" and t["note"]


def test_mesure_conserve_reference_meme_sans_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(archives, "RECETTES", tmp_path / "recettes.json")
    ref = {"source": "https://archives.example/registre", "document": "naissance"}
    archives.enregistrer_recette("AD00", "ok", environnement="local", reference=ref)
    mesure = archives.recette("AD00")["mesures"]["local"]
    assert mesure["reference"] == ref
    assert mesure["revision"] == ""
