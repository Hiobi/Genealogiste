"""Cache SQLite à durée de vie (TTL) pour les réponses des sources."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

ATTENTE = 30.0  # secondes d'attente d'un verrou SQLite tenu par un autre processus


class Cache:
    BORNER_TOUS = 100  # contrôle de taille toutes les N écritures

    def __init__(self, path: Path | str, max_octets: int = 0):
        self.path = Path(path)
        self.max_octets = max_octets  # 0 = aucun plafond
        self._ecritures = 0
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Plusieurs serveurs peuvent partager ce cache : WAL (lecteurs et écrivain simultanés) et attente du
        # verrou plutôt que « database is locked » immédiat.
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=ATTENTE)
        self._db.execute(f"PRAGMA busy_timeout = {int(ATTENTE * 1000)}")
        if str(path) != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
            self._db.execute("PRAGMA synchronous = NORMAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL,"
            " cree REAL NOT NULL, ttl REAL NOT NULL, source TEXT)"
        )
        self._db.commit()

    @staticmethod
    def key(*parts: Any) -> str:
        raw = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self._db.execute("SELECT valeur, cree, ttl FROM cache WHERE cle = ?", (key,)).fetchone()
        if not row:
            return None
        valeur, cree, ttl = row
        if ttl >= 0 and time.time() - cree > ttl:
            self.delete(key)
            return None
        return json.loads(valeur)

    def set(self, key: str, value: Any, ttl: float, source: str = "") -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO cache (cle, valeur, cree, ttl, source) VALUES (?, ?, ?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), time.time(), ttl, source),
            )
            self._db.commit()
            self._ecritures += 1
        if self.max_octets and self._ecritures % self.BORNER_TOUS == 0:
            self.borner()

    def taille(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COALESCE(SUM(LENGTH(valeur)), 0) FROM cache").fetchone()[0]

    def purge_expirees(self) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM cache WHERE ttl >= 0 AND ? - cree > ttl", (time.time(),))
            self._db.commit()
            return cur.rowcount

    def borner(self) -> int:
        """Purge les entrées expirées puis, au-delà de max_octets, les plus anciennes."""
        n = self.purge_expirees()
        if not self.max_octets:
            return n
        with self._lock:
            total = self._db.execute("SELECT COALESCE(SUM(LENGTH(valeur)), 0) FROM cache").fetchone()[0]
            if total <= self.max_octets:
                return n
            rows = self._db.execute("SELECT cle, LENGTH(valeur) FROM cache ORDER BY cree ASC").fetchall()
            trop = []
            for cle, taille in rows:
                if total <= self.max_octets:
                    break
                trop.append((cle,))
                total -= taille
            self._db.executemany("DELETE FROM cache WHERE cle = ?", trop)
            self._db.commit()
        return n + len(trop)

    def delete(self, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM cache WHERE cle = ?", (key,))
            self._db.commit()

    def purge(self, source: str | None = None) -> int:
        with self._lock:
            if source:
                cur = self._db.execute("DELETE FROM cache WHERE source = ?", (source,))
            else:
                cur = self._db.execute("DELETE FROM cache")
            self._db.commit()
            return cur.rowcount

    def stats(self) -> dict:
        with self._lock:
            rows = self._db.execute("SELECT source, COUNT(*) FROM cache GROUP BY source").fetchall()
        return {s or "?": n for s, n in rows}
