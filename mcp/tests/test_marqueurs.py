"""#182 : marqueurs « sosa: » / « Sosa-* » migrés vers « genealogiste: » / « Genealogiste-* » sans doublon ni perte.

Double lecture permanente, écriture configurable (GENEALOGISTE_MARQUEURS), migration explicite en deux temps
(marqueurs_migrer_proposer / marqueurs_migrer_appliquer), idempotente."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date

import pytest
from gramps_fake import URL, FakeGrampsWeb

from genealogiste_mcp import server
from genealogiste_mcp.config import Config, marqueurs_mode
from genealogiste_mcp.gedcom.mapping import write_gedcom
from genealogiste_mcp.gramps.mapping import gramps_to_tree, tree_to_gramps
from genealogiste_mcp.gramps.types import attribute, tname

# ============================================================================ configuration


def test_marqueurs_mode():
    assert marqueurs_mode(None) == "genealogiste" and marqueurs_mode("") == "genealogiste"
    assert marqueurs_mode(" Sosa ") == "sosa" and marqueurs_mode("genealogiste") == "genealogiste"
    with pytest.raises(ValueError, match="GENEALOGISTE_MARQUEURS"):
        marqueurs_mode("ancien")


def test_load_config_lit_marqueurs(monkeypatch, tmp_path):
    from genealogiste_mcp.config import load_config
    monkeypatch.setenv("GENEALOGISTE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GENEALOGISTE_MARQUEURS", "sosa")
    assert load_config().marqueurs == "sosa"
    monkeypatch.setenv("GENEALOGISTE_MARQUEURS", "x")
    with pytest.raises(ValueError, match="genealogiste \\| sosa"):
        load_config()


# ============================================================================ notes Markdown

def _napp(tmp_path, fixtures, marqueurs="genealogiste"):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", notes_dir=tmp_path / "vault",
                 sosa_racine="I3", marqueurs=marqueurs)
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    a.notes.today = lambda: date(2026, 11, 4)
    return a


@pytest.fixture
def napp(tmp_path, fixtures):
    yield _napp(tmp_path, fixtures)
    server.set_app(None)


def _jean(a):
    return next((a.config.notes_dir / "personnes").glob("I1 - *.md"))


def _vers_ancien(text: str) -> str:
    return text.replace("<!-- genealogiste:debut ", "<!-- sosa:debut ").replace("<!-- genealogiste:fin -->",
                                                                                   "<!-- sosa:fin -->")


def test_ecriture_par_defaut_nouvelle_forme(napp):
    server.notes_generer()
    text = _jean(napp).read_text(encoding="utf-8")
    assert "<!-- genealogiste:debut faits -->" in text and "<!-- genealogiste:fin -->" in text
    assert "sosa:debut" not in text and "sosa:fin" not in text
    assert "sosa: 2" in text  # numérotation Sosa-Stradonitz : non concernée


def test_option_sosa_ecrit_ancienne_forme(tmp_path, fixtures):
    a = _napp(tmp_path, fixtures, marqueurs="sosa")
    try:
        server.notes_generer()
        text = _jean(a).read_text(encoding="utf-8")
        assert "<!-- sosa:debut faits -->" in text and "genealogiste:" not in text
        assert server.notes_generer()["ecrites"] == []  # idempotent dans l'ancienne forme
    finally:
        server.set_app(None)


def test_ancien_bloc_converti_a_la_regeneration_sans_doublon(napp):
    server.notes_generer()
    jean = _jean(napp)
    ancien = _vers_ancien(jean.read_text(encoding="utf-8"))
    ancien = ancien.replace("<!-- sosa:debut faits -->", "Remarque libre avant les faits.\n\n<!-- sosa:debut faits -->")
    ancien += "\nHypothèse : frère cadet parti à Rochefort.\n"
    jean.write_text(ancien, encoding="utf-8")
    assert "sosa:debut" in ancien
    server.notes_generer("I1")
    text = jean.read_text(encoding="utf-8")
    assert "sosa:debut" not in text and "sosa:fin" not in text
    assert text.count("<!-- genealogiste:debut faits -->") == 1
    assert text.count("<!-- genealogiste:fin -->") == text.count("<!-- genealogiste:debut ")
    assert "Remarque libre avant les faits." in text and "Hypothèse : frère cadet parti à Rochefort." in text


def test_fiche_mixte_divergente_un_seul_bloc_regenere(napp):
    server.notes_generer()
    jean = _jean(napp)
    text = jean.read_text(encoding="utf-8")
    debut = "<!-- genealogiste:debut faits -->"
    i = text.index(debut)
    mixte = (text[:i] + "<!-- sosa:debut faits -->\nANCIEN CONTENU PÉRIMÉ\n<!-- sosa:fin -->\n\n"
             + "Texte libre entre les deux blocs.\n\n" + text[i:])
    mixte = mixte.replace(debut + "\n", debut + "\nCONTENU DIVERGENT\n", 1)
    jean.write_text(mixte, encoding="utf-8")
    server.notes_generer("I1")
    out = jean.read_text(encoding="utf-8")
    assert out.count("debut faits -->") == 1 and "sosa:" not in out.replace("sosa: 2", "")
    assert "ANCIEN CONTENU PÉRIMÉ" not in out and "CONTENU DIVERGENT" not in out
    assert "| Naissance |" in out  # contenu régénéré
    assert "Texte libre entre les deux blocs." in out


def test_lecture_ancienne_forme_reconnait_les_fiches_gerees(napp):
    """Patronymes et renommages reconnaissent une fiche à l'ancienne forme (pas de fiche orpheline)."""
    server.notes_generer()
    vault = napp.config.notes_dir
    for p in vault.rglob("*.md"):
        p.write_text(_vers_ancien(p.read_text(encoding="utf-8")), encoding="utf-8")
    avant = sorted(str(p.relative_to(vault)) for p in vault.rglob("*.md"))
    server.notes_generer()
    assert sorted(str(p.relative_to(vault)) for p in vault.rglob("*.md")) == avant
    assert not any("sosa:debut" in p.read_text(encoding="utf-8") for p in vault.rglob("*.md"))


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def _depot(root):
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.org")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "initial")


