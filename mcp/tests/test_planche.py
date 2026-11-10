"""Planche-contact (#124) : grille locale de vues AD59 avec numéros incrustés, sans API ni image réelles."""
import io
import json
from uuid import UUID

import pytest
import respx
from PIL import Image

from genealogiste_mcp import server

HOST = "https://archivesdepartementales.lenord.fr"
API = HOST + "/visualizer/api"
REGISTRE = "ark:/33518/registrefictif"


def uuid(n):
    return str(UUID(int=n))


def image_url(n):
    return f"{HOST}/images/{uuid(n)}.jpg"


def miniature_url(n):
    return f"{HOST}/images/{uuid(n)}_thumbnail.jpg"


def media(n):
    return {"uuid": uuid(n), "type": "image", "url": f"{HOST}/{REGISTRE}/{uuid(n)}",
            "location": {"original": image_url(n), "thumb": miniature_url(n), "iiif": None}}


def jpeg(taille=(1200, 800)):
    sortie = io.BytesIO()
    Image.new("RGB", taille, "white").save(sortie, "JPEG")
    return sortie.getvalue()


@pytest.fixture
def routes():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def preparer(routes, debut, fin, taille=(1200, 800), nb_vues=954):
    """API : fenêtre debut..fin (indices 0-based) et images ; liste JSON si elle commence à 0, sinon dictionnaire."""
    indices = range(debut, fin + 1)
    if debut == 0:
        fenetre = [media(i + 1) for i in indices]
    else:
        fenetre = {str(i): media(i + 1) for i in indices}
    lot = routes.get(API, params={"naan": "33518", "arkName": "registrefictif", "start": str(debut),
                                  "end": str(fin), "group": "0"}).respond(200, json=fenetre)
    routes.get(API, params={"naan": "33518", "arkName": "registrefictif", "uuid": uuid(debut + 1)}).respond(
        200, json={"counts": {"media": nb_vues}})
    images = {i + 1: routes.get(image_url(i + 1)).respond(200, content=jpeg(taille)) for i in indices}
    miniatures = {i + 1: routes.get(miniature_url(i + 1)).respond(200, content=jpeg((100, 100))) for i in indices}
    return lot, images, miniatures


def planche_image(sortie):
    assert "erreur" not in sortie, sortie
    return Image.open(sortie["chemin_absolu"])


