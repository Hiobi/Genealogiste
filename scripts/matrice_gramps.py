"""Lit la matrice de compatibilité Gramps (`compatibilite-gramps.json`) pour Make et GitHub Actions.

Bibliothèque standard uniquement (lancé par `python3` sans l'environnement du serveur MCP).

  python3 scripts/matrice_gramps.py github-web       # {"include": [...]} pour strategy.matrix
  python3 scripts/matrice_gramps.py github-desktop   # {"include": [...]} pour strategy.matrix
  python3 scripts/matrice_gramps.py web [ROLE…]      # lance make test-gramps sur chaque image, bilan final
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRICE = ROOT / "compatibilite-gramps.json"


def charger() -> dict:
    return json.loads(MATRICE.read_text(encoding="utf-8"))


def github_web() -> dict:
    return {"include": [{k: e[k] for k in ("role", "tag", "api", "image")} for e in charger()["gramps_web"]]}


def github_desktop() -> dict:
    return {"include": [{"version": e["version"]} for e in charger()["gramps_desktop"]]}


def executer_web(roles: list[str]) -> int:
    images = [e for e in charger()["gramps_web"] if not roles or e["role"] in roles]
    if not images:
        print(f"aucune image pour {roles}", file=sys.stderr)
        return 2
    bilan = []
    for e in images:
        print(f"\n== Gramps Web {e['tag']} (API {e['api']}, {e['role']})", flush=True)
        code = subprocess.run(["make", "--no-print-directory", "test-gramps", f"GRAMPSWEB_IMAGE={e['image']}",
                               f"GRAMPSWEB_API={e['api']}"], cwd=ROOT).returncode
        bilan.append((e, code))
    print("\n| image | API | rôle | résultat |\n|---|---|---|---|")
    for e, code in bilan:
        print(f"| {e['tag']} | {e['api']} | {e['role']} | {'ok' if code == 0 else 'ÉCHEC'} |")
    return 1 if any(code for _, code in bilan) else 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    commande, reste = argv[0], argv[1:]
    if commande == "github-web":
        print(json.dumps(github_web(), separators=(",", ":")))
    elif commande == "github-desktop":
        print(json.dumps(github_desktop(), separators=(",", ":")))
    elif commande == "web":
        return executer_web(reste)
    else:
        print(f"commande inconnue : {commande}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
