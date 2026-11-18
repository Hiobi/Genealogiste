"""#222 : ajouter_media / modifier_media lient un média à une source (S…) ou à un événement (uid) via lier_a.
Données fictives."""

import shutil

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed

from genealogiste_mcp import server
from genealogiste_mcp.config import Config
from genealogiste_mcp.gedcom.mapping import read_gedcom, write_gedcom
from genealogiste_mcp.gramps.mapping import diff, gramps_to_tree, tree_to_gramps
from genealogiste_mcp.models import Media
from genealogiste_mcp.privacy import publication
from genealogiste_mcp.tree.integrite import dangling

NAISSANCE = "11111111-1111-4111-8111-111111111111"  # naissance de I1 (fixture famille.ged)


def _op(lier_a, **kw):
    return [{"op": "ajouter_media", "fichier": "medias/acte-1820.jpg", "format": "image/jpeg",
             "titre": "Acte de naissance MARTIN", "lier_a": lier_a, **kw}]


def _bloc(text: str, entete: str) -> str:
    return text.split(entete + "\n")[1].split("\n0 ")[0]


def _image(app):
    """Le fichier du média doit exister : ajouter_media refuse un fichier local introuvable (#192)."""
    f = app.config.data_dir / "medias" / "acte-1820.jpg"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"\xff\xd8image-fictive\xff\xd9")
    return app


# --- backend fichier ---------------------------------------------------------

@pytest.fixture
def app_famille(app_famille):
    return _image(app_famille)


def test_source_acceptee_et_diff(app_famille):
    p = server.arbre_proposer(_op(["S1"]), "Registre", "Image du registre.")
    assert "jeton" in p, p
    assert "+1 OBJE @O1@" in p["diff"]  # lien sous l'enregistrement SOUR
    assert any("liée à S1" in ligne for ligne in p["resume"]), p["resume"]
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert t.sources["S1"].medias == ["O1"]
    assert "1 OBJE @O1@" in _bloc(app_famille.store.path.read_text(encoding="utf-8"), "0 @S1@ SOUR")


def test_evenement_accepte_et_diff(app_famille):
    p = server.arbre_proposer(_op([NAISSANCE]), "Acte", "Image de l'acte de naissance.")
    assert "jeton" in p, p
    assert "+2 OBJE @O1@" in p["diff"]  # lien sous l'événement
    assert any("liée à I1 naissance" in ligne for ligne in p["resume"]), p["resume"]
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert t.personnes["I1"].event_by_uid(NAISSANCE).medias == ["O1"]
    assert t.personnes["I1"].medias == []


def test_mixte_et_deduplique(app_famille):
    p = server.arbre_proposer(_op(["I1", "S1", NAISSANCE, "S1", NAISSANCE]), "Acte", "Image.")
    assert "jeton" in p, p
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert t.personnes["I1"].medias == ["O1"]
    assert t.sources["S1"].medias == ["O1"]
    assert t.personnes["I1"].event_by_uid(NAISSANCE).medias == ["O1"]


def test_refs_source_et_evenement_crees_dans_la_proposition(app_famille):
    ops = [{"op": "ajouter_source", "titre": "Registre BMS Rochefort 1820", "ref": "src"},
           {"op": "ajouter_evenement", "cible": "I2", "ref": "bapt",
            "evenement": {"type": "CHR", "date": "1824", "non_source": True, "motif": "test"}},
           *_op(["$src", "$bapt"])]
    p = server.arbre_proposer(ops, "Acte", "Image.")
    assert "jeton" in p, p
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    sid = next(s for s, x in t.sources.items() if x.titre == "Registre BMS Rochefort 1820")
    assert t.sources[sid].medias == ["O1"]
    bapt = next(e for e in t.personnes["I2"].evenements if e.type == "CHR")
    assert bapt.medias == ["O1"]


