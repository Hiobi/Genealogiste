"""#142 : cache négatif par URL, coupe-circuit par hôte après blocage anti-robot, cache borné en taille."""

from __future__ import annotations

import os
import time

import httpx
import pytest
import respx

from genealogiste_mcp import menage, server
from genealogiste_mcp.cache import Cache
from genealogiste_mcp.config import load_config
from genealogiste_mcp.http import SourceError

URL = "https://archives.exemple.fr/api/vue/1"
AUTRE = "https://archives.exemple.fr/api/vue/2"
CF = "<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/cloudflare'></script></html>"


@respx.mock
@pytest.mark.parametrize("statut", [403, 404, 429])
def test_echec_memorise(app, statut):
    route = respx.get(URL).mock(return_value=httpx.Response(statut, headers={"Retry-After": "600"}))
    with pytest.raises(SourceError):
        app.http.get(URL)
    with pytest.raises(SourceError) as e:
        app.http.get(URL)
    assert route.call_count == 1
    assert e.value.echec_memorise is True and e.value.status == statut


@respx.mock
def test_erreur_serveur_non_memorisee(app):
    route = respx.get(URL).mock(return_value=httpx.Response(500))
    for _ in range(2):
        with pytest.raises(SourceError):
            app.http.get(URL)
    assert route.call_count == 2


@respx.mock
def test_echec_memorise_visible_dans_enveloppe(app):
    route = respx.get("https://gallica.bnf.fr/ark:/12148/bpt6k123456/f2.texteBrut").mock(
        return_value=httpx.Response(404))
    server.gallica_texte("ark:/12148/bpt6k123456", page=2)
    r = server.gallica_texte("ark:/12148/bpt6k123456", page=2)
    assert route.call_count == 1
    assert r["echec_memorise"] is True and r["depuis_cache"] is True
    server.cache_purger("gallica")  # l'utilisateur peut oublier l'échec
    server.gallica_texte("ark:/12148/bpt6k123456", page=2)
    assert route.call_count == 2


@respx.mock
def test_coupe_circuit_apres_blocage_anti_robot(app):
    respx.get(URL).mock(return_value=httpx.Response(403, text=CF))
    autre = respx.get(AUTRE).mock(return_value=httpx.Response(200, json={}))
    ailleurs = respx.get("https://autre-service.fr/x").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(SourceError):
        app.http.get(URL)
    with pytest.raises(SourceError) as e:
        app.http.get(AUTRE)
    assert autre.call_count == 0
    assert e.value.coupe_circuit is True and e.value.reessayer_apres > 0
    assert "reprise" in str(e.value)
    app.http.get("https://autre-service.fr/x")  # les autres hôtes ne sont pas touchés
    assert ailleurs.call_count == 1
    server.cache_purger("coupe_circuit")
    app.http.get(AUTRE)
    assert autre.call_count == 1


def test_purge_des_expirees(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    c.set("a", 1, ttl=0.01)
    c.set("b", 2, ttl=3600)
    time.sleep(0.05)
    assert c.purge_expirees() == 1
    assert c.get("b") == 2


def test_cache_sqlite_borne(tmp_path):
    c = Cache(tmp_path / "c.sqlite", max_octets=2000)
    for i in range(50):
        c.set(f"k{i}", "x" * 100, ttl=3600)
    c.borner()
    assert c.taille() <= 2000
    assert c.get("k49") is not None and c.get("k0") is None  # les plus anciennes partent d'abord


def test_cache_images_borne(tmp_path):
    d = tmp_path / "cache-images"
    (d / "iiif").mkdir(parents=True)
    for i in range(10):
        f = d / "iiif" / f"{i}.jpg"
        f.write_bytes(b"x" * 100)
        os.utime(f, (1000 + i, 1000 + i))
    (d / "iiif" / ".genealogiste.lock").write_text("")
    supprimes = menage.borner_dossier(d, 450)
    restants = sorted(p.name for p in (d / "iiif").iterdir() if not p.name.startswith("."))
    assert supprimes == 6 and restants == ["6.jpg", "7.jpg", "8.jpg", "9.jpg"]
    assert (d / "iiif" / ".genealogiste.lock").exists()


def test_config_plafonds(tmp_path, monkeypatch):
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GENEALOGISTE_CACHE_MAX_MO", "50")
    monkeypatch.setenv("GENEALOGISTE_CACHE_IMAGES_MAX_MO", "300")
    cfg = load_config()
    assert (cfg.cache_max_mo, cfg.cache_images_max_mo) == (50.0, 300.0)


def test_docstring_cache_purger():
    doc = server.cache_purger.__doc__
    for categorie in ("iiif", "visionneuse", "ark", "archives", "coupe_circuit"):
        assert categorie in doc
