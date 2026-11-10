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


def make_app(tmp_path, backend="gramps", mirror=False, remote="", notes_auto="true"):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend=backend,
                 gramps_url=URL, gramps_user="sosa", gramps_password="secret", git_mirror=mirror, git_remote=remote,
                 gramps_ttl=0, gramps_notes_auto=notes_auto)
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


def test_incremental_refresh_fetches_changed_and_boundary(gapp, fake):
    server.arbre_info()
    get_one = fake.router.routes[-1]
    before = get_one.call_count
    expected = {h for objects in gapp.backend.db.objects.values() if objects
                for h, o in objects.items() if o.get("change", 0) == max(x.get("change", 0) for x in objects.values())}
    expected.add(fake.find("Person", "I2")["handle"])
    fake.ui_edit("Person", "I2", lambda o: o["primary_name"].update(first_name="Marie-Anne"))
    assert server.arbre_personne("I2")["noms"][0]["prenoms"] == "Marie-Anne"
    calls = get_one.calls[before:]
    assert {str(call.request.url).rsplit("/", 1)[-1] for call in calls} == expected
    assert get_one.call_count - before == len(expected)
    assert gapp.backend.last_refresh == {"Person": {"modifies": 1, "supprimes": 0}}


# ---------------------------------------------------------------------------- écriture

def test_propose_then_apply_is_one_transaction(gapp, fake):
    n = len(fake.transactions)
    p = server.arbre_proposer(CIT_DEATH, "Acte de décès de Jean MARTIN", "Acte lu sur le registre de Rochefort.")
    assert "jeton" in p and p["transaction_gramps"]["bilan"]["Citation"]["add"] == 1
    assert "+3 PAGE Décès 1885, acte n° 3" in p["diff"]
    assert len(fake.transactions) == n  # rien d'écrit avant l'accord
    assert "Validé" not in p["message_de_transaction"]  # #17 : pas de validation affirmée à la proposition
    r = server.arbre_appliquer(p["jeton"])
    assert "transaction" in r and len(fake.transactions) == n + 1 and not fake.forced
    assert "Justification : Acte lu" in fake.messages[-1] and "2 E 299" in fake.messages[-1]
    assert f"Validé explicitement par l'utilisateur (proposition {p['jeton']})" in fake.messages[-1]
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
    assert "validée" not in str(u).lower()  # #17 : rien n'est validé à la préparation de l'annulation
    done = server.arbre_appliquer(u["jeton"])
    assert "validée explicitement" in fake.messages[-1]
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


@pytest.mark.parametrize("repo", ["Sosa", "Genealogiste"])
def test_remote_repository_rules(repo):
    for bad in ("https://github.com/Hiobi/Sosa", "https://github.com/hiobi/sosa.git", "git@github.com:Hiobi/Sosa.git",
                "ssh://git@github.com/hiobi/sosa", "https://github.com/Hiobi/Sosa.git/",
                "git@github.com:Hiobi/Sosa.git/", "ssh://git@github.com:22/Hiobi/Sosa.git"):
        bad = bad.replace("Sosa", repo).replace("sosa", repo.lower())
        assert remote_problem(bad), bad
    assert remote_problem("git@forge.example:famille/arbre-prive.git") == ""


def test_backend_names():
    assert backend_name("fichier") == backend_name("gedcom") == "fichier"
    assert backend_name("gramps") == backend_name("grampsweb") == "gramps"
    with pytest.raises(ValueError):
        backend_name("sqlite")


def test_untagged_proof_notes_are_adopted_not_duplicated(tmp_path, fake, tree):
    """#15 : notes de preuve importées sans étiquette Sosa:auto (export GEDCOM/GeneWeb) reconnues et adoptées."""
    import re
    seed(fake, tree)
    auto = next(h for h, t in fake.objects["Tag"].items() if t["name"] == SOSA_AUTO)
    del fake.objects["Tag"][auto]
    for n in fake.objects["Note"].values():
        n["tag_list"] = [t for t in n["tag_list"] if t != auto]
        n["type"] = {"_class": "NoteType", "value": 1, "string": ""}  # « General », comme après un import GEDCOM
    notes_before = len(fake.objects["Note"])
    make_app(tmp_path)
    try:
        p = server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")
        assert p["transaction_gramps"]["bilan"].get("Note", {}).get("add", 0) == 0
        server.arbre_appliquer(p["jeton"])
    finally:
        server.set_app(None)
    assert len(fake.objects["Note"]) == notes_before
    proof = re.compile(r"^(⛔|🟡|🟢|✅|⚠️|❌) Preuve : ")
    for ev in fake.objects["Event"].values():
        texts = [fake.objects["Note"][h]["text"]["string"] for h in ev["note_list"]]
        assert sum(bool(proof.match(t)) for t in texts) <= 1
    new_auto = next(h for h, t in fake.objects["Tag"].items() if t["name"] == SOSA_AUTO)
    assert all(new_auto in n["tag_list"] for n in fake.objects["Note"].values()
               if proof.match(n["text"]["string"]) or n["text"]["string"].startswith("Fiche de preuve"))


