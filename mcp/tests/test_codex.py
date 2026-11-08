"""Le paquet Codex reste inerte jusqu'au chargement de la politique native."""

import importlib.util
import json
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("configurer_codex", ROOT / "scripts/configurer_codex.py")
configurer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configurer)


def test_paquet_codex_sans_hooks_ni_mcp_implicites():
    manifest = json.loads((ROOT / "plugin.json").read_text())
    assert manifest["extensions"]["com.openai"]["hooks"] == []
    assert json.loads((ROOT / "mcp.json").read_text())["mcpServers"] == {}
    # Claude garde son serveur et ses confirmations.
    assert "genealogiste" in json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]
    assert json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]["PreToolUse"]


def test_profil_demande_approbation_de_tous_les_outils(tmp_path):
    data = tmp_path / 'privé "famille"'
    cfg = tomllib.loads(configurer.profil(data))
    assert cfg["approvals_reviewer"] == "user"
    mcp = cfg["mcp_servers"]["genealogiste"]
    assert mcp["default_tools_approval_mode"] == "prompt"
    assert "tools" not in mcp  # aucune exemption implicite pour une écriture auxiliaire
    assert mcp["required"] is True
    assert mcp["env"]["GENEALOGISTE_DATA_DIR"] == str(data)
    assert mcp["args"][-2:] == [str(ROOT / "mcp"), "genealogiste-mcp"]
    assert not data.exists()  # générer la config ne crée pas les données


@pytest.mark.parametrize("data", [ROOT, ROOT / "donnees"])
def test_profil_refuse_donnees_dans_plugin(data):
    with pytest.raises(ValueError, match="hors du dépôt"):
        configurer.profil(data)


def test_profil_resout_liens_symboliques(tmp_path):
    link = tmp_path / "lien"
    link.symlink_to(ROOT, target_is_directory=True)
    with pytest.raises(ValueError, match="hors du dépôt"):
        configurer.profil(link / "donnees")
