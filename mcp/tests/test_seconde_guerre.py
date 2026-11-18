"""Seconde Guerre mondiale (#131) : variantes françaises et allemandes, fonds connus, classement des pièces.
Exemples fictifs, aucun réseau."""

from pathlib import Path

import pytest

from genealogiste_mcp import outils, pieces, server, sites_tiers
from genealogiste_mcp.normalize import allemand

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("nom,attendues", [
    ("Müller", {"MÜLLER", "MUELLER", "MULLER"}),
    ("MUELLER", {"MÜLLER"}),
    ("Meyer", {"MAIER", "MAYER", "MEIER"}),
    ("Schmidt", {"SCHMITT", "SCHMID"}),
    ("Hoffmann", {"HOFFMAN"}),
    ("Weiß", {"WEISS"}),
    ("Konrad", {"CONRAD"}),
])
def test_variantes_nom(nom, attendues):
    v = allemand.variantes_nom(nom)
    assert v[0] == nom.upper() and attendues <= set(v) and len(v) == len(set(v))


def test_variantes_prenom_dans_les_deux_sens():
    assert allemand.variantes_prenom("Jean") == ["Jean", "Johann", "Johannes", "Hans"]
    assert "Joseph" in allemand.variantes_prenom("Josef")
    assert allemand.variantes_prenom("Charles Louis") == ["Charles", "Karl", "Carl", "Louis", "Ludwig"]
    assert allemand.variantes_prenom("Kévin") == ["Kévin"]  # inconnu : inchangé
    assert allemand.variantes_prenom("") == []


def test_outil_variantes_noms_borne_et_sans_reseau():
    r = server.variantes_noms("Schmidt", "Jean")
    assert "Johann SCHMITT" in r["combinaisons"] and len(r["combinaisons"]) <= 24
    assert outils.OUTILS["variantes_noms"] == (outils.LECTURE, outils.LECTURE)
    assert server.variantes_noms("")["nom"] == []


@pytest.mark.parametrize("a,b", [("Müller", "Mueller"), ("Schmidt", "Schmitt"), ("Weiß", "Weiss")])
def test_comparer_noms_reconnait_les_variantes_germaniques(a, b):
    assert server.comparer_noms(a, b)["score"] >= 0.95


def test_comparer_noms_ne_rapproche_pas_des_noms_differents():
    assert server.comparer_noms("MULLER", "MARTIN")["score"] < 0.8


def test_fonds_de_la_periode_connus():
    codes = {s["code"] for s in sites_tiers.filtrer(theme="ww2")}
    assert {"AROLSEN", "BUNDESARCHIV-INVENIO", "VOLKSBUND", "USHMM-HSV", "FMD-LIVRE-MEMORIAL"} <= codes
    # bornés à la période : rien pour une vie terminée avant 1900
    assert "AROLSEN" not in {s["code"] for s in sites_tiers.filtrer(annee_min=1820, annee_max=1890)}
    assert server.sources_catalogue(theme="ww2")["totaux"]["sites_tiers"] == len(codes)


@pytest.mark.parametrize("nom,type_,pat", [
    ("fiche Arolsen KLEIN Joseph.jpg", "SGM", "KLEIN"),
    ("Stalag XII A WEBER 1941.jpg", "SGM", "WEBER"),
    ("STO MARTIN Paul.jpg", "SGM", "MARTIN"),
    ("cour de justice LEBLANC 1945.pdf", "SGM", "LEBLANC"),
    ("acte deces DUPONT mort en deportation.jpg", "D", "DUPONT"),  # un acte reste un acte
])
def test_classement_des_pieces(nom, type_, pat):
    info = pieces.detecter(Path(nom))
    assert (info["type"], info["patronyme"]) == (type_, pat)
    if type_ == "SGM":
        assert pieces.TYPES["SGM"][1] == "Seconde Guerre mondiale"


def test_skill_et_doc_rappellent_la_distinction_accusation_condamnation():
    skill = (ROOT / "skills" / "seconde-guerre-mondiale" / "SKILL.md").read_text(encoding="utf-8")
    doc = (ROOT / "docs" / "seconde-guerre-mondiale.md").read_text(encoding="utf-8")
    for texte in (skill, doc):
        assert "qualification" in texte.lower() or "qualifier" in texte.lower()
        assert "condamn" in texte and "vivant" in texte
    for outil in ("variantes_noms", "sources_catalogue", "communicabilite", "arbre_proposer"):
        assert outil in skill