@pytest.mark.parametrize("ident, attendu", [
    ("S99", "source inconnue : S99"),
    ("eeeeeeee-9999-4999-8999-999999999999", "événement inconnu : eeeeeeee-9999-4999-8999-999999999999"),
    ("X1", "lier_a accepte des personnes I…, familles F…, sources S… et événements (uid)"),
])
def test_identifiant_refuse(app_famille, ident, attendu):
    r = server.arbre_proposer(_op([ident]), "t", "j")
    assert attendu in r["erreur"], r


def test_medias_hors_lier_a_refuses(app_famille):
    r = server.arbre_proposer([{"op": "ajouter_source", "titre": "Registre", "medias": ["O1"]}], "t", "j")
    assert "lier_a" in r["erreur"], r
    r = server.arbre_proposer([{"op": "ajouter_evenement", "cible": "I2", "evenement": {
        "type": "CHR", "non_source": True, "motif": "t", "medias": ["O1"]}}], "t", "j")
    assert "lier_a" in r["erreur"], r


def test_modifier_media_lier_a(app_famille):
    p = server.arbre_proposer(_op([]), "Média", "Image.")
    server.arbre_appliquer(p["jeton"])
    p = server.arbre_proposer([{"op": "modifier_media", "id": "O1", "lier_a": ["S1", NAISSANCE, "F1"]}],
                              "Lien", "Rattacher l'image.")
    assert "jeton" in p, p
    assert "+1 OBJE @O1@" in p["diff"] and "+2 OBJE @O1@" in p["diff"]
    assert any("liée à S1, I1 naissance, F1" in s for s in p["resume"]), p["resume"]
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert t.sources["S1"].medias == ["O1"] and t.familles["F1"].medias == ["O1"]
    assert t.personnes["I1"].event_by_uid(NAISSANCE).medias == ["O1"]
    # déjà lié : la proposition ne change rien
    r = server.arbre_proposer([{"op": "modifier_media", "id": "O1", "lier_a": ["S1"]}], "t", "j")
    assert "ne modifie rien" in r["erreur"], r


def test_modifier_media_lier_a_inconnu(app_famille):
    p = server.arbre_proposer(_op([]), "Média", "Image.")
    server.arbre_appliquer(p["jeton"])
    r = server.arbre_proposer([{"op": "modifier_media", "id": "O1", "lier_a": ["S99"]}], "t", "j")
    assert "modifier_media : lier_a, source inconnue : S99" in r["erreur"], r


def test_fusion_d_evenements_identiques_garde_les_medias(app_famille):
    t = app_famille.store.load()
    t.medias["O1"] = Media(id="O1", fichier="medias/acte-1820.jpg")
    t.medias["O2"] = Media(id="O2", fichier="medias/acte-1820-bis.jpg")
    birth = t.personnes["I1"].events("BIRT")[0]
    twin = t.personnes["I4"].events("BIRT")[0]
    twin.date, twin.lieu = birth.date, birth.lieu
    birth.medias, twin.medias = ["O1"], ["O1", "O2"]
    app_famille.store.write(t)
    app_famille.store.commit("prépa")
    r = server.arbre_proposer([{"op": "fusionner_personnes", "conserver": "I1", "absorber": "I4",
                                "justification": "même homme"}], "Fusion", "Même homme.")
    assert "jeton" in r, r
    server.arbre_appliquer(r["jeton"])
    assert app_famille.store.load().personnes["I1"].events("BIRT")[0].medias == ["O1", "O2"]


