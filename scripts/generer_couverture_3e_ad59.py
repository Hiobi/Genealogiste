"""Générer le référentiel du classeur 3 E des AD59 (état civil : cotes et mise en ligne) depuis son PDF (#374).

Sans réseau par défaut : le PDF public est passé en argument.

    uv --directory mcp run python -I ../scripts/generer_couverture_3e_ad59.py /chemin/classeur-3e.pdf \
        --releve 2026-11-27

``--telecharger`` est une étape séparée et explicite : contrôle de robots.txt, puis une seule requête pour le
document, écrit dans le fichier donné (qui ne doit pas exister). Le PDF est une donnée non fiable : il est lu
par pdfplumber, jamais exécuté ; lancer Python avec ``-I``. Le nom du document est millésimé : pour un nouveau
classeur, passer ``--source`` (et mettre à jour ``couverture_3e.SOURCE``).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
import urllib.robotparser
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from genealogiste_mcp import couverture_3e

AGENT = "Mozilla/5.0 (compatible; releve-referentiel-archives)"
HOTE = "archivesdepartementales.lenord.fr"
MAX_PDF = 50_000_000


def telecharger(source: str, cible: Path) -> None:
    """robots.txt puis une seule requête pour le document ; refus hors de l'hôte officiel ou si le fichier existe."""
    parts = urlsplit(source)
    if parts.scheme != "https" or parts.hostname != HOTE:
        raise SystemExit(f"Source refusée : seul https://{HOTE} est accepté.")
    if cible.exists():
        raise SystemExit(f"{cible} existe déjà : le supprimer ou choisir un autre nom.")
    requete = urllib.request.Request(f"https://{HOTE}/robots.txt", headers={"User-Agent": AGENT})
    with urllib.request.urlopen(requete, timeout=30) as reponse:  # noqa: S310 (https vérifié ci-dessus)
        robots = urllib.robotparser.RobotFileParser()
        robots.parse(reponse.read(1_000_000).decode("utf-8", "replace").splitlines())
    if not robots.can_fetch(AGENT, source):
        raise SystemExit("robots.txt interdit ce document : téléchargement abandonné.")
    requete = urllib.request.Request(source, headers={"User-Agent": AGENT, "Accept": "application/pdf"})
    with urllib.request.urlopen(requete, timeout=120) as reponse:  # noqa: S310
        if urlsplit(reponse.geturl()).hostname != HOTE:
            raise SystemExit("Redirection hors du service : téléchargement abandonné.")
        contenu = reponse.read(MAX_PDF + 1)
    if len(contenu) > MAX_PDF or not contenu.startswith(b"%PDF-"):
        raise SystemExit("La réponse n'est pas un PDF de taille attendue (défi, page HTML ou document changé).")
    cible.write_bytes(contenu)


def lignes_du_pdf(pdf: Path) -> list[list]:
    """Lignes du tableau, page par page (pdfplumber). Une page sans tableau est une erreur, pas un silence."""
    import pdfplumber

    lignes: list[list] = []
    with pdfplumber.open(pdf) as document:
        for numero, page in enumerate(document.pages, 1):
            tableaux = page.extract_tables()
            if not tableaux:
                raise couverture_3e.ClasseurError(f"Page {numero} sans tableau : format du classeur non reconnu.")
            for tableau in tableaux:
                lignes.extend(tableau)
    return lignes


def generer(pdf: Path, releve_le: str, source: str = couverture_3e.SOURCE) -> dict:
    empreinte = hashlib.sha256(pdf.read_bytes()).hexdigest()
    return couverture_3e.analyser(lignes_du_pdf(pdf), source, empreinte, releve_le)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path, help="PDF du classeur (lu, ou écrit avec --telecharger)")
    parser.add_argument("--releve", default="", help="date du relevé AAAA-MM-JJ (défaut : aujourd'hui)")
    parser.add_argument("--source", default=couverture_3e.SOURCE, help="URL publique du document")
    parser.add_argument("--sortie", type=Path, default=couverture_3e.PATH)
    parser.add_argument("--telecharger", action="store_true",
                        help="télécharger d'abord le PDF depuis --source (robots.txt contrôlé, une requête)")
    parser.add_argument("--check", action="store_true", help="comparer au référentiel existant sans l'écrire")
    args = parser.parse_args(argv)
    try:
        releve = date.fromisoformat(args.releve).isoformat() if args.releve else date.today().isoformat()
    except ValueError:
        parser.error("--releve : date AAAA-MM-JJ attendue")
    if args.telecharger:
        telecharger(args.source, args.pdf)
    try:
        referentiel = generer(args.pdf, releve, args.source)
    except couverture_3e.ClasseurError as exc:
        print(f"Référentiel refusé : {exc}", file=sys.stderr)
        return 1
    contenu = couverture_3e.serialiser(referentiel)
    if args.check:
        if not args.sortie.exists() or args.sortie.read_text(encoding="utf-8") != contenu:
            print("Référentiel différent du PDF : relancer scripts/generer_couverture_3e_ad59.py")
            return 1
        return 0
    args.sortie.write_text(contenu, encoding="utf-8")
    print(f"{args.sortie} : {referentiel['lignes']} lignes, {referentiel['volumes']} volumes, "
          f"{len(referentiel['communes'])} communes, {len(referentiel['lignes_rejetees'])} rejetées, "
          f"{referentiel['bornes_incompletes']} à bornes incomplètes, {referentiel['doublons']} doublons.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
