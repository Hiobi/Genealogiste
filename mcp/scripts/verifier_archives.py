"""Vérifie que les sites du référentiel des archives, des sites tiers (#181) et des services de contexte historique
(#285) répondent (requête HEAD ; repli GET limité aux en-têtes, corps jamais lu, quand le site refuse HEAD).

Services de contexte : une requête par service, sans clé ni paramètre (aucune donnée personnelle) ; un service en
lien seulement, protégé ou à clé requise rend AVERT (jamais KO), sans contournement.

Usage : uv run python scripts/verifier_archives.py
Rapport seulement : ``verifie_le`` atteste une vérification humaine de l'entrée et n'est jamais modifié ici.
"""

from __future__ import annotations

import sys

import httpx

from genealogiste_mcp import archives, sites_tiers
from genealogiste_mcp.contexte import services as services_contexte

UA = "genealogiste-mcp (verification du referentiel des archives ; en-tetes uniquement)"
REPLI = {400, 403, 405, 501}  # sites qui refusent HEAD (400 : OAI-PMH de Persée, #285) mais répondent en GET


def sonder(client: httpx.Client, url: str) -> tuple[str, str]:
    """(verdict, détail) : OK, AVERT (site présent mais non contrôlable : anti-robots, TLS incomplet) ou KO."""
    def get():
        request = client.build_request("GET", url)
        for _ in range(client.max_redirects + 1):
            # httpx lit les corps intermédiaires si follow_redirects=True, même en streaming.
            response = client.send(request, stream=True, follow_redirects=False)
            try:
                if not client.follow_redirects or response.next_request is None:
                    return response
                request = response.next_request
            finally:
                response.close()
        raise httpx.TooManyRedirects("Trop de redirections", request=request)

    try:
        try:
            r = client.head(url)
        except (httpx.ReadError, httpx.RemoteProtocolError):  # connexion coupée sur HEAD
            r = get()
        else:
            if r.status_code in REPLI:
                r = get()
    except httpx.ConnectError as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            return "AVERT", "certificat TLS non vérifiable (chaîne incomplète ?) : vérifier dans un navigateur"
        return "KO", type(exc).__name__
    except httpx.HTTPError as exc:
        return "KO", type(exc).__name__
    if r.status_code < 400:
        return "OK", str(r.status_code)
    if r.status_code in (403, 503) and (r.headers.get("cf-mitigated") or "cloudflare" in r.headers.get("server", "").lower()):
        return "AVERT", f"{r.status_code} protection anti-robots : vérifier dans un navigateur"
    return "KO", str(r.status_code)


def sonder_contexte(client: httpx.Client, s: dict) -> tuple[str, str, str]:
    """(verdict, détail, url) d'un service de contexte : url_sonde (requête minimale sans donnée personnelle), sinon
    son point d'accès, sinon son site. KO réservé aux services interrogeables par défaut (api, sans clé requise,
    sans protection) ; les autres rendent AVERT."""
    url = services_contexte.url_de_sondage(s)
    verdict, detail = sonder(client, url)
    if verdict == "OK" and s.get("protection") != "aucune":
        verdict, detail = "AVERT", f"{detail}, protection relevée : {s['protection']}"
    if verdict == "KO" and not services_contexte.actif_par_defaut(s):
        raison = ("lien seulement" if s["mode"] == "lien_seulement" else
                  f"clé requise ({s['variable_cle']}), sondé sans clé" if s["cle"] == "requise" else "protégé")
        verdict, detail = "AVERT", f"{detail} ({raison})"
    return verdict, detail, url


def main() -> int:
    errs = (archives.validate() + [f"sites_tiers : {e}" for e in sites_tiers.validate()]
            + [f"sources_contexte : {e}" for e in services_contexte.validate()])
    for e in errs:
        print(f"FORMAT  {e}")
    bad = 0
    with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as client:
        for s in archives.services():
            for field in ("site", "visionneuse", "demande_a_distance"):
                url = s.get(field)
                if not url:
                    continue
                verdict, detail = sonder(client, url)
                bad += verdict == "KO"
                print(f"{verdict:<6}  {s['code']:<16} {field:<18} {detail}  {url}")
            if w := archives.staleness(s):
                print(f"VIEUX   {w}")
        for s in sites_tiers.sites():  # protection relevée signalée, jamais contournée
            verdict, detail = sonder(client, s["url"])
            if verdict == "OK" and s.get("protection") not in (None, "aucune"):
                verdict, detail = "AVERT", f"{detail}, protection relevée : {s['protection']}"
            bad += verdict == "KO"
            print(f"{verdict:<6}  {s['code']:<16} {'site_tiers':<18} {detail}  {s['url']}")
        for s in services_contexte.services():  # rapport seulement : le référentiel n'est jamais modifié
            verdict, detail, url = sonder_contexte(client, s)
            bad += verdict == "KO"
            print(f"{verdict:<6}  {s['code']:<16} {'contexte':<18} {detail}  {url}")
    return 1 if errs or bad else 0


if __name__ == "__main__":
    sys.exit(main())
