"""Tâches de Gramps Web (#263) : source + note étiquetées ToDo, attributs Status et Priority, réglage
GENEALOGISTE_GRAMPS_TACHES (désactivé par défaut : rien ne change), privé par défaut, garde des vivants, preuve,
notes de recherche, correspondance avec les pistes et tâches manuelles d'une enquête, lacunes priorisées.
Données fictives uniquement (famille.ged : I9 Lucas MARTIN, né en 1990, présumé vivant)."""

from __future__ import annotations

import copy
import json

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import URL, seed

from genealogiste_mcp import evidence, server, taches
from genealogiste_mcp.config import Config, load_config, taches_mode
from genealogiste_mcp.gramps.mapping import AUTO_TAG, diff, gramps_to_tree, tree_to_gramps
from genealogiste_mcp.gramps.types import tname
from genealogiste_mcp.models import Citation, Source
from genealogiste_mcp.notes import Notes, NotesError
from genealogiste_mcp.tree.ops import OpError, apply_ops

DESCRIPTION = "Chercher l'acte de mariage de Jean MARTIN et Marie DUPONT (Rochefort, vers 1850)."


def _tache(**kw) -> dict:
    return {"op": "ajouter_tache", "ref": "t", "titre": "Mariage MARTIN × DUPONT", "description": DESCRIPTION, **kw}


def _ops(tree, ops, **kw):
    return apply_ops(tree, ops, backend="gramps", taches_actives=True, **kw)


def _src(db, sid):
    return next(o for o in db.all("Source").values() if o["gramps_id"] == sid)


def _tag(db, nom):
    return next(h for h, t in db.all("Tag").items() if t["name"] == nom)


def _attrs(src) -> list[tuple[str, str]]:
    return [(tname(a["type"]), a["value"]) for a in src["attribute_list"]]


def _tache_ui(db, statut="Open", priorite="5", prive=False, auto_avant=False) -> None:
    """Tâche saisie comme l'interface (GrampsjsViewNewTask.js : attributs Priority puis Status, types en chaîne,
    note de type To Do portant les étiquettes et la confidentialité de la tâche)."""
    todo = {"_class": "Tag", "handle": "tagtodo", "name": "ToDo", "color": "#000000000000", "priority": 0}
    db.put(todo)
    notes = ["ndesc"]
    if auto_avant:
        auto = next(h for h, t in db.all("Tag").items() if t["name"] == AUTO_TAG)
        db.put({"_class": "Note", "handle": "nlien", "gramps_id": "N900", "private": prive, "type": "Source Note",
                "text": {"_class": "StyledText", "string": "Lien : https://ex.org/t", "tags": []},
                "tag_list": [auto], "change": 1})
        notes = ["nlien", "ndesc"]
    db.put({"_class": "Note", "handle": "ndesc", "gramps_id": "N901", "private": prive, "type": "To Do",
            "text": {"_class": "StyledText", "string": "Relever la table décennale.", "tags": []},
            "tag_list": ["tagtodo"], "change": 1})
    db.put({"_class": "Source", "handle": "sui", "gramps_id": "S90", "title": "Table décennale 1843-1852",
            "author": "", "pubinfo": "", "abbrev": "", "private": prive, "note_list": notes, "media_list": [],
            "reporef_list": [], "attribute_list": [
                {"_class": "SrcAttribute", "private": False, "type": "Priority", "value": priorite},
                {"_class": "SrcAttribute", "private": False, "type": "Status", "value": statut}],
            "tag_list": ["tagtodo"], "change": 1})


# ---------------------------------------------------------------------------- réglage

def test_reglage_valeurs_et_defaut(monkeypatch, tmp_path):
    assert taches_mode(None) is False and taches_mode("") is False
    assert taches_mode("true") is True and taches_mode("Oui") is True and taches_mode("0") is False
    for v in ("modifies", "peut-etre"):
        with pytest.raises(ValueError, match="GENEALOGISTE_GRAMPS_TACHES"):
            taches_mode(v)
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GENEALOGISTE_GRAMPS_TACHES", raising=False)
    assert load_config().gramps_taches is False
    monkeypatch.setenv("GENEALOGISTE_GRAMPS_TACHES", "true")
    assert load_config().gramps_taches is True


