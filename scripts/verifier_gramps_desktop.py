"""Compatibilité Gramps Desktop sans interface : export Gramps XML de Genealogiste lu par Gramps 5.2, 6.0, 6.1.

Pour chaque version déclarée dans `compatibilite-gramps.json` (`gramps_desktop`), un environnement Python isolé
est créé dans un cache (jamais dans `mcp/.venv` ni `uv.lock`) : `gramps` depuis PyPI, ou depuis les sources
Git épinglées par commit (6.1, absente de PyPI). Les arbres synthétiques du dépôt (`mcp/tests/fixtures/*.ged`)
sont exportés avec l'export actuel (`to_gramps_xml`), puis la sonde `sonde_gramps_desktop.py`, lancée dans
l'environnement isolé, les importe et les réexporte. Invariants vérifiés pour chaque cas et chaque version :

- import sans erreur ni avertissement de Gramps ;
- mêmes objets que l'export, classe par classe (personnes, familles, événements, sources, citations, lieux,
  notes, dépôts, médias, étiquettes) : mêmes nombres et mêmes handles ;
- réexport par Gramps (aller-retour) : mêmes nombres et mêmes handles.

Points d'extension (#268, #269) : ajouter un `Cas` à `CAS` (autre forme de fichier : `.gramps` gzip, `.gpkg`,
version XML cible ; `refus_attendu` pour une version qui doit refuser le fichier, ex. 1.7.2 dans Gramps 5.2), et
un contrôle à `CONTROLES` (ex. relire le réexport de Gramps avec l'import Genealogiste).

Usage (depuis la racine) : make test-gramps-desktop [GRAMPS_DESKTOP=6.0] [GI=systeme] [PYTHON=/usr/bin/python3]
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRICE = ROOT / "compatibilite-gramps.json"
SONDE = ROOT / "scripts" / "sonde_gramps_desktop.py"
FIXTURES = ROOT / "mcp" / "tests" / "fixtures"
ARBRES = ("famille.ged", "legacy551.ged", "geneweb7_gwb2ged.ged")
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "genealogiste" / "gramps-desktop"

# élément Gramps XML d'un objet primaire -> classe Gramps
ELEMENTS = {"person": "Person", "family": "Family", "event": "Event", "source": "Source", "citation": "Citation",
            "placeobj": "Place", "note": "Note", "repository": "Repository", "object": "Media", "tag": "Tag"}
CLASSES = tuple(ELEMENTS.values())


def charger_matrice(chemin: Path = MATRICE) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))


def handle_gramps(attribut: str) -> str:
    """Handle tel que Gramps le stocke : l'importeur XML retire tous les « _ » (`importxml.inaugurate`)."""
    return attribut.replace("_", "")


def inventaire_xml(chemin: Path) -> dict[str, list[str]]:
    """Handles des objets primaires d'un fichier Gramps XML (gzip ou non), par classe Gramps."""
    brut = chemin.read_bytes()
    if brut[:2] == b"\x1f\x8b":
        brut = gzip.decompress(brut)
    racine = ET.fromstring(brut)
    trouves: dict[str, list[str]] = {cls: [] for cls in CLASSES}
    for section in racine:
        for objet in section:
            nom = objet.tag.rsplit("}", 1)[-1]
            if nom in ELEMENTS and "handle" in objet.attrib:
                trouves[ELEMENTS[nom]].append(handle_gramps(objet.attrib["handle"]))
    return {cls: sorted(h) for cls, h in trouves.items()}


def comparer(attendu: dict[str, list[str]], obtenu: dict[str, list[str]], contexte: str) -> list[str]:
    ecarts = []
    for cls in CLASSES:
        a, o = set(attendu.get(cls, [])), set(obtenu.get(cls, []))
        if len(attendu.get(cls, [])) != len(obtenu.get(cls, [])) or a != o:
            ecarts.append(f"{contexte} : {cls} attendu {len(a)}, obtenu {len(o)} "
                          f"(manquants {sorted(a - o)[:3]}, en trop {sorted(o - a)[:3]})")
    return ecarts


# --- cas : forme du fichier remis à Gramps ---------------------------------------------------------------

@dataclass(frozen=True)
class Cas:
    nom: str
    description: str
    produire: Callable[[object, Path], Path]  # (Tree, dossier) -> fichier écrit
    refus_attendu: frozenset[str] = field(default_factory=frozenset)  # versions Gramps qui doivent refuser


def produire_xml_genealogiste(tree, dossier: Path) -> Path:
    from genealogiste_mcp.export.gramps_xml import to_gramps_xml

    chemin = dossier / "genealogiste.gramps"
    chemin.write_text(to_gramps_xml(tree), encoding="utf-8")
    return chemin


