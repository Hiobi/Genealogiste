"""#38, #44, #48, #53 : écritures du backend fichier (verrou, atomicité, reprise, indexation explicite, JSONL)."""

import os
import subprocess
import threading

import pytest

from genealogiste_mcp import fichiers, server
from genealogiste_mcp.fichiers import ajouter_jsonl, ecrire_atomique, lire_jsonl
from genealogiste_mcp.tree.store import GITIGNORE_REQUIS


def _prop(pid="I7"):
    return server.arbre_proposer([{"op": "marquer_vivant", "id": pid, "vivant": "N"}], "t", "justification")


def _git(app, *args):
    return subprocess.run(["git", "-C", str(app.store.dir), *args], capture_output=True, text=True).stdout


# ---------------------------------------------------------------- #44 atomicité et reprise

def test_ecriture_atomique_jamais_tronquee(tmp_path, monkeypatch):
    f = tmp_path / "arbre.ged"
    f.write_text("ancien", encoding="utf-8")

    def panne(*_):
        raise OSError("disque plein")
    monkeypatch.setattr(fichiers.os, "replace", panne)
    with pytest.raises(OSError):
        ecrire_atomique(f, "nouveau contenu")
    assert f.read_text(encoding="utf-8") == "ancien"
    assert [p.name for p in tmp_path.iterdir()] == ["arbre.ged"]  # temporaire nettoyé


def test_echec_du_commit_restaure_et_garde_le_jeton(app_famille):
    avant = app_famille.store.path.read_text(encoding="utf-8")
    hook = app_famille.store.dir / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    p = _prop()
    r = server.arbre_appliquer(p["jeton"])
    assert "erreur" in r and "restauré" in r["erreur"]
    assert app_famille.store.path.read_text(encoding="utf-8") == avant
    assert any(x["jeton"] == p["jeton"] for x in app_famille.backend.pending())
    hook.unlink()
    r = server.arbre_appliquer(p["jeton"])  # reprise
    assert r["commit"] and r["ecrit"] and r["commite"]


# ---------------------------------------------------------------- #38 concurrence

def test_deux_applications_concurrentes_une_seule_reussit(app_famille):
    jetons = [_prop("I7")["jeton"], _prop("I6")["jeton"]]
    res = []
    barriere = threading.Barrier(2)

    def go(j):
        barriere.wait()
        res.append(server.arbre_appliquer(j))
    th = [threading.Thread(target=go, args=(j,)) for j in jetons]
    [t.start() for t in th]
    [t.join() for t in th]
    assert sum("commit" in r for r in res) == 1
    assert sum("a changé" in r.get("erreur", "") for r in res) == 1


def test_meme_jeton_concurrent_usage_unique(app_famille):
    j = _prop()["jeton"]
    res = []
    th = [threading.Thread(target=lambda: res.append(server.arbre_appliquer(j))) for _ in range(4)]
    [t.start() for t in th]
    [t.join() for t in th]
    assert sum("commit" in r for r in res) == 1


def test_empreinte_de_la_proposition_sur_l_etat_du_diff(app_famille):
    import hashlib
    texte = app_famille.store.text()
    p = _prop()
    rec = app_famille.backend.tokens.peek(p["jeton"])
    assert rec["empreinte_base"] == hashlib.sha256(texte.encode()).hexdigest()


# ---------------------------------------------------------------- #48 indexation explicite

def test_fichiers_etrangers_jamais_commites(app_famille):
    d = app_famille.store.dir
    (d / ".gitignore").write_text("medias/\n", encoding="utf-8")  # .gitignore préexistant incomplet
    (d / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (d / "brouillon.txt").write_text("perso", encoding="utf-8")
    app_famille.store.ensure()
    lignes = (d / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "medias/" in lignes and all(x in lignes for x in GITIGNORE_REQUIS)
    server.arbre_appliquer(_prop()["jeton"])
    suivis = _git(app_famille, "ls-files").split()
    assert ".env" not in suivis and "brouillon.txt" not in suivis
    assert _git(app_famille, "show", "--name-only", "--format=", "HEAD").split() == ["arbre.ged"]


def test_journal_commite_a_part(app_famille):
    server.journal_ajouter("AD17", "consultation", "negatif", "rien")
    server.arbre_appliquer(_prop()["jeton"])
    assert _git(app_famille, "show", "--name-only", "--format=", "HEAD").split() == ["arbre.ged"]
    assert "journal.jsonl" in _git(app_famille, "show", "--name-only", "--format=", "HEAD~1").split()


def test_apercu_annulation_perimetre_exact(app_famille):
    d = app_famille.store.dir
    t = app_famille.store.load()
    t.personnes["I7"].vivant = "N"
    app_famille.store.write(t)
    (d / "rapports").mkdir(exist_ok=True)
    (d / "rapports" / "r.md").write_text("rapport", encoding="utf-8")
    c = app_famille.store.commit("mixte", ["arbre.ged", "rapports/r.md"])
    p = server.arbre_annuler_modification(c)
    assert set(p["fichiers_annules"]) == {"arbre.ged", "rapports/r.md"}
    assert "rapports/r.md" in p["attention"] and "rapports/r.md" in p["diff_annule"]


# ---------------------------------------------------------------- #53 JSONL

def test_jsonl_ligne_tronquee_tolere(tmp_path):
    f = tmp_path / "journal.jsonl"
    ajouter_jsonl(f, {"id": 1})
    with f.open("a", encoding="utf-8") as fh:
        fh.write('{"id": 2, "res')  # arrêt pendant l'écriture
    ajouter_jsonl(f, {"id": 3})
    ok, bad = lire_jsonl(f)
    assert [e["id"] for e in ok] == [1, 3] and bad == [2]


def test_journal_lister_signale_sans_bloquer(app_famille):
    server.journal_ajouter("AD17", "consultation", "negatif", "rien")
    with app_famille.journal.path.open("a", encoding="utf-8") as fh:
        fh.write("{tronq")
    out = server.journal_lister()
    assert "avertissement" in out[0] and any(e.get("source") == "AD17" for e in out[1:])
    assert os.path.getsize(app_famille.journal.path) > 0
