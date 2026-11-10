"""Résolution ciblée AD59, IIIF international et cache partagé ; toutes données synthétiques."""

import io
import json
from pathlib import Path

import pytest
import respx
from PIL import Image

from genealogiste_mcp import server
from genealogiste_mcp.gedcom.mapping import write_gedcom
from genealogiste_mcp.sources import iiif

HOST = "https://archivesdepartementales.lenord.fr"
UUID = "11111111-1111-4111-8111-111111111111"
ARK = f"ark:/33518/registrefictif/{UUID}"
VIEW = HOST + "/" + ARK
IMAGE = HOST + f"/images/{UUID}.jpg"
API = HOST + "/visualizer/api"
PARAMS = {"naan": "33518", "arkName": "registrefictif", "uuid": UUID}


def metadata():
    return {"counts": {"media": 3}, "positions": {"media": 1}, "media": {"1": {
        "uuid": UUID, "type": "image", "url": VIEW,
        "record": {"arkId": {"naan": 33518, "arkName": "registrefictif"},
                   "title": ["Registre fictif"], "referenceCode": ["2 E FICTIF"],
                   "period": {"boundaries": ["1800-01-01", "1810-12-31"]},
                   "locationKeywords": ["VILLERS-EN-CAUCHIES"]},
        "location": {"original": IMAGE, "iiif": None}}},
        "app": {"licenses": {"visualizer": {"text": "Licence fictive de test", "enabled": True}}},
        "contenu_inutile": "NE PAS ENVOYER AU MODELE " * 1000}


def jpeg():
    output = io.BytesIO()
    Image.new("RGB", (1200, 800), "white").save(output, "JPEG")
    return output.getvalue()


@pytest.fixture
def routes():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def _complet(app, *args, **kwargs):
    """Réponse intégrale de iiif.fetch : résolution partagée avec piece_archiver (mode, licence, URL…)."""
    return iiif.fetch(app.sctx, app.config.cache_images_dir, *args, **kwargs)


def test_vue_ark_apercu_recadrage_archivage_un_seul_telechargement(app_famille, routes):
    original = jpeg()
    api = routes.get(API, params=PARAMS).respond(200, json=metadata())
    image = routes.get(IMAGE).respond(200, content=original)
    avant = write_gedcom(app_famille.tree())
    preview = server.archive_image(VIEW)
    assert "erreur" not in preview, preview
    assert _complet(app_famille, VIEW)["mode"] == "visionneuse:visualizer_api"
    assert preview["vue"] == 2 and preview["nb_vues"] == 3 and preview["ark_vue"] == ARK
    assert preview["commune"] == "VILLERS-EN-CAUCHIES"
    assert preview["dimensions_originales"] == [1200, 800]
    assert preview["dimensions_demandees"] == [800, 533]
    assert "contenu_inutile" not in preview and len(json.dumps(preview)) < 8000
    cropped = server.archive_image(VIEW, region="pct:50,0,50,100", largeur=1500)
    assert cropped["dimensions_demandees"] == [600, 800]
    assert "résolution" in cropped["avertissement"]
    archived = server.piece_archiver(VIEW, personnes=["I1"], type_piece="N", commune="Rochefort")
    assert "erreur" not in archived, archived
    assert archived["mode"] == "visionneuse:visualizer_api" and archived["ark_vue"] == ARK
    assert archived["cote"] == "2 E FICTIF" and archived["licence"] == "Licence fictive de test"
    path = Path(archived["chemin_absolu"])
    assert path.read_bytes() == original
    assert path.parent.name == "MARTIN" and "AD59" in path.name and "p.2" in path.name
    text = path.with_suffix(".md").read_text()
    assert ARK in text and "Registre fictif" in text
    assert archived["citation_suggeree"]["page"] == "vue 2/3"
    again = server.piece_archiver(VIEW, personnes=["I1"], type_piece="N")
    assert again["deja_archivee"] and again["ark_vue"] == ARK
    assert api.call_count == image.call_count == 1
    assert write_gedcom(app_famille.tree()) == avant