def test_diagnostic_configuration_effective_et_backend(app, tmp_path, fake):
    conf = next(c for c in server.diagnostic(reseau=False)["controles"] if c["controle"] == "configuration")
    assert conf["valeurs"]["gramps_taches"] is False
    app.config.gramps_taches = True
    conf = next(c for c in server.diagnostic(reseau=False)["controles"] if c["controle"] == "configuration")
    assert conf["valeurs"]["gramps_taches"] is True
    for v in (False, True):
        cfg = Config(data_dir=tmp_path / f"d{v}", cache_path=tmp_path / "c.sqlite", backend="gramps", gramps_url=URL,
                     gramps_user="sosa", gramps_password="secret", gramps_taches=v)
        assert server.App(cfg, sleeper=lambda s: None).backend.taches is v


def test_desactive_tache_de_l_interface_lue_comme_une_source(tree):
    """Réglage désactivé : une tâche saisie dans l'interface reste une source ordinaire, ses attributs restent
    intacts, rien n'est réécrit, et ajouter_tache est refusé."""
    db = tree_to_gramps(tree)
    _tache_ui(db)
    t, _ = gramps_to_tree(db)
    s = t.sources["S90"]
    assert s.tache == {} and s.tags == ["ToDo"] and "tache" not in s.to_dict()
    assert diff(db, tree_to_gramps(t, base=db)) == []
    ctx = apply_ops(t, [{"op": "modifier_source", "id": "S90", "champs": {"titre": "Revu"}}], backend="gramps")
    new = tree_to_gramps(ctx.tree, base=db)
    assert _attrs(_src(new, "S90")) == [("Priority", "5"), ("Status", "Open")]
    assert not any("Tâche" in x for x in ctx.summary)
    with pytest.raises(OpError, match="GENEALOGISTE_GRAMPS_TACHES"):
        apply_ops(tree, [_tache()], backend="gramps")
    with pytest.raises(OpError, match="GENEALOGISTE_GRAMPS_TACHES"):
        apply_ops(t, [{"op": "modifier_tache", "id": "S90", "statut": "Done"}], backend="gramps")


def test_desactive_ajouter_source_todo_inchangee(tree):
    ctx = apply_ops(tree, [{"op": "ajouter_source", "ref": "s", "titre": "Source", "tags": ["ToDo"]}],
                    backend="gramps")
    s = ctx.tree.sources[ctx.refs["s"]]
    assert s.prive is False and s.tache == {}  # comportement antérieur : rien de particulier


def test_backend_fichier_refuse(tree):
    with pytest.raises(OpError, match="backend fichier"):
        apply_ops(tree, [_tache()], backend="fichier", taches_actives=True)


# ---------------------------------------------------------------------------- opérations

def test_ajouter_tache_defauts_de_l_interface_et_prive(tree):
    ctx = _ops(tree, [_tache(tags=["Recherche"])])
    sid = ctx.refs["t"]
    s = ctx.tree.sources[sid]
    assert s.tags == ["ToDo", "Recherche"] and s.prive is True and s.note == DESCRIPTION
    assert s.tache == {"statut": "Open", "priorite": "5"}
    assert any(x.startswith(f"Tâche {sid} « Mariage MARTIN × DUPONT » : privée") and "statut Open" in x
               and "priorité 5 (moyenne)" in x for x in ctx.summary)


@pytest.mark.parametrize(("valeur", "attendu"), [("haute", "1"), ("moyenne", "5"), ("basse", "9"), (3, "3"),
                                                 ("7", "7")])
def test_priorites(tree, valeur, attendu):
    ctx = _ops(tree, [_tache(priorite=valeur)])
    assert ctx.tree.sources[ctx.refs["t"]].tache["priorite"] == attendu


@pytest.mark.parametrize(("valeur", "attendu"), [("Open", "Open"), ("in progress", "In Progress"),
                                                 ("bloquee", "Blocked"), ("terminee", "Done"), ("Done", "Done")])
