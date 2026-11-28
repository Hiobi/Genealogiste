"""Plans du cadastre des services Mnesys autres qu'AD59 (#392) : formulaires dédiés relevés le 28 novembre 2026,
fixtures réelles réduites (formulaire, page de résultats), aucun réseau.

Comme pour AD59 (#391), aucune date n'est envoyée et aucun plan n'est écarté sur sa date : la date situe chaque
lot (``position_periode``). Les matrices et états de section que proposent certains formulaires ne sont pas
interrogés (``autres_documents``). Réduction contrôlée au relevé : même requête, mêmes résultats."""

from urllib.parse import parse_qs, urlsplit

import pytest
import respx

from genealogiste_mcp import archives, server
from genealogiste_mcp.sources import registres

RELEVE = "2026-11-28"
# code : (commune saisie, valeur du service, champ de lieu, typologie envoyée, résultats lus, total)
CAS = {
    "AD14": ("Bayeux", "Bayeux (Calvados, France)", "controlledAccessGeographicName", ["plan cadastral"], 20, 36),
    "AD19": ("Tulle", "Tulle (Corrèze, France)", "0-controlledAccessGeographicName", ["plan cadastral"], 20, 28),
    "AD25": ("Pontarlier", "Pontarlier", "0-controlledAccessGeographicName", None, 1, 1),
    "AD39": ("Dole", "Dole, commune", "0-controlledAccessGeographicName",
             ["plan du livre foncier", "plan par masses de culture", "plan parcellaire napoléonien",
              "tableau d'assemblage"], 16, 16),
    "AD55": ("Verdun", "VERDUN", "0-controlledAccessGeographicName", None, 20, 31),
    "AD58": ("Clamecy", "CLAMECY", "0-controlledAccessGeographicName", None, 20, 20),
    "AD69": ("Tarare", "TARARE", "0-controlledAccessCorporateName", ["Plan cadastral", "Plan de remembrement"], 20,
             65),
    "AD90": ("Delle", "Delle (Territoire de Belfort, France)", "0-controlledAccessGeographicName",
             ["Plan de finage", "Plan cadastral"], 2, 2),
    "AD91": ("Étampes", "ETAMPES Commune", "1-controlledAccessGeographicName", None, 20, 45),
}


def _mock(fixtures, code: str, page: str = "cadastre-positive"):
    svc = archives.by_code(code)
    host, uuid = svc["site"].rstrip("/"), svc["recherche_registres"]["formulaires"]["cadastre"]
    respx.get(f"{host}/search/form/{uuid}").respond(
        200, text=(fixtures / f"{code.lower()}-cadastre-formulaire.html").read_text())
    return respx.get(f"{host}/search/results").respond(200, text=(fixtures / f"{code.lower()}-{page}.html").read_text())


def _params(route) -> dict:
    return parse_qs(urlsplit(str(route.calls[-1].request.url)).query)


def test_referentiel_declare_le_cadastre_releve():
    declares = {c for c in registres.services_registres()[1:]
                if "cadastre" in archives.by_code(c)["recherche_registres"]["formulaires"]}
    assert declares == set(CAS)
    for code in CAS:
        assert archives.by_code(code)["recherche_registres"]["releves"]["cadastre"] == RELEVE
    # AD69 : la commune est en collectivité, après un titre (type de cadastre) que le lecteur prendrait sinon
    assert archives.by_code("AD69")["recherche_registres"]["champs_lieu"] == {
        "cadastre": "0-controlledAccessCorporateName"}
    # AD27 : plans sans média image (relevé du 28 novembre 2026), formulaire non déclaré
    assert "cadastre" not in archives.by_code("AD27")["recherche_registres"]["formulaires"]
    assert archives.validate() == []


def test_referentiel_refuse_un_champ_de_lieu_sans_formulaire(monkeypatch):
    reels = archives.services()
    svc = archives.by_code("AD14")
    faux = {**svc, "recherche_registres": {**svc["recherche_registres"], "champs_lieu": {"hypotheques": "0-title"}}}
    monkeypatch.setattr(archives, "services", lambda: tuple(faux if s["code"] == "AD14" else s for s in reels))
    assert any("AD14 : recherche_registres.champs_lieu" in e for e in archives.validate())