def test_aller_retour_gedcom(tree):
    tree.medias["O9"] = Media(id="O9", fichier="medias/registre.jpg", titre="Registre")
    tree.sources["S1"].medias.append("O9")
    tree.personnes["I1"].event_by_uid(NAISSANCE).medias.append("O9")
    text = write_gedcom(tree)
    assert "1 OBJE @O9@" in _bloc(text, "0 @S1@ SOUR")
    naissance = text.split("0 @I1@ INDI\n")[1].split("1 OCCU")[0]
    assert "2 OBJE @O9@" in naissance
    back = read_gedcom(text)[0]
    assert back.sources["S1"].medias == ["O9"]
    ev = back.personnes["I1"].event_by_uid(NAISSANCE)
    assert ev.medias == ["O9"] and not any(x.get("tag") == "OBJE" for x in ev.extra)
    assert not any(x.get("tag") == "OBJE" for x in back.sources["S1"].extra)
    assert write_gedcom(back) == text
    assert "1 OBJE @O9@" in _bloc(write_gedcom(back, version=5), "0 @S1@ SOUR")


def test_obje_en_ligne_sous_evenement_conserve(tree):
    """OBJE sans pointeur sous un événement : conservé tel quel (non interprété), pas de média créé."""
    text = write_gedcom(tree).replace("2 UID " + NAISSANCE, "2 OBJE\n3 FILE m.jpg\n2 UID " + NAISSANCE)
    back = read_gedcom(text)[0]
    ev = back.personnes["I1"].event_by_uid(NAISSANCE)
    assert ev.medias == [] and any(x.get("tag") == "OBJE" for x in ev.extra)
    assert "3 FILE m.jpg" in write_gedcom(back)


def test_obje_avec_sous_structure_conserve(tree):
    """OBJE pointeur avec CROP (sous l'événement ou la source) : conservé tel quel, aller-retour sans perte."""
    crop = "OBJE @O1@\n{n} CROP\n{m} TOP 10\n"
    text = write_gedcom(tree).replace("2 UID " + NAISSANCE, "2 " + crop.format(n=3, m=4) + "2 UID " + NAISSANCE)
    text = text.replace("0 @S1@ SOUR\n", "0 @S1@ SOUR\n1 " + crop.format(n=2, m=3))
    back = read_gedcom(text)[0]
    assert back.personnes["I1"].event_by_uid(NAISSANCE).medias == [] and back.sources["S1"].medias == []
    out = write_gedcom(back)
    assert "2 OBJE @O1@\n3 CROP\n4 TOP 10" in out and "1 OBJE @O1@\n2 CROP\n3 TOP 10" in out


def test_references_pendantes(tree):
    tree.sources["S1"].medias.append("O99")
    tree.personnes["I1"].event_by_uid(NAISSANCE).medias.append("O98")
    out = dangling(tree)
    assert "S1 → média O99 absent" in out and "I1 → média O98 absent" in out


def test_import_en_ajout_renumerote(app_famille, tmp_path):
    t = app_famille.store.load()
    t.medias["O1"] = Media(id="O1", fichier="medias/registre.jpg", titre="Registre")
    t.sources["S1"].medias.append("O1")
    t.personnes["I1"].event_by_uid(NAISSANCE).medias.append("O1")
    f = tmp_path / "import.ged"
    f.write_text(write_gedcom(t), encoding="utf-8")
    p = server.arbre_importer_gedcom(str(f), "ajouter")
    assert "jeton" in p, p
    server.arbre_appliquer(p["jeton"])
    t2 = app_famille.store.load()
    assert dangling(t2) == []
    src = next(s for s in t2.sources.values() if s.medias)
    assert t2.medias[src.medias[0]].fichier == "medias/registre.jpg"
    evs = [e for p in t2.personnes.values() for e in p.evenements if e.medias]
    assert len(evs) == 1 and evs[0].medias == src.medias


def test_publication_retire_medias_prives(tree):
    tree.medias["O8"] = Media(id="O8", fichier="medias/prive-evt.jpg")
    tree.medias["O9"] = Media(id="O9", fichier="medias/prive-src.jpg")
    ev = tree.personnes["I1"].event_by_uid(NAISSANCE)
    ev.medias.append("O8")
    ev.prive = True
    tree.sources["S1"].medias.append("O9")
    tree.sources["S1"].prive = True
    pub, _, rapport = publication(tree)
    assert "O8" in rapport["retires"]["medias"] and "O9" in rapport["retires"]["medias"]
    assert "O8" not in pub.medias and "O9" not in pub.medias


