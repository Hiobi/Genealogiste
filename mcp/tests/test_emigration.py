"""Parcours émigration / immigration (#284) : sources des deux côtés, fenêtre de départ tirée des seuls faits de
l'arbre, typage d'un événement générique proposé (jamais appliqué), sites relevés du thème emigration."""

from __future__ import annotations

import pytest

from genealogiste_mcp import server, sites_tiers
from genealogiste_mcp.emigration import fenetre_depart
from genealogiste_mcp.export.fiche import fiche_markdown
from genealogiste_mcp.fr_sources import (
    AVERT_FONDS_ETRANGER,
    DECRETS_NATURALISATION,
    POLICE_PASSEPORTS,
    SI_FRANCE,
    next_source_hint,
)
from genealogiste_mcp.gedcom.mapping import read_gedcom
from genealogiste_mcp.types_documents import SERIES

COTES_AD = ("série E", "4 E", "3 Q", "série U", "série M", "série R", "1 R", "4 M", "6 M")
MINEUR = pytest.mark.parametrize("app_contexte", ["mineur_artois_oklahoma"], indirect=True)
US = "Krebs, Pittsburg, Oklahoma, États-Unis"


def _sans_cote_ad(sources: list[dict]) -> None:
    for s in sources:
        assert s["cote_typique"] not in SERIES.values() and s["cote_typique"] != POLICE_PASSEPORTS, s
        assert not any(c in s["cote_typique"] for c in COTES_AD), s
        assert "condition" not in s, s


def _versants(sources: list[dict]) -> set[str]:
    return {s.get("versant") for s in sources}


# ---------------------------------------------------------------------------- chaînes de sources

def test_emig_en_france_sources_des_deux_cotes():
    out = next_source_hint("EMIG", "1906", "Fenain, Nord")
    assert _versants(out) == {"france", "etranger"}
    fr = {s["source"]: s for s in out if s["versant"] == "france"}
    assert fr["Registre matricule (classe = année de naissance + 20)"]["cote_typique"] == SERIES["matricules"]
    assert fr["Passeports et police des étrangers"]["cote_typique"] == POLICE_PASSEPORTS
    assert "avertissement" in fr["Passeports et police des étrangers"]  # fonds non vérifié pour ce service
    assert fr["Listes nominatives de recensement avant et après le départ"]["cote_typique"] == SERIES["recensements"]
    assert any("consulaire" in s for s in fr)
    etr = [s for s in out if s["versant"] == "etranger"]
    assert {s["source"] for s in etr} >= {"Listes de passagers à l'arrivée", "Recensements du pays d'arrivée",
                                          "Naturalisation dans le pays d'arrivée",
                                          "Conscription et registres militaires du pays d'arrivée"}
    for s in etr:  # aucune cote étrangère inventée, avertissement explicite
        assert s["avertissement"] == AVERT_FONDS_ETRANGER
        assert s["cote_typique"].startswith("aucune cote connue du plugin")
    _sans_cote_ad(etr)
    assert all(s["pays"]["code"] == "FR" for s in out)


def test_emig_sans_lieu_sans_affirmation_de_pays():
    out = next_source_hint("EMIG")
    assert _versants(out) == {"france", "etranger"}
    assert all("pays" not in s for s in out)


def test_emig_pays_inconnu_series_conditionnelles():
    out = next_source_hint("EMIG", "1906", "Charleroi")
    ad = [s for s in out if s["versant"] == "france" and s.get("condition")]
    assert {s["source"] for s in ad} >= {"Registre matricule (classe = année de naissance + 20)",
                                         "Passeports et police des étrangers"}
    assert all(s["condition"] == SI_FRANCE and s["cote_typique"].endswith(SI_FRANCE) for s in ad)


def test_bornes_d_annee_matricule_et_recensement():
    avant = {s["source"] for s in next_source_hint("EMIG", "1830", "Fenain, Nord")}
    assert not any("matricule" in s or "recensement" in s for s in avant)


@pytest.mark.parametrize("fait", ["IMMI", "NATU", "RESI", "EVEN", "DEAT", "EMIG"])
def test_faits_americains_sans_serie_d_ad(fait):
    out = next_source_hint(fait, "1917", US)
    _sans_cote_ad(out)
    assert all(s["pays"]["code"] == "US" for s in out)


