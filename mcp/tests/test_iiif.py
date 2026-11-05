"""Images IIIF : résolution des vues, taille et zone demandées, cache fichier, coût estimé (respx, fictif)."""

import httpx
import respx

from genealogiste_mcp import server
from genealogiste_mcp.sources import iiif

JPEG = b"\xff\xd8\xff\xe0fictif\xff\xd9"
SVC = "https://iiif.exemple.org/image/registre-1926/vue-12"
INFO = {"@context": "http://iiif.io/api/image/2/context.json", "@id": SVC, "protocol": "http://iiif.io/api/image",
        "width": 4000, "height": 3000, "profile": ["http://iiif.io/api/image/2/level2.json"]}
MANIFEST_V2 = {"@context": "http://iiif.io/api/presentation/2/context.json", "sequences": [{"canvases": [
    {"label": f"Vue {i}", "images": [{"resource": {"service": {"@id": f"https://iiif.exemple.org/image/r/v{i}"}}}]}
    for i in (1, 2, 3)]}]}
MANIFEST_V3 = {"@context": "http://iiif.io/api/presentation/3/context.json", "items": [
    {"label": {"fr": [f"Vue {i}"]}, "items": [{"items": [{"body": {
        "service": [{"id": f"https://iiif.exemple.org/image/r3/v{i}"}]}}]}]} for i in (1, 2)]}


def test_canvases_v2_v3():
    assert [c["service"] for c in iiif.canvases(MANIFEST_V2)][1] == "https://iiif.exemple.org/image/r/v2"
    assert iiif.canvases(MANIFEST_V3)[1] == {"label": "Vue 2", "service": "https://iiif.exemple.org/image/r3/v2"}


def test_image_url_and_region_validation():
    assert iiif.image_url(SVC, "pct:10,20,50,30", 1500, True) == f"{SVC}/pct:10,20,50,30/1500,/0/gray.jpg"
    try:
        iiif.image_url(SVC, "n'importe quoi")
    except iiif.IiifError:
        pass
    else:
        raise AssertionError


@respx.mock
def test_preview_then_crop_with_cost_and_cache(app):
    respx.get(f"{SVC}/info.json").mock(return_value=httpx.Response(200, json=INFO))
    prev = respx.get(f"{SVC}/full/800,/0/gray.jpg").mock(return_value=httpx.Response(200, content=JPEG))
    r = server.archive_image(f"{SVC}/info.json")
    assert r["dimensions_demandees"] == [800, 600] and r["cout_estime_tokens"] == 640
    assert open(r["chemin_absolu"], "rb").read() == JPEG and r["fichier"].startswith("cache-images/iiif/")
    again = server.archive_image(f"{SVC}/info.json")
    assert again["depuis_cache"] is True and prev.call_count == 1  # jamais retéléchargée
    crop = respx.get(f"{SVC}/pct:10,20,50,30/1500,/0/gray.jpg").mock(return_value=httpx.Response(200, content=JPEG))
    c = server.archive_image(SVC + "/full/800,/0/gray.jpg", region="pct:10,20,50,30", largeur=1500)
    assert crop.called and c["dimensions_demandees"] == [1500, 675]
    assert server.journal_lister(source="iiif")[-1]["operation"] == "image"


@respx.mock
def test_manifest_page_and_gray_fallback(app):
    url = "https://iiif.exemple.org/manifeste/registre.json"
    respx.get(url).mock(return_value=httpx.Response(200, json=MANIFEST_V2))
    base = "https://iiif.exemple.org/image/r/v2"
    respx.get(f"{base}/info.json").mock(return_value=httpx.Response(404))
    respx.get(f"{base}/full/800,/0/gray.jpg").mock(return_value=httpx.Response(400))
    respx.get(f"{base}/full/800,/0/default.jpg").mock(return_value=httpx.Response(200, content=JPEG))
    r = server.archive_image(url, page=2)
    assert r["vue"] == 2 and r["nb_vues"] == 3 and r["url_image"].endswith("default.jpg")
    assert "cout_estime_tokens" not in r  # dimensions inconnues
    assert "hors du manifeste" in server.archive_image(url, page=9)["erreur"]


@respx.mock
def test_gallica_ark_and_width_cap(app):
    base = "https://gallica.bnf.fr/iiif/ark:/12148/bpt6k5619759j/f12"
    respx.get(f"{base}/info.json").mock(return_value=httpx.Response(200, json={**INFO, "@id": base}))
    img = respx.get(f"{base}/full/2000,/0/gray.jpg").mock(return_value=httpx.Response(200, content=JPEG))
    r = server.archive_image("https://gallica.bnf.fr/ark:/12148/bpt6k5619759j/f12.item", largeur=5000)
    assert img.called and r["vue"] == 12 and r["manifeste"].endswith("/manifest.json")


def test_archives_ark_without_iiif_asks_for_link(app):
    r = server.archive_image("https://archivesdepartementales.lenord.fr/ark:/33518/48150m2qjdhb/"
                             "7eb8efac-a2f7-4356-bf7a-bfe1f1ea91b7")
    assert "Copier le lien IIIF" in r["erreur"]


# ---------------------------------------------------------------------------- sans IIIF : recadrage local

def _image(path, w=3000, h=2000):
    from PIL import Image
    Image.new("RGB", (w, h), (200, 180, 150)).save(path, "JPEG")
    return path


def test_local_file_preview_and_crop(app, tmp_path):
    src = _image(tmp_path / "vue.jpg")
    r = server.archive_image(str(src))
    assert r["mode"].startswith("local") and r["dimensions_demandees"] == [800, 533]
    assert r["cout_estime_tokens"] == round(800 * 533 / 750) and r["dimensions_originales"] == [3000, 2000]
    c = server.archive_image(str(src), region="pct:50,50,50,50", largeur=1500)
    assert c["zone_pixels"] == [1500, 1000, 3000, 2000] and c["dimensions_demandees"] == [1500, 1000]
    small = server.archive_image(str(src), region="0,0,600,400", largeur=1500)
    assert small["dimensions_demandees"] == [600, 400]  # jamais agrandie
    assert server.archive_image(str(src))["depuis_cache"] is True
    from PIL import Image
    assert Image.open(r["chemin_absolu"]).mode == "L"


@respx.mock
def test_direct_image_url_downloaded_once(app, tmp_path):
    data = _image(tmp_path / "o.jpg").read_bytes()
    url = "https://archives.exemple.org/images/7eb8efac.jpg"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=data))
    r = server.archive_image(url)
    assert r["original_telecharge"] is True and route.call_count == 1
    server.archive_image(url, region="pct:0,0,50,50", largeur=1200)
    assert route.call_count == 1  # originale gardée dans medias/originaux/


@respx.mock
def test_direct_image_blocked_suggests_manual_download(app):
    url = "https://archives.exemple.org/images/x.jpg"
    respx.get(url).mock(return_value=httpx.Response(403))
    assert "Télécharger l'image depuis la visionneuse" in server.archive_image(url)["erreur"]
