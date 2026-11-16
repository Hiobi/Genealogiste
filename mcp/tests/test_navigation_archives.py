"""Contrat de navigation et disponibilité des archives (#144), données synthétiques."""

import httpx
import pytest
import respx

from genealogiste_mcp import server

HOST = "https://archivesdepartementales.lenord.fr"
API = HOST + "/visualizer/api"
REGISTRE = "ark:/33518/registrefictif"
UUID = "11111111-1111-4111-8111-111111111111"
PARAMS = {"naan": "33518", "arkName": "registrefictif"}
MANIFEST = "https://archives.exemple.org/manifest.json"


@pytest.fixture
def routes():
    with respx.mock(assert_all_called=False) as router:
        yield router


def media(image="/images/vue.jpg"):
    return {"uuid": UUID, "url": HOST + "/" + REGISTRE + "/" + UUID,
            "location": {"original": image}, "record": {"title": ["Registre fictif"]}}


def mock_iiif(routes):
    routes.get(MANIFEST).respond(200, json={"label": "Registre fictif", "items": [
        {"items": [{"items": [{"body": {"id": HOST + "/images/vue.jpg", "type": "Image"}}]}]}
        for _ in range(3)]})


def mock_ad59(routes, page=1, pas=2, image="/images/vue.jpg", count=3):
    debut = max(0, page - 1)
    batch = {str(i): media(image) for i in range(debut, min(count, debut + pas))}
    routes.get(API, params={**PARAMS, "start": debut, "end": debut + pas - 1, "group": 0}).respond(200, json=batch)
    # Une fenêtre vide oblige à trouver une première vue pour obtenir counts.media.
    routes.get(API, params={**PARAMS, "start": 0, "end": 0, "group": 0}).respond(200, json=[media(image)])
    routes.get(API, params={**PARAMS, "uuid": UUID}).respond(200, json={"counts": {"media": count}})


@pytest.mark.parametrize("provider", ["iiif", "ad59", "gallica"])
@pytest.mark.parametrize("page,pas,fin,suivante", [(1, 2, False, 3), (3, 2, True, None), (0, 20, True, None)])
def test_navigation_annonce_total_fin_et_suite(app, routes, provider, page, pas, fin, suivante):
    if provider == "ad59":
        mock_ad59(routes, page, pas)
        source = REGISTRE
    else:
        mock_iiif(routes)
        source = MANIFEST
        if provider == "gallica":
            source = "ark:/12148/registrefictif"
            routes.get("https://gallica.bnf.fr/iiif/" + source + "/manifest.json").respond(
                200, json={"items": [{"items": [{"items": [{"body": {"type": "Image", "id": HOST + "/vue.jpg"}}]}]} for _ in range(3)]})
    result = server.archives_naviguer(source, page=page, pas=pas)
    assert "erreur" not in result, result
    assert result["nb_vues"] == result["registre"]["nb_vues"] == 3
    assert result["fin_de_registre"] is fin
    assert result["vue_suivante"] == suivante


@pytest.mark.parametrize("provider", ["iiif", "ad59"])
@pytest.mark.parametrize("page", [-1, 4])
def test_hors_bornes_explicite_avec_bornes_valides(app, routes, provider, page):
    if provider == "ad59":
        mock_ad59(routes, page, 2)
        source = REGISTRE
    else:
        mock_iiif(routes)
        source = MANIFEST
    result = server.archives_naviguer(source, page=page, pas=2)
    assert "hors" in result["erreur"].lower(), result
    assert "1" in result["erreur"] and "3" in result["erreur"]


@pytest.mark.parametrize("provider", ["iiif", "ad59"])
def test_une_entree_par_navigation_et_cache(app, routes, provider):
    if provider == "ad59":
        mock_ad59(routes)
        source = REGISTRE
    else:
        mock_iiif(routes)
        source = MANIFEST
    for cached in [False, True]:
        avant = len(app.journal.entries())
        result = server.archives_naviguer(source, page=1, pas=2)
        entries = app.journal.entries()
        assert len(entries) == avant + 1
        entry = next(e for e in entries if e["id"] == result["journal"])
        assert entry["operation"] == "naviguer" and entry["source"] == "archives"
        assert bool(entry["cache"]) is cached
        assert result["depuis_cache"] is cached
    assert len(routes.calls) == (2 if provider == "ad59" else 1)