def test_statuts(tree, valeur, attendu):
    ctx = _ops(tree, [_tache(statut=valeur)])
    assert ctx.tree.sources[ctx.refs["t"]].tache["statut"] == attendu


@pytest.mark.parametrize(("op", "message"), [
    (_tache(titre=""), "titre requis"), (_tache(statut="Fini"), "statut"), (_tache(priorite="urgente"), "priorite"),
    (_tache(priorite=12), "priorite"), (_tache(prive="non"), "prive"), (_tache(inconnu=1), "champs inconnus"),
    (_tache(personnes=["I999"]), "personne inconnue"), (_tache(enquete="x"), "vont ensemble"),
    (_tache(enquete="x", element="r1"), "element")])
def test_parametres_refuses(tree, op, message):
    with pytest.raises(OpError, match=message):
        _ops(tree, [op])


def test_libelle_priorite_regle_de_l_interface():
    assert [taches.libelle_priorite(v) for v in ("1", "4", "4.5", "5", "6", "9", "", "x", "nan")] == \
        ["haute", "haute", "haute", "moyenne", "basse", "basse", "", "", ""]


def test_personnes_et_reference_d_enquete_dans_la_description(tree):
    ctx = _ops(tree, [_tache(personnes=["I1", "I2"], enquete="mariage-martin", element="t1",
                             description="**Table décennale** d'abord", format_texte="markdown")])
    s = ctx.tree.sources[ctx.refs["t"]]
    assert s.note.splitlines()[0] == "Table décennale d'abord"
    assert "Personnes concernées : Jean MARTIN (I1), Marie DUPONT (I2)" in s.note
    assert taches.reference(s.note) == ("mariage-martin", "t1")
    assert ctx.tree.styles[s.note]  # la mise en forme suit le texte complété
    db = tree_to_gramps(ctx.tree, taches=True)
    note = db.get("Note", _src(db, s.id)["note_list"][0])
    assert {tname(t["name"]) for t in note["text"]["tags"]} == {"bold"}


def test_modifier_tache_statut_priorite_description_garde_la_reference(tree):
    ctx = _ops(tree, [_tache(enquete="e1", element="p2")])
    sid = ctx.refs["t"]
    ctx2 = _ops(ctx.tree, [{"op": "modifier_tache", "id": sid, "statut": "Done", "priorite": "haute",
                            "description": "Acte trouvé, vue 41."}])
    s = ctx2.tree.sources[sid]
    assert s.tache == {"statut": "Done", "priorite": "1"}
    assert s.note.startswith("Acte trouvé, vue 41.") and taches.reference(s.note) == ("e1", "p2")
    assert any("statut Open → Done" in x and "priorite 5 → 1" in x for x in ctx2.summary)
    with pytest.raises(OpError, match="n'est pas une tâche"):
        _ops(tree, [{"op": "modifier_tache", "id": "S1", "statut": "Done"}])


def test_etiquette_todo_posee_ou_retiree(tree):
    ctx = _ops(tree, [{"op": "etiqueter", "cible": {"type": "source", "id": "S1"}, "tags": ["ToDo"]}])
    assert ctx.tree.sources["S1"].tache == {"statut": "", "priorite": ""}  # rien d'inventé
    assert any("devenue tâche" in w for w in ctx.warnings)  # S1 est citée : ses citations ne comptent plus
    ctx2 = _ops(ctx.tree, [{"op": "modifier_source", "id": "S1", "tags_retrait": ["ToDo"]}])
    assert ctx2.tree.sources["S1"].tache == {}
    ctx3 = _ops(tree, [{"op": "ajouter_source", "ref": "s", "titre": "À faire", "tags": ["ToDo"]}])
    s = ctx3.tree.sources[ctx3.refs["s"]]
    assert s.prive is True and s.tache == {"statut": "Open", "priorite": "5"}


# ---------------------------------------------------------------------------- vivants, preuve, notes

