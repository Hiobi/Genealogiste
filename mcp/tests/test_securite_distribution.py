"""Régressions de l'audit de distribution publique, données fictives uniquement."""

import subprocess

import pytest

from genealogiste_mcp.sources.familysearch import export_gedcom
from genealogiste_mcp.tree.store import GitError, TreeStore


def test_exporteur_vulnerable_jamais_execute(monkeypatch):
    def interdit(*args, **kwargs):
        pytest.fail("Aucun processus externe ne doit recevoir les identifiants")
    monkeypatch.setattr(subprocess, "run", interdit)
    assert "désactivé" in export_gedcom(None, ["ABCD-123"])["erreur"]


@pytest.mark.parametrize("sous_dossier", [".", "data", "autre/prive"])
def test_donnees_refusees_dans_checkout_plugin(tmp_path, sous_dossier):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin/plugin.json").write_text('{}')
    (tmp_path / "mcp").mkdir()
    (tmp_path / "mcp/pyproject.toml").write_text('')
    dossier = tmp_path / sous_dossier
    with pytest.raises(GitError, match="dépôt du plugin"):
        TreeStore(dossier).ensure()
    assert not (dossier / "arbre.ged").exists()
    assert not (dossier / "medias").exists()


def test_controle_distribution_refuse_un_ajout_force(tmp_path):
    from pathlib import Path

    controle = Path(__file__).resolve().parents[2] / 'scripts/verifier_distribution.py'
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / '.gitignore').write_text('.env\n')
    (tmp_path / '.env').write_text('CLE=valeur-fictive-ne-pas-afficher\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '-f', '.env'], check=True)
    resultat = subprocess.run(['python3', str(controle)], cwd=tmp_path, capture_output=True, text=True)
    assert resultat.returncode == 1
    assert '.env' in resultat.stderr
    assert 'valeur-fictive' not in resultat.stderr + resultat.stdout
