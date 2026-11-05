"""#41, #51 : aucun chemin fourni par un outil ou un média ne sort du répertoire de données
ni n'écrase un fichier interne (arbre, journal)."""

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import respx

from genealogiste_mcp import server
from genealogiste_mcp.gramps.backend import media_pending
from genealogiste_mcp.gramps.mapping import A_FICHIER, GrampsDb

HOOKS = Path(__file__).resolve().parents[2] / "hooks" / "hooks.json"


# ---------------------------------------------------------------- media_enregistrer (#41)

@pytest.fixture
def scan(tmp_path):
    p = tmp_path / "scan.jpg"
    p.write_bytes(b"\xff\xd8image\xff\xd9")
    return p


@pytest.mark.parametrize("nom", ["../arbre.ged", "../../x.jpg", "/tmp/x.jpg", "sous/x.jpg", "..", ".", "a\\..\\b.jpg"])
def test_media_nom_traversant_refuse(app_famille, scan, nom):
    avant = app_famille.store.path.read_bytes()
    r = server.media_enregistrer(str(scan), nom)
    assert "erreur" in r
    assert app_famille.store.path.read_bytes() == avant


def test_media_nom_simple_accepte(app_famille, scan):
    r = server.media_enregistrer(str(scan), "acte-1885.jpg")
    assert r["fichier"] == "medias/acte-1885.jpg"
    assert (app_famille.config.media_dir / "acte-1885.jpg").read_bytes() == scan.read_bytes()


def test_media_lien_symbolique_sortant_refuse(app_famille, scan, tmp_path):
    media = app_famille.config.media_dir
    media.mkdir(parents=True, exist_ok=True)
    cible = tmp_path / "ailleurs.jpg"
    cible.write_bytes(b"original")
    (media / "piege.jpg").symlink_to(cible)
    r = server.media_enregistrer(str(scan), "piege.jpg")
    assert "erreur" in r
    assert cible.read_bytes() == b"original"


def test_media_ecrasement_contenu_different_refuse(app_famille, scan, tmp_path):
    assert "erreur" not in server.media_enregistrer(str(scan), "acte.jpg")
    autre = tmp_path / "autre.jpg"
    autre.write_bytes(b"autre contenu")
    r = server.media_enregistrer(str(autre), "acte.jpg")
    assert "erreur" in r
    assert (app_famille.config.media_dir / "acte.jpg").read_bytes() == scan.read_bytes()
    # même contenu : idempotent
    assert "erreur" not in server.media_enregistrer(str(scan), "acte.jpg")


# ---------------------------------------------------------------- media_pending (#41, envoi vers Gramps)

def _db(chemin: str) -> GrampsDb:
    db = GrampsDb()
    db.put({"_class": "Media", "handle": "h1", "gramps_id": "O1", "path": chemin, "mime": "text/plain",
            "checksum": "", "attribute_list": []})
    return db


@pytest.mark.parametrize("chemin", ["../secret.env", "/SECRET_ABS", "medias/../../secret.env"])
def test_media_pending_hors_repertoire_jamais_lu(tmp_path, chemin):
    data = tmp_path / "donnees"
    data.mkdir()
    secret = tmp_path / "secret.env"
    secret.write_text("TOKEN=xyz")
    chemin = str(secret) if chemin == "/SECRET_ABS" else chemin
    todo, missing = media_pending(_db(chemin), data)
    assert todo == []
    assert any("hors du répertoire" in m for m in missing)


def test_media_pending_lien_symbolique_sortant(tmp_path):
    data = tmp_path / "donnees"
    (data / "medias").mkdir(parents=True)
    secret = tmp_path / "secret.env"
    secret.write_text("TOKEN=xyz")
    (data / "medias" / "lien.txt").symlink_to(secret)
    todo, missing = media_pending(_db("medias/lien.txt"), data)
    assert todo == []
    assert any("hors du répertoire" in m for m in missing)


def test_media_pending_attribut_fichier_prioritaire_controle(tmp_path):
    data = tmp_path / "donnees"
    data.mkdir()
    (tmp_path / "secret.env").write_text("x")
    db = _db("medias/ok.jpg")
    db.all("Media")["h1"]["attribute_list"] = [{"type": A_FICHIER, "value": "../secret.env"}]
    todo, _ = media_pending(db, data)
    assert todo == []


def test_media_pending_interne_accepte(tmp_path):
    data = tmp_path / "donnees"
    (data / "medias").mkdir(parents=True)
    (data / "medias" / "a.jpg").write_bytes(b"img")
    todo, missing = media_pending(_db("medias/a.jpg"), data)
    assert [t["id"] for t in todo] == ["O1"] and missing == []


# ---------------------------------------------------------------- matchid_appariement_statut (#51)

CSV = "nom;prenom;score\nMARTIN;Jean;0.9\n"


@pytest.fixture
def job_fini():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://deces\.matchid\.io/deces/api/v1/search/csv/.*").mock(
            return_value=httpx.Response(200, text=CSV))
        yield mock


@pytest.mark.parametrize("sortie", ["arbre.ged", "journal.jsonl", "../dehors.csv", "ABS",
                                    ".git/config.csv", "resultat.txt"])
def test_matchid_sortie_refusee(app_famille, job_fini, sortie, tmp_path):
    dehors = tmp_path / "dehors.csv"
    sortie = str(dehors) if sortie == "ABS" else sortie
    avant = app_famille.store.path.read_bytes()
    r = server.matchid_appariement_statut("job1", sortie)
    assert "erreur" in r
    assert app_famille.store.path.read_bytes() == avant
    assert not dehors.exists()


def test_matchid_sortie_relative_dans_donnees(app_famille, job_fini):
    r = server.matchid_appariement_statut("job1", "appariements/lot1.csv")
    attendu = app_famille.config.data_dir / "appariements" / "lot1.csv"
    assert Path(r["fichier"]) == attendu
    assert attendu.read_text(encoding="utf-8") == CSV


def test_matchid_sortie_absolue_dans_donnees(app_famille, job_fini):
    cible = app_famille.config.data_dir / "lot2.csv"
    r = server.matchid_appariement_statut("job1", str(cible))
    assert cible.read_text(encoding="utf-8") == CSV and Path(r["fichier"]) == cible


def test_matchid_sans_sortie_apercu(app_famille, job_fini):
    r = server.matchid_appariement_statut("job1")
    assert "apercu" in r and "fichier" not in r


# ---------------------------------------------------------------- hook (#51)

def _hook_decision(tool: str, tool_input: dict) -> str | None:
    hooks = json.loads(HOOKS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    import re
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input})
    for h in hooks:
        if re.fullmatch(h["matcher"], tool):
            for cmd in h["hooks"]:
                out = subprocess.run(["sh", "-c", cmd["command"]], input=payload, capture_output=True,
                                     text=True, check=True).stdout
                if out.strip():
                    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    return None


@pytest.mark.skipif(shutil.which("sh") is None, reason="sh requis")
@pytest.mark.parametrize("tool_input,attendu", [
    ({"job": "1"}, "allow"),
    ({"job": "1", "sortie": ""}, "allow"),
    ({"job": "1", "sortie": "lot.csv"}, "ask"),
    ({"job": "1", "sortie": "../arbre.ged"}, "ask"),
])
def test_hook_statut_matchid(tool_input, attendu):
    assert _hook_decision("mcp__plugin_genealogiste_genealogiste__matchid_appariement_statut", tool_input) == attendu
