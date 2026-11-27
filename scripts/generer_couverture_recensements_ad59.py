"""Générer le référentiel des recensements de population des AD59 (cotes et mode d'accès) depuis son PDF (#375).

Sans réseau par défaut : le PDF public « Recensements de population, État de la collection » est passé en argument.

    uv --directory mcp run python -I ../scripts/generer_couverture_recensements_ad59.py /chemin/etat.pdf \
        --releve 2026-11-27

``--telecharger`` est une étape séparée et explicite : contrôle de robots.txt, puis une seule requête pour le
document, écrit dans le fichier donné (qui ne doit pas exister). Le PDF est une donnée non fiable : il est lu
par pdfplumber, jamais exécuté ; lancer Python avec ``-I``. L'adresse du média porte un UUID qui peut changer :
la reprendre sur la notice (``couverture_recensements.SOURCE``) et la passer avec ``--document``.
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

from genealogiste_mcp import couverture_recensements as recensements

AGENT = "Mozilla/5.0 (compatible; releve-referentiel-archives)"
HOTE = "archivesdepartementales.lenord.fr"
MAX_PDF = 50_000_000


def telecharger(document: str, cible: Path) -> None:
    """robots.txt puis une seule requête pour le document ; refus hors de l'hôte officiel ou si le fichier existe."""
    parts = urlsplit(document)
    if parts.scheme != "https" or parts.hostname != HOTE:
        raise SystemExit(f"Source refusée : seul https://{HOTE} est accepté.")
    if cible.exists():
        raise SystemExit(f"{cible} existe déjà : le supprimer ou choisir un autre nom.")
    requete = urllib.request.Request(f"https://{HOTE}/robots.txt", headers={"User-Agent": AGENT})
    with urllib.request.urlopen(requete, timeout=30) as reponse:  # noqa: S310 (https vérifié ci-dessus)
        robots = urllib.robotparser.RobotFileParser()
        robots.parse(reponse.read(1_000_000).decode("utf-8", "replace").splitlines())
    if not robots.can_fetch(AGENT, document):
        raise SystemExit("robots.txt interdit ce document : téléchargement abandonné.")
    requete = urllib.request.Request(document, headers={"User-Agent": AGENT, "Accept": "application/pdf"})
    with urllib.request.urlopen(requete, timeout=120) as reponse:  # noqa: S310
        if urlsplit(reponse.geturl()).hostname != HOTE:
            raise SystemExit("Redirection hors du service : téléchargement abandonné.")
        contenu = reponse.read(MAX_PDF + 1)
    if len(contenu) > MAX_PDF or not contenu.startswith(b"%PDF-"):
        raise SystemExit("La réponse n'est pas un PDF de taille attendue (défi, page HTML ou document changé).")
    cible.write_bytes(contenu)


def _frontiere(mots: list[dict]) -> float:
    """Abscisse séparant « Mis en ligne » de « Salle de lecture », lue sur la ligne d'en-tête de la première page."""
    for salle in (m for m in mots if m["text"] == "Salle"):
        ligne = [m for m in mots if abs(m["top"] - salle["top"]) < 3 and m["x1"] <= salle["x0"]]
        if ligne and [m["text"] for m in ligne][-3:] == ["Mis", "en", "ligne"]:
            return (ligne[-1]["x1"] + salle["x0"]) / 2
    raise recensements.EtatCollectionError("En-tête « Mis en ligne / Salle de lecture » introuvable sur la première "
                                           "page : colonnes d'accès non identifiables.")


def lignes_du_pdf(pdf: Path) -> list[list]:
    """Lignes du tableau, page par page (pdfplumber ``extract_tables``). Une page sans tableau est une erreur, pas
    un silence. Le mode d'accès ne tenant qu'à la position de la croix, chaque page est recoupée avec les mots
    et leurs coordonnées : autant de croix de part et d'autre de la frontière des deux colonnes que de lignes
    « en ligne » et « salle de lecture » dans le tableau, sinon l'extraction est ambiguë et refusée."""
    import pdfplumber

    lignes: list[list] = []
    with pdfplumber.open(pdf) as document:
        frontiere = None
        for numero, page in enumerate(document.pages, 1):
            tableaux = page.extract_tables()
            if not tableaux:
                raise recensements.EtatCollectionError(f"Page {numero} sans tableau : format de l'état de la "
                                                       "collection non reconnu.")
            mots = page.extract_words()
            if frontiere is None:
                frontiere = _frontiere(mots)
            page_lignes = [ligne for tableau in tableaux for ligne in tableau]
            croix = [(m["x0"] + m["x1"]) / 2 for m in mots if m["text"].upper() == "X"]
            positions = (sum(x < frontiere for x in croix), sum(x > frontiere for x in croix))
            cellules = tuple(sum(len(ligne) == 5 and str(ligne[i] or "").strip().upper() == "X"
                                 for ligne in page_lignes) for i in (3, 4))
            if positions != cellules:
                raise recensements.EtatCollectionError(
                    f"Page {numero} : {cellules[0]} + {cellules[1]} croix dans le tableau, {positions[0]} + "
                    f"{positions[1]} d'après leur position : colonne d'accès ambiguë, référentiel refusé.")
            lignes.extend(page_lignes)
    return lignes


def generer(pdf: Path, releve_le: str, source: str = recensements.SOURCE,
            document: str = recensements.DOCUMENT) -> dict:
    empreinte = hashlib.sha256(pdf.read_bytes()).hexdigest()
    return recensements.analyser(lignes_du_pdf(pdf), source, empreinte, releve_le, document)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path, help="PDF de l'état de la collection (lu, ou écrit avec --telecharger)")
    parser.add_argument("--releve", default="", help="date du relevé AAAA-MM-JJ (défaut : aujourd'hui)")
    parser.add_argument("--source", default=recensements.SOURCE, help="URL publique de la notice du document")
    parser.add_argument("--document", default=recensements.DOCUMENT, help="URL publique du PDF (média)")
    parser.add_argument("--sortie", type=Path, default=recensements.PATH)
    parser.add_argument("--telecharger", action="store_true",
                        help="télécharger d'abord le PDF depuis --document (robots.txt contrôlé, une requête)")
    parser.add_argument("--check", action="store_true", help="comparer au référentiel existant sans l'écrire")
    args = parser.parse_args(argv)
    try:
        releve = date.fromisoformat(args.releve).isoformat() if args.releve else date.today().isoformat()
    except ValueError:
        parser.error("--releve : date AAAA-MM-JJ attendue")
    if args.telecharger:
        telecharger(args.document, args.pdf)
    try:
        referentiel = generer(args.pdf, releve, args.source, args.document)
    except recensements.EtatCollectionError as exc:
        print(f"Référentiel refusé : {exc}", file=sys.stderr)
        return 1
    contenu = recensements.serialiser(referentiel)
    if args.check:
        if not args.sortie.exists() or args.sortie.read_text(encoding="utf-8") != contenu:
            print("Référentiel différent du PDF : relancer scripts/generer_couverture_recensements_ad59.py")
            return 1
        return 0
    args.sortie.write_text(contenu, encoding="utf-8")
    print(f"{args.sortie} : {referentiel['lignes']} lignes, {referentiel['volumes']} volumes, "
          f"{len(referentiel['communes'])} libellés de commune, {referentiel['en_ligne']} en ligne, "
          f"{referentiel['salle_de_lecture']} en salle de lecture, {len(referentiel['lignes_rejetees'])} rejetées, "
          f"{referentiel['annees_illisibles']} à millésime illisible, {referentiel['doublons']} doublons.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
