"""Écritures sûres : remplacement atomique, verrou interprocessus, journaux JSONL tolérants (#38, #44, #53)."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
    import msvcrt

LOCK_NAME = ".genealogiste.lock"
_THREADS: dict[str, threading.RLock] = {}
_GUARD = threading.Lock()


def ecrire_atomique(path: Path, text: str | bytes) -> None:
    """Écrit dans un temporaire du même répertoire, fsync, puis os.replace : jamais de fichier tronqué."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(text if isinstance(text, bytes) else text.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    with contextlib.suppress(OSError):  # répertoire : rend le renommage durable (POSIX)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


@contextlib.contextmanager
def verrou(directory: Path) -> Iterator[None]:
    """Verrou exclusif sur le répertoire de données, entre processus (flock) et entre fils d'exécution."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    key = str(directory.resolve())
    with _GUARD:
        rlock = _THREADS.setdefault(key, threading.RLock())
    with rlock:
        fh = open(directory / LOCK_NAME, "a+b")  # noqa: SIM115
        try:
            if fcntl:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            else:  # pragma: no cover
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            yield
        finally:
            if fcntl:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()


def ajouter_jsonl(path: Path, entry: dict) -> None:
    """Ajoute une ligne (flush + fsync). Une dernière ligne tronquée par un arrêt est isolée par un saut de ligne."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as fh:
        fh.seek(0, os.SEEK_END)
        prefix = b""
        if fh.tell():
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                prefix = b"\n"
        fh.write(prefix + (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())


def lire_jsonl(path: Path) -> tuple[list[dict], list[int]]:
    """(entrées valides, numéros des lignes illisibles) : une ligne corrompue n'empêche pas de lire les autres."""
    path = Path(path)
    if not path.exists():
        return [], []
    ok, bad = [], []
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            bad.append(i)
            continue
        if isinstance(e, dict):
            ok.append(e)
        else:
            bad.append(i)
    return ok, bad
