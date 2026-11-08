"""Produit un profil Codex à relire, sans modifier la configuration personnelle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def profil(data_dir: Path, plugin_root: Path = ROOT) -> str:
    root = plugin_root.expanduser().resolve()
    data = data_dir.expanduser().resolve()
    if data == root or root in data.parents:
        raise ValueError("Le répertoire de données doit être hors du dépôt du plugin.")
    if not (root / "mcp" / "uv.lock").is_file():
        raise ValueError("Racine du plugin invalide : mcp/uv.lock absent.")
    # Les chaînes JSON constituent aussi des chaînes TOML valides (chemins Windows compris).
    def quote(value: Path) -> str:
        return json.dumps(str(value), ensure_ascii=False)
    return f'''# Profil genealogiste.config.toml — conserver prompt pour TOUS les outils.
# MCP séparé du paquet : aucune connexion avant le chargement de ce profil.
approval_policy = "on-request"
approvals_reviewer = "user"

[plugins."genealogiste@genealogiste"]
enabled = true

[mcp_servers.genealogiste]
command = "uv"
args = ["run", "--quiet", "--locked", "--directory", {quote(root / 'mcp')}, "genealogiste-mcp"]
default_tools_approval_mode = "prompt"
required = true

[mcp_servers.genealogiste.env]
GENEALOGISTE_DATA_DIR = {quote(data)}
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True, help="Données privées, hors du dépôt")
    args = parser.parse_args()
    try:
        print(profil(args.data_dir), end="")
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
