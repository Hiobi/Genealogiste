"""#248 : supprimer une citation, une source (cascade) et fusionner une source en double. Données fictives
(fixture famille.ged : naissance de I1 citée par S1, S2 et S3)."""

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed

from genealogiste_mcp import server

NAISSANCE = "11111111-1111-4111-8111-111111111111"
EV = {"type": "evenement", "uid": NAISSANCE}


def _naissance(t):
    return t.personnes["I1"].event_by_uid(NAISSANCE)


def _appliquer(ops, titre="Correction"):
    p = server.arbre_proposer(ops, titre, "Données fictives.")
    assert "jeton" in p, p
    r = server.arbre_appliquer(p["jeton"])
    assert "erreur" not in r, r
    return p, r


def test_supprimer_citation_precise(app_famille):
    p, r = _appliquer([{"op": "supprimer_citation", "cible": EV, "source": "S2"}])
    assert any("Citation S2 (Table décennale 1813-1822, M) retirée de I1 naissance" in s for s in p["resume"])
    assert "-2 SOUR @S2@" in p["diff"]
    assert [c.source for c in _naissance(app_famille.tree()).citations] == ["S1", "S3"]
    # annulation : la citation revient
    a = server.arbre_annuler_modification(r["commit"])
    server.arbre_appliquer(a["jeton"])
    assert [c.source for c in _naissance(app_famille.tree()).citations] == ["S1", "S2", "S3"]


def test_supprimer_citation_absente_ou_ambigue(app_famille):
    err = server.arbre_proposer([{"op": "supprimer_citation", "cible": EV, "source": "S4"}], "t", "j")["erreur"]
    assert "aucune citation S4" in err and "S1 (Naissances 1820" in err
    _appliquer([{"op": "ajouter_citation", "cible": EV, "citation": {"source": "S1", "page": "autre vue"}}])
    err = server.arbre_proposer([{"op": "supprimer_citation", "cible": EV, "source": "S1"}], "t", "j")["erreur"]
    assert "2 citations S1" in err and "préciser page ou index" in err
    _appliquer([{"op": "supprimer_citation", "cible": EV, "source": "S1", "page": "autre vue"}])
    assert [c.page for c in _naissance(app_famille.tree()).citations if c.source == "S1"] == \
        ["Naissances 1820, acte n° 45, vue 12/80"]


def test_supprimer_source_encore_citee_refusee_sans_cascade(app_famille):
    err = server.arbre_proposer([{"op": "supprimer_source", "id": "S3"}], "t", "j")["erreur"]
    assert "encore citée par 2 objet(s)" in err and "I1 naissance" in err
    assert "cascade" in err


def test_supprimer_source_cascade_liste_les_citations(app_famille):
    p, _ = _appliquer([{"op": "supprimer_source", "id": "S3", "cascade": True}])
    retraits = [s for s in p["resume"] if "retirée de" in s]
    assert len(retraits) == 2 and all("Citation S3" in s for s in retraits)
    assert any("Suppression de la source S3" in s for s in p["resume"])
    t = app_famille.tree()
    assert "S3" not in t.sources
    assert all(c.source != "S3" for _, liste in _listes(t) for c in liste)


def test_supprimer_source_originale_d_une_autre_refusee(app_famille):
    assert app_famille.tree().sources["S2"].original == "S1"  # fixture : table décennale dérivée du registre
    err = server.arbre_proposer([{"op": "supprimer_source", "id": "S1", "cascade": True}], "t", "j")["erreur"]
    assert "source originale de S2" in err


def test_supprimer_source_detache_ses_medias(app_famille):
    f = app_famille.config.data_dir / "medias" / "registre.jpg"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"\xff\xd8\xff\xd9")
    _appliquer([{"op": "ajouter_source", "titre": "Doublon", "ref": "d"},
                {"op": "ajouter_media", "fichier": "medias/registre.jpg", "lier_a": ["$d"]}])
    p, _ = _appliquer([{"op": "supprimer_source", "id": "S5"}])
    assert any("médias détachés (conservés) : O1" in s for s in p["resume"])
    assert "O1" in app_famille.tree().medias


