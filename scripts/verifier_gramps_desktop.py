"""Compatibilité Gramps Desktop sans interface : export Gramps XML de Genealogiste lu par Gramps 5.2, 6.0, 6.1.

Pour chaque version déclarée dans `compatibilite-gramps.json` (`gramps_desktop`), un environnement Python isolé
est créé dans un cache (jamais dans `mcp/.venv` ni `uv.lock`) : `gramps` depuis PyPI, ou depuis les sources
Git épinglées par commit (6.1, absente de PyPI). Les arbres synthétiques du dépôt (`mcp/tests/fixtures/*.ged`)
sont exportés sous chaque forme de `CAS` (Gramps XML 1.7.1 et 1.7.2, `.gramps` gzip, paquet `.gpkg` avec
médias), puis la sonde `sonde_gramps_desktop.py`, lancée dans l'environnement isolé, les importe et les
réexporte. Invariants vérifiés pour chaque cas et chaque version :

- fichier valide au DTD et au RNG livrés avec la bibliothèque (`data/grampsxml.dtd`, `.rng`), étiquette du
  fichier ramenée à celle du schéma : le contenu écrit sous l'étiquette 1.7.1 suit déjà 1.7.2, comme celui de
  Gramps 5.2 (le schéma 1.7.1 strict est vérifié par les tests unitaires) ;
- refus par les versions de `refus_attendu` (1.7.2 dans Gramps 5.2) ;
- import sans erreur ni avertissement de Gramps (sauf ceux que le cas admet : chemin de base des médias d'un
  `.gpkg`) ;
- médias : chaque fichier empaqueté est retrouvé par Gramps après import ;
- mêmes objets que l'export, classe par classe (personnes, familles, événements, sources, citations, lieux,
  notes, dépôts, médias, étiquettes) : mêmes nombres et mêmes handles ;
- réexport par Gramps (aller-retour) : mêmes nombres et mêmes handles.

Points d'extension : ajouter un `Cas` à `CAS` (autre forme de fichier ; `refus_attendu` pour une version qui
doit refuser le fichier), et un contrôle à `CONTROLES` (ex. relire le réexport de Gramps avec l'import
Genealogiste, #269).

Usage (depuis la racine) : make test-gramps-desktop [GRAMPS_DESKTOP=6.0] [GI=systeme] [PYTHON=/usr/bin/python3]
"""

from __future__ import annotations

import argparse
import copy
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
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


def lire_xml(chemin: Path) -> bytes:
    """Contenu XML d'un fichier remis à Gramps : `.gramps` (gzip ou non) ou `data.gramps` d'un paquet `.gpkg`
    (reconnu au contenu : le réexport de Gramps garde le nom du fichier importé)."""
    brut = chemin.read_bytes()
    if brut[:2] == b"\x1f\x8b":
        brut = gzip.decompress(brut)
    if tarfile.is_tarfile(io.BytesIO(brut)):
        with tarfile.open(fileobj=io.BytesIO(brut)) as tar:
            brut = tar.extractfile("data.gramps").read()
        brut = gzip.decompress(brut) if brut[:2] == b"\x1f\x8b" else brut
    return brut


def valider_schemas(brut: bytes, schemas: dict[str, str]) -> list[str]:
    """Validation DTD puis RNG contre les schémas d'une bibliothèque Gramps, l'étiquette du fichier (espace de
    noms) ramenée à celle du schéma. lxml : groupe dev de mcp/."""
    from lxml import etree

    dtd_brut = Path(schemas["dtd"]).read_bytes()
    cible = re.search(rb'xmlns CDATA #FIXED "(http://gramps-project.org/xml/[0-9.]+/)"', dtd_brut).group(1)
    brut = re.sub(rb'xmlns="http://gramps-project.org/xml/[0-9.]+/"', b'xmlns="' + cible + b'"', brut, count=1)
    doc = etree.fromstring(brut, etree.XMLParser(load_dtd=False, resolve_entities=False, no_network=True))
    ecarts = []
    dtd = etree.DTD(io.BytesIO(dtd_brut))
    if not dtd.validate(doc):
        ecarts += [f"DTD {cible.decode()} l.{e.line} : {e.message}" for e in list(dtd.error_log)[:5]]
    rng = etree.RelaxNG(etree.parse(schemas["rng"]))
    if not rng.validate(doc):
        ecarts += [f"RNG l.{e.line} : {e.message}" for e in list(rng.error_log)[:3]]
    return ecarts


