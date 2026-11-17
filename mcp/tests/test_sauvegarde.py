"""#152 : sauvegarde et restauration outillées (make sauvegarde / make restauration)."""

from __future__ import annotations

import io
import json
import os
import stat
import tarfile

import pytest

from genealogiste_mcp import sauvegarde
from genealogiste_mcp.tree.store import TreeStore


def _donnees(app_famille, tmp_path):
    a = app_famille
    (a.config.data_dir / ".env").write_text("GENEALOGISTE_GRAMPS_PASSWORD=secret\n", encoding="utf-8")
    (a.config.data_dir / "medias" / "acte.jpg").write_bytes(b"\xff\xd8image\xff\xd9")
    a.config.cache_images_dir.mkdir(parents=True, exist_ok=True)
    (a.config.cache_images_dir / "vue.jpg").write_bytes(b"x" * 10)
    a.journal.add("test", "op", {}, "positif")
    externe = tmp_path / "coffre" / "documents"
    externe.mkdir(parents=True)
    (externe / "piece.jpg").write_bytes(b"piece")
    a.config.media_dir_conf = externe
    return a


def test_sauvegarde_contenu_et_droits(app_famille, tmp_path):
    a = _donnees(app_famille, tmp_path)
    archive = sauvegarde.sauvegarder(a.config, tmp_path / "sauvegardes")
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    with tarfile.open(archive) as tar:
        noms = tar.getnames()
        manifeste = json.load(tar.extractfile("MANIFESTE.json"))
    assert "donnees/arbre.ged" in noms and "donnees/journal.jsonl" in noms
    assert any(n.startswith("donnees/.git/") for n in noms)
    assert "donnees/medias/acte.jpg" in noms and "medias/piece.jpg" in noms
    assert not any(".env" in n for n in noms)  # secrets conservés séparément
    assert not any("cache-images" in n or n.endswith(".sqlite") for n in noms)
    assert manifeste["version"] and manifeste["arbre_sha256"] and manifeste["git_head"]


def test_restauration_identique(app_famille, tmp_path):
    a = _donnees(app_famille, tmp_path)
    archive = sauvegarde.sauvegarder(a.config, tmp_path / "s")
    cible = tmp_path / "restaure"
    rapport = sauvegarde.restaurer(archive, cible)
    assert (cible / "donnees" / "arbre.ged").read_bytes() == a.store.path.read_bytes()
    assert TreeStore(cible / "donnees").log(1)[0]["commit"] == a.store.log(1)[0]["commit"]
    assert (cible / "medias" / "piece.jpg").read_bytes() == b"piece"
    assert rapport["verifications"]["git_fsck"] == "ok" and rapport["verifications"]["arbre_lisible"]
    assert rapport["personnes"] == len(a.tree().personnes)


def test_restauration_refuse_dossier_non_vide(app_famille, tmp_path):
    archive = sauvegarde.sauvegarder(app_famille.config, tmp_path / "s")
    cible = tmp_path / "occupe"
    cible.mkdir()
    (cible / "x").write_text("x")
    with pytest.raises(sauvegarde.SauvegardeError, match="vide"):
        sauvegarde.restaurer(archive, cible)


def test_restauration_refuse_chemins_dangereux(tmp_path):
    archive = tmp_path / "piege.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for nom, data in (("MANIFESTE.json", b"{}"), ("../evasion.txt", b"x")):
            info = tarfile.TarInfo(nom)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    with pytest.raises(sauvegarde.SauvegardeError, match="chemin"):
        sauvegarde.restaurer(archive, tmp_path / "cible")
    assert not (tmp_path / "evasion.txt").exists()


def test_cli(app_famille, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sauvegarde, "load_config", lambda: app_famille.config)
    assert sauvegarde.main(["sauvegarder", "--sortie", str(tmp_path / "s")]) == 0
    chemin = json.loads(capsys.readouterr().out)["archive"]
    assert os.path.exists(chemin)
    assert sauvegarde.main(["restaurer", chemin, "--vers", str(tmp_path / "r")]) == 0


def test_diagnostic_renvoie_au_guide_serveur(app):
    from genealogiste_mcp import server
    assert server.diagnostic(reseau=False)["guide"].endswith("/wiki/Serveur")


def test_file_propositions_sauvegardee_jetons_exclus(app_famille, tmp_path):
    """#154 : la file durable survit à une restauration ; les jetons d'une heure n'y figurent pas."""
    d = app_famille.config.data_dir / ".propositions"
    (d / "file").mkdir(parents=True, exist_ok=True)
    (d / "file" / "20261117T000000000000-x.json").write_text("{}", encoding="utf-8")
    (d / "jeton-abc.json").write_text("{}", encoding="utf-8")
    archive = sauvegarde.sauvegarder(app_famille.config, tmp_path / "sauvegardes")
    with tarfile.open(archive) as tar:
        noms = tar.getnames()
    assert "donnees/.propositions/file/20261117T000000000000-x.json" in noms
    assert not any("jeton-abc" in n for n in noms)
