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

from ..fichiers import LOCK_NAME, ecrire_atomique
from ..gedcom.mapping import read_gedcom, write_gedcom
from ..models import Tree

# Toujours présents dans .gitignore, même s'il existait déjà (#48) : secrets, jetons, fichiers techniques.
GITIGNORE_REQUIS = (".propositions/", ".env", ".env.*", "*.token", "*.key", "*.pem", "exports/", "cache-images/", "*.sqlite",
                    LOCK_NAME, ".*.tmp")
GITIGNORE = "\n".join(GITIGNORE_REQUIS) + "\n"
ARBRE = "arbre.ged"
# Fichiers internes versionnés à part (jamais dans le commit d'une modification d'arbre : une annulation ne
# doit pas effacer d'entrées du journal).
INTERNES = ("journal.jsonl", "gramps-transactions.jsonl")
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
        actuel = gi.read_text(encoding="utf-8") if gi.exists() else ""
        lignes = {x.strip() for x in actuel.splitlines()}
        manquants = [x for x in GITIGNORE_REQUIS if x not in lignes]
        if manquants:
            sep = "" if not actuel or actuel.endswith("\n") else "\n"
            gi.write_text(actuel + sep + "\n".join(manquants) + "\n", encoding="utf-8")
        rd = self.dir / "README.md"
        if not rd.exists():
            rd.write_text(README, encoding="utf-8")
        if not self.path.exists():
            ecrire_atomique(self.path, write_gedcom(Tree()))
            self.commit("Initialisation de l'arbre de travail", [ARBRE, ".gitignore", "README.md"])
        elif manquants and (self.dir / ".git").exists():
            self.commit("Exclusion des secrets et fichiers techniques (.gitignore)", [".gitignore"])

    def commit(self, message: str, paths: list[str] | None = None) -> str:
        """Commit des seuls fichiers indiqués (relatifs au répertoire de données ; arbre.ged par défaut), jamais
        de ``git add -A`` : un fichier étranger (.env, document) n'est jamais embarqué (#48)."""
        paths = list(paths or [ARBRE])
        presents = [x for x in paths if (self.dir / x).exists()]
        if presents:
            self._git("add", "--", *presents)
        absents = [x for x in paths if not (self.dir / x).exists()]
        if absents:
            self._git("rm", "-q", "--cached", "--ignore-unmatch", "--", *absents)
        if not self._git("diff", "--cached", "--name-only", "--", *paths).strip():
            return ""
        self._git("commit", "-q", "-m", message, "--", *paths)
        self.push()
        return self._git("rev-parse", "--short", "HEAD").strip()

    def commit_internes(self) -> str:
        """Versionne le journal de recherche et des transactions, dans un commit à part."""
        return self.commit("Journal de recherche", [x for x in INTERNES if (self.dir / x).exists()] or [INTERNES[0]])

    def files(self, commit: str) -> list[str]:
        out = self._git("show", "--name-only", "--format=", commit, check=False)
        return [x for x in out.splitlines() if x.strip()]

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
        """Diff complet du commit : exactement ce qu'une annulation (git revert) défera (#48)."""
        return self._git("show", "--format=", commit, check=False)

    def revert(self, commit: str) -> str:
        try:
            self._git("revert", "--no-edit", commit)
        except GitError:
            self._git("revert", "--abort", check=False)
            raise
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
        ecrire_atomique(self.path, text)
        return text

    def write_text(self, text: str) -> None:
        ecrire_atomique(self.path, text)

    # ------------------------------------------------------------------ bascule vers Gramps Web
    def frozen(self) -> dict | None:
        p = self.dir / BASCULE
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def freeze(self, info: dict) -> str:
        ecrire_atomique(self.dir / BASCULE, json.dumps(info, ensure_ascii=False, indent=2))
        return self.commit("Bascule vers Gramps Web\n\n" + json.dumps(info, ensure_ascii=False, indent=2),
                           [BASCULE, ARBRE])
