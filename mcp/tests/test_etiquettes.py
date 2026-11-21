"""Étiquettes (tags) de tout objet (#262) : opérations, diff concis, GEDCOM, Gramps Web (faux serveur), lecture,
exports publics, annulation. Données fictives uniquement."""

from __future__ import annotations

import copy

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed

from genealogiste_mcp import privacy, server
from genealogiste_mcp.etiquettes import GEDCOM_TAG, lignes_arbres
from genealogiste_mcp.gedcom.mapping import EXTENSIONS, read_gedcom, write_gedcom
from genealogiste_mcp.models import Media
from genealogiste_mcp.tree.ops import OpError, apply_ops

NAISSANCE_I1 = "11111111-1111-4111-8111-111111111111"


def _cit(page: str = "acte fictif") -> dict:
    return {"source": "S1", "page": page}


# ---------------------------------------------------------------------------- opérations

def test_tags_sur_les_operations_d_ajout(tree):
    tree.notes["N1"] = "Note partagée"
    ctx = apply_ops(tree, [
        {"op": "ajouter_personne", "ref": "p", "noms": [{"prenoms": "Luc", "nom": "FICTIF"}], "tags": ["ToDo"],
         "evenements": [{"type": "BIRT", "date": "1900", "citations": [{**_cit(), "tags": ["Blog"]}],
                         "tags": ["À vérifier"]}]},
        {"op": "ajouter_famille", "epoux": "$p", "tags": ["Blog"]},
        {"op": "ajouter_source", "titre": "Registre fictif", "tags": ["Blog"]},
        {"op": "ajouter_depot", "nom": "Archives fictives", "tags": ["Visité"]},
        {"op": "ajouter_media", "fichier": "medias/x.jpg", "tags": ["ToDo"]},
        {"op": "ajouter_evenement", "cible": "I1", "evenement": {"type": "RESI", "citations": [_cit()],
                                                                  "tags": ["Blog"]}},
        {"op": "ajouter_citation", "cible": {"type": "personne", "id": "I1"}, "citation": {**_cit(), "tags": ["ToDo"]}},
    ])
    t = ctx.tree
    p = t.personnes[ctx.refs["p"]]
    assert p.tags == ["ToDo"] and p.evenements[0].tags == ["À vérifier"]
    assert p.evenements[0].citations[0].tags == ["Blog"]
    assert t.familles["F4"].tags == ["Blog"] and t.sources["S5"].tags == ["Blog"]
    assert t.depots["R2"].tags == ["Visité"] and t.medias["O1"].tags == ["ToDo"]
    assert t.personnes["I1"].evenements[-1].tags == ["Blog"] and t.personnes["I1"].citations[-1].tags == ["ToDo"]
    assert f"étiquettes {p.id} : +ToDo" in ctx.summary and "étiquettes F4 : +Blog" in ctx.summary


def test_tags_sur_les_operations_de_modification(tree):
    tree.medias["O1"] = Media(id="O1", fichier="medias/x.jpg", tags=["ToDo"])
    tree.sources["S1"].tags = ["Blog", "ToDo"]
    ctx = apply_ops(tree, [
        {"op": "modifier_evenement", "uid": NAISSANCE_I1, "tags": ["Blog"]},
        {"op": "modifier_source", "id": "S1", "tags_retrait": ["ToDo"], "tags": ["Publié"]},
        {"op": "modifier_media", "id": "O1", "tags_retrait": ["ToDo"]},
        {"op": "modifier_personne", "id": "I2", "tags": ["Blog", "Blog"]},
    ])
    t = ctx.tree
    assert t.personnes["I1"].evenements[0].tags == ["Blog"]
    assert t.sources["S1"].tags == ["Blog", "Publié"] and t.medias["O1"].tags == [] and t.personnes["I2"].tags == ["Blog"]
    assert "étiquettes S1 : +Publié −ToDo" in ctx.summary and "étiquettes O1 : −ToDo" in ctx.summary
    assert "étiquettes I1 naissance : +Blog" in ctx.summary
    assert not any("modifié (" in s for s in ctx.summary)  # étiquetage seul : pas de ligne de modification vide


