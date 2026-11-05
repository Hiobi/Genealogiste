"""Fixe la version du plugin partout où Claude Code et uv la lisent.

Claude Code ne propose une mise à jour (`claude plugin update`) que si le numéro de version change :
un commit publié sans nouvelle version n'atteint pas les utilisateurs.

Usage : python3 scripts/version.py            -> affiche la version de chaque fichier
        python3 scripts/version.py 0.3.0      -> écrit cette version (puis `uv lock` met à jour uv.lock)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PYPROJECT = ROOT / "mcp" / "pyproject.toml"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
PYPROJECT_VERSION = re.compile(r'^version = "([^"]+)"$', re.M)


def versions() -> dict[str, str]:
    market = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    entry = next(p for p in market["plugins"] if p["name"] == "genealogiste")
    return {
        ".claude-plugin/plugin.json": json.loads(PLUGIN.read_text(encoding="utf-8"))["version"],
        ".claude-plugin/marketplace.json": entry["version"],
        "mcp/pyproject.toml": PYPROJECT_VERSION.search(PYPROJECT.read_text(encoding="utf-8")).group(1),
    }


def _set_json(path: Path, version: str, find) -> None:
    text = path.read_text(encoding="utf-8")
    old = find(json.loads(text))
    # remplacement textuel ciblé : conserve la mise en forme du fichier
    pattern = re.compile(r'("version"\s*:\s*")' + re.escape(old) + '"')
    if len(pattern.findall(text)) != 1:
        raise SystemExit(f"{path} : champ version introuvable ou ambigu")
    path.write_text(pattern.sub(lambda m: m.group(1) + version + '"', text), encoding="utf-8")


def set_version(version: str) -> None:
    if not SEMVER.match(version):
        raise SystemExit(f"Version invalide : {version!r} (attendu : X.Y.Z)")
    _set_json(PLUGIN, version, lambda d: d["version"])
    _set_json(MARKETPLACE, version, lambda d: next(p for p in d["plugins"] if p["name"] == "genealogiste")["version"])
    text = PYPROJECT.read_text(encoding="utf-8")
    PYPROJECT.write_text(PYPROJECT_VERSION.sub(f'version = "{version}"', text, count=1), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        set_version(sys.argv[1])
    for f, v in versions().items():
        print(f"{v:10} {f}")
