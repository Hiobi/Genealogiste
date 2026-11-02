"""Journal de recherche : chaque requête (y compris négative) est tracée en JSONL."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path


class Journal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def add(
        self,
        source: str,
        operation: str,
        parametres: dict,
        statut: str,
        nb_resultats: int = 0,
        resume: str = "",
        references: list[str] | None = None,
        cache: bool = False,
        personne: str | None = None,
        note: str = "",
    ) -> str:
        """statut : positif | negatif | erreur | manuel."""
        entry = {
            "id": uuid.uuid4().hex[:12],
            "date": datetime.now(UTC).isoformat(timespec="seconds"),
            "source": source,
            "operation": operation,
            "parametres": parametres,
            "statut": statut,
            "nb_resultats": nb_resultats,
            "resume": resume,
            "references": references or [],
            "cache": cache,
            "personne": personne,
            "note": note,
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry["id"]

    def entries(
        self,
        source: str | None = None,
        personne: str | None = None,
        statut: str | None = None,
        texte: str | None = None,
        limite: int = 50,
    ) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if source and e["source"] != source:
                continue
            if personne and e.get("personne") != personne:
                continue
            if statut and e["statut"] != statut:
                continue
            if texte and texte.lower() not in json.dumps(e, ensure_ascii=False).lower():
                continue
            out.append(e)
        return out[-limite:]
