"""Référentiel des sites tiers (#181) : schéma, filtres, liens et outil sources_catalogue, sans réseau."""

import copy

import pytest

from genealogiste_mcp import outils, server, sites_tiers


def test_referentiel_valide_et_jamais_verifie_sans_humain():
    assert sites_tiers.validate() == []
    tous = sites_tiers.sites()
    assert len(tous) > 100
    # verifie_le atteste un contrôle humain : le peuplement automatique le laisse vide
    assert all(s["verifie_le"] == "" for s in tous)


def test_au_moins_un_cercle_pour_une_majorite_de_departements():
    deps = {z for s in sites_tiers.sites() if s["type"] == "cercle_departemental" for z in s["zone"]}
    assert {"59", "62", "29", "2A", "974"} <= deps
    assert len(deps) >= 70


@pytest.mark.parametrize("champ,valeur,attendu", [
    ("acces", "gratuit", "acces"),
    ("nature", "original", "nature"),
    ("type", "forum", "type"),
    ("url", "ftp://x.example/", "url"),
    ("zone", ["99"], "zone"),
    ("periode", {"de": 1900, "a": 1800}, "periode"),
    ("verifie_le", "hier", "verifie_le"),
    ("recherche", "https://x.example/?q=fixe", "recherche"),
])
def test_validate_refuse_valeurs_hors_liste(monkeypatch, champ, valeur, attendu):
    base = copy.deepcopy(next(s for s in sites_tiers.sites() if s["code"] == "GENEABANK"))
    base[champ] = valeur
    monkeypatch.setattr(sites_tiers, "sites", lambda: (base,))
    assert any(attendu in e for e in sites_tiers.validate())


def test_pas_de_modele_de_recherche_sur_site_protege(monkeypatch):
    s = copy.deepcopy(next(s for s in sites_tiers.sites() if s["code"] == "GENEABANK"))
    s["protection"] = "captcha"
    monkeypatch.setattr(sites_tiers, "sites", lambda: (s,))
    assert any("protégé" in e for e in sites_tiers.validate())
    # et lien() n'utilise jamais le modèle d'un site protégé
    assert sites_tiers.lien(s, "DUPONT", "Jean")["url"] == s["url"]


def test_lien_encode_le_nom_et_marque_le_releve_derive():
    s = next(s for s in sites_tiers.sites() if s["code"] == "GENEABANK")
    lien = sites_tiers.lien(s, "D'ARTOIS", "Jean Marie")
    assert "nom=D%27ARTOIS" in lien["url"] and "prenom=Jean%20Marie" in lien["url"]
    assert "remonter à l'acte" in lien["avertissement"]


def test_filtre_periode_et_theme():
    ww2 = {s["code"] for s in sites_tiers.filtrer(theme="ww2")}
    assert {"FMD-LIVRE-MEMORIAL", "FRANCAIS-LIBRES", "MAITRON"} <= ww2
    # Refuge huguenot (1685-1700) hors d'une vie 1850-1920
    codes = {s["code"] for s in sites_tiers.filtrer(annee_min=1850, annee_max=1920)}
    assert "REFUGE-HUGUENOT" not in codes and "GENEABANK" in codes


def test_liens_recherche_ajoute_les_sites_tiers_du_departement():
    r = server.liens_recherche("LEGRAND", "Gustave", "1926", "Somain (59)")
    codes = [x["code"] for x in r["sites_tiers"]]
    assert "GENNPDC" in codes and "GENEABANK" in codes
    assert "CGF-RECIF" not in codes  # Finistère
    assert "remonter à l'acte" in r["sites_tiers_avertissement"]
    # sans lieu : aucun site tiers proposé, liens historiques inchangés
    assert "sites_tiers" not in server.liens_recherche("LEGRAND", "Gustave")


def test_cotes_a_consulter_propose_le_cercle_du_departement():
    r = server.cotes_a_consulter("BIRT", "1860", "Brest (29)")
    assert "CGF-RECIF" in [x["code"] for x in r["sites_tiers"]]


def test_sources_catalogue_complet_et_filtres():
    tout = server.sources_catalogue()
    assert tout["totaux"]["archives"] >= 110 and tout["totaux"]["sites_tiers"] > 100 and tout["api"]
    nord = server.sources_catalogue(departement="59")
    assert any(a["code"] == "AD59" for a in nord["archives"])
    assert not any(a.get("departement") == "62" for a in nord["archives"])
    assert all("59" in s["zone"] or "FR" in s["zone"] for s in nord["sites_tiers"])
    lieux = server.sources_catalogue(type="lieux")
    assert lieux["archives"] == [] and {s["type"] for s in lieux["sites_tiers"]} == {"lieux"}
    assert server.sources_catalogue(departement="2a")["filtres"]["departement"] == "2A"
    assert server.sources_catalogue(departement="5")["filtres"]["departement"] == "05"
    for erreur in ({"departement": "99"}, {"type": "forum"}, {"acces": "gratuit"}):
        assert "erreur" in server.sources_catalogue(**erreur)


def test_sources_catalogue_est_une_lecture():
    assert outils.OUTILS["sources_catalogue"] == (outils.LECTURE, outils.LECTURE)
    assert "sources_catalogue" not in outils.GARDE_VIVANTS


def test_api_listees_existent():
    for api in sites_tiers.API:
        for nom in api["outils"]:
            assert nom in outils.OUTILS, nom
