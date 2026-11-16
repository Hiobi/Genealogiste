"""Le blocage reste exploitable après les adaptateurs et les sorties minimales (#150)."""

import hashlib

import httpx
import pytest
import respx

from genealogiste_mcp import server
from genealogiste_mcp.http import SourceError
from genealogiste_mcp.sources import iiif
from genealogiste_mcp.sources.base import error_envelope


@pytest.mark.parametrize("outil,params", [
    ("archives_naviguer", {"source": "ark:/33518/registre"}),
    ("archives_naviguer", {"source": "https://iiif.example/registre/manifest.json"}),
    ("archive_image", {"source": "ark:/33518/registre", "page": 1}),
    ("piece_archiver", {"source": "ark:/33518/registre", "page": 1}),
    ("archives_planche", {"source": "ark:/33518/registre", "de": 1}),
])
def test_blocage_conserve_tache_et_trace(app, monkeypatch, outil, params):
    exc = SourceError("Défi hCaptcha", 200)
    exc.bloque_antirobot = True
    exc.protection = "hCaptcha"
    exc.url = "https://archivesdepartementales.lenord.fr/visualizer/api?start=0&end=2"
    exc.date_detection = "2026-11-16T12:00:00+00:00"

    def bloquer(*args, **kwargs):
        raise exc

    monkeypatch.setattr(app.http, "get", bloquer)
    res = getattr(server, outil)(**params)
    assert res["statut"] == "bloque_antirobot"
    assert res["protection"] == "hCaptcha"
    assert res["date_detection"] == exc.date_detection
    assert res["tache_manuelle"]["url"] == exc.url
    assert res["tache_manuelle"]["statut"] == "a_faire"
    assert res["service"] == "AD59"  # service de l'URL effectivement bloquée
    assert "source_collee" in res["conseil"]
    trace = next(e for e in app.journal.entries() if e["id"] == res["journal"])
    assert trace["statut"] == "bloque_antirobot"
    assert exc.url in trace["references"]
    assert "hCaptcha" in trace["note"]


def test_erreur_ordinaire_ne_cree_pas_de_tache(app, monkeypatch):
    def echouer(*args, **kwargs):
        raise SourceError("Serveur indisponible", 500)
    monkeypatch.setattr(app.http, "get", echouer)
    res = server.archives_naviguer("https://iiif.example/registre/manifest.json")
    assert "erreur" in res and "tache_manuelle" not in res


def test_defi_reel_du_transport_puis_coupe_circuit_autre_outil(app):
    source = "ark:/33518/registre"
    with respx.mock as routes:
        route = routes.get("https://archivesdepartementales.lenord.fr/visualizer/api").mock(
            return_value=httpx.Response(503, headers={"cf-mitigated": "challenge"}, text="Défi"))
        premier = server.archives_naviguer(source, page=1, pas=3)
        second = server.archive_image(source, page=1)
    assert route.call_count == 1
    assert premier["statut"] == second["statut"] == "bloque_antirobot"
    assert premier["service"] == second["service"] == "AD59"
    assert premier["date_detection"] == second["date_detection"]
    assert premier["url"] == second["url"]
    assert second["coupe_circuit"]
    assert len(server.journal_lister(statut="bloque_antirobot")) == 2


@pytest.mark.parametrize("url,source,attendu", [
    ("https://archives-deux-sevres-vienne.fr/api", "ark:/28387/registre", "AD86"),
    ("https://archives-deux-sevres-vienne.fr/ark:/28387/registre", "", "AD86"),
    ("https://archives-deux-sevres-vienne.fr/api", "", "archives-deux-sevres-vienne.fr"),
    ("https://archives.isula.corsica/api", "", "archives.isula.corsica"),
    ("https://archives-deux-sevres-vienne.fr/api", "ark:/33518/registre", "archives-deux-sevres-vienne.fr"),
])
def test_service_ambigu_identifie_par_ark_coherent(app, url, source, attendu):
    exc = SourceError("défi", 403, bloque_antirobot=True, protection="Cloudflare", url=url,
                      date_detection="2026-11-16T12:00:00+00:00")
    assert error_envelope(app.sctx, "iiif", "image", {"source": source}, exc)["service"] == attendu


def test_info_defi_n_est_pas_masque_par_jpeg_cache(app, monkeypatch):
    service = "https://iiif.example/service"
    url_info = service + "/info.json"
    url_image = iiif.image_url(service, "full", 800, True)
    dest = app.config.media_dir / "iiif" / (hashlib.sha256(url_image.encode()).hexdigest()[:16] + ".jpg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"\xff\xd8image synthetique\xff\xd9")
    monkeypatch.setattr(iiif, "resoudre_vue", lambda *a: {"service": service})

    def bloquer(*args, **kwargs):
        raise SourceError("défi", 503, bloque_antirobot=True, protection="Cloudflare", url=url_info,
                          date_detection="2026-11-16T12:00:00+00:00")

    monkeypatch.setattr(app.http, "get", bloquer)
    res = iiif.fetch(app.sctx, app.config.media_dir, service)
    assert res["statut"] == "bloque_antirobot" and res["url"] == url_info
    assert next(e for e in app.journal.entries() if e["id"] == res["journal"])["statut"] == "bloque_antirobot"

    def erreur_ordinaire(*args, **kwargs):
        raise SourceError("indisponible", 500)

    monkeypatch.setattr(app.http, "get", erreur_ordinaire)
    repli = iiif.fetch(app.sctx, app.config.media_dir, service)
    assert repli["depuis_cache"] and repli["dimensions_originales"] is None
