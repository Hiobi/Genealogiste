"""#194 : ajouter_media lie un média à une famille (acte de mariage) via lier_a. Données fictives."""

import shutil

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed

from genealogiste_mcp import server
from genealogiste_mcp.config import Config
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom
from genealogiste_mcp.gramps.mapping import diff, gramps_to_tree, tree_to_gramps
from genealogiste_mcp.models import Media


def _op(lier_a):
    return [{"op": "ajouter_media", "fichier": "medias/mariage-1845.jpg", "format": "image/jpeg",
             "titre": "Acte de mariage MARTIN × DUPUIS", "lier_a": lier_a}]


def _image(app):
    """Le fichier du média doit exister : ajouter_media refuse un fichier local introuvable (#192)."""
    f = app.config.data_dir / "medias" / "mariage-1845.jpg"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"\xff\xd8image-fictive\xff\xd9")
    return app


# --- backend fichier ---------------------------------------------------------

@pytest.fixture
def app_famille(app_famille):
    return _image(app_famille)


def test_famille_acceptee_et_diff(app_famille):
    p = server.arbre_proposer(_op(["F1"]), "Acte de mariage", "Image de l'acte de mariage.")
    assert "jeton" in p, p
    assert "+1 OBJE @O1@" in p["diff"]  # le lien famille apparaît dans le diff
    assert any("liée à F1" in ligne for ligne in p["resume"])
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert t.familles["F1"].medias == ["O1"]
    assert "O1" not in t.personnes["I1"].medias


def test_mixte_personnes_et_famille(app_famille):
    p = server.arbre_proposer(_op(["I1", "I2", "F1"]), "Acte de mariage", "Image de l'acte de mariage.")
    assert "jeton" in p, p
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert t.personnes["I1"].medias == ["O1"] and t.personnes["I2"].medias == ["O1"]
    assert t.familles["F1"].medias == ["O1"]


@pytest.mark.parametrize("ident, attendu", [
    ("F99", "famille inconnue : F99"),
    ("I99", "personne inconnue : I99"),
])
def test_identifiant_inconnu(app_famille, ident, attendu):
    r = server.arbre_proposer(_op([ident]), "t", "j")
    assert attendu in r["erreur"]


@pytest.mark.parametrize("ident", ["S1", "ffffffff-1111-4111-8111-111111111111", "X1"])
def test_type_non_pris_en_charge(app_famille, ident):
    r = server.arbre_proposer(_op([ident]), "t", "j")
    assert "lier_a accepte des personnes I… et familles F…" in r["erreur"]


def test_aller_retour_gedcom(tree):
    tree.medias["O9"] = Media(id="O9", fichier="medias/mariage.jpg", titre="Mariage")
    tree.familles["F1"].medias.append("O9")
    text = write_gedcom(tree)
    fam = text.split("0 @F1@ FAM")[1].split("\n0 ")[0]
    assert "1 OBJE @O9@" in fam
    back = read_gedcom(text)[0]
    assert back.familles["F1"].medias == ["O9"]
    assert not any(x.get("tag") == "OBJE" for x in back.familles["F1"].extra)
    assert write_gedcom(back) == text


def test_obje_en_ligne_sous_fam_converti(tree):
    text = write_gedcom(tree).replace("0 @F1@ FAM\n", "0 @F1@ FAM\n1 OBJE\n2 FILE medias/m.jpg\n3 FORM image/jpeg\n")
    back = read_gedcom(text)[0]
    (mid,) = back.familles["F1"].medias
    assert back.medias[mid].fichier == "medias/m.jpg"


# --- backend gramps ----------------------------------------------------------

def test_gramps_aller_retour_mapping(tree):
    tree.medias["O9"] = Media(id="O9", fichier="medias/mariage.jpg", titre="Mariage")
    tree.familles["F1"].medias.append("O9")
    db = tree_to_gramps(tree)
    media = next(m for m in db.all("Media").values() if m["gramps_id"] == "O9")
    fam = next(f for f in db.all("Family").values() if f["gramps_id"] == "F1")
    assert [m["ref"] for m in fam["media_list"]] == [media["handle"]]
    back, _ = gramps_to_tree(db)
    assert back.familles["F1"].medias == ["O9"]
    assert diff(db, tree_to_gramps(back, base=db)) == []


def test_export_gramps_xml_objref_de_famille(tree):
    from genealogiste_mcp.export.gramps_xml import to_gramps_xml
    tree.medias["O9"] = Media(id="O9", fichier="medias/mariage.jpg", titre="Mariage")
    tree.familles["F1"].medias.append("O9")
    xml = to_gramps_xml(tree)
    fam = xml.split('id="F1"')[1].split("</family>")[0]
    assert "<objref hlink=" in fam and fam.index("<objref") < fam.index("<childref")


@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


@pytest.fixture
def gapp(tmp_path, fake, tree):
    seed(fake, tree)
    a = _image(make_app(tmp_path))
    yield a
    server.set_app(None)


def test_gramps_famille_et_personnes(gapp, fake):
    p = server.arbre_proposer(_op(["I1", "F1"]), "Acte de mariage", "Image de l'acte de mariage.")
    assert "jeton" in p, p
    server.arbre_appliquer(p["jeton"])
    media = fake.find("Media", "O1")
    assert [m["ref"] for m in fake.find("Family", "F1")["media_list"]] == [media["handle"]]
    assert [m["ref"] for m in fake.find("Person", "I1")["media_list"]] == [media["handle"]]


def test_gramps_famille_inconnue(gapp):
    assert "famille inconnue : F99" in server.arbre_proposer(_op(["F99"]), "t", "j")["erreur"]


# --- notes : section Pièces des conjoints -------------------------------------

@pytest.fixture
def vapp(tmp_path, fixtures):
    vault = tmp_path / "vault"
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", notes_dir=vault,
                 media_dir_conf=vault / "documents")
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    a.vault = vault
    yield a
    server.set_app(None)


def test_piece_de_famille_dans_les_notes_des_conjoints(vapp):
    image = vapp.vault / "documents" / "mariage-1845.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\xff\xd8\xff\xd9")
    p = server.arbre_proposer([dict(_op(["F1"])[0], fichier=str(image))], "Acte de mariage", "Image de l'acte.")
    server.arbre_appliquer(p["jeton"])
    server.notes_generer()
    for pid in ("I1", "I2"):
        fiche = next((vapp.vault / "personnes").glob(f"{pid} - *.md")).read_text(encoding="utf-8")
        assert "## Pièces" in fiche and "mariage-1845.jpg" in fiche
