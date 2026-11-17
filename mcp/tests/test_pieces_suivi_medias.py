"""#193 (point 4) : une pièce référencée par un média de l'arbre peut être rangée par pieces_appliquer si
pieces_proposer(suivre_medias=true) ; la référence du média est alors mise à jour par une proposition d'arbre
(modifier_media, diff + jeton) produite APRÈS le déplacement réussi et appliquée par arbre_appliquer après accord.
Données fictives."""

import hashlib

import pytest
from gramps_fake import FakeGrampsWeb
from test_gramps_backend import make_app, seed

from genealogiste_mcp import server
from genealogiste_mcp.gramps.mapping import A_FICHIER, _attr_value
from genealogiste_mcp.models import Media
from genealogiste_mcp.tree.proposals import ProposalError

JPEG = b"\xff\xd8\xff\xe0image-fictive-acte\xff\xd9"
NOM = "acte naissance DUPONT 1850.jpg"
ANCIEN = f"medias/scans/{NOM}"
NEUF = f"medias/documents/État civil/DUPONT/{NOM}"


def _ecrire(base, rel: str, data: bytes = JPEG):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


@pytest.fixture
def fapp(app_famille):
    """Média O1 de l'arbre (backend fichier) pointant vers une pièce non classée de <données>/medias."""
    _ecrire(app_famille.config.data_dir, ANCIEN)
    p = server.arbre_proposer([{"op": "ajouter_media", "fichier": ANCIEN, "format": "image/jpeg", "titre": "Acte"}],
                              "Média", "Image de l'acte.")
    assert "erreur" not in p, p
    server.arbre_appliquer(p["jeton"])
    return app_famille


def _medias(a):
    return a.config.media_dir


def test_gel_par_defaut_et_suggestion(fapp):
    r = server.pieces_proposer(str(_medias(fapp)))
    assert r["references_arbre_non_deplacees"] == [f"scans/{NOM}"]
    assert r.get("note") == "Rien à déplacer."
    assert "suivre_medias" in r["medias_conseil"]
    assert (fapp.config.data_dir / ANCIEN).is_file()


def test_suivi_deplace_puis_propose_l_arbre(fapp):
    r = server.pieces_proposer(str(_medias(fapp)), suivre_medias=True)
    assert "erreur" not in r, r
    assert r["references_arbre_non_deplacees"] == []
    assert r["medias_suivis"] == [f"O1 : {ANCIEN} → {NEUF}"]
    assert any("média de l'arbre suivi" in x for x in r["apercu"])
    assert fapp.tree().medias["O1"].fichier == ANCIEN  # rien d'écrit

    out = server.pieces_appliquer(r["jeton"])
    assert out["erreurs"] == [] and (fapp.config.data_dir / NEUF).is_file()
    assert out["medias_a_mettre_a_jour"] == [f"O1 : {ANCIEN} → {NEUF}"]
    prop = out["proposition_arbre"]
    assert prop["jeton"] and NEUF in prop["diff"]
    assert "arbre_appliquer" in out["consigne_medias"]
    assert fapp.tree().medias["O1"].fichier == ANCIEN  # l'arbre attend l'accord

    assert "erreur" not in server.arbre_appliquer(prop["jeton"])
    assert fapp.tree().medias["O1"].fichier == NEUF

    # l'annulation du rangement propose le retour de la référence
    u = server.pieces_proposer(str(_medias(fapp)), annuler=out["journal"].split("/")[-1])
    back = server.pieces_appliquer(u["jeton"])
    assert back["medias_a_mettre_a_jour"] == [f"O1 : {NEUF} → {ANCIEN}"]
    server.arbre_appliquer(back["proposition_arbre"]["jeton"])
    assert fapp.tree().medias["O1"].fichier == ANCIEN and (fapp.config.data_dir / ANCIEN).is_file()


def test_proposition_impossible_ops_fournies(fapp, monkeypatch):
    r = server.pieces_proposer(str(_medias(fapp)), suivre_medias=True)

    def refus(*a, **k):
        raise ProposalError("arbre verrouillé")
    monkeypatch.setattr(type(fapp.backend), "propose", refus)
    out = server.pieces_appliquer(r["jeton"])
    assert out["deplaces"] == 1 and "proposition_arbre" not in out
    assert "arbre verrouillé" in out["avertissement_medias"]
    assert out["operations_medias"] == [{"op": "modifier_media", "id": "O1", "champs": {"fichier": NEUF}}]
    monkeypatch.undo()
    p = server.arbre_proposer(out["operations_medias"], "Suivi", "Pièce rangée.")
    assert "erreur" not in p, p
    server.arbre_appliquer(p["jeton"])
    assert fapp.tree().medias["O1"].fichier == NEUF


