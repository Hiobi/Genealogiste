"""#193 (point 3) : références de médias relatives à l'arborescence des pièces (GENEALOGISTE_MEDIA_DIR), résolues
sans ambiguïté par la même règle partout (proposition, notes, envoi vers Gramps Web, suivi des pièces)."""

import shutil
from datetime import date
from pathlib import Path

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.chemins import CheminAmbigu, CheminRefuse, localiser
from genealogiste_mcp.config import Config
from genealogiste_mcp.gramps.backend import media_pending
from genealogiste_mcp.gramps.mapping import GrampsDb

WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 image-fictive"
RELATIF = "documents/État civil/MARTIN/MARTIN Jean -- N [1820].webp"


# ---------------------------------------------------------------- règle de résolution (chemins.localiser)

@pytest.fixture
def racines(tmp_path):
    data, vault = tmp_path / "donnees", tmp_path / "vault"
    for d in (data, vault):
        d.mkdir()
    return data, vault / "documents", vault


def _ecrire(path: Path, contenu: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contenu)
    return path


def test_relatif_present_sous_une_seule_racine(racines):
    f = _ecrire(racines[2] / RELATIF, WEBP)
    assert localiser(racines, RELATIF) == f.resolve()


def test_relatif_present_deux_fois_meme_contenu_premiere_racine(racines):
    _ecrire(racines[2] / RELATIF, WEBP)
    d = _ecrire(racines[0] / RELATIF, WEBP)
    assert localiser(racines, RELATIF) == d.resolve()


def test_relatif_present_deux_fois_contenus_differents_refuse(racines):
    v = _ecrire(racines[2] / RELATIF, WEBP)
    d = _ecrire(racines[0] / RELATIF, b"autre image")
    with pytest.raises(CheminAmbigu) as exc:
        localiser(racines, RELATIF)
    assert exc.value.candidats == [d.resolve(), v.resolve()]
    assert isinstance(exc.value, CheminRefuse) and "ambigu" in str(exc.value)


def test_absolu_jamais_ambigu(racines):
    v = _ecrire(racines[2] / RELATIF, WEBP)
    _ecrire(racines[0] / RELATIF, b"autre image")
    assert localiser(racines, str(v)) == v.resolve()


# ---------------------------------------------------------------- référence enregistrée (Config.media_ref)

@pytest.fixture
def cfg(tmp_path):
    return Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite",
                  media_dir_conf=tmp_path / "vault" / "documents")


def test_reference_relative_a_l_arborescence_des_pieces(cfg):
    f = _ecrire(cfg.pieces_root / RELATIF, WEBP)
    assert cfg.media_ref(f) == RELATIF
    photo = _ecrire(cfg.pieces_root / "photographies" / "MARTIN" / "p.jpg", b"jpg")
    assert cfg.media_ref(photo) == "photographies/MARTIN/p.jpg"


def test_reference_relative_au_repertoire_des_medias_hors_documents(tmp_path):
    c = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "c.sqlite", media_dir_conf=tmp_path / "fonds")
    f = _ecrire(tmp_path / "fonds" / "État civil" / "x.jpg", b"jpg")
    assert c.media_ref(f) == "État civil/x.jpg"


def test_reference_dans_les_donnees_inchangee(cfg):
    f = _ecrire(cfg.data_dir / "medias" / "a.jpg", b"jpg")
    assert cfg.media_ref(f) == "medias/a.jpg"


def test_reference_absolue_si_le_relatif_serait_ambigu(cfg):
    f = _ecrire(cfg.pieces_root / RELATIF, WEBP)
    _ecrire(cfg.data_dir / RELATIF, b"autre image")
    assert cfg.media_ref(f) == str(f.resolve())


def test_reference_absolue_hors_des_racines(cfg, tmp_path):
    f = _ecrire(tmp_path / "ailleurs" / "x.jpg", b"jpg")
    assert cfg.media_ref(f) == str(f.resolve())


def test_reference_relative_resolue_vers_le_meme_fichier(cfg):
    f = _ecrire(cfg.pieces_root / RELATIF, WEBP)
    assert localiser(cfg.media_racines, cfg.media_ref(f)) == f.resolve()


# ---------------------------------------------------------------- proposition (ajouter_media)

def _op(fichier: str, lier_a=None) -> list[dict]:
    op = {"op": "ajouter_media", "fichier": fichier, "format": "image/webp", "titre": "Naissance"}
    return [{**op, "lier_a": lier_a}] if lier_a else [op]


