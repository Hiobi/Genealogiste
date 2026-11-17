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
            self._passer_en_wal()
            self._db.execute("PRAGMA synchronous = NORMAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL,"
            " cree REAL NOT NULL, ttl REAL NOT NULL, source TEXT)"
        )
        # Compteurs de requêtes par hôte et par jour (plafond journalier, #157) : hors du cache des réponses,
        # jamais vidés par purge() ni borner().
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS compteurs_jour (hote TEXT NOT NULL, jour TEXT NOT NULL,"
            " n INTEGER NOT NULL, PRIMARY KEY (hote, jour))"
        )
        self._db.commit()

    def _passer_en_wal(self) -> None:
        """Le changement de mode de journal n'attend pas le verrou (busy_timeout ignoré) : plusieurs serveurs
        ouvrant ensemble un cache neuf se le disputent. Réessayer jusqu'à ATTENTE."""
        fin = time.monotonic() + ATTENTE
        pause = 0.02
        while True:
            try:
                self._db.execute("PRAGMA journal_mode = WAL")
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc) or time.monotonic() >= fin:
                    raise
                time.sleep(pause)
                pause = min(pause * 2, 0.5)

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

    def incrementer_jour(self, hote: str, jour: str, plafond: int) -> int | None:
        """Compte une requête de ``hote`` le ``jour`` ; None (rien compté) si le plafond est déjà atteint.
        Lecture et écriture dans une même transaction : sûr entre plusieurs serveurs."""
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute("DELETE FROM compteurs_jour WHERE jour < ?", (jour,))
                row = self._db.execute("SELECT n FROM compteurs_jour WHERE hote = ? AND jour = ?",
                                       (hote, jour)).fetchone()
                n = row[0] if row else 0
                if plafond and n >= plafond:
                    self._db.commit()
                    return None
                self._db.execute("INSERT OR REPLACE INTO compteurs_jour (hote, jour, n) VALUES (?, ?, ?)",
                                 (hote, jour, n + 1))
                self._db.commit()
                return n + 1
            except BaseException:
                self._db.rollback()
                raise

    def compteurs_jour(self, jour: str) -> dict[str, int]:
        with self._lock:
            rows = self._db.execute("SELECT hote, n FROM compteurs_jour WHERE jour = ? ORDER BY hote",
                                    (jour,)).fetchall()
        return dict(rows)

    def stats(self) -> dict:
        with self._lock:
            rows = self._db.execute("SELECT source, COUNT(*) FROM cache GROUP BY source").fetchall()
        return {s or "?": n for s, n in rows}
