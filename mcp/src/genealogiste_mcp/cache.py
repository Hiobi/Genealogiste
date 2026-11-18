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
ATTENTE_CRENEAU = 5.0  # attente maximale du verrou pour réserver un créneau ; au-delà, repli en mémoire
DERIVE_MAX = 3600.0  # créneau enregistré plus loin dans le futur : horloge reculée, ignoré
RALENTISSEMENT = "ralentissement"  # catégorie de cache_purger qui lève les ralentissements du jour
ANTIROBOT = "antirobot"  # catégorie de cache_purger qui oublie les défis anti-robot observés (#150)
COUPE_CIRCUIT = "coupe_circuit"  # catégorie de cache_purger : pauses et exclusions anti-robot levées


class Cache:
    BORNER_TOUS = 100  # contrôle de taille toutes les N écritures
    attente_creneau = ATTENTE_CRENEAU

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
        # Débit partagé entre processus (#211) : dernier créneau réservé par hôte (horloge murale) et
        # ralentissement du jour après 429/502/503/504. Hors du cache des réponses ; seul
        # purge("ralentissement") lève les ralentissements.
        self._db.execute("CREATE TABLE IF NOT EXISTS creneaux (hote TEXT PRIMARY KEY, dernier REAL NOT NULL)")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS ralentissements (hote TEXT PRIMARY KEY, jour TEXT NOT NULL,"
            " facteur REAL NOT NULL, incidents INTEGER NOT NULL, statut INTEGER, maj REAL NOT NULL,"
            " double_a REAL)"
        )
        self._migrer_ralentissements()
        # Défis anti-robot observés par hôte (#150) : historique durable de cette installation et exclusion
        # éventuelle (défi persistant). Hors du cache des réponses : une purge complète ne les touche pas ;
        # purge("coupe_circuit") lève l'exclusion, purge("antirobot") oublie l'historique.
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS defis_antirobot (hote TEXT PRIMARY KEY, protection TEXT, url TEXT,"
            " statut INTEGER, premiere REAL NOT NULL, derniere REAL NOT NULL, detections INTEGER NOT NULL,"
            " exclu_jusqu_a REAL)"
        )
        self._db.commit()

    def _migrer_ralentissements(self) -> None:
        """Cache antérieur à l'anti-rebond (#211) : ajoute la colonne ``double_a`` (horodatage du dernier
        doublement). Plusieurs serveurs ouvrant ensemble un ancien cache peuvent se la disputer : une colonne
        déjà ajoutée par un autre n'est pas une erreur."""
        colonnes = {r[1] for r in self._db.execute("PRAGMA table_info(ralentissements)")}
        if "double_a" in colonnes:
            return
        try:
            self._db.execute("ALTER TABLE ralentissements ADD COLUMN double_a REAL")
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise

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
        """Vide le cache des réponses (tout ou une catégorie). ``"ralentissement"`` lève les ralentissements
        d'hôtes ; une purge complète ne les lève pas, ni les compteurs journaliers."""
        with self._lock:
            if source == RALENTISSEMENT:
                cur = self._db.execute("DELETE FROM ralentissements")
                self._db.commit()
                return cur.rowcount
            if source == ANTIROBOT:
                cur = self._db.execute("DELETE FROM defis_antirobot")
                self._db.commit()
                return cur.rowcount
            if source == COUPE_CIRCUIT:  # pauses et exclusions levées ; l'historique des défis reste
                levees = self._db.execute("UPDATE defis_antirobot SET exclu_jusqu_a = NULL"
                                          " WHERE exclu_jusqu_a IS NOT NULL").rowcount
                cur = self._db.execute("DELETE FROM cache WHERE source = ?", (source,))
                self._db.commit()
                return cur.rowcount + levees
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

    def _transaction(self, attente: float):
        """BEGIN IMMEDIATE avec une attente de verrou bornée (``attente`` s) ; à appeler sous self._lock."""
        self._db.execute(f"PRAGMA busy_timeout = {int(attente * 1000)}")
        try:
            self._db.execute("BEGIN IMMEDIATE")
        finally:
            self._db.execute(f"PRAGMA busy_timeout = {int(ATTENTE * 1000)}")

    def reserver_creneau(self, hote: str, intervalle: float, maintenant: float) -> float:
        """Réserve le prochain créneau d'envoi vers ``hote`` : ``max(maintenant, dernier + intervalle)``, lu et
        écrit dans une même transaction (sûr entre processus partageant ce fichier). ``maintenant`` est une
        horloge murale (time.time). Lève sqlite3.OperationalError si le verrou n'est pas obtenu à temps."""
        with self._lock:
            try:
                self._transaction(self.attente_creneau)
                row = self._db.execute("SELECT dernier FROM creneaux WHERE hote = ?", (hote,)).fetchone()
                dernier = row[0] if row else None
                if dernier is None or dernier - maintenant > DERIVE_MAX:
                    slot = maintenant
                else:
                    slot = max(maintenant, dernier + intervalle)
                self._db.execute("INSERT OR REPLACE INTO creneaux (hote, dernier) VALUES (?, ?)", (hote, slot))
                self._db.commit()
                return slot
            except BaseException:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def ralentir(self, hote: str, jour: str, facteur_max: float, statut: int | None = None,
                 maintenant: float | None = None, anti_rebond: float = 0.0) -> float:
        """Double le facteur de ralentissement de ``hote`` pour ``jour`` (plafonné à ``facteur_max``) ;
        un ralentissement d'un jour précédent repart de 1. Anti-rebond : un incident survenu moins de
        ``anti_rebond`` s (horloge murale) après le dernier doublement est compté (incidents, statut) sans
        doubler de nouveau, pour qu'une rafale d'erreurs d'un même épisode ne vaille qu'un doublement. Lecture
        et écriture dans une même transaction : sûr entre processus. Renvoie le facteur courant."""
        maintenant = time.time() if maintenant is None else maintenant
        with self._lock:
            try:
                self._transaction(self.attente_creneau)
                row = self._db.execute(
                    "SELECT jour, facteur, incidents, double_a FROM ralentissements WHERE hote = ?",
                    (hote,)).fetchone()
                facteur, incidents, double_a = (row[1], row[2], row[3]) if row and row[0] == jour else (1.0, 0, None)
                if double_a is None or not 0 <= maintenant - double_a < anti_rebond:
                    facteur = min(max(1.0, facteur_max), facteur * 2)
                    double_a = maintenant
                self._db.execute(
                    "INSERT OR REPLACE INTO ralentissements (hote, jour, facteur, incidents, statut, maj, double_a)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (hote, jour, facteur, incidents + 1, statut, maintenant, double_a))
                self._db.commit()
                return facteur
            except BaseException:
                if self._db.in_transaction:
                    self._db.rollback()
                raise

    def noter_defi(self, hote: str, protection: str, url: str, statut: int | None, maintenant: float,
                   exclusion: float = 0.0, fenetre: float = 0.0) -> dict:
        """Enregistre un défi anti-robot observé sur ``hote`` (#150). Récidive : un défi précédent observé il y a
        moins de ``fenetre`` s (le défi persiste après la pause du coupe-circuit) ; avec ``exclusion`` > 0, l'hôte
        est alors exclu ``exclusion`` s. Lecture et écriture dans une même transaction. Renvoie l'observation."""
        with self._lock:
            try:
                self._transaction(ATTENTE)
                row = self._db.execute("SELECT premiere, derniere, detections, exclu_jusqu_a FROM defis_antirobot"
                                       " WHERE hote = ?", (hote,)).fetchone()
                premiere, detections, exclu = (row[0], row[2], row[3]) if row else (maintenant, 0, None)
                recidive = bool(row) and 0 <= maintenant - row[1] < fenetre
                if recidive and exclusion > 0:
                    exclu = maintenant + exclusion
                self._db.execute(
                    "INSERT OR REPLACE INTO defis_antirobot (hote, protection, url, statut, premiere, derniere,"
                    " detections, exclu_jusqu_a) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (hote, protection, url, statut, premiere, maintenant, detections + 1, exclu))
                self._db.commit()
            except BaseException:
                if self._db.in_transaction:
                    self._db.rollback()
                raise
        return {**(self.defi_antirobot(hote) or {}), "recidive": recidive}

    def defi_antirobot(self, hote: str) -> dict | None:
        """Dernier défi anti-robot observé sur ``hote`` (None s'il n'y en a pas)."""
        with self._lock:
            row = self._db.execute("SELECT hote, protection, url, statut, premiere, derniere, detections,"
                                   " exclu_jusqu_a FROM defis_antirobot WHERE hote = ?", (hote,)).fetchone()
        if row is None:
            return None
        return dict(zip(("hote", "protection", "url", "statut", "premiere", "derniere", "detections",
                         "exclu_jusqu_a"), row, strict=True))

    def ralentissement(self, hote: str, jour: str) -> float:
        """Facteur de ralentissement de ``hote`` pour ``jour`` (1.0 sans incident ce jour-là)."""
        with self._lock:
            row = self._db.execute("SELECT facteur FROM ralentissements WHERE hote = ? AND jour = ?",
                                   (hote, jour)).fetchone()
        return row[0] if row else 1.0

    def ralentissements(self, jour: str) -> dict[str, dict]:
        with self._lock:
            rows = self._db.execute("SELECT hote, facteur, incidents, statut, maj FROM ralentissements"
                                    " WHERE jour = ? ORDER BY hote", (jour,)).fetchall()
        return {h: {"facteur": f, "incidents": n, "dernier_statut": s, "depuis": m} for h, f, n, s, m in rows}

    def compteurs_jour(self, jour: str) -> dict[str, int]:
        with self._lock:
            rows = self._db.execute("SELECT hote, n FROM compteurs_jour WHERE jour = ? ORDER BY hote",
                                    (jour,)).fetchall()
        return dict(rows)

    def stats(self) -> dict:
        with self._lock:
            rows = self._db.execute("SELECT source, COUNT(*) FROM cache GROUP BY source").fetchall()
        return {s or "?": n for s, n in rows}