def test_planche_liste_json_numeros_incrustes_un_telechargement_par_vue(app, routes):
    lot, images, _ = preparer(routes, 0, 3)  # fenêtre qui commence à 0 : liste JSON
    sortie = server.archives_planche(REGISTRE, de=1, a=4)
    assert sortie["vues"] == [1, 2, 3, 4] and sortie["grille"] == [2, 2] and sortie["nb_vues"] == 954
    assert sortie["telechargements"] == 4 and all(r.call_count == 1 for r in images.values())
    assert lot.call_count == 1  # une seule requête de métadonnées pour la plage
    im = planche_image(sortie)
    assert im.size == tuple(sortie["dimensions_demandees"]) and max(im.size) <= 1600
    assert sortie["cout_estime_tokens"] == round(im.width * im.height / 750)
    cellule_l, cellule_h = im.width // 2, im.height // 2
    for i in range(4):  # numéro incrusté : pastille sombre dans le coin de chaque cellule (vues blanches)
        assert im.getpixel(((i % 2) * cellule_l + 4, (i // 2) * cellule_h + 4)) < 60
    # la pastille contient du texte clair (numéro) : au moins un pixel clair dans le coin de la première cellule
    coin = im.crop((2, 2, 60, 40))
    assert coin.getextrema()[1] > 200
    # deuxième appel : tout vient du cache, aucun nouveau téléchargement
    again = server.archives_planche(REGISTRE, de=1, a=4)
    assert again["telechargements"] == 0 and all(r.call_count == 1 for r in images.values())


def test_planche_fenetre_au_milieu_en_dictionnaire(app, routes):
    _, images, _ = preparer(routes, 285, 288)
    sortie = server.archives_planche(REGISTRE, de=286, a=289)
    assert sortie["vues"] == [286, 287, 288, 289] and "vues_absentes" not in sortie
    assert all(r.call_count == 1 for r in images.values())


def test_planche_limitee_a_douze_vues_et_1600_px(app, routes):
    _, images, _ = preparer(routes, 0, 11, taille=(3000, 2000))
    sortie = server.archives_planche(REGISTRE, de=1, a=40, largeur=5000)
    assert len(sortie["vues"]) == 12 and "12 vues" in sortie["avertissement"]
    assert max(planche_image(sortie).size) <= 1600
    assert sum(r.call_count for r in images.values()) == 12  # les vues au-delà ne sont jamais téléchargées


def test_planche_pas_sonde_large(app, routes):
    _, images, _ = preparer(routes, 0, 40)
    sortie = server.archives_planche(REGISTRE, de=1, a=50, pas=10)
    assert sortie["vues"] == [1, 11, 21, 31, 41]
    assert sum(r.call_count for r in images.values()) == 5


def test_bandeau_reduit_hauteur_et_cout(app, routes):
    preparer(routes, 0, 3)
    plein = server.archives_planche(REGISTRE, de=1, a=4, largeur=800)
    bande = server.archives_planche(REGISTRE, de=1, a=4, largeur=800, bandeau="pct:0,0,100,35")
    assert bande["dimensions_demandees"][1] < plein["dimensions_demandees"][1]
    assert bande["cout_estime_tokens"] < plein["cout_estime_tokens"]
    assert "erreur" in server.archives_planche(REGISTRE, de=1, a=4, bandeau="0,0,100,35")


def test_miniatures_utilisent_thumb_sans_original(app, routes):
    _, images, miniatures = preparer(routes, 0, 3)
    sortie = server.archives_planche(REGISTRE, de=1, a=4, miniatures=True)
    assert "miniatures" in sortie["images"] and sortie["telechargements"] == 0
    assert all(r.call_count == 0 for r in images.values())
    assert all(r.call_count == 1 for r in miniatures.values())


def test_originales_partagees_avec_archive_image(app, routes):
    _, images, _ = preparer(routes, 0, 3)
    routes.get(API, params={"naan": "33518", "arkName": "registrefictif", "uuid": uuid(2)}).respond(200, json={
        "counts": {"media": 954}, "positions": {"media": 1}, "media": {"1": {
            **media(2), "record": {"arkId": {"naan": 33518, "arkName": "registrefictif"}}}}})
    server.archives_planche(REGISTRE, de=1, a=4)
    apercu = server.archive_image(f"{HOST}/{REGISTRE}/{uuid(2)}")
    assert "erreur" not in apercu, apercu
    assert images[2].call_count == 1  # la vue de la planche n'est pas retéléchargée


def test_protection_arret_explicite_sans_telechargement(app, routes):
    routes.get(API).respond(403, text="Cloudflare accès refusé")
    image = routes.get(url__regex=HOST + "/images/.*").respond(200, content=jpeg())
    sortie = server.archives_planche(REGISTRE, de=1, a=4)
    assert "erreur" in sortie and "protégé" in sortie["erreur"] and sortie["telechargements"] == 0
    assert image.call_count == 0


def test_arret_a_la_premiere_image_refusee(app, routes):
    _, images, _ = preparer(routes, 0, 3)
    routes.get(image_url(2)).respond(403)
    sortie = server.archives_planche(REGISTRE, de=1, a=4)
    assert "erreur" in sortie and sortie["telechargements"] == 1
    assert images[3].call_count == 0 and images[4].call_count == 0  # arrêt : aucune vue suivante demandée


@pytest.mark.parametrize("args", [{"de": 0}, {"de": 5, "a": 2}])
def test_planche_parametres_invalides(app, routes, args):
    assert "erreur" in server.archives_planche(REGISTRE, **args)
    assert not routes.calls


def test_planche_source_non_prise_en_charge(app, routes):
    sortie = server.archives_planche("ark:/64297/registre-inconnu", de=1, a=4)
    assert "AD59" in sortie["erreur"] and not routes.calls
    json.dumps(sortie)
