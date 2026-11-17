"""Générer ou vérifier le tableau de couverture sans réseau."""
from __future__ import annotations

import argparse
from pathlib import Path

from genealogiste_mcp import archives
from genealogiste_mcp.capacites_archives import tableau


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    cible = Path(__file__).resolve().parents[1] / "docs/couverture-archives.md"
    contenu = tableau(archives.services(), archives.recettes(), archives.DOCUMENTS)
    if args.check:
        if not cible.exists() or cible.read_text(encoding="utf-8") != contenu:
            print("Tableau périmé : relancer scripts/generer_couverture_archives.py")
            return 1
    else:
        cible.write_text(contenu, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