@pytest.mark.parametrize("forme", ["dict", "list"])
def test_ark_registre_vue_explicite_et_deux_formes_api(app, routes, forme):
    data = metadata()
    media = data["media"]["1"]
    batch = {"1": media} if forme == "dict" else [media]
    routes.get(API, params={"naan": "33518", "arkName": "registrefictif", "start": 1, "end": 1, "group": 0}).respond(
        200, json=batch)
    routes.get(API, params=PARAMS).respond(200, json=data)
    loc = iiif.resoudre_vue(app.sctx, "ark:/33518/registrefictif", page=2)
    assert loc["vue"] == 2 and loc["nb_vues"] == 3 and loc["ark_vue"] == ARK


def test_iiif_prioritaire_si_annonce_par_visionneuse(app, routes):
    data = metadata()
    service = HOST + "/iiif/test"
    data["media"]["1"]["location"]["iiif"] = service
    routes.get(API, params=PARAMS).respond(200, json=data)
    routes.get(service + "/info.json").respond(200, json={"width": 1200, "height": 800})
    crop = routes.get(service + "/full/800,/0/gray.jpg").respond(200, content=jpeg())
    image = routes.get(IMAGE).respond(200, content=jpeg())
    result = _complet(app, VIEW)
    assert "erreur" not in result, result
    assert result["service_iiif"] == service and crop.call_count == 1 and image.call_count == 0


@pytest.mark.parametrize("defaut", ["registre", "url_privee", "position", "json_malforme"])
def test_reponse_incoherente_refusee_avant_image(app, routes, defaut):
    data = metadata()
    if defaut == "registre":
        data["media"]["1"]["record"]["arkId"]["arkName"] = "autre"
    elif defaut == "url_privee":
        data["media"]["1"]["location"]["original"] = "http://127.0.0.1/secret.jpg"
    elif defaut == "position":
        data["positions"]["media"] = 99
    else:
        data["counts"] = []
    routes.get(API, params=PARAMS).respond(200, json=data)
    image = routes.get(IMAGE).respond(200, content=jpeg())
    assert "erreur" in server.archive_image(VIEW)
    assert image.call_count == 0


def test_vue_absente_connexion_et_repli(app, routes):
    routes.get(API, params=PARAMS).respond(403, text="Cloudflare accès refusé")
    assert "Télécharger" in server.archive_image(VIEW)["erreur"]
    assert "page=N" in server.archive_image("ark:/33518/registrefictif")["erreur"]


def test_html_declare_manifest_etranger_sans_ark(app, routes):
    page = "https://archives.exemple.ch/notice/123"
    manifest = "https://archives.exemple.ch/iiif/123/manifest.json"
    service = "https://images.exemple.ch/iiif/abc"
    html = routes.get(page).respond(200, text='<html><link rel="manifest" href="/iiif/123/manifest.json"></html>')
    routes.get(manifest).respond(200, json={"label": {"fr": ["Notice fictive suisse"]},
        "rights": "https://example.org/droits-fictifs", "items": [{"items": [{"items": [{"body": {
            "id": service + "/full/max/0/default.jpg", "service": [{"id": service}]}}]}]}]})
    routes.get(service + "/info.json").respond(200, json={"width": 1200, "height": 800})
    routes.get(service + "/full/800,/0/gray.jpg").respond(200, content=jpeg())
    result = _complet(app, page)
    assert result["mode"] == "iiif" and result["titre_registre"] == "Notice fictive suisse"
    assert result["licence"] == "https://example.org/droits-fictifs" and not result["ark_vue"]
    assert "licence" not in server.archive_image(page)  # jamais dans la sortie d'archive_image
    server.archive_image(page)
    assert html.call_count == 1


