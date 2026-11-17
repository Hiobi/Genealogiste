"""Recette AD59 volontaire : GENEALOGISTE_TEST_REGISTRES=1, jamais dans la suite ordinaire.

Un contrôle robots.txt puis trois appels de recherche ciblés : registre NMD, filtre N, négatif.
Pas de feuilletage, téléchargement, API de métadonnées ou contournement de défi.
"""

from __future__ import annotations

import json
import os
from urllib.robotparser import RobotFileParser

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.config import Config
from genealogiste_mcp.http import SourceError
from genealogiste_mcp.sources.registres import HOST, URL

pytestmark = [pytest.mark.archives_live,
              pytest.mark.skipif(os.environ.get("GENEALOGISTE_TEST_REGISTRES") != "1",
                                 reason="GENEALOGISTE_TEST_REGISTRES=1 requis (recette HTTP volontaire)")]


@pytest.fixture(autouse=True)
def dns_fictif():
    """La recette volontaire utilise la résolution réelle, jamais le DNS simulé de conftest."""
    yield


def test_recherche_reelle_registres_ad59(tmp_path):
    config = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", http_timeout=20,
                    user_agent="genealogiste-mcp (https://github.com/Hiobi/Genealogiste; recette AD59 ciblee)")
    app = server.App(config)
    app.http.max_retries = 1
    server.set_app(app)
    resultats = []
    try:
        try:
            texte, _ = app.http.get(HOST + "/robots.txt", parse="text", source="archives")
        except SourceError as exc:
            if exc.bloque_antirobot:
                pytest.skip("Protection sur robots.txt : aucune recherche lancée.")
            raise
        robots = RobotFileParser()
        robots.parse(texte.splitlines())
        assert robots.can_fetch(config.user_agent, URL), "Recherche interdite par robots.txt : arrêt."
        for type_acte, annee in [("NMD", 1860), ("N", 1860), ("", 1200)]:
            result = server.archives_registres("AD59", "Saint-Vaast-en-Cambrésis", annee, type_acte=type_acte)
            resultats.append(result)
            (tmp_path / "recette-registres.json").write_text(json.dumps(resultats, ensure_ascii=False, indent=2))
            if result.get("statut") == "bloque_antirobot":
                pytest.skip(f"Protection AD59 : arrêt sans autre requête ({result['protection']}).")
            assert "erreur" not in result, result
            if annee == 1200:
                assert result["total"] == 0 and result["resultats"] == []
                assert result.get("recherche_negative")
            else:
                registres = {r["ark"]: r for r in result["resultats"]}
                assert "ark:/33518/jq9hpbzxnc72" in registres, result
                registre = registres["ark:/33518/jq9hpbzxnc72"]
                assert "".join(registre["cote"].split()) == "5Mi018R024"
                assert registre["bornes"] == [1831, 1864] and registre["nb_vues"] == 954
    finally:
        server.set_app(None)
        app.http.client.close()