def test_publication_filtre_liens_des_sources_gardees(tree):
    tree.medias["O9"] = Media(id="O9", fichier="medias/prive.jpg", prive=True)
    tree.sources["S2"].medias.append("O9")
    pub, _, _ = publication(tree)
    assert "S2" in pub.sources and pub.sources["S2"].medias == []


# --- backend gramps ----------------------------------------------------------

def test_gramps_aller_retour_mapping(tree):
    tree.medias["O9"] = Media(id="O9", fichier="medias/registre.jpg", titre="Registre")
    tree.sources["S1"].medias.append("O9")
    tree.personnes["I1"].event_by_uid(NAISSANCE).medias.append("O9")
    db = tree_to_gramps(tree)
    media = next(m for m in db.all("Media").values() if m["gramps_id"] == "O9")
    src = next(s for s in db.all("Source").values() if s["gramps_id"] == "S1")
    assert [m["ref"] for m in src["media_list"]] == [media["handle"]]
    evs = [e for e in db.all("Event").values() if e.get("media_list")]
    assert len(evs) == 1 and [m["ref"] for m in evs[0]["media_list"]] == [media["handle"]]
    back, _ = gramps_to_tree(db)
    assert back.sources["S1"].medias == ["O9"]
    assert back.personnes["I1"].event_by_uid(NAISSANCE).medias == ["O9"]
    assert diff(db, tree_to_gramps(back, base=db)) == []


def test_export_gramps_xml_objref_de_source(tree):
    from genealogiste_mcp.export.gramps_xml import to_gramps_xml
    tree.medias["O9"] = Media(id="O9", fichier="medias/registre.jpg", titre="Registre")
    tree.sources["S1"].medias.append("O9")
    tree.personnes["I1"].event_by_uid(NAISSANCE).medias.append("O9")
    xml = to_gramps_xml(tree)
    src = xml.split('id="S1"')[1].split("</source>")[0]
    assert "<objref hlink=" in src and src.index("<objref") < src.index("<srcattribute")
    assert any("<objref hlink=" in e.split("</event>")[0] for e in xml.split("<event ")[1:])


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


def test_gramps_source_et_evenement(gapp, fake):
    p = server.arbre_proposer(_op(["S1", NAISSANCE]), "Acte", "Image de l'acte.")
    assert "jeton" in p, p
    assert any("liée à S1, I1 naissance" in s for s in p["resume"]), p["resume"]
    server.arbre_appliquer(p["jeton"])
    media = fake.find("Media", "O1")
    assert [m["ref"] for m in fake.find("Source", "S1")["media_list"]] == [media["handle"]]
    evs = [e for e in fake.objects["Event"].values()
           if [m["ref"] for m in e.get("media_list") or []] == [media["handle"]]]
    assert len(evs) == 1
    t = gapp.tree()
    assert t.sources["S1"].medias == ["O1"]
    assert t.personnes["I1"].event_by_uid(NAISSANCE).medias == ["O1"]


def test_gramps_source_inconnue(gapp):
    assert "source inconnue : S99" in server.arbre_proposer(_op(["S99"]), "t", "j")["erreur"]


# --- notes : section Pièces ---------------------------------------------------

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


def test_piece_d_evenement_dans_les_notes(vapp):
    image = vapp.vault / "documents" / "naissance-1820.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\xff\xd8\xff\xd9")
    p = server.arbre_proposer([dict(_op([NAISSANCE])[0], fichier=str(image))], "Acte", "Image de l'acte.")
    server.arbre_appliquer(p["jeton"])
    server.notes_generer()
    fiche = next((vapp.vault / "personnes").glob("I1 - *.md")).read_text(encoding="utf-8")
    assert "## Pièces" in fiche and "naissance-1820.jpg" in fiche