def test_etiqueter_toutes_les_cibles(tree):
    tree.notes["N1"] = "Note partagée"
    tree.medias["O1"] = Media(id="O1", fichier="medias/x.jpg")
    cibles = [{"type": "personne", "id": "I1"}, {"type": "famille", "id": "F1"},
              {"type": "evenement", "uid": NAISSANCE_I1}, {"type": "source", "id": "S2"}, {"type": "depot", "id": "R1"},
              {"type": "media", "id": "O1"}, {"type": "note", "id": "N1"},
              {"type": "citation", "porteur": {"type": "evenement", "uid": NAISSANCE_I1}, "source": "S2"}]
    ctx = apply_ops(tree, [{"op": "etiqueter", "cible": c, "tags": ["ToDo"]} for c in cibles])
    t = ctx.tree
    assert all(o.tags == ["ToDo"] for o in (t.personnes["I1"], t.familles["F1"], t.personnes["I1"].evenements[0],
                                             t.sources["S2"], t.depots["R1"], t.medias["O1"]))
    assert t.notes_tags == {"N1": ["ToDo"]}
    assert [c.tags for c in t.personnes["I1"].evenements[0].citations] == [[], ["ToDo"], []]
    assert len([s for s in ctx.summary if s.startswith("étiquettes ")]) == len(cibles)
    retrait = apply_ops(t, [{"op": "etiqueter", "cible": {"type": "note", "id": "N1"}, "tags_retrait": ["ToDo"]},
                            {"op": "etiqueter", "cible": {"type": "personne", "id": "I1"},
                             "tags_retrait": ["Absente"]}])
    assert retrait.tree.notes_tags == {} and any("absente" in w for w in retrait.warnings)


@pytest.mark.parametrize("op", [
    {"op": "etiqueter", "cible": {"type": "personne", "id": "I1"}},
    {"op": "etiqueter", "cible": {"type": "lieu", "id": "P1"}, "tags": ["X"]},
    {"op": "etiqueter", "cible": {"type": "personne", "id": "I99"}, "tags": ["X"]},
    {"op": "etiqueter", "cible": {"type": "note", "id": "N9"}, "tags": ["X"]},
    {"op": "etiqueter", "cible": {"type": "citation", "source": "S1"}, "tags": ["X"]},
    {"op": "etiqueter", "cible": {"type": "personne", "id": "I1"}, "tags": ["X"], "tags_retrait": ["X"]},
    {"op": "etiqueter", "cible": {"type": "personne", "id": "I1"}, "tags": "Blog\nToDo"},
    {"op": "etiqueter", "cible": {"type": "personne", "id": "I1"}, "tags": [{"nom": "Blog"}]},
    {"op": "ajouter_personne", "noms": [{"nom": "X"}], "tags_retrait": ["Blog"]},
    {"op": "ajouter_evenement", "cible": "I1", "evenement": {"type": "RESI", "citations": [_cit()],
                                                              "tags_retrait": ["Blog"]}},
    {"op": "modifier_source", "id": "S1", "champs": {"tags": ["Blog"]}},
    {"op": "modifier_evenement", "uid": NAISSANCE_I1, "champs": {"tags": ["Blog"]}},
    {"op": "modifier_media", "id": "O1", "champs": {"tags": ["Blog"]}},
    {"op": "modifier_personne", "id": "I1", "tags": ["Genealogiste:auto"]},
    {"op": "modifier_personne", "id": "I1", "tags": ["Preuve : Confirmé"]},
])
def test_operations_d_etiquetage_refusees(tree, op):
    tree.medias["O1"] = Media(id="O1", fichier="medias/x.jpg")
    with pytest.raises(OpError):
        apply_ops(tree, [op])


def test_fusions_reunissent_les_etiquettes(tree):
    tree.personnes["I6"].tags = ["ToDo", "Blog"]
    tree.personnes["I7"].tags = ["Blog", "Notaire"]
    tree.sources["S2"].tags = ["Blog"]
    ctx = apply_ops(tree, [
        {"op": "fusionner_personnes", "conserver": "I6", "absorber": "I7", "justification": "même homme (test)",
         "forcer": True},
        {"op": "fusionner_sources", "de": "S2", "vers": "S3"}])
    assert ctx.tree.personnes["I6"].tags == ["ToDo", "Blog", "Notaire"] and ctx.tree.sources["S3"].tags == ["Blog"]


# ---------------------------------------------------------------------------- GEDCOM