def inventaire_xml(chemin: Path) -> dict[str, list[str]]:
    """Handles des objets primaires d'un fichier Gramps XML (gzip ou non, ou paquet .gpkg), par classe Gramps."""
    racine = ET.fromstring(lire_xml(chemin))
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
    enrichir: Callable[[object, Path], object] | None = None  # (Tree, dossier) -> arbre exporté (copie)
    avertissements_admis: tuple[str, ...] = ()  # débuts d'avertissements Gramps attendus pour ce cas


def produire_xml(version_xml: str, compresse: bool = False) -> Callable[[object, Path], Path]:
    def produire(tree, dossier: Path) -> Path:
        from genealogiste_mcp.export.gramps_xml import compresser, to_gramps_xml

        chemin = dossier / "genealogiste.gramps"
        xml = to_gramps_xml(tree, version_xml=version_xml)
        if compresse:
            chemin.write_bytes(compresser(xml))
        else:
            chemin.write_text(xml, encoding="utf-8")
        return chemin
    return produire


MEDIA_TEST = "medias/acte de décès é.jpg"


def avec_media(tree, dossier: Path):
    """Copie de l'arbre avec un média local (nom accentué, sous-dossier) rattaché à la première personne."""
    from genealogiste_mcp.models import Media

    tree = copy.deepcopy(tree)
    (dossier / "racine" / "medias").mkdir(parents=True)
    (dossier / "racine" / MEDIA_TEST).write_bytes(b"\xff\xd8\xff\xe0 image fictive")
    mid = "O" + str(len(tree.medias) + 900)
    tree.medias[mid] = Media(id=mid, fichier=MEDIA_TEST, titre="Acte fictif")
    tree.personnes[sorted(tree.personnes)[0]].medias.append(mid)
    return tree


def produire_gpkg(tree, dossier: Path) -> Path:
    from genealogiste_mcp.export.gramps_xml import paquet_gpkg
    from genealogiste_mcp.gramps.mapping import tree_to_gramps_stats

    db, _ = tree_to_gramps_stats(tree, None, False)
    brut, bilan = paquet_gpkg(db, (dossier / "racine",))
    if bilan["manquants"]:
        raise SystemExit(f"paquet incomplet : {bilan['manquants']}")
    chemin = dossier / "genealogiste.gpkg"
    chemin.write_bytes(brut)
    return chemin