def test_tache_publique_nommant_un_vivant_refusee_privee_avertie(tree):
    with pytest.raises(OpError, match="Tâche S.* publique refusée.*I9 Lucas MARTIN"):
        _ops(tree, [_tache(description="Lucas MARTIN, mon cousin.", prive=False)])
    with pytest.raises(OpError, match="identifiant I9"):
        _ops(tree, [_tache(description="Voir la fiche I9.", prive=False)])
    with pytest.raises(OpError, match="I9"):
        _ops(tree, [_tache(personnes=["I9"], prive=False)])
    ctx = _ops(tree, [_tache(personnes=["I9"])])
    assert any("I9 Lucas MARTIN" in w and "ne doit pas devenir publique" in w for w in ctx.warnings)
    sid = ctx.refs["t"]
    with pytest.raises(OpError, match="publique refusée"):
        _ops(ctx.tree, [{"op": "modifier_tache", "id": sid, "prive": False}])
    ok = _ops(tree, [_tache(prive=False)])  # publique sans vivant : avertie
    assert any("publique" in w and "Invité" in w for w in ok.warnings)


def test_tache_citee_ne_compte_jamais_comme_preuve(tree):
    ctx = _ops(tree, [_tache()])
    t, sid = ctx.tree, ctx.refs["t"]
    c = Citation(source=sid, consultation="original", type_source="originale", information="primaire")
    assert evidence.citation_weight(c, t) == 0.0
    r = evidence.assess_citations([c], t)
    assert r["sources_independantes"] == 0 and sid in r["taches_citees"][0]
    t.sources["S90"] = Source(id="S90", titre="Simple")  # même source sans tâche : pèse
    assert evidence.citation_weight(Citation(source="S90", consultation="original", type_source="originale",
                                             information="primaire"), t) > 0


def test_notes_generer_ignore_les_taches(tmp_path, tree):
    ctx = _ops(tree, [_tache()])
    sid = ctx.refs["t"]
    notes = Notes(tmp_path / "vault")
    notes.generate(ctx.tree, "tout")
    assert not list((tmp_path / "vault" / "sources").glob(f"{sid} - *.md"))
    assert f"[[{sid} - " not in (tmp_path / "vault" / "index.md").read_text(encoding="utf-8")
    with pytest.raises(NotesError, match="tâche"):
        notes.generate(ctx.tree, sid)


# ---------------------------------------------------------------------------- correspondance Gramps

def _ecrire(tree, ops, base=None, only=None):
    ctx = _ops(tree, ops)
    avis: list[str] = []
    db = tree_to_gramps(ctx.tree, base=base, only=only, avis=avis, taches=True)
    return ctx, db, avis


def test_gramps_attributs_note_to_do_privee_relue_sans_reecriture(tree):
    ctx, db, _ = _ecrire(tree, [_tache(), {"op": "modifier_source", "id": "$t", "champs": {"url": "https://ex.org"}}])
    src = _src(db, ctx.refs["t"])
    assert _attrs(src) == [("URL", "https://ex.org"), ("Priority", "5"), ("Status", "Open")]
    assert all(a["_class"] == "SrcAttribute" and a["type"]["string"] in ("URL", "Priority", "Status")
               for a in src["attribute_list"])
    assert src["private"] is True and src["tag_list"] == [_tag(db, "ToDo")]
    assert len(src["note_list"]) == 1  # aucune note générée sur une tâche (pas de « Lien : … » en description)
    note = db.get("Note", src["note_list"][0])
    assert tname(note["type"]) == "To Do" and note["private"] is True and _tag(db, "ToDo") in note["tag_list"]
    assert note["text"]["string"] == DESCRIPTION
    back, _ = gramps_to_tree(db, taches=True)
    s = back.sources[ctx.refs["t"]]
    assert s.tache == {"statut": "Open", "priorite": "5"} and s.note == DESCRIPTION and s.prive
    assert diff(db, tree_to_gramps(back, base=db, taches=True)) == []
    assert diff(db, tree_to_gramps(back, base=db, only=set(), taches=True)) == []  # mode « modifies »


