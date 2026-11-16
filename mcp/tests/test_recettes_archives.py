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


def test_adaptateur_sans_recette_signale_non_eprouve():
    eprouve = archives.service(code="AD25")["telechargement"]
    assert eprouve["etat"] == "automatique"
    for code in ("AD14", "AD91", "AD972"):
        t = archives.service(code=code)["telechargement"]
        assert t["adaptateur_disponible"] and t["etat"] == "automatique_non_eprouve" and t["note"]
