"""Kit Obsidian des notes : dépôt, idempotence, copie modifiée conservée, extrait CSS dans le vault."""

import json
import shutil
from datetime import date

import pytest

from genealogiste_mcp import obsidian_kit, server
from genealogiste_mcp.config import Config


def _app(tmp_path, fixtures, notes_dir, **kw):
    cfg = Config(data_dir=tmp_path / "donnees", cache_path=tmp_path / "cache.sqlite", notes_dir=notes_dir, **kw)
    a = server.App(cfg, sleeper=lambda s: None)
    server.set_app(a)
    shutil.copy(fixtures / "famille.ged", a.store.path)
    a.store.write(a.store.load())
    a.store.commit("fixture")
    a.notes.today = lambda: date(2026, 11, 16)
    return a


@pytest.fixture
def vault(tmp_path, fixtures):
    racine = tmp_path / "vault"
    (racine / ".obsidian").mkdir(parents=True)
    _app(tmp_path, fixtures, racine / "Genealogie")
    yield racine
    server.set_app(None)


def test_kit_depose_vues_modeles_et_extrait_css(vault):
    r = server.notes_generer()["kit"]
    kit = vault / "Genealogie" / "_genealogiste"
    for f in obsidian_kit.FICHIERS:
        assert (kit / f).is_file()
    css = vault / ".obsidian" / "snippets" / "genealogiste.css"
    assert css.is_file() and r["extrait_css"] == str(css.resolve())
    assert len(r["ecrits"]) == len(obsidian_kit.FICHIERS) + 1 and "Extraits CSS" in r["consigne"]


def test_kit_idempotent(vault):
    server.notes_generer()
    r = server.notes_generer()["kit"]
    assert r["ecrits"] == [] and r["inchanges"] == len(obsidian_kit.FICHIERS) + 1


def test_copie_modifiee_conservee_et_version_deposee_mise_a_jour(vault):
    server.notes_generer()
    kit = vault / "Genealogie" / "_genealogiste"
    perso = kit / "modeles" / "Courrier.md"
    perso.write_text("mon modèle\n", encoding="utf-8")
    r = server.notes_generer()["kit"]
    assert perso.read_text(encoding="utf-8") == "mon modèle\n"
    assert any(c.startswith("modeles/Courrier.md") for c in r["conserves"])
    # version précédente du plugin, intacte : remplacée par la nouvelle
    base = kit / "vues" / "Genealogiste.base"
    ancien = "ancienne version\n"
    base.write_text(ancien, encoding="utf-8")
    man = json.loads((kit / ".kit.json").read_text(encoding="utf-8"))
    man["vues/Genealogiste.base"] = obsidian_kit._empreinte(ancien)
    (kit / ".kit.json").write_text(json.dumps(man), encoding="utf-8")
    r = server.notes_generer()["kit"]
    assert "vues/Genealogiste.base" in r["ecrits"] and base.read_text(encoding="utf-8") != ancien


def test_sans_vault_extrait_css_a_cote_des_vues(tmp_path, fixtures, monkeypatch):
    monkeypatch.setattr(obsidian_kit, "vault", lambda notes: None)
    _app(tmp_path, fixtures, tmp_path / "notes")
    try:
        r = server.notes_generer()["kit"]
    finally:
        server.set_app(None)
    assert (tmp_path / "notes" / "_genealogiste" / "genealogiste.css").is_file()
    assert ".obsidian/snippets" in r["consigne"]


def test_kit_desactive_et_absent_hors_generation_complete(tmp_path, fixtures):
    _app(tmp_path, fixtures, tmp_path / "notes", notes_kit=False)
    try:
        assert "kit" not in server.notes_generer()
    finally:
        server.set_app(None)
    a = _app(tmp_path, fixtures, tmp_path / "notes2")
    try:
        pid = next(iter(a.tree().personnes))
        assert "kit" not in server.notes_generer(pid)
        assert not (tmp_path / "notes2" / "_genealogiste").exists()
    finally:
        server.set_app(None)


def test_vues_bases_valides():
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load((obsidian_kit.SOURCE / "vues" / "Genealogiste.base").read_text(encoding="utf-8"))
    noms = [v["name"] for v in data["views"]]
    assert "Ascendance (Sosa)" in noms and all(v["type"] == "table" for v in data["views"])


def test_lien_symbolique_refuse(vault, tmp_path):
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    (vault / ".obsidian" / "snippets").symlink_to(ailleurs)
    r = server.notes_generer()["kit"]
    assert any("lien symbolique" in x for x in r["refuses"]) and not list(ailleurs.iterdir())
