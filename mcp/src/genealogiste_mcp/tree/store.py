"""Stockage de l'arbre : fichier GEDCOM 7 dans un dépôt Git dédié (un commit par modification).

Le dépôt est local par défaut ; un dépôt distant (GENEALOGISTE_GIT_REMOTE) est optionnel : il doit être
privé (données de personnes vivantes) et ne peut pas être le dépôt du plugin.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from ..gedcom.mapping import read_gedcom, write_gedcom
from ..models import Tree

GITIGNORE = ".propositions/\n.env\nexports/\n*.sqlite\n"
README = """# Données généalogiques (plugin genealogiste)

- `arbre.ged` : arbre de travail, GEDCOM 7 (source de vérité en mode fichier ; miroir de Gramps Web en mode
  gramps si GENEALOGISTE_GIT_MIRROR=true). Ne pas éditer à la main pendant une session.
- `journal.jsonl` : journal de recherche (toutes les requêtes, résultats positifs et négatifs).
- `gramps-transactions.jsonl` : transactions écrites dans Gramps Web (mode gramps, pour l'annulation).
- `medias/` : images d'actes et documents liés.

Chaque modification de l'arbre est un commit dont le message contient la justification et les sources.
Ce dépôt contient des données personnelles : ne le publiez pas sans masquer les personnes vivantes.
"""
# Le dépôt du plugin ne doit jamais recevoir de données d'arbre
PLUGIN_REPOS = ("github.com/hiobi/sosa",)
BASCULE = "BASCULE.json"


class GitError(RuntimeError):
    pass


def remote_problem(url: str) -> str:
    """Motif de refus d'un dépôt distant, ou ""."""
    if not url:
        return ""
    norm = re.sub(r"^(https?://|ssh://|git@)", "", url.strip().lower()).replace(":", "/").removesuffix(".git")
    norm = re.sub(r"^[^@/]+@", "", norm).rstrip("/")
    if any(norm.endswith(r) or norm == r for r in PLUGIN_REPOS):
        return "GENEALOGISTE_GIT_REMOTE pointe vers le dépôt du plugin : refusé (aucune donnée d'arbre dans ce dépôt)."
    return ""


class TreeStore:
    def __init__(self, data_dir: Path, remote: str = ""):
        self.dir = Path(data_dir)
        self.path = self.dir / "arbre.ged"
        self.remote = remote
        self.last_push = ""

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
        self.push()
        return self._git("rev-parse", "--short", "HEAD").strip()

    def push(self) -> str:
        """Pousse vers le dépôt distant optionnel ; un échec n'empêche jamais l'écriture locale."""
        if not self.remote:
            return ""
        problem = remote_problem(self.remote)
        if problem:
            self.last_push = problem
            return problem
        r = subprocess.run(["git", "-C", str(self.dir), "push", "--quiet", self.remote, "HEAD"],
                           capture_output=True, text=True)
        self.last_push = "ok" if r.returncode == 0 else f"échec du push : {r.stderr.strip()[:200]}"
        return self.last_push

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

    def show(self, commit: str) -> str:
        return self._git("show", "--format=", commit, "--", "arbre.ged", check=False)

    def revert(self, commit: str) -> str:
        self._git("revert", "--no-edit", commit)
        self.push()
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

    # ------------------------------------------------------------------ bascule vers Gramps Web
    def frozen(self) -> dict | None:
        p = self.dir / BASCULE
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def freeze(self, info: dict) -> str:
        (self.dir / BASCULE).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.commit("Bascule vers Gramps Web\n\n" + json.dumps(info, ensure_ascii=False, indent=2))