def test_entree_invalide_nom_ne_declenche_aucun_telechargement(app_famille, routes):
    assert "nom_fichier" in server.piece_archiver(VIEW, personnes=["I1"], nom="MARTIN")["erreur"]
    assert "erreur" in server.piece_archiver(VIEW, nom_fichier="../test -- N.jpg")
    assert not routes.calls


def test_capacites_service_sans_generaliser_iiif(app):
    ad59 = server.archives_service(code="AD59")
    assert ad59["telechargement"]["adaptateur_disponible"] is True
    assert ad59["telechargement"]["iiif"] is False
    inconnu = server.archives_service(code="AD17")["telechargement"]
    assert inconnu["iiif"] is None and inconnu["adaptateur_disponible"] is False


def test_api_nara_non_cachee_sans_promettre_un_adaptateur(app, routes):
    url = "https://catalog.archives.gov/api/v2/records/123"
    route = routes.get(url).respond(200, json={"record": {"titre": "Notice fictive, pas un manifeste"}})
    assert "erreur" in server.archive_image(url)
    assert "erreur" in server.archive_image(url)
    assert route.call_count == 2


def test_manifest_sans_service_utilise_image_declaree(app, routes):
    url = "https://bibliotheque.exemple.org/manifest.json"
    image = "https://images.exemple.org/original?id=123"
    routes.get(url).respond(200, json={"items": [{"items": [{"items": [{"body": {
        "id": image, "type": "Image", "format": "image/jpeg"}}]}]}]})
    original = routes.get(image).respond(200, content=jpeg())
    result = _complet(app, url)
    assert "erreur" not in result, result
    assert result["mode"] == "iiif" and original.call_count == 1


def test_html_login_ou_plusieurs_manifestes_sans_exploration(app, routes):
    url = "https://archives.exemple.org/login"
    routes.get(url).respond(200, text="<html>Veuillez vous connecter</html>")
    assert "Télécharger" in server.archive_image(url)["erreur"]
    multiple = "https://archives.exemple.org/choix"
    routes.get(multiple).respond(200, text='<a href="/iiif/a/manifest">a</a><a href="/iiif/b/manifest">b</a>')
    assert "Plusieurs manifestes" in server.archive_image(multiple)["erreur"]
    assert len(routes.calls) == 2


def test_lien_iiif_explicite_prioritaire_sur_adaptateur_naan(app, routes):
    service = HOST + f"/iiif/ark:/33518/registrefictif/{UUID}"
    routes.get(service + "/info.json").respond(200, json={"width": 1200, "height": 800})
    image = routes.get(service + "/full/800,/0/gray.jpg").respond(200, content=jpeg())
    result = _complet(app, service + "/full/max/0/default.jpg")
    assert "erreur" not in result, result
    assert result["mode"] == "iiif" and image.call_count == 1


def test_objet_sonore_dans_manifest_n_est_pas_telecharge(app, routes):
    url = "https://archives.exemple.org/manifest.json"
    audio = "https://archives.exemple.org/audio.mp3"
    routes.get(url).respond(200, json={"items": [{"items": [{"items": [{"body": {
        "id": audio, "type": "Sound", "format": "audio/mpeg"}}]}]}]})
    assert "erreur" in server.archive_image(url)
    assert len(routes.calls) == 1


@pytest.mark.parametrize("region", ["pct:.,0,50,50", "0,0,0,20", "pct:0,0,0,0"])
def test_zone_invalide_refusee_avant_reseau(app, routes, region):
    assert "erreur" in server.archive_image(VIEW, region=region)
    assert not routes.calls


