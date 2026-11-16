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
from genealogiste_mcp.http import SourceError, _protection

URL = "https://archives.exemple.fr/api/vue/1"
AUTRE = "https://archives.exemple.fr/api/vue/2"
# Pages synthétiques construites pour exercer les signatures, sans capture de service réel.
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
    respx.get(URL).mock(return_value=httpx.Response(403, text=CF, headers={"Content-Type": "text/html"}))
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


@respx.mock
@pytest.mark.parametrize("statut", [200, 403, 503])
@pytest.mark.parametrize(("corps", "protection"), [
    (CF, "Cloudflare"),
    ('<html><title>Security verification</title><h1>Verify you are human</h1>'
     '<div class="h-captcha" data-sitekey="synthetique"></div>'
     '<script src="https://js.hcaptcha.com/1/api.js"></script></html>', "hCaptcha"),
    ('<html><script src="https://geo.captcha-delivery.com/captcha/">'
     '</script><iframe src="https://geo.captcha-delivery.com/captcha/"></iframe></html>', "DataDome"),
    ('<html><title>Just a moment...</title><div id="challenge-running">'
     'Checking your browser before accessing</div></html>', "attente"),
])
def test_defi_avant_reprise_cache_et_analyse(app, statut, corps, protection):
    route = respx.get(URL).mock(return_value=httpx.Response(statut, text=corps, headers={"Content-Type": "text/html"}))
    with pytest.raises(SourceError) as erreur:
        app.http.get(URL, parse="text")
    assert erreur.value.bloque_antirobot is True
    assert erreur.value.protection == protection
    assert erreur.value.url == URL
    assert erreur.value.date_detection.endswith("+00:00")
    assert route.call_count == 1
    with pytest.raises(SourceError) as coupe:
        app.http.get(AUTRE)
    assert coupe.value.coupe_circuit and coupe.value.url == URL
    assert coupe.value.date_detection == erreur.value.date_detection
    app.http.cache.purge("coupe_circuit")
    with pytest.raises(SourceError) as cache:
        app.http.get(URL, parse="text")
    assert cache.value.echec_memorise and cache.value.protection == protection
    assert cache.value.url == URL and cache.value.date_detection == erreur.value.date_detection
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize("corps", [
    "<html>Documentation Cloudflare et hCaptcha pour les archives</html>",
    '<html><script src="https://js.hcaptcha.com/1/api.js"></script> formulaire</html>',
    "<html>Checking your browser: documentation du service</html>",
])
def test_mentions_ordinaires_ne_sont_pas_un_defi(app, corps):
    respx.get(URL).mock(return_value=httpx.Response(200, text=corps))
    assert app.http.get(URL, parse="text")[0] == corps


@respx.mock
def test_defi_sur_ecriture_non_rejoue_et_url_redirigee(app):
    destination = "https://autre-service.fr/defi?vue=1"
    route = respx.post(URL).mock(return_value=httpx.Response(
        503, headers={"cf-mitigated": "challenge"}, text="attendez"))
    with pytest.raises(SourceError) as erreur:
        app.http.post(URL, json={"donnee": "fictive"})
    assert erreur.value.bloque_antirobot and route.call_count == 1
    respx.get(AUTRE).mock(return_value=httpx.Response(302, headers={"Location": destination}))
    # Lever la pause pour suivre la redirection puis vérifier l'URL effective.
    app.http.cache.purge("coupe_circuit")
    respx.get(destination).mock(return_value=httpx.Response(200, text=CF, headers={"Content-Type": "text/html"}))
    with pytest.raises(SourceError) as redirection:
        app.http.get(AUTRE)
    assert redirection.value.url == destination
    with pytest.raises(SourceError) as coupe:
        app.http.get("https://autre-service.fr/autre")
    assert coupe.value.url == destination and coupe.value.coupe_circuit


@respx.mock
def test_redirection_vers_hote_en_pause_sans_recontact(app):
    destination = "https://autre-service.fr/defi"
    cible = respx.get(destination).mock(return_value=httpx.Response(403, text=CF, headers={"Content-Type": "text/html"}))
    respx.get(URL).mock(return_value=httpx.Response(302, headers={"Location": destination}))
    with pytest.raises(SourceError):
        app.http.get(destination)
    with pytest.raises(SourceError) as erreur:
        app.http.get(URL)
    assert erreur.value.coupe_circuit and erreur.value.url == destination
    assert cible.call_count == 1


@respx.mock
def test_formulaire_legitime_hcaptcha_accepte(app):
    corps = ('<html><form action="/inscription"><input name="email"><p>Verify you are human</p>'
             '<div class="h-captcha" data-sitekey="synthetique"></div>'
             '<script src="https://js.hcaptcha.com/1/api.js"></script>'
             '<button>Inscription</button></form></html>')
    respx.get(URL).mock(return_value=httpx.Response(200, text=corps))
    assert app.http.get(URL, parse="text")[0] == corps


@respx.mock
@pytest.mark.parametrize(("content_type", "corps"), [
    ("application/json", '{"exemple":"/cdn-cgi/challenge-platform/ ou cf-chl-example"}'),
    ("application/pdf", "%PDF-1.4 documentation cf-chl-example"),
    ("text/plain", "documentation /cdn-cgi/challenge-platform/"),
])
def test_signature_dans_document_non_html_acceptee(app, content_type, corps):
    respx.get(URL).mock(return_value=httpx.Response(200, content=corps, headers={"Content-Type": content_type}))
    assert app.http.get(URL, parse="text")[0] == corps


@respx.mock
def test_html_sans_type_et_403_ordinaire(app):
    respx.get(URL).mock(return_value=httpx.Response(200, content=CF.encode()))
    with pytest.raises(SourceError) as erreur:
        app.http.get(URL)
    assert erreur.value.protection == "Cloudflare"
    app.http.cache.purge("coupe_circuit")
    respx.get(AUTRE).mock(return_value=httpx.Response(403, text="Accès refusé"))
    with pytest.raises(SourceError) as ordinaire:
        app.http.get(AUTRE)
    assert not ordinaire.value.bloque_antirobot and ordinaire.value.status == 403


def test_reponse_en_stream_ne_lit_pas_le_corps():
    class Flux(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("Le corps ne doit pas être lu")

    resp = httpx.Response(503, stream=Flux(), headers={"Content-Type": "text/html"})
    assert _protection(resp) is None
    resp.headers["cf-mitigated"] = "challenge"
    assert _protection(resp) == "Cloudflare"
