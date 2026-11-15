"""#148 : serveur MCP déclaré par le manifeste du plugin (jamais en portée projet), version exposée et
comparée à celle du plugin sur disque, User-Agent dérivé de la version du paquet."""

from __future__ import annotations

import json
from pathlib import Path

from genealogiste_mcp import diagnostic, server
from genealogiste_mcp.config import Config, user_agent_par_defaut

ROOT = Path(__file__).resolve().parents[2]


def test_serveur_declare_dans_le_manifeste_claude():
    manifeste = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    serveur = manifeste["mcpServers"]["genealogiste"]
    assert serveur["command"] == "uv"
    assert "${CLAUDE_PLUGIN_ROOT}/mcp" in serveur["args"]
    # Plus de déclaration lue en portée projet quand le dépôt est ouvert comme dossier de travail.
    assert not (ROOT / ".mcp.json").exists()


def test_user_agent_versionne(tmp_path):
    ua = Config(data_dir=tmp_path, cache_path=tmp_path / "c.sqlite").user_agent
    assert ua == user_agent_par_defaut()
    assert f"genealogiste-mcp/{diagnostic.version_serveur()}" in ua
    assert "/0.1 " not in ua


def test_arbre_info_version_et_ecart(app, monkeypatch):
    info = server.arbre_info()
    assert info["version_serveur"] == diagnostic.version_serveur()
    monkeypatch.setattr(diagnostic, "version_plugin", lambda: ("99.0.0", "/plugin/.claude-plugin/plugin.json"))
    info = server.arbre_info()
    assert info["version_plugin"] == "99.0.0"
    assert any("reconnecter le serveur MCP" in w for w in info["avertissements"])