def test_parametres_url_iiif_et_rotation_decimale_conserves(app, routes):
    service = "https://iiif.exemple.org/image/objet"
    source = service + "/pct:10,10,50,50/400,/13.5/default.jpg?version=2"
    routes.get(service + "/info.json?version=2").respond(200, json={"width": 1200, "height": 800})
    preview = routes.get(service + "/full/800,/0/gray.jpg?version=2").respond(200, content=jpeg())
    original = routes.get(service + "/full/max/0/default.jpg?version=2").respond(200, content=jpeg())
    assert "erreur" not in server.archive_image(source)
    assert "erreur" not in server.piece_archiver(source)
    assert preview.call_count == original.call_count == 1


def test_archive_existante_retrouvee_meme_sans_api_disponible(app_famille, routes):
    api = routes.get(API, params=PARAMS).respond(200, json=metadata())
    image = routes.get(IMAGE).respond(200, content=jpeg())
    first = server.piece_archiver(VIEW)
    assert "erreur" not in first, first
    app_famille.cache.purge()
    app_famille.http.offline = True
    again = server.piece_archiver(VIEW)
    assert again["deja_archivee"] and again["ark_vue"] == ARK
    assert api.call_count == image.call_count == 1


def test_ark_image_api_ne_contient_pas_taille_rotation_qualite(app, routes):
    service = "https://gallica.bnf.fr/iiif/ark:/12148/bpt6k123/f12"
    loc = iiif.resoudre_vue(app.sctx, service + "/pct:10,20,30,40/800,/0/default.jpg")
    assert loc["vue"] == 12 and loc["ark_vue"] == "ark:/12148/bpt6k123/f12"
    assert not routes.calls


def test_manifest_ark_technique_pas_transforme_en_citation_de_vue(app_famille, routes):
    manifest = HOST + "/iiif/ark:/33518/registrefictif/manifest.json"
    service = "https://images.exemple.org/iiif/opaque"
    routes.get(manifest).respond(200, json={"items": [{"items": [{"items": [{"body": {
        "id": service + "/full/max/0/default.jpg", "service": [{"id": service}]}}]}]}]})
    routes.get(service + "/full/max/0/default.jpg").respond(200, content=jpeg())
    result = server.piece_archiver(manifest)
    assert "erreur" not in result, result
    assert result["ark_vue"] == ""
    assert "ark" not in result["citation_suggeree"]
    note = Path(result["chemin_absolu"]).with_suffix(".md").read_text()
    assert 'ark: "ark:/33518/registrefictif"' in note
    assert 'ark: "ark:/33518/registrefictif/manifest.json"' not in note


@pytest.mark.parametrize("nom", ["MARTIN Jean -- N.md", "MARTIN Jean -- N.txt"])
def test_nom_image_avec_extension_non_image_refuse_avant_reseau(app_famille, routes, nom):
    assert "erreur" in server.piece_archiver(VIEW, nom_fichier=nom)
    assert not routes.calls


def test_extension_image_incompatible_contenu_ne_cree_pas_piece(app_famille, routes):
    routes.get(IMAGE).respond(200, content=jpeg())
    result = server.piece_archiver(IMAGE, nom_fichier="MARTIN Jean -- N.png")
    assert "erreur" in result
    assert not list(app_famille.config.pieces_root.rglob("*.png"))


def test_erreur_de_resolution_tracee_au_journal(app, routes):
    routes.get(API, params=PARAMS).respond(403, text="Accès refusé")
    result = server.archive_image(VIEW)
    assert "erreur" in result
    assert app.journal.entries(statut="erreur")


def _fenetre(debut, n, forme):
    """Réponse de plage de l'API : liste JSON si la fenêtre commence à 0, dictionnaire sinon (relevé AD59)."""
    media = metadata()["media"]["1"]
    medias = [json.loads(json.dumps(media)) for _ in range(n)]
    return medias if forme == "liste" else {str(debut + i): m for i, m in enumerate(medias)}