def test_gedcom_sans_etiquette_inchange_octet_pour_octet(famille_text):
    """Un arbre sans étiquette s'écrit exactement comme avant #262 : aucune déclaration ni ligne _ETIQUETTE."""
    t = read_gedcom(famille_text)[0]
    texte = write_gedcom(t)
    assert GEDCOM_TAG not in texte and GEDCOM_TAG not in EXTENSIONS
    assert texte.count("2 TAG ") == len(EXTENSIONS)
    assert write_gedcom(read_gedcom(texte)[0]) == texte
    assert GEDCOM_TAG not in write_gedcom(t, 5)


def test_gedcom_aller_retour_toutes_structures(tree):
    tree.medias["O1"] = Media(id="O1", fichier="medias/x.jpg", tags=["ToDo"])
    tree.notes["N1"] = "Note partagée"
    tree.notes_tags["N1"] = ["Blog"]
    p = tree.personnes["I1"]
    p.tags = ["ToDo", "Blog"]
    p.evenements[0].tags = ["À vérifier"]
    p.evenements[0].citations[0].tags = ["Lu"]
    p.noms[0].citations[0].tags = ["Nom"]
    tree.familles["F1"].tags = ["Blog"]
    tree.familles["F1"].enfants[0].citations[0].tags = ["Filiation"]
    tree.sources["S1"].tags = ["Blog"]
    tree.depots["R1"].tags = ["Visité"]
    texte = write_gedcom(tree)
    assert f"2 TAG {GEDCOM_TAG} https://github.com/Hiobi/Genealogiste/blob/main/docs/gedcom-extensions.md#_etiquette" \
        in texte
    assert "0 @I1@ INDI" in texte and "1 _ETIQUETTE ToDo\n1 _ETIQUETTE Blog\n" in texte
    relu = read_gedcom(texte)[0]
    assert relu.personnes["I1"].tags == ["ToDo", "Blog"] and relu.notes_tags == {"N1": ["Blog"]}
    assert relu.personnes["I1"].evenements[0].citations[0].tags == ["Lu"]
    assert relu.familles["F1"].enfants[0].citations[0].tags == ["Filiation"]
    assert relu.depots["R1"].tags == ["Visité"] and relu.medias["O1"].tags == ["ToDo"]
    assert write_gedcom(relu) == texte
    # GEDCOM 5.5.1 : même traitement que les autres extensions (écrite, relue)
    v5 = write_gedcom(tree, 5)
    assert "1 _ETIQUETTE ToDo" in v5
    assert read_gedcom(v5)[0].personnes["I1"].tags == ["ToDo", "Blog"]


def test_gedcom_etiquette_geree_jamais_dans_le_modele():
    texte = ("0 HEAD\n1 GEDC\n2 VERS 7.0\n0 @I1@ INDI\n1 NAME A /X/\n1 _ETIQUETTE Genealogiste:auto\n"
             "1 _ETIQUETTE Blog\n1 _ETIQUETTE Blog\n0 TRLR\n")
    p = read_gedcom(texte)[0].personnes["I1"]
    assert p.tags == ["Blog"]
    assert p.extra == [{"tag": "_ETIQUETTE", "value": "Genealogiste:auto"}]  # conservée, non interprétée


def test_diff_concis_et_lignes_arbres(tree):
    avant = copy.deepcopy(tree)
    tree.personnes["I1"].tags = ["Blog"]
    tree.personnes["I1"].evenements[0].tags = ["ToDo"]
    tree.sources["S1"].tags = ["Blog"]
    assert lignes_arbres(avant, tree) == ["étiquettes I1 : +Blog", "étiquettes I1 naissance : +ToDo",
                                          "étiquettes S1 : +Blog"]
    assert lignes_arbres(tree, avant) == ["étiquettes I1 : −Blog", "étiquettes I1 naissance : −ToDo",
                                          "étiquettes S1 : −Blog"]


# ---------------------------------------------------------------------------- backend fichier, lecture