def test_migration_notes_en_deux_temps_commit_et_idempotence(tmp_path, fixtures):
    a = _napp(tmp_path, fixtures, marqueurs="sosa")
    try:
        server.notes_generer()
        vault = a.config.notes_dir
        jean = _jean(a)
        jean.write_text(jean.read_text(encoding="utf-8") + "\nNote libre : sosa:debut cité dans le texte.\n",
                        encoding="utf-8")
        (vault / "libre.md").write_text("# Hors outil\n\nsosa:debut sans balise.\n", encoding="utf-8")
        _depot(vault)
        avant = {p: p.read_text(encoding="utf-8") for p in vault.rglob("*.md")}
        a.config.marqueurs = a.notes.forme = "genealogiste"
        p = server.marqueurs_migrer_proposer()
        assert "jeton" in p and p["notes"]["fichiers"]
        assert str(jean.relative_to(vault)) in p["notes"]["fichiers"] and "libre.md" not in p["notes"]["fichiers"]
        assert "-<!-- sosa:debut faits -->" in p["notes"]["diff"]
        assert "+<!-- genealogiste:debut faits -->" in p["notes"]["diff"]
        assert {q: q.read_text(encoding="utf-8") for q in vault.rglob("*.md")} == avant  # rien d'écrit
        r = server.marqueurs_migrer_appliquer(p["jeton"])
        assert "erreur" not in r and r["notes"]["commit"]
        assert "marqueurs" in _git(vault, "log", "-1", "--format=%s").lower()
        assert _git(vault, "status", "--porcelain") == ""
        for q, t in avant.items():
            neuf = q.read_text(encoding="utf-8")
            assert neuf == t.replace("<!-- sosa:debut ", "<!-- genealogiste:debut ").replace(
                "<!-- sosa:fin -->", "<!-- genealogiste:fin -->")
        assert "Note libre : sosa:debut cité dans le texte." in jean.read_text(encoding="utf-8")
        assert (vault / "libre.md").read_text(encoding="utf-8") == avant[vault / "libre.md"]
        # deuxième exécution : rien à faire
        p2 = server.marqueurs_migrer_proposer()
        assert "jeton" not in p2 and p2["notes"]["fichiers"] == []
        assert "erreur" in server.marqueurs_migrer_appliquer(p["jeton"])  # usage unique
        assert server.notes_generer()["ecrites"] == []  # notes déjà à jour
    finally:
        server.set_app(None)


def test_migration_notes_sans_depot_git_et_fiche_modifiee_entre_temps(tmp_path, fixtures):
    a = _napp(tmp_path, fixtures, marqueurs="sosa")
    try:
        server.notes_generer()
        a.config.marqueurs = a.notes.forme = "genealogiste"
        p = server.marqueurs_migrer_proposer()
        jean = _jean(a)
        jean.write_text(jean.read_text(encoding="utf-8") + "\najout\n", encoding="utf-8")
        r = server.marqueurs_migrer_appliquer(p["jeton"])
        assert "erreur" in r and "modifi" in r["erreur"]
        assert "sosa:debut" in jean.read_text(encoding="utf-8")  # rien d'écrit
        p = server.marqueurs_migrer_proposer()
        r = server.marqueurs_migrer_appliquer(p["jeton"])
        assert "erreur" not in r and r["notes"]["commit"] is None and "Git" in r["notes"]["avertissement"]
        assert "sosa:debut" not in jean.read_text(encoding="utf-8")
    finally:
        server.set_app(None)


