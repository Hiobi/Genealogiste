"""#139 : rien n'entre dans le cache d'images sans être une image complète (Content-Type, octets magiques,
fin de fichier), écriture atomique, plafonds de taille (octets et pixels)."""

from __future__ import annotations

import io

import httpx
import respx

from genealogiste_mcp import http, server

JPEG = b"\xff\xd8\xff\xe0fictif\xff\xd9"
SVC = "https://iiif.exemple.org/image/registre/vue-1"
APERCU = f"{SVC}/full/800,/0/gray.jpg"
DIRECTE = "https://images.exemple.org/vue-1.jpg"
CAPTCHA = b"<!DOCTYPE html><html><body>Verifying you are human</body></html>"


def _fichiers(app, sous: str) -> list:
    d = app.config.cache_images_dir / sous
    return [p for p in d.rglob("*") if p.is_file() and not p.name.startswith(".")] if d.exists() else []


def _apercu(route_contenu, **kw):
    respx.get(f"{SVC}/info.json").mock(return_value=httpx.Response(404))
    return respx.get(APERCU).mock(return_value=httpx.Response(200, content=route_contenu, **kw))


@respx.mock
def test_html_en_200_jamais_en_cache(app):
    route = _apercu(CAPTCHA, headers={"Content-Type": "text/html; charset=utf-8"})
    r = server.archive_image(f"{SVC}/info.json")
    assert "erreur" in r and "text/html" in r["erreur"]
    assert _fichiers(app, "iiif") == []
    assert app.journal.entries(source="iiif", statut="erreur")
    server.archive_image(f"{SVC}/info.json")
    assert route.call_count == 2  # aucun faux succès « depuis_cache »


@respx.mock
def test_html_deguise_en_jpeg_refuse(app):
    _apercu(CAPTCHA, headers={"Content-Type": "image/jpeg"})
    r = server.archive_image(f"{SVC}/info.json")
    assert "erreur" in r and "pas une image" in r["erreur"]
    assert _fichiers(app, "iiif") == []


@respx.mock
def test_apercu_tronque_refuse(app):
    _apercu(JPEG[:-2] + b"suite perdue")
    r = server.archive_image(f"{SVC}/info.json")
    assert "erreur" in r and "tronquée" in r["erreur"]
    assert _fichiers(app, "iiif") == []


@respx.mock
def test_cache_corrompu_existant_retelecharge(app):
    route = _apercu(JPEG)
    r = server.archive_image(f"{SVC}/info.json")
    chemin = r["chemin_absolu"]
    open(chemin, "wb").write(CAPTCHA)  # cache empoisonné par une version antérieure
    again = server.archive_image(f"{SVC}/info.json")
    assert again["depuis_cache"] is False and route.call_count == 2
    assert open(chemin, "rb").read() == JPEG


@respx.mock
def test_originale_tronquee_jamais_en_cache(app):
    route = respx.get(DIRECTE).mock(return_value=httpx.Response(200, content=JPEG[:-2]))
    r = server.archive_image(DIRECTE)
    assert "erreur" in r and "tronquée" in r["erreur"]
    assert _fichiers(app, "originaux") == []
    server.archive_image(DIRECTE)
    assert route.call_count == 2


@respx.mock
def test_image_trop_lourde_refusee(app, monkeypatch):
    monkeypatch.setattr(http, "MAX_IMAGE_BYTES", 8)
    _apercu(JPEG + b"\x00" * 64)
    r = server.archive_image(f"{SVC}/info.json")
    assert "erreur" in r and "trop volumineuse" in r["erreur"]
    assert _fichiers(app, "iiif") == []


def test_bombe_de_decompression_capturee(app, tmp_path, monkeypatch):
    from PIL import Image

    fichier = tmp_path / "vue.png"
    Image.new("L", (100, 100)).save(fichier)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    r = server.archive_image(str(fichier))
    assert "erreur" in r and "trop grande" in r["erreur"]


def test_bombe_de_decompression_archivage(app, tmp_path, monkeypatch):
    from PIL import Image

    fichier = tmp_path / "vue.png"
    buf = io.BytesIO()
    Image.new("L", (100, 100)).save(buf, "PNG")
    fichier.write_bytes(buf.getvalue())
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    r = server.piece_archiver(str(fichier))
    assert isinstance(r, dict)  # aucune exception ne s'échappe
