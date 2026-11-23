from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.config import Config
from genealogiste_mcp.gedcom.mapping import read_gedcom

FIX = Path(__file__).parent / "fixtures"


INTERNES = {"localhost": "127.0.0.1", "interne.example": "10.0.0.5", "metadata.example": "169.254.169.254",
            "rebond.example": "192.168.1.1"}


PILOTAGE_TESTS = ("GENEALOGISTE_TEST_", "GENEALOGISTE_RECETTE_")


@pytest.fixture(autouse=True)
def configuration_isolee(monkeypatch, tmp_path_factory):
    """Aucune configuration réelle : `load_config` ne lit ni le `.env` de l'utilisateur
    (~/.local/share/genealogiste/.env) ni ses variables GENEALOGISTE_*. Le chargement d'un `.env`
    écrit dans os.environ (setdefault) : l'environnement est restauré après chaque test pour
    qu'aucune valeur ne fuie vers le suivant. Les variables de pilotage des recettes sont conservées."""
    sauvegarde = dict(os.environ)
    maison = tmp_path_factory.mktemp("maison")
    for cle in list(os.environ):
        if cle.startswith("GENEALOGISTE_") and not cle.startswith(PILOTAGE_TESTS):
            monkeypatch.delenv(cle)
    monkeypatch.setenv("HOME", str(maison))
    for var, rel in (("XDG_DATA_HOME", ".local/share"), ("XDG_CACHE_HOME", ".cache"),
                     ("XDG_CONFIG_HOME", ".config")):
        monkeypatch.setenv(var, str(maison / rel))
    yield maison
    os.environ.clear()
    os.environ.update(sauvegarde)


@pytest.fixture(autouse=True)
def dns_fictif(monkeypatch):
    """Aucune résolution DNS réelle : noms publics -> adresse publique de documentation, noms « internes » ->
    adresses privées (politique réseau #42)."""
    from genealogiste_mcp import reseau
    monkeypatch.setattr(reseau, "getaddrinfo", lambda host, port: [INTERNES.get(host, "93.184.216.34")])


@pytest.fixture
def fixtures() -> Path:
    return FIX


@pytest.fixture
def famille_text() -> str:
    return (FIX / "famille.ged").read_text(encoding="utf-8")


@pytest.fixture
def tree(famille_text):
    return read_gedcom(famille_text)[0]


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite",
                  wikitree_app_id="genealogiste-tests")


@pytest.fixture
def app(config):
    """Application MCP isolée (données temporaires, pas d'attente réelle)."""
    sleeps: list[float] = []
    a = server.App(config, sleeper=sleeps.append)
    a.sleeps = sleeps
    server.set_app(a)
    yield a
    server.set_app(None)


@pytest.fixture
def app_famille(app, fixtures):
    """Application dont l'arbre de travail est la fixture famille.ged (commitée)."""
    shutil.copy(fixtures / "famille.ged", app.store.path)
    # normalisation par l'écrivain pour partir d'un état stable
    app.store.write(app.store.load())
    app.store.commit("fixture")
    return app


CAS_CONTEXTE = ("mineur_artois_oklahoma", "cultivateur_ancien_regime", "soldat_1914_1918", "lieu_non_documente")


@pytest.fixture(params=CAS_CONTEXTE)
def app_contexte(request, app, fixtures):
    """Application dont l'arbre de travail est un cas témoin du contexte historique (#292), un par paramètre.

    `app_contexte.cas` : nom du cas ; `app_contexte.attendus` : contenu de `<cas>.attendus.json`
    (voir `fixtures/contexte/`). Paramétrable aussi à la demande :
    `@pytest.mark.parametrize("app_contexte", ["soldat_1914_1918"], indirect=True)`."""
    import json
    cas = request.param
    dossier = fixtures / "contexte"
    shutil.copy(dossier / f"{cas}.ged", app.store.path)
    app.store.write(app.store.load())  # normalisation par l'écrivain, comme app_famille
    app.store.commit(f"cas témoin {cas}")
    app.cas = cas
    app.attendus = json.loads((dossier / f"{cas}.attendus.json").read_text(encoding="utf-8"))
    return app
