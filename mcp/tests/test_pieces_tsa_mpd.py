"""Pièces de l'enregistrement (série 3 Q) : codes TSA et MPD, distincts des actes notariés (#258)."""

from __future__ import annotations

from pathlib import Path

import pytest

from genealogiste_mcp import pieces, server
from genealogiste_mcp.types_documents import SERIES


def test_codes_rattaches_a_l_enregistrement():
    assert pieces.TYPES["TSA"][1] == pieces.TYPES["MPD"][1] == "Enregistrement"
    assert pieces.TYPES_ARCHIVES["TSA"] == pieces.TYPES_ARCHIVES["MPD"] == "enregistrement"


@pytest.mark.parametrize("nom, code", [
    ("DUPONT TSA 1850.pdf", "TSA"),
    ("table des successions DUPONT.jpg", "TSA"),
    ("Tables de successions et absences DUPONT.pdf", "TSA"),
    ("DUPONT successions et absences Erre.jpg", "TSA"),
    ("DUPONT mutation par décès 1880.pdf", "MPD"),
    ("DUPONT mutations après décès.pdf", "MPD"),
    ("déclaration de succession DUPONT 1880.pdf", "MPD"),
    ("DUPONT déclaration de mutation.pdf", "MPD"),
    ("DUPONT MPD 1880.pdf", "MPD"),
    # « succession » seul, partage, notoriété : actes notariés
    ("DUPONT succession 1880.pdf", "NOT"),
    ("DUPONT partage succession.pdf", "NOT"),
    ("DUPONT acte de décès.pdf", "D"),
])
def test_detection_nom_libre(nom, code):
    info = pieces.detecter(Path(nom))
    assert info["type"] == code
    assert info["patronyme"] == "DUPONT"


def test_convention_et_classement():
    info = pieces.detecter(Path("DUPONT Jean -- ERRE - AD59 - TSA [1850] - 3 Q 12-45.jpg"))
    assert (info["type"], info["cote"]) == ("TSA", "3 Q 12-45")
    assert pieces.destination(info) == "documents/Enregistrement/DUPONT"
    info = pieces.detecter(Path("DUPONT Jean -- ERRE - AD59 - MPD [1880].pdf"))
    assert pieces.destination(info) == "documents/Enregistrement/DUPONT"


def test_cote_3q_seule_ne_deduit_pas_le_type():
    assert pieces.detecter(Path("DUPONT Jean -- ERRE - AD59 - 3 Q 1234.pdf"))["type"] == ""


@pytest.mark.parametrize("cote", ["3 Q 1234", "3Q 12-45", "3 Q 52/123", "3q12", " 3 Q 7 "])
def test_cote_3q_reconnue(cote):
    assert pieces.cote_3q(cote)


@pytest.mark.parametrize("cote", ["", "4 Q 12", "13 Q 4", "3 QA 1", "3 E 12", "Q 3"])
def test_cote_hors_3q(cote):
    assert not pieces.cote_3q(cote)


def test_rattachement_tsa():
    r = pieces.rattachement_archives("TSA")
    assert r["type_document"] == "enregistrement" and r["serie"] == SERIES["enregistrement"]
    assert r["cote"] == "a_completer" and "3 Q" in r["consigne"] and "bureau" in r["consigne"]
    assert "librement communicables" in r["communicabilite"]
    assert pieces.rattachement_archives("TSA", "3 Q 12/45")["cote"] == "serie_3q"
    r = pieces.rattachement_archives("TSA", "Q 456")
    assert r["cote"] == "hors_3q" and "vérifier" in r["consigne"]


def test_rattachement_mpd_cinquante_ans():
    r = pieces.rattachement_archives("MPD", "3 Q 9/88")
    assert r["cote"] == "serie_3q" and "50 ans" in r["communicabilite"]


def test_rattachement_not_inchange():
    r = pieces.rattachement_archives("NOT", "3 Q 12")
    assert (r["type_document"], r["cote"]) == ("notaire", "hors_3e")
    assert "communicabilite" not in r


def test_piece_nommer_tsa(app):
    r = server.piece_nommer(["DUPONT Jean"], "Erre", "AD59", "TSA", "1850", cote="3 Q 12/45", extension=".jpg")
    assert r["nom"] == "DUPONT Jean -- ERRE - AD59 - TSA [1850] - 3 Q 12-45.jpg"
    assert r["dossier_convention"] == "documents/Enregistrement/DUPONT"
    assert r["archives"]["type_document"] == "enregistrement" and r["archives"]["cote"] == "serie_3q"