def test_fusionner_sources_sans_doublon_ni_orpheline(app_famille):
    # cas réel #248 : source dédiée en double, même acte cité deux fois sur le décès
    _appliquer([{"op": "ajouter_source", "titre": "INSEE - doublon", "ref": "d"},
                {"op": "ajouter_citation", "cible": EV,
                 "citation": {"source": "$d", "page": "Naissances 1820, acte n° 45, vue 12/80", "texte": "extrait"}},
                {"op": "ajouter_citation", "cible": {"type": "personne", "id": "I2"},
                 "citation": {"source": "$d", "page": "p. 3"}}])
    p, r = _appliquer([{"op": "fusionner_sources", "de": "S5", "vers": "S1"}])
    assert any("Fusion de la source S5" in s and "2 citation(s) réécrite(s)" in s and "I1 naissance" in s
               for s in p["resume"]), p["resume"]
    t = app_famille.tree()
    assert "S5" not in t.sources
    s1 = [c for c in _naissance(t).citations if c.source == "S1"]
    assert len(s1) == 1 and s1[0].texte == "extrait"  # fondue, rien de perdu
    assert [c.source for c in t.personnes["I2"].citations] == ["S1"]
    assert all(c.source != "S5" for _, liste in _listes(t) for c in liste)
    a = server.arbre_annuler_modification(r["commit"])
    server.arbre_appliquer(a["jeton"])
    assert "S5" in app_famille.tree().sources


def test_fusionner_sources_meme_source_refusee(app_famille):
    assert "même source" in server.arbre_proposer([{"op": "fusionner_sources", "de": "S1", "vers": "S1"}],
                                                   "t", "j")["erreur"]


def _listes(t):
    from genealogiste_mcp.tree.ops import _toutes_listes_citations
    return list(_toutes_listes_citations(t))


# --- notes ----------------------------------------------------------------------

@pytest.fixture
def napp(tmp_path, fixtures):
    import shutil

    from genealogiste_mcp.config import Config
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", notes_dir=tmp_path / "vault")
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    yield a
    server.set_app(None)


def test_notes_fiche_de_source_supprimee(napp):
    server.notes_generer()
    sources = napp.config.notes_dir / "sources"
    s2 = next(sources.glob("S2 - *.md"))
    s3 = next(sources.glob("S3 - *.md"))
    s3.write_text(s3.read_text(encoding="utf-8") + "\nRemarque saisie à la main.\n", encoding="utf-8")
    _appliquer([{"op": "supprimer_source", "id": "S2", "cascade": True},
                {"op": "supprimer_source", "id": "S3", "cascade": True}])
    napp.attendre_notes()
    assert not s2.exists()  # sans texte libre : retirée
    texte = s3.read_text(encoding="utf-8")
    assert "Remarque saisie à la main." in texte and "Cité par" not in texte and "supprimee: true" in texte
    fiche = next((napp.config.notes_dir / "personnes").glob("I1 - *.md")).read_text(encoding="utf-8")
    assert s2.stem not in fiche and s3.stem not in fiche
    r = server.notes_generer()
    assert any("source supprimée" in x for x in r.get("alertes", []))
    assert not s2.exists()


def _existe(fake, gid):
    return any(x.get("gramps_id") == gid for x in fake.objects["Source"].values())


def tree_sources_gramps(tree):
    from genealogiste_mcp.gramps.mapping import tree_to_gramps
    return tree_to_gramps(tree).objects["Source"].values()


# --- Gramps Web -------------------------------------------------------------------

@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


def test_gramps_fusion_et_suppression(tmp_path, fake, tree):
    seed(fake, tree)
    make_app(tmp_path)
    try:
        _appliquer([{"op": "supprimer_citation", "cible": EV, "source": "S2"}])
        assert _existe(fake, "S2")
        _appliquer([{"op": "fusionner_sources", "de": "S3", "vers": "S1"}])
        assert not _existe(fake, "S3") and _existe(fake, "S1")
        handle_s3 = next(x["handle"] for x in tree_sources_gramps(tree) if x.get("gramps_id") == "S3")
        assert all(c.get("source_handle") != handle_s3 for c in fake.objects["Citation"].values())
        t = server.app().tree()
        assert "S3" not in t.sources and [c.source for c in _naissance(t).citations] == ["S1", "S1"]
    finally:
        server.set_app(None)