@pytest.mark.parametrize("forme", ["liste", "dict"])
def test_navigation_registre_ad59(app, routes, forme):
    """Fenêtre à l'indice 0 : liste JSON sur le service réel (#120) ; le dictionnaire reste accepté."""
    routes.get(API, params={"naan": "33518", "arkName": "registrefictif", "start": 0, "end": 2,
                            "group": 0}).respond(200, json=_fenetre(0, 3, forme))
    routes.get(API, params=PARAMS).respond(200, json=metadata())
    r = server.archives_naviguer("ark:/33518/registrefictif", page=1, pas=3)
    assert "erreur" not in r, r
    assert r["mode"] == "visionneuse:visualizer_api" and r["depot"] == "AD59"
    assert r["registre"]["titre"] == "Registre fictif" and r["registre"]["cote"] == "2 E FICTIF"
    assert r["registre"]["commune"] == "VILLERS-EN-CAUCHIES" and r["registre"]["nb_vues"] == 3
    assert [v["vue"] for v in r["vues"]] == [1, 2, 3] and all(v["ark_vue"] == ARK for v in r["vues"])


def test_navigation_fenetre_milieu_de_registre_dictionnaire(app, routes):
    """Fenêtre qui ne commence pas à 0 : dictionnaire indexé par position (non-régression)."""
    routes.get(API, params={"naan": "33518", "arkName": "registrefictif", "start": 2, "end": 3,
                            "group": 0}).respond(200, json=_fenetre(2, 2, "dict"))
    routes.get(API, params=PARAMS).respond(200, json=metadata())
    r = server.archives_naviguer("ark:/33518/registrefictif", page=3, pas=2)
    assert "erreur" not in r, r
    assert [v["vue"] for v in r["vues"]] == [3, 4] and r["fenetre"] == {"de": 3, "a": 4}


def test_navigation_fenetre_depassant_la_fin_liste_courte(app, routes):
    """Une liste plus courte que la fenêtre demandée n'est pas une erreur."""
    routes.get(API, params={"naan": "33518", "arkName": "registrefictif", "start": 0, "end": 9,
                            "group": 0}).respond(200, json=_fenetre(0, 3, "liste"))
    routes.get(API, params=PARAMS).respond(200, json=metadata())
    r = server.archives_naviguer("ark:/33518/registrefictif", page=1, pas=10)
    assert "erreur" not in r, r
    assert [v["vue"] for v in r["vues"]] == [1, 2, 3]


def test_navigation_reponse_inconnue_reste_une_erreur_explicite(app, routes):
    routes.get(API, params={"naan": "33518", "arkName": "registrefictif", "start": 0, "end": 2,
                            "group": 0}).respond(200, json={"a": {"uuid": UUID}})
    r = server.archives_naviguer("ark:/33518/registrefictif", page=1, pas=3)
    assert "erreur" in r and "pagination inattendue" in r["erreur"]


def test_vue_proche_du_debut_media_en_liste(app_famille, routes):
    """Vue de position 1 : `media` est une liste depuis l'indice 0 sur le service réel (#120)."""
    data = metadata()
    voisin = json.loads(json.dumps(data["media"]["1"]))
    voisin["uuid"] = "22222222-2222-4222-8222-222222222222"
    data["media"] = [voisin, data["media"]["1"]]
    routes.get(API, params=PARAMS).respond(200, json=data)
    routes.get(IMAGE).respond(200, content=jpeg())
    preview = server.archive_image(VIEW)
    assert "erreur" not in preview, preview
    assert preview["vue"] == 2 and preview["ark_vue"] == ARK


def test_vue_par_page_1_reponse_liste(app_famille, routes):
    """`page=1` : start=end=0, l'API renvoie une liste d'un élément."""
    routes.get(API, params={"naan": "33518", "arkName": "registrefictif", "start": 0, "end": 0,
                            "group": 0}).respond(200, json=[metadata()["media"]["1"]])
    data = metadata()
    data["positions"]["media"] = 0
    data["media"] = [data["media"]["1"]]
    routes.get(API, params=PARAMS).respond(200, json=data)
    routes.get(IMAGE).respond(200, content=jpeg())
    preview = server.archive_image("ark:/33518/registrefictif", page=1)
    assert "erreur" not in preview, preview
    assert preview["vue"] == 1


