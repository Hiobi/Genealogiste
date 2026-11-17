"""#193 : modifier un média (fichier, titre, format, citations) et relocaliser les chemins après un changement de
machine, en deux temps (proposition → accord → application). Faux serveur Gramps Web, données fictives."""

import hashlib
import json

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed

from genealogiste_mcp import server
from genealogiste_mcp.gramps.mapping import A_FICHIER, _attr_value

JPEG = b"\xff\xd8\xff\xe0image-fictive-acte\xff\xd9"
JPEG_HD = b"\xff\xd8\xff\xe0image-fictive-acte-haute-definition\xff\xd9"
ANCIEN = "/ancienne/racine/vault/"


def _ecrire(base, rel: str, data: bytes = JPEG):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _media_gramps(handle: str, gid: str, fichier: str, checksum: str = "", path: str = "") -> dict:
    """Média tel que Gramps Web le renvoie : chemin attribué par le serveur, fichier local dans Sosa-Fichier."""
    return {"_class": "Media", "handle": handle, "gramps_id": gid, "change": 0, "private": False, "tag_list": [],
            "citation_list": [], "note_list": [], "attribute_list": [
                {"_class": "Attribute", "private": False, "type": {"_class": "AttributeType", "value": 0,
                                                                   "string": A_FICHIER},
                 "value": fichier, "citation_list": [], "note_list": []}],
            "date": None, "path": path or fichier, "mime": "image/jpeg", "desc": f"Acte {gid}",
            "checksum": checksum, "thumb": None}


# ============================================================================ backend fichier

@pytest.fixture
def fapp(app_famille):
    _ecrire(app_famille.config.media_dir, "iiif/acte.jpg")
    p = server.arbre_proposer([{"op": "ajouter_media", "fichier": "medias/iiif/acte.jpg", "format": "image/jpeg",
                                "titre": "Acte"}], "Média", "Image de l'acte.")
    assert "erreur" not in p, p
    server.arbre_appliquer(p["jeton"])
    return app_famille


def test_modifier_media_fichier_titre(fapp):
    _ecrire(fapp.config.media_dir, "actes/acte-hd.jpg", JPEG_HD)
    p = server.arbre_proposer([{"op": "modifier_media", "id": "O1",
                                "champs": {"fichier": "actes/acte-hd.jpg", "titre": "Acte (HD)"}}],
                              "Image HD", "Version haute définition de l'acte.")
    assert "erreur" not in p, p
    assert any("medias/iiif/acte.jpg → medias/actes/acte-hd.jpg" in s for s in p["resume"]), p["resume"]
    assert any("Acte (HD)" in s for s in p["resume"])
    assert "medias/actes/acte-hd.jpg" in p["diff"]
    server.arbre_appliquer(p["jeton"])
    m = fapp.tree().medias["O1"]
    assert (m.fichier, m.titre, m.format) == ("medias/actes/acte-hd.jpg", "Acte (HD)", "image/jpeg")


def test_modifier_media_extension_changee_format_recalcule(fapp):
    _ecrire(fapp.config.media_dir, "acte.pdf", b"%PDF-1.4 fictif")
    p = server.arbre_proposer([{"op": "modifier_media", "id": "O1", "champs": {"fichier": "medias/acte.pdf"}}],
                              "PDF", "Acte numérisé en PDF.")
    server.arbre_appliquer(p["jeton"])
    assert fapp.tree().medias["O1"].format != "image/jpeg"  # ancien format effacé, déduit de l'extension


def test_modifier_media_citations_ajout(fapp):
    p = server.arbre_proposer([{"op": "modifier_media", "id": "O1", "citations_ajout": [
        {"source": "S1", "page": "vue 12", "consultation": "image"}]}], "Citation", "Image de la vue 12.")
    assert "erreur" not in p, p
    server.arbre_appliquer(p["jeton"])
    assert [c.page for c in fapp.tree().medias["O1"].citations] == ["vue 12"]


@pytest.mark.parametrize(("op", "attendu"), [
    ({"id": "O1", "champs": {"date": "1885"}}, "date"),
    ({"id": "O1", "champs": {"auteur": "x"}}, "auteur"),
    ({"id": "O99", "champs": {"titre": "x"}}, "O99"),
    ({"id": "O1", "champs": {"fichier": "medias/absent.jpg"}}, "introuvable"),
    ({"id": "O1", "champs": {"fichier": "/etc/passwd"}}, "hors"),
    ({"id": "O1", "champs": {"fichier": ""}}, "fichier"),
    ({"id": "O1"}, "rien"),
])
def test_modifier_media_refus(fapp, op, attendu):
    p = server.arbre_proposer([{"op": "modifier_media", **op}], "t", "j")
    assert attendu in p.get("erreur", ""), p


