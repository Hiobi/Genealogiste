"""Mode Gramps Web : client API, écriture par transactions, conflits, annulation, notes Sosa:auto, bascule,
miroir Git. Faux serveur respx (tests/gramps_fake.py), données fictives uniquement."""

from __future__ import annotations

import shutil

import pytest
from gramps_fake import URL, FakeGrampsWeb

from genealogiste_mcp import server
from genealogiste_mcp.config import Config, backend_name
from genealogiste_mcp.gedcom.mapping import read_gedcom
from genealogiste_mcp.gramps.client import ConflictError, GrampsClient, GrampsError
from genealogiste_mcp.gramps.mapping import SOSA_AUTO, tree_to_gramps
from genealogiste_mcp.gramps.types import tname
from genealogiste_mcp.tree.store import remote_problem

CIT_DEATH = [{"op": "ajouter_citation", "cible": {"type": "evenement", "uid": "11111111-1111-4111-8111-111111111113"},
              "citation": {"source": "S1", "page": "Décès 1885, acte n° 3", "type_source": "originale",
                           "information": "primaire", "consultation": "image"}}]


def seed(fake: FakeGrampsWeb, tree) -> None:
    for objs in tree_to_gramps(tree).objects.values():
        for o in objs.values():
            fake.put(o)


@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


def make_app(tmp_path, backend="gramps", mirror=False, remote=""):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend=backend,
                 gramps_url=URL, gramps_user="sosa", gramps_password="secret", git_mirror=mirror, git_remote=remote,
                 gramps_ttl=0)
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    return a


@pytest.fixture
def gapp(tmp_path, fake, tree):
    seed(fake, tree)
    a = make_app(tmp_path)
    yield a
    server.set_app(None)


def person(fake, gid):
    return fake.find("Person", gid)


# ---------------------------------------------------------------------------- lecture

def test_reads_tree_from_gramps(gapp, fake):
    info = server.arbre_info()
    assert info["backend"] == "gramps" and info["personnes"] == 8 and info["sources"] == 4
    p = server.arbre_personne("I1")
    assert p["noms"][0]["nom"] == "MARTIN" and p["parents"]["pere"].startswith("Jacques")
    birth = next(f for f in server.arbre_statut_preuve("I1") if f["fait"] == "BIRT")
    assert birth["statut"] in ("confirme", "probable")
    assert server.arbre_ascendance("I3", 3)


def test_incremental_refresh_fetches_only_changed(gapp, fake):
    server.arbre_info()
    get_one = fake.router.routes[-1]
    before = get_one.call_count
    fake.ui_edit("Person", "I2", lambda o: o["primary_name"].update(first_name="Marie-Anne"))
    assert server.arbre_personne("I2")["noms"][0]["prenoms"] == "Marie-Anne"
    assert get_one.call_count - before == 1
    assert gapp.backend.last_refresh == {"Person": {"modifies": 1, "supprimes": 0}}


# ---------------------------------------------------------------------------- écriture

def test_propose_then_apply_is_one_transaction(gapp, fake):
    n = len(fake.transactions)
    p = server.arbre_proposer(CIT_DEATH, "Acte de décès de Jean MARTIN", "Acte lu sur le registre de Rochefort.")
    assert "jeton" in p and p["transaction_gramps"]["bilan"]["Citation"]["add"] == 1
    assert "+3 PAGE Décès 1885, acte n° 3" in p["diff"]
    assert len(fake.transactions) == n  # rien d'écrit avant l'accord
    r = server.arbre_appliquer(p["jeton"])
    assert "transaction" in r and len(fake.transactions) == n + 1 and not fake.forced
    assert "Justification : Acte lu" in fake.messages[-1] and "2 E 299" in fake.messages[-1]
    death = next(f for f in server.arbre_statut_preuve("I1") if f["fait"] == "DEAT")
    assert death["statut"] == "probable"
    # statut de preuve recalculé dans Gramps : étiquette et note Sosa:auto de l'événement
    ev = next(e for e in fake.objects["Event"].values() if tname(e["type"]) == "Death"
              and any(a["value"] == "11111111-1111-4111-8111-111111111113" for a in e["attribute_list"]))
    tags = {fake.objects["Tag"][t]["name"] for t in ev["tag_list"]}
    assert "Preuve : probable" in tags
    auto = next(h for h, t in fake.objects["Tag"].items() if t["name"] == SOSA_AUTO)
    notes = [fake.objects["Note"][n] for n in ev["note_list"]]
    assert any(auto in n["tag_list"] and "probable" in n["text"]["string"] for n in notes)
    hist = server.arbre_historique(5)
    assert hist[0]["transaction"] == r["transaction"] and "Acte de décès" in hist[0]["message"]