def test_gramps_changement_de_statut_comme_l_interface(tree):
    """Statut changé par Genealogiste : seul l'attribut Status change (retiré puis remis en fin, comme le fait
    l'interface) ; la description reste la première note, intacte."""
    ctx, db, _ = _ecrire(tree, [_tache()])
    sid = ctx.refs["t"]
    back, _ = gramps_to_tree(db, taches=True)
    _, db2, _ = _ecrire(back, [{"op": "modifier_tache", "id": sid, "statut": "In Progress"}], base=db)
    items = diff(db, db2)
    assert [(i["_class"], i["type"]) for i in items] == [("Source", "update")]
    assert _attrs(_src(db2, sid)) == [("Priority", "5"), ("Status", "In Progress")]
    assert _src(db2, sid)["note_list"] == _src(db, sid)["note_list"]


def test_gramps_tache_de_l_interface_lue_et_reordonnee(tree):
    db = tree_to_gramps(tree)
    _tache_ui(db, statut="Blocked", priorite="1", prive=True, auto_avant=True)
    t, _ = gramps_to_tree(db, taches=True)
    s = t.sources["S90"]
    assert s.tache == {"statut": "Blocked", "priorite": "1"} and s.note == "Relever la table décennale."
    assert taches.etat(s)["priorite_libelle"] == "haute" and s.prive  # description privée gardée (corps)
    assert not [i for i in diff(db, tree_to_gramps(t, base=db, taches=True)) if i["handle"] in ("sui", "ndesc")]
    ctx, new, avis = _ecrire(t, [{"op": "modifier_tache", "id": "S90", "titre": "Table 1843-1852"}], base=db)
    assert _src(new, "S90")["note_list"][0] == "ndesc"
    assert new.get("Note", "ndesc") == db.get("Note", "ndesc")  # type, étiquette, texte intacts
    assert any("Tâche S90 : description remise en première note" in a for a in avis)
    assert _attrs(_src(new, "S90")) == [("Priority", "1"), ("Status", "Blocked")]


def test_gramps_statut_hors_liste_garde_tel_quel(tree):
    db = tree_to_gramps(tree)
    _tache_ui(db, statut="Waiting", priorite="")
    t, _ = gramps_to_tree(db, taches=True)
    assert t.sources["S90"].tache == {"statut": "Waiting", "priorite": ""}
    assert diff(db, tree_to_gramps(t, base=db, taches=True)) == []


# ---------------------------------------------------------------------------- serveur (faux Gramps Web)

@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


def _tapp(tmp_path, fake, tree, notes_auto="true", taches_actives=True, mirror=False):
    seed(fake, tree)
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend="gramps",
                 gramps_url=URL, gramps_user="sosa", gramps_password="secret", gramps_ttl=0,
                 gramps_notes_auto=notes_auto, gramps_taches=taches_actives, git_mirror=mirror)
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    return a


def test_serveur_desactive_sorties_inchangees(tmp_path, fake, tree):
    a = _tapp(tmp_path, fake, tree, taches_actives=False)
    db = a.backend.snapshot()
    _tache_ui(db)
    for cls in ("Tag", "Note", "Source"):
        for h, o in db.all(cls).items():
            if h in ("tagtodo", "ndesc", "sui"):
                fake.put(o)
    a.backend.db = None
    lus = server.arbre_recherche(etiquette="ToDo", objet="source")
    assert lus == [{"id": "S90", "titre": "Table décennale 1843-1852", "auteur": "", "prive": False,
                    "etiquettes": ["ToDo"], "medias": [], "billet": False}]
    assert "taches_a_proposer" not in server.arbre_lacunes("I1")
    server.enquete_ouvrir("Mariage", ["I1"], "mariage")
    assert "taches_gramps" not in server.enquete_reprendre("mariage")
    assert "taches_gramps" not in server.enquete_etat("mariage")
    assert "taches_ecarts" not in server.gramps_synchroniser()
    assert "erreur" in server.arbre_proposer([_tache()], "Tâche", "Essai (test).")


