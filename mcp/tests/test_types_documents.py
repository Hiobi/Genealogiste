"""Vocabulaire commun et compatibilité des appels publics (#129)."""
from datetime import date

import pytest

from genealogiste_mcp import archives, fr_sources, server
from genealogiste_mcp.types_documents import ALIASES, DOCUMENTS, TYPES_DOCUMENTS, normaliser


def test_catalogue_coherent_et_exceptions_explicitement_hors_catalogue():
    assert archives.DOCUMENTS == DOCUMENTS
    for key in DOCUMENTS:
        assert key in fr_sources.RULES and key in fr_sources.SERIES
        assert TYPES_DOCUMENTS[key].libelle
        assert "erreur" not in fr_sources.communicability(key)
    assert {k for k, v in TYPES_DOCUMENTS.items() if not v.catalogue} == {"medical", "vie_privee", "etat_civil"}


@pytest.mark.parametrize("alias,canonique", list(ALIASES.items()))
def test_alias_meme_regle_et_meme_couverture(alias, canonique):
    a = fr_sources.communicability(alias, "1800", today=date(2026, 1, 1))
    b = fr_sources.communicability(canonique, "1800", today=date(2026, 1, 1))
    assert {k: v for k, v in a.items() if k != "document"} == {k: v for k, v in b.items() if k != "document"}
    assert archives.service(code="AD59", document=alias, annee=1800) == archives.service(code="AD59", document=canonique, annee=1800)
    assert fr_sources.SERIES[alias] == fr_sources.SERIES[canonique]


@pytest.mark.parametrize("key", ["paroissiaux", "enregistrement", "insinuation", "etat_civil"])
def test_type_large_ne_deduit_pas_delai(key):
    r = fr_sources.communicability(key, "1700", today=date(2026, 1, 1))
    assert r["communicable"] is None and r["delai_annees"] is None
    assert "erreur" not in r and "préciser" in r["note"]


def test_alias_transmis_a_couverture_en_ligne(monkeypatch):
    service = {"code": "AD99", "nom": "Fictif", "type": "autre", "site": "https://archives.example",
               "en_ligne": {"matricule": {"de": 1800, "a": 1900}}}
    monkeypatch.setattr(archives, "services", lambda: (service,))
    assert archives.online(service, "matricules", 1850)
    assert archives.view(service, "matricules", 1850)["en_ligne_pour_la_demande"] is True
    appels = []
    monkeypatch.setattr(archives, "service", lambda **kw: appels.append(kw) or {"en_ligne_pour_la_demande": True})
    resultat = archives.communicability_online("matricules", "1850", "1800", lieu="Commune fictive")
    assert resultat["type_document"] == "matricule" and resultat["en_ligne"] is True
    assert appels[0]["document"] == "matricule"


def test_accents_et_cle_inconnue_restent_explicites(app):
    assert normaliser("  Hypothèques ") == "hypotheques"
    assert server.communicabilite("hypothèques", "1800")["type_document"] == "hypotheques"
    assert "erreur" in server.communicabilite("naturalisations", "1800")
