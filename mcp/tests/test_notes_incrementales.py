"""#151 (partie D1) : régénération des notes par lot, limitée aux objets touchés — même résultat que la
boucle objet par objet, sans réécrire toutes les pages de patronymes ni relister les dossiers à chaque lien."""

from __future__ import annotations

import copy
import shutil
from datetime import date
from pathlib import Path

import pytest

from genealogiste_mcp import server
from genealogiste_mcp.config import Config
from genealogiste_mcp.models import Name


@pytest.fixture
def napp(tmp_path, fixtures):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", notes_dir=tmp_path / "vault",
                 sosa_racine="I3")
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    a.notes.today = lambda: date(2026, 11, 4)
    a.notes.generate(a.tree(), "tout")
    yield a
    server.set_app(None)


def _cliche(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.md"))}


def _id(tree, nom: str) -> str:
    return next(pid for pid, p in tree.personnes.items() if p.nom_principal.nom.upper() == nom)


def test_lot_equivalent_a_la_boucle(napp, tmp_path):
    autre = copy.copy(napp.notes)
    autre.dir = tmp_path / "vault2"
    shutil.copytree(napp.notes.dir, autre.dir)
    t = napp.tree()
    pid = _id(t, "BERNARD")  # changement de nom de famille : BERNARD perd son porteur, DUPONT en gagne un
    t.personnes[pid].noms[0] = Name(prenoms=t.personnes[pid].noms[0].prenoms, nom="DUPONT")
    t.personnes["I1"].noms.append(Name(prenoms="Joannes", nom="MARTINI", type="AKA"))
    ids = [pid, "I1", next(iter(t.familles))]
    for oid in ids:  # ancien comportement : un appel par objet
        autre.generate(t, oid)
    r = napp.notes.generate(t, ids)
    assert "erreurs" not in r
    assert _cliche(napp.notes.dir) == _cliche(autre.dir)


def test_lot_ne_recalcule_que_les_patronymes_concernes(napp, monkeypatch):
    t = napp.tree()
    appels = []
    vrai = type(napp.notes).surname

    def espion(self, tree, key, *args, **kw):
        appels.append(key)
        return vrai(self, tree, key, *args, **kw)

    monkeypatch.setattr(type(napp.notes), "surname", espion)
    napp.notes.generate(t, [_id(t, "BERNARD")])
    assert appels == ["BERNARD"]


def test_un_listage_par_dossier(napp, monkeypatch):
    t = napp.tree()
    globs = []
    vrai = Path.glob

    def espion(self, motif):
        globs.append(motif)
        return vrai(self, motif)

    monkeypatch.setattr(Path, "glob", espion)
    napp.notes.generate(t, list(t.personnes) + list(t.familles))
    assert len([g for g in globs if g == "* - *.md"]) <= 3  # personnes, familles, sources
    assert len(globs) <= len(t.personnes) + len(t.familles) + 6  # plus de glob par lien


def test_identifiant_inconnu_dans_un_lot(napp):
    r = napp.notes.generate(napp.tree(), ["I1", "I999"])
    assert any("I999" in e for e in r["erreurs"])
    assert r["ecrites"] is not None


def test_refresh_notes_un_seul_appel(napp, monkeypatch):
    appels = []
    vrai = napp.notes.generate
    monkeypatch.setattr(napp.notes, "generate", lambda tree, cible: appels.append(cible) or vrai(tree, cible))
    napp.refresh_notes(["I1", "I2", "I1", "F1"])
    assert appels == [["I1", "I2", "F1"]]
