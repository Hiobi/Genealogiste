"""#8 : médias (images d'actes) envoyés à Gramps Web et liés aux citations. Faux serveur, données fictives."""

import hashlib

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed

from genealogiste_mcp import server
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom
from genealogiste_mcp.gramps.mapping import A_FICHIER, diff, gramps_to_tree, tree_to_gramps
from genealogiste_mcp.models import Citation, Media

UID_DEATH = "11111111-1111-4111-8111-111111111113"
JPEG = b"\xff\xd8\xff\xe0image-fictive-acte\xff\xd9"


def _with_media(tree):
    tree.medias["O9"] = Media(id="O9", fichier="medias/iiif/acte.jpg", format="image/jpeg", titre="Acte de décès")
    ev = next(e for p in tree.personnes.values() for e in p.evenements if e.uid == UID_DEATH)
    ev.citations.append(Citation(source="S1", page="Décès 1885, n° 3", medias=["O9"]))
    return tree


def test_citation_media_gedcom_round_trip(tree):
    text = write_gedcom(_with_media(tree))
    assert "OBJE @O9@" in text
    back = read_gedcom(text)[0]
    ev = next(e for p in back.personnes.values() for e in p.evenements if e.uid == UID_DEATH)
    assert ev.citations[-1].medias == ["O9"]


def test_citation_media_gramps_round_trip_and_server_path_kept(tree):
    db = tree_to_gramps(_with_media(tree))
    media = next(m for m in db.all("Media").values() if m["gramps_id"] == "O9")
    cit = next(c for c in db.all("Citation").values() if c.get("page") == "Décès 1885, n° 3")
    assert cit["media_list"][0]["ref"] == media["handle"]
    assert any(a["value"] == "medias/iiif/acte.jpg" for a in media["attribute_list"])
    # le serveur a reçu le fichier : chemin et somme attribués par Gramps Web
    media.update(checksum="abc", path="abc.jpeg")
    back, _ = gramps_to_tree(db)
    assert back.medias["O9"].fichier == "medias/iiif/acte.jpg"
    ev = next(e for p in back.personnes.values() for e in p.evenements if e.uid == UID_DEATH)
    assert ev.citations[-1].medias == ["O9"]
    assert diff(db, tree_to_gramps(back, base=db)) == []  # chemin du serveur jamais écrasé


@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


@pytest.fixture
def mapp(tmp_path, fake, tree):
    seed(fake, tree)
    a = make_app(tmp_path)
    (a.config.media_dir / "iiif").mkdir(parents=True)
    (a.config.media_dir / "iiif" / "acte.jpg").write_bytes(JPEG)
    yield a
    server.set_app(None)


OPS = [{"op": "ajouter_media", "ref": "img", "fichier": "medias/iiif/acte.jpg", "format": "image/jpeg",
        "titre": "Acte de décès de Jean MARTIN"},
       {"op": "ajouter_citation", "cible": {"type": "evenement", "uid": UID_DEATH},
        "citation": {"source": "S1", "page": "Décès 1885, acte n° 3", "medias": ["$img"], "consultation": "image",
                     "type_source": "originale", "information": "primaire"}}]


def test_apply_uploads_file_and_links_citation(mapp, fake):
    p = server.arbre_proposer(OPS, "Image de l'acte de décès", "Image consultée sur la visionneuse des AD.")
    assert p["transaction_gramps"]["fichiers_a_envoyer"] == [f"O1 : medias/iiif/acte.jpg ({len(JPEG)} octets)"]
    assert not fake.files  # rien d'envoyé avant l'accord
    r = server.arbre_appliquer(p["jeton"])
    assert r["medias"]["envoyes"] == ["O1 : medias/iiif/acte.jpg"] and not r["medias"]["erreurs"]
    media = fake.find("Media", "O1")
    assert fake.files[media["handle"]] == JPEG and media["checksum"] == hashlib.md5(JPEG).hexdigest()
    cit = next(c for c in fake.objects["Citation"].values() if c.get("page") == "Décès 1885, acte n° 3")
    assert cit["media_list"][0]["ref"] == media["handle"]
    assert server.arbre_info()["medias"] == 1
    assert server.gramps_envoyer_medias()["a_envoyer"] == []  # à jour
    # écriture suivante : le média n'est ni modifié ni renvoyé
    p2 = server.arbre_proposer([{"op": "marquer_vivant", "id": "I7", "vivant": "N"}], "Décès présumé", "Né en 1795.")
    assert "Media" not in p2["transaction_gramps"]["bilan"] and "fichiers_a_envoyer" not in p2["transaction_gramps"]


def test_missing_local_file_reported(mapp, fake):
    ops = [dict(OPS[0], fichier="medias/absent.jpg")]
    p = server.arbre_proposer(ops, "Média", "Image annoncée.")
    assert p["transaction_gramps"]["fichiers_absents"] == ["O1 : medias/absent.jpg"]


def test_send_pending_files_after_the_fact(mapp, fake):
    media = {"_class": "Media", "handle": "mexist", "gramps_id": "O5", "change": 0, "private": False, "tag_list": [],
             "citation_list": [], "note_list": [], "attribute_list": [
                 {"_class": "Attribute", "private": False, "type": {"_class": "AttributeType", "value": 0,
                                                                    "string": A_FICHIER},
                  "value": "medias/iiif/acte.jpg", "citation_list": [], "note_list": []}],
             "date": None, "path": "medias/iiif/acte.jpg", "mime": "image/jpeg", "desc": "", "checksum": "",
             "thumb": None}
    fake.put(media)
    listing = server.gramps_envoyer_medias()
    assert listing["a_envoyer"] == [f"O5 : medias/iiif/acte.jpg ({len(JPEG)} octets)"] and not fake.files
    sent = server.gramps_envoyer_medias(appliquer=True)
    assert sent["envoyes"] == ["O5 : medias/iiif/acte.jpg"] and fake.files["mexist"] == JPEG
    assert server.gramps_envoyer_medias(appliquer=True)["note"] == "Rien à envoyer."


def test_upload_conflict_reported(mapp, fake):
    from genealogiste_mcp.gramps.client import ConflictError
    fake.put({"_class": "Media", "handle": "mx", "gramps_id": "O6", "change": 0, "private": False, "tag_list": [],
              "citation_list": [], "note_list": [], "attribute_list": [], "date": None,
              "path": "medias/iiif/acte.jpg", "mime": "image/jpeg", "desc": "", "checksum": "ancien", "thumb": None})
    with pytest.raises(ConflictError):
        mapp.backend.client.upload_media("mx", JPEG, "image/jpeg", "autre")
    assert "mx" not in fake.files


def test_file_mode_refuses_tool(app):
    assert "mode gramps" in server.gramps_envoyer_medias()["erreur"]


def test_unknown_media_in_citation_refused(mapp):
    ops = [{"op": "ajouter_citation", "cible": {"type": "evenement", "uid": UID_DEATH},
            "citation": {"source": "S1", "page": "x", "medias": ["O99"]}}]
    assert "média inconnu" in server.arbre_proposer(ops, "t", "j")["erreur"]
