"""#150 : protections anti-robot depuis un VPS — page de blocage Cloudflare 403, exclusion durable d'un hôte
dont le défi persiste, suite sans navigateur structurée, tâche manuelle dans l'état d'enquête, défi observé
exposé par archives_service. Réponses enregistrées synthétiques, aucun réseau."""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from genealogiste_mcp import server
from genealogiste_mcp.config import load_config
from genealogiste_mcp.http import HttpClient, SourceError, _protection
from genealogiste_mcp.sources.base import error_envelope

HOTE = "archivesdepartementales.lenord.fr"
API = f"https://{HOTE}/visualizer/api"
SOURCE = "ark:/33518/registre"
DEFI = {"headers": {"cf-mitigated": "challenge"}, "text": "Défi"}

# Page d'erreur 1020 de Cloudflare (règle de pare-feu), réduite à sa structure.
CF_1020 = ('<!DOCTYPE html><html><head><title>Access denied | archives.example used Cloudflare to restrict '
           'access</title></head><body><div id="cf-wrapper"><div id="cf-error-details" class="p-0">'
           '<h1>Access denied</h1><span class="cf-error-code">1020</span><p>Ray ID: 0000000000000000</p>'
           '<span>Performance &amp; security by Cloudflare</span></div></div></body></html>')


def _reponse(statut: int, corps: str) -> httpx.Response:
    return httpx.Response(statut, text=corps, headers={"Content-Type": "text/html; charset=UTF-8"})


# ---------------------------------------------------------------- détection

def test_page_blocage_cloudflare_403_reconnue():
    assert _protection(_reponse(403, CF_1020)) == "Cloudflare"


@pytest.mark.parametrize("statut", [200, 500, 521, 522])
def test_page_erreur_cloudflare_hors_403_n_est_pas_un_defi(statut):
    # Une erreur d'origine (52x) servie par Cloudflare porte la même structure : panne, pas un défi.
    assert _protection(_reponse(statut, CF_1020)) is None


def test_403_ordinaire_sans_structure_cloudflare():
    assert _protection(_reponse(403, "<html><h1>Access denied</h1>Ray ID mentionné</html>")) is None


# ---------------------------------------------------------------- exclusion durable

def _client(app, **kw) -> HttpClient:
    return HttpClient(app.cache, "tests", sleeper=lambda s: None, **kw)


def _defi(client, url=API) -> SourceError:
    with pytest.raises(SourceError) as exc:
        client.get(url, use_cache=False)
    return exc.value


@respx.mock
def test_premier_defi_pause_seulement(app):
    respx.get(API).mock(return_value=httpx.Response(503, **DEFI))
    client = _client(app, exclusion_ttl=7 * 86400)
    premier = _defi(client)
    assert premier.bloque_antirobot and not premier.exclusion
    obs = app.cache.defi_antirobot(HOTE)
    assert obs["detections"] == 1 and obs["protection"] == "Cloudflare" and obs["exclu_jusqu_a"] is None


@respx.mock
def test_defi_persistant_exclusion_durable_levee_explicitement(app):
    route = respx.get(API).mock(return_value=httpx.Response(503, **DEFI))
    client = _client(app, exclusion_ttl=7 * 86400)
    _defi(client)
    app.cache.purge("coupe_circuit")  # nouvel essai explicite de l'utilisateur
    recidive = _defi(client, API + "?vue=2")
    assert recidive.bloque_antirobot and recidive.exclusion
    assert recidive.exclu_jusqu_au and recidive.reessayer_apres > 6 * 86400
    assert route.call_count == 2
    # Nouveau processus, même cache : l'exclusion tient, sans requête, et survit à une purge complète.
    app.cache.purge()
    autre = _defi(_client(app, exclusion_ttl=7 * 86400), API + "?vue=3")
    assert autre.coupe_circuit and autre.exclusion and route.call_count == 2
    assert "exclu" in str(autre) and "cache_purger" in str(autre)
    # Levée explicite : l'historique reste (archives_service), l'exclusion part.
    app.cache.purge("coupe_circuit")
    assert app.cache.defi_antirobot(HOTE)["exclu_jusqu_a"] is None
    assert app.cache.defi_antirobot(HOTE)["detections"] == 2
    _defi(client, API + "?vue=4")
    assert route.call_count == 3
    # Oubli complet : catégorie dédiée.
    assert app.cache.purge("antirobot") == 1
    assert app.cache.defi_antirobot(HOTE) is None


@respx.mock
def test_exclusion_desactivee(app):
    respx.get(API).mock(return_value=httpx.Response(503, **DEFI))
    client = _client(app, exclusion_ttl=0)
    _defi(client)
    app.cache.purge("coupe_circuit")
    assert not _defi(client, API + "?vue=2").exclusion
    assert app.cache.defi_antirobot(HOTE)["detections"] == 2


