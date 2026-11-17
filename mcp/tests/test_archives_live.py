"""Recette de contrat contre les services d'archives réels (make test-archives, #143). Ignorée sans
GENEALOGISTE_TEST_ARCHIVES=1 : jamais exécutée par make test.

Une recette par service du référentiel doté d'un champ « recette » (adaptateur qualifié) : résoudre l'ARK de
référence (sans requête), lister une petite fenêtre de vues, télécharger une vue en basse définition. Quelques
requêtes par service, débit du plugin respecté (réel, pas simulé). Toute protection anti-robot arrête la
recette du service : résultat « protection », jamais de contournement. Avec GENEALOGISTE_RECETTE_ECRIRE=1, le
résultat est inscrit dans referentiels/recettes_archives.json (lu par archives_service)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from genealogiste_mcp import archives, server
from genealogiste_mcp.config import Config
from genealogiste_mcp.http import SourceError

ACTIVE = os.environ.get("GENEALOGISTE_TEST_ARCHIVES") == "1"
ECRIRE = os.environ.get("GENEALOGISTE_RECETTE_ECRIRE") == "1"
ENVIRONNEMENT = os.environ.get("GENEALOGISTE_RECETTE_ENVIRONNEMENT", "inconnu")
pytestmark = [pytest.mark.archives_live,
              pytest.mark.skipif(not ACTIVE, reason="GENEALOGISTE_TEST_ARCHIVES=1 non défini (make test-archives)")]

def _appel(outil, *args, **kw) -> dict:
    """Une exception d'outil (avant #138) est traitée comme une enveloppe d'erreur."""
    try:
        return outil(*args, **kw)
    except SourceError as exc:
        return {"erreur": str(exc), "statut": "bloque_antirobot" if exc.bloque_antirobot else "erreur"}


def _protection(res: dict) -> bool:
    return res.get("statut") == "bloque_antirobot"


@pytest.fixture(autouse=True)
def dns_fictif():
    """Annule la fixture DNS simulée de conftest : la politique réseau résout réellement les hôtes."""
    yield


@pytest.fixture(scope="module")
def revision_recette():
    """Capturer avant que les recettes ne modifient leur fichier de résultats."""
    racine = Path(__file__).resolve().parents[2]
    options = dict(cwd=racine, capture_output=True, text=True, timeout=5,
                   stdin=subprocess.DEVNULL, check=True)
    propre = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], **options).stdout
    if propre:
        return ""
    return subprocess.run(["git", "rev-parse", "HEAD"], **options).stdout.strip()


@pytest.mark.parametrize("service", archives.services_recette(), ids=lambda s: s["code"])
def test_recette_reelle(service, tmp_path, revision_recette):
    ref = service["recette"]
    revision = revision_recette
    config = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", http_timeout=20)
    app = server.App(config)
    app.http.max_retries = 2
    server.set_app(app)
    etape = "ark_resoudre"
    try:
        res = _appel(server.ark_resoudre, ref["source"], verifier=False)
        assert "erreur" not in res, res
        etape = "archives_naviguer"
        res = _appel(server.archives_naviguer, ref["source"], page=ref.get("page", 1), pas=3)
        if not _protection(res):
            assert "erreur" not in res, res
            assert res.get("vues"), res
            etape = "archive_image"
            res = _appel(server.archive_image, ref["source"], page=ref.get("page", 0), largeur=400)
        if _protection(res):
            if ECRIRE:
                archives.enregistrer_recette(service["code"], "protection", f"{etape} : {res['erreur']}",
                                             environnement=ENVIRONNEMENT, revision=revision, reference=ref)
            pytest.skip(f"{service['code']} : protection à l'étape {etape}, recette arrêtée ({res['erreur'][:200]})")
        assert "erreur" not in res, res
        assert Path(res["chemin_absolu"]).is_file()
    except AssertionError as exc:
        if ECRIRE:
            archives.enregistrer_recette(service["code"], "echec", f"{etape} : {exc}", environnement=ENVIRONNEMENT, revision=revision, reference=ref)
        raise
    else:
        if ECRIRE:
            archives.enregistrer_recette(service["code"], "ok", "", environnement=ENVIRONNEMENT, revision=revision, reference=ref)
    finally:
        server.set_app(None)
        app.http.client.close()
