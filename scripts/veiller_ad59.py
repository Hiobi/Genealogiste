"""Veille des mises en ligne des AD59 (#380) : étape réseau explicite, hors `make test` et hors outils MCP.

    make veille-ad59                      # ou :
    uv --directory mcp run python ../scripts/veiller_ad59.py [--forum flux|html|non] [--sans-formulaires]
        [--sans-classeur] [--limite 10] [--sortie veille.json]

Un passage complet émet au plus 15 requêtes, espacées, par le client HTTP du plugin (politique réseau, intervalle
et plafond par hôte, configuration de l'utilisateur) : la page des nouveautés (classeur 3 E millésimé), le
``robots.txt`` du forum puis son flux Atom des ajouts (ou sa page HTML), et la page de chacun des formulaires de
recherche connus. Aucune image, aucune notice, aucun nom de personne, aucun compte ; un nouveau classeur est
signalé, jamais téléchargé. Les constats sont consignés au journal de recherche (source ``veille_ad59``).

Code de sortie : 0 si rien n'est à signaler, 1 s'il y a au moins un signalement (dérive, nouveauté à vérifier,
référentiel ancien, volet non lu). Détail : docs/veille-ad59.md.
"""

from __future__ import annotations

import argparse
import json

from genealogiste_mcp import server
from genealogiste_mcp.sources import veille_ad59


def main(argv: list[str] | None = None, app=None) -> int:
    """``app`` : application déjà construite (tests) ; par défaut celle de la configuration de l'utilisateur."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--forum", choices=["flux", "html", "non"], default="flux",
                        help="lecture du forum des ajouts : flux Atom (défaut), page HTML, ou aucune")
    parser.add_argument("--sans-formulaires", action="store_true", help="ne pas relire les formulaires de recherche")
    parser.add_argument("--sans-classeur", action="store_true", help="ne pas relire la page des nouveautés")
    parser.add_argument("--limite", type=int, default=10, help=f"fils du forum retenus (1 à {veille_ad59.MAX_FILS})")
    parser.add_argument("--sortie", help="fichier JSON du résultat complet")
    args = parser.parse_args(argv)
    fournie = app is not None
    app = app or server.App()
    try:
        resultat = veille_ad59.veiller(app.sctx, formulaires=not args.sans_formulaires,
                                       forum="" if args.forum == "non" else args.forum,
                                       classeur=not args.sans_classeur, limite=args.limite)
    finally:
        if not fournie:
            app.http.client.close()
    if args.sortie:
        with open(args.sortie, "w", encoding="utf-8") as f:
            json.dump(resultat, f, ensure_ascii=False, indent=1)
    for r in resultat["referentiels"]:
        print(f"référentiel {r['referentiel']} : relevé le {r['releve_le']}"
              + (" — À RENOUVELER" if r["a_renouveler"] else ""))
    if "classeur_3e" in resultat:
        print(f"classeur 3 E : {resultat['classeur_3e']['etat']} — {resultat['classeur_3e']['message']}")
    if "forum" in resultat:
        forum = resultat["forum"]
        print(f"forum ({forum['mode']}) : {forum['etat']} — {forum['robots']}")
        for fil in forum["fils"]:
            print(f"  {'*' if fil['nouveau'] else ' '} {fil['date']} {fil['titre']} <{fil['lien']}>")
    if "formulaires" in resultat:
        print(f"formulaires : {resultat['formulaires']['resume']}")
        for f in resultat["formulaires"]["formulaires"]:
            if f["etat"] != "conforme":
                print("  " + json.dumps(f, ensure_ascii=False))
    print(f"{resultat['requetes']} requête(s) émise(s) ; {len(resultat['signalements'])} signalement(s).")
    for s in resultat["signalements"]:
        print("SIGNALEMENT : " + s)
    return int(bool(resultat["signalements"]))


if __name__ == "__main__":
    raise SystemExit(main())