def test_generated_note_patterns():
    from genealogiste_mcp.gramps.mapping import looks_generated
    assert looks_generated("🟡 Preuve : hypothèse — 1 source(s)\nÀ consulter : AD")
    assert looks_generated("⚠️ Preuve : contradictoire — 0 source(s)")
    assert looks_generated("Filiation de Jean MARTIN : ⛔ non sourcé")
    assert looks_generated("Fiche de preuve (plugin genealogiste) — réf. I1\n…")
    assert looks_generated("Lien : https://exemple.org/x")
    assert not looks_generated("Vérifier le registre paroissial")
    assert not looks_generated("Preuve : voir le registre")  # sans icône : note manuelle
    assert not looks_generated("Lien : voir mon cousin")


# ---------------------------------------------------------------------------- #16 : notes auto configurables

def _app_with(tmp_path, fake, tree, mode):
    seed(fake, tree)
    return make_app(tmp_path, notes_auto=mode)


def _death_event(fake):
    return next(e for e in fake.objects["Event"].values() if tname(e["type"]) == "Death"
                and any(a["value"] == "11111111-1111-4111-8111-111111111113" for a in e["attribute_list"]))


def test_notes_auto_false_keeps_existing_and_generates_nothing(tmp_path, fake, tree):
    import copy
    _app_with(tmp_path, fake, tree, "false")
    try:
        notes_before = copy.deepcopy(fake.objects["Note"])
        p = server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")
        assert set(p["transaction_gramps"]["bilan"]) <= {"Citation", "Event"}
        server.arbre_appliquer(p["jeton"])
        assert fake.objects["Note"] == notes_before  # notes générées existantes conservées, aucune nouvelle
        ev = _death_event(fake)
        assert set(ev["note_list"]) <= set(notes_before)
        assert "désactivées" in server.gramps_recalculer_notes()["erreur"]
    finally:
        server.set_app(None)


def test_notes_auto_modifies_limits_recalculation(tmp_path, fake, tree):
    _app_with(tmp_path, fake, tree, "modifies")
    try:
        # notes périmées partout (comme après des modifications dans l'interface)
        for n in fake.objects["Note"].values():
            n["text"]["string"] += " (périmé)"
        p = server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")
        notes = p["transaction_gramps"]["bilan"].get("Note", {})
        # seulement Jean MARTIN, ses événements et ses familles : pas toute la base
        assert 0 < notes.get("update", 0) < len(fake.objects["Note"]) // 2, notes
        server.arbre_appliquer(p["jeton"])
        ev = _death_event(fake)
        assert any("probable" in fake.objects["Note"][h]["text"]["string"]
                   and "périmé" not in fake.objects["Note"][h]["text"]["string"] for h in ev["note_list"])
        stale = [n for n in fake.objects["Note"].values() if "périmé" in n["text"]["string"]]
        assert stale  # les autres notes ne sont pas recalculées
        assert "jeton" in server.gramps_recalculer_notes()  # recalcul global toujours possible
    finally:
        server.set_app(None)


def test_massive_transaction_warning_and_proof_only_count(tmp_path, fake, tree):
    from genealogiste_mcp.gramps import backend as gb
    _app_with(tmp_path, fake, tree, "true")
    try:
        for n in fake.objects["Note"].values():
            n["text"]["string"] += " (périmé)"
        old = gb.MASSIVE_OBJECTS
        gb.MASSIVE_OBJECTS = 5
        try:
            p = server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")
        finally:
            gb.MASSIVE_OBJECTS = old
        tg = p["transaction_gramps"]
        assert tg["dont_notes_de_preuve_seules"] >= 10
        assert any("notes de preuve" in w for w in p["avertissements"])
    finally:
        server.set_app(None)


def test_notes_auto_config_values():
    from genealogiste_mcp.config import notes_auto_mode
    assert notes_auto_mode("") == "true" and notes_auto_mode("Modifies") == "modifies"
    assert notes_auto_mode("non") == "false"
    with pytest.raises(ValueError):
        notes_auto_mode("parfois")


# ---------------------------------------------------------------------------- journal d'intention (#49)

def _etats(a, jeton):
    import json
    return [json.loads(x).get("etat") for x in a.backend.log_path.read_text(encoding="utf-8").splitlines()
            if json.loads(x)["id"] == jeton]


def test_intention_journalisee_avant_envoi(gapp, fake, monkeypatch):
    p = server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")
    vu = []
    vrai = gapp.backend.client.transaction

    def espion(*a, **k):
        vu.append(_etats(gapp, p["jeton"]))
        return vrai(*a, **k)
    monkeypatch.setattr(gapp.backend.client, "transaction", espion)
    server.arbre_appliquer(p["jeton"])
    assert vu == [["intention"]]
    assert _etats(gapp, p["jeton"]) == ["intention", "envoyee", "terminee"]