def test_modifier_media_date_refus_explicite(fapp):
    err = server.arbre_proposer([{"op": "modifier_media", "id": "O1", "champs": {"date": "1885"}}], "t", "j")["erreur"]
    assert "date" in err and "citation" in err  # l'erreur oriente vers la date de l'acte (citation, événement)


def test_relocaliser_mode_fichier(fapp):
    """Mode fichier : même outil, contrôle d'existence (pas de somme Gramps à comparer)."""
    p0 = server.arbre_proposer([{"op": "modifier_media", "id": "O1",
                                 "champs": {"fichier": "medias/iiif/acte.jpg", "titre": "x"}}], "t", "j")
    assert "erreur" not in p0
    server.arbre_annuler_proposition(p0["jeton"])
    _ecrire(fapp.config.media_dir, "classes/iiif/acte.jpg")
    r = server.gramps_relocaliser_medias("medias/iiif/", "medias/classes/iiif/")
    assert r["a_relocaliser"] == ["O1 : medias/iiif/acte.jpg → medias/classes/iiif/acte.jpg"], r
    server.arbre_appliquer(r["jeton"])
    assert fapp.tree().medias["O1"].fichier == "medias/classes/iiif/acte.jpg"


def test_relocaliser_rien(fapp):
    r = server.gramps_relocaliser_medias("/nulle/part/", "medias/")
    assert "jeton" not in r and "Aucun média" in r["note"]


def test_relocaliser_prefixe_vide_refuse(fapp):
    assert "erreur" in server.gramps_relocaliser_medias("", "medias/")


# ============================================================================ backend Gramps Web

@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


@pytest.fixture
def gapp(tmp_path, fake, tree):
    seed(fake, tree)
    a = make_app(tmp_path)
    yield a
    server.set_app(None)


def _envoye(fake, gapp, rel="iiif/acte.jpg"):
    """Média O1 créé par le plugin et son fichier reçu par Gramps Web (chemin et somme attribués par le serveur)."""
    _ecrire(gapp.config.media_dir, rel)
    p = server.arbre_proposer([{"op": "ajouter_media", "fichier": f"medias/{rel}", "format": "image/jpeg",
                                "titre": "Acte"}], "Média", "Image de l'acte.")
    server.arbre_appliquer(p["jeton"])
    media = fake.find("Media", "O1")
    assert media["checksum"] == hashlib.md5(JPEG).hexdigest() and media["path"] != f"medias/{rel}"
    return media


def test_gramps_deplacement_meme_fichier_sans_envoi(gapp, fake):
    avant = _envoye(fake, gapp)
    _ecrire(gapp.config.media_dir, "classes/acte.jpg")
    p = server.arbre_proposer([{"op": "modifier_media", "id": "O1", "champs": {"fichier": "medias/classes/acte.jpg"}}],
                              "Déplacement", "Pièce classée.")
    assert "erreur" not in p, p
    assert not p["transaction_gramps"].get("fichiers_a_envoyer")  # même contenu : rien à renvoyer
    r = server.arbre_appliquer(p["jeton"])
    assert "medias" not in r and "avertissement" not in r, r
    media = fake.find("Media", "O1")
    assert _attr_value(media, A_FICHIER) == "medias/classes/acte.jpg"
    assert (media["path"], media["checksum"]) == (avant["path"], avant["checksum"])  # fichier serveur conservé
    assert server.gramps_envoyer_medias()["a_envoyer"] == []


def test_gramps_remplacement_image_envoyee(gapp, fake):
    avant = _envoye(fake, gapp)
    _ecrire(gapp.config.media_dir, "iiif/acte-hd.jpg", JPEG_HD)
    p = server.arbre_proposer([{"op": "modifier_media", "id": "O1",
                                "champs": {"fichier": "medias/iiif/acte-hd.jpg", "titre": "Acte (HD)"}}],
                              "Image HD", "Version haute définition.")
    assert p["transaction_gramps"]["fichiers_a_envoyer"] == [f"O1 : medias/iiif/acte-hd.jpg ({len(JPEG_HD)} octets)"]
    assert fake.files[avant["handle"]] == JPEG  # rien d'envoyé avant l'accord
    r = server.arbre_appliquer(p["jeton"])
    assert r["medias"]["envoyes"] == ["O1 : medias/iiif/acte-hd.jpg"] and not r["medias"]["erreurs"], r
    media = fake.find("Media", "O1")
    assert fake.files[media["handle"]] == JPEG_HD and media["checksum"] == hashlib.md5(JPEG_HD).hexdigest()
    assert media["desc"] == "Acte (HD)"


