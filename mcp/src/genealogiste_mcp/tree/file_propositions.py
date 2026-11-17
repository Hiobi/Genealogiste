"""File de propositions durable (#154) : validation différée d'opérations sur l'arbre.

Une entrée range les opérations (pas le diff), leur titre, la justification, les sources et pièces à l'appui,
les personnes visées et l'enquête d'origine. Elle survit à l'expiration des jetons (1 h) : la reprise rejoue les
opérations sur l'arbre courant (diff frais, jeton neuf) ; l'écriture reste ``arbre_appliquer`` après accord.

Stockage : un fichier JSON lisible par entrée dans ``<données>/.propositions/file/`` (hors Git, comme les
jetons), écrit atomiquement sous verrou. Rien n'est envoyé à l'extérieur.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

from ..fichiers import ecrire_atomique, verrou

EN_ATTENTE, A_REVOIR, APPLIQUEE, ABANDONNEE = "en_attente", "a_revoir", "appliquee", "abandonnee"
STATUTS = (EN_ATTENTE, A_REVOIR, APPLIQUEE, ABANDONNEE)
OUVERTS = (EN_ATTENTE, A_REVOIR)
_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_VERROU = ".file.lock"


class FileError(RuntimeError):
    pass


def _maintenant() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class FilePropositions:
    def __init__(self, directory: Path):
        self.dir = Path(directory)

    def _path(self, ident: str) -> Path:
        if not isinstance(ident, str) or not _ID.match(ident):
            raise FileError(f"Identifiant de proposition invalide : {ident!r}")
        return self.dir / f"{ident}.json"

    def _ecrire(self, entree: dict) -> None:
        ecrire_atomique(self._path(entree["id"]), json.dumps(entree, ensure_ascii=False, indent=2) + "\n")

    def deposer(self, contenu: dict) -> dict:
        ns = time.time_ns()  # microsecondes dans l'id : l'ordre de dépôt reste l'ordre lexical
        ident = (time.strftime("%Y%m%d-%H%M%S-", time.localtime(ns / 1e9)) + f"{ns % 10**9 // 1000:06d}-"
                 + secrets.token_hex(2))
        date = _maintenant()
        entree = {"id": ident, "statut": EN_ATTENTE, "raison": "", "depose": date, **contenu,
                  "jeton": "", "historique": [{"date": date, "statut": EN_ATTENTE, "detail": "dépôt"}]}
        with verrou(self.dir, _VERROU):
            self._ecrire(entree)
        return entree

    def lire(self, ident: str) -> dict:
        try:
            return json.loads(self._path(ident).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileError(f"Proposition inconnue dans la file : {ident}") from None

    def lister(self, statuts: tuple[str, ...] | None = None) -> list[dict]:
        if not self.dir.exists():
            return []
        out = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                e = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if statuts is None or e.get("statut") in statuts:
                out.append(e)
        return sorted(out, key=lambda e: e.get("id", ""))

    def maj(self, ident: str, statut: str | None = None, detail: str = "", **champs) -> dict:
        """Mise à jour sous verrou ; un changement de statut est tracé dans l'historique de l'entrée."""
        with verrou(self.dir, _VERROU):
            e = self.lire(ident)
            e.update(champs)
            if statut:
                e["statut"] = statut
                e["raison"] = champs.get("raison", "") if statut == A_REVOIR else ""
                e["historique"].append({"date": _maintenant(), "statut": statut, "detail": detail})
            self._ecrire(e)
        return e

    def par_jeton(self, jeton: str) -> dict | None:
        if not jeton:
            return None
        return next((e for e in self.lister(OUVERTS) if e.get("jeton") == jeton), None)
