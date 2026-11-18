"""Type de pièce NOT relié à la série 3 E et au type d'archives « notaire » (#223)."""

from __future__ import annotations

from pathlib import Path

import pytest

from genealogiste_mcp import pieces, server
from genealogiste_mcp.types_documents import SERIES, TYPES_DOCUMENTS


def test_not_rattache_au_type_notaire_du_vocabulaire():
    assert pieces.TYPES_ARCHIVES["NOT"] == "notaire"
    assert set(pieces.TYPES_ARCHIVES) <= set(pieces.TYPES)
    assert set(pieces.TYPES_ARCHIVES.values()) <= set(TYPES_DOCUMENTS)


@pytest.mark.parametrize("cote", ["3 E 1234", "3E 12-45", "3 E 52/123", "3e12", " 3 E 7 ", "3 E"])
def test_cote_3e_reconnue(cote):
    assert pieces.cote_3e(cote)


@pytest.mark.parametrize("cote", ["", "4 E 12", "13 E 4", "3 ES 12", "5 Mi 023", "E 3", "3 Q 12", "MC-ET-XV-12"])
def test_cote_hors_3e(cote):
    assert not pieces.cote_3e(cote)


def test_rattachement_sans_cote_suggere_3e():
    r = pieces.rattachement_archives("NOT testament")
    assert r["type_document"] == "notaire" and r["serie"] == SERIES["notaire"]
    assert r["cote"] == "a_completer"
    assert "3 E" in r["consigne"] and "répertoire" in r["consigne"]


def test_rattachement_cote_3e_acceptee():
    r = pieces.rattachement_archives("NOT", "3 E 1234")
    assert (r["type_document"], r["cote"]) == ("notaire", "serie_3e")


def test_rattachement_cote_hors_3e_conservee_sans_refus():
    r = pieces.rattachement_archives("NOT", "MC-ET-XV-12")
    assert r["cote"] == "hors_3e" and "vérifier" in r["consigne"]


@pytest.mark.parametrize("type_piece", ["", "N", "M", "PHOTO", "COUR"])
def test_pas_de_rattachement_hors_not(type_piece):
    assert pieces.rattachement_archives(type_piece, "3 E 12") is None


def test_detecter_cote_3e_sans_type_suggere_not():
    info = pieces.detecter(Path("DUPONT Jean -- ERRE - AD59 - 3 E 1234.pdf"))
    assert info["cote"] == "3 E 1234" and info["type"] == "NOT"
    assert pieces.destination(info) == "documents/Notaires/DUPONT"


def test_detecter_type_explicite_prime_sur_la_cote():
    info = pieces.detecter(Path("DUPONT Jean -- ERRE - AD59 - M [1850] - 3 E 1234.pdf"))
    assert info["type"] == "M"


def test_piece_nommer_not_avec_cote_3e(app):
    r = server.piece_nommer(["DUPONT Jean"], "Erre", "AD59", "NOT testament", "1850", cote="3 E 52/123",
                            extension=".pdf")
    assert r["nom"] == "DUPONT Jean -- ERRE - AD59 - NOT TESTAMENT [1850] - 3 E 52-123.pdf"
    assert r["lecture"]["cote"] == "3 E 52-123"
    assert r["archives"]["type_document"] == "notaire" and r["archives"]["cote"] == "serie_3e"


def test_piece_nommer_not_sans_cote_suggere(app):
    r = server.piece_nommer(["DUPONT Jean"], "Erre", "Étude Leroy", "NOT", "1850", extension=".pdf")
    assert r["archives"]["cote"] == "a_completer"


def test_piece_nommer_hors_not_sans_archives(app):
    r = server.piece_nommer(["DUPONT Jean"], "Erre", "AD59", "N", "1850")
    assert "archives" not in r