@pytest.mark.parametrize("image", ["https://tiers.example/vue.jpg", "http://127.0.0.1/secret", "//tiers.example/vue.jpg", HOST + ":444/vue.jpg", "https://user:secret@archivesdepartementales.lenord.fr/vue.jpg"])
def test_navigation_refuse_image_hors_origine(app, routes, image):
    mock_ad59(routes, image=image)
    result = server.archives_naviguer(REGISTRE, pas=2)
    assert "erreur" in result, result
    assert len(app.journal.entries()) == 1


def test_navigation_normalise_image_relative(app, routes):
    mock_ad59(routes)
    result = server.archives_naviguer(REGISTRE, pas=2)
    assert result["vues"][0]["url_image"] == HOST + "/images/vue.jpg"


def test_navigation_iiif_v2_conserve_les_metadonnees_et_la_fin(app, routes):
    routes.get(MANIFEST).respond(200, json={"label": "Registre fictif", "license": "Licence fictive",
        "sequences": [{"canvases": [{"label": "Vue 1", "images": [{"resource": {
            "@id": HOST + "/vue.jpg", "service": {"@id": HOST + "/iiif/vue"}}}]}]}]})
    result = server.archives_naviguer(MANIFEST)
    assert result["nb_vues"] == 1 and result["fin_de_registre"] is True
    assert result["vue_suivante"] is None
    assert result["registre"]["licence"] == "Licence fictive"
    assert result["vues"][0]["service_iiif"] == HOST + "/iiif/vue"


def test_navigation_echec_api_une_seule_entree(app, routes):
    routes.get(API).respond(403, text="Accès refusé")
    result = server.archives_naviguer(REGISTRE)
    assert "erreur" in result
    assert len(app.journal.entries()) == 1
    assert app.journal.entries()[0]["id"] == result["journal"]


class CorpsInterdit(httpx.SyncByteStream):
    def __init__(self):
        self.closed = False

    def __iter__(self):
        pytest.fail("Le repli de disponibilité ne doit pas lire le corps GET")
        yield b""  # pragma: no cover

    def close(self):
        self.closed = True


@pytest.mark.parametrize("status", [405, 501])
def test_head_non_pris_en_charge_repli_get_sans_lire_le_corps(app, routes, status):
    url = HOST + "/" + REGISTRE
    routes.head(url).respond(status)
    corps = CorpsInterdit()
    route = routes.get(url).respond(200, stream=corps, headers={"Content-Length": "99999999999"})
    routes.head("https://n2t.net/" + REGISTRE).respond(200)
    result = server.ark_resoudre(url)
    assert result["disponibilite"]["accessible"] is True, result
    assert route.called and corps.closed


@pytest.mark.parametrize("status", [200, 403, 404, 500])
def test_repli_get_redirige_et_erreurs_sans_lire_le_corps(app, routes, status):
    url = HOST + "/" + REGISTRE
    destination = HOST + "/notice/registre"
    routes.head(url).respond(405)
    redirection, corps = CorpsInterdit(), CorpsInterdit()
    routes.get(url).respond(302, stream=redirection, headers={"Location": destination})
    routes.get(destination).respond(status, stream=corps)
    routes.head("https://n2t.net/" + REGISTRE).respond(200)
    result = server.ark_resoudre(url)
    assert result["disponibilite"]["accessible"] is (status == 200)
    if status >= 400:
        assert result["disponibilite"]["statut_http"] == status
    assert redirection.closed and corps.closed


def test_repli_get_conserve_la_politique_reseau(app, routes):
    url = HOST + "/" + REGISTRE
    routes.head(url).respond(501)
    redirection = CorpsInterdit()
    routes.get(url).respond(302, stream=redirection, headers={"Location": "http://127.0.0.1/secret"})
    routes.head("https://n2t.net/" + REGISTRE).respond(200)
    result = server.ark_resoudre(url)
    assert result["disponibilite"]["accessible"] is False
    assert len(routes.calls) == 3 and redirection.closed


@pytest.mark.parametrize("count", [None, "3", 0, True])
def test_navigation_total_inconnu_ou_invalide_est_une_erreur(app, routes, count):
    mock_ad59(routes)
    routes.get(API, params={**PARAMS, "uuid": UUID}).respond(200, json={"counts": {"media": count}})
    result = server.archives_naviguer(REGISTRE, pas=2)
    assert "erreur" in result
    assert len(app.journal.entries()) == 1


def test_gallica_capacites_coherentes(app):
    cap = server.archives_service(code="BnF")["telechargement"]
    assert cap["iiif"] is True
    assert cap["adaptateur_disponible"] is True
    assert cap["etat"] == "automatique"
