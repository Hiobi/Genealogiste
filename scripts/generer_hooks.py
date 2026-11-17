"""Générer ou vérifier hooks/hooks.json depuis le catalogue des outils (mcp/src/genealogiste_mcp/outils.py) ;
--profil-campagne affiche le profil de permissions d'une campagne sans surveillance (docs/campagne.md)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from genealogiste_mcp.outils import PREFIXE_PLUGIN, hooks_texte, profil_sans_surveillance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="échoue si hooks/hooks.json est périmé")
    parser.add_argument("--profil-campagne", action="store_true",
                        help="affiche le profil de permissions sans surveillance (settings JSON) et quitte")
    parser.add_argument("--prefixe", default=PREFIXE_PLUGIN,
                        help="préfixe des outils (serveur HTTP Docker : mcp__genealogiste__)")
    args = parser.parse_args()
    if args.profil_campagne:
        print(json.dumps(profil_sans_surveillance(args.prefixe), ensure_ascii=False, indent=2))
        return 0
    cible = Path(__file__).resolve().parents[1] / "hooks" / "hooks.json"
    contenu = hooks_texte()
    if args.check:
        if not cible.exists() or cible.read_text(encoding="utf-8") != contenu:
            print("hooks/hooks.json périmé : lancer make hooks")
            return 1
    else:
        cible.write_text(contenu, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