def test_complements_en_echec_transaction_tracee_et_annulable(tmp_path, fake, tree, monkeypatch):
    seed(fake, tree)
    a = make_app(tmp_path, mirror=True)
    server.arbre_info()

    def panne(*_a, **_k):
        raise OSError("disque plein")
    monkeypatch.setattr(a.backend.mirror, "sync", panne)
    r = server.arbre_appliquer(server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")["jeton"])
    assert r["transaction"] and "avertissement" in r and "disque plein" in r["avertissement"]
    h = server.arbre_historique(1)[0]
    assert h["etat"] == "complements_en_echec" and "échec" in h["etapes"]["miroir_git"]
    assert "jeton" in server.arbre_annuler_modification(r["transaction"])
    server.set_app(None)


@pytest.mark.parametrize("appliquee,etat", [(True, "envoyee"), (False, "non_envoyee")])
def test_interruption_pendant_l_envoi_reprise(gapp, fake, monkeypatch, appliquee, etat):
    p = server.arbre_proposer(CIT_DEATH, "Décès", "Acte lu.")
    vrai = gapp.backend.client.transaction

    def coupure(*a, **k):
        if appliquee:
            vrai(*a, **k)
        raise ConnectionError("connexion coupée")
    monkeypatch.setattr(gapp.backend.client, "transaction", coupure)
    with pytest.raises(ConnectionError):
        gapp.backend.apply(p["jeton"])
    assert _etats(gapp, p["jeton"])[-1] == "indeterminee"
    monkeypatch.setattr(gapp.backend.client, "transaction", vrai)
    assert gapp.backend.recover() == [{"transaction": p["jeton"], "etat": etat}]
    u = server.arbre_annuler_modification(p["jeton"])
    assert ("jeton" in u) is appliquee


@pytest.mark.parametrize("value, compact", [("BEF 1925", "av. 1925"), ("AFT 1925", "ap. 1925"),
                                          ("BET 1920 AND 1925", "1920/1925"),
                                          ("FROM 1920 TO 1925", "1920/1925")])
def test_dates_gramps_affichees_sans_utiliser_sortval(gapp, fake, value, compact):
    from genealogiste_mcp.gramps.types import date_to_gramps

    death = next(e for e in fake.objects["Event"].values() if tname(e["type"]) == "Death"
                 and e["date"]["dateval"][2] == 1885)
    fake.ui_edit("Event", death["gramps_id"], lambda e: e["date"].update(
        date_to_gramps(value), text="", sortval=0))
    assert next(e for e in server.arbre_personne("I1")["evenements"] if e["type"] == "DEAT")["date"] == value
    for outil in (server.arbre_ascendance, server.arbre_descendance):
        liste = outil("I1", format="liste")
        assert (liste[0] if isinstance(liste, list) else liste)["dates"] == "1820–" + compact
        for format in ("mermaid", "svg"):
            assert "1820–" + compact in outil("I1", format=format)


def test_date_modifiee_gramps_renomme_les_notes_apres_accord(gapp, tmp_path):
    from genealogiste_mcp.notes import Notes

    vault = tmp_path / "notes"
    gapp.notes = Notes(vault, data_dir=gapp.config.data_dir)
    server.notes_generer()
    ancienne = next((vault / "personnes").glob("I1 - *.md"))
    ancienne.write_text(ancienne.read_text(encoding="utf-8") + "\nHypothèse à conserver.\n", encoding="utf-8")
    uid = gapp.tree().personnes["I1"].events("DEAT")[0].uid
    prop = server.arbre_proposer([{"op": "modifier_evenement", "uid": uid, "champs": {"date": "BEF 1925"}}],
                                "Correction fictive", "Date contrôlée pour la recette")
    assert "jeton" in prop and ancienne.exists(), prop
    res = server.arbre_appliquer(prop["jeton"])
    assert not res.get("erreur") and not res.get("notes", {}).get("erreurs"), res
    assert res["notes"]["renommees"][0]["ancien"] == "personnes/" + ancienne.name
    nouvelle = next((vault / "personnes").glob("I1 - *.md"))
    assert "av 1925" in nouvelle.name and not ancienne.exists()
    assert "Hypothèse à conserver." in nouvelle.read_text(encoding="utf-8")
    assert ancienne.stem not in (vault / "index.md").read_text(encoding="utf-8")


def test_bilan_de_transaction_avant_le_diff(gapp):
    p = server.arbre_proposer(CIT_DEATH, "Acte de décès", "Acte lu sur le registre.")
    cles = list(p)
    assert cles.index("transaction_gramps") < cles.index("diff")
    assert "@@ @I1@ INDI @@" in p["diff"] and "@I2@" not in p["diff"]