@pytest.mark.parametrize("fait", ["IMMI", "NATU", "RESI", "RESI_ETRANGER"])
def test_francais_a_l_etranger_deux_versants(fait):
    out = next_source_hint(fait, "1917", US if fait != "RESI_ETRANGER" else "")
    assert _versants(out) >= {"france", "etranger"}
    fr = [s for s in out if s.get("versant") == "france"]
    assert any("matricule" in s["source"] for s in fr)
    assert any("dernier domicile en France" in s["cote_typique"] for s in fr)
    etr = [s for s in out if s.get("versant") == "etranger" and s.get("avertissement")]
    assert etr and all(s["avertissement"] == AVERT_FONDS_ETRANGER for s in etr)
    if fait != "RESI_ETRANGER":
        assert any("(États-Unis)" in s["source"] for s in etr)
        _sans_cote_ad(out)


def test_naturalisation_en_france():
    out = next_source_hint("NATU", "1930", "Lille, Nord")
    fr = {s["source"]: s for s in out if s["versant"] == "france"}
    assert fr["Décret et dossier de naturalisation"]["cote_typique"] == DECRETS_NATURALISATION
    assert "avertissement" in fr["Décret et dossier de naturalisation"]
    assert any(s["cote_typique"] == POLICE_PASSEPORTS for s in fr.values())
    etr = [s for s in out if s["versant"] == "etranger"]
    assert etr and all("pays d'origine" in s["cote_typique"] for s in etr)


def test_prochaine_source_emig_issue():
    """Constat de l'issue : plus seulement « Actes d'état civil liés » et « Actes notariés »."""
    out = server.prochaine_source(fait="EMIG", lieu="Fenain, Nord")
    assert not {"Actes d'état civil liés", "Actes notariés"} & {s["source"] for s in out}
    assert _versants(out) == {"france", "etranger"}


# ---------------------------------------------------------------------------- fenêtre de départ (cas témoin)

@MINEUR
def test_fenetre_cas_temoin_mineur(app_contexte):
    w = server.arbre_lacunes(id="I1")["fenetre_depart"]
    assert w["determinee"] is True
    d, f = w["debut"], w["fin"]
    assert (d["fait"], d["date"], d["lieu"], d["pays"]["code"]) == ("RESI", "JUL 1906", "Denain, Nord, France", "FR")
    assert (f["fait"], f["date"], f["lieu"], f["pays"]["code"]) == ("EVEN", "17 SEP 1917", US, "US")
    t = app_contexte.tree()
    assert d["uid"] in {e.uid for e in t.person("I1").evenements}
    for b in (d, f):  # chaque borne cite le fait qui la fonde, avec son statut de sourçage
        assert b["statut"] == "hypothese" and b["citations"] and b["source_de_la_borne"] == "fait de l'arbre"
    assert "Registre de population 1906" in d["citations"][0]
    assert "juillet 1906" in w["texte"] and "17 septembre 1917" in w["texte"]
    assert app_contexte.attendus["vie"]["dernier_fait_en_france"] == d["date"]
    assert _versants(w["pistes"]) == {"france", "etranger"}
    assert any(s["cote_typique"] == SERIES["matricules"] for s in w["pistes"])
    assert all(s["pays_arrivee"]["code"] == "US" for s in w["pistes"] if s["versant"] == "etranger")


@MINEUR
def test_cas_temoin_faits_americains_sans_serie_d_ad(app_contexte):
    faits = server.arbre_statut_preuve("I1")
    us = [f for f in faits if "États-Unis" in f.get("lieu", "")]
    assert {f["fait"] for f in us} == {"EVEN", "DEAT"}
    for f in us:
        _sans_cote_ad(f.get("prochaine_source", []))


@MINEUR
def test_cas_temoin_fiche_et_plan(app_contexte):
    fiche = server.arbre_fiche("I1")
    assert "## Fenêtre de départ" in fiche
    assert "juillet 1906" in fiche and "17 septembre 1917" in fiche
    assert "Registres de population de Denain" in fiche.split("## Fenêtre de départ")[1]
    assert "pays d'arrivée : États-Unis" in fiche
    plan = server.arbre_lacunes(id="I1")["plan"]
    emig = [p for p in plan if p["fait"] == "EMIG"]
    assert len(emig) == 1 and "émigration non enregistrée" in emig[0]["probleme"]
    assert _versants(emig[0]["sources"]) == {"france", "etranger"}


@MINEUR
def test_typage_propose_jamais_applique(app_contexte):
    avant = app_contexte.store.text()
    w = server.arbre_lacunes(id="I1")["fenetre_depart"]
    (t,) = w["typage_propose"]
    assert t["uid"] == w["fin"]["uid"]
    assert set(t["operations_par_type"]) == {"IMMI", "NATU", "RESI", "CENS", "MILI"}
    assert app_contexte.store.text() == avant  # rien n'est écrit
    ops = t["operations_par_type"]["IMMI"]
    p = server.arbre_proposer(ops, "Typage de l'événement de 1917", "La pièce n° 12 atteste l'arrivée.")
    assert "jeton" in p, p
    assert app_contexte.store.text() == avant  # toujours rien avant arbre_appliquer
    server.arbre_appliquer(p["jeton"])
    ev = [e for e in app_contexte.tree().person("I1").evenements if e.type == "IMMI"]
    assert len(ev) == 1 and ev[0].date == "17 SEP 1917" and ev[0].citations[0].source == "S4"
    assert not [e for e in app_contexte.tree().person("I1").evenements if e.type == "EVEN"]


