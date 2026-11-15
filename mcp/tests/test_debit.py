"""#140 : limite de débit pour tout hôte (intervalle par défaut non nul), surcharges par service du référentiel
et par variable d'environnement, attente hors du verrou global (un hôte lent ne bloque pas les autres)."""

from __future__ import annotations

import threading
import time

import httpx
import pytest
import respx

from genealogiste_mcp import archives, server
from genealogiste_mcp.cache import Cache
from genealogiste_mcp.config import Config, load_config
from genealogiste_mcp.http import HttpClient

AD = "https://archives.exemple-departement.fr/vue/1.json"


@respx.mock
def test_hote_archives_non_liste_espace(app):
    respx.get(AD).mock(return_value=httpx.Response(200, json={}))
    app.http.get(AD, use_cache=False)
    app.http.get(AD, use_cache=False)
    assert app.sleeps and app.sleeps[-1] >= 1.0


def test_config_debits_par_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GENEALOGISTE_DEBIT_DEFAUT", "2.5")
    monkeypatch.setenv("GENEALOGISTE_DEBITS", "archives.exemple.fr=4, gallica.bnf.fr=0.5,")
    cfg = load_config()
    assert cfg.debit_defaut == 2.5
    assert cfg.debits == {"archives.exemple.fr": 4.0, "gallica.bnf.fr": 0.5}


def test_config_debits_invalides(tmp_path, monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path))
    for var, valeur in (("GENEALOGISTE_DEBITS", "archives.exemple.fr"), ("GENEALOGISTE_DEBITS", "a.fr=vite"),
                        ("GENEALOGISTE_DEBIT_DEFAUT", "-1")):
        monkeypatch.setenv(var, valeur)
        with pytest.raises(ValueError, match=var):
            load_config()
        monkeypatch.delenv(var)


def test_defaut_config_non_nul(tmp_path):
    assert Config(data_dir=tmp_path, cache_path=tmp_path / "c.sqlite").debit_defaut >= 1.0


def test_intervalles_referentiel(monkeypatch):
    faux = ({"code": "AD99", "site": "https://archives.ad99.fr", "visionneuse": "https://vision.ad99.fr/v",
             "intervalle_requetes": 3},
            {"code": "AD98", "site": "https://archives.ad98.fr"})
    monkeypatch.setattr(archives, "services", lambda: faux)
    assert archives.intervalles() == {"archives.ad99.fr": 3.0, "vision.ad99.fr": 3.0}


def test_priorites_app(config, monkeypatch):
    monkeypatch.setattr(archives, "intervalles", lambda: {"gallica.bnf.fr": 5.0, "archives.ad99.fr": 3.0})
    config.debits = {"archives.ad99.fr": 7.0}
    config.debit_defaut = 2.0
    a = server.App(config, sleeper=lambda s: None)
    assert a.http.min_intervals["gallica.bnf.fr"] == 5.0  # référentiel > valeur codée
    assert a.http.min_intervals["archives.ad99.fr"] == 7.0  # variable d'environnement > référentiel
    assert a.http.min_intervals["geo.api.gouv.fr"] == 0.1
    assert a.http.default_interval == 2.0


def test_attente_hors_verrou_global(tmp_path):
    """Un hôte qui attend son créneau ne retarde pas un autre hôte."""
    client = HttpClient(Cache(tmp_path / "c.sqlite"), "test", min_intervals={"lent.example": 0.6, "rapide.example": 0.01})
    client._throttle("lent.example")
    t = threading.Thread(target=client._throttle, args=("lent.example",))
    t.start()
    time.sleep(0.05)
    debut = time.monotonic()
    client._throttle("rapide.example")
    assert time.monotonic() - debut < 0.2
    t.join()