def test_migration_fiche_mixte(napp):
    server.notes_generer()
    jean = _jean(napp)
    text = jean.read_text(encoding="utf-8")
    debut = "<!-- genealogiste:debut faits -->"
    bloc = text[text.index(debut):text.index("<!-- genealogiste:fin -->", text.index(debut)) + 25]
    identique = text.replace(bloc, _vers_ancien(bloc) + "\n\n" + bloc)
    jean.write_text(identique, encoding="utf-8")
    p = server.marqueurs_migrer_proposer()
    server.marqueurs_migrer_appliquer(p["jeton"])
    out = jean.read_text(encoding="utf-8")
    assert out.count(debut) == 1 and "sosa:debut" not in out  # doublon identique retiré
    # divergent : laissé intact, signalé (notes_generer le résout en gardant le contenu régénéré)
    divergent = out.replace(bloc, _vers_ancien(bloc).replace("| Naissance |", "| Naissance (vieux) |") + "\n\n" + bloc)
    jean.write_text(divergent, encoding="utf-8")
    p = server.marqueurs_migrer_proposer()
    assert str(jean.relative_to(napp.config.notes_dir)) in p["notes"]["a_regenerer"]
    assert "jeton" not in p
    assert jean.read_text(encoding="utf-8") == divergent


def test_migration_sans_notes_ni_gramps(app):
    r = server.marqueurs_migrer_proposer()
    assert "jeton" not in r and "rien" in r["note"].lower()


# ============================================================================ Gramps Web

def _noms_attributs(db_objects):
    out = set()

    def walk(o):
        if isinstance(o, dict):
            for a in o.get("attribute_list") or []:
                out.add(tname(a.get("type")))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(db_objects)
    return out


def test_tree_to_gramps_forme_ecrite(tree):
    neuf = tree_to_gramps(tree)
    noms = _noms_attributs(neuf.objects)
    assert "Genealogiste-UID" in noms and not any(n.startswith("Sosa-") for n in noms)
    assert {t["name"] for t in neuf.all("Tag").values()} >= {"Genealogiste:auto"}
    ancien = tree_to_gramps(tree, forme="sosa")
    noms = _noms_attributs(ancien.objects)
    assert "Sosa-UID" in noms and not any(n.startswith("Genealogiste-") for n in noms)
    assert "Sosa:auto" in {t["name"] for t in ancien.all("Tag").values()}
    # lecture identique des deux formes
    assert write_gedcom(gramps_to_tree(neuf)[0]) == write_gedcom(gramps_to_tree(ancien)[0])


def test_ecriture_conserve_la_forme_des_attributs_inchanges(tree):
    ancien = tree_to_gramps(tree, forme="sosa")
    t2 = gramps_to_tree(ancien)[0]
    again = tree_to_gramps(t2, base=ancien)  # forme par défaut : genealogiste
    from genealogiste_mcp.gramps.mapping import diff
    assert diff(ancien, again) == []  # aucune migration silencieuse des attributs ni de l'étiquette


@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


def _gapp(tmp_path, mirror=False, marqueurs="genealogiste"):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", backend="gramps",
                 gramps_url=URL, gramps_user="sosa", gramps_password="secret", gramps_ttl=0, git_mirror=mirror,
                 marqueurs=marqueurs)
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    return a


def _seed(fake, db):
    for objs in db.objects.values():
        for o in objs.values():
            fake.put(o)


def _uid(obj, nom):
    return [a["value"] for a in obj.get("attribute_list") or [] if tname(a.get("type")) == nom]