@respx.mock
@pytest.mark.parametrize("code", sorted(CAS))
def test_plans_d_une_commune_sans_date_envoyee(app, fixtures, code):
    commune, valeur, lieu, typologie, nb, total = CAS[code]
    res = _mock(fixtures, code)
    r = registres.rechercher(app.sctx, code, commune, 1850, "CAD")
    assert "erreur" not in r, r
    assert len(r["resultats"]) == nb and r["total"] == total and "recherche_negative" not in r
    q = _params(res)
    assert q[lieu + "[]"] == [valeur] and r["commune_service"] == valeur
    assert not any("date" in k or k.startswith("period") for k in q)  # aucune date envoyée (#391)
    typo = [v for k, v in q.items() if "PhysicalCharacteristic" in k]
    assert typo == ([typologie] if typologie else [])
    cad = r["cadastre"]
    assert cad["formulaire"] == archives.by_code(code)["recherche_registres"]["formulaires"]["cadastre"]
    assert cad["releve_le"] == RELEVE and cad["typologie_envoyee"] == typologie
    assert "Aucun plan n'est écarté sur sa date" in cad["lecture"]
    # lots triés par date (sans date d'abord), chacun situé ; aucun écarté
    cles = [x["bornes"] or [0, 0] for x in r["resultats"]]
    assert cles == sorted(cles) and "registres_hors_periode" not in r
    for x in r["resultats"]:
        attendu = None if x["bornes"] is None else registres._position(x["bornes"], [1850, 1850])
        assert x["position_periode"] == attendu
    assert app.journal.entries()[-1]["statut"] == "positif"


@respx.mock
def test_matrices_et_etats_de_section_signales_non_interroges(app, fixtures):
    _mock(fixtures, "AD69")
    cad = registres.rechercher(app.sctx, "AD69", "Tarare", 1850, "CAD")["cadastre"]
    assert cad["autres_documents"] == ["Matrice des propriétés bâties", "Matrice des propriétés foncières",
                                       "Matrice des propriétés non bâties",
                                       "Procès-verbal de délimitation communale", "État de section"]
    assert "non interrogés" in cad["lecture"]


@respx.mock
def test_plan_anterieur_et_posterieur_tous_rendus(app, fixtures):
    """AD14, Bayeux : plans de 1812 et de 1970 ; pour 1850, les deux sont rendus, situés avant et après."""
    _mock(fixtures, "AD14")
    r = registres.rechercher(app.sctx, "AD14", "Bayeux", 1850, "CAD")
    positions = {x["position_periode"] for x in r["resultats"]}
    assert positions == {"anterieur", "posterieur"}
    assert r["resultats"][0]["bornes"] == [1812, 1812] and r["resultats"][-1]["bornes"] == [1970, 1970]


@respx.mock
def test_negatif_non_concluant(app, fixtures):
    """Page négative réelle d'AD58 (même service, relevé des recensements) : aucun plan renvoyé."""
    _mock(fixtures, "AD58", "recensements-negative")
    r = registres.rechercher(app.sctx, "AD58", "Clamecy", 1850, "CAD")
    assert r["resultats"] == [] and "recherche_negative" in r
    assert "ne prouve pas" in r["recherche_negative"]


def test_hypotheques_et_fiches_deces_restent_propres_a_ad59(app, respx_mock):
    route = respx_mock.route().respond(200, text="aucune requête attendue")
    for type_acte in ("HYP", "FD"):
        assert "disponible pour AD59 seulement" in server.archives_registres("AD69", "Tarare", 1850, type_acte)[
            "erreur"]
    r = server.archives_registres("AD27", "Bernay", 1850, "CAD")
    assert "Aucun formulaire « cadastre »" in r["erreur"] and not route.called