def test_arbre_illisible_au_moment_d_appliquer_rien_ne_bouge(fapp, monkeypatch):
    r = server.pieces_proposer(str(_medias(fapp)), suivre_medias=True)

    def panne():
        raise OSError("arbre.ged illisible")
    monkeypatch.setattr(fapp, "tree", panne)
    out = server.pieces_appliquer(r["jeton"])
    assert "rien n'a été déplacé" in out["erreur"]
    assert (fapp.config.data_dir / ANCIEN).is_file()


def test_doublon_reference_jamais_isole(fapp):
    _ecrire(_medias(fapp), f"autre/{NOM}")  # même contenu, non référencé
    r = server.pieces_proposer(str(_medias(fapp)), suivre_medias=True)
    vers = {x.split("  →  ")[0]: x.split("  →  ")[1] for x in r["apercu"]}
    assert vers[f"scans/{NOM}"].startswith(f"documents/État civil/DUPONT/{NOM}")
    assert vers[f"autre/{NOM}"].startswith("archives/Doublons/")


def test_hors_racines_medias_reste_gele(app_famille, tmp_path):
    """Racine d'organisation hors des répertoires des médias : modifier_media refuserait le nouveau chemin."""
    r0 = tmp_path / "p"
    f = _ecrire(r0, NOM)
    t = app_famille.tree()
    t.medias["O99"] = Media(id="O99", fichier=str(f))
    app_famille.store.write(t)
    r = server.pieces_proposer(str(r0), suivre_medias=True)
    assert r["references_arbre_non_deplacees"] == [NOM]
    assert "hors des répertoires des médias" in r["medias_conseil"]
    assert f.is_file()


def test_reference_relative_a_l_arborescence_des_pieces_gelee(app_famille, tmp_path):
    """Référence relative au vault (pieces_root, #192) : reconnue comme média de l'arbre."""
    vault = tmp_path / "vault"
    app_famille.config.media_dir_conf = vault / "documents"
    _ecrire(vault, f"scans/{NOM}")
    t = app_famille.tree()
    t.medias["O99"] = Media(id="O99", fichier=f"scans/{NOM}")
    app_famille.store.write(t)
    r = server.pieces_proposer(str(vault))
    assert r["references_arbre_non_deplacees"] == [f"scans/{NOM}"]


# ============================================================================ backend Gramps Web

@pytest.fixture
def fake():
    with FakeGrampsWeb() as f:
        yield f


@pytest.fixture
def gapp(tmp_path, fake, tree):
    seed(fake, tree)
    a = make_app(tmp_path)
    yield a
    server.set_app(None)


def test_gramps_suivi(gapp, fake):
    _ecrire(gapp.config.data_dir, ANCIEN)
    p = server.arbre_proposer([{"op": "ajouter_media", "fichier": ANCIEN, "format": "image/jpeg", "titre": "Acte"}],
                              "Média", "Image de l'acte.")
    server.arbre_appliquer(p["jeton"])
    media = fake.find("Media", "O1")
    assert media["checksum"] == hashlib.md5(JPEG).hexdigest()

    r = server.pieces_proposer(str(gapp.config.media_dir), suivre_medias=True)
    assert r["medias_suivis"] == [f"O1 : {ANCIEN} → {NEUF}"], r
    out = server.pieces_appliquer(r["jeton"])
    prop = out["proposition_arbre"]
    assert not prop["transaction_gramps"].get("fichiers_a_envoyer")  # même contenu : rien à renvoyer
    assert _attr_value(fake.find("Media", "O1"), A_FICHIER) == ANCIEN
    res = server.arbre_appliquer(prop["jeton"])
    assert "erreur" not in res, res
    after = fake.find("Media", "O1")
    assert _attr_value(after, A_FICHIER) == NEUF
    assert (after["path"], after["checksum"]) == (media["path"], media["checksum"])