def test_migration_gramps_transaction_annulable_identifiants_inchanges(tmp_path, fake, tree):
    ancien = tree_to_gramps(tree, forme="sosa")
    # objet double : même UID sous les deux formes (doublon identique) ; un autre divergent (incohérence)
    i2 = next(o for o in ancien.all("Person").values() if o["gramps_id"] == "I2")
    i2["attribute_list"].append(attribute("Genealogiste-UID", _uid(i2, "Sosa-UID")[0]))
    i4 = next(o for o in ancien.all("Person").values() if o["gramps_id"] == "I4")
    uid4 = _uid(i4, "Sosa-UID")[0]
    i4["attribute_list"].append(attribute("Genealogiste-UID", "autre-uid-divergent"))
    _seed(fake, ancien)
    a = _gapp(tmp_path, mirror=True)
    try:
        avant_tree = a.tree()
        assert avant_tree.personnes["I4"].uid == "autre-uid-divergent"  # nouvelle forme lue en priorité
        avant_ged = a.store.text()
        handles = {c: set(o) for c, o in fake.objects.items()}
        tag_auto = next(h for h, t in fake.objects["Tag"].items() if t["name"] == "Sosa:auto")
        n = len(fake.transactions)
        p = server.marqueurs_migrer_proposer()
        assert "jeton" in p and p["gramps"]["bilan"]["Person"]["update"] >= 1
        assert any("I4" in x and "autre-uid-divergent" in x for x in p["gramps"]["incoherences"])
        assert len(fake.transactions) == n  # rien d'écrit
        r = server.marqueurs_migrer_appliquer(p["jeton"])
        assert "erreur" not in r and len(fake.transactions) == n + 1
        noms = _noms_attributs(fake.objects)
        assert "Genealogiste-UID" in noms
        # seuls restent à l'ancienne forme les attributs incohérents (I4), jamais supprimés
        i4n = fake.find("Person", "I4")
        assert _uid(i4n, "Sosa-UID") == [uid4] and _uid(i4n, "Genealogiste-UID") == ["autre-uid-divergent"]
        i2n = fake.find("Person", "I2")
        assert _uid(i2n, "Sosa-UID") == [] and len(_uid(i2n, "Genealogiste-UID")) == 1
        assert fake.objects["Tag"][tag_auto]["name"] == "Genealogiste:auto"  # même handle, notes inchangées
        assert {c: set(o) for c, o in fake.objects.items()} == handles  # aucun objet créé ni supprimé
        assert all(o.get("gramps_id") == fake.objects[c][h].get("gramps_id")
                   for c, objs in ancien.objects.items() for h, o in objs.items())
        apres = a.tree()
        assert write_gedcom(apres) == write_gedcom(avant_tree)  # uid, ids et _UID GEDCOM inchangés
        assert a.store.text() == avant_ged  # miroir Git : arbre.ged inchangé
        log = [json.loads(x) for x in (a.config.data_dir / "gramps-transactions.jsonl").read_text().splitlines()]
        assert any(e.get("etat") == "terminee" for e in log)
        # idempotence
        p2 = server.marqueurs_migrer_proposer()
        assert "jeton" not in p2 and p2["gramps"]["incoherences"]
        # annulable par le mécanisme existant
        u = server.arbre_annuler_modification(r["gramps"]["transaction"])
        assert "jeton" in u
    finally:
        server.set_app(None)


def test_gramps_ancienne_forme_lue_et_ecriture_sans_doublon(tmp_path, fake, tree):
    _seed(fake, tree_to_gramps(tree, forme="sosa"))
    a = _gapp(tmp_path)
    try:
        assert server.arbre_info()["personnes"] == 8
        assert {p.uid for p in a.tree().personnes.values()} == {p.uid for p in tree.personnes.values()}
        cit = [{"op": "ajouter_citation", "cible": {"type": "evenement", "uid": "11111111-1111-4111-8111-111111111113"},
                "citation": {"source": "S1", "page": "Décès 1885, acte n° 3", "type_source": "originale",
                             "information": "primaire", "consultation": "image"}}]
        r = server.arbre_appliquer(server.arbre_proposer(cit, "Acte", "Acte lu.")["jeton"])
        assert "erreur" not in r
        for objs in fake.objects.values():
            for o in objs.values():
                types = [tname(x.get("type")) for x in o.get("attribute_list") or []]
                canon = [t.replace("Sosa-", "Genealogiste-") for t in types if t != "Genealogiste-Association"]
                assert len(canon) == len(set(canon)), (o.get("gramps_id"), types)
        assert [t["name"] for t in fake.objects["Tag"].values()].count("Genealogiste:auto") == 0
    finally:
        server.set_app(None)


def test_option_sosa_en_mode_gramps(tmp_path, fake, tree):
    _seed(fake, tree_to_gramps(tree, forme="sosa"))
    a = _gapp(tmp_path, marqueurs="sosa")
    try:
        r = server.marqueurs_migrer_proposer()
        assert "jeton" not in r and "sosa" in r["note"].lower()
        assert a.backend.forme == "sosa"
    finally:
        server.set_app(None)
