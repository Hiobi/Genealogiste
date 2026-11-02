"""Cache SQLite à durée de vie (TTL) pour les réponses des sources."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
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
