"""La version du plugin doit être identique partout : Claude Code compare plugin.json / marketplace.json
pour proposer une mise à jour ; un écart ou un oubli laisse les utilisateurs sur l'ancien code."""

import importlib.util
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("version_script", ROOT / "scripts" / "version.py")
version_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version_script)


def test_versions_identiques():
    v = version_script.versions()
    assert len(set(v.values())) == 1, f"Versions divergentes : {v} — corriger avec `make version V=X.Y.Z`"
    assert version_script.SEMVER.match(next(iter(v.values())))


def test_uv_lock_aligne():
    lock = tomllib.loads((ROOT / "mcp" / "uv.lock").read_text(encoding="utf-8"))
    pkg = next(p for p in lock["package"] if p["name"] == "genealogiste-mcp")
    assert pkg["version"] == version_script.versions()["mcp/pyproject.toml"], "lancer `make version V=…` (uv lock)"


def test_set_version_conserve_la_forme(tmp_path, monkeypatch):
    for name in ("PLUGIN", "MARKETPLACE", "PYPROJECT"):
        src = getattr(version_script, name)
        dst = tmp_path / src.name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        monkeypatch.setattr(version_script, name, dst)
    avant = (tmp_path / "plugin.json").read_text(encoding="utf-8")
    version_script.set_version("9.8.7")
    assert set(version_script.versions().values()) == {"9.8.7"}
    apres = (tmp_path / "plugin.json").read_text(encoding="utf-8")
    assert len(avant.splitlines()) == len(apres.splitlines())
    with pytest.raises(SystemExit):
        version_script.set_version("v1")
