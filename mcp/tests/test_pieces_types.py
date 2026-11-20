"""Types de pièces NOT, CNI, PM, COUR et dossier explicite d'un renommage (#161)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from genealogiste_mcp import pieces, server


def _ecrire(racine: Path, rel: str, contenu: bytes) -> None:
    p = racine / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenu)


def _etat(racine: Path) -> dict[str, str]:
    return {str(p.relative_to(racine)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(racine.rglob("*")) if p.is_file() and "_organisation" not in p.parts}


# ---------------------------------------------------------------- TYPES

@pytest.mark.parametrize("code,dossier", [
    ("NOT", "documents/Notaires/DUPONT"), ("CNI", "documents/Divers/DUPONT"),
    ("PM", "documents/Mines (ANMT)/DUPONT"), ("COUR", "documents/Divers/DUPONT"),
])
def test_types_classes(app, code, dossier):
    assert code in pieces.TYPES
    r = server.piece_nommer(["DUPONT Jean"], "Erre", "Étude Leroy", code, "2003", extension=".pdf")
    assert r["dossier_convention"] == dossier and r["lecture"]["type"] == code


def test_not_sous_type_libre_dans_le_segment_type(app):
    r = server.piece_nommer(["DUPONT Jean"], "Erre", "Étude Leroy", "NOT testament", "1850", extension=".pdf")
    assert r["nom"] == "DUPONT Jean -- ERRE - Étude Leroy - NOT TESTAMENT [1850].pdf"
    assert r["dossier_convention"] == "documents/Notaires/DUPONT"
    assert (r["lecture"]["depot"], r["lecture"]["annees"]) == ("Étude Leroy", "1850")


# ---------------------------------------------------------------- _MOTS et ordre de priorité

@pytest.mark.parametrize("nom,type_", [
    ("DUPONT attestation immobilière après décès 2003.pdf", "NOT"),
    ("DUPONT déclaration de succession après décès.pdf", "MPD"),  # enregistrement, 3 Q (#258)
    ("DUPONT contrat de mariage 1850.pdf", "NOT"),
    ("DUPONT acte de notoriété naissance.pdf", "NOT"),
    ("DUPONT testament.pdf", "NOT"),
    ("DUPONT partage 1870.pdf", "NOT"),
    ("DUPONT inventaire notaire.pdf", "NOT"),
    ("DUPONT acte notarié.pdf", "NOT"),
    ("DUPONT hypothèques 1860.pdf", "NOT"),
    ("DUPONT acte de mariage 1850.jpg", "M"),  # pas de faux positif notarié
    ("DUPONT acte de décès 1880.jpg", "D"),
    ("DUPONT mariage succession de témoins.jpg", "NOT"),
    ("DUPONT carte nationale d'identité.jpg", "CNI"),
    ("DUPONT CNI.jpg", "CNI"),
    ("DUPONT dossier personnel des mines.pdf", "PM"),
    ("DUPONT demande d'acte de naissance service-public.pdf", "COUR"),
    ("DUPONT - demande acte D [1995].pdf", "COUR"),
    ("DUPONT courrier mairie.pdf", "COUR"),
    ("DUPONT lettre 1916.jpg", "COUR"),
    ("DUPONT réponse mairie.pdf", "COUR"),
    ("DUPONT acte de naissance lettre marginale.jpg", "N"),  # « lettre » ne vole pas un acte
    ("DUPONT réponse décès.pdf", "D"),
])
def test_detection_et_ordre(nom, type_):
    info = pieces.detecter(Path(nom))
    assert (info["type"], info["patronyme"]) == (type_, "DUPONT")


def test_mots_ordre_not_avant_n_m_d():
    codes = [c for _, c in pieces._MOTS]
    assert codes.index("NOT") < min(codes.index("N"), codes.index("M"), codes.index("D"))
    assert set(codes) <= set(pieces.TYPES)


@pytest.mark.parametrize("code", ["NOT", "CNI", "PM", "COUR"])
def test_codes_jamais_patronyme(code):
    assert pieces.detecter(Path(f"{code} DUPONT.pdf"))["patronyme"] == "DUPONT"


# ---------------------------------------------------------------- reclassement

def test_reclassement_not_convention(app, tmp_path):
    r0 = tmp_path / "p"
    nom = "X -- COMMUNE - Étude Y - NOT [2003].pdf"
    _ecrire(r0, f"_À trier/{nom}", b"attestation")
    r = server.pieces_proposer(str(r0))
    assert any(f"documents/Notaires/X/{nom}" in m for m in r["apercu"])
    server.pieces_appliquer(r["jeton"])
    assert (r0 / "documents/Notaires/X" / nom).exists()


def test_renommage_reclasse_not(app, tmp_path):
    r0 = tmp_path / "p"
    _ecrire(r0, "_À trier/scan.pdf", b"attestation")
    nom = server.piece_nommer(["X Pierre"], "Commune", "Étude Y", "NOT", "2003", extension=".pdf")["nom"]
    r = server.pieces_proposer(str(r0), renommages=[{"actuel": "_À trier/scan.pdf", "propose": nom}],
                               seulement_renommages=True)
    assert any(f"documents/Notaires/X/{nom}" in m and "acte notarié (renommée)" in m for m in r["apercu"])


# ---------------------------------------------------------------- dossier explicite

def test_renommage_dossier_explicite(app, tmp_path):
    r0 = tmp_path / "p"
    _ecrire(r0, "_À trier/scan1.pdf", b"recap")
    _ecrire(r0, "_À trier/scan2.pdf", b"lettre")
    _ecrire(r0, "_À trier/scan3.jpg", b"photo")
    r = server.pieces_proposer(str(r0), seulement_renommages=True, renommages=[
        {"actuel": "_À trier/scan1.pdf", "propose": "DUPONT Jean -- demande acte D [1995].pdf",
         "dossier": "courriers/DUPONT"},
        {"actuel": "_À trier/scan2.pdf", "propose": "DUPONT Jean -- carnet.pdf", "dossier": "documents/Divers/DUPONT/"},
        {"actuel": "_À trier/scan3.jpg", "propose": "DUPONT Jean -- PHOTO.jpg", "dossier": "photographies/Fêtes"}])
    assert "erreur" not in r, r
    assert any("dossier explicite" in m for m in r["apercu"])
    out = server.pieces_appliquer(r["jeton"])
    assert out["erreurs"] == []
    assert (r0 / "courriers/DUPONT/DUPONT Jean -- demande acte D [1995].pdf").exists()
    assert (r0 / "documents/Divers/DUPONT/DUPONT Jean -- carnet.pdf").exists()
    assert (r0 / "photographies/Fêtes/DUPONT Jean -- PHOTO.jpg").exists()
    # désormais classées : une organisation suivante ne les déplace plus
    assert server.pieces_proposer(str(r0))["note"] == "Rien à déplacer."


@pytest.mark.parametrize("dossier", [
    "personnes", "familles/F1", "sources", "patronymes/DUPONT", "archives/GEDCOM", "_À trier", "/tmp/x",
    "documents/../personnes", "../documents", "documents/.cache", "documents/a:b", "C:/documents",
    "documents\\..\\personnes", 3,
])
def test_renommage_dossier_explicite_refuse(app, tmp_path, dossier):
    r0 = tmp_path / "p"
    _ecrire(r0, "_À trier/scan1.pdf", b"recap")
    avant = _etat(r0)
    r = server.pieces_proposer(str(r0), seulement_renommages=True, renommages=[
        {"actuel": "_À trier/scan1.pdf", "propose": "DUPONT Jean -- carnet.pdf", "dossier": dossier}])
    assert "erreur" in r and "dossier" in r["erreur"].lower()
    assert _etat(r0) == avant


def test_renommage_dossier_explicite_vide_ignore(app, tmp_path):
    r0 = tmp_path / "p"
    _ecrire(r0, "_À trier/scan1.pdf", b"recap")
    r = server.pieces_proposer(str(r0), seulement_renommages=True, renommages=[
        {"actuel": "_À trier/scan1.pdf", "propose": "DUPONT Jean -- NOT [1900].pdf", "dossier": ""}])
    assert any("documents/Notaires/DUPONT/" in m for m in r["apercu"])


def test_renommage_dossier_explicite_lien_symbolique_refuse(app, tmp_path):
    r0 = tmp_path / "p"
    _ecrire(r0, "_À trier/scan1.pdf", b"recap")
    dehors = tmp_path / "dehors"
    dehors.mkdir()
    (r0 / "documents").mkdir()
    (r0 / "documents/Fuite").symlink_to(dehors, target_is_directory=True)
    (r0 / "personnes").mkdir()
    (r0 / "documents/Notes").symlink_to(r0 / "personnes", target_is_directory=True)
    for d in ("documents/Fuite", "documents/Notes/DUPONT"):
        r = server.pieces_proposer(str(r0), seulement_renommages=True, renommages=[
            {"actuel": "_À trier/scan1.pdf", "propose": "DUPONT Jean -- carnet.pdf", "dossier": d}])
        assert "erreur" in r, d
    assert not any(dehors.iterdir())


def test_patronyme_jamais_pris_dans_la_description():
    assert pieces.detecter(Path("X -- COMMUNE - Étude Y - NOT [2003].pdf"))["patronyme"] == "X"
    assert pieces.detecter(Path("dupont jean -- ERRE - AD59 - N [1850].jpg"))["patronyme"] == ""


def test_piece_archiver_accepte_sous_type_not(app):
    r = server.piece_archiver("/inexistant.jpg", personnes=["DUPONT Jean"], type_piece="NOT testament")
    assert "type_piece inconnu" not in str(r.get("erreur", ""))
    assert "type_piece inconnu" in server.piece_archiver("/inexistant.jpg", type_piece="ZZZ")["erreur"]