@respx.mock
def test_defi_ancien_ne_vaut_pas_recidive(app):
    respx.get(API).mock(return_value=httpx.Response(503, **DEFI))
    horloge = [time.time() - 40 * 86400]
    client = _client(app, exclusion_ttl=7 * 86400, horloge_murale=lambda: horloge[0])
    _defi(client)
    app.cache.purge("coupe_circuit")
    horloge[0] = time.time()
    assert not _defi(client, API + "?vue=2").exclusion


def test_configuration_exclusion(monkeypatch):
    assert load_config().exclusion_antirobot == 7 * 86400
    monkeypatch.setenv("GENEALOGISTE_EXCLUSION_ANTIROBOT", "0")
    assert load_config().exclusion_antirobot == 0


def test_app_transmet_exclusion(app):
    assert app.http.exclusion_ttl == app.config.exclusion_antirobot


# ---------------------------------------------------------------- statut structuré et suite sans navigateur

def test_enveloppe_suite_sans_navigateur(app):
    exc = SourceError("défi", 403, bloque_antirobot=True, protection="Cloudflare", url=API,
                      date_detection="2026-11-18T10:00:00+00:00", exclusion=True,
                      exclu_jusqu_au="2026-11-25T10:00:00+00:00")
    out = error_envelope(app.sctx, "archives", "naviguer", {"source": SOURCE}, exc)
    assert out["statut"] == "bloque_antirobot" and out["service"] == "AD59"
    assert out["exclusion"] is True and out["exclu_jusqu_au"] == "2026-11-25T10:00:00+00:00"
    suite = out["suite"]
    assert suite["relancer"] is False and suite["navigateur_serveur"] is False
    assert suite["ouvrir"] == API
    assert {"source_collee", "piece_archiver", "media_enregistrer"} <= set(suite["reprise"])
    assert "cache_purger" in suite["lever"]
    assert "enquete_noter" in suite["tache"]


def test_enveloppe_ordinaire_sans_suite(app):
    out = error_envelope(app.sctx, "archives", "naviguer", {}, SourceError("indisponible", 500))
    assert "suite" not in out and "exclusion" not in out


# ---------------------------------------------------------------- tâche manuelle dans l'enquête

def _taches(eid):
    return server.enquete_etat(eid)["taches_manuelles"]


def test_blocage_inscrit_tache_manuelle_dans_enquete(app):
    eid = server.enquete_ouvrir("Défi depuis le VPS")["id"]
    with respx.mock as routes:
        route = routes.get(API).mock(return_value=httpx.Response(503, **DEFI))
        premier = server.archives_naviguer(SOURCE, page=1, pas=3, enquete=eid)
        second = server.archive_image(SOURCE, page=1, enquete=eid)  # coupe-circuit, même hôte
    assert route.call_count == 1
    assert premier["statut"] == second["statut"] == "bloque_antirobot"
    taches = _taches(eid)
    assert len(taches) == 1  # même URL bloquée : une seule tâche
    t = taches[0]
    assert t["statut"] == "a_faire" and t["service"] == "AD59" and t["url"] == premier["url"]
    assert "Cloudflare" in t["description"]
    assert premier["tache_manuelle"]["enquete"] == eid and premier["tache_manuelle"]["id"] == t["id"]
    assert second["tache_manuelle"]["id"] == t["id"]
    reprise = server.enquete_reprendre(eid)
    assert [x["id"] for x in reprise["taches_manuelles"]] == [t["id"]]


def test_blocage_outil_generique_inscrit_tache(app):  # enveloppe générique (ServeurMCP.mesure)
    eid = server.enquete_ouvrir("Défi Gallica")["id"]
    with respx.mock(assert_all_called=False) as routes:
        routes.route().mock(return_value=_reponse(403, CF_1020))
        res = server.gallica_texte(ark="ark:/12148/bpt6k123456", page=1, enquete=eid)
    assert res["statut"] == "bloque_antirobot", res
    assert res["tache_manuelle"]["enquete"] == eid
    assert len(_taches(eid)) == 1


def test_blocage_sans_enquete_ne_cree_rien(app):
    with respx.mock as routes:
        routes.get(API).mock(return_value=httpx.Response(503, **DEFI))
        res = server.archives_naviguer(SOURCE, page=1, pas=3)
    assert "enquete" not in res["tache_manuelle"]
    assert server.enquete_etat()["enquetes"] == []


# ---------------------------------------------------------------- défi observé dans archives_service

def test_archives_service_expose_defi_observe(app):
    assert "defi_observe" not in server.archives_service(code="AD59")
    with respx.mock as routes:
        routes.get(API).mock(return_value=httpx.Response(503, **DEFI))
        server.archives_naviguer(SOURCE, page=1, pas=3)
    obs = server.archives_service(code="AD59")["defi_observe"]
    assert obs["hote"] == HOTE and obs["protection"] == "Cloudflare" and obs["detections"] == 1
    assert obs["derniere_detection"].endswith("+00:00")
    assert "installation" in obs["note"]
