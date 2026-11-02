from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.config import Config
from genealogiste_mcp.gedcom.mapping import read_gedcom

FIX = Path(__file__).parent / "fixtures"


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
