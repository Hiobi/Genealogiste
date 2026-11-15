"""Recette réseau explicite : une vue publique par service, cache et archivage dans un dossier jetable.

uv --directory mcp run python ../scripts/verifier_telechargements.py --service ad59
Aucune clé, aucun compte, aucune donnée d'arbre ; aucune image réelle ajoutée au dépôt.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from genealogiste_mcp import server
from genealogiste_mcp.config import Config

EXEMPLES = {
    "ad59": "https://archivesdepartementales.lenord.fr/ark:/33518/d31bpqk27xhj/b27563d3-2ef8-4798-832a-d604a4e131dc",
    "ad59_td": "ark:/33518/q0km71zxrv5s",
    "ad25": "https://archives.doubs.fr/ark:/25993/7rx3d5cm9tzk/0cb0200e-150f-426e-958f-68ce8f04f9a2",
    "ad39": "https://archives39.fr/ark:/36595/p3rdck27zjbm/6e6facba-b9d7-4672-9c7c-ea86f058a89b",
    "suisse": "https://www.e-manuscripta.ch/i3f/v20/3192957/manifest",
    "loc": "https://tile.loc.gov/image-services/iiif/service:sgp:sgpbatches:batch_dlc_anacostia_ver01:"
           "data:sn84025948:0023728866A:1942081001:0202/info.json",
}


def verifier(nom: str, racine: Path) -> dict:
    config = Config(data_dir=racine / "donnees", cache_path=racine / "cache.sqlite", http_timeout=15)
    app = server.App(config)
    app.http.max_retries = 1  # recette bornée ; les reprises normales du plugin restent inchangées
    calls = []
    app.http.client.event_hooks["response"].append(lambda r: calls.append(
        {"hote": r.url.host, "chemin": r.url.path, "http": r.status_code}))
    server.set_app(app)
    try:
        page = 25 if nom == "ad59_td" else 0
        apercu = server.archive_image(EXEMPLES[nom], page=page)
        assert "erreur" not in apercu, apercu
        assert Path(apercu["chemin_absolu"]).is_file()
        zone = server.archive_image(EXEMPLES[nom], page=page, region="pct:0,0,50,50", largeur=1200)
        assert "erreur" not in zone, zone
        archive = server.piece_archiver(EXEMPLES[nom], page=page)
        assert "erreur" not in archive, archive
        dest = Path(archive["chemin_absolu"])
        assert dest.is_file() and dest.with_suffix(".md").is_file()
        avant = len(calls)
        encore = server.piece_archiver(EXEMPLES[nom], page=page)
        assert encore.get("deja_archivee"), encore
        assert len(calls) == avant, "Une répétition ne doit pas relancer le réseau"
        assert server.arbre_info()["personnes"] == 0
        if nom.startswith("ad59"):
            assert sum(c["chemin"].startswith("/images/") for c in calls) == 1
        return {"service": nom, "hote_source": urlsplit(EXEMPLES[nom]).hostname or calls[0]["hote"], "resultat": "OK",
                "mode": apercu["mode"], "dimensions_apercu": apercu["dimensions_demandees"],
                "estimation_tokens_apercu": apercu["cout_estime_tokens"],
                "dimensions_originales": archive["dimensions_originales"],
                "requêtes_http": calls, "repetition_sans_reseau": True}
    finally:
        server.set_app(None)
        app.http.client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=[*EXEMPLES, "tous"], required=True)
    args = parser.parse_args()
    selection = list(EXEMPLES) if args.service == "tous" else [args.service]
    resultats = []
    with tempfile.TemporaryDirectory(prefix="genealogiste-telechargements-") as directory:
        for nom in selection:
            try:
                resultats.append(verifier(nom, Path(directory) / nom))
            except Exception as exc:
                resultats.append({"service": nom, "resultat": "ECHEC", "detail": str(exc)})
    print(json.dumps(resultats, ensure_ascii=False, indent=2))
    return int(any(r["resultat"] != "OK" for r in resultats))


if __name__ == "__main__":
    raise SystemExit(main())
