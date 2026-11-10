"""Sonde passive des visionneuses des services départementaux (issue #128), sans contournement.

uv --directory mcp run python ../scripts/sonder_visionneuses.py [--sortie sonde.json]

Une requête par service sur ``<site>/visualizer/api`` sans paramètre. Classement :
``naoned_api`` (réponse JSON 400 « Unable to handle this request », signature de l'API Naoned déjà
prise en charge pour AD59), ``anubis`` / ``cloudflare`` / ``redirection_js`` (défi anti-robot : non
qualifiable sans navigateur, jamais contourné), ``injoignable``, ``autre``. Un classement ``naoned_api``
ne prouve pas qu'un registre est lisible : il faut une recette réelle sur un ARK de registre
(scripts/verifier_telechargements.py) avant de déclarer ``resolution_image``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json

import httpx

from genealogiste_mcp import archives

ENTETES = {"User-Agent": "Mozilla/5.0 (genealogiste; sonde passive)", "Accept": "application/json,text/html"}


def classer(statut: int | None, corps: str) -> str:
    bas = corps.lower()
    if statut is None:
        return "injoignable"
    if "anubis" in bas:
        return "anubis"
    if "just a moment" in bas or "cf-chl" in bas:
        return "cloudflare"
    if "window.location.href='/redirect_" in bas:
        return "redirection_js"
    if statut == 400 and "unable to handle this request" in bas:
        return "naoned_api"
    return "autre"


def sonder(service: dict) -> dict:
    site = (service.get("site") or "").rstrip("/")
    statut, corps = None, ""
    if site:
        try:
            r = httpx.get(site + "/visualizer/api", headers=ENTETES, timeout=10, follow_redirects=True)
            statut, corps = r.status_code, r.text[:2000]
        except httpx.HTTPError:
            pass
    return {"code": service["code"], "site": site, "http": statut, "classe": classer(statut, corps)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sortie", help="fichier JSON de résultats")
    args = parser.parse_args()
    services = [s for s in archives.services() if s.get("type") == "departementales"]
    with concurrent.futures.ThreadPoolExecutor(16) as ex:
        resultats = list(ex.map(sonder, services))
    classes: dict[str, list[str]] = {}
    for r in resultats:
        classes.setdefault(r["classe"], []).append(r["code"])
    for classe, codes in sorted(classes.items()):
        print(f"{classe} ({len(codes)}) : {' '.join(codes)}")
    if args.sortie:
        with open(args.sortie, "w", encoding="utf-8") as f:
            json.dump(resultats, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