@pytest.mark.parametrize("notes_auto", ["true", "modifies"])
def test_serveur_tache_de_bout_en_bout_recalcul_puis_annulation(tmp_path, fake, tree, notes_auto):
    _tapp(tmp_path, fake, tree, notes_auto)
    before = copy.deepcopy(fake.objects)
    p = server.arbre_proposer([_tache(personnes=["I1"])], "Tâche", "Plan de recherche (test).")
    assert "erreur" not in p, p
    sid = p["references_creees"]["t"]
    assert f"@@ tâche {sid} (créée) : statut Open, priorité 5 (moyenne) @@" in p["diff"]
    assert f"@@ étiquettes {sid} : +ToDo @@" in p["diff"] and "+1 _RESN PRIVACY" in p["diff"]
    r = server.arbre_appliquer(p["jeton"])
    src = fake.find("Source", sid)
    note = fake.objects["Note"][src["note_list"][0]]
    assert tname(note["type"]) == "To Do" and note["private"] is True and len(src["note_list"]) == 1
    lus = server.arbre_recherche(etiquette="ToDo", objet="source")
    assert [(x["id"], x["tache"]["statut"], x["tache"]["priorite_libelle"]) for x in lus] == [(sid, "Open",
                                                                                               "moyenne")]
    # autre proposition puis recalcul des notes : la tâche ne bouge pas (aucune note de preuve parasite)
    fige = copy.deepcopy(src)
    server.arbre_appliquer(server.arbre_proposer([{"op": "marquer_vivant", "id": "I7", "vivant": "N"}], "Vivant",
                                                 "Décédé (test).")["jeton"])
    assert fake.find("Source", sid) == fige
    rec = server.gramps_recalculer_notes()
    if "jeton" in rec:
        server.arbre_appliquer(rec["jeton"])
    assert fake.find("Source", sid) == fige
    # changement de statut dans l'interface (PUT de l'objet complet, attribut remis en fin), relu sans réécriture
    fake.ui_edit("Source", sid, lambda o: o.update(attribute_list=[
        *[x for x in o["attribute_list"] if tname(x["type"]) != "Status"],
        {"_class": "SrcAttribute", "type": "Status", "value": "Done"}]))
    server.gramps_synchroniser()
    assert server.arbre_recherche(etiquette="ToDo", objet="source")[0]["tache"]["statut"] == "Done"
    fige = copy.deepcopy(fake.find("Source", sid))
    server.arbre_appliquer(server.arbre_proposer([{"op": "marquer_vivant", "id": "I7", "vivant": "Y"}], "Vivant",
                                                 "Retour (test).")["jeton"])
    assert fake.find("Source", sid) == fige
    # annulation de la création : refusée tant que l'interface a modifié la tâche (conflit), sinon complète
    u = server.arbre_annuler_modification(r["transaction"])
    assert "Conflit" in server.arbre_appliquer(u["jeton"]).get("erreur", "")
    p2 = server.arbre_proposer([_tache(titre="Seconde")], "Tâche", "Plan (test).")
    r2 = server.arbre_appliquer(p2["jeton"])
    u2 = server.arbre_annuler_modification(r2["transaction"])
    assert "erreur" not in server.arbre_appliquer(u2["jeton"])
    assert not any(o.get("gramps_id") == p2["references_creees"]["t"] for o in fake.objects["Source"].values())
    assert len(fake.objects["Note"]) == len(before["Note"]) + 1  # reste la description de la première tâche


def test_serveur_modification_seule_de_statut_deposee_en_file(tmp_path, fake, tree):
    _tapp(tmp_path, fake, tree)
    p = server.arbre_proposer([_tache()], "Tâche", "Plan (test).")
    server.arbre_appliquer(p["jeton"])
    sid = p["references_creees"]["t"]
    r = server.propositions_deposer([{"op": "modifier_tache", "id": sid, "statut": "Done"}], "Clôture",
                                    "Acte trouvé (test).")
    assert "erreur" not in r, r


