"""Recensements de population des services Mnesys autres qu'AD59 (#392) : formulaires dédiés relevés le
28 novembre 2026, fixtures réelles réduites (formulaire, page de résultats), aucun réseau.

Réduction : formulaire limité à ses champs (vocabulaire des communes ramené à quelques valeurs dont celle de la
commune du test) ; page de résultats sans en-tête, scripts ni pied de page. Les deux réductions ont été contrôlées
au relevé : même requête construite et mêmes résultats lus que sur la page complète."""

from urllib.parse import parse_qs, urlsplit

import pytest
import respx

from genealogiste_mcp import archives
from genealogiste_mcp.sources import registres

RELEVE = "2026-11-28"
# code : (commune saisie, valeur du vocabulaire du service, champs de date envoyés pour un millésime,
#         résultats de la page pour 1906, total, cote du premier résultat, bornes du premier résultat)
POSITIFS = {
    "AD14": ("Bayeux", "Bayeux (Calvados, France)", {"period_begin", "period_end"}, 1, 1, None, [1906, 1906]),
    "AD19": ("Tulle", "Tulle (Corrèze, France)", {"4-date_begin", "4-date_end"}, 2, 2, "EDEP/272/222", [1891, 1926]),
    "AD25": ("Pontarlier", "Pontarlier", {"1-date"}, 1, 1, None, [1906, 1906]),
    "AD27": ("Bernay", "Bernay (Eure, France)", {"1-date_begin", "1-date_end"}, 5, 5, "6M158", [1906, 1906]),
    "AD37": ("Chinon", "Chinon (Indre-et-Loire, France)", {"3-date_begin", "3-date_end"}, 1, 1, "6NUM5/072/015",
             [1906, 1906]),
    "AD39": ("Dole", "Dole, commune", {"3-date_begin", "3-date_end"}, 1, 1, "6M515", [1906, 1906]),
    "AD51": ("Épernay", "Épernay (Marne, France)", {"2-date_begin", "2-date_end"}, 1, 1, "122 M 316", [1906, 1906]),
    "AD58": ("Clamecy", "Clamecy (Nièvre, France)", {"3-date_begin", "3-date_end"}, 1, 1, "6 M 079/2", [1906, 1906]),
    "AD69": ("Tarare", "TARARE", {"3-date_begin", "3-date_end"}, 20, 81, "6 M 513", [1906, 1906]),
    "AD80": ("Péronne", "Péronne (Somme, France)", {"1-date_begin", "1-date_end"}, 3, 3, "6M715", [1906, 1906]),
    "AD90": ("Delle", "Delle (Territoire de Belfort, France)", {"1-date[]"}, 1, 1, "6 M 156/15", [1906, 1906]),
    "AD91": ("Étampes", "ETAMPES Commune", {"2-date"}, 1, 1, "6M/126", [1906, 1906]),
}
NEGATIFS = ["AD14", "AD19", "AD27", "AD37", "AD39", "AD51", "AD58", "AD69", "AD80"]  # 1700-1701, période envoyée
SERVICES = sorted([*POSITIFS, "AD55"])


def _mock(fixtures, code: str, page: str):
    host = archives.by_code(code)["site"].rstrip("/")
    uuid = archives.by_code(code)["recherche_registres"]["formulaires"]["recensements"]
    form = respx.get(f"{host}/search/form/{uuid}").respond(
        200, text=(fixtures / f"{code.lower()}-recensements-formulaire.html").read_text())
    res = respx.get(f"{host}/search/results").respond(
        200, text=(fixtures / f"{code.lower()}-recensements-{page}.html").read_text())
    return form, res


def _params(route) -> dict:
    return parse_qs(urlsplit(str(route.calls[-1].request.url)).query)


def test_referentiel_declare_les_recensements_releves():
    declares = {c for c in registres.services_registres()[1:]
                if "recensements" in archives.by_code(c)["recherche_registres"]["formulaires"]}
    assert declares == set(SERVICES)
    for code in SERVICES:
        rr = archives.by_code(code)["recherche_registres"]
        assert rr["releves"]["recensements"] == RELEVE
        assert rr["releve_le"] == "2026-11-18"  # date du formulaire d'état civil inchangée
    # AD972 : aucune page de recensements sur le portail (relevé du 28 novembre 2026) ; AD73 : pas de recherche
    # de registres (autre portail, hors de cette étape)
    assert "recensements" not in archives.by_code("AD972")["recherche_registres"]["formulaires"]
    assert "AD73" not in registres.services_registres()
    assert archives.validate() == []


def test_referentiel_refuse_une_date_de_releve_sans_formulaire(monkeypatch):
    reels = archives.services()
    svc = archives.by_code("AD14")
    faux = {**svc, "recherche_registres": {**svc["recherche_registres"], "releves": {"hypotheques": RELEVE}}}
    monkeypatch.setattr(archives, "services", lambda: tuple(faux if s["code"] == "AD14" else s for s in reels))
    assert any("AD14 : recherche_registres.releves" in e for e in archives.validate())


