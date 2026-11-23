"""Cas témoins du contexte historique (#292) : arbres fictifs et attendus, critère d'arrêt du jalon M7.

Ces tests ne vérifient que la cohérence des données de test avec leurs attendus ; aucun outil de contexte
n'existe encore. Les lots suivants s'appuient sur ces cas (fixture `app_contexte`)."""

import re

import pytest

from genealogiste_mcp import coherence, privacy, server
from genealogiste_mcp.normalize.dates import parse_date

DOSSIER = "contexte"


def _annees(date: str) -> tuple[int, int]:
    """Années extrêmes de la date (parse_date valide la forme ; l'intervalle est en jours depuis l'an 0)."""
    assert parse_date(date), f"date illisible : {date!r}"
    annees = [int(a) for a in re.findall(r"\b(\d{4})\b", date)]
    return min(annees), max(annees)


def _personne(app):
    return app.tree().personnes[app.attendus["personne"]]


def _evenements(p):
    return [e for e in p.evenements if e.type != "FAMC"]


def test_quatre_cas_declares(fixtures):
    presents = {p.stem for p in (fixtures / DOSSIER).glob("*.ged")}
    assert presents == {"mineur_artois_oklahoma", "cultivateur_ancien_regime", "soldat_1914_1918",
                        "lieu_non_documente"}
    assert {p.name.removesuffix(".attendus.json") for p in (fixtures / DOSSIER).glob("*.json")} == presents


def test_import_sans_alerte_bloquante(app_contexte, fixtures):
    alertes = coherence.check_tree(app_contexte.tree())
    assert not [a for a in alertes if a["niveau"] == "erreur"], alertes
    p = server.arbre_importer_gedcom(str(fixtures / DOSSIER / f"{app_contexte.cas}.ged"), "remplacer")
    assert "erreur" not in p, p
    assert not p.get("nouvelles_alertes_coherence"), p["nouvelles_alertes_coherence"]


def test_personne_non_presumee_vivante(app_contexte):
    t = app_contexte.tree()
    p = _personne(app_contexte)
    statut = privacy.is_living(t, p)
    assert statut["vivant"] is False, statut
    assert not privacy.living_ids(t)


def test_chaque_fait_est_source(app_contexte):
    """Règle EXIGER_SOURCE : aucune assertion sans citation (aucun `non_source` dans les cas témoins)."""
    p = _personne(app_contexte)
    for e in p.evenements:
        assert e.citations, f"{e.type} {e.date} sans citation"
        assert all(c.page for c in e.citations), f"{e.type} {e.date} : citation sans page"
        assert all(c.source in app_contexte.tree().sources for c in e.citations)


def test_bornes_de_vie_coherentes(app_contexte):
    att, p = app_contexte.attendus, _personne(app_contexte)
    naissance = next(e for e in p.events("BIRT"))
    deces = next(e for e in p.events("DEAT"))
    assert _annees(naissance.date)[0] == _annees(att["vie"]["naissance"])[0]
    assert _annees(deces.date)[1] == _annees(att["vie"]["deces"])[1]
    debut, fin = _annees(naissance.date)[0], _annees(deces.date)[1]
    for e in p.evenements:
        if e.date:
            assert debut <= _annees(e.date)[0] and _annees(e.date)[1] <= fin, f"{e.type} {e.date} hors de la vie"


def test_lieux_et_pays_attendus(app_contexte):
    att, p = app_contexte.attendus, _personne(app_contexte)
    reels = [(e.type, e.lieu.nom) for e in p.evenements if e.lieu]
    attendus = [(x["evenement"], x["lieu"]) for x in att["lieux"]]
    assert sorted(reels) == sorted(attendus)
    for x in att["lieux"]:
        assert x["pays"] and x["lieu"].rsplit(", ", 1)[-1] == x["pays"], x  # pays = dernier segment du lieu


def test_metier_attendu(app_contexte):
    p = _personne(app_contexte)
    assert [e.valeur for e in p.events("OCCU")] == [app_contexte.attendus["metier"]]


def test_interdits_bien_formes(app_contexte):
    att = app_contexte.attendus
    ni = att["ne_doit_pas_contenir"]
    assert set(ni) == {"causalites", "hors_periode", "hors_lieu", "anachronismes", "phrases_generiques"}
    assert ni["causalites"] and ni["hors_periode"]
    naissance = _annees(_personne(app_contexte).events("BIRT")[0].date)[0]
    deces = _annees(_personne(app_contexte).events("DEAT")[0].date)[1]
    for x in ni["hors_periode"]:
        assert not naissance <= x["annee"] <= deces, f"{x['element']} ({x['annee']}) tombe dans la vie"
    assert att["sortie_si_non_documente"] == "contexte non documenté"
    assert isinstance(att["contexte_documente"], bool)


def test_interdits_absents_de_l_arbre(app_contexte):
    """L'arbre ne contient lui-même aucune des formulations interdites (sinon l'attendu serait invérifiable)."""
    from genealogiste_mcp.gedcom.mapping import write_gedcom
    texte = write_gedcom(app_contexte.tree()).lower()
    ni = app_contexte.attendus["ne_doit_pas_contenir"]
    for cle in ("causalites", "hors_lieu", "anachronismes", "phrases_generiques"):
        for phrase in ni[cle]:
            assert phrase.lower() not in texte, phrase
    assert not re.search(r"courri[eè]res", texte)


def test_cas_mineur_pays_de_charleroi(app_contexte):
    if app_contexte.cas != "mineur_artois_oklahoma":
        pytest.skip("cas propre au mineur")
    p = _personne(app_contexte)
    deces = p.events("DEAT")[0]
    assert deces.lieu.nom.endswith("Pennsylvanie, États-Unis") and "Belgique" not in deces.lieu.nom
    evens = [e for e in p.events("EVEN") if not e.type_detail]
    assert len(evens) == 1 and evens[0].date == "17 SEP 1917" and "Oklahoma" in evens[0].lieu.nom
    dernier_france = max((e for e in p.evenements if e.lieu and e.lieu.nom.endswith("France")),
                         key=lambda e: _annees(e.date)[1] if e.date else 0)
    assert dernier_france.date == "JUL 1906" and ", Nord," in dernier_france.lieu.nom
