"""Recette volontaire #112 : une vue candidate AD59, aucun acte identifié ni arbre modifié."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.robotparser import RobotFileParser

import pytest
from chaine_archives import parcourir

from genealogiste_mcp import server
from genealogiste_mcp.config import Config
from genealogiste_mcp.http import SourceError
from genealogiste_mcp.sources.registres import HOST, URL

pytestmark = [pytest.mark.archives_live,
              pytest.mark.skipif(os.environ.get("GENEALOGISTE_TEST_CHAINE_AD59") != "1",
                                 reason="GENEALOGISTE_TEST_CHAINE_AD59=1 requis")]


@pytest.fixture(autouse=True)
def dns_fictif():
    yield  # résolution réelle, remplace la fixture synthétique


def test_chaine_reelle_ad59(tmp_path):
    config = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", http_timeout=20,
                    user_agent="genealogiste-mcp (https://github.com/Hiobi/Genealogiste; recette AD59 ciblee)")
    app = server.App(config)
    app.http.max_retries = 1
    server.set_app(app)
    options = dict(cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
                   timeout=5, stdin=subprocess.DEVNULL, check=True)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], **options).stdout.strip()
    modifie = bool(subprocess.run(["git", "status", "--porcelain"], **options).stdout)
    empreintes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                  (Path(__file__), Path(__file__).with_name("chaine_archives.py"))}
    rapport = {"revision_base": revision, "checkout_modifie": modifie, "empreintes_recette": empreintes,
               "date": datetime.now(UTC).isoformat(), "environnement": "inconnu", "acte_identifie": False}
    try:
        try:
            texte, _ = app.http.get(HOST + "/robots.txt", parse="text", source="archives")
        except SourceError as exc:
            rapport["robots_erreur"] = str(exc)
            if exc.bloque_antirobot:
                pytest.skip("Protection sur robots.txt : arrêt.")
            raise
        robots = RobotFileParser()
        robots.parse(texte.splitlines())
        assert robots.can_fetch(config.user_agent, URL)
        assert robots.can_fetch(config.user_agent, HOST + "/visualizer/api")
        rapport.update(parcourir(app, "Saint-Vaast-en-Cambrésis", 1860))
        for etape, resultat in rapport["etapes"].items():
            if resultat.get("statut") == "bloque_antirobot":
                pytest.skip(f"Protection à {etape} : arrêt, aucune suite réseau.")
            assert "erreur" not in resultat, resultat
        assert rapport.get("vue_candidate_archivee"), rapport
    finally:
        (tmp_path / "recette-chaine-ad59.json").write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
        server.set_app(None)
        app.http.client.close()
