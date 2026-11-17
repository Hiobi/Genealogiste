"""Sauvegarde et restauration des données (#152) : `make sauvegarde` / `make restauration`.

L'archive (tar.gz, droits 600) contient le répertoire de données complet, historique Git compris, et les
médias et notes configurés hors de ce répertoire. Elle exclut ce qui se reconstruit (caches, exports,
journaux d'exploitation, propositions temporaires) et les secrets (.env, clés), à conserver séparément et
chiffrés. La restauration ne se fait que dans un dossier vide, après contrôle de chaque chemin, puis vérifie
l'historique Git et la lecture de l'arbre. Une sauvegarde contient des données de personnes vivantes : à
chiffrer, jamais dans un dépôt public."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import os
import sys
import tarfile
import time
from pathlib import Path, PurePosixPath

from .config import load_config
from .fichiers import verrou

EXCLUS = (".env", ".env.*", "*.token", "*.key", "*.pem", "*.sqlite", "*.sqlite-wal", "*.sqlite-shm", ".*.lock",
          ".*.tmp", ".genealogiste.lock")
DOSSIERS_EXCLUS = ("cache-images", "cache-pdf", "exports", "logs", ".propositions")
# File de propositions durable (#154) : conservée, contrairement aux jetons d'une heure de .propositions/.
CONSERVES = (PurePosixPath(".propositions/file"),)


class SauvegardeError(RuntimeError):
    pass


def _exclu(rel: PurePosixPath) -> bool:
    if any(rel == c or c in rel.parents for c in CONSERVES):
        return any(fnmatch.fnmatch(rel.name, m) for m in EXCLUS)
    if rel.parts and rel.parts[0] in DOSSIERS_EXCLUS:
        return True
    return any(fnmatch.fnmatch(rel.name, m) for m in EXCLUS)


def _ajouter(tar: tarfile.TarFile, racine: Path, prefixe: str, exclure: bool) -> int:
    n = 0
    for chemin in sorted(racine.rglob("*")):
        rel = PurePosixPath(chemin.relative_to(racine).as_posix())
        if chemin.is_symlink() or (exclure and _exclu(rel)) or not chemin.is_file():
            continue
        tar.add(chemin, arcname=f"{prefixe}/{rel}", recursive=False)
        n += 1
    return n


def _hors(chemin: Path | None, data_dir: Path) -> bool:
    return bool(chemin) and chemin.exists() and not chemin.resolve().is_relative_to(data_dir.resolve())


def sauvegarder(config, sortie: Path, medias: bool = True, notes: bool = True) -> Path:
    from .diagnostic import version_serveur
    from .tree.store import TreeStore

    data_dir = Path(config.data_dir)
    if not (data_dir / "arbre.ged").exists() and not (data_dir / ".git").exists():
        raise SauvegardeError(f"Aucune donnée à sauvegarder dans {data_dir} (GENEALOGISTE_DATA_DIR ?).")
    sortie = Path(sortie).expanduser()
    sortie.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = sortie / f"genealogiste-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
    manifeste = {"version": version_serveur(), "date": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                 "backend": config.backend, "contenu": {}}
    fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with verrou(data_dir), os.fdopen(fd, "wb") as brut, tarfile.open(fileobj=brut, mode="w:gz") as tar:
        arbre = data_dir / "arbre.ged"
        manifeste["arbre_sha256"] = hashlib.sha256(arbre.read_bytes()).hexdigest() if arbre.exists() else ""
        log = TreeStore(data_dir).log(1) if (data_dir / ".git").exists() else []
        manifeste["git_head"] = log[0]["commit"] if log else ""
        manifeste["contenu"]["donnees"] = _ajouter(tar, data_dir, "donnees", exclure=True)
        if medias and _hors(getattr(config, "media_dir", None), data_dir):
            manifeste["contenu"]["medias"] = _ajouter(tar, Path(config.media_dir), "medias", exclure=False)
        if notes and _hors(getattr(config, "notes_dir", None), data_dir):
            manifeste["contenu"]["notes"] = _ajouter(tar, Path(config.notes_dir), "notes", exclure=False)
        corps = json.dumps(manifeste, ensure_ascii=False, indent=2).encode("utf-8")
        info = tarfile.TarInfo("MANIFESTE.json")
        info.size, info.mtime, info.mode = len(corps), int(time.time()), 0o600
        tar.addfile(info, io.BytesIO(corps))
    return archive


def _controler(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    membres = tar.getmembers()
    for m in membres:
        p = PurePosixPath(m.name)
        if p.is_absolute() or ".." in p.parts or not p.parts:
            raise SauvegardeError(f"Archive refusée : chemin dangereux {m.name!r}.")
        if not (m.isfile() or m.isdir()):
            raise SauvegardeError(f"Archive refusée : {m.name!r} n'est ni un fichier ni un dossier (lien ?).")
        if p.parts[0] not in ("donnees", "medias", "notes", "MANIFESTE.json"):
            raise SauvegardeError(f"Archive refusée : chemin inattendu {m.name!r}.")
    if "MANIFESTE.json" not in {m.name for m in membres}:
        raise SauvegardeError("Archive refusée : MANIFESTE.json absent (pas une sauvegarde Genealogiste).")
    return membres


def restaurer(archive: Path, vers: Path) -> dict:
    from .gedcom.mapping import read_gedcom
    from .tree.store import git_non_interactif

    archive, vers = Path(archive).expanduser(), Path(vers).expanduser()
    if vers.exists() and any(vers.iterdir()):
        raise SauvegardeError(f"{vers} n'est pas vide : restaurer dans un dossier vide, jamais par-dessus "
                              "des données existantes.")
    with tarfile.open(archive, "r:gz") as tar:
        membres = _controler(tar)
        vers.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Chemins déjà contrôlés ; le filtre « data » de Python (3.11.4+) ajoute une seconde barrière.
        extra = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(vers, members=membres, **extra)  # noqa: S202 — membres contrôlés par _controler
    manifeste = json.loads((vers / "MANIFESTE.json").read_text(encoding="utf-8"))
    donnees = vers / "donnees"
    verifs: dict = {}
    arbre = donnees / "arbre.ged"
    personnes = 0
    if arbre.exists():
        verifs["arbre_sha256_conforme"] = hashlib.sha256(arbre.read_bytes()).hexdigest() == manifeste.get(
            "arbre_sha256")
        try:
            personnes = len(read_gedcom(arbre.read_text(encoding="utf-8"))[0].personnes)
            verifs["arbre_lisible"] = True
        except Exception as exc:  # noqa: BLE001
            verifs["arbre_lisible"] = False
            verifs["arbre_erreur"] = str(exc)
    if (donnees / ".git").exists():
        r = git_non_interactif(["-C", str(donnees), "fsck", "--no-progress"], 300)
        verifs["git_fsck"] = "ok" if r.returncode == 0 else r.stderr.strip()[:300]
    return {"restaure_dans": str(vers), "manifeste": manifeste, "personnes": personnes, "verifications": verifs,
            "suite": f"Contrôler dans une instance isolée : GENEALOGISTE_DATA_DIR={donnees}, sans dépôt distant "
                     "ni identifiants (wiki Sauvegardes)."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m genealogiste_mcp.sauvegarde", description=__doc__.split("\n")[0])
    sous = parser.add_subparsers(dest="action", required=True)
    s = sous.add_parser("sauvegarder", help="Archive datée (tar.gz, droits 600)")
    s.add_argument("--sortie", required=True, type=Path)
    s.add_argument("--sans-medias", action="store_true")
    s.add_argument("--sans-notes", action="store_true")
    r = sous.add_parser("restaurer", help="Restauration dans un dossier vide, avec vérifications")
    r.add_argument("archive", type=Path)
    r.add_argument("--vers", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "sauvegarder":
            chemin = sauvegarder(load_config(), args.sortie, not args.sans_medias, not args.sans_notes)
            print(json.dumps({"archive": str(chemin), "taille_octets": chemin.stat().st_size}, ensure_ascii=False))
        else:
            print(json.dumps(restaurer(args.archive, args.vers), ensure_ascii=False, indent=2))
    except (SauvegardeError, OSError, tarfile.TarError) as exc:
        print(f"genealogiste : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
