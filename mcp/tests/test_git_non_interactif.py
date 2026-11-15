"""#151 (partie A) : aucun appel git ne peut bloquer le serveur — délai, stdin fermé, invites désactivées."""

from __future__ import annotations

import socket
import subprocess
import threading
import time

import pytest

from genealogiste_mcp.config import load_config
from genealogiste_mcp.tree import store as store_mod
from genealogiste_mcp.tree.store import GitError, TreeStore


@pytest.fixture
def miroir_muet():
    """Serveur qui accepte la connexion et ne répond jamais (miroir en panne, proxy bloqué)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    conns = []
    arret = threading.Event()

    def accepter():
        srv.settimeout(0.2)
        while not arret.is_set():
            try:
                conns.append(srv.accept())
            except OSError:
                continue

    threading.Thread(target=accepter, daemon=True).start()
    yield f"https://127.0.0.1:{srv.getsockname()[1]}/arbre.git"
    arret.set()
    srv.close()


def test_push_vers_miroir_muet_borne(tmp_path, miroir_muet):
    st = TreeStore(tmp_path / "d", "", delai=2.0)
    st.ensure()
    st.commit("init")
    st.remote = miroir_muet
    debut = time.monotonic()
    res = st.push()
    assert time.monotonic() - debut < 10
    assert "délai" in res and st.last_push == res
    assert st.log(1)  # l'écriture locale reste faite


def test_appels_git_non_interactifs(tmp_path, monkeypatch):
    appels = []
    vrai = subprocess.run

    def espion(cmd, **kw):
        appels.append(kw)
        return vrai(cmd, **kw)

    monkeypatch.setattr(store_mod.subprocess, "run", espion)
    st = TreeStore(tmp_path / "d", "")
    st.ensure()
    st.commit("init")
    st.remote = str(tmp_path / "inexistant.git")
    st.push()
    assert appels
    for kw in appels:
        assert kw.get("stdin") == subprocess.DEVNULL
        assert kw.get("timeout") and kw["timeout"] > 0
        assert kw["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert "BatchMode=yes" in kw["env"]["GIT_SSH_COMMAND"]


def test_delai_git_local_explicite(tmp_path, monkeypatch):
    st = TreeStore(tmp_path / "d", "")
    st.ensure()

    def lent(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(store_mod.subprocess, "run", lent)
    with pytest.raises(GitError, match="délai"):
        st._git("status")


def test_delai_configurable(tmp_path, monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("GENEALOGISTE_GIT_DELAI", "15")
    assert load_config().git_delai == 15.0
