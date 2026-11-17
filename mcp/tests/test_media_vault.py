"""#192 : média à chemin relatif au vault (GENEALOGISTE_MEDIA_DIR hors des données) résolu, confiné et envoyé."""

from pathlib import Path

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import URL, seed

from genealogiste_mcp import server
from genealogiste_mcp.config import Config
from genealogiste_mcp.gramps.backend import media_pending
from genealogiste_mcp.gramps.mapping import GrampsDb

WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 image-fictive"
RELATIF = "documents/État civil/MARTIN/naissance MARTIN Jean.webp"


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    f = v / RELATIF
    f.parent.mkdir(parents=True)
    f.write_bytes(WEBP)
    return v


def _op(fichier: str) -> list[dict]:
    return [{"op": "ajouter_media", "fichier": fichier, "format": "image/webp", "titre": "Naissance"}]


# ---------------------------------------------------------------- envoi vers Gramps Web

@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


@pytest.fixture
def gvault(tmp_path, fake, tree, vault):
    seed(fake, tree)
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend="gramps",
                 gramps_url=URL, gramps_user="sosa", gramps_password="secret", gramps_ttl=0,
                 media_dir_conf=vault / "documents")
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    yield a
    server.set_app(None)


def test_media_relatif_au_vault_envoye(gvault, fake, vault):
    p = server.arbre_proposer(_op(RELATIF), "Image", "Acte de naissance archivé dans le vault.")
    assert "erreur" not in p, p
    tx = p["transaction_gramps"]
    assert "fichiers_absents" not in tx
    assert tx["fichiers_a_envoyer"] == [f"O1 : {vault / RELATIF} ({len(WEBP)} octets)"]
    r = server.arbre_appliquer(p["jeton"])
    assert not r["medias"]["erreurs"]
    assert fake.files[fake.find("Media", "O1")["handle"]] == WEBP
    assert server.gramps_envoyer_medias()["absents_en_local"] == []


def _db(chemin: str) -> GrampsDb:
    db = GrampsDb()
    db.put({"_class": "Media", "handle": "h1", "gramps_id": "O1", "path": chemin, "mime": "image/webp",
            "checksum": "", "attribute_list": []})
    return db


def test_media_pending_reference_relative_existante_repli_sur_vault(tmp_path, vault):
    """Médias déjà créés avec un chemin relatif au vault (avant la normalisation) : retrouvés à l'envoi."""
    data = tmp_path / "donnees"
    data.mkdir()
    todo, missing = media_pending(_db(RELATIF), data, None, vault)
    assert [t["chemin"] for t in todo] == [str(vault / RELATIF)] and missing == []


def test_media_pending_absent_partout(tmp_path, vault):
    data = tmp_path / "donnees"
    data.mkdir()
    todo, missing = media_pending(_db("documents/absent.webp"), data, None, vault)
    assert todo == [] and missing == ["O1 : documents/absent.webp"]


@pytest.mark.parametrize("chemin", ["../secret.env", "documents/../../secret.env"])
def test_media_pending_traversee_hors_racines_refusee(tmp_path, vault, chemin):
    data = tmp_path / "donnees"
    data.mkdir()
    (tmp_path / "secret.env").write_text("TOKEN=xyz")
    todo, missing = media_pending(_db(chemin), data, None, vault)
    assert todo == [] and any("refusé" in m for m in missing)


# ---------------------------------------------------------------- normalisation à la proposition

@pytest.fixture
def fvault(app_famille, vault):
    app_famille.config.media_dir_conf = vault / "documents"
    return app_famille



def test_ajouter_media_relatif_normalise_en_reference(fvault, vault):
    p = server.arbre_proposer(_op(RELATIF), "Image", "Acte archivé.")
    assert "erreur" not in p, p
    server.arbre_appliquer(p["jeton"])
    fichiers = [m.fichier for m in fvault.tree().medias.values()]
    assert str(vault / RELATIF) in fichiers


def test_ajouter_media_relatif_au_repertoire_des_medias(fvault, vault):
    p = server.arbre_proposer(_op("État civil/MARTIN/naissance MARTIN Jean.webp"), "Image", "Acte archivé.")
    assert "erreur" not in p, p
    server.arbre_appliquer(p["jeton"])
    assert str(vault / RELATIF) in [m.fichier for m in fvault.tree().medias.values()]


def test_ajouter_media_dans_les_donnees_reste_relatif(app_famille):
    f = app_famille.config.media_dir / "acte.jpg"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"img")
    p = server.arbre_proposer(_op("acte.jpg"), "Image", "Acte.")
    assert "erreur" not in p, p
    server.arbre_appliquer(p["jeton"])
    assert "medias/acte.jpg" in [m.fichier for m in app_famille.tree().medias.values()]


def test_ajouter_media_fichier_introuvable_refuse(fvault):
    avant = fvault.store.path.read_bytes()
    p = server.arbre_proposer(_op("documents/absent.webp"), "Image", "Acte.")
    assert "introuvable" in p["erreur"]
    assert fvault.store.path.read_bytes() == avant


@pytest.mark.parametrize("chemin", ["../secret.jpg", "../../secret.jpg", "documents/../../secret.jpg", "ABS"])
def test_ajouter_media_traversee_refusee(fvault, tmp_path, chemin):
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"img")
    chemin = str(secret) if chemin == "ABS" else chemin
    p = server.arbre_proposer(_op(chemin), "Image", "Acte.")
    assert "erreur" in p and "hors" in p["erreur"]


def test_ajouter_media_url_distante_inchangee(app_famille):
    url = "https://gallica.bnf.fr/iiif/ark:/12148/btv1b0000000/f1/full/full/0/native.jpg"
    p = server.arbre_proposer(_op(url), "Image", "Vue Gallica.")
    assert "erreur" not in p, p
    server.arbre_appliquer(p["jeton"])
    assert url in [m.fichier for m in app_famille.tree().medias.values()]


# ---------------------------------------------------------------- media_enregistrer

def test_media_enregistrer_renvoie_reference_media(app, tmp_path):
    src = tmp_path / "scan.jpg"
    src.write_bytes(b"img")
    r = server.media_enregistrer(str(src), "a.jpg")
    assert r["reference_media"] == "medias/a.jpg"
    app.config.media_dir_conf = tmp_path / "vault" / "documents"
    r = server.media_enregistrer(str(src), "naissance MARTIN.jpg", classer=True)
    assert r["reference_media"] == r["chemin_absolu"] and Path(r["reference_media"]).is_file()