@pytest.fixture
def vapp(tmp_path, fixtures):
    vault = tmp_path / "vault"
    c = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", notes_dir=vault,
               media_dir_conf=vault / "documents")
    a = server.App(c, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    a.notes.today = lambda: date(2026, 11, 4)
    a.vault = vault
    yield a
    server.set_app(None)


def test_ajouter_media_enregistre_le_chemin_relatif(vapp):
    _ecrire(vapp.vault / RELATIF, WEBP)
    for fichier in (RELATIF, "État civil/MARTIN/MARTIN Jean -- N [1820].webp", str(vapp.vault / RELATIF)):
        p = server.arbre_proposer(_op(fichier), "Image", "Acte archivé.")
        assert "erreur" not in p, p
        server.arbre_appliquer(p["jeton"])
    assert [m.fichier for m in vapp.tree().medias.values()] == [RELATIF] * 3


def test_ajouter_media_ambigu_refuse(vapp):
    _ecrire(vapp.vault / RELATIF, WEBP)
    _ecrire(vapp.config.data_dir / RELATIF, b"autre image")
    avant = vapp.store.path.read_bytes()
    p = server.arbre_proposer(_op(RELATIF), "Image", "Acte.")
    assert "ambigu" in p["erreur"]
    assert vapp.store.path.read_bytes() == avant


# ---------------------------------------------------------------- notes (section « Pièces »)

def _appliquer(fichier: str):
    p = server.arbre_proposer(_op(fichier, ["I1"]), "Image", "Acte archivé.")
    assert "jeton" in p, p
    server.arbre_appliquer(p["jeton"])


def _section_pieces(vapp) -> str:
    server.notes_generer()
    fiche = next((vapp.vault / "personnes").glob("I1 - *.md")).read_text(encoding="utf-8")
    return fiche.split("## Pièces", 1)[1].split("<!--", 1)[0]


def test_notes_resolvent_la_reference_relative_au_vault(vapp):
    _ecrire(vapp.vault / RELATIF, WEBP)
    _appliquer(RELATIF)
    assert RELATIF in [m.fichier for m in vapp.tree().medias.values()]
    section = _section_pieces(vapp)
    assert "![](../documents/" in section and "hors du vault" not in section, section


def test_notes_signalent_une_reference_ambigue_sans_image(vapp):
    _ecrire(vapp.vault / RELATIF, WEBP)
    _appliquer(RELATIF)
    _ecrire(vapp.config.data_dir / RELATIF, b"autre image")  # doublon apparu après coup
    section = _section_pieces(vapp)
    assert "ambigu" in section and "![](" not in section, section


# ---------------------------------------------------------------- envoi vers Gramps Web (media_pending)

def _db(chemin: str) -> GrampsDb:
    db = GrampsDb()
    db.put({"_class": "Media", "handle": "h1", "gramps_id": "O1", "path": chemin, "mime": "image/webp",
            "checksum": "", "attribute_list": []})
    return db


def test_media_pending_reference_relative_au_repertoire_des_medias(racines):
    data, medias, vault = racines
    f = _ecrire(vault / RELATIF, WEBP)
    todo, missing = media_pending(_db("État civil/MARTIN/MARTIN Jean -- N [1820].webp"), data, None, (medias, vault))
    assert [t["chemin"] for t in todo] == [str(f.resolve())] and missing == []


def test_media_pending_reference_ambigue_jamais_envoyee(racines):
    data, medias, vault = racines
    _ecrire(vault / RELATIF, WEBP)
    _ecrire(data / RELATIF, b"autre image")
    todo, missing = media_pending(_db(RELATIF), data, None, (medias, vault))
    assert todo == [] and len(missing) == 1 and "ambigu" in missing[0]


# ---------------------------------------------------------------- conversion des chemins absolus existants

def test_relocaliser_meme_prefixe_convertit_en_relatif(vapp):
    f = _ecrire(vapp.vault / RELATIF, WEBP)
    p = server.arbre_proposer(_op(str(f), ["I1"]), "Image", "Acte archivé.")
    server.arbre_appliquer(p["jeton"])
    mid = next(iter(vapp.tree().medias))
    vapp.store.write(_avec_fichier(vapp.tree(), mid, str(f)))  # référence absolue héritée (avant #193)
    vapp.store.commit("référence absolue")
    r = server.gramps_relocaliser_medias(str(vapp.vault), str(vapp.vault))
    assert r["a_relocaliser"] == [f"{mid} : {f} → {RELATIF}"], r
    server.arbre_appliquer(r["jeton"])
    assert vapp.tree().medias[mid].fichier == RELATIF


def _avec_fichier(tree, mid, fichier):
    from dataclasses import replace
    tree.medias[mid] = replace(tree.medias[mid], fichier=fichier)
    return tree


def test_suivi_des_pieces_reference_ambigue_couvre_les_deux_fichiers(vapp):
    """Organisation des pièces : un fichier désigné par une référence ambiguë reste « référencé » (#193)."""
    v = _ecrire(vapp.vault / RELATIF, WEBP)
    _appliquer(RELATIF)
    d = _ecrire(vapp.config.data_dir / RELATIF, b"autre image")
    refs = server._tree_media_refs()
    assert {v.resolve(), d.resolve()} <= set(refs)