def test_navigation_manifest_iiif(app, routes):
    url = "https://archives.exemple.org/manifest.json"
    service = "https://images.exemple.org/iiif/abc"
    manifest = {"label": {"fr": ["Registre fictif suisse"]},
                "items": [{"items": [{"items": [{"body": {"id": service + "/full/max/0/default.jpg",
                                                            "service": [{"id": service}]}}]}]} for _ in range(4)]}
    routes.get(url).respond(200, json=manifest)
    r = server.archives_naviguer(url)
    assert "erreur" not in r, r
    assert r["mode"] == "iiif:manifeste" and r["registre"]["nb_vues"] == 4
    assert [v["vue"] for v in r["vues"]] == [1, 2, 3, 4]
    assert all(v["service_iiif"] == service for v in r["vues"])


def test_sortie_minimale_archive_image_figee_sans_licence(app_famille, routes):
    routes.get(API, params=PARAMS).respond(200, json=metadata())
    routes.get(IMAGE).respond(200, content=jpeg())
    avant = _complet(app_famille, VIEW)  # réponse intégrale, avant filtrage
    premier = server.archive_image(VIEW)
    suivant = server.archive_image(VIEW)
    detaille = server.archive_image(VIEW, details=True)
    minimal = {"chemin_absolu", "vue", "nb_vues", "ark_vue", "dimensions_originales", "dimensions_demandees",
               "cout_estime_tokens", "registre"}
    assert set(suivant) == minimal
    assert minimal < set(premier) <= minimal | {"titre_registre", "cote", "commune", "periode"}
    assert premier["cote"] == "2 E FICTIF" and premier["commune"] == "VILLERS-EN-CAUCHIES"
    assert set(detaille) == set(premier)  # details=true rend les métadonnées du registre
    for sortie in (premier, suivant, detaille):
        texte = json.dumps(sortie, ensure_ascii=False)
        assert "licence" not in sortie and "consigne" not in sortie and "Licence fictive" not in texte
    assert "Licence fictive de test" in json.dumps(avant, ensure_ascii=False)
    # gain mesuré : taille JSON de la réponse intégrale / première réponse / réponses suivantes
    taille = {"avant": len(json.dumps(avant, ensure_ascii=False)),
              "premier": len(json.dumps(premier, ensure_ascii=False)),
              "suivant": len(json.dumps(suivant, ensure_ascii=False))}
    print("octets archive_image :", taille)
    assert taille["suivant"] < taille["avant"] * 0.5


def test_metadonnees_registre_une_fois_par_session(app_famille, routes):
    routes.get(API, params=PARAMS).respond(200, json=metadata())
    routes.get(IMAGE).respond(200, content=jpeg())
    assert "cote" in server.archive_image(VIEW)
    assert "cote" not in server.archive_image(VIEW)
    assert "cote" in server.archive_image(VIEW, details=True)
    app_famille.sctx.registres_vus.clear()  # nouvelle session
    assert "cote" in server.archive_image(VIEW)


def test_piece_archiver_garde_licence_et_reutilisation(app_famille, routes):
    routes.get(API, params=PARAMS).respond(200, json=metadata())
    routes.get(IMAGE).respond(200, content=jpeg())
    assert "licence" not in server.archive_image(VIEW)
    archive = server.piece_archiver(VIEW, personnes=["I1"], type_piece="N", commune="Rochefort")
    assert "erreur" not in archive, archive
    assert archive["licence"] == "Licence fictive de test"
    texte = Path(archive["chemin_absolu"]).with_suffix(".md").read_text(encoding="utf-8")
    assert 'reutilisation: "Licence fictive de test"' in texte and 'licence: "Licence fictive de test"' in texte
    assert "**Réutilisation** : Licence fictive de test" in texte