def test_backend_fichier_proposition_diff_annulation(app_famille):
    p = server.arbre_proposer([{"op": "etiqueter", "cible": {"type": "personne", "id": "I1"}, "tags": ["Blog"]},
                               {"op": "etiqueter", "cible": {"type": "source", "id": "S1"}, "tags": ["ToDo"]}],
                              "Étiquettes", "Suivi de publication (test).")
    assert "@@ étiquettes I1 : +Blog @@" in p["diff"] and "@@ étiquettes S1 : +ToDo @@" in p["diff"]
    assert "+1 _ETIQUETTE Blog" in p["diff"]
    r = server.arbre_appliquer(p["jeton"])
    assert "1 _ETIQUETTE Blog" in app_famille.store.path.read_text(encoding="utf-8")
    assert [(x["id"], x["etiquettes"]) for x in server.arbre_recherche(etiquette="Blog")] == [("I1", ["Blog"])]
    assert [x["id"] for x in server.arbre_recherche(nom="MARTIN", etiquette="Blog")] == ["I1"]
    assert server.arbre_recherche(etiquette="blog") == []  # sensible à la casse, comme Gramps Web
    assert all("etiquettes" in x for x in server.arbre_recherche(nom="MARTIN"))
    assert "- **Étiquettes** : Blog" in server.arbre_fiche("I1")
    u = server.arbre_annuler_modification(r["commit"])
    server.arbre_appliquer(u["jeton"])
    assert GEDCOM_TAG not in app_famille.store.path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------- exports publics

def test_publication_meme_politique_que_les_notes(tree):
    tree.personnes["I9"].tags = ["ToDo"]  # I9 : présumé vivant dans la fixture
    tree.personnes["I1"].tags = ["Blog", "Famille de Paul DUPONT"]
    tree.notes["N1"] = "Note privée"
    tree.notes_privees.add("N1")
    tree.notes_tags["N1"] = ["Secret"]
    hidden = privacy.hidden_ids(tree)
    assert "I9" in hidden and "I1" not in hidden
    nom = tree.personnes["I9"].nom_principal
    tree.personnes["I1"].tags.append(f"Voir {nom.prenoms} {nom.nom}")
    t, _, _ = privacy.publication(tree)
    assert t.personnes["I9"].tags == [] and "N1" not in t.notes_tags
    assert t.personnes["I1"].tags[:2] == ["Blog", "Famille de Paul DUPONT"]
    assert t.personnes["I1"].tags[2] == "Voir Vivant"  # nom d'un masqué remplacé, comme dans les notes


# ---------------------------------------------------------------------------- Gramps Web (faux serveur)

@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


@pytest.fixture
def gapp(tmp_path, fake, tree):
    seed(fake, tree)
    fake.put({"_class": "Tag", "handle": "tagblog", "name": "Blog", "color": "#ff0000ff0000", "priority": 1})
    a = make_app(tmp_path)
    yield a
    server.set_app(None)


def _strip(objs):
    return {c: {h: {k: v for k, v in o.items() if k != "change"} for h, o in d.items()} for c, d in objs.items()}


