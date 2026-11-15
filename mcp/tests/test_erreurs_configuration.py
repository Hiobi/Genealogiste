"""#146 : une erreur d'initialisation ou une exception d'outil arrive au modèle avec sa cause et son remède,
jamais sous la forme opaque « Error executing tool … » ; validation de la configuration au démarrage."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client

from genealogiste_mcp import server

RACINE_PLUGIN = Path(server.__file__).resolve().parents[3]


def _appel(nom: str, args: dict | None = None):
    return asyncio.run(server.mcp.call_tool(nom, args or {}))


def _charge(res) -> dict:
    assert res.is_error, res
    return json.loads(res.content[0].text)


@pytest.fixture
def env_neuf(tmp_path, monkeypatch):
    """App reconstruite à partir de l'environnement, comme au premier appel d'outil du serveur."""
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path / "donnees"))
    monkeypatch.setenv("GENEALOGISTE_CACHE", str(tmp_path / "cache.sqlite"))
    monkeypatch.delenv("GENEALOGISTE_ENV_FILE", raising=False)
    server.set_app(None)
    yield tmp_path
    server.set_app(None)


def test_backend_invalide(env_neuf, monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_BACKEND", "mauvais")
    d = _charge(_appel("arbre_info"))
    assert "GENEALOGISTE_BACKEND" in d["erreur"]
    assert d["cause"] == "configuration" and d["variable"] == "GENEALOGISTE_BACKEND"
    assert "fichier | gramps" in d["erreur"] and "make check" in d["remede"]


def test_gramps_injoignable(env_neuf, monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_BACKEND", "gramps")
    monkeypatch.setenv("GENEALOGISTE_GRAMPS_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("GENEALOGISTE_GRAMPS_USER", "u")
    monkeypatch.setenv("GENEALOGISTE_GRAMPS_PASSWORD", "p")
    d = _charge(_appel("arbre_info"))
    assert d["cause"] == "gramps_web"
    assert "GENEALOGISTE_GRAMPS_URL" in d["remede"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignore les droits de fichiers")
def test_donnees_non_inscriptibles(env_neuf):
    bloque = env_neuf / "bloque"
    bloque.mkdir()
    bloque.chmod(0o500)
    os.environ["GENEALOGISTE_DATA_DIR"] = str(bloque / "donnees")
    try:
        d = _charge(_appel("arbre_info"))
    finally:
        bloque.chmod(0o700)
    assert d["cause"] == "droits"
    assert "GENEALOGISTE_DATA_DIR" in d["remede"]


def test_donnees_dans_le_depot_du_plugin(env_neuf, monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(RACINE_PLUGIN / "donnees-interdites"))
    d = _charge(_appel("arbre_info"))
    assert d["cause"] == "donnees_dans_le_plugin"
    assert not (RACINE_PLUGIN / "donnees-interdites").exists()


def test_git_absent(env_neuf, monkeypatch):
    vide = env_neuf / "bin-vide"
    vide.mkdir()
    monkeypatch.setenv("PATH", str(vide))
    d = _charge(_appel("arbre_info"))
    assert d["cause"] == "git_absent" and "git" in d["remede"]


def test_exception_inattendue_d_outil(app, monkeypatch):
    def boum():
        raise RuntimeError("panne simulée")
    monkeypatch.setattr(app, "tree", boum)
    d = _charge(_appel("arbre_info"))
    assert "panne simulée" in d["erreur"] and d["outil"] == "arbre_info"
    assert d["cause"] == "interne" and d["remede"]


def test_demarrage_check_code_de_sortie(env_neuf, monkeypatch, capsys):
    monkeypatch.setenv("GENEALOGISTE_BACKEND", "mauvais")
    monkeypatch.setattr(sys, "argv", ["genealogiste-mcp", "--check"])
    with pytest.raises(SystemExit) as e:
        server.main()
    assert e.value.code == 2
    assert "GENEALOGISTE_BACKEND" in capsys.readouterr().err


def test_demarrage_http_refuse_config_fatale(env_neuf, monkeypatch, capsys):
    monkeypatch.setenv("GENEALOGISTE_BACKEND", "mauvais")
    monkeypatch.setattr(sys, "argv", ["genealogiste-mcp", "--transport", "streamable-http"])
    with pytest.raises(SystemExit) as e:
        server.main()
    assert e.value.code == 2
    assert "GENEALOGISTE_BACKEND" in capsys.readouterr().err


def test_stdio_config_invalide_cause_visible(tmp_path):
    """Bout en bout : en stdio, le serveur reste joignable et chaque outil donne la cause."""
    parametres = StdioServerParameters(
        command=sys.executable, args=["-m", "genealogiste_mcp.server"], cwd=str(tmp_path),
        env={"GENEALOGISTE_DATA_DIR": str(tmp_path / "donnees"), "GENEALOGISTE_CACHE": str(tmp_path / "c.sqlite"),
             "GENEALOGISTE_BACKEND": "mauvais", "PATH": os.environ["PATH"],
             "PYTHONPATH": str(Path(server.__file__).resolve().parents[1])})

    async def echange():
        with anyio.fail_after(20):
            async with stdio_client(parametres) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    res = await session.call_tool("arbre_info", {})
                    assert res.is_error
                    d = json.loads(res.content[0].text)
                    assert d["variable"] == "GENEALOGISTE_BACKEND" and d["remede"]
    asyncio.run(echange())
