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


@pytest.mark.parametrize("chemin, refuse", [
    ("mcp/tests/fixtures/gramps-desktop/gramps-6.0/famille.gramps", False),
    ("mcp/tests/fixtures/gramps-desktop/gramps-5.2/famille.gpkg", False),
    ("mcp/tests/fixtures/gramps-desktop/gramps-6.0/vrai-arbre.gramps", True),
    ("mcp/tests/fixtures/famille.gramps", True),
    ("exports/famille.gpkg", True),
    ("docs/arbre.gramps", True),
])
def test_seuls_les_fichiers_gramps_fictifs_sont_admis(chemin, refuse):
    import runpy
    from pathlib import Path

    controle = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/verifier_distribution.py"))
    assert controle["interdit"](chemin) is refuse


# ---------------------------------------------------------------- base Cassini (#349) : jamais dans le dépôt

def _controle() -> dict:
    import runpy
    from pathlib import Path

    return runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/verifier_distribution.py"))


@pytest.mark.parametrize("chemin, taille, debut, refuse", [
    ("mcp/tests/fixtures/lieux_cassini_devenus_communes.csv", 10, b"a,b\n", True),  # nom
    ("docs/extrait_Lieux_Cassini.txt", 10, b"", True),
    ("mcp/tests/fixtures/cassini.csv", 10, b"a,b\n", True),
    ("data/base-cassini.zip", 10, b"PK", True),
    ("mcp/tests/fixtures/anodin.bin", 25_497_478, b"", True),  # taille exacte du fichier publié
    ("mcp/tests/fixtures/gros.csv", 6_000_000, b"a,b\n", True),  # tableur volumineux
    ("mcp/tests/fixtures/anodin.csv", 300, b"gid,noacass,featuretype,nom_cassini,nom_an3\r\n1,2,3,4,5\r\n", True),
    ("docs/tableau.txt", 300, b'"noacass";"commune_mars_2021";"position_cassini"\n', True),  # en-tête
    ("mcp/src/genealogiste_mcp/contexte/cassini.py", 30_000, b'"""Base Cassini installee par l utilisateur', False),
    ("mcp/tests/test_cassini_local.py", 30_000, b'"""#349 : base Cassini', False),
    ("mcp/tests/fixtures/cog/communes.csv", 2183, b"TYPECOM,COM,REG,DEP\n", False),
    ("docs/etudes/lieux-1790-1943.md", 20_000, b"# Etude : noacass, nom_cassini\n", False),
])
def test_controle_distribution_refuse_ce_qui_ressemble_au_jeu_cassini(chemin, taille, debut, refuse):
    assert bool(_controle()["cassini_interdit"](chemin, taille, debut)) is refuse


def test_controle_distribution_refuse_un_extrait_cassini_ajoute(tmp_path):
    """Ajout forcé d'un extrait sous un nom anodin : refusé à son en-tête, sans afficher son contenu."""
    from pathlib import Path

    controle = Path(__file__).resolve().parents[2] / "scripts/verifier_distribution.py"
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "communes-temoins.csv").write_text(
        "gid,noacass,nom_cassini,commune_mars_2021\n1,900001,Valeur-Factice-A-Taire,99999\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", "communes-temoins.csv"], check=True)
    resultat = subprocess.run(["python3", str(controle)], cwd=tmp_path, capture_output=True, text=True)
    assert resultat.returncode == 1
    assert "communes-temoins.csv" in resultat.stderr and "en-tête du jeu Cassini" in resultat.stderr
    assert "Valeur-Factice-A-Taire" not in resultat.stderr + resultat.stdout


def test_depot_sans_fichier_cassini():
    """Le dépôt lui-même : aucun fichier suivi ne ressemble au jeu (nom, taille, en-tête)."""
    from pathlib import Path

    racine = Path(__file__).resolve().parents[2]
    suivis = subprocess.run(["git", "-C", str(racine), "ls-files", "-z"], capture_output=True, check=True)
    c = _controle()
    refuses = {}
    for chemin in filter(None, suivis.stdout.decode().split("\0")):
        f = racine / chemin
        if f.is_file():
            with f.open("rb") as fh:
                debut = fh.read(8192)
            if motif := c["cassini_interdit"](chemin, f.stat().st_size, debut):
                refuses[chemin] = motif
    assert refuses == {}
