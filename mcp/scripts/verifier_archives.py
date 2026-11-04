"""Vérifie que les sites du référentiel des archives répondent (requête HEAD, aucun contenu téléchargé).

Usage : uv run python scripts/verifier_archives.py
Rapport seulement : ``verifie_le`` atteste une vérification humaine de l'entrée et n'est jamais modifié ici.
"""

from __future__ import annotations

import sys

import httpx

from genealogiste_mcp import archives

UA = "genealogiste-mcp (verification du referentiel des archives ; HEAD uniquement)"


def main() -> int:
    errs = archives.validate()
    for e in errs:
        print(f"FORMAT  {e}")
    bad = 0
    with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as client:
        for s in archives.services():
            for field in ("site", "visionneuse", "demande_a_distance"):
                url = s.get(field)
                if not url:
                    continue
                try:
                    code = client.head(url).status_code
                except httpx.HTTPError as exc:
                    code = type(exc).__name__
                ok = isinstance(code, int) and code < 400
                bad += not ok
                print(f"{'OK  ' if ok else 'KO  '}  {s['code']:<16} {field:<18} {code}  {url}")
            if w := archives.staleness(s):
                print(f"VIEUX   {w}")
    return 1 if errs or bad else 0


if __name__ == "__main__":
    sys.exit(main())
