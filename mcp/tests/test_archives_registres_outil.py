"""Garde locale, transport et erreurs publiques de la recherche de registres."""

import httpx
import respx

from genealogiste_mcp import server


def test_personne_locale_ne_part_pas_vers_les_archives(app_famille, fixtures):
    html = (fixtures / "ad59-recherche-positive.html").read_text()
    with respx.mock as routes:
        route = routes.get("https://archivesdepartementales.lenord.fr/search/results").respond(
            200, text=html, headers={"Content-Type": "text/html"})
        res = server.archives_registres("AD59", "Saint-Vaast-en-Cambrésis", 1860, "N", personne="I1")
    assert res["resultats"] and route.call_count == 1
    assert "personne" not in route.calls[0].request.url.params
    assert "I1" not in str(route.calls[0].request.url)
    entree = next(e for e in app_famille.journal.entries() if e["id"] == res["journal"])
    assert entree["personne"] == "I1"


def test_nom_de_vivant_dans_le_champ_commune_refuse(app_famille):
    with respx.mock(assert_all_called=False) as routes:
        route = routes.route().respond(200, text="aucune requête attendue")
        res = server.archives_registres("AD59", "Lucas MARTIN", 2020)
    assert "refus" in res
    assert not route.called


def test_protection_recherche_conserve_tache_et_journal(app):
    with respx.mock as routes:
        route = routes.get("https://archivesdepartementales.lenord.fr/search/results").mock(
            return_value=httpx.Response(503, headers={"cf-mitigated": "challenge"}, text="défi"))
        res = server.archives_registres("AD59", "Somain", 1860)
    assert route.call_count == 1
    assert res["statut"] == "bloque_antirobot"
    assert res["service"] == "AD59"
    assert res["tache_manuelle"]["url"].startswith("https://archivesdepartementales.lenord.fr/search/results?")
    assert any(e["id"] == res["journal"] for e in app.journal.entries(statut="bloque_antirobot"))
