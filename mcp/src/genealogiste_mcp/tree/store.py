"""Stockage de l'arbre : fichier GEDCOM 7 dans un dépôt Git dédié (un commit par modification)."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from ..gedcom.mapping import read_gedcom, write_gedcom
from ..models import Tree

GITIGNORE = ".propositions/\n.env\nexports/\n*.sqlite\n"
README = """# Données généalogiques (plugin genealogiste)

- `arbre.ged` : arbre de travail, GEDCOM 7 (source de vérité). Ne pas éditer à la main pendant une session.
- `journal.jsonl` : journal de recherche (toutes les requêtes, résultats positifs et négatifs).
- `medias/` : images d'actes et documents liés.

Chaque modification de l'arbre est un commit dont le message contient la justification et les sources.
Ce dépôt contient des données personnelles : ne le publiez pas sans masquer les personnes vivantes.
"""


class GitError(RuntimeError):
    pass


class TreeStore:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.path = self.dir / "arbre.ged"

    # ------------------------------------------------------------------ git
    def _git(self, *args: str, check: bool = True) -> str:
        r = subprocess.run(["git", "-C", str(self.dir), *args], capture_output=True, text=True)
        if check and r.returncode != 0:
            raise GitError(f"git {' '.join(args)} : {r.stderr.strip() or r.stdout.strip()}")
        return r.stdout

    def ensure(self) -> None:
        """Initialise le répertoire de données et son dépôt Git si nécessaire."""
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "medias").mkdir(exist_ok=True)
        if not (self.dir / ".git").exists():
            self._git("init", "-q")
            self._git("config", "user.name", "genealogiste")
            self._git("config", "user.email", "genealogiste@localhost")
        gi = self.dir / ".gitignore"
        if not gi.exists():
            gi.write_text(GITIGNORE, encoding="utf-8")
        rd = self.dir / "README.md"
        if not rd.exists():
            rd.write_text(README, encoding="utf-8")
        if not self.path.exists():
            self.path.write_text(write_gedcom(Tree()), encoding="utf-8")
            self.commit("Initialisation de l'arbre de travail")

    def commit(self, message: str) -> str:
        self._git("add", "-A")
        status = self._git("status", "--porcelain")
        if not status.strip():
            return ""
        self._git("commit", "-q", "-m", message)
        return self._git("rev-parse", "--short", "HEAD").strip()

    def log(self, limit: int = 20, path: str | None = None) -> list[dict]:
        args = ["log", f"-n{limit}", "--date=iso", "--pretty=format:%h%x1f%ad%x1f%an%x1f%B%x1e"]
        if path:
            args += ["--", path]
        out = self._git(*args, check=False)
        entries = []
        for rec in out.split("\x1e"):
            rec = rec.strip()
            if not rec:
                continue
            h, d, a, msg = (rec.split("\x1f") + ["", "", "", ""])[:4]
            entries.append({"commit": h, "date": d, "auteur": a, "message": msg.strip()})
        return entries

    def revert(self, commit: str) -> str:
        self._git("revert", "--no-edit", commit)
        return self._git("rev-parse", "--short", "HEAD").strip()

    # ------------------------------------------------------------------ arbre
    def text(self) -> str:
        self.ensure()
        return self.path.read_text(encoding="utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.text().encode("utf-8")).hexdigest()

    def load(self) -> Tree:
        return read_gedcom(self.text())[0]

    def write(self, tree: Tree) -> str:
        text = write_gedcom(tree)
        self.path.write_text(text, encoding="utf-8")
        return text
