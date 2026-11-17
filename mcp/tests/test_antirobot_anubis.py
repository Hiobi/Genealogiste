"""#196 : page de défi Anubis (AD48) et interstitiels reCAPTCHA reconnus, consigne explicite à l'agent."""

from __future__ import annotations

import httpx
import pytest
import respx

from genealogiste_mcp import acces_archives, archives, server
from genealogiste_mcp.http import SourceError

URL = "https://archives.exemple.fr/ark:/00000/registre"
# Squelette synthétique reprenant seulement les marqueurs du gabarit public d'Anubis (web/index.templ :
# scripts JSON anubis_version/anubis_challenge, ressources /.within.website/x/cmd/anubis/), sans page réelle.
ANUBIS = ('<!DOCTYPE html><html lang="fr"><head><title>Making sure you&#39;re not a bot!</title>'
          '<script id="anubis_version" type="application/json">"v0.0.0-fictif"</script>'
          '<script id="anubis_challenge" type="application/json">{"rules":{"difficulty":4}}</script>'
          '</head><body><main><p id="status">Chargement...</p>'
          '<script id="anubis-main" type="module" src="/.within.website/x/cmd/anubis/static/js/main.mjs">'
          '</script></main></body></html>')
RECAPTCHA = ('<html><head><title>Vérification de sécurité</title>'
             '<script src="https://www.google.com/recaptcha/api.js"></script></head>'
             '<body><div class="g-recaptcha" data-sitekey="synthetique"></div></body></html>')


@respx.mock
@pytest.mark.parametrize("statut", [200, 401, 403, 429, 503])
def test_anubis_reconnu_quel_que_soit_le_statut(app, statut):
    # Le statut d'un défi Anubis est configurable (status_codes.CHALLENGE, 200 par défaut).
    route = respx.get(URL).mock(return_value=httpx.Response(
        statut, text=ANUBIS, headers={"Content-Type": "text/html; charset=utf-8"}))
    with pytest.raises(SourceError) as erreur:
        app.http.get(URL, parse="text")
    assert erreur.value.bloque_antirobot and erreur.value.protection == "Anubis"
    assert route.call_count == 1  # aucune reprise, aucune exécution du défi


@respx.mock
def test_recaptcha_interstitiel_reconnu(app):
    respx.get(URL).mock(return_value=httpx.Response(200, text=RECAPTCHA, headers={"Content-Type": "text/html"}))
    with pytest.raises(SourceError) as erreur:
        app.http.get(URL, parse="text")
    assert erreur.value.protection == "reCAPTCHA"


@respx.mock
@pytest.mark.parametrize(("ctype", "corps"), [
    ("text/html", "<html><title>Anubis, dieu de l'Égypte</title><p>Le culte d'Anubis…</p></html>"),
    ("text/html", "<html><p>Notre site est protégé par Anubis contre les robots d'indexation.</p></html>"),
    ("text/html", '<html><a href="https://github.com/TecharoHQ/anubis">anubis_challenge, documentation</a></html>'),
    ("text/plain", 'id="anubis_challenge" /.within.website/x/cmd/anubis/ (extrait de documentation)'),
    ("text/html", '<html><title>Contact</title><form><div class="g-recaptcha" data-sitekey="x"></div>'
                  '<script src="https://www.google.com/recaptcha/api.js"></script></form></html>'),
    ("text/html", "<html><p>Ce formulaire utilise un captcha pour limiter les abus.</p></html>"),
])
def test_page_ordinaire_citant_anubis_ou_captcha_acceptee(app, ctype, corps):
    respx.get(URL).mock(return_value=httpx.Response(200, text=corps, headers={"Content-Type": ctype}))
    assert app.http.get(URL, parse="text")[0] == corps


def test_naviguer_ad48_anubis_renvoie_consigne_et_trace(app):
    source = "https://archives.lozere.fr/ark:/24967/registrefictif"
    with respx.mock as routes:
        route = routes.route(host="archives.lozere.fr").mock(return_value=httpx.Response(
            200, text=ANUBIS, headers={"Content-Type": "text/html; charset=utf-8"}))
        res = server.archives_naviguer(source)
        second = server.archive_image(source, page=1)
    assert route.call_count == 1  # le coupe-circuit évite de redemander le défi
    for r in (res, second):
        assert r["statut"] == "bloque_antirobot"
        assert r["bloque"] == "anti-robot"
        assert r["protection"] == "Anubis"
        assert r["service"] == "AD48"
        assert "media_enregistrer" in r["consigne"] and "capture" in r["consigne"]
    trace = next(e for e in app.journal.entries() if e["id"] == res["journal"])
    assert trace["statut"] == "bloque_antirobot" and "Anubis" in trace["note"]
    assert len(server.journal_lister(statut="bloque_antirobot")) == 2


def test_erreur_ordinaire_sans_consigne_anti_robot(app, monkeypatch):
    def echouer(*args, **kwargs):
        raise SourceError("Serveur indisponible", 500)

    monkeypatch.setattr(app.http, "get", echouer)
    res = server.archives_naviguer("https://iiif.example/registre/manifest.json")
    assert "bloque" not in res and "consigne" not in res


def test_referentiel_ad48_protection_anubis_sourcee():
    acces = archives.by_code("AD48")["visionneuse_acces"]
    assert acces["protection"] == "anubis"
    assert acces["protection_releve_le"] and acces["protection_reference"].startswith("https://archives.lozere.fr")
    assert archives.validate() == []


def test_archives_service_expose_consultation_manuelle():
    r = server.archives_service(code="AD48")
    manuel = r["consultation_manuelle"]
    assert manuel["protection"] == "anubis"
    assert manuel["releve_le"] == archives.by_code("AD48")["visionneuse_acces"]["protection_releve_le"]
    assert "media_enregistrer" in manuel["consigne"]
    assert "cache_purger" in manuel["reessai"]  # une protection peut être levée : pas de blocage définitif
    assert server.archives_service(code="AD59")["consultation_manuelle"]["protection"] == "cloudflare_hcaptcha"
    assert "consultation_manuelle" not in server.archives_service(code="AD25")


@pytest.mark.parametrize(("acces", "erreur"), [
    ({"famille": "editeur_ad", "protection": "inconnue"}, "protection inconnue"),
    ({"famille": "editeur_ad", "protection": "anubis", "protection_releve_le": "hier"}, "protection_releve_le"),
    ({"famille": "editeur_ad", "protection": "anubis", "protection_reference": "ftp://x"}, "protection_reference"),
])
def test_validation_protection(acces, erreur):
    assert any(erreur in e for e in acces_archives.valider(acces))


def test_validation_protection_valide():
    assert acces_archives.valider({"famille": "editeur_ad", "protection": "anubis",
                                   "protection_releve_le": "2026-11-17",
                                   "protection_reference": "https://archives.exemple.fr/"}) == []