def test_gramps_pose_retrait_annulation(gapp, fake):
    before = copy.deepcopy(fake.objects)
    ops = [{"op": "etiqueter", "cible": {"type": "personne", "id": "I1"}, "tags": ["Blog", "ToDo"]},
           {"op": "etiqueter", "cible": {"type": "famille", "id": "F1"}, "tags": ["ToDo"]},
           {"op": "etiqueter", "cible": {"type": "evenement", "uid": NAISSANCE_I1}, "tags": ["Blog"]},
           {"op": "etiqueter", "cible": {"type": "citation", "porteur": {"type": "evenement", "uid": NAISSANCE_I1},
                                         "source": "S2"}, "tags": ["ToDo"]},
           {"op": "etiqueter", "cible": {"type": "source", "id": "S1"}, "tags": ["ToDo"]},  # Blog : billet (#261)
           {"op": "etiqueter", "cible": {"type": "depot", "id": "R1"}, "tags": ["ToDo"]}]
    p = server.arbre_proposer(ops, "Étiquettes", "Suivi (test).")
    tg = p["transaction_gramps"]
    assert tg["bilan"]["Tag"] == {"add": 1, "update": 0, "delete": 0}  # ToDo créée, Blog réutilisée
    assert "étiquettes I1 : +Blog +ToDo" in tg["etiquettes"] and "étiquettes F1 : +ToDo" in tg["etiquettes"]
    assert len(tg["etiquettes"]) == 6 and tg["dont_notes_de_preuve_seules"] == 0
    assert "@@ étiquettes I1 : +Blog +ToDo @@" in p["diff"]
    r = server.arbre_appliquer(p["jeton"])
    todo = next(h for h, t in fake.objects["Tag"].items() if t["name"] == "ToDo")
    assert "gramps_id" not in fake.objects["Tag"][todo]
    assert fake.find("Person", "I1")["tag_list"][-2:] == ["tagblog", todo]
    assert fake.objects["Tag"]["tagblog"]["color"] == "#ff0000ff0000"  # couleur et priorité jamais touchées
    t = gapp.tree()
    assert t.personnes["I1"].tags == ["Blog", "ToDo"] and t.depots["R1"].tags == ["ToDo"]
    assert t.personnes["I1"].evenements[0].citations[1].tags == ["ToDo"]
    # retrait : l'objet Tag reste
    r2 = server.arbre_appliquer(server.arbre_proposer(
        [{"op": "modifier_personne", "id": "I1", "tags_retrait": ["ToDo"]}], "Retrait", "Fait (test).")["jeton"])
    assert todo in fake.objects["Tag"] and todo not in fake.find("Person", "I1")["tag_list"]
    # annulations : étiquettes restaurées, Tag créé retiré
    u2 = server.arbre_annuler_modification(r2["transaction"])
    assert u2["transaction_inverse"]["etiquettes"] == ["étiquettes I1 : +ToDo"]
    server.arbre_appliquer(u2["jeton"])
    assert todo in fake.find("Person", "I1")["tag_list"]
    u = server.arbre_annuler_modification(r["transaction"])
    assert "étiquettes I1 : −Blog −ToDo" in u["transaction_inverse"]["etiquettes"]
    server.arbre_appliquer(u["jeton"])
    assert _strip(fake.objects) == _strip(before)


def test_gramps_etiquette_en_double_signalee_jamais_fusionnee(gapp, fake):
    fake.put({"_class": "Tag", "handle": "tagblog0", "name": "Blog", "color": "#000000000000", "priority": 0})
    p = server.arbre_proposer([{"op": "etiqueter", "cible": {"type": "personne", "id": "I2"}, "tags": ["Blog"]}],
                              "Blog", "Publication (test).")
    assert any("présente 2 fois" in w and "tagblog0" in w for w in p["avertissements"])
    assert "Tag" not in p["transaction_gramps"]["bilan"]
    server.arbre_appliquer(p["jeton"])
    assert "tagblog0" in fake.find("Person", "I2")["tag_list"]  # priorité 0 : la première
    assert {"tagblog", "tagblog0"} <= set(fake.objects["Tag"])
    assert gapp.tree().personnes["I2"].tags == ["Blog"]


def test_gramps_compte_contributeur_refuse_a_la_proposition(gapp, fake):
    """Créer une étiquette n'exige que Contributor, mais toute écriture de Genealogiste passe par une transaction
    (Editor) : le refus a lieu à la proposition, pas à l'application."""
    fake.role = 2
    gapp.gramps()._exp = 0  # le jeton expire : le renouvellement relit le rôle courant
    r = server.arbre_proposer([{"op": "etiqueter", "cible": {"type": "personne", "id": "I1"}, "tags": ["Nouvelle"]}],
                              "Étiquette", "Essai (test).")
    assert "erreur" in r and "Editor" in r["erreur"] and not fake.transactions


def test_gramps_xml_export_puis_import(tree):
    """Export Gramps XML (Tag + tagref) relu par l'import : étiquettes reprises, aucune perte comptée."""
    from genealogiste_mcp.export.gramps_xml import db_to_xml
    from genealogiste_mcp.gramps.lecture_xml import lire_xml, pertes
    from genealogiste_mcp.gramps.mapping import gramps_to_tree, tree_to_gramps
    tree.personnes["I1"].tags = ["Blog", "ToDo"]
    tree.sources["S1"].tags = ["Blog"]
    db = tree_to_gramps(tree, generated=False)
    xml = db_to_xml(db)
    assert 'name="Blog"' in xml and "<tagref " in xml
    relu = lire_xml(xml.encode("utf-8")).db
    t, _ = gramps_to_tree(relu)
    assert t.personnes["I1"].tags == ["Blog", "ToDo"] and t.sources["S1"].tags == ["Blog"]
    assert not {k: v for k, v in pertes(relu, tree_to_gramps(t, generated=False)).items() if "ag" in k}