CAS: list[Cas] = [
    Cas("xml-1.7.1", "Gramps XML 1.7.1 non compressé (défaut d'arbre_exporter, format gramps)", produire_xml("1.7.1")),
    Cas("xml-1.7.2", "Gramps XML 1.7.2 non compressé (version_xml=1.7.2) : refusé par Gramps 5.2",
        produire_xml("1.7.2"), refus_attendu=frozenset({"5.2"})),
    Cas("gramps-gzip", "Gramps XML 1.7.1 compressé gzip (compresse=True)", produire_xml("1.7.1", True)),
    Cas("gpkg", "paquet .gpkg : data.gramps (1.7.1, gzip) + un média local", produire_gpkg, enrichir=avec_media,
        avertissements_admis=("Base path for relative media set",)),
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


def controle_medias(cas: Cas, version: str, attendu: dict[str, list[str]], rapport: dict) -> list[str]:
    """Médias d'un paquet : chaque fichier empaqueté est retrouvé par Gramps à son chemin relatif."""
    if cas.enrichir is None:
        return []
    trouves = {m["chemin"] for m in rapport.get("medias", []) if m["fichier"]}
    return [] if MEDIA_TEST in trouves else [f"média {MEDIA_TEST} introuvable après import : {rapport.get('medias')}"]


MODELE = "_objets"  # clé de `attendu` : objets Gramps JSON du modèle exporté (comparés champ par champ)

# Écarts propres à Gramps, sans perte de contenu exporté : identifiants renumérotés selon les préférences de
# l'arbre cible (I7 -> I0007), date de modification 0 remplacée par celle du fichier, champs calculés à l'import
# (somme de contrôle, valeur de tri, texte d'une date non textuelle), champs JSON hors XML ou propres à une
# version (vignette, complete, familysearch_sync de 6.1).
IGNORES = {"gramps_id", "thumb", "complete", "familysearch_sync", "sortval"}


def _normaliser(o, cls: str = ""):
    if isinstance(o, dict):
        c = o.get("_class", cls)
        out = {}
        for k, v in o.items():
            if k in IGNORES or (c == "Date" and k == "format") or (c == "Date" and k == "text"
                                                                  and o.get("modifier") != 6):
                continue
            out[k] = _normaliser(v, c)
        return out
    if isinstance(o, (list, tuple)):
        return [_normaliser(x, cls) for x in o]
    return o


def _ecarts(a, b, chemin: str):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:  # clés de l'objet exporté ; celles que Gramps ajoute sont sans objet
            if k not in b:
                yield f"{chemin}.{k} absent après import"
            elif not (k in ("change", "checksum") and not a[k]):
                yield from _ecarts(a[k], b[k], f"{chemin}.{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            yield from _ecarts(x, y, f"{chemin}[{i}]")
    elif a != b:
        yield f"{chemin} : exporté {a!r}, importé {b!r}"


def controle_champs(cas: Cas, version: str, attendu: dict, rapport: dict) -> list[str]:
    """Gramps ≥ 6.0 : chaque objet importé est identique, champ par champ, à l'objet Gramps exporté."""
    if "objets" not in rapport:
        return []  # Gramps 5.2 : pas de format JSON
    importes = {o["handle"]: o for o in rapport["objets"]}
    ecarts = []
    for o in attendu.get(MODELE, []):
        h = handle_gramps(o["handle"])
        if h in importes:
            ecarts += list(_ecarts(_normaliser({**o, "handle": h}), _normaliser(importes[h]), f"{o['_class']}:{h}"))
    return ecarts[:10]


CONTROLES: list[Controle] = [controle_reexport, controle_medias, controle_champs]


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
        origine = read_gedcom((FIXTURES / arbre).read_text(encoding="utf-8"))[0]
        for cas in CAS:
            dossier = travail / "entrees" / cas.nom / Path(arbre).stem
            dossier.mkdir(parents=True)
            tree = cas.enrichir(origine, dossier) if cas.enrichir else origine
            db, _ = tree_to_gramps_stats(tree, None, False)
            attendu = {cls: sorted(handle_gramps(h) for h in db.all(cls)) for cls in CLASSES}
            attendu[MODELE] = [o for cls in CLASSES for o in db.all(cls).values()]  # objets JSON exportés
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
        maison = sortie / "home"  # import .gpkg : médias extraits sous le dossier d'images de l'utilisateur
        (maison / "Pictures").mkdir(parents=True)
        env = {**os.environ, **env_sup, "GRAMPSHOME": str(maison), "HOME": str(maison),
               "XDG_PICTURES_DIR": str(maison), "XDG_CONFIG_HOME": str(maison / ".config"),
               "XDG_DATA_HOME": str(maison / ".local" / "share"), "LANGUAGE": "en", "LC_ALL": "C.UTF-8"}
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
            schema = valider_schemas(lire_xml(fichier), rapport["schemas"])
            if refus:
                ecarts = schema + ([] if not r["importe"] else ["import accepté alors qu'un refus est attendu"])
                ecarts += [] if "older version" in " ".join(r["erreurs"]) else [f"refus inattendu : {r['erreurs']}"]
                ok = not ecarts
            elif not r["importe"]:
                ok, ecarts = False, r["erreurs"] or ["import refusé"]
            else:
                ecarts = schema + r["erreurs"] + [f"avertissement : {a}" for a in r["avertissements"]
                                                  if not a.startswith(cas.avertissements_admis or ("\0",))]
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