def test_serveur_correspondance_enquete_sans_ecriture_silencieuse(tmp_path, fake, tree):
    a = _tapp(tmp_path, fake, tree)
    server.enquete_ouvrir("Mariage de Jean MARTIN", ["I1"], "mariage-martin")
    server.enquete_noter("mariage-martin", tache={"description": "Table décennale 1843-1852 non numérisée, "
                                                                "consultation sur place", "service": "AD17"})
    server.enquete_noter("mariage-martin", piste={"question": "Mariage à Rochefort vers 1850 ?",
                                                   "sources": ["Registre des mariages 1850"]})
    etat = server.enquete_reprendre("mariage-martin", taches=True)
    assert etat["taches_gramps"]["non_liees"] == ["p1", "t1"]
    prop = etat["taches_a_proposer"]
    assert [o["element"] for o in prop["operations"]] == ["p1", "t1"]
    assert all(o["op"] == "ajouter_tache" and o["personnes"] == ["I1"] for o in prop["operations"])
    p = server.arbre_proposer(prop["operations"], prop["titre"], prop["justification"])
    assert "erreur" not in p, p
    server.arbre_appliquer(p["jeton"])
    s_t1 = p["references_creees"]["t1"]
    # lien lu dans la description, pas encore mémorisé : signalé, rien d'écrit dans l'état
    fichier = a.enquetes._chemin("mariage-martin")
    avant = fichier.read_text(encoding="utf-8")
    corr = server.enquete_etat("mariage-martin")["taches_gramps"]
    assert {x["element"]: x["lien"] for x in corr["liees"]} == {"p1": "reference", "t1": "reference"}
    assert corr["a_memoriser"] and corr["ecarts"] == []
    assert fichier.read_text(encoding="utf-8") == avant
    server.enquete_noter("mariage-martin", tache={"id": "t1", "tache_gramps": s_t1})
    # tâche close dans l'interface : écart signalé dans les deux sens, aucune écriture
    fake.ui_edit("Source", s_t1, lambda o: o.update(attribute_list=[
        *[x for x in o["attribute_list"] if tname(x["type"]) != "Status"],
        {"_class": "SrcAttribute", "type": "Status", "value": "Done"}]))
    avant = fichier.read_text(encoding="utf-8")
    n_tx = len(fake.transactions)
    ecarts = server.enquete_reprendre("mariage-martin")["taches_gramps"]["ecarts"]
    assert [(x["element"], x["tache"]) for x in ecarts] == [("t1", s_t1)]
    assert ecarts[0]["vers_enquete"]["parametres"]["tache"] == {"id": "t1", "statut": "faite"}
    assert ecarts[0]["vers_gramps"] == {"op": "modifier_tache", "id": s_t1, "statut": "Open"}
    assert [x["element"] for x in server.gramps_synchroniser()["taches_ecarts"]] == ["t1"]
    assert fichier.read_text(encoding="utf-8") == avant and len(fake.transactions) == n_tx
    # propagation vers l'enquête, explicite : plus d'écart ; piste close localement : écart inverse
    server.enquete_noter("mariage-martin", tache={"id": "t1", "statut": "faite"})
    server.enquete_noter("mariage-martin", piste={"id": "p1", "statut": "trouve"})
    ecarts = server.enquete_reprendre("mariage-martin")["taches_gramps"]["ecarts"]
    assert [(x["element"], x["vers_gramps"]["statut"]) for x in ecarts] == [("p1", "Done")]
    # déjà liées : plus rien à proposer
    assert server.enquete_reprendre("mariage-martin", taches=True)["taches_a_proposer"]["operations"] == []


def test_serveur_lacunes_priorisees(tmp_path, fake, tree):
    _tapp(tmp_path, fake, tree)
    r = server.arbre_lacunes("I1", taches=True)
    ops = r["taches_a_proposer"]["operations"]
    assert len(ops) == r["nb_actions"] and all(o["personnes"] == ["I1"] for o in ops)
    attendu = {0: "1", 1: "1", 2: "5", 3: "9"}
    assert [o["priorite"] for o in ops] == [attendu[min(a["priorite"], 3)] for a in r["plan"]]
    assert "erreur" in server.arbre_lacunes(taches=True)["taches_a_proposer"]
    p = server.arbre_proposer(ops[:1], "Lacune", "Plan (test).")
    assert "erreur" not in p, p
    assert json.dumps(r, ensure_ascii=False)  # sérialisable


def test_priorite_lacune_table():
    assert [taches.priorite_lacune(x) for x in (0, 1, 2, 3, 4)] == ["1", "1", "5", "9", "9"]