def test_conflict_with_ui_edit_refuses_then_reproposes(gapp, fake):
    p = server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")
    jean = person(fake, "I1")
    death_ref = jean["event_ref_list"][2]["ref"]
    fake.ui_edit("Event", fake.objects["Event"][death_ref]["gramps_id"], lambda o: o.update(description="noyé"))
    n = len(fake.transactions)
    r = server.arbre_appliquer(p["jeton"])
    assert "Conflit" in r["erreur"] and len(fake.transactions) == n and not fake.forced
    p2 = server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")
    assert "transaction" in server.arbre_appliquer(p2["jeton"])
    assert fake.objects["Event"][death_ref]["description"] == "noyé"  # modification de l'interface conservée


def test_server_side_conflict_is_reported(fake, tree):
    seed(fake, tree)
    c = GrampsClient(URL, "sosa", "secret")
    db = c.load_all()
    h, p = next(iter(db.all("Person").items()))
    fake.ui_edit("Person", p["gramps_id"], lambda o: o.update(private=True))
    new = dict(p, gender=0)
    with pytest.raises(ConflictError):
        c.transaction([{"type": "update", "_class": "Person", "handle": h, "old": p, "new": new}], "test")


def test_undo_restores_previous_state(gapp, fake):
    import copy
    before = copy.deepcopy(fake.objects)
    r = server.arbre_appliquer(server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")["jeton"])
    u = server.arbre_annuler_modification(r["transaction"])
    assert "jeton" in u and len(fake.transactions) == 1
    done = server.arbre_appliquer(u["jeton"])
    assert done["annule"] == r["transaction"]
    strip = lambda objs: {c: {h: {k: v for k, v in o.items() if k != "change"} for h, o in d.items()}  # noqa: E731
                          for c, d in objs.items()}
    assert strip(fake.objects) == strip(before)
    assert "erreur" in server.arbre_annuler_modification(r["transaction"])  # déjà annulée
    assert server.arbre_historique(1)[0]["type"] == "annulation"


def test_manual_notes_and_unmapped_data_never_touched(gapp, fake):
    manual = {"_class": "Note", "handle": "nmanuelle", "gramps_id": "N0100", "change": 0, "private": False,
              "tag_list": [], "text": {"_class": "StyledText", "string": "Vérifier le registre paroissial",
                                       "tags": []}, "format": 0,
              "type": {"_class": "NoteType", "value": 25, "string": ""}}
    fake.put(manual)
    fake.ui_edit("Person", "I1", lambda o: (o["note_list"].append("nmanuelle"), o.update(urls=[
        {"_class": "Url", "private": False, "path": "https://exemple.org/jean", "desc": "",
         "type": {"_class": "UrlType", "value": 2, "string": ""}}])))
    server.arbre_appliquer(server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")["jeton"])
    jean = person(fake, "I1")
    assert "nmanuelle" in jean["note_list"] and jean["urls"][0]["path"] == "https://exemple.org/jean"
    assert fake.objects["Note"]["nmanuelle"]["text"]["string"] == "Vérifier le registre paroissial"


def test_recalculate_notes_after_ui_change(gapp, fake):
    assert "ne modifie rien" in server.gramps_recalculer_notes()["erreur"]
    # citation ajoutée dans l'interface : les notes de preuve sont périmées
    cit = next(iter(fake.objects["Citation"].values()))
    jean = person(fake, "I1")
    death = fake.objects["Event"][jean["event_ref_list"][2]["ref"]]
    fake.ui_edit("Event", death["gramps_id"], lambda o: o["citation_list"].append(cit["handle"]))
    p = server.gramps_recalculer_notes()
    assert "jeton" in p and set(p["transaction_gramps"]["bilan"]) <= {"Note", "Event", "Tag"}
    assert "transaction" in server.arbre_appliquer(p["jeton"])


def test_background_transaction_and_task_polling(fake, tree):
    seed(fake, tree)
    c = GrampsClient(URL, "sosa", "secret", sleeper=lambda s: None)
    db = c.load_all()
    h, p = next(iter(db.all("Person").items()))
    out = c.transaction([{"type": "update", "_class": "Person", "handle": h, "old": p, "new": dict(p, private=True)}],
                        "lot", background=True)
    assert out and out[0]["new"]["private"] is True


def test_auth_error_does_not_leak_credentials(fake):
    c = GrampsClient(URL, "sosa", "mauvais-mot-de-passe")
    with pytest.raises(GrampsError) as exc:
        c.load_all()
    assert "mauvais-mot-de-passe" not in str(exc.value) and "403" in str(exc.value)
    with pytest.raises(GrampsError):
        GrampsClient(URL, "", "")


# ---------------------------------------------------------------------------- bascule, miroir, configuration

def test_bascule_freezes_local_tree(tmp_path, fake, fixtures):
    a = make_app(tmp_path, backend="fichier")
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.commit("fixture")
    p = server.gramps_bascule_proposer()
    assert p["personnes"] == 8 and not fake.objects["Person"]
    r = server.gramps_bascule_appliquer(p["jeton"])
    assert r["commit"] and len(fake.objects["Person"]) == 8
    assert a.store.log(1)[0]["message"].startswith("Bascule vers Gramps Web")
    assert "figé" in server.arbre_proposer([{"op": "marquer_vivant", "id": "I7", "vivant": "N"}], "t", "j")["erreur"]
    assert "déjà" in server.gramps_bascule_proposer()["erreur"]
    # puis travail en direct sur Gramps Web
    b = make_app(tmp_path, backend="gramps")
    assert server.arbre_info()["personnes"] == 8
    assert "transaction" in server.arbre_appliquer(server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")["jeton"])
    assert b.store.frozen()
    server.set_app(None)


def test_bascule_refused_when_gramps_not_empty(tmp_path, fake, tree, fixtures):
    seed(fake, tree)
    a = make_app(tmp_path, backend="fichier")
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.commit("fixture")
    assert "pas vide" in server.gramps_bascule_proposer()["erreur"]
    server.set_app(None)


def test_git_mirror_commits_transactions_and_external_changes(tmp_path, fake, tree):
    seed(fake, tree)
    a = make_app(tmp_path, mirror=True)
    server.arbre_info()
    assert a.store.log(1)[0]["message"].startswith("Miroir de Gramps Web")
    assert read_gedcom(a.store.text())[0].personnes.keys() == tree.personnes.keys()
    server.arbre_appliquer(server.arbre_proposer(CIT_DEATH, "Acte de décès", "Acte lu.")["jeton"])
    assert a.store.log(1)[0]["message"].startswith("Acte de décès")
    fake.ui_edit("Person", "I2", lambda o: o["primary_name"].update(first_name="Marie-Anne"))
    server.gramps_synchroniser()
    assert a.store.log(1)[0]["message"].startswith("Modifications externes")
    assert "Marie-Anne" in a.store.text()
    server.set_app(None)


def test_remote_repository_rules():
    for bad in ("https://github.com/Hiobi/Sosa", "https://github.com/hiobi/sosa.git", "git@github.com:Hiobi/Sosa.git",
                "ssh://git@github.com/hiobi/sosa"):
        assert remote_problem(bad), bad
    assert remote_problem("git@forge.example:famille/arbre-prive.git") == ""


def test_backend_names():
    assert backend_name("fichier") == backend_name("gedcom") == "fichier"
    assert backend_name("gramps") == backend_name("grampsweb") == "gramps"
    with pytest.raises(ValueError):
        backend_name("sqlite")
