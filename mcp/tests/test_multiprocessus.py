"""#151 (partie B) : plusieurs serveurs sur les mêmes données — cache SQLite en WAL avec délai d'attente,
journal protégé par un verrou de fichier entre processus."""

from __future__ import annotations

import multiprocessing as mp
import random
import sqlite3
from pathlib import Path

from genealogiste_mcp import fichiers
from genealogiste_mcp.cache import Cache
from genealogiste_mcp.journal import Journal
from genealogiste_mcp.tree.store import GITIGNORE_REQUIS

N = 120


def _travail(rep: str, k: int) -> list[str]:
    c, j = Cache(Path(rep) / "cache.sqlite"), Journal(Path(rep) / "journal.jsonl")
    erreurs = []
    for i in range(N):
        try:
            c.set(f"{k}-{i}", {"v": "x" * random.randint(10, 20000)}, 3600, "test")
            c.get(f"{k}-{i // 2}")
            if i % 50 == 0:
                c.purge_expirees()
        except sqlite3.Error as e:
            erreurs.append(f"{type(e).__name__}: {e}")
        j.add("test", "op", {"i": i, "k": k}, "positif", resume="r" * random.randint(10, 30000))
    return erreurs


def test_cache_en_wal_avec_delai(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    assert c._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c._db.execute("PRAGMA busy_timeout").fetchone()[0] >= 10000


def test_journal_verrouille_entre_processus(tmp_path, monkeypatch):
    verrous = []
    vrai = fichiers.verrou

    def espion(directory, nom=fichiers.LOCK_NAME):
        verrous.append(nom)
        return vrai(directory, nom)

    monkeypatch.setattr("genealogiste_mcp.journal.verrou", espion)
    Journal(tmp_path / "journal.jsonl").add("t", "op", {}, "positif")
    assert verrous == [".journal.lock"]
    assert ".journal.lock" in GITIGNORE_REQUIS


def test_quatre_processus_sans_erreur_ni_perte(tmp_path):
    ctx = mp.get_context("spawn")
    with ctx.Pool(4) as p:
        res = p.starmap(_travail, [(str(tmp_path), k) for k in range(4)])
    assert [e for r in res for e in r] == []
    j = Journal(tmp_path / "journal.jsonl")
    assert len(j.entries(limite=10**9)) == 4 * N and j.lignes_corrompues == []


def _ouvrir(chemin: str, barriere) -> str:
    barriere.wait()
    try:
        Cache(Path(chemin)).set("k", 1, 60, "test")
    except sqlite3.Error as e:
        return f"{type(e).__name__}: {e}"
    return ""


def test_ouverture_simultanee_d_un_cache_neuf(tmp_path):
    """Plusieurs serveurs qui démarrent ensemble sur un cache neuf : le passage en WAL ne doit pas échouer."""
    ctx = mp.get_context("spawn")
    erreurs = []
    with ctx.Manager() as m, ctx.Pool(8) as p:
        for essai in range(6):
            barriere = m.Barrier(8)
            chemin = str(tmp_path / f"cache-{essai}.sqlite")
            erreurs += [e for e in p.starmap(_ouvrir, [(chemin, barriere)] * 8) if e]
    assert erreurs == []