# ---------------------------------------------------------------------------- fenêtres indéterminées

def _arbre(lignes: str):
    ged = "0 HEAD\n1 GEDC\n2 VERS 7.0\n0 @I1@ INDI\n1 NAME Jean /ESSAI/\n" + lignes + "0 TRLR\n"
    return read_gedcom(ged)[0]


def test_aucun_fait_a_l_etranger_rien_a_dire():
    t = _arbre("1 BIRT\n2 DATE 1881\n2 PLAC Denain, Nord, France\n")
    assert fenetre_depart(t, "I1") is None
    assert "Fenêtre de départ" not in fiche_markdown(t, "I1")


def test_fenetre_indeterminee_sans_fait_en_france_avant():
    t = _arbre("1 BIRT\n2 DATE 1881\n2 PLAC Krebs, Oklahoma, États-Unis\n"
               "1 RESI\n2 DATE 1906\n2 PLAC Denain, Nord, France\n")
    w = fenetre_depart(t, "I1")
    assert w["determinee"] is False and w["debut"] is None and w["fin"]["date"] == "1881"
    assert "indéterminé" in w["texte"]
    assert w["faits_en_france_apres"][0]["date"] == "1906" and "retour" in w["remarque"]
    assert "Fenêtre de départ indéterminée" in fiche_markdown(t, "I1")


def test_fenetre_indeterminee_fait_etranger_non_date_et_pays_inconnu():
    t = _arbre("1 BIRT\n2 DATE 1881\n2 PLAC Denain, Nord, France\n"
               "1 RESI\n2 PLAC Krebs, Oklahoma, États-Unis\n"
               "1 RESI\n2 DATE 1910\n2 PLAC Charleroi\n")
    w = fenetre_depart(t, "I1")
    assert w["determinee"] is False and w["debut"] is None and w["fin"] is None
    assert w["motif"].startswith("aucun fait daté situé hors de France")
    assert {x["raison"] for x in w["faits_ecartes"]} == {"fait non daté", "pays du lieu inconnu"}


def test_fait_non_source_dit_comme_tel():
    t = _arbre("1 RESI\n2 DATE 1905\n2 PLAC Denain, Nord, France\n"
               "1 RESI\n2 DATE 1910\n2 PLAC Krebs, Oklahoma, États-Unis\n")
    w = fenetre_depart(t, "I1")
    assert w["determinee"] and w["debut"]["citations"] == []
    assert w["debut"]["source_de_la_borne"] == "fait de l'arbre non sourcé"
    assert w["debut"]["statut"] == "non_source" and "aucune citation" in w["texte"]
    assert "typage_propose" not in w  # aucun événement générique


def test_dernier_fait_en_france_avant_le_premier_a_l_etranger():
    t = _arbre("1 BIRT\n2 DATE 1881\n2 PLAC Denain, Nord, France\n"
               "1 RESI\n2 DATE 1912\n2 PLAC Krebs, Oklahoma, États-Unis\n"
               "1 RESI\n2 DATE 1908\n2 PLAC Lille, Nord, France\n"
               "1 RESI\n2 DATE 1920\n2 PLAC Krebs, Oklahoma, États-Unis\n")
    w = fenetre_depart(t, "I1")
    assert (w["debut"]["date"], w["fin"]["date"]) == ("1908", "1912")


# ---------------------------------------------------------------------------- sites relevés

def test_sites_emigration_releves_et_dates():
    codes = {s["code"]: s for s in sites_tiers.filtrer(theme="emigration")}
    assert {"NARA-IMMIGRATION", "NARA-NATURALISATION", "NARA-WW1-DRAFT", "NARA-RECENSEMENTS",
            "ELLIS-ISLAND"} <= set(codes)
    for s in codes.values():
        assert s["origine"] and s["site_repond_le"] and s["verifie_le"] == ""
    assert not sites_tiers.validate()
    cat = server.sources_catalogue(theme="emigration")
    assert cat["totaux"]["sites_tiers"] >= 7
    sur_1917 = {s["code"] for s in sites_tiers.filtrer(theme="emigration", annee_min=1906, annee_max=1917)}
    assert "NARA-WW1-DRAFT" in sur_1917
