"""#253 : défi « redirection JS » des visionneuses Arkotheque (AD15) et page 403 de WikiTree contre les robots
d'IA reconnus comme blocages anti-robot, avec tâche manuelle et sans réessai. Réponses synthétiques, aucun réseau."""

from __future__ import annotations

import httpx
import pytest
import respx

from genealogiste_mcp import server
from genealogiste_mcp.config import user_agent_par_defaut
from genealogiste_mcp.http import SourceError, _protection

# Squelette de la page de redirection Arkotheque relevée le 2026-11-19 (jeton remplacé).
ARKOTHEQUE = ("<html lang=\"en\"><head></head><body><script>window.location.href='/redirect_JETONFICTIF===="
              "/ark:16075/registrefictif';</script><noscript>This website requires JS enabled and cookies"
              "</noscript></body></html>")
# Page 403 de WikiTree relevée le 2026-11-19, réduite à sa structure.
WIKITREE_403 = ('<html lang="en"><head><meta charset="utf-8"><title>Error 403 - Access Blocked</title></head>'
                '<body><h1>Error 403</h1><p>WikiTree is having serious problems with AI-scraping bots abusing '
                'our free and open website. Your IP address may be blocked.</p><p>Please let us know at '
                '<a href="mailto:info@wikitree.com">info@wikitree.com</a>.</p></body></html>')
HTML = {"Content-Type": "text/html"}


def _reponse(statut: int, corps: str) -> httpx.Response:
    return httpx.Response(statut, text=corps, headers=HTML)


# ---------------------------------------------------------------- détection

def test_redirection_js_arkotheque_reconnue():
    assert _protection(_reponse(200, ARKOTHEQUE)) == "redirection JS"


@pytest.mark.parametrize("corps", [
    "<html><script>window.location.href='/accueil';</script></html>",  # redirection ordinaire
    "<html><script>window.location.href='/redirect_X/ark';</script></html>",  # sans le message noscript
    "<html><noscript>This website requires JS enabled and cookies</noscript></html>",  # sans redirection
])
def test_redirection_ordinaire_n_est_pas_un_defi(corps):
    assert _protection(_reponse(200, corps)) is None


def test_page_403_wikitree_robots_ia_reconnue():
    assert _protection(_reponse(403, WIKITREE_403)) == "blocage robots IA"


def test_page_wikitree_hors_403_n_est_pas_un_defi():
    assert _protection(_reponse(200, WIKITREE_403)) is None


def test_403_wikitree_ordinaire_reste_un_refus():
    assert _protection(_reponse(403, "<html><title>Forbidden</title></html>")) is None


# ---------------------------------------------------------------- parcours outils

def test_naviguer_ad15_redirection_js_renvoie_consigne(app):
    # Le référentiel note www.archives.cantal.fr ; la visionneuse sert l'ARK sans « www. ».
    source = "https://archives.cantal.fr/ark:16075/registrefictif"
    with respx.mock as routes:
        route = routes.route(host="archives.cantal.fr").mock(return_value=_reponse(200, ARKOTHEQUE))
        res = server.archives_naviguer(source)
        second = server.archive_image(source, page=1)
    assert route.call_count == 1  # coupe-circuit : aucun nouvel essai sur le défi
    for r in (res, second):
        assert r["statut"] == "bloque_antirobot"
        assert r["protection"] == "redirection JS"
        assert r["service"] == "AD15"
        assert r["tache_manuelle"]["statut"] == "a_faire"
        assert "IIIF de ce service inconnu" not in r["erreur"]
    trace = next(e for e in app.journal.entries() if e["id"] == res["journal"])
    assert trace["statut"] == "bloque_antirobot"


def test_wikitree_robots_ia_tache_manuelle_sans_contournement(app):
    with respx.mock as routes:
        route = routes.post("https://api.wikitree.com/api.php").mock(return_value=_reponse(403, WIKITREE_403))
        res = server.wikitree_recherche("Rolland", "Louis")
        second = server.wikitree_recherche("Rolland", "Pierre")
    assert route.call_count == 1
    assert res["statut"] == "bloque_antirobot" and res["protection"] == "blocage robots IA"
    assert "identifiants requis" not in res["erreur"]
    assert second["statut"] == "bloque_antirobot" and second.get("coupe_circuit")
    # Le User-Agent reste transparent : le filtre n'est pas contourné en masquant l'outil.
    assert "Claude Code" in route.calls[0].request.headers["User-Agent"]


def test_user_agent_declare_le_plugin():
    assert "plugin Claude Code" in user_agent_par_defaut()


def test_erreur_403_brute_inchangee(app):
    with respx.mock as routes:
        routes.post("https://api.wikitree.com/api.php").mock(return_value=_reponse(403, "<html>Forbidden</html>"))
        with pytest.raises(SourceError) as exc:
            app.http.post("https://api.wikitree.com/api.php", data={"action": "x"})
    assert not exc.value.bloque_antirobot and exc.value.status == 403
