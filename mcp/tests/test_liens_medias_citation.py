"""#246 : l'image jointe à une citation est liée aussi à ce que la citation prouve (personne, événement, famille,
conjoints, source), sauf lier_media: false ; rattrapage de l'existant par arbre_lacunes. Données fictives."""

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed
from test_media_source_evenement import NAISSANCE, _bloc, _image

from genealogiste_mcp import server
from genealogiste_mcp.privacy import publication

MARIAGE = "ffffffff-1111-4111-8111-111111111111"  # mariage de F1 (I1 × I2), fixture famille.ged


def _ops(cible, **citation):
    return [{"op": "ajouter_media", "fichier": "medias/acte-1820.jpg", "titre": "Acte", "ref": "img"},
            {"op": "ajouter_citation", "cible": cible,
             "citation": {"source": "S1", "page": "vue 12", "medias": ["$img"], **citation}}]


@pytest.fixture
def app_famille(app_famille):
    return _image(app_famille)


def test_evenement_individuel_lie_personne_evenement_source(app_famille):
    p = server.arbre_proposer(_ops({"type": "evenement", "uid": NAISSANCE}), "Acte", "Image de l'acte.")
    assert "jeton" in p, p
    assert any("O1 (image de citation) liée à I1 naissance, I1, S1" in s for s in p["resume"]), p["resume"]
    assert "+2 OBJE @O1@" in p["diff"] and "+1 OBJE @O1@" in p["diff"]
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert t.personnes["I1"].medias == ["O1"]
    assert t.personnes["I1"].event_by_uid(NAISSANCE).medias == ["O1"]
    assert t.sources["S1"].medias == ["O1"]
    texte = app_famille.store.path.read_text(encoding="utf-8")
    assert "1 OBJE @O1@" in _bloc(texte, "0 @I1@ INDI") and "1 OBJE @O1@" in _bloc(texte, "0 @S1@ SOUR")


def test_evenement_familial_lie_famille_et_conjoints(app_famille):
    p = server.arbre_proposer(_ops({"type": "evenement", "uid": MARIAGE}), "Acte", "Image de l'acte.")
    assert "jeton" in p, p
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert t.familles["F1"].medias == ["O1"]
    assert t.personnes["I1"].medias == ["O1"] and t.personnes["I2"].medias == ["O1"]
    assert next(e for e in t.familles["F1"].evenements if e.uid == MARIAGE).medias == ["O1"]
    assert t.personnes["I3"].medias == []  # l'enfant n'est pas cité


def test_filiation_et_nom(app_famille):
    p = server.arbre_proposer(_ops({"type": "filiation", "famille": "F1", "enfant": "I3"}), "Acte", "Image.")
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert t.personnes["I3"].medias == ["O1"] and t.familles["F1"].medias == []
    p = server.arbre_proposer([{"op": "ajouter_citation", "cible": {"type": "nom", "id": "I5"},
                                "citation": {"source": "S1", "medias": ["O1"]}}], "Nom", "Même image.")
    server.arbre_appliquer(p["jeton"])
    assert app_famille.tree().personnes["I5"].medias == ["O1"]


def test_pas_de_doublon_avec_lier_a_explicite(app_famille):
    ops = _ops({"type": "evenement", "uid": NAISSANCE})
    ops[0]["lier_a"] = ["I1", "S1"]
    p = server.arbre_proposer(ops, "Acte", "Image.")
    assert any("O1 (image de citation) liée à I1 naissance" in s and "S1" not in s.split("liée à")[1]
               for s in p["resume"]), p["resume"]
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert t.personnes["I1"].medias == ["O1"] and t.sources["S1"].medias == ["O1"]


def test_lier_media_false_garde_le_lien_fin(app_famille):
    p = server.arbre_proposer(_ops({"type": "evenement", "uid": NAISSANCE}, lier_media=False), "Acte", "Image.")
    assert "jeton" in p, p
    assert not any("image de citation" in s for s in p["resume"])
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert t.personnes["I1"].medias == [] and t.sources["S1"].medias == []
    c = t.personnes["I1"].event_by_uid(NAISSANCE).citations[-1]
    assert c.medias == ["O1"]
    # rattrapage : détecté, opération prête, rien d'écrit
    lacunes = server.arbre_lacunes()
    item = next(m for m in lacunes["medias_a_lier"] if m["media"] == "O1")
    assert item["cibles"] == [NAISSANCE, "I1", "S1"]
    assert item["operation"] == {"op": "modifier_media", "id": "O1", "lier_a": [NAISSANCE, "I1", "S1"]}
    assert server.arbre_lacunes("I1")["medias_a_lier"][0]["media"] == "O1"
    assert "medias_a_lier" not in server.arbre_lacunes("I3")
    assert app_famille.tree().personnes["I1"].medias == []
    p = server.arbre_proposer([item["operation"]], "Rattrapage", "Images de citation.")
    server.arbre_appliquer(p["jeton"])
    assert "medias_a_lier" not in server.arbre_lacunes()


def test_lier_media_invalide(app_famille):
    p = server.arbre_proposer(_ops({"type": "evenement", "uid": NAISSANCE}, lier_media="non"), "Acte", "Image.")
    assert "lier_media" in p["erreur"]


def test_personne_masquee_image_retiree_de_la_publication(app_famille):
    ops = _ops({"type": "evenement", "uid": MARIAGE}) + [{"op": "marquer_vivant", "id": "I2", "vivant": "Y"}]
    p = server.arbre_proposer(ops, "Acte", "Image.")
    server.arbre_appliquer(p["jeton"])
    t = app_famille.tree()
    assert t.personnes["I1"].medias == ["O1"]
    pub, masques, _ = publication(t)
    assert "I2" in masques
    assert "O1" not in pub.medias and pub.personnes["I1"].medias == []


# --- Gramps Web ---------------------------------------------------------------

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


def test_gramps_media_list_personne_evenement_source(gapp, fake):
    p = server.arbre_proposer(_ops({"type": "evenement", "uid": NAISSANCE}), "Acte", "Image de l'acte.")
    assert "jeton" in p, p
    server.arbre_appliquer(p["jeton"])
    media = fake.find("Media", "O1")["handle"]
    for classe, gid in (("Person", "I1"), ("Source", "S1")):
        assert [m["ref"] for m in fake.find(classe, gid).get("media_list") or []] == [media]
    assert any([m["ref"] for m in e.get("media_list") or []] == [media] for e in fake.objects["Event"].values())
