"""Citation normée d'une Reference (#321) : ISO 690 par défaut, Evidence Explained en option."""

from __future__ import annotations

import pytest

from genealogiste_mcp.config import load_config, style_citation
from genealogiste_mcp.contexte.citation import STYLES, champs_manquants, citer
from genealogiste_mcp.contexte.modeles import Reference

COMMUN = {"service": "test", "requete": "q", "consulte_le": "2026-11-23"}


def ref(**kw) -> Reference:
    return Reference.from_dict({**COMMUN, **kw})


ARTICLE = ref(identifiant={"type": "doi", "valeur": "10.3406/rnord.1975.3360"}, type_document="article",
              auteurs=["Dupont, Jean", "Martin, Paul"], titre="Les mineurs de Courrières",
              publication="Revue du Nord", annee=1975, volume="57", numero="225", pages="45-67",
              nature="secondaire_savante", evaluation_par_les_pairs="oui", lu="oui")
THESE = ref(identifiant={"type": "hal", "valeur": "tel-01234567"}, type_document="these",
            auteurs=["Martin, Paul"], titre="Les houillères du Nord, 1880-1914", publication="Université de Lille",
            lieu_edition="Lille", annee=1998, nature="secondaire_savante", lu="oui")
MONOGRAPHIE = ref(identifiant={"type": "ppn", "valeur": "02659968X"}, type_document="monographie",
                  auteurs=["Durand, Louis"], titre="Histoire de Courrières", publication="Imprimerie centrale",
                  lieu_edition="Arras", annee=1950, pages="320", nature="secondaire")
PRESSE = ref(identifiant={"type": "ark", "valeur": "ark:/12148/bpt6k4659837"}, type_document="presse",
             publication="Le Grand Écho du Nord de la France", date="1906-03-12", numero="71", pages="2",
             nature="primaire", acces="libre")


@pytest.mark.parametrize("reference, attendu", [
    (ARTICLE, "DUPONT, Jean et MARTIN, Paul. Les mineurs de Courrières. Revue du Nord. 1975, vol. 57, n° 225, "
              "p. 45-67. [Consulté le 23 novembre 2026]. DOI 10.3406/rnord.1975.3360."),
    (THESE, "MARTIN, Paul. Les houillères du Nord, 1880-1914. Thèse de doctorat. Lille : Université de Lille, "
            "1998. [Consulté le 23 novembre 2026]. HAL tel-01234567."),
    (MONOGRAPHIE, "DURAND, Louis. Histoire de Courrières. Arras : Imprimerie centrale, 1950. 320 p. "
                  "[Consulté le 23 novembre 2026]. PPN 02659968X. [Notice seule, non lu.]"),
    (PRESSE, "Le Grand Écho du Nord de la France. 12 mars 1906, n° 71, p. 2. [Consulté le 23 novembre 2026]. "
             "ark:/12148/bpt6k4659837. [Notice seule, non lu.]"),
])
def test_iso690_cas_types(reference, attendu):
    assert citer(reference) == attendu
    assert citer(reference, "iso690") == attendu


def test_iso690_plus_de_trois_auteurs():
    r = ref(identifiant={"type": "doi", "valeur": "10.1000/x"}, type_document="article", nature="secondaire",
            auteurs=["A, a", "B, b", "C, c", "D, d"], titre="T", publication="R", annee=2000, pages="1-2", lu="oui")
    assert citer(r).startswith("A, a et al. T. R. 2000, p. 1-2.")


def test_auteur_sans_virgule_non_reordonne():
    r = ref(identifiant={"type": "url", "valeur": "https://example.org/x"}, nature="tertiaire",
            auteurs=["Société d'émulation de Roubaix"], titre="Annuaire", annee=1900, lu="oui")
    assert citer(r).startswith("Société d'émulation de Roubaix. Annuaire. 1900.")
    assert "Disponible à l'adresse : https://example.org/x." in citer(r)


def test_reference_incomplete_citee_avec_champs_connus_sans_invention():
    r = ref(identifiant={"type": "ppn", "valeur": "123456789"}, type_document="monographie",
            titre="Monographie de la commune de Lens", nature="secondaire")
    texte = citer(r)
    assert texte == ("Monographie de la commune de Lens. [Consulté le 23 novembre 2026]. PPN 123456789. "
                     "[Non renseigné : auteur, éditeur, lieu d'édition, année.] [Notice seule, non lu.]")
    assert champs_manquants(r) == ["auteur", "éditeur", "lieu d'édition", "année"]
    assert "s. d." not in texte and "s. n." not in texte  # aucune valeur de substitution


def test_evidence_explained():
    assert citer(ARTICLE, "evidence_explained") == (
        "Jean Dupont et Paul Martin, « Les mineurs de Courrières », Revue du Nord 57, n° 225 (1975) : 45-67 ; "
        "DOI 10.3406/rnord.1975.3360 ; consulté le 23 novembre 2026.")
    assert citer(MONOGRAPHIE, "evidence_explained") == (
        "Louis Durand, Histoire de Courrières (Arras : Imprimerie centrale, 1950), 320 p. ; PPN 02659968X ; "
        "consulté le 23 novembre 2026. [Notice seule, non lu.]")
    assert citer(THESE, "evidence_explained").startswith(
        "Paul Martin, « Les houillères du Nord, 1880-1914 » (thèse de doctorat, Lille : Université de Lille, 1998)")
    assert citer(PRESSE, "evidence_explained").startswith(
        "Le Grand Écho du Nord de la France, 12 mars 1906, n° 71, p. 2 ; ark:/12148/bpt6k4659837 ;")


def test_italique_markdown():
    assert "*Revue du Nord*" in citer(ARTICLE, italique=True)
    assert "*Histoire de Courrières*" in citer(MONOGRAPHIE, italique=True)


def test_style_inconnu_refuse():
    with pytest.raises(ValueError):
        citer(ARTICLE, "apa")


def test_variable_de_style(monkeypatch):
    assert STYLES == ("iso690", "evidence_explained")
    assert load_config().contexte_style_citation == "iso690"
    monkeypatch.setenv("GENEALOGISTE_CONTEXTE_STYLE_CITATION", "Evidence_Explained")
    assert load_config().contexte_style_citation == "evidence_explained"
    assert style_citation(" ") == "iso690"
    with pytest.raises(ValueError, match="GENEALOGISTE_CONTEXTE_STYLE_CITATION"):
        style_citation("chicago")


def test_to_dict_utilise_le_style():
    assert ARTICLE.to_dict()["citation"] == citer(ARTICLE)
    assert ARTICLE.to_dict(style="evidence_explained")["citation"] == citer(ARTICLE, "evidence_explained")