CAS: list[Cas] = [
    Cas("xml-genealogiste", "export actuel to_gramps_xml (Gramps XML 1.7.1, non compressé)",
        produire_xml_genealogiste),
]


@dataclass
class Resultat:
    version: str
    arbre: str
    cas: str
    ok: bool
    detail: str
    nombres: dict[str, int] = field(default_factory=dict)


# Contrôle supplémentaire sur un fichier importé : (cas, version, attendu, rapport de la sonde) -> écarts.
Controle = Callable[[Cas, str, dict[str, list[str]], dict], list[str]]


def controle_reexport(cas: Cas, version: str, attendu: dict[str, list[str]], rapport: dict) -> list[str]:
    if "reexport" not in rapport:
        return ["réexport absent"]
    return comparer(attendu, inventaire_xml(Path(rapport["reexport"])), "réexport Gramps")


CONTROLES: list[Controle] = [controle_reexport]


# --- environnements isolés ------------------------------------------------------------------------------

def _run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True, **kw)


def environnement(entree: dict, cache: Path, python: str, gi_systeme: bool) -> tuple[Path, dict[str, str]]:
    """Crée (ou réutilise) l'environnement d'une version ; renvoie l'interpréteur et les variables à ajouter."""
    version = entree["version"]
    dossier = cache / f"gramps-{version}"
    venv = dossier / "venv"
    exe = venv / "bin" / "python"
    signature = json.dumps({"entree": entree, "python": python, "gi_systeme": gi_systeme}, sort_keys=True)
    marqueur = dossier / "installe.json"
    if not (marqueur.exists() and marqueur.read_text(encoding="utf-8") == signature and exe.exists()):
        shutil.rmtree(dossier, ignore_errors=True)
        dossier.mkdir(parents=True)
        _run(["uv", "venv", "--quiet", "--python", python, *(["--system-site-packages"] if gi_systeme else []),
              str(venv)])
        if "pypi" in entree:
            _run(["uv", "pip", "install", "--quiet", "--python", str(exe), entree["pypi"]])
        else:
            depot = entree["git"]
            src = dossier / "src"
            _run(["git", "init", "--quiet", str(src)])
            _run(["git", "-C", str(src), "fetch", "--quiet", "--depth", "1", depot["depot"], depot["commit"]])
            _run(["git", "-C", str(src), "-c", "advice.detachedHead=false", "checkout", "--quiet", "FETCH_HEAD"])
            tete = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], check=True, capture_output=True,
                                  text=True).stdout.strip()
            if tete != depot["commit"]:
                raise SystemExit(f"Gramps {version} : commit {tete} au lieu de {depot['commit']}")
            if entree.get("dependances"):
                _run(["uv", "pip", "install", "--quiet", "--python", str(exe), *entree["dependances"]])
            # lancement depuis les sources sans compilation des traductions (msgfmt) : ressources = data/
            (dossier / "share").mkdir()
            (dossier / "share" / "gramps").symlink_to(src / "data", target_is_directory=True)
        marqueur.write_text(signature, encoding="utf-8")
    env: dict[str, str] = {}
    if "git" in entree:
        env = {"PYTHONPATH": str(dossier / "src"), "GRAMPS_RESOURCES": str(dossier / "share")}
    return exe, env


# --- exécution ------------------------------------------------------------------------------------------

def preparer_cas(travail: Path) -> list[tuple[str, Cas, Path, dict[str, list[str]]]]:
    """Fichiers à importer et objets attendus (handles du modèle Gramps produit par Genealogiste)."""
    from genealogiste_mcp.gedcom.mapping import read_gedcom
    from genealogiste_mcp.gramps.mapping import tree_to_gramps_stats

    lots = []
    for arbre in ARBRES:
        tree = read_gedcom((FIXTURES / arbre).read_text(encoding="utf-8"))[0]
        db, _ = tree_to_gramps_stats(tree, None, False)
        attendu = {cls: sorted(handle_gramps(h) for h in db.all(cls)) for cls in CLASSES}
        for cas in CAS:
            dossier = travail / "entrees" / cas.nom / Path(arbre).stem
            dossier.mkdir(parents=True)
            fichier = cas.produire(tree, dossier)
            cible = dossier / f"{Path(arbre).stem}{''.join(fichier.suffixes)}"
            fichier.rename(cible)
            ecarts = comparer(attendu, inventaire_xml(cible), f"export {cas.nom}")
            if ecarts:  # l'export lui-même ne contient pas le modèle : inutile d'interroger Gramps
                raise SystemExit("\n".join(ecarts))
            lots.append((arbre, cas, cible, attendu))
    return lots