@respx.mock
@pytest.mark.parametrize("code", sorted(POSITIFS))
def test_recensement_d_un_millesime(app, fixtures, code):
    commune, valeur, champs_date, nb, total, cote, bornes = POSITIFS[code]
    form, res = _mock(fixtures, code, "positive")
    r = registres.rechercher(app.sctx, code, commune, 1906, "REC")
    assert "erreur" not in r, r
    assert len(r["resultats"]) == nb and r["total"] == total and "recherche_negative" not in r
    premier = r["resultats"][0]
    assert premier["cote"] == cote and premier["bornes"] == bornes
    assert premier["ark"].startswith(f"ark:/{archives.by_code(code)['ark_naan']}/")
    q = _params(res)
    uuid = archives.by_code(code)["recherche_registres"]["formulaires"]["recensements"]
    assert q["formUuid"] == [uuid] and r["commune_service"] == valeur
    assert [v for k, v in q.items() if k.endswith("controlledAccessGeographicName[]")] == [[valeur]]
    assert {k for k in q if "date" in k or k.startswith("period")} == champs_date
    assert all(q[k] == ["1906"] for k in champs_date)
    rec = r["recensements"]
    assert rec["formulaire"] == uuid and rec["releve_le"] == RELEVE and rec["periode_envoyee"] is True
    assert "aucune recherche par nom" in rec["lecture"]
    assert app.journal.entries()[-1]["statut"] == "positif"


@respx.mock
@pytest.mark.parametrize("code", NEGATIFS)
def test_negatif_non_concluant(app, fixtures, code):
    _, res = _mock(fixtures, code, "negative")
    r = registres.rechercher(app.sctx, code, POSITIFS[code][0], 1700, "REC", annee_fin=1701)
    assert "erreur" not in r and r["resultats"] == [] and r["total"] == 0
    assert "ne prouve ni que le recensement n'existe pas" in r["recherche_negative"]
    assert "annee_fin" in r["recherche_negative"]
    assert any(v == ["1700"] for v in _params(res).values())  # période envoyée au service
    assert app.journal.entries()[-1]["statut"] == "negatif"


@respx.mock
def test_formulaire_sans_date_filtre_local_et_millesimes_ecartes(app, fixtures):
    """AD55 : la commune est le seul champ ; les volumes en ligne sont filtrés localement sur leur date."""
    _, res = _mock(fixtures, "AD55", "positive")
    r = registres.rechercher(app.sctx, "AD55", "Verdun", 1906, "REC")
    assert "erreur" not in r and r["resultats"] == [] and r["total"] == 5 and r["registres_hors_periode"] == 5
    assert set(_params(res)) == {"formUuid", "sort", "mode", "facet_media", "0-controlledAccessGeographicName[]",
                                 "page"}
    assert r["recensements"]["periode_envoyee"] is False
    assert r["recensements"]["millesimes_hors_periode"] == [1836, 1926, 1931, 1936, 1946]
    assert "1836, 1926, 1931, 1936, 1946" in r["recherche_negative"]
    r = registres.rechercher(app.sctx, "AD55", "Verdun", 1920, "REC", annee_fin=1940)
    assert [x["bornes"][0] for x in r["resultats"]] == [1936, 1926, 1931] and r["registres_hors_periode"] == 2


@respx.mock
@pytest.mark.parametrize("code,commune,nb", [("AD25", "Pontarlier", 7), ("AD90", "Delle", 20), ("AD91", "Étampes", 20)])
def test_intervalle_sur_un_formulaire_a_millesime_seul(app, fixtures, code, commune, nb):
    """AD25, AD90, AD91 : millésime seul, sans champ de période ; un intervalle n'envoie que la commune et se
    filtre localement."""
    _, res = _mock(fixtures, code, "intervalle")
    r = registres.rechercher(app.sctx, code, commune, 1800, "REC", annee_fin=1950)
    assert "erreur" not in r and len(r["resultats"]) == nb
    assert not any("date" in k for k in _params(res)) and r["recensements"]["periode_envoyee"] is False
    assert all(x["couvre_periode"] is True for x in r["resultats"])


@respx.mock
def test_millesime_absent_de_la_liste_du_formulaire(app, fixtures):
    """AD90 : millésime en liste fermée, sans champ de période ; 1916 n'y figure pas (pas de recensement pendant
    la guerre) : aucune requête de résultats, aucun négatif déduit."""
    _, res = _mock(fixtures, "AD90", "positive")
    r = registres.rechercher(app.sctx, "AD90", "Delle", 1916, "REC")
    assert "Millésime 1916 absent de la liste" in r["erreur"] and "1911, 1921" in r["erreur"]
    assert res.call_count == 0 and "recherche_negative" not in r


@respx.mock
def test_liste_de_millesimes_et_periode_la_periode_prime(app, fixtures):
    """AD19 : liste de millésimes et champ de période ; la période est envoyée, même pour un millésime absent
    de la liste (un volume peut couvrir plusieurs recensements : 1891-1926)."""
    _, res = _mock(fixtures, "AD19", "positive")
    r = registres.rechercher(app.sctx, "AD19", "Tulle", 1896, "REC")
    assert "erreur" not in r and _params(res)["4-date_begin"] == ["1896"]
    assert "1896" not in r["recensements"]["millesimes_formulaire"]  # absent de la liste, envoyé en période


def test_service_mnesys_sans_formulaire_de_recensements(app):
    r = registres.rechercher(app.sctx, "AD972", "Fort-de-France", 1906, "REC")
    assert "Aucun formulaire « recensements »" in r["erreur"]