def test_gramps_relocaliser_medias(gapp, fake):
    md5 = hashlib.md5(JPEG).hexdigest()
    fake.put(_media_gramps("m1", "O1", ANCIEN + "documents/a.jpg", md5, f"{md5}.jpeg"))
    fake.put(_media_gramps("m2", "O2", ANCIEN + "documents/absent.jpg", "x" * 32, "x.jpeg"))
    fake.put(_media_gramps("m3", "O3", ANCIEN + "documents/autre.jpg", md5, f"{md5}.jpeg"))
    fake.put(_media_gramps("m4", "O4", ANCIEN + "documents/neuf.jpg"))  # jamais envoyé : pas de somme
    fake.put(_media_gramps("m5", "O5", "/ailleurs/b.jpg", md5, f"{md5}.jpeg"))  # hors préfixe : intact
    _ecrire(gapp.config.media_dir, "documents/a.jpg")
    _ecrire(gapp.config.media_dir, "documents/autre.jpg", JPEG_HD)
    _ecrire(gapp.config.media_dir, "documents/neuf.jpg", JPEG_HD)

    r = server.gramps_relocaliser_medias(ANCIEN, "medias/")
    assert "erreur" not in r, r
    assert r["a_relocaliser"] == [f"O1 : {ANCIEN}documents/a.jpg → medias/documents/a.jpg",
                                  f"O4 : {ANCIEN}documents/neuf.jpg → medias/documents/neuf.jpg"]
    assert [x.split(" :")[0] for x in r["introuvables"]] == ["O2"]
    assert [x.split(" :")[0] for x in r["md5_differents"]] == ["O3"]
    assert r["transaction_gramps"]["fichiers_a_envoyer"] == [f"O4 : medias/documents/neuf.jpg ({len(JPEG_HD)} octets)"]
    assert _attr_value(fake.find("Media", "O1"), A_FICHIER).startswith(ANCIEN)  # rien d'écrit avant l'accord

    out = server.arbre_appliquer(r["jeton"])
    assert "erreur" not in out, out
    assert _attr_value(fake.find("Media", "O1"), A_FICHIER) == "medias/documents/a.jpg"
    assert fake.find("Media", "O1")["path"] == f"{md5}.jpeg"
    assert _attr_value(fake.find("Media", "O2"), A_FICHIER).startswith(ANCIEN)
    assert _attr_value(fake.find("Media", "O3"), A_FICHIER).startswith(ANCIEN)
    assert _attr_value(fake.find("Media", "O5"), A_FICHIER) == "/ailleurs/b.jpg"
    assert fake.files["m4"] == JPEG_HD
    # une seule transaction, journalisée et annulable
    lignes = [json.loads(x) for x in (gapp.config.data_dir / "gramps-transactions.jsonl").read_text().splitlines()]
    assert [x["etat"] for x in lignes if x["id"] == r["jeton"]][-1] == "terminee"
    annul = server.arbre_annuler_modification(r["jeton"])
    assert "erreur" not in annul, annul


def test_relocaliser_prefixe_borne_au_dossier(fapp):
    """« medias/ii » ne doit pas capter « medias/iiif/… » ; sans « / » final, le dossier reste reconnu."""
    assert fapp.tree().medias["O1"].fichier == "medias/iiif/acte.jpg"
    assert "Aucun média" in server.gramps_relocaliser_medias("medias/ii", "medias/classes")["note"]
    _ecrire(fapp.config.media_dir, "classes/iiif/acte.jpg")
    r = server.gramps_relocaliser_medias("medias/iiif", "medias/classes/iiif")
    assert r["a_relocaliser"] == ["O1 : medias/iiif/acte.jpg → medias/classes/iiif/acte.jpg"], r
    server.arbre_annuler_proposition(r["jeton"])


def test_relocaliser_racine_refusee(fapp):
    assert "erreur" in server.gramps_relocaliser_medias("/", "medias/")