def verifier_version(entree: dict, lots, travail: Path, cache: Path, python: str, gi_systeme: bool
                     ) -> list[Resultat]:
    version = entree["version"]
    print(f"\n== Gramps {version} ({entree.get('pypi') or entree['git']['tag']})", flush=True)
    exe, env_sup = environnement(entree, cache, python, gi_systeme)
    resultats = []
    for cas in CAS:
        entrees = [(arbre, f, att) for arbre, c, f, att in lots if c is cas]
        sortie = travail / f"gramps-{version}" / cas.nom
        (sortie / "reexport").mkdir(parents=True)
        rapport_json = sortie / "rapport.json"
        env = {**os.environ, **env_sup, "GRAMPSHOME": str(sortie / "home"), "LANGUAGE": "en", "LC_ALL": "C.UTF-8"}
        proc = subprocess.run([str(exe), "-P", str(SONDE), "--rapport", str(rapport_json),
                               "--reexporter", str(sortie / "reexport"), *[str(f) for _, f, _ in entrees]],
                              env=env, capture_output=True, text=True)
        if proc.returncode or not rapport_json.exists():
            detail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
            resultats += [Resultat(version, a, cas.nom, False, "sonde en échec : " + " / ".join(detail))
                          for a, _, _ in entrees]
            continue
        rapport = json.loads(rapport_json.read_text(encoding="utf-8"))
        if gi_systeme and entree.get("gi") and rapport["gi"] != "systeme":
            raise SystemExit(f"Gramps {version} : PyGObject système attendu, mode {rapport['gi']}")
        print(f"   gramps {rapport['gramps']}, XML {rapport['xml']}, gi {rapport['gi']}, "
              f"interface d'export {rapport['gui_export']}")
        if not str(rapport["gramps"]).startswith(version):
            raise SystemExit(f"Gramps {version} attendu, {rapport['gramps']} chargé")
        if rapport["xml"] != entree["xml"]:
            raise SystemExit(f"Gramps {version} : XML {rapport['xml']} au lieu de {entree['xml']}")
        for arbre, fichier, attendu in entrees:
            r = rapport["fichiers"][fichier.name]
            refus = version in cas.refus_attendu
            if refus:
                ok = not r["importe"]
                ecarts = [] if ok else ["import accepté alors qu'un refus est attendu"]
            elif not r["importe"]:
                ok, ecarts = False, r["erreurs"] or ["import refusé"]
            else:
                ecarts = r["erreurs"] + [f"avertissement : {a}" for a in r["avertissements"]]
                ecarts += comparer(attendu, r["handles"], "import")
                for controle in CONTROLES:
                    ecarts += controle(cas, version, attendu, r)
                ok = not ecarts
            nombres = {cls: len(h) for cls, h in (r.get("handles") or {}).items() if h}
            detail = ("refus attendu" if refus and ok else "") if ok else " ; ".join(ecarts)
            resultats.append(Resultat(version, arbre, cas.nom, ok, detail, nombres))
    return resultats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--version", action="append", dest="versions",
                        help="version Gramps à vérifier (répétable ; défaut : toutes celles de la matrice)")
    parser.add_argument("--python", default="3.12", help="interpréteur des environnements isolés (uv venv --python)")
    parser.add_argument("--gi", choices=("auto", "systeme"), default="auto",
                        help="systeme : venv --system-site-packages, PyGObject du système exigé pour 5.2 et 6.0")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--rapport", type=Path, help="écrit aussi le résultat en JSON")
    args = parser.parse_args(argv)

    matrice = charger_matrice()["gramps_desktop"]
    connues = [e["version"] for e in matrice]
    inconnues = set(args.versions or []) - set(connues)
    if inconnues:
        parser.error(f"versions inconnues {sorted(inconnues)} ; matrice : {connues}")
    choisies = [e for e in matrice if not args.versions or e["version"] in args.versions]
    resultats: list[Resultat] = []
    with tempfile.TemporaryDirectory(prefix="genealogiste-gramps-desktop-") as tmp:
        travail = Path(tmp)
        lots = preparer_cas(travail)
        for entree in choisies:
            resultats += verifier_version(entree, lots, travail, args.cache, args.python, args.gi == "systeme")

    print("\n| Gramps | arbre | cas | résultat | objets importés |\n|---|---|---|---|---|")
    for r in resultats:
        nombres = ", ".join(f"{cls} {n}" for cls, n in r.nombres.items())
        etat = "ok" if r.ok else "ÉCHEC"
        print(f"| {r.version} | {r.arbre} | {r.cas} | {etat}{' : ' + r.detail if r.detail else ''} | {nombres} |")
    if args.rapport:
        args.rapport.write_text(json.dumps([r.__dict__ for r in resultats], ensure_ascii=False, indent=1),
                                encoding="utf-8")
    echecs = [r for r in resultats if not r.ok]
    print(f"\n{len(resultats) - len(echecs)}/{len(resultats)} vérifications réussies")
    return 1 if echecs or not resultats else 0


if __name__ == "__main__":
    sys.exit(main())
